# Cortex — Step-by-Step Implementation Tracker

> **Status:** 🟢 Phase 0 complete
> **Last Updated:** 2026-04-17
> **Total Phases:** 7 | **Completed:** 1/7

---

## Legend

- [ ] Task not started
- [x] Task completed
- ⏳ In progress
- ✅ Phase verified and passing
- ❌ Phase verification failed
- 🔧 Known issue / needs fix

---

## Pre-Flight Checklist (Before Writing Any Code)

### Accounts & API Keys

| Service | Status | Free Tier Limit | Notes |
|---|---|---|---|
| [x] GitHub PAT (Fine-Grained) | 🟢 | 5000 req/hr | Added to local `.env`; scopes should include Contents(R), Issues(R), PRs(R), Metadata(R), Webhooks(RW) |
| [x] Gemini API Key (Google AI Studio) | 🟢 | 15 RPM generation | Added to local `.env`; rotate before production because it was shared in chat |
| [ ] Jina AI API Key | 🔴 | Depends on plan/free tier | Still needed for real embeddings via `jina-embeddings-v3`; can mock until Phase 3 if needed |
| [x] Groq API Key | 🟢 | ~6000 TPM on 70B | Added to local `.env`; rotate before production because it was shared in chat |
| [x] Qdrant Cloud Account | 🟢 | 1GB free cluster | Existing cluster verified; use collection `cortex_kb` (1024-dim dense for Jina) |
| [x] Neo4j AuraDB | 🟢 | 50K nodes, 175K relationships | Existing database verified; safe to clear for Cortex when graph phase starts |
| [ ] Vercel Account | 🔴 | Hobby tier (free) | For frontend deployment |
| [ ] Render Account | 🔴 | Free tier (512MB, spins down) | For backend Docker deployment |

### Local Dev Requirements

| Tool | Required Version | Check Command |
|---|---|---|
| [x] Python | 3.12+ | `python --version` → 3.13.5 |
| [x] Node.js | 20+ | `node --version` → 24.13.0 |
| [x] npm | 10+ | `npm --version` → 11.6.2 |
| [x] Git | Any | `git --version` → 2.52.0.windows.1 |
| [ ] VS Code | Any | — |

---

## Phase 0 — Project Scaffold & Wiring

> **Goal:** Empty project that runs. FastAPI returns `/health`. Next.js shows a page. Git is initialized.
> **Estimated Time:** 2-3 hours

### 0.1 Create Project Structure

- [x] Use current project folder `C:\Users\SAKET\Desktop\cortex\`
- [x] `git init` + `git branch -M main`
- [x] Create GitHub repo `Cortex` on github.com
- [x] `git remote add origin` + initial push (remote configured; scaffold push still pending)
- [x] Create `.gitignore` (Python + Node + .env)
- [x] Create `.env.example` with all variable names (no values)
- [x] Create `.env` with real values (gitignored; Jina key still pending)

### 0.2 Backend Scaffold

- [x] Create `backend/` directory
- [x] Create Python virtual environment (`python -m venv .venv`)
- [x] Create `backend/requirements.txt` with ALL dependencies
- [x] `pip install -r requirements.txt`
- [x] Create directory structure:
  ```
  backend/
  ├── main.py
  ├── requirements.txt
  ├── api/
  │   ├── __init__.py
  │   ├── routes.py
  │   └── webhook.py
  ├── models/
  │   ├── __init__.py
  │   └── schemas.py
  ├── ingestion/
  │   ├── __init__.py
  │   ├── pipeline.py
  │   ├── github_client.py
  │   ├── file_router.py
  │   ├── secret_scanner.py
  │   └── parsers/
  │       ├── __init__.py
  │       ├── code_parser.py
  │       ├── markdown_parser.py
  │       ├── issue_parser.py
  │       ├── pr_parser.py
  │       └── config_parser.py
  ├── chunkers/
  │   ├── __init__.py
  │   ├── ast_chunker.py
  │   └── prose_chunker.py
  ├── indexing/
  │   ├── __init__.py
  │   ├── embedder.py
  │   ├── qdrant_store.py
  │   └── graph_builder/
  │       ├── __init__.py
  │       ├── static_analyzer.py
  │       ├── git_graph.py
  │       └── neo4j_manager.py
  ├── retrieval/
  │   ├── __init__.py
  │   └── rag_pipeline.py
  ├── agents/
  │   ├── __init__.py
  │   ├── supervisor.py
  │   └── tools.py
  └── core/
      ├── __init__.py
      ├── config.py
      ├── rate_limiter.py
      └── logger.py
  ```
- [x] Implement `core/config.py` — Pydantic `BaseSettings` loading all env vars
- [x] Implement `core/logger.py` — structured logging (JSON format)
- [x] Implement `main.py` — FastAPI app with CORS, `/health` endpoint
- [x] Implement `models/schemas.py` — all Pydantic request/response models (stubs)
- [x] Implement `api/routes.py` — all route stubs (return 501 "Not Implemented")

### 0.3 Frontend Scaffold

- [x] Run `npx -y create-next-app@latest ./frontend --typescript --app --src-dir --no-tailwind --no-eslint`
- [x] Clean up boilerplate (remove default Next.js content)
- [x] Create page stubs:
  - [x] `src/app/page.tsx` — Chat page (placeholder)
  - [x] `src/app/repos/page.tsx` — Repo Manager (placeholder)
  - [x] `src/app/graph/page.tsx` — Graph Explorer (placeholder)
- [x] Create `src/app/layout.tsx` — sidebar nav with 3 links
- [x] Install frontend dependencies:
  - [x] `shiki` (syntax highlighting)
  - [x] `react-force-graph-2d` (graph visualization)
- [x] Create `vercel.json` config

### 0.4 Docker

- [x] Create `Dockerfile` for backend
- [x] Create `docker-compose.yml` for local dev (backend only; frontend runs via `npm run dev`)
- [x] Test: `docker build` succeeds

### 0.5 Phase 0 Verification ✅ / ❌

```
TEST 1: Backend starts
  Command: cd backend && python -m uvicorn main:app --reload
  Expected: Server running on http://localhost:8000
  Result: [x] Passed

