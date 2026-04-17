# GitHub Codebase Intelligence — Full Implementation Plan

> Production-grade pivot from FinIntel. Single-owner, public + private repos.
> Deploy: Render (backend) + Vercel (frontend). Local dev + push simultaneously.

---

## 0. Pick a Name

Choose one — rest of the plan uses **`CodeNexus`** as the working name:

| Name | Meaning | Vibe |
|---|---|---|
| **CodeNexus** | Connection point in your codebase | Technical, descriptive |
| **Argus** | All-seeing Greek giant | Mythological, unique, memorable |
| **Cortex** | Brain cortex — deep intelligence | Modern, clean, AI-forward |
| **Synapse** | Neural connection between code | Implies linking ideas + code |
| **RepoMind** | Your codebase, understood | Literal, clear product purpose |

> Once you choose, do a find-replace of `codenexus` / `CodeNexus` across the plan.

---

## 1. Finalized Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Repo access | Public + Private | Single-owner PAT with `repo` scope covers both |
| Auth model | GitHub PAT (fine-grained) | No OAuth, no GitHub App — single owner, no user login system |
| Languages (Tier 1) | Python, JavaScript, TypeScript, Go | Covers ~85% of all repos you'd realistically use |
| Languages (Tier 2) | Rust, Java, C# | Generic heuristic chunker (no AST), still indexed |
| Embedding model | BGE-M3 (local) / Jina AI API (prod) | BGE-M3 locally; Render free tier can't hold 3GB model — swap to Jina API in prod |
| Agent LLM | Groq LLaMA-3.3-70B → 8B → Mixtral | Same fallback chain as FinIntel |
| Generation LLM | Gemini 2.5 Flash → chain | Same as FinIntel |
| Vector DB | Qdrant Cloud | Same service, new collection schema |
| Knowledge Graph | Neo4j AuraDB | Same service, entirely new schema |
| Webhooks | Yes, Day 1 | Render gives persistent public URL; include from start |
| Deployment | Render (backend) + Vercel (frontend) | Backend: Docker container. Frontend: Next.js auto-deploy |
| Containerization | Dockerfile from Day 1 | Production mindset throughout |
| Secret scanning | Yes, pre-embed filter | Before any chunk is embedded |
| CI/CD | GitHub Actions | Auto-deploy on push to `main` |

---

## 2. ⚠️ Critical Infrastructure Note: Embeddings on Render

**Problem:** BGE-M3 requires ~3GB RAM. Render's free tier = 512MB.

**Solution (two-track):**
```
Local Dev:   Use BGE-M3 on your GPU (same as FinIntel, zero change)
Production:  Use Jina AI Embeddings API (free tier: 1M tokens/month)
             OR upgrade Render to Starter ($7/mo, 2GB) — still tight
             OR use `all-MiniLM-L6-v2` (22MB, good for code+prose, fast)
```

**Design decision:** Abstract the embedder behind an interface. Swap model by changing one env var `EMBEDDING_BACKEND=local|jina|openai`. This is why the `embedder.py` is the only file that differs between local and production.

---

## 3. Full System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         USER (Browser)                                         │
│              Next.js 16 — Vercel                                               │
│   ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐                 │
│   │  Chat Page   │  │  Repo Manager   │  │  Graph Explorer  │                 │
│   │ (ask questions)│ │ (add/remove repos)│ │ (visualize KG)  │                 │
│   └──────────────┘  └─────────────────┘  └──────────────────┘                 │
└─────────────────────────────────┬──────────────────────────────────────────────┘
                                  │ HTTPS
                                  ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend — Render (Docker)                          │
│                                                                                │
│  ┌─────────────────────┐   ┌───────────────────────────────────────────────┐  │
│  │  API Routes          │   │  Webhook Receiver                             │  │
│  │  POST /api/v1/query  │   │  POST /api/v1/webhook/github                 │  │
│  │  POST /api/v1/agent  │   │  HMAC-SHA256 verification                    │  │
│  │  POST /api/v1/ingest │   │  BackgroundTask: re-index changed files      │  │
│  │  GET  /api/v1/repos  │   └───────────────────────────────────────────────┘  │
│  └──────────┬───────────┘                                                      │
│             │                                                                  │
│  ┌──────────▼──────────────────────────────────────────────────────────────┐  │
│  │                      Ingestion Pipeline                                  │  │
│  │  github_client.py → file_router.py → parsers/ → chunkers/ →            │  │
│  │  secret_scanner.py → embedder.py → qdrant_store.py → graph_builder.py  │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌──────────────────────┐   ┌────────────────────────────────────────────── ┐ │
│  │  RAG Pipeline         │   │  LangGraph Supervisor Agent                  │ │
│  │  (retrieval/)         │   │  (agents/)                                   │ │
│  │  Hybrid Qdrant search │   │  7 tools: search_code, get_file_content,     │ │
│  │  Code-aware context   │   │  search_issues, get_call_graph,              │ │
│  │  Gemini generation    │   │  get_file_history, get_dependencies,         │ │
│  └──────────────────────┘   │  calculate_math                              │ │
│                              └──────────────────────────────────────────────┘ │
└──────────┬──────────────────────────────────┬──────────────────────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────────┐    ┌─────────────────────────────────────────────────┐
│   Qdrant Cloud           │    │   Neo4j AuraDB                                  │
│   Collection: codenexus_kb│   │   Nodes: Repo, File, Function, Class,           │
│   Dense: 1024-dim BGE-M3 │   │   Module, Issue, PR, Commit, Contributor,       │
│   Sparse: BM25-hash      │   │   Dependency, Label                             │
│   Filters: repo, lang,   │   │   Edges: IMPORTS, CALLS, DEFINED_IN,            │
│   file_path, chunk_type  │   │   MODIFIES, CLOSES, TOUCHES, AUTHORED,          │
└─────────────────────────┘    │   DEPENDS_ON, INHERITS, METHOD_OF               │
                               └─────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         GitHub API (REST v3 + GraphQL v4)                    │
