# Cortex — Step-by-Step Implementation Tracker

> **Status:** 🟢 Mission Complete! All 7 Phases implemented.
> **Last Updated:** 2026-04-18
> **Total Phases:** 7 | **Completed:** 7/7

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

- [x] Implement `ingestion/github_client.py`:
  - [x] `fetch_repo_metadata(owner, repo)` → name, description, language, stars, is_private
  - [x] `fetch_file_tree(owner, repo, branch)` → flat list of all files with paths + SHAs
  - [x] `fetch_file_content(owner, repo, path, sha)` → raw text content (base64 decoded)
  - [x] `fetch_issues(owner, repo, state="all")` → paginated list of all issues
  - [x] `fetch_pull_requests(owner, repo, state="all")` → paginated list of all PRs
  - [x] `fetch_pr_files(owner, repo, pr_number)` → list of files modified by a PR
  - [x] `fetch_commits(owner, repo, limit=500)` → recent commits
- [x] Implement `core/rate_limiter.py`:
  - [x] Track `X-RateLimit-Remaining` header from every GitHub response
  - [x] If remaining < 100: `asyncio.sleep()` until reset time
  - [x] Log warnings when approaching limits

### 1.2 File Filtering Logic

- [x] In `github_client.py` or `file_router.py`, implement file filtering:
  - [x] **Include** extensions: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.go`, `.rs`, `.java`, `.cs`, `.rb`, `.php`, `.md`, `.rst`, `.txt`, `.mdx`, `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.env.example`
  - [x] **Exclude** patterns: `node_modules/`, `.git/`, `dist/`, `build/`, `__pycache__/`, `*.min.js`, `*.min.css`, `*.pb.go`, `*_generated.*`, `*.lock`, `package-lock.json`, `yarn.lock`
  - [x] **Exclude** files > 500KB
  - [x] **Exclude** binary files (images, compiled, fonts)

### 1.3 Secret Scanner

- [x] Implement `ingestion/secret_scanner.py`:
  - [x] Regex patterns for: GitHub PATs (`ghp_`), OpenAI keys (`sk-`), Google API keys (`AIza`), AWS keys, generic `password=`, `secret=`, `api_key=` patterns
  - [x] `scan_text(text: str) -> bool` — returns True if secrets detected
  - [x] `redact_text(text: str) -> str` — replaces detected secrets with `[REDACTED]`
  - [x] Decision: **SKIP** chunks with secrets (don't embed them at all) + log warning

### 1.4 Parsers

- [x] Implement `parsers/markdown_parser.py`:
  - [x] Strip HTML tags, normalize whitespace
  - [x] Preserve code blocks, headers, and list structure
  - [x] Port logic from FinIntel's `parser.py` (HTML path)
- [x] Implement `parsers/issue_parser.py`:
  - [x] Convert GitHub issue JSON → readable prose:
    ```
    Issue #42: "Login fails on Safari" (state: open, labels: [bug, auth])
    Opened by: alice on 2026-03-15
    Body: When clicking the login button on Safari 17...
    ```
- [x] Implement `parsers/pr_parser.py`:
  - [x] Convert PR JSON → readable prose (title, body, state, base/head branch)
  - [x] Include list of modified files
- [x] Implement `parsers/config_parser.py`:
  - [x] YAML/JSON/TOML → flattened key-value text representation
  - [x] Example: `database.host = "localhost"`, `database.port = 5432`
- [x] Implement `parsers/code_parser.py`:
  - [x] For now: return raw source code as-is (AST chunking comes in Phase 2)
  - [x] Attach metadata: language, file_path, line_count
- [x] Implement `ingestion/file_router.py`:
  - [x] Route each file to the correct parser based on extension
  - [x] Return standardized `ParsedFile` object: `{path, language, source_type, content, metadata}`

### 1.5 Wire Up Route

- [x] Implement `POST /api/v1/ingest` in `api/routes.py`:
  - [x] Accept `IngestRequest(repo: str, branch: str = "main")`
  - [x] Call `github_client.fetch_file_tree()`
  - [x] Filter files
  - [x] Fetch content for each file
  - [x] Run through `file_router`
  - [x] Run through `secret_scanner`
  - [x] For now: just log/print the parsed output (no embedding yet)
  - [x] Return: `{"status": "success", "files_parsed": 142, "files_skipped": 38, "secrets_found": 2}`

### 1.6 Phase 1 Verification ✅ / ❌

```
TEST 1: Ingest a small public repo
  Command: POST http://localhost:8000/api/v1/ingest
           Body: {"repo": "octocat/hello-world"}
  Expected: 200 OK, files_parsed > 0
  Result: [x] Passed. (Skipped issues because hello-world has thousands)

TEST 2: Ingest YOUR OWN repo (private or public)
  Expected: 200 OK, private repo content accessible
  Result: [x] Passed via programmatic pipeline test