TEST 2: Health endpoint
  Command: curl http://localhost:8000/health
  Expected: {"status": "healthy"}
  Result: [x] Passed — returned {"status":"healthy"}

TEST 3: Frontend starts
  Command: cd frontend && npm run dev
  Expected: App running on http://localhost:3000
  Result: [x] Passed — dev server started on http://127.0.0.1:3000

TEST 4: Frontend shows 3 nav links
  Expected: Chat, Repos, Graph links visible in sidebar
  Result: [x] Passed — Chat, Repos, Graph present

TEST 5: Docker builds
  Command: docker build -t cortex-backend .
  Expected: Build succeeds
  Result: [x] Passed — Docker image `cortex-backend` built successfully

TEST 6: Git push
  Command: git push origin main
  Expected: Code on GitHub
  Result: [ ] Pending — waiting for approval/input before pushing scaffold
```

**Phase 0 Notes:**
```
- Current workspace is `C:\Users\SAKET\Desktop\cortex`, so Phase 0 was scaffolded in-place instead of creating a duplicate `Desktop\Cortex` folder.
- Embeddings are standardized on Jina AI: `EMBEDDING_BACKEND=jina`, `EMBEDDING_MODEL=jina-embeddings-v3`, `EMBEDDING_DIMENSIONS=1024`. Jina key is still pending.
- Qdrant connectivity verified against the existing free cluster. Upgraded `qdrant-client` to `1.17.1` to match the cluster server version.
- Neo4j connectivity verified against the existing AuraDB database.
- User approved deleting existing Qdrant/Neo4j data when Cortex initialization reaches those phases.
- Python local version is 3.13.5. Tree-sitter grammar pins were updated to Python 3.13-compatible versions.
- Frontend Google font imports were removed because they require network during `next build`; local-first font stacks are used instead.
- Docker build passed after Docker Desktop Linux engine was started.
- GitHub PAT is present in `.env` and detected by backend config.
- `.env` is complete for Phase 1; Jina key is still pending for real embeddings in Phase 3.

```

---

## Phase 1 — GitHub Ingestion (No Embedding Yet)

> **Goal:** Paste a repo URL → backend crawls it → prints list of files + their parsed content to console.
> **Estimated Time:** 4-6 hours
> **Depends on:** Phase 0 ✅

### 1.1 GitHub API Client

- [ ] Implement `ingestion/github_client.py`:
  - [ ] `fetch_repo_metadata(owner, repo)` → name, description, language, stars, is_private
  - [ ] `fetch_file_tree(owner, repo, branch)` → flat list of all files with paths + SHAs
  - [ ] `fetch_file_content(owner, repo, path, sha)` → raw text content (base64 decoded)
  - [ ] `fetch_issues(owner, repo, state="all")` → paginated list of all issues
  - [ ] `fetch_pull_requests(owner, repo, state="all")` → paginated list of all PRs
  - [ ] `fetch_pr_files(owner, repo, pr_number)` → list of files modified by a PR
  - [ ] `fetch_commits(owner, repo, limit=500)` → recent commits
- [ ] Implement `core/rate_limiter.py`:
  - [ ] Track `X-RateLimit-Remaining` header from every GitHub response
  - [ ] If remaining < 100: `asyncio.sleep()` until reset time
  - [ ] Log warnings when approaching limits

### 1.2 File Filtering Logic

- [ ] In `github_client.py` or `file_router.py`, implement file filtering:
  - [ ] **Include** extensions: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.go`, `.rs`, `.java`, `.cs`, `.rb`, `.php`, `.md`, `.rst`, `.txt`, `.mdx`, `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.env.example`
  - [ ] **Exclude** patterns: `node_modules/`, `.git/`, `dist/`, `build/`, `__pycache__/`, `*.min.js`, `*.min.css`, `*.pb.go`, `*_generated.*`, `*.lock`, `package-lock.json`, `yarn.lock`
  - [ ] **Exclude** files > 500KB
  - [ ] **Exclude** binary files (images, compiled, fonts)

### 1.3 Secret Scanner