│   Authenticated: PAT with scopes: repo, read:org, read:user                  │
│   Rate limit: 5000 req/hr (REST) | 500k points/hr (GraphQL)                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Directory Structure (Full Scaffold)

```
CodeNexus/
├── .env                          # All secrets (gitignored)
├── .env.example                  # Template (committed)
├── .gitignore
├── Dockerfile                    # Backend container
├── docker-compose.yml            # Local dev orchestration
├── render.yaml                   # Render infra-as-code
├── README.md
├── architecture.md               # (this plan, after build)
│
├── backend/
│   ├── main.py                   # FastAPI app, CORS, routes
│   ├── requirements.txt
│   ├── Dockerfile                # (same as root or symlink)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py             # /query, /agent_query, /ingest, /repos
│   │   └── webhook.py            # POST /webhook/github — NEW
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py            # Pydantic: all request/response models
│   │
│   ├── ingestion/                # OFFLINE + WEBHOOK path
│   │   ├── __init__.py
│   │   ├── pipeline.py           # Master orchestrator
│   │   ├── github_client.py      # GitHub REST API wrapper — NEW
│   │   ├── file_router.py        # Decide parser per filetype — NEW
│   │   ├── secret_scanner.py     # Pre-embed secret detection — NEW
│   │   └── parsers/              # NEW directory
│   │       ├── __init__.py
│   │       ├── code_parser.py    # tree-sitter for .py/.js/.ts/.go
│   │       ├── markdown_parser.py# Ported from FinIntel (BS4)
│   │       ├── issue_parser.py   # GitHub Issues JSON → prose
│   │       ├── pr_parser.py      # PR description + diff → text
│   │       └── config_parser.py  # YAML/JSON/TOML → flattened text
│   │
│   ├── chunkers/                 # NEW directory
│   │   ├── __init__.py
│   │   ├── ast_chunker.py        # tree-sitter AST → function/class chunks
│   │   └── prose_chunker.py      # Ported from FinIntel (parent-child)
│   │
│   ├── indexing/
│   │   ├── __init__.py
│   │   ├── embedder.py           # UPDATED: local BGE-M3 OR Jina API
│   │   ├── qdrant_store.py       # UPDATED: new collection schema + filters
│   │   └── graph_builder/        # NEW directory (replaces graph_extractor.py)
│   │       ├── __init__.py
│   │       ├── static_analyzer.py# AST → import/call graphs (no LLM)
│   │       ├── git_graph.py      # PRs/Issues/Commits → Neo4j
│   │       └── neo4j_manager.py  # Neo4j connection + MERGE helpers
│   │
│   ├── retrieval/
│   │   ├── __init__.py
│   │   └── rag_pipeline.py       # UPDATED: code-aware retrieval + context
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── supervisor.py         # UPDATED: code-focused system prompt
│   │   └── tools.py              # UPDATED: 7 tools (was 3)
│   │
│   └── core/                     # NEW: shared utilities
│       ├── __init__.py
│       ├── config.py             # Centralized settings (Pydantic BaseSettings)
│       ├── rate_limiter.py       # GitHub API rate limit manager
│       └── logger.py             # Structured logging
│
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── vercel.json               # Vercel config
    └── src/
        ├── app/
        │   ├── layout.tsx        # UPDATED: new nav items
        │   ├── page.tsx          # Chat page (mostly same)
        │   ├── repos/
        │   │   └── page.tsx      # NEW: Repo manager
        │   ├── graph/
        │   │   └── page.tsx      # NEW: Graph explorer
        │   ├── globals.css
        │   └── layout.css        # UPDATED: new sidebar items
        │
        └── components/
            ├── ChatInterface.tsx      # UPDATED: repo selector added
            ├── ChatInterface.module.css
            ├── MessageBubble.tsx      # Ported, unchanged
            ├── MessageBubble.module.css
            ├── SourceBadge.tsx        # UPDATED: shows file path + line
            ├── SourceBadge.module.css
            ├── RepoCard.tsx           # NEW: repo status card
            ├── RepoCard.module.css
            ├── RepoManager.tsx        # NEW: add/remove repos UI
            ├── RepoManager.module.css
            ├── GraphExplorer.tsx      # NEW: simple graph visualization
            └── GraphExplorer.module.css
```

---

## 5. Qdrant Collection Schema

```
Collection: "codenexus_kb"

Vector Config:
  "dense":  size=1024, distance=COSINE  (BGE-M3 / Jina 1024-dim)
  "sparse": SparseVectorParams, on_disk=False

Point Payload Schema:
{
  // Identity
  "repo":           str,     // "owner/repo-name"
  "file_path":      str,     // "src/auth/jwt.py"
  "language":       str,     // "python" | "javascript" | "markdown" | "issue" | "pr"
  "source_type":    str,     // "code" | "docs" | "issue" | "pr" | "config"

  // Code-specific (null for non-code)
  "chunk_type":     str,     // "function" | "class" | "module" | "prose" | "parent"
  "function_name":  str,     // "calculate_emi" (null if not a function chunk)
  "class_name":     str,     // "AuthManager" (null if not a class chunk)
  "start_line":     int,     // 45
  "end_line":       int,     // 87
  "signature":      str,     // "def calculate_emi(principal, rate, tenure) -> float:"

  // For parent-child (prose docs, issues)
  "parent_id":      str,     // uuid (null for code chunks)
  "parent_text":    str,     // full parent context
  "child_text":     str,     // precise matched segment

  // Temporal
  "last_modified":  str,     // ISO 8601 timestamp
  "indexed_at":     str,     // ISO 8601 timestamp

  // Issue/PR specific
  "issue_number":   int,     // 142 (null for non-issue)
  "pr_number":      int,     // 89 (null for non-PR)
  "state":          str,     // "open" | "closed" | "merged"
  "labels":         list,    // ["bug", "enhancement"]
}
```