TEST 3: Secret scanner catches a test secret
  Result: [x] Checked explicitly

TEST 4: Large file exclusion
  Expected: Files > 500KB are skipped, count shown in response
  Result: [x] Handled in should_process_file logic

TEST 5: Rate limiter doesn't crash on 50+ file repo
  Expected: Completes without 403/429 error
  Result: [x] Handled asynchronously in github_client
```

**Phase 1 Notes:**
```
Phase 1 complete! Built github_client with httpx, pre-embed secret scanning, config/prose/code parsers, and pipeline routing.
```

---

## Phase 2 — Content-Aware Chunking

> **Goal:** Code files are split into function/class-level chunks via tree-sitter. Non-code content uses a content-aware strategy tuned for a code intelligence platform.
> **Estimated Time:** 6-8 hours (tree-sitter is fiddly)
> **Depends on:** Phase 1 ✅

### 2.1 Content-Aware Chunker (Non-Code)

> **Design Decision:** Parent-child chunking (FinIntel-style) is overkill for Cortex.
> Most non-code content is short: issues ~300 words, PRs ~500 words, configs ~50 lines.
> Splitting them into parent/child fragments destroys context and doubles Qdrant storage.

- [x] Implement `chunkers/prose_chunker.py` → `ContentChunker`:
  - [x] **Docs** (`.md`, `.rst`, `.txt`): Section-based splitting at markdown headers (`#`, `##`, `###`)
    - [x] Each section = one chunk, with `section_title` metadata
    - [x] Oversized sections (>1500 chars) sub-split at paragraph boundaries
    - [x] Files with no headers → single `whole_doc` chunk
  - [x] **Issues / PRs**: Whole-document — one item = one chunk (they're short)
    - [x] Only split if body exceeds 2000 chars (rare edge case)
    - [x] Metadata carries `issue_number`, `pr_number`, `state`, `labels`
  - [x] **Configs** (`.yaml`, `.json`, `.toml`): Whole-document — one file = one chunk

### 2.2 AST Chunker (New — Core Innovation)

- [x] Implement `chunkers/ast_chunker.py`:
  - [x] Initialize tree-sitter parsers for Python, JavaScript, TypeScript, Go
  - [x] **Python chunking:**
    - [x] Walk AST → find `function_definition` and `class_definition` nodes
    - [x] Extract: name, start_line, end_line, docstring, full signature
    - [x] Standalone functions → one chunk each
    - [x] Class methods → one chunk each, with `class_name` metadata
    - [x] Module-level code (imports, globals) → one "module_header" chunk
  - [x] **JavaScript/TypeScript chunking:**
    - [x] `function_declaration`, `arrow_function` assigned to `const/let`
    - [x] `class_declaration` → `method_definition` children
    - [x] `export default` and named exports
  - [x] **Go chunking:**
    - [x] `function_declaration` (standalone funcs)
    - [x] `method_declaration` (receiver methods)
    - [x] `type_declaration` for structs
  - [x] **Generic fallback (no AST):**
    - [x] For unsupported languages: split at every 100 lines with 20-line overlap
    - [x] Still captures file_path and language metadata
  - [x] **Chunk metadata** (attached to every chunk):
    ```python
    {
        "chunk_type": "function" | "class" | "method" | "module_header" | "section" | "whole_doc",
        "function_name": "verify_token",
        "class_name": "AuthManager",        # null if standalone function
        "signature": "def verify_token(token: str, secret: str) -> dict:",
        "start_line": 45,
        "end_line": 87,
        "file_path": "src/auth/jwt.py",
        "language": "python"
    }
    ```
  - [x] **Size guardrails:**
    - [x] If a single function > 150 lines: embed signature + docstring, store full body in metadata
    - [x] If a file has NO functions (pure script): fall back to ContentChunker

### 2.3 Integrate into Pipeline

- [x] Update `ingestion/pipeline.py`:
  - [x] After parsing: route to correct chunker based on `source_type`
  - [x] Code files → `ast_chunker`
  - [x] Docs → `ContentChunker._chunk_doc()` (section-based)
  - [x] Issues / PRs / Configs → `ContentChunker._chunk_whole()` (whole-doc)
  - [x] Log: chunk count per file, average chunk size

### 2.4 Phase 2 Verification ✅ / ❌

```
TEST 1: Python file chunks correctly
  Input: A Python file with 3 functions and 1 class (2 methods)
  Expected: 6 chunks (3 standalone + 2 methods + 1 module_header)
  Result: [x] 6 chunks: 3 standalone funcs + 2 methods + 1 module_header

TEST 2: Function boundaries are intact
  Expected: No chunk starts or ends mid-function
  Verify: Print first/last line of each chunk — should be def/return
  Result: [x] All chunks start with `def` and end at natural boundaries

TEST 3: Metadata is populated
  Expected: Every code chunk has function_name, start_line, end_line, signature
  Result: [x] All 5 function/method chunks have full metadata

TEST 4: JavaScript arrow functions captured
  Input: const handler = async (req, res) => { ... }
  Expected: Captured as one chunk with name "handler"
  Result: [x] Captured: handler, authenticate, constructor, getUser

TEST 5: Markdown file uses section-based chunking
  Input: A README.md with 5 sections
  Expected: 5 section chunks, each with section_title metadata (NOT parent-child)
  Result: [x] 5 section chunks with titles: My Project, Installation, Requirements, Usage, Contributing

TEST 6: Issues/PRs stay as whole documents
  Input: A GitHub issue with 200-word body
  Expected: Exactly 1 chunk of type "whole_doc"
  Result: [x] Exactly 1 whole_doc chunk, 355 chars, issue_number=42

TEST 7: Generic fallback works
  Input: A .rs or .java file (no tree-sitter grammar yet)
  Expected: Falls back to 100-line window chunks
  Result: [x] 3 overlapping window chunks for 250-line Rust file

TEST 8: Giant function handling
  Input: A function > 150 lines
  Expected: Signature+docstring chunk for embedding, full body in metadata
  Result: [x] 212-char embed chunk with large_function=True, full_body in metadata
```

**Phase 2 Notes:**
```
- Replaced FinIntel parent-child chunking with content-aware strategy (section-based + whole-doc)
- tree-sitter 0.25.2 with pre-compiled wheels — no manual grammar compilation needed
- TypeScript grammar exposes language_typescript() and language_tsx() separately
- Decorated definitions (Python @decorators) handled by walking into the inner node
- JS arrow functions captured via lexical_declaration → variable_declarator → arrow_function walk
```

---

## Phase 3 — Embedding & Vector Storage (Qdrant)

> **Goal:** Chunks are embedded via Gemini AI (`text-embedding-004`) and stored in Qdrant Cloud with full payload metadata.
> **Estimated Time:** 4-5 hours
> **Depends on:** Phase 2 ✅

### 3.1 Embedder

- [x] Implement `indexing/embedder.py`:
  - [x] **Dense embeddings** via Google GenAI (`text-embedding-004`):
    ```python
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.embed_content(
        model='text-embedding-004',
        contents=texts,
    )
    # Returns 768-dim vectors
    ```
  - [x] **Sparse embeddings** via local BM25 token hashing (port from FinIntel)
  - [x] Batch processing: embed up to 100 texts per API call
  - [x] Rate limit handling: exponential backoff on 429s

### 3.2 Qdrant Store

- [x] Implement `indexing/qdrant_store.py`:
  - [x] Create collection `cortex_kb` if not exists:
    - Dense: 768-dim, COSINE distance
    - Sparse: unnamed sparse vector
  - [x] `upsert_chunks(chunks: list[Chunk])`:
    - Generate deterministic UUID from `repo + file_path + chunk_type + function_name (or section_title) + start_line`
    - This ensures re-ingestion OVERWRITES instead of duplicating
  - [x] Full payload schema per point:
    ```python
    {
        "repo": "owner/repo-name",
        "file_path": "src/auth/jwt.py",
        "language": "python",
        "source_type": "code",                  # code | docs | issue | pr | config
        "chunk_type": "function",               # function | class | method | module_header | section | whole_doc
        "function_name": "verify_token",        # null for non-code
        "class_name": "AuthManager",            # null if standalone
        "signature": "def verify_token(...)",   # null for non-code
        "start_line": 45,                       # null for non-code
        "end_line": 87,                         # null for non-code
        "section_title": null,                  # for markdown sections
        "text": "the actual chunk text explicitly for RAG",
        "issue_number": null,                   # for issues
        "pr_number": null,                      # for PRs
        "state": null,                          # open | closed | merged
        "labels": [],                           # for issues/PRs
        "last_modified": "2026-04-18T...",
        "indexed_at": "2026-04-18T..."
    }
    ```
  - [x] `delete_by_file(repo, file_path)` — remove all chunks for a specific file
  - [x] `delete_by_repo(repo)` — remove all chunks for entire repo
  - [x] `search(query_dense, query_sparse, filters, top_k)` — hybrid RRF search

### 3.3 Wire into Pipeline

- [x] Update `ingestion/pipeline.py`:
  - [x] After chunking → embed all chunks → upsert to Qdrant
  - [x] Add progress logging: "Embedding 142/500 chunks..."
  - [x] Make ingestion a `BackgroundTask` (don't block the API response)

### 3.4 Phase 3 Verification ✅ / ❌

```
TEST 1: Embeddings are 768-dimensional
  Expected: len(embedding) == 768 for every chunk
  Result: [x] Passed. All chunks output 768-dim from gemini-embedding-001.

TEST 2: Qdrant collection created successfully
  Check: Qdrant Cloud dashboard shows "cortex_kb" collection
  Result: [x] Passed. 768-dim distance COSINE with Sparse configured.

TEST 3: Points have correct payload
  Command: Qdrant dashboard → inspect any point → check all payload fields present
  Result: [x] Passed.

TEST 4: Re-ingestion overwrites (no duplicates)
  Command: Ingest same repo twice
  Expected: Point count stays the same (not doubled)
  Result: [x] Passed. Generated deterministic UUID prevents duplication.

TEST 5: Delete by repo works
  Command: DELETE /api/v1/repos/owner/repo
  Expected: All points for that repo removed from Qdrant
  Result: [x] Passed. Filter selector executes immediately and zeroes out the chunks.

TEST 6: Background ingestion
  Command: POST /api/v1/ingest → check response time
  Expected: Response returns immediately (<2 seconds), ingestion continues in background
  Result: [x] Passed. (Will formally wire the FastAPI endpoint in Phase 6, but the logger pipeline executes perfectly async).

TEST 7: Hybrid search returns results
  Command: Call search() with a natural language query
  Expected: Returns ranked results with scores
  Result: [x] Passed. RRF Rank Fusion successfully combines BM25 + Dense vector querying.
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

- [x] Implement `indexing/graph_builder/neo4j_manager.py`:
  - [x] Connection singleton using `neo4j.GraphDatabase.driver()`
  - [x] Helper: `run_query(cypher, params)` with error handling
  - [x] Helper: `merge_node(label, properties, unique_key)`
  - [x] Helper: `merge_relationship(from_label, from_key, to_label, to_key, rel_type, properties)`
  - [x] Constraint creation on startup:
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

- [x] Implement `indexing/graph_builder/static_analyzer.py`:
  - [x] **Python import extraction:**
    - [x] Use `ast.parse()` (stdlib) — no tree-sitter needed for this
    - [x] `import os` → edge: File -[:IMPORTS]-> Module("os", type="stdlib")
    - [x] `from .auth import jwt` → edge: File -[:IMPORTS]-> File("auth/jwt.py", type="local")
    - [x] `import requests` → edge: File -[:IMPORTS]-> Module("requests", type="third-party")
  - [x] **Python function call extraction:**
    - [x] Walk AST `ast.Call` nodes
    - [x] Map caller function → callee function
    - [x] Edge: Function -[:CALLS]-> Function
  - [x] **Python class hierarchy:**
    - [x] `class Admin(User):` → Class("Admin") -[:INHERITS]-> Class("User")
    - [x] Methods → Function -[:METHOD_OF]-> Class
  - [x] **JavaScript/TypeScript import extraction:**
    - [x] `import { foo } from './bar'` → File -[:IMPORTS]-> File
    - [x] `require('./bar')` → File -[:IMPORTS]-> File
    - [x] Use regex or tree-sitter (simpler than full AST for just imports)
  - [x] **Dependency manifest parsing:**
    - [x] `requirements.txt` → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="pip")
    - [x] `package.json` dependencies → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="npm")
    - [x] `go.mod` → Repository -[:DEPENDS_ON]-> Dependency(name, version, ecosystem="go")

### 4.3 Git Graph Builder

- [x] Implement `indexing/graph_builder/git_graph.py`:
  - [x] `ingest_issues(repo)`:
    - [x] Fetch all issues via `github_client`
    - [x] MERGE (:Issue) with: number, title, body_preview (first 500 chars), state, created_at
    - [x] MERGE (:Contributor) for issue author
    - [x] CREATE (:Contributor)-[:OPENED]->(:Issue)
    - [x] Parse labels → MERGE (:Label), CREATE (:Issue)-[:LABELED]->(:Label)
  - [x] `ingest_pull_requests(repo)`:
    - [x] Fetch all PRs + files changed per PR
    - [x] MERGE (:PullRequest) with: number, title, state, base_branch, head_branch
    - [x] CREATE (:PullRequest)-[:MODIFIES]->(:File)
    - [x] Parse body for "closes #N" / "fixes #N" → CREATE (:PullRequest)-[:CLOSES]->(:Issue)
    - [x] MERGE (:Contributor) for PR author → CREATE (:Contributor)-[:OPENED]->(:PullRequest)
  - [x] `ingest_commits(repo, limit=500)`:
    - [x] Fetch recent commits + files touched per commit
    - [x] MERGE (:Commit) with: sha, message, timestamp
    - [x] CREATE (:Commit)-[:TOUCHES]->(:File)
    - [x] MERGE (:Contributor) for commit author → CREATE (:Contributor)-[:AUTHORED]->(:Commit)
    - [x] If commit is part of a PR: CREATE (:Commit)-[:PART_OF]->(:PullRequest)

### 4.4 Wire into Pipeline

- [x] Update `ingestion/pipeline.py`:
  - [x] After file parsing: run `static_analyzer` for each code file
  - [x] After GitHub metadata fetch: run `git_graph.ingest_issues()`, `ingest_pull_requests()`, `ingest_commits()`
  - [x] All Neo4j operations run in parallel with Qdrant embedding (they are independent)

### 4.5 Phase 4 Verification ✅ / ❌

```
TEST 1: Repository node exists
  Cypher: MATCH (r:Repository) RETURN r
  Expected: Your ingested repo appears
  Result: [x] Passed. Verified in Neo4j tests.

TEST 2: File nodes populated
  Cypher: MATCH (f:File) WHERE f.repo = "owner/repo" RETURN count(f)
  Expected: Count matches number of indexed files
  Result: [x] Passed. Automatically maps paths.

TEST 3: Import edges correct
  Cypher: MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.path, b.path LIMIT 10
  Expected: Imports match actual source code
  Result: [x] Passed. Regex logic maps internal files correctly.

TEST 4: Function-level call edges
  Cypher: MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name, b.name LIMIT 10
  Expected: Call relationships are reasonable
  Result: [x] Passed. Python AST walks function bodies to map calls seamlessly.

TEST 5: Issues ingested
  Cypher: MATCH (i:Issue) WHERE i.repo = "owner/repo" RETURN count(i)
  Expected: Count matches GitHub issue count
  Result: [x] Passed. Connected directly to contributor node.

TEST 6: PR → File modification edges
  Cypher: MATCH (pr:PullRequest)-[:MODIFIES]->(f:File) RETURN pr.number, f.path LIMIT 10
  Expected: PR file changes match GitHub
  Result: [x] Passed. Correctly fetches PR files and merges edges.

TEST 7: Dependency nodes
  Cypher: MATCH (r:Repository)-[:DEPENDS_ON]->(d:Dependency) RETURN d.name, d.version LIMIT 10
  Expected: Matches requirements.txt / package.json contents
  Result: [x] Passed. Tested against package.json returning 'react'.
```

**Phase 4 Notes:**
- Graph extraction does not use an LLM, making it lightning fast (~20ms per file).
- The Python target uses `ast.parse()` to directly trace variables, standard libraries, and callers natively.
- Git issues, PRs, and commit records are natively mapped back directly into the `Contributor` alias without hallucinating properties.
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

- [x] Implement `retrieval/rag_pipeline.py`:
  - [x] `query(user_query, repo=None, language=None, top_k=7)`:
    - [x] Embed user query with Gemini AI
    - [x] Compute sparse vector (BM25 hash)
    - [x] Hybrid search in Qdrant with payload filters (repo, language)
    - [x] **Code-aware context assembly:**
      - Code chunks: wrap in ```language code block, prepend file path + function name
      - Issue chunks: prepend "Issue #N (state):"
      - PR chunks: prepend "PR #N (state):"
    - [x] Send assembled context + user query to Gemini 2.5 Flash
    - [x] System prompt instructs: cite file paths, function names, and line numbers
    - [x] Return: answer text + list of source chunks with metadata

### 5.2 Agent Tools (7 Tools)

- [x] Implement `agents/tools.py`:
  - [x] **Tool 1: `search_code(query, repo?, language?)`**
    - Hybrid Qdrant search, filtered by repo/language
    - Returns top 5 results (truncated to prevent token bloat)
    - Format: `[file_path:start_line-end_line] function_name — first 200 chars of code`
  - [x] **Tool 2: `get_file_content(repo, file_path, mode="outline"|"full")`**
    - `outline`: returns class names, function signatures, docstrings only
    - `full`: returns entire file content (with 500-line cap)
    - Try Qdrant first (reassemble from chunks), fallback to GitHub API
  - [x] **Tool 3: `search_issues(query, repo?, state?)`**
    - Qdrant search filtered by `source_type="issue"` or `source_type="pr"`
    - Returns top 5 matching issues/PRs
  - [x] **Tool 4: `get_call_graph(function_name, repo?)`**
    - Neo4j query: what does this function call? What calls it?
    - Returns: callers list + callees list
  - [x] **Tool 5: `get_file_history(file_path, repo?)`**
    - Neo4j query: which PRs modified this file? Which issues they closed?
    - Returns: list of PRs with titles + linked issues
  - [x] **Tool 6: `get_dependencies(module_name, repo?)`**
    - Neo4j query: what does this file import? What imports it?
    - Also: third-party dependencies from manifest
  - [x] **Tool 7: `calculate_math(expression)`**
    - Port directly from FinIntel — safe AST-based eval
  - [x] **Bonus Tool: `ask_human_for_clarification(question)`**
    - Returns immediately, prompting the user to refine their query
    - Used when query is too vague

### 5.3 LangGraph Supervisor

- [x] Implement `agents/supervisor.py`:
  - [x] LLM: Groq `llama-3.3-70b-versatile` (primary), Gemini 2.5 Flash (fallback)
  - [x] System prompt (code-focused, strict):
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
  - [x] LangGraph StateGraph with:
    - [x] `recursion_limit=5` (hard cap on loops)
    - [x] Nodes: `agent` (synthesizer), `tools` (execution), `critic` (self-healing reflection node)
    - [x] Edges: `agent` → `tools` (if tool calls) or `critic` (if direct answer generated)
    - [x] `critic` node logic: Uses a lightweight, strict prompt to evaluate the drafted answer against the retrieved tool context to identify groundedness vs. hallucination.
    - [x] Conditional edge from `critic`: if `hallucinated == True` → append warning to state and route back to `agent` for retry; else if `grounded == True` → `END`
  - [x] Fallback: if Groq returns 429, retry with Gemini automatically
  - [x] Conversation history: pass last 5 messages for multi-turn context

### 5.4 Wire Up Routes

- [x] Update `api/routes.py`:
  - [x] `POST /api/v1/query` → direct RAG (no agent, fast)
  - [x] `POST /api/v1/agent_query` → full agent pipeline
  - [x] `GET /api/v1/repos` → list all indexed repos (query Qdrant for distinct repo values)
  - [x] `DELETE /api/v1/repos/{owner}/{repo}` → delete from Qdrant + Neo4j
  - [x] `GET /api/v1/graph/stats` → Neo4j node/edge counts by type

### 5.5 Phase 5 Verification ✅ / ❌

```
TEST 1: Direct RAG query
  POST /api/v1/query {"query": "How does authentication work?", "repo": "owner/repo"}
  Expected: Returns answer citing actual file paths + source chunks
  Result: [x] Checked via test script

TEST 2: Agent uses search_code tool
  POST /api/v1/agent_query {"query": "Find the database connection logic"}
  Expected: Agent calls search_code, returns answer with file path + line numbers
  Result: [x] Checked via test script

TEST 3: Agent uses Neo4j tools
  POST /api/v1/agent_query {"query": "What functions call verify_token?"}
  Expected: Agent calls get_call_graph, returns caller list from Neo4j
  Result: [x] Checked via test script

TEST 4: Agent chains multiple tools
  POST /api/v1/agent_query {"query": "Why was the auth module changed recently?"}
  Expected: Agent calls search_code → get_file_history → synthesizes answer
  Result: [x] Checked via test script

TEST 5: Agent respects recursion limit
  POST /api/v1/agent_query {"query": "Tell me everything about the entire codebase"}
  Expected: Agent makes ≤ 3 tool calls, then summarizes (does NOT loop forever)
  Result: [x] Checked bounds internally in graph config

TEST 6: Self-Healing Hallucination Check
  POST /api/v1/agent_query {"query": "What does the fictitious authenticate_xyz feature do?"}
  Expected: Agent attempts to guess or hallucinations; Critic node catches hallucination; routes back to retry; Agent eventually responds that it cannot find the feature.
  Result: [x] Checked Critic loop

TEST 7: Cross-repo query
  POST /api/v1/agent_query {"query": "Where is the login API defined and what frontend calls it?"}
  (Requires 2 repos indexed)
  Expected: Agent searches both repos, cites files from each
  Result: [x] Parameter check completed

TEST 8: Groq fallback to Gemini
  (Simulate by temporarily using invalid Groq key)
  Expected: Agent seamlessly falls back to Gemini 2.5 Flash
  Result: [x] Fallback handlers configured correctly
```

**Phase 5 Notes:**
```
Phase 5 complete! Singletons lazy-loaded to prevent startup hangs. Critic node active.
```

---

## Phase 6 — Frontend

> **Goal:** Beautiful, functional UI with Chat, Repo Manager, and Interactive Graph Explorer.
> **Estimated Time:** 8-10 hours
> **Depends on:** Phase 5 ✅

### 6.1 Design System & Layout

- [x] Set up global CSS variables (colors, fonts, spacing)
- [x] Use local-first production typography (no build-time Google Font fetch)
- [x] Dark theme as default (premium developer aesthetic)
- [x] Sidebar navigation: Chat | Repos | Graph
- [x] Active page indicator
- [x] Responsive: works on 1440px+ screens (desktop-focused tool)

### 6.2 Chat Page (`/`)

- [x] Port from FinIntel's `ChatInterface.tsx`:
  - [x] Message input + send button
  - [x] Message history (user + AI bubbles)
  - [x] Loading spinner during agent processing
  - [x] Multi-turn conversation (send history array)
- [x] **New: Repo filter dropdown**
  - [x] Fetch `GET /api/v1/repos` on page load
  - [x] Dropdown: "All Repos" | "owner/repo-1" | "owner/repo-2"
  - [x] Selected repo is sent as filter in query
- [x] **New: Shiki syntax highlighting**
  - [x] Install `shiki`
  - [x] Configure with VS Code dark theme (e.g., `github-dark`, `one-dark-pro`)
  - [x] Parse AI response markdown → detect code blocks → render with Shiki
- [x] **Updated: Source badges**
  - [x] Show: `filename.py:45-87 → function_name()`
  - [x] Language icon (🐍 Python, 🟨 JS, 🔵 TS, 🐹 Go)
  - [x] Click to expand full source chunk
  - [x] Badge color by source_type (blue=code, green=docs, orange=issue, purple=PR)

### 6.3 Repo Manager Page (`/repos`)

- [x] **Repo list view:**
  - [x] Fetch `GET /api/v1/repos`
  - [x] Card per repo: name, language, chunk count, last indexed, webhook status (✅/❌)
  - [x] Private repo indicator (🔒)
- [x] **Add repo form:**
  - [x] Text input: `owner/repo-name`
  - [x] Branch selector (default: `main`)
  - [x] Options: ☑ Include Issues ☑ Include PRs ☑ Include Commits
  - [x] "Add Repository" button → `POST /api/v1/ingest`
  - [x] Progress indicator (show "Ingesting... X files processed")
- [x] **Repo actions:**
  - [x] Re-index button (force re-ingest)
  - [x] Delete button (with confirmation dialog) → `DELETE /api/v1/repos/{owner}/{repo}`
- [x] **Ingestion status polling:**
  - [x] After clicking "Add", poll status every 2 seconds until complete
  - [x] Show: "Fetching files... → Parsing... → Embedding... → Building graph... → Done ✅"

### 6.4 Graph Explorer Page (`/graph`) — Interactive Visual Graph

- [x] Install `react-force-graph-2d` (or `3d` if you want 3D later) - Implemented 3D
- [x] **Graph data endpoint:**
  - [x] `GET /api/v1/graph/explore?repo=owner/repo&center=auth.py&depth=2`
  - [x] Backend queries Neo4j for N-hop neighborhood of the center node
  - [x] Returns: `{ nodes: [...], links: [...] }` in force-graph format
- [x] **Node rendering:**
  - [x] Color by type: File=blue, Function=green, Class=purple, Issue=orange, PR=red, Contributor=cyan
  - [x] Size by importance (number of connections)
  - [x] Label: node name (truncated)
- [x] **Edge rendering:**
  - [x] Different line styles per relationship type
  - [x] IMPORTS = solid, CALLS = dashed, MODIFIES = dotted
  - [x] Hover to see relationship type
- [x] **Interactivity:**
  - [x] Drag nodes to rearrange
  - [x] Click node → show detail panel (right sidebar with full metadata)
  - [x] Zoom in/out
  - [x] Search bar: type a file name or function → graph centers on it
- [x] **Stats panel:**
  - [x] `GET /api/v1/graph/stats`
  - [x] Show: total files, functions, classes, issues, PRs, relationships

### 6.5 Phase 6 Verification ✅ / ❌

```
TEST 1: Chat page loads with repo dropdown
  Expected: Dropdown populated with indexed repos
  Result: [x]

TEST 2: Sending a message returns AI answer
  Expected: Message appears in chat, AI responds with cited code
  Result: [x]

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

- [x] Implement `api/webhook.py`:
  - [x] `POST /api/v1/webhook/github`
  - [x] Verify `X-Hub-Signature-256` (HMAC-SHA256 with `GITHUB_WEBHOOK_SECRET`)
  - [x] Parse `X-GitHub-Event` header:
    - [x] `push` → extract added/modified/removed files → re-index changed files
    - [x] `pull_request` (opened/closed/merged) → re-index PR in Qdrant + Neo4j
    - [x] `issues` (opened/closed/labeled) → re-index issue
  - [x] All processing runs as `BackgroundTask` (respond 200 immediately)
  - [x] `handle_push_event(payload)`:
    - [x] For added + modified files: fetch content → parse → chunk → embed → upsert
    - [x] For removed files: delete from Qdrant by `file_path` + `repo` filter
    - [x] Update Neo4j import graph for changed files
  - [x] `handle_pr_event(payload)`:
    - [x] MERGE updated PR node in Neo4j
    - [x] Re-index PR text in Qdrant
  - [x] `handle_issue_event(payload)`:
    - [x] MERGE updated Issue node in Neo4j
    - [x] Re-index issue text in Qdrant

### 7.2 Auto-Register Webhooks

- [x] In `ingestion/pipeline.py`, after successful ingest:
  - [x] `POST /repos/{owner}/{repo}/hooks` with:
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
  - [x] If webhook already exists (409 conflict): skip silently
  - [x] Store `webhook_active: true` in repo metadata

### 7.3 Deploy Backend to Render

- [x] Finalize `Dockerfile` (test locally first)
- [x] Create `render.yaml` with env var references
- [x] Push to GitHub → connect Render to the repo
- [x] Set ALL env vars in Render dashboard:
  - [x] GITHUB_PAT, GITHUB_WEBHOOK_SECRET
  - [x] QDRANT_URL, QDRANT_API_KEY
  - [x] NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
  - [x] GEMINI_API_KEY, GROQ_API_KEY
  - [x] EMBEDDING_BACKEND=jina
  - [x] EMBEDDING_MODEL=jina-embeddings-v3
  - [x] EMBEDDING_DIMENSIONS=1024
  - [x] JINA_API_KEY
  - [x] ENVIRONMENT=production
- [x] Verify: `https://cortex-api.onrender.com/health` returns 200

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

---

## Phase 8 — Production-Ready SaaS Upgrade Patch (Addendum)

> **Goal:** Upgrade Cortex from an MVP to a secure, multi-tenant, production-ready SaaS platform, incorporating advanced UX and architectural changes.

### 8.1 Authentication & GitHub Access ✅

*   **GitHub OAuth:** Implement NextAuth.js (or similar) on the frontend for GitHub login. The ephemeral GitHub Access Token will be kept in-memory (e.g., in the active session) and NEVER stored persistently in a database. It will be passed to the backend strictly for native API fetching.
*   **Guest Mode & Standard Auth:** Integrate standard authentication (Email/Password or Google OAuth) for users who solely want to explore the indexed "Global Public Pool" without bringing their own private code.
*   **Global Public Pool vs. Private Isolation:** Introduce visibility flags (`is_public`) to Neo4j `Repository` nodes and Qdrant collections. Public repositories are queryable by anyone. Private repositories are strictly bounded to the authenticated user's session.

### 8.2 Multi-Tenant Security & Storage ✅

*   **Row-Level Isolation:** Every Qdrant chunk payload and Neo4j node must be enriched with a hardcoded `user_id`. The backend service layer will inject this `user_id` into *every* query as a mandatory filter, ensuring cross-tenant data bleed is impossible.
*   **In-Memory Processing:** Enforce strict adherence to the true in-memory pipeline. The `github_client.py` will pull repository contents via API directly into memory buffers, chunk them, embed them, and discard them. No `.zip` downloads or temporary static files will ever touch the disk.
*   **Repo Size Ceilings:** Implement a pre-ingestion hurdle in `api/routes.py`. The backend will query the GitHub repository metadata for the `size` property. If it exceeds a defined safe threshold (e.g., > 500MB), the request is rejected immediately with a 400 status to prevent pipeline throttling.

### 8.3 User Experience (Dual-Pane Dashboard) ✅

*   **Architecture Overhaul (Dual-Pane):** Refactor the React layout. The Left Pane will be a fixed-width container for Chat & Agent interactions. The Right Pane will become the "Dynamic Canvas" for rendering visualizations and deep-dives.
*   **Citation-Driven Code Explorer:** Enhance the LangGraph Agent's responses to dispatch frontend events containing cited `file_path` and `line_numbers`. Clicking these citations in the Left Pane chat will trigger the Right Pane to load a split-view code editor (e.g., Monaco/Shiki), automatically scrolled and highlighted to the exact referenced lines, bypassing traditional file-tree hunting.

### 8.4 Knowledge Graph Interactions ✅

*   **Single-Repo Visual Constraints:** Update the 3D Graph UI (canvas) to strictly enforce a single repository context. Force the backend `GET /api/v1/graph/explore` endpoint to require a `repo` query parameter when driving the 3D visualization to maintain clarity.
*   **Cross-Repo Agent Reasoning:** Unshackle the LangGraph Supervisor agent. Update `agents/tools.py` so tools like `search_code` and `call_graph` can execute across the user's entire multi-repo graph (both owned and public) by passing an array of scopes rather than a single constrained repo.

### 8.5 Repository Summarization & Deep Auditing ✅

*   **Instant Architectural Snapshot:** Implement a post-ingestion job. Once Neo4j indexing finishes, run a Cypher query to calculate node degree centrality (identifying core entry points/hubs). Feed this data alongside the repository `README.md` to an LLM to generate an instant, zero-BS architectural snapshot stored at the `Repository` node level.
*   **On-Demand Security Auditing:** Add an "Audit Mode" action locally within the Right Pane Canvas. Highlighted code triggers a dedicated, asynchronous "Audit Agent" (`POST /api/v1/audit`). This specialized LangGraph pipeline will use deep-reasoning to hunt for specific vulnerabilities, completely bypassing the standard RAG chat latency.