- [ ] Implement `ingestion/secret_scanner.py`:
  - [ ] Regex patterns for: GitHub PATs (`ghp_`), OpenAI keys (`sk-`), Google API keys (`AIza`), AWS keys, generic `password=`, `secret=`, `api_key=` patterns
  - [ ] `scan_text(text: str) -> bool` — returns True if secrets detected
  - [ ] `redact_text(text: str) -> str` — replaces detected secrets with `[REDACTED]`
  - [ ] Decision: **SKIP** chunks with secrets (don't embed them at all) + log warning

### 1.4 Parsers

- [ ] Implement `parsers/markdown_parser.py`:
  - [ ] Strip HTML tags, normalize whitespace
  - [ ] Preserve code blocks, headers, and list structure
  - [ ] Port logic from FinIntel's `parser.py` (HTML path)
- [ ] Implement `parsers/issue_parser.py`:
  - [ ] Convert GitHub issue JSON → readable prose:
    ```
    Issue #42: "Login fails on Safari" (state: open, labels: [bug, auth])
    Opened by: alice on 2026-03-15
    Body: When clicking the login button on Safari 17...
    ```
- [ ] Implement `parsers/pr_parser.py`:
  - [ ] Convert PR JSON → readable prose (title, body, state, base/head branch)
  - [ ] Include list of modified files
- [ ] Implement `parsers/config_parser.py`:
  - [ ] YAML/JSON/TOML → flattened key-value text representation
  - [ ] Example: `database.host = "localhost"`, `database.port = 5432`
- [ ] Implement `parsers/code_parser.py`:
  - [ ] For now: return raw source code as-is (AST chunking comes in Phase 2)
  - [ ] Attach metadata: language, file_path, line_count
- [ ] Implement `ingestion/file_router.py`:
  - [ ] Route each file to the correct parser based on extension
  - [ ] Return standardized `ParsedFile` object: `{path, language, source_type, content, metadata}`

### 1.5 Wire Up Route

- [ ] Implement `POST /api/v1/ingest` in `api/routes.py`:
  - [ ] Accept `IngestRequest(repo: str, branch: str = "main")`
  - [ ] Call `github_client.fetch_file_tree()`
  - [ ] Filter files
  - [ ] Fetch content for each file
  - [ ] Run through `file_router`
  - [ ] Run through `secret_scanner`
  - [ ] For now: just log/print the parsed output (no embedding yet)
  - [ ] Return: `{"status": "success", "files_parsed": 142, "files_skipped": 38, "secrets_found": 2}`

### 1.6 Phase 1 Verification ✅ / ❌

```
TEST 1: Ingest a small public repo
  Command: POST http://localhost:8000/api/v1/ingest
           Body: {"repo": "octocat/hello-world"}
  Expected: 200 OK, files_parsed > 0
  Result: [ ]

TEST 2: Ingest YOUR OWN repo (private or public)
  Command: POST with your own repo name
  Expected: 200 OK, private repo content accessible
  Result: [ ]

TEST 3: Secret scanner catches a test secret
  Create a test file with "GITHUB_PAT=ghp_abc123def456ghi789"
  Expected: File skipped or redacted, warning logged
  Result: [ ]

TEST 4: Large file exclusion
  Expected: Files > 500KB are skipped, count shown in response
  Result: [ ]

TEST 5: Rate limiter doesn't crash on 50+ file repo
  Command: Ingest a repo with 50+ files
  Expected: Completes without 403/429 error
  Result: [ ]
```

**Phase 1 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 2 — AST Chunking

> **Goal:** Code files are split into function/class-level chunks. Prose files use parent-child chunking.
> **Estimated Time:** 6-8 hours (tree-sitter is fiddly)
> **Depends on:** Phase 1 ✅

### 2.1 Prose Chunker (Port from FinIntel)

- [ ] Implement `chunkers/prose_chunker.py`:
  - [ ] Port FinIntel's parent-child chunking strategy
  - [ ] Parent chunk: ~3200 chars (full section)
  - [ ] Child chunks: ~800 chars (precise segments)
  - [ ] Each child stores reference to parent_id and parent_text
  - [ ] Used for: `.md`, `.rst`, `.txt`, issues, PRs, config files

### 2.2 AST Chunker (New — Core Innovation)

- [ ] Implement `chunkers/ast_chunker.py`:
  - [ ] Initialize tree-sitter parsers for Python, JavaScript, TypeScript, Go
  - [ ] **Python chunking:**
    - [ ] Walk AST → find `function_definition` and `class_definition` nodes
    - [ ] Extract: name, start_line, end_line, docstring, full signature
    - [ ] Standalone functions → one chunk each
    - [ ] Class methods → one chunk each, with `class_name` metadata
    - [ ] Module-level code (imports, globals) → one "module_header" chunk
  - [ ] **JavaScript/TypeScript chunking:**
    - [ ] `function_declaration`, `arrow_function` assigned to `const/let`
    - [ ] `class_declaration` → `method_definition` children
    - [ ] `export default` and named exports
  - [ ] **Go chunking:**
    - [ ] `function_declaration` (standalone funcs)
    - [ ] `method_declaration` (receiver methods)
    - [ ] `type_declaration` for structs
  - [ ] **Generic fallback (no AST):**
    - [ ] For unsupported languages: split at every 100 lines with 20-line overlap
    - [ ] Still captures file_path and language metadata
  - [ ] **Chunk metadata** (attached to every chunk):
    ```python
    {
        "chunk_type": "function" | "class" | "method" | "module_header" | "prose",
        "function_name": "verify_token",
        "class_name": "AuthManager",        # null if standalone function
        "signature": "def verify_token(token: str, secret: str) -> dict:",
        "start_line": 45,
        "end_line": 87,
        "file_path": "src/auth/jwt.py",
        "language": "python"
    }
    ```
  - [ ] **Size guardrails:**
    - [ ] If a single function > 150 lines: use signature + docstring as "child", full body as "parent"
    - [ ] If a file has NO functions (pure script): fall back to prose_chunker

### 2.3 Integrate into Pipeline

- [ ] Update `ingestion/pipeline.py`:
  - [ ] After parsing: route to correct chunker based on `source_type`
  - [ ] Code files → `ast_chunker`
  - [ ] Prose/issues/PRs/configs → `prose_chunker`
  - [ ] Log: chunk count per file, average chunk size

### 2.4 Phase 2 Verification ✅ / ❌

```
TEST 1: Python file chunks correctly
  Input: A Python file with 3 functions and 1 class (2 methods)
  Expected: 6 chunks (3 standalone + 2 methods + 1 module_header)
  Result: [ ]

TEST 2: Function boundaries are intact
  Expected: No chunk starts or ends mid-function
  Verify: Print first/last line of each chunk — should be def/return
  Result: [ ]

TEST 3: Metadata is populated
  Expected: Every code chunk has function_name, start_line, end_line, signature
  Result: [ ]

TEST 4: JavaScript arrow functions captured
  Input: const handler = async (req, res) => { ... }
  Expected: Captured as one chunk with name "handler"
  Result: [ ]

TEST 5: Markdown file uses prose chunker
  Input: A README.md with 5 sections
  Expected: Parent-child chunks, NOT AST chunks
  Result: [ ]

TEST 6: Generic fallback works
  Input: A .rs or .java file (no tree-sitter grammar yet)
  Expected: Falls back to 100-line window chunks
  Result: [ ]

TEST 7: Giant function handling
  Input: A function > 150 lines
  Expected: Summary chunk (signature + docstring) + full body as parent
  Result: [ ]
```

**Phase 2 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 3 — Embedding & Vector Storage (Qdrant)

> **Goal:** Chunks are embedded via Jina AI and stored in Qdrant Cloud with full payload metadata.
> **Estimated Time:** 4-5 hours
> **Depends on:** Phase 2 ✅

### 3.1 Embedder

- [ ] Implement `indexing/embedder.py`:
  - [ ] **Dense embeddings** via Jina AI `jina-embeddings-v3`:
    ```python
    import httpx

    response = httpx.post(
        "https://api.jina.ai/v1/embeddings",
        headers={"Authorization": f"Bearer {JINA_API_KEY}"},
        json={"model": "jina-embeddings-v3", "input": texts},
    )
    # Returns 1024-dim vectors
    ```
  - [ ] **Sparse embeddings** via local BM25 token hashing (port from FinIntel)
  - [ ] Batch processing: embed up to 20 texts per API call
  - [ ] Rate limit handling: if Jina returns 429, backoff + retry

### 3.2 Qdrant Store

- [ ] Implement `indexing/qdrant_store.py`:
  - [ ] Create collection `cortex_kb` if not exists:
    - Dense: 1024-dim, COSINE distance
    - Sparse: unnamed sparse vector
  - [ ] `upsert_chunks(chunks: list[Chunk])`:
    - Generate deterministic UUID from `repo + file_path + chunk_type + function_name + start_line`
    - This ensures re-ingestion OVERWRITES instead of duplicating
  - [ ] Full payload schema per point:
    ```python
    {
        "repo": "owner/repo-name",
        "file_path": "src/auth/jwt.py",
        "language": "python",
        "source_type": "code",                  # code | docs | issue | pr | config
        "chunk_type": "function",               # function | class | method | module_header | prose | parent
        "function_name": "verify_token",        # null for non-code
        "class_name": "AuthManager",            # null if standalone
        "signature": "def verify_token(...)",   # null for non-code
        "start_line": 45,                       # null for non-code
        "end_line": 87,                         # null for non-code
        "parent_id": null,                      # for prose parent-child
        "parent_text": null,                    # for prose parent-child
        "child_text": "the actual chunk text",
        "issue_number": null,                   # for issues
        "pr_number": null,                      # for PRs
        "state": null,                          # open | closed | merged
        "labels": [],                           # for issues/PRs
        "last_modified": "2026-04-17T...",
        "indexed_at": "2026-04-17T..."
    }
    ```
  - [ ] `delete_by_file(repo, file_path)` — remove all chunks for a specific file
  - [ ] `delete_by_repo(repo)` — remove all chunks for entire repo
  - [ ] `search(query_dense, query_sparse, filters, top_k)` — hybrid RRF search

### 3.3 Wire into Pipeline

- [ ] Update `ingestion/pipeline.py`:
  - [ ] After chunking → embed all chunks → upsert to Qdrant
  - [ ] Add progress logging: "Embedded 142/500 chunks..."
  - [ ] Make ingestion a `BackgroundTask` (don't block the API response)

### 3.4 Phase 3 Verification ✅ / ❌

```
TEST 1: Embeddings are 1024-dimensional
  Expected: len(embedding) == 1024 for every chunk
  Result: [ ]

TEST 2: Qdrant collection created successfully
  Check: Qdrant Cloud dashboard shows "cortex_kb" collection
  Result: [ ]

TEST 3: Points have correct payload
  Command: Qdrant dashboard → inspect any point → check all payload fields present
  Result: [ ]

TEST 4: Re-ingestion overwrites (no duplicates)
  Command: Ingest same repo twice
  Expected: Point count stays the same (not doubled)
  Result: [ ]

TEST 5: Delete by repo works
  Command: DELETE /api/v1/repos/owner/repo
  Expected: All points for that repo removed from Qdrant
  Result: [ ]

TEST 6: Background ingestion
  Command: POST /api/v1/ingest → check response time
  Expected: Response returns immediately (<2 seconds), ingestion continues in background
  Result: [ ]

TEST 7: Hybrid search returns results
  Command: Call search() with a natural language query
  Expected: Returns ranked results with scores
  Result: [ ]
```

**Phase 3 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 4 — Knowledge Graph (Neo4j)

> **Goal:** Code imports, function calls, Git history (Issues, PRs, Commits) are mapped into Neo4j. No LLM needed.
> **Estimated Time:** 6-8 hours
> **Depends on:** Phase 1 ✅ (does NOT depend on Phase 3; can be built in parallel)

### 4.1 Neo4j Manager

- [ ] Implement `indexing/graph_builder/neo4j_manager.py`:
  - [ ] Connection singleton using `neo4j.GraphDatabase.driver()`
  - [ ] Helper: `run_query(cypher, params)` with error handling
  - [ ] Helper: `merge_node(label, properties, unique_key)`
  - [ ] Helper: `merge_relationship(from_label, from_key, to_label, to_key, rel_type, properties)`
  - [ ] Constraint creation on startup:
    ```cypher
    CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.full_name IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (i:Issue) REQUIRE i.id IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (p:PullRequest) REQUIRE p.id IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (co:Commit) REQUIRE co.sha IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (ct:Contributor) REQUIRE ct.login IS UNIQUE
    CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dependency) REQUIRE d.id IS UNIQUE
    ```

### 4.2 Static Analyzer (Code → Graph, No LLM)

- [ ] Implement `indexing/graph_builder/static_analyzer.py`:
  - [ ] **Python import extraction:**
    - [ ] Use `ast.parse()` (stdlib) — no tree-sitter needed for this
    - [ ] `import os` → edge: File -[:IMPORTS]-> Module("os", type="stdlib")
    - [ ] `from .auth import jwt` → edge: File -[:IMPORTS]-> File("auth/jwt.py", type="local")
    - [ ] `import requests` → edge: File -[:IMPORTS]-> Module("requests", type="third-party")
  - [ ] **Python function call extraction:**
    - [ ] Walk AST `ast.Call` nodes
    - [ ] Map caller function → callee function
    - [ ] Edge: Function -[:CALLS]-> Function
  - [ ] **Python class hierarchy:**
    - [ ] `class Admin(User):` → Class("Admin") -[:INHERITS]-> Class("User")
    - [ ] Methods → Function -[:METHOD_OF]-> Class
  - [ ] **JavaScript/TypeScript import extraction:**
    - [ ] `import { foo } from './bar'` → File -[:IMPORTS]-> File
    - [ ] `require('./bar')` → File -[:IMPORTS]-> File
    - [ ] Use regex or tree-sitter (simpler than full AST for just imports)
  - [ ] **Dependency manifest parsing:**
    - [ ] `requirements.txt` → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="pip")
    - [ ] `package.json` dependencies → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="npm")
    - [ ] `go.mod` → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="go")