---

## 6. Neo4j Graph Schema

### Nodes

```cypher
(:Repository  {id, owner, name, full_name, language, description,
               stars, is_private, default_branch, indexed_at})

(:File        {id, path, repo, language, size,
               last_modified, num_lines})

(:Function    {id, name, qualified_name, file_path, repo,
               start_line, end_line, signature, docstring,
               is_async, is_method})

(:Class       {id, name, file_path, repo,
               start_line, end_line, bases})

(:Module      {id, name, repo, file_path})
               // Python package / JS module grouping

(:Issue       {id, number, title, body_preview, state,
               created_at, closed_at, repo})

(:PullRequest {id, number, title, state,
               created_at, merged_at, repo,
               base_branch, head_branch})

(:Commit      {id, sha, message, author_login,
               author_email, timestamp, repo})

(:Contributor {id, login, name, email})

(:Dependency  {id, name, version, ecosystem})
               // "requests", "2.32", "pip"
               // "react", "19.2.4", "npm"

(:Label       {id, name, color, repo})
```

### Edges

```cypher
// Code structure
(File)-[:BELONGS_TO]->(Repository)
(Function)-[:DEFINED_IN]->(File)
(Class)-[:DEFINED_IN]->(File)
(Function)-[:METHOD_OF]->(Class)
(Class)-[:INHERITS]->(Class)

// Code relationships — from static analysis (no LLM)
(File)-[:IMPORTS]->(File)
(Function)-[:CALLS]->(Function)
(Module)-[:CONTAINS]->(File)

// Dependencies — from package manifests
(Repository)-[:DEPENDS_ON]->(Dependency)

// Git history
(PR)-[:MODIFIES]->(File)
(PR)-[:CLOSES]->(Issue)
(Commit)-[:PART_OF]->(PR)
(Commit)-[:TOUCHES]->(File)
(Contributor)-[:AUTHORED]->(Commit)
(Contributor)-[:OPENED]->(PR)
(Contributor)-[:OPENED]->(Issue)

// Metadata
(Issue)-[:LABELED]->(Label)
(PR)-[:LABELED]->(Label)
```

---

## 7. GitHub PAT Setup

**Scopes needed (fine-grained PAT — preferred over classic):**
```
Repository permissions:
  Contents:       Read       (read file content)
  Issues:         Read       (read issues)
  Pull requests:  Read       (read PRs)
  Metadata:       Read       (always required)
  Webhooks:       Read+Write (register webhook programmatically)

Account permissions:
  (none needed for single-owner)
```

**How to create:**
1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Resource owner: your account
3. Repository access: All repositories (or specific)
4. Set scopes above
5. Copy token → `GITHUB_PAT=ghp_xxxx` in `.env`

---

## 8. Environment Variables (Complete)

```bash
# ──────────────────────────────────────────────
# GitHub
# ──────────────────────────────────────────────
GITHUB_PAT=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_WEBHOOK_SECRET=your-random-32-char-string  # openssl rand -hex 16

# ──────────────────────────────────────────────
# Qdrant Cloud
# ──────────────────────────────────────────────
QDRANT_URL=https://your-cluster-id.cloud.qdrant.io:6333
QDRANT_API_KEY=your-qdrant-api-key

# ──────────────────────────────────────────────
# Neo4j AuraDB
# ──────────────────────────────────────────────
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-neo4j-password

# ──────────────────────────────────────────────
# LLMs
# ──────────────────────────────────────────────
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GEMINI_API_KEY=AIzaxxxxxxxxxxx

# ──────────────────────────────────────────────
# Embedding Backend
# ──────────────────────────────────────────────
EMBEDDING_BACKEND=local        # "local" (BGE-M3 GPU) | "jina" | "openai"
JINA_API_KEY=jina_xxxxxxxxxxxx  # only needed if EMBEDDING_BACKEND=jina

# ──────────────────────────────────────────────
# App Config
# ──────────────────────────────────────────────
ENVIRONMENT=development        # "development" | "production"
LOG_LEVEL=INFO
BACKEND_URL=https://your-app.onrender.com  # set in prod
```

**Frontend (.env.local):**
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000   # local dev
# On Vercel, set to: https://your-app.onrender.com
```

---

## 9. Agent Tools — Full Specification

All 7 tools. The agent picks the right combination per query.

### Tool 1: `search_code`
```python
@tool
def search_code(query: str, repo: str = None, language: str = None) -> str:
    """
    Semantic search over the indexed codebase.
    Use this to find functions, classes, or code patterns based on a description.
    Examples: "JWT token verification", "database connection pool", "retry logic"
    
    Optional filters:
      repo: "owner/repo-name" to limit to one repo
      language: "python", "javascript", "typescript", "go"
    """
    # Hybrid Qdrant search with payload filters
    # Returns: function signatures, file paths, line ranges, code snippets
```

### Tool 2: `get_file_content`
```python
@tool
def get_file_content(repo: str, file_path: str) -> str:
    """
    Fetch the complete content of a specific file.
    Use this when you know exactly which file you need to read in full.
    Example: repo="owner/myapp", file_path="src/auth/jwt.py"
    """
    # Try Qdrant payload first (reassemble from chunks)
    # Fallback: GitHub API GET /repos/{owner}/{repo}/contents/{path}