### 4.3 Git Graph Builder

- [ ] Implement `indexing/graph_builder/git_graph.py`:
  - [ ] `ingest_issues(repo)`:
    - [ ] Fetch all issues via `github_client`
    - [ ] MERGE (:Issue) with: number, title, body_preview (first 500 chars), state, created_at
    - [ ] MERGE (:Contributor) for issue author
    - [ ] CREATE (:Contributor)-[:OPENED]->(:Issue)
    - [ ] Parse labels → MERGE (:Label), CREATE (:Issue)-[:LABELED]->(:Label)
  - [ ] `ingest_pull_requests(repo)`:
    - [ ] Fetch all PRs + files changed per PR
    - [ ] MERGE (:PullRequest) with: number, title, state, base_branch, head_branch
    - [ ] CREATE (:PullRequest)-[:MODIFIES]->(:File)
    - [ ] Parse body for "closes #N" / "fixes #N" → CREATE (:PullRequest)-[:CLOSES]->(:Issue)
    - [ ] MERGE (:Contributor) for PR author → CREATE (:Contributor)-[:OPENED]->(:PullRequest)
  - [ ] `ingest_commits(repo, limit=500)`:
    - [ ] Fetch recent commits + files touched per commit
    - [ ] MERGE (:Commit) with: sha, message, timestamp
    - [ ] CREATE (:Commit)-[:TOUCHES]->(:File)
    - [ ] MERGE (:Contributor) for commit author → CREATE (:Contributor)-[:AUTHORED]->(:Commit)
    - [ ] If commit is part of a PR: CREATE (:Commit)-[:PART_OF]->(:PullRequest)