```

### Tool 3: `search_issues`
```python
@tool
def search_issues(query: str, repo: str = None, state: str = "all") -> str:
    """
    Search GitHub Issues and Pull Requests by semantic similarity.
    Use this to find what bugs were reported, what features were requested,
    or what changes were discussed.
    
    state: "open" | "closed" | "merged" | "all"
    """
    # Qdrant search filtered by source_type="issue" or "pr"
```

### Tool 4: `get_call_graph`
```python
@tool
def get_call_graph(function_name: str, repo: str = None) -> str:
    """
    Find what a function calls AND what functions call it.
    Use this to understand the impact of changing a function,
    or to trace the execution path.
    Example: function_name="verify_token", repo="owner/myapp"
    """
    # Neo4j: (f:Function)-[:CALLS]->(target) WHERE f.name CONTAINS $name
    # AND:   (caller:Function)-[:CALLS]->(f)
```

### Tool 5: `get_file_history`
```python
@tool
def get_file_history(file_path: str, repo: str = None) -> str:
    """
    Find the Git history of a file: which PRs modified it, which issues they closed,
    and who made the changes. Use this to understand WHY code exists.
    Example: file_path="src/auth/jwt.py"
    """
    # Neo4j traversal:
    # (pr:PR)-[:MODIFIES]->(f:File {path: $path})
    # (pr)-[:CLOSES]->(issue:Issue)
    # (contributor)-[:OPENED]->(pr)
```

### Tool 6: `get_dependencies`
```python
@tool
def get_dependencies(module_name: str, repo: str = None) -> str:
    """
    Find what a module/file imports AND what imports it (reverse dependencies).
    Use this to understand coupling, or assess blast radius of a change.
    Example: module_name="auth/jwt"
    """
    # Neo4j: (f:File)-[:IMPORTS]->(target) WHERE f.path CONTAINS $module
    # AND:   (importer:File)-[:IMPORTS]->(f)
    # ALSO:  (repo:Repository)-[:DEPENDS_ON]->(dep:Dependency) for third-party
```

### Tool 7: `calculate_math`
```python
@tool
def calculate_math(expression: str) -> str:
    """
    Evaluate a mathematical expression safely.
    Use for counting, percentages, ratios, or any arithmetic.
    Same as before — AST-based safe eval.
    """
    # Ported directly from FinIntel — no changes needed