### 4.4 Wire into Pipeline

- [ ] Update `ingestion/pipeline.py`:
  - [ ] After file parsing: run `static_analyzer` for each code file
  - [ ] After GitHub metadata fetch: run `git_graph.ingest_issues()`, `ingest_pull_requests()`, `ingest_commits()`
  - [ ] All Neo4j operations run in parallel with Qdrant embedding (they are independent)

### 4.5 Phase 4 Verification ✅ / ❌

```
TEST 1: Repository node exists
  Cypher: MATCH (r:Repository) RETURN r
  Expected: Your ingested repo appears
  Result: [ ]

TEST 2: File nodes populated
  Cypher: MATCH (f:File) WHERE f.repo = "owner/repo" RETURN count(f)
  Expected: Count matches number of indexed files
  Result: [ ]

TEST 3: Import edges correct
  Cypher: MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.path, b.path LIMIT 10
  Expected: Imports match actual source code
  Result: [ ]

TEST 4: Function-level call edges
  Cypher: MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name, b.name LIMIT 10
  Expected: Call relationships are reasonable
  Result: [ ]

TEST 5: Issues ingested
  Cypher: MATCH (i:Issue) WHERE i.repo = "owner/repo" RETURN count(i)
  Expected: Count matches GitHub issue count
  Result: [ ]

TEST 6: PR → File modification edges
  Cypher: MATCH (pr:PullRequest)-[:MODIFIES]->(f:File) RETURN pr.number, f.path LIMIT 10
  Expected: PR file changes match GitHub
  Result: [ ]

TEST 7: Dependency nodes
  Cypher: MATCH (r:Repository)-[:DEPENDS_ON]->(d:Dependency) RETURN d.name, d.version LIMIT 10
  Expected: Matches requirements.txt / package.json contents
  Result: [ ]
```

**Phase 4 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 5 — RAG Pipeline & Agent

> **Goal:** User asks a question → Agent picks tools → retrieves from Qdrant + Neo4j → Gemini generates answer.
> **Estimated Time:** 6-8 hours
> **Depends on:** Phase 3 ✅ AND Phase 4 ✅

### 5.1 RAG Pipeline (Direct Query)

- [ ] Implement `retrieval/rag_pipeline.py`:
  - [ ] `query(user_query, repo=None, language=None, top_k=7)`:
    - [ ] Embed user query with Jina AI
    - [ ] Compute sparse vector (BM25 hash)
    - [ ] Hybrid search in Qdrant with payload filters (repo, language)
    - [ ] **Code-aware context assembly:**
      - Code chunks: wrap in ```language code block, prepend file path + function name
      - Issue chunks: prepend "Issue #N (state):"
      - PR chunks: prepend "PR #N (state):"
    - [ ] Send assembled context + user query to Gemini 2.5 Flash
    - [ ] System prompt instructs: cite file paths, function names, and line numbers
    - [ ] Return: answer text + list of source chunks with metadata

### 5.2 Agent Tools (7 Tools)

- [ ] Implement `agents/tools.py`:
  - [ ] **Tool 1: `search_code(query, repo?, language?)`**
    - Hybrid Qdrant search, filtered by repo/language
    - Returns top 5 results (truncated to prevent token bloat)
    - Format: `[file_path:start_line-end_line] function_name — first 200 chars of code`
  - [ ] **Tool 2: `get_file_content(repo, file_path, mode="outline"|"full")`**
    - `outline`: returns class names, function signatures, docstrings only
    - `full`: returns entire file content (with 500-line cap)
    - Try Qdrant first (reassemble from chunks), fallback to GitHub API
  - [ ] **Tool 3: `search_issues(query, repo?, state?)`**
    - Qdrant search filtered by `source_type="issue"` or `source_type="pr"`
    - Returns top 5 matching issues/PRs
  - [ ] **Tool 4: `get_call_graph(function_name, repo?)`**
    - Neo4j query: what does this function call? What calls it?
    - Returns: callers list + callees list
  - [ ] **Tool 5: `get_file_history(file_path, repo?)`**
    - Neo4j query: which PRs modified this file? Which issues they closed?
    - Returns: list of PRs with titles + linked issues
  - [ ] **Tool 6: `get_dependencies(module_name, repo?)`**
    - Neo4j query: what does this file import? What imports it?
    - Also: third-party dependencies from manifest
  - [ ] **Tool 7: `calculate_math(expression)`**
    - Port directly from FinIntel — safe AST-based eval
  - [ ] **Bonus Tool: `ask_human_for_clarification(question)`**
    - Returns immediately, prompting the user to refine their query
    - Used when query is too vague

### 5.3 LangGraph Supervisor

- [ ] Implement `agents/supervisor.py`:
  - [ ] LLM: Groq `llama-3.3-70b-versatile` (primary), Gemini 2.5 Flash (fallback)
  - [ ] System prompt (code-focused, strict):
    ```
    You are Cortex, an elite Code Intelligence Agent.
    You have access to 7 tools for exploring indexed codebases.
    
    RULES:
    - NEVER guess. Always use tools to find actual source code.
    - Maximum 3 tool calls before synthesizing your final answer.
    - Always cite: file path, function name, line numbers.
    - If the query is ambiguous, call ask_human_for_clarification.
    - Format code in markdown with correct language tags.
    ```
  - [ ] LangGraph StateGraph with:
    - [ ] `recursion_limit=5` (hard cap on loops)
    - [ ] Nodes: `agent`, `tools`
    - [ ] Conditional edge: if agent returns tool_calls → route to tools; else → END
  - [ ] Fallback: if Groq returns 429, retry with Gemini automatically
  - [ ] Conversation history: pass last 5 messages for multi-turn context

### 5.4 Wire Up Routes

- [ ] Update `api/routes.py`:
  - [ ] `POST /api/v1/query` → direct RAG (no agent, fast)
  - [ ] `POST /api/v1/agent_query` → full agent pipeline
  - [ ] `GET /api/v1/repos` → list all indexed repos (query Qdrant for distinct repo values)
  - [ ] `DELETE /api/v1/repos/{owner}/{repo}` → delete from Qdrant + Neo4j
  - [ ] `GET /api/v1/graph/stats` → Neo4j node/edge counts by type

### 5.5 Phase 5 Verification ✅ / ❌

```
TEST 1: Direct RAG query
  POST /api/v1/query {"query": "How does authentication work?", "repo": "owner/repo"}
  Expected: Returns answer citing actual file paths + source chunks
  Result: [ ]

TEST 2: Agent uses search_code tool
  POST /api/v1/agent_query {"query": "Find the database connection logic"}
  Expected: Agent calls search_code, returns answer with file path + line numbers
  Result: [ ]

TEST 3: Agent uses Neo4j tools
  POST /api/v1/agent_query {"query": "What functions call verify_token?"}
  Expected: Agent calls get_call_graph, returns caller list from Neo4j
  Result: [ ]

TEST 4: Agent chains multiple tools
  POST /api/v1/agent_query {"query": "Why was the auth module changed recently?"}
  Expected: Agent calls search_code → get_file_history → synthesizes answer
  Result: [ ]

TEST 5: Agent respects recursion limit
  POST /api/v1/agent_query {"query": "Tell me everything about the entire codebase"}
  Expected: Agent makes ≤ 3 tool calls, then summarizes (does NOT loop forever)
  Result: [ ]

TEST 6: Cross-repo query
  POST /api/v1/agent_query {"query": "Where is the login API defined and what frontend calls it?"}
  (Requires 2 repos indexed)
  Expected: Agent searches both repos, cites files from each
  Result: [ ]

TEST 7: Groq fallback to Gemini
  (Simulate by temporarily using invalid Groq key)
  Expected: Agent seamlessly falls back to Gemini 2.5 Flash
  Result: [ ]