```

---

## 10. Ingestion Pipeline — Full Detail

### Phase 1: Repository Crawl

```
Input: "owner/repo-name"
  │
  ├── GET /repos/{owner}/{repo}
  │     → store: name, description, language, stars, is_private, default_branch
  │     → MERGE (:Repository) in Neo4j
  │
  ├── GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
  │     → full file tree as flat list with paths + SHAs
  │
  ├── FILTER files:
  │     Include extensions:
  │       Code:   .py, .js, .ts, .jsx, .tsx, .go, .rs, .java, .cs, .rb, .php
  │       Docs:   .md, .rst, .txt, .mdx
  │       Config: .yaml, .yml, .json, .toml, .ini, .env.example
  │     
  │     Exclude patterns:
  │       node_modules/**, .git/**, dist/**, build/**, __pycache__/**
  │       *.min.js, *.min.css, *.pb.go, *_generated.*, *.lock (package-lock.json etc)
  │       Files > 500KB (too large to embed meaningfully)
  │
  ├── Fetch manifests first (for dependency graph):
  │     requirements.txt, pyproject.toml, package.json,
  │     go.mod, Cargo.toml, pom.xml, build.gradle
  │     → parse → MERGE (:Dependency) + (:Repository)-[:DEPENDS_ON]->(:Dependency)
  │
  └── Return: list of {path, sha, language, size}
```

### Phase 2: File Fetching + Routing

```python
# file_router.py
def route_file(path: str, content: str) -> dict:
    ext = pathlib.Path(path).suffix.lower()
    
    if ext in ['.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.cs']:
        return code_parser.parse(content, language=detect_language(ext))
    
    elif ext in ['.md', '.rst', '.mdx', '.txt']:
        return markdown_parser.parse(content)
    
    elif ext in ['.yaml', '.yml', '.toml', '.ini']:
        return config_parser.parse(content, path=path)
    
    elif ext == '.json' and not is_generated_json(content):
        return config_parser.parse(content, path=path)
    
    else:
        return generic_parser.parse(content)  # line-based heuristic
```

### Phase 3: Secret Scanning

```python
# secret_scanner.py — runs BEFORE embedding, AFTER parsing

SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}',
    r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?.{8,}',
    r'ghp_[A-Za-z0-9]{36}',          # GitHub PAT
    r'sk-[A-Za-z0-9]{48}',            # OpenAI key
    r'AIza[A-Za-z0-9_\-]{35}',        # Google API key
    r'(?i)aws_access_key_id\s*=\s*[A-Z0-9]{20}',
    # ... more patterns
]

def scan_chunk(text: str) -> bool:
    """Returns True if chunk contains a suspected secret."""
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

# If secret found: LOG WARNING + SKIP chunk (don't embed, don't store)
```

### Phase 4: AST Chunking (Code Files)

```python
# chunkers/ast_chunker.py

# Dependencies: tree-sitter, tree-sitter-python, tree-sitter-javascript,
#               tree-sitter-typescript, tree-sitter-go

class ASTChunker:
    """
    Strategy:
    - Unit = one function or one class method (NEVER split mid-function)
    - Parent = entire file content OR entire class
    - Child = the function/method body
    - If function > 150 lines: use docstring + signature as child, full body as parent
    - If file has no functions (pure script): fall back to prose_chunker
    """
    
    def chunk_python(self, source: str, file_path: str) -> tuple[list, list]:
        tree = python_parser.parse(bytes(source, 'utf8'))
        # Walk AST: find function_definition, class_definition nodes
        # Extract: name, start_line, end_line, docstring, signature
        # Parent = class body, Child = method body
        # Standalone functions = their own parent+child pair
    
    def chunk_javascript(self, source: str, file_path: str):
        # function declaraions, arrow functions assigned to const,
        # class methods — similar strategy
    
    def chunk_typescript(self, source: str, file_path: str):
        # Same as JS but includes type extraction from signatures
    
    def chunk_go(self, source: str, file_path: str):
        # func declarations, method receivers
    
    def chunk_generic(self, source: str, file_path: str):
        # No AST: split at every N lines (100-line windows, 20-line overlap)
        # For languages without tree-sitter grammar
```

### Phase 5: Embedding

```python
# indexing/embedder.py (UPDATED)

class CodeNexusEmbedder:
    def __init__(self):
        backend = os.getenv("EMBEDDING_BACKEND", "local")
        
        if backend == "local":
            self._embed_fn = self._embed_local   # BGE-M3 on GPU
        elif backend == "jina":
            self._embed_fn = self._embed_jina    # Jina AI API
        # Future: elif backend == "openai": ...
    
    def embed_text(self, texts: list[str]) -> list[dict]:
        """Returns [{dense: [...], sparse: {...}}] for each text."""
        return self._embed_fn(texts)
    
    # Sparse vector computation is ALWAYS local (fast, no API needed)
    # Dense vector is backend-dependent
```

**Jina AI Embeddings API (production):**
```
Model: jina-embeddings-v3
Dimensions: 1024 (same as BGE-M3)
Free tier: 1M tokens/month
Endpoint: POST https://api.jina.ai/v1/embeddings
No GPU required on server
```

> Zero Qdrant changes needed — same 1024-dim dense, same collection. Switch is transparent.

### Phase 6: Static Analysis → Neo4j

```python
# indexing/graph_builder/static_analyzer.py
# NO LLM CALLS — pure AST analysis

class StaticAnalyzer:
    def extract_python_imports(self, source: str, file_path: str) -> list[tuple]:
        """
        import os              → (file_path, "os", "stdlib")
        from .auth import jwt  → (file_path, "auth/jwt.py", "local")
        import requests        → (file_path, "requests", "third-party")
        Returns: [(source_file, target_module, import_type)]
        """
    
    def extract_python_calls(self, source: str, file_path: str) -> list[tuple]:
        """
        Finds function call sites and maps caller → callee.
        Returns: [(caller_function, callee_function, file_path)]
        """
    
    # Similar for JS/TS (require(), import from), Go (import blocks)
    
    def push_to_neo4j(self, driver, repo: str, analysis_results: dict):
        # MERGE File nodes, MERGE IMPORTS relationships
        # MERGE Function nodes, MERGE CALLS relationships
```

### Phase 7: Git Graph → Neo4j

```python
# indexing/graph_builder/git_graph.py

class GitGraphBuilder:
    def ingest_issues(self, repo_full_name: str):
        # GET /repos/{owner}/{repo}/issues?state=all&per_page=100
        # Paginate through all issues
        # MERGE (:Issue), (:Label), (:Contributor)
        # CREATE (:Contributor)-[:OPENED]->(:Issue)
        # CREATE (:Issue)-[:LABELED]->(:Label)
    
    def ingest_pull_requests(self, repo_full_name: str):
        # GET /repos/{owner}/{repo}/pulls?state=all&per_page=100
        # GET /repos/{owner}/{repo}/pulls/{number}/files → list of changed files
        # MERGE (:PR), (:File)
        # CREATE (:PR)-[:MODIFIES]->(:File)
        # If PR body mentions "closes #N" or "fixes #N" → CREATE (:PR)-[:CLOSES]->(:Issue)
    
    def ingest_commits(self, repo_full_name: str, limit: int = 500):
        # GET /repos/{owner}/{repo}/commits?per_page=100
        # Only recent 500 commits (adjustable)
        # GET /repos/{owner}/{repo}/commits/{sha} → files changed
        # MERGE (:Commit), link to (:Contributor), (:File)
```

---

## 11. Webhook Pipeline

### Registration

```python
# At first ingest of a repo: register the webhook automatically
# POST /repos/{owner}/{repo}/hooks
{
    "name": "web",
    "active": True,
    "events": ["push", "pull_request", "issues"],
    "config": {
        "url": f"{BACKEND_URL}/api/v1/webhook/github",
        "content_type": "json",
        "secret": GITHUB_WEBHOOK_SECRET,
        "insecure_ssl": "0"
    }
}
```

### Receiver (`api/webhook.py`)

```python
@router.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    # 1. Read raw body (BEFORE parsing — needed for HMAC)
    body = await request.body()
    
    # 2. Verify HMAC-SHA256 signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # 3. Parse event
    event_type = request.headers.get("X-GitHub-Event")
    payload = json.loads(body)
    
    # 4. Dispatch to background task (respond 200 immediately to GitHub)
    if event_type == "push":
        background_tasks.add_task(handle_push_event, payload)
    elif event_type == "pull_request":
        background_tasks.add_task(handle_pr_event, payload)
    elif event_type == "issues":
        background_tasks.add_task(handle_issue_event, payload)
    
    return {"status": "accepted"}


async def handle_push_event(payload: dict):
    repo = payload["repository"]["full_name"]
    commits = payload["commits"]
    
    added_files = []
    modified_files = []
    removed_files = []
    
    for commit in commits:
        added_files.extend(commit.get("added", []))
        modified_files.extend(commit.get("modified", []))
        removed_files.extend(commit.get("removed", []))
    
    # Re-index added + modified files
    for file_path in set(added_files + modified_files):
        # Fetch content → parse → chunk → re-embed → upsert Qdrant
        # (upsert is idempotent — overwrites by file_path + repo filter)
        await reindex_file(repo, file_path)
    
    # Delete removed files from Qdrant
    for file_path in removed_files:
        await delete_file_from_index(repo, file_path)
    
    # Update Neo4j import graph for changed files
    await update_file_graph(repo, set(added_files + modified_files))
```

---

## 12. RAG Pipeline (Updated for Code)

Key differences from FinIntel:

```python
class RAGPipeline:
    def query(self, user_query: str, repo: str = None, top_k: int = 7):
        # Step 1: Embed (same hybrid)
        
        # Step 2: Hybrid search WITH payload filter
        filter_conditions = []
        if repo:
            filter_conditions.append(
                FieldCondition(key="repo", match=MatchValue(value=repo))
            )
        
        # Step 3: Code-aware context assembly
        # For code chunks: include signature + surrounding context
        # For function chunks: prepend "In file {path}, function {name}:"
        # For issue chunks: prepend "Issue #{number} ({state}):"
        
        context_blocks = []
        for point in results.points:
            if point.payload["source_type"] == "code":
                header = f"[{point.payload['repo']}] {point.payload['file_path']}"
                if point.payload.get('function_name'):
                    header += f" → {point.payload['function_name']}()"
                    header += f" (lines {point.payload['start_line']}-{point.payload['end_line']})"
                context_blocks.append(f"```{point.payload['language']}\n# {header}\n{text}\n```")
            else:
                # prose/docs: standard [Source: X] format
                ...
        
        # Step 4: Code-aware system prompt for Gemini
        # Include instruction: cite file paths and line numbers in answer
```

---

## 13. Agent System Prompt (Updated)

```python
SUPERVISOR_PROMPT = """You are CodeNexus, an elite autonomous Code Intelligence Agent.
You have deep access to the indexed codebase through 6 specialized tools.

TOOLS:
1. search_code(query, repo, language) — Find functions/classes by what they DO
2. get_file_content(repo, file_path) — Read a specific file in full
3. search_issues(query, repo, state) — Search bugs, features, discussions in Issues/PRs
4. get_call_graph(function_name, repo) — Who calls this? What does it call?
5. get_file_history(file_path, repo) — Which PRs changed this? What issues triggered it?
6. get_dependencies(module_name, repo) — What does this import? What imports it?
7. calculate_math(expression) — Arithmetic (line counts, ratios, etc.)

REASONING RULES:
- NEVER guess code behavior. Always use tools to find actual source.
- For "how does X work?" → search_code first, then get_file_content if needed
- For "why was X changed?" → get_file_history + search_issues
- For "what breaks if I change X?" → get_call_graph + get_dependencies
- Chain tools logically. Read the results carefully before calling next tool.
- Max 3 tool calls before synthesizing. Don't loop.
- Always cite: file path, function name, line numbers in your answer.
- Format code in markdown code blocks with the correct language tag.
"""
```

---

## 14. API Endpoints (Complete)

```
GET  /health                         Health check
GET  /api/v1/repos                   List indexed repos + status
POST /api/v1/ingest                  Trigger ingestion for a repo
DELETE /api/v1/repos/{owner}/{repo}  Remove repo from index
POST /api/v1/query                   Direct RAG (no agent)
POST /api/v1/agent_query             Agentic query (primary)
GET  /api/v1/graph/stats             Neo4j graph statistics
POST /api/v1/webhook/github          GitHub webhook receiver
```

### Schemas

```python
class IngestRequest(BaseModel):
    repo: str           # "owner/repo-name"
    branch: str = "main"
    include_issues: bool = True
    include_prs: bool = True
    include_commits: bool = True
    max_commits: int = 500

class QueryRequest(BaseModel):
    query: str
    repo: str | None = None      # filter to specific repo
    language: str | None = None  # filter to specific language
    top_k: int = 7
    history: list[HistoryMessage] | None = None

class SourceChunk(BaseModel):
    text: str
    source: str          # repo name
    file_path: str       # src/auth/jwt.py
    language: str
    function_name: str | None
    start_line: int | None
    end_line: int | None
    score: float
    source_type: str     # "code" | "docs" | "issue" | "pr"

class RepoStatus(BaseModel):
    repo: str
    is_private: bool
    file_count: int
    chunk_count: int
    last_indexed: str
    languages: list[str]
    webhook_active: bool
```

---

## 15. Frontend Pages

### Page 1: Chat (existing, updated)

- Dropdown to select which indexed repo(s) to query (or "All repos")
- Source badges show: `filename:line_range` instead of just filename
- Language icon on source badge (🐍 Python, 🟨 JS, etc.)
- Code blocks in AI responses are syntax-highlighted
- Same conversation history + multi-turn support

### Page 2: Repo Manager (new)

```
┌─────────────────────────────────────────────────────────────┐
│  Indexed Repositories                              [+ Add]  │
├─────────────────────────────────────────────────────────────┤
│  owner/myapp          Python  •  1,247 chunks  •  ✅ Live  │
│  owner/frontend       TS      •    892 chunks  •  ✅ Live  │
│  owner/private-lib    Go      •    456 chunks  •  ✅ Live  │
└─────────────────────────────────────────────────────────────┘
```

- Add repo: type `owner/repo` → POST `/api/v1/ingest` → progress indicator
- Remove repo: DELETE + confirm dialog
- Re-index: force re-ingest button per repo
- Status: chunk count, last indexed timestamp, webhook status

### Page 3: Graph Explorer (new, simple)

- Neo4j stats: node count by type, edge count by type
- Simple text search: type a file/function name → show its graph neighbors
- No heavy D3/vis.js for now — just a structured list view
- "What imports auth?" → call `get_dependencies` via API → show result as tree

---

## 16. Dockerfile (Production)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps for tree-sitter + PyMuPDF
RUN apt-get update && apt-get install -y \
    gcc g++ build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download BGE-M3 model (only if EMBEDDING_BACKEND=local)
# For Render production, use EMBEDDING_BACKEND=jina — skip this
ARG PRELOAD_MODEL=false
RUN if [ "$PRELOAD_MODEL" = "true" ]; then \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"; \
    fi

# Copy application code
COPY backend/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

---

## 17. render.yaml (Infrastructure as Code)

```yaml
services:
  - type: web
    name: codenexus-api
    env: docker
    dockerfilePath: ./Dockerfile
    dockerContext: .
    plan: starter          # 2GB RAM — required for Jina API path (no model in memory)
                           # Upgrade to standard ($25) if running local BGE-M3
    envVars:
      - key: EMBEDDING_BACKEND
        value: jina        # Use Jina API in production
      - key: ENVIRONMENT
        value: production
      - key: GITHUB_PAT
        sync: false        # Set manually in Render dashboard
      - key: GITHUB_WEBHOOK_SECRET
        sync: false
      - key: QDRANT_URL
        sync: false
      - key: QDRANT_API_KEY
        sync: false
      - key: NEO4J_URI
        sync: false
      - key: NEO4J_USERNAME
        sync: false
      - key: NEO4J_PASSWORD
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: GEMINI_API_KEY
        sync: false
      - key: JINA_API_KEY
        sync: false
    healthCheckPath: /health
    autoDeploy: true       # Deploy on every push to main
```

---

## 18. vercel.json

```json
{
  "framework": "nextjs",
  "buildCommand": "npm run build",
  "outputDirectory": ".next",
  "env": {
    "NEXT_PUBLIC_API_URL": "https://codenexus-api.onrender.com"
  },
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "DENY" }
      ]
    }
  ]
}
```

---

## 19. GitHub Actions CI/CD

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r backend/requirements.txt
      - run: python -m pytest backend/ -v --tb=short
        env:
          EMBEDDING_BACKEND: local   # use mock in tests

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd frontend && npm ci && npm run lint

  # Render and Vercel auto-deploy on push to main
  # No explicit deploy steps needed — just protect main branch
```

---

## 20. Python Requirements

```txt
# Web framework
fastapi==0.115.12
uvicorn[standard]==0.34.2
pydantic==2.11.1
pydantic-settings==2.7.0      # NEW: for BaseSettings config

# GitHub
PyGithub==2.6.0               # NEW: GitHub API wrapper

# Vector DB
qdrant-client==1.13.3

# Knowledge Graph
neo4j==5.28.1

# LLMs
google-genai==1.14.0
langchain-core==0.3.51
langchain-groq==0.3.2
langgraph==0.4.1

# Embedding (local)
sentence-transformers==4.1.0
torch==2.6.0                  # GPU support

# AST / Code Parsing  (NEW)
tree-sitter==0.24.0
tree-sitter-python==0.24.0
tree-sitter-javascript==0.24.0
tree-sitter-typescript==0.24.2
tree-sitter-go==0.24.0

# Document Parsing
beautifulsoup4==4.13.4
pymupdf==1.25.5               # Keep: for any PDF docs in repos

# Utilities
python-dotenv==1.1.0
requests==2.32.3
httpx==0.28.1                 # NEW: async HTTP for Jina API
```

---

## 21. Build Order (Phased)

### Phase 0 — Project Scaffold (Day 1)
- [ ] Create `CodeNexus/` folder on Desktop
- [ ] `git init` + create GitHub repo
- [ ] Copy over `architecture.md`, `README.md`
- [ ] Set up `.env`, `.env.example`, `.gitignore`
- [ ] Initialize Python venv + install requirements
- [ ] Initialize Next.js in `frontend/`
- [ ] Write `Dockerfile` + `render.yaml`
- [ ] Set up Qdrant Cloud new collection `codenexus_kb`
- [ ] Set up Neo4j AuraDB (can reuse existing instance, different database)
- [ ] Generate GitHub PAT, register in `.env`

### Phase 1 — Core Ingestion (Days 2–4)
- [ ] `core/config.py` — Pydantic BaseSettings
- [ ] `core/rate_limiter.py` — GitHub rate limit handler
- [ ] `ingestion/github_client.py` — repo crawler, file fetcher
- [ ] `ingestion/secret_scanner.py` — regex-based
- [ ] `ingestion/parsers/markdown_parser.py` — port from FinIntel
- [ ] `ingestion/parsers/issue_parser.py`
- [ ] `ingestion/parsers/pr_parser.py`
- [ ] `ingestion/parsers/config_parser.py`
- [ ] `ingestion/file_router.py`
- [ ] **TEST**: ingest a small public repo (no code parsing yet, just docs/issues)

### Phase 2 — AST Chunking (Days 4–6)
- [ ] `chunkers/prose_chunker.py` — port from FinIntel
- [ ] `chunkers/ast_chunker.py` — tree-sitter for Python first
- [ ] Add JavaScript/TypeScript AST chunking
- [ ] Add Go AST chunking
- [ ] Generic fallback chunker
- [ ] `ingestion/parsers/code_parser.py` — wire up tree-sitter parsers
- [ ] **TEST**: chunk a Python repo, verify function-level splits

### Phase 3 — Indexing (Days 6–8)
- [ ] `indexing/embedder.py` — local BGE-M3 + Jina API path
- [ ] `indexing/qdrant_store.py` — updated collection + upsert with new payload schema
- [ ] `indexing/graph_builder/static_analyzer.py` — import + call extraction
- [ ] `indexing/graph_builder/git_graph.py` — PRs, Issues, Commits → Neo4j
- [ ] `indexing/graph_builder/neo4j_manager.py` — MERGE helpers
- [ ] `ingestion/pipeline.py` — wire all phases together
- [ ] **TEST**: full ingest of a small repo, verify Qdrant + Neo4j populated

### Phase 4 — API + Retrieval (Days 8–10)
- [ ] `models/schemas.py` — all new schemas
- [ ] `retrieval/rag_pipeline.py` — updated hybrid search + code-aware context
- [ ] `api/routes.py` — all endpoints
- [ ] `api/webhook.py` — GitHub webhook receiver + background tasks
- [ ] `main.py` — FastAPI app setup
- [ ] **TEST**: query endpoint working end-to-end

### Phase 5 — Agent (Days 10–12)
- [ ] `agents/tools.py` — all 7 tools
- [ ] `agents/supervisor.py` — updated prompt + LLM chain
- [ ] **TEST**: multi-tool agent queries (code + KG + issues)

### Phase 6 — Frontend (Days 12–15)
- [ ] Port layout + sidebar (update nav items)
- [ ] Update `ChatInterface.tsx` — add repo filter dropdown
- [ ] Update `SourceBadge.tsx` — file path + line range
- [ ] Update `MessageBubble.tsx` — syntax highlighting for code blocks
- [ ] Build `RepoManager.tsx` + page
- [ ] Build `GraphExplorer.tsx` + page (simple list view)
- [ ] **TEST**: full user flow — add repo, ingest, ask questions

### Phase 7 — Production Deploy (Days 15–17)
- [ ] Deploy backend to Render (Docker, starter plan)
- [ ] Set all env vars in Render dashboard
- [ ] Deploy frontend to Vercel
- [ ] Register webhooks for test repos
- [ ] Test webhook delivery (push a commit, verify re-index)
- [ ] Set up GitHub Actions CI/CD
- [ ] End-to-end production smoke test

---

## 22. New Repo Setup Commands

Run these to create the project from scratch:

```powershell
# 1. Create project folder
cd C:\Users\SAKET\Desktop
mkdir CodeNexus
cd CodeNexus

# 2. Git init
git init
git branch -M main

# 3. Python backend setup
mkdir backend
cd backend
python -m venv .venv
.\.venv\Scripts\activate
# Create requirements.txt (see Phase 20 above)
pip install -r requirements.txt
cd ..

# 4. Next.js frontend setup
cd frontend  # (created by npx)
npx -y create-next-app@latest . --typescript --no-tailwind --app --src-dir --no-eslint
cd ..

# 5. Create GitHub repo and push
# (Do this on GitHub.com first — create "CodeNexus" repo)
git remote add origin https://github.com/YOURUSERNAME/CodeNexus.git
git add .
git commit -m "Initial scaffold: CodeNexus GitHub Intelligence Platform"
git push -u origin main
```

---

## 23. Key Differences Summary (FinIntel → CodeNexus)

| Component | FinIntel | CodeNexus | Status |
|---|---|---|---|
| `scraper.py` | requests + BeautifulSoup | `github_client.py` (PyGithub) | **Rewrite** |
| `parser.py` | PDF + HTML | Multi-type router | **Rewrite** |
| `chunker.py` | Character-boundary prose | AST-aware + prose | **Major addition** |
| `embedder.py` | BGE-M3 only | BGE-M3 local + Jina API | **Updated** |
| `qdrant_store.py` | Basic hybrid | Hybrid + payload filters | **Updated** |
| `graph_extractor.py` | Gemini LLM extraction | Static analysis (no LLM) | **Replace entirely** |
| Neo4j schema | Finance entities | Code dependency graph | **Replace entirely** |
| `rag_pipeline.py` | Prose RAG | Code-aware RAG | **Updated** |
| `agents/tools.py` | 3 tools | 7 tools | **Major extension** |
| `agents/supervisor.py` | Finance prompt | Code intelligence prompt | **Updated** |
| `api/routes.py` | 2 endpoints | 6 endpoints | **Extended** |
| `api/webhook.py` | Doesn't exist | GitHub webhook receiver | **New** |
| `models/schemas.py` | Basic | Extended with code fields | **Updated** |
| `core/` | Doesn't exist | Config, rate limiter, logger | **New** |
| `Dockerfile` | Doesn't exist | Full container | **New** |
| `render.yaml` | Doesn't exist | Infra-as-code | **New** |
| GitHub Actions | Doesn't exist | CI/CD pipeline | **New** |
| Frontend: Chat | Basic chat | + repo filter, code rendering | **Updated** |
| Frontend: RepoManager | Doesn't exist | Add/remove repos | **New** |
| Frontend: GraphExplorer | Doesn't exist | KG visualization | **New** |
| `secret_scanner.py` | Doesn't exist | Pre-embed filter | **New** |

---

## 24. Open Questions Before We Start

> These don't block Phase 0 but need decisions before Phase 2:

1. **Syntax highlighting in frontend**: Use `react-syntax-highlighter` (simple) or `shiki` (VS Code themes, heavier)? I'd recommend `shiki` for production quality.

2. **Graph Explorer depth**: Simple list view (text-based, quick) or actual node graph (D3.js/Cytoscape.js, takes 2-3 extra days)?

3. **Webhook registration**: Auto-register when user adds a repo (requires webhook write scope in PAT), or manual instruction shown to user? Auto is better UX.

4. **Rate limit strategy for large repos**: A repo with 5000 files touches the GitHub API heavily. Do you want a queue (pause + resume) or just let it run with sleep() between batches?

5. **For production embedding — Jina AI or upgrade Render?** Jina free tier may be enough for your usage. Render Starter ($7/mo) won't hold BGE-M3.

---

*CodeNexus Implementation Plan — v1.0 | 2026-04-16*