```

**Phase 5 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 6 — Frontend

> **Goal:** Beautiful, functional UI with Chat, Repo Manager, and Interactive Graph Explorer.
> **Estimated Time:** 8-10 hours
> **Depends on:** Phase 5 ✅

### 6.1 Design System & Layout

- [ ] Set up global CSS variables (colors, fonts, spacing)
- [ ] Use local-first production typography (no build-time Google Font fetch)
- [ ] Dark theme as default (premium developer aesthetic)
- [ ] Sidebar navigation: Chat | Repos | Graph
- [ ] Active page indicator
- [ ] Responsive: works on 1440px+ screens (desktop-focused tool)

### 6.2 Chat Page (`/`)

- [ ] Port from FinIntel's `ChatInterface.tsx`:
  - [ ] Message input + send button
  - [ ] Message history (user + AI bubbles)
  - [ ] Loading spinner during agent processing
  - [ ] Multi-turn conversation (send history array)
- [ ] **New: Repo filter dropdown**
  - [ ] Fetch `GET /api/v1/repos` on page load
  - [ ] Dropdown: "All Repos" | "owner/repo-1" | "owner/repo-2"
  - [ ] Selected repo is sent as filter in query
- [ ] **New: Shiki syntax highlighting**
  - [ ] Install `shiki`
  - [ ] Configure with VS Code dark theme (e.g., `github-dark`, `one-dark-pro`)
  - [ ] Parse AI response markdown → detect code blocks → render with Shiki
- [ ] **Updated: Source badges**
  - [ ] Show: `filename.py:45-87 → function_name()`
  - [ ] Language icon (🐍 Python, 🟨 JS, 🔵 TS, 🐹 Go)
  - [ ] Click to expand full source chunk
  - [ ] Badge color by source_type (blue=code, green=docs, orange=issue, purple=PR)

### 6.3 Repo Manager Page (`/repos`)

- [ ] **Repo list view:**
  - [ ] Fetch `GET /api/v1/repos`
  - [ ] Card per repo: name, language, chunk count, last indexed, webhook status (✅/❌)
  - [ ] Private repo indicator (🔒)
- [ ] **Add repo form:**
  - [ ] Text input: `owner/repo-name`
  - [ ] Branch selector (default: `main`)
  - [ ] Options: ☑ Include Issues ☑ Include PRs ☑ Include Commits
  - [ ] "Add Repository" button → `POST /api/v1/ingest`
  - [ ] Progress indicator (show "Ingesting... X files processed")
- [ ] **Repo actions:**
  - [ ] Re-index button (force re-ingest)
  - [ ] Delete button (with confirmation dialog) → `DELETE /api/v1/repos/{owner}/{repo}`
- [ ] **Ingestion status polling:**
  - [ ] After clicking "Add", poll status every 2 seconds until complete
  - [ ] Show: "Fetching files... → Parsing... → Embedding... → Building graph... → Done ✅"

### 6.4 Graph Explorer Page (`/graph`) — Interactive Visual Graph

- [ ] Install `react-force-graph-2d` (or `3d` if you want 3D later)
- [ ] **Graph data endpoint:**
  - [ ] `GET /api/v1/graph/explore?repo=owner/repo&center=auth.py&depth=2`
  - [ ] Backend queries Neo4j for N-hop neighborhood of the center node
  - [ ] Returns: `{ nodes: [...], links: [...] }` in force-graph format
- [ ] **Node rendering:**
  - [ ] Color by type: File=blue, Function=green, Class=purple, Issue=orange, PR=red, Contributor=cyan
  - [ ] Size by importance (number of connections)
  - [ ] Label: node name (truncated)
- [ ] **Edge rendering:**
  - [ ] Different line styles per relationship type
  - [ ] IMPORTS = solid, CALLS = dashed, MODIFIES = dotted
  - [ ] Hover to see relationship type
- [ ] **Interactivity:**
  - [ ] Drag nodes to rearrange
  - [ ] Click node → show detail panel (right sidebar with full metadata)
  - [ ] Zoom in/out
  - [ ] Search bar: type a file name or function → graph centers on it
- [ ] **Stats panel:**
  - [ ] `GET /api/v1/graph/stats`
  - [ ] Show: total files, functions, classes, issues, PRs, relationships

### 6.5 Phase 6 Verification ✅ / ❌

```
TEST 1: Chat page loads with repo dropdown
  Expected: Dropdown populated with indexed repos
  Result: [ ]

TEST 2: Sending a message returns AI answer
  Expected: Message appears in chat, AI responds with cited code
  Result: [ ]

TEST 3: Code blocks are syntax highlighted (Shiki)
  Expected: Python/JS code in AI answer is colorized, NOT plain text
  Result: [ ]

TEST 4: Source badges show file:line → function format
  Expected: Badges are clickable and show correct metadata
  Result: [ ]

TEST 5: Repo Manager lists indexed repos
  Expected: Cards show repo name, language, chunk count
  Result: [ ]

TEST 6: Adding a new repo shows progress
  Expected: "Ingesting..." status updates, then "Done ✅"
  Result: [ ]

TEST 7: Deleting a repo removes it from list
  Expected: Repo disappears from list + Qdrant + Neo4j
  Result: [ ]

TEST 8: Graph Explorer renders nodes and edges
  Expected: Interactive force-directed graph visible
  Result: [ ]

TEST 9: Clicking a graph node shows details
  Expected: Right panel shows node metadata (file path, connections)
  Result: [ ]

TEST 10: Graph search bar centers on a node
  Expected: Type "auth.py" → graph zooms to that node
  Result: [ ]
```

**Phase 6 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Phase 7 — Webhooks, Deployment & Production

> **Goal:** Auto-sync on push. Backend on Render. Frontend on Vercel. Fully operational.
> **Estimated Time:** 4-6 hours
> **Depends on:** Phase 6 ✅

### 7.1 GitHub Webhook Receiver

- [ ] Implement `api/webhook.py`:
  - [ ] `POST /api/v1/webhook/github`
  - [ ] Verify `X-Hub-Signature-256` (HMAC-SHA256 with `GITHUB_WEBHOOK_SECRET`)
  - [ ] Parse `X-GitHub-Event` header:
    - [ ] `push` → extract added/modified/removed files → re-index changed files
    - [ ] `pull_request` (opened/closed/merged) → re-index PR in Qdrant + Neo4j
    - [ ] `issues` (opened/closed/labeled) → re-index issue
  - [ ] All processing runs as `BackgroundTask` (respond 200 immediately)
  - [ ] `handle_push_event(payload)`:
    - [ ] For added + modified files: fetch content → parse → chunk → embed → upsert
    - [ ] For removed files: delete from Qdrant by `file_path` + `repo` filter
    - [ ] Update Neo4j import graph for changed files
  - [ ] `handle_pr_event(payload)`:
    - [ ] MERGE updated PR node in Neo4j
    - [ ] Re-index PR text in Qdrant
  - [ ] `handle_issue_event(payload)`:
    - [ ] MERGE updated Issue node in Neo4j
    - [ ] Re-index issue text in Qdrant

### 7.2 Auto-Register Webhooks

- [ ] In `ingestion/pipeline.py`, after successful ingest:
  - [ ] `POST /repos/{owner}/{repo}/hooks` with:
    ```json
    {
      "name": "web",
      "active": true,
      "events": ["push", "pull_request", "issues"],
      "config": {
        "url": "{BACKEND_URL}/api/v1/webhook/github",
        "content_type": "json",
        "secret": "{GITHUB_WEBHOOK_SECRET}"
      }
    }
    ```
  - [ ] If webhook already exists (409 conflict): skip silently
  - [ ] Store `webhook_active: true` in repo metadata

### 7.3 Deploy Backend to Render

- [ ] Finalize `Dockerfile` (test locally first)
- [ ] Create `render.yaml` with env var references
- [ ] Push to GitHub → connect Render to the repo
- [ ] Set ALL env vars in Render dashboard:
  - [ ] GITHUB_PAT, GITHUB_WEBHOOK_SECRET
  - [ ] QDRANT_URL, QDRANT_API_KEY
  - [ ] NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
  - [ ] GEMINI_API_KEY, GROQ_API_KEY
  - [ ] EMBEDDING_BACKEND=jina
  - [ ] EMBEDDING_MODEL=jina-embeddings-v3
  - [ ] EMBEDDING_DIMENSIONS=1024
  - [ ] JINA_API_KEY
  - [ ] ENVIRONMENT=production
- [ ] Verify: `https://cortex-api.onrender.com/health` returns 200

### 7.4 Deploy Frontend to Vercel

- [ ] Push frontend to GitHub (same repo, `frontend/` subdirectory)
- [ ] Connect Vercel to the repo
- [ ] Set root directory to `frontend/`
- [ ] Set env var: `NEXT_PUBLIC_API_URL=https://cortex-api.onrender.com`
- [ ] Verify: `https://cortex.vercel.app` loads the UI

### 7.5 GitHub Actions CI/CD

- [ ] Create `.github/workflows/deploy.yml`:
  - [ ] On push to `main`:
    - [ ] Lint backend (`ruff check`)
    - [ ] Lint frontend (`npm run lint`)
    - [ ] (Render + Vercel auto-deploy on push — no explicit deploy step needed)

### 7.6 Phase 7 Verification ✅ / ❌

```
TEST 1: Webhook receives push events
  Command: Make a commit + push to an indexed repo
  Expected: Render logs show "Webhook received: push"
  Result: [ ]

TEST 2: Changed file is re-indexed
  Command: Modify a function in indexed repo, push, wait 30s
  Expected: Qdrant chunk is updated (check via search)
  Result: [ ]

TEST 3: New file is indexed
  Command: Add a new .py file to repo, push
  Expected: New chunks appear in Qdrant
  Result: [ ]

TEST 4: Deleted file is removed
  Command: Delete a file from repo, push
  Expected: Chunks for that file removed from Qdrant
  Result: [ ]

TEST 5: Production backend health
  URL: https://cortex-api.onrender.com/health
  Expected: {"status": "healthy"}
  Result: [ ]

TEST 6: Production frontend loads
  URL: https://cortex.vercel.app
  Expected: Full UI with Chat, Repos, Graph pages
  Result: [ ]

TEST 7: End-to-end production flow
  - Add a repo via production Repo Manager
  - Ask a question via production Chat
  - View graph via production Graph Explorer
  Expected: Everything works
  Result: [ ]
```

**Phase 7 Notes:**
```
(Write any issues, observations, or deviations here during implementation)


```

---

## Post-Launch Improvements (Backlog)

> These are NOT required for launch. Track them here for future iterations.

- [ ] **Streaming responses:** Stream agent output token-by-token to the chat UI (SSE)
- [ ] **3D Graph Explorer:** Upgrade `react-force-graph-2d` → `3d` for immersive visualization
- [ ] **Code-specialized embedding tuning:** Evaluate Jina settings or alternate code-focused models if search quality is lacking
- [ ] **PR diff viewer:** Show actual code diffs inline in the chat for "what changed?" queries
- [ ] **Multiple branches:** Support indexing `dev`, `staging`, `main` separately
- [ ] **Scheduled re-indexing:** Cron job to periodically refresh the entire index (backup for missed webhooks)
- [ ] **Usage analytics:** Track which tools the agent uses most, which queries fail
- [ ] **Export graph:** Download Neo4j subgraph as JSON/PNG for documentation

---

## Quick Reference: All API Endpoints

| Method | Endpoint | Purpose | Phase |
|---|---|---|---|
| `GET` | `/health` | Health check | 0 |
| `POST` | `/api/v1/ingest` | Trigger repo ingestion | 1 |
| `GET` | `/api/v1/repos` | List indexed repos | 5 |
| `DELETE` | `/api/v1/repos/{owner}/{repo}` | Remove repo entirely | 5 |
| `POST` | `/api/v1/query` | Direct RAG query | 5 |
| `POST` | `/api/v1/agent_query` | Agent-powered query | 5 |
| `GET` | `/api/v1/graph/stats` | Neo4j graph statistics | 5 |
| `GET` | `/api/v1/graph/explore` | Graph neighborhood for visualization | 6 |
| `POST` | `/api/v1/webhook/github` | GitHub webhook receiver | 7 |

---

## Quick Reference: Tech Stack

| Layer | Technology | Cost |
|---|---|---|
| Frontend | Next.js 16 + Shiki + react-force-graph | $0 |
| Backend | FastAPI + Python 3.12 | $0 |
| Embeddings | Jina AI `jina-embeddings-v3` | Depends on usage/free tier |
| Agent LLM | Groq LLaMA-3.3-70B (fallback: Gemini 2.5 Flash) | $0 |
| Generation LLM | Gemini 2.5 Flash | $0 |
| Vector DB | Qdrant Cloud (1GB free) | $0 |
| Graph DB | Neo4j AuraDB (free tier) | $0 |
| AST Parsing | tree-sitter (Python/JS/TS/Go) | $0 |
| Backend Hosting | Render (free Docker) | $0 |
| Frontend Hosting | Vercel (hobby tier) | $0 |
| **Total** | | **$0** |

---

*Cortex Implementation Tracker v1.0 — 2026-04-17*
*Update this document as each phase is completed.*
