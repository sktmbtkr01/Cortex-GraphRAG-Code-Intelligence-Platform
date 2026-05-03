wait# Cortex v2 — Architecture-Aligned Implementation Tracker

> **Source of truth:** `cortex_architecture_final_v2.md`
> **Baseline:** existing codebase (Phases 0–8 from `cortex_implementation_tracker.md`)
> **Goal:** evolve current MVP into the dual-pane, glassmorphism, Canvas-driven product specified in v2 — with **zero duplication** of already-working backend logic.
> **Last Updated:** 2026-04-20

---

## Legend

- [ ] Not started
- [⏳] In progress
- [✅] Verified by user
- [❌] Failed verification / needs rework
- [🔧] Existing code to modify
- [🆕] Net-new code
- [♻] Existing code to reuse unchanged

---

## Global Principles

1. **Never rebuild what works.** Ingestion pipeline, chunkers, embedder, Qdrant/Neo4j managers, hybrid search, webhook receiver, git graph builder, snapshot generator → reuse as-is unless explicitly marked 🔧.
2. **One phase at a time.** User tests and marks ✅ before next phase starts.
3. **Verification gates are hard stops.** Phase cannot proceed until its gate passes.
4. **Every modification must state the file(s) touched and why.** No silent edits.

---

## Phase 1 — GitHub OAuth via HttpOnly Cookie Session

**Status:** [✅] Verified by user
**Depends on:** none
**Architecture ref:** Section 1 (Phase A) + Section 8 Identity Gate

### What already exists ♻
- `backend/core/auth.py` — JWT create/decode, `exchange_github_code`, `AuthenticatedUser` model
- `backend/api/auth_routes.py` — `/auth/github/login`, `/auth/github/callback`, `/auth/guest`, `/auth/me`
- `frontend/src/context/AuthContext.tsx` — login/logout/guest flows, `authHeaders()` helper
- `frontend/src/app/login/page.tsx` — login UI
- `frontend/src/app/auth/callback/page.tsx` — OAuth callback handler
- `frontend/src/components/AppShell.tsx` — auth gate / redirect-to-login

### What needs modification 🔧
- `backend/core/auth.py`
  - `get_current_user` must read JWT from **`cortex_session` HttpOnly cookie** instead of (or in addition to) `Authorization: Bearer` header
  - Keep Bearer fallback only for programmatic/test access
  - Remove reliance on `X-GitHub-Token` header from frontend; GitHub token must live server-side (see new session store below)
- `backend/api/auth_routes.py`
  - `/auth/github/callback` must set cookie on response: `HttpOnly`, `Secure` (prod), `SameSite=Lax`, path `/`, 24h expiry
  - `/auth/guest` must do the same
  - Add new `POST /auth/logout` → clears cookie server-side and destroys session store entry
  - Callback response: **stop returning `github_token` to the browser**
- `frontend/src/context/AuthContext.tsx`
  - Remove `localStorage.getItem/setItem("cortex_auth")`
  - Remove `accessToken` and `githubToken` from client state (server holds them)
  - All `fetch` calls must use `credentials: "include"`
  - `authHeaders()` collapses to just `{ "Content-Type": "application/json" }`
  - On mount: call `GET /auth/me` to hydrate user state from cookie
  - `logout()` hits backend `/auth/logout` then clears local user state
- `frontend/src/app/auth/callback/page.tsx`
  - After successful exchange, no token to store → just `router.push("/repos")`
- All existing backend routes that use `user.github_token`
  - Currently relies on `X-GitHub-Token` header; must instead read from server-side session keyed by `user_id`

### What is net-new 🆕
- `backend/core/session_store.py` — minimal in-memory dict `user_id → {github_token, expires_at}` with TTL cleanup. (Redis later; dict is fine for MVP.)
- `backend/core/auth.py` — helper `get_github_token_for_user(user_id) -> str | None`
- `POST /auth/logout` endpoint

### Files touched
- 🔧 `backend/core/auth.py`
- 🔧 `backend/api/auth_routes.py`
- 🔧 `backend/api/routes.py` (every `request.github_token` site → `get_github_token_for_user`)
- 🔧 `backend/ingestion/pipeline.py` (how token reaches `GitHubClient`)
- 🔧 `frontend/src/context/AuthContext.tsx`
- 🔧 `frontend/src/app/auth/callback/page.tsx`
- 🆕 `backend/core/session_store.py`

### How you test
1. Clear all cookies and localStorage for the site.
2. Click "Continue with GitHub" → approve → land on `/repos`.
3. Open DevTools → Application → Cookies → confirm `cortex_session` exists, `HttpOnly=true`, `SameSite=Lax`.
4. Open Application → Local Storage → confirm it is **empty** (no `cortex_auth` key).
5. Hard refresh page → still logged in (cookie survives).
6. Click "Sign out" → cookie gone, redirected to `/login`.
7. In a private window, click "Enter as Guest" → same cookie-based flow works.

### Acceptance gate
- ✅ JWT present ONLY in HttpOnly cookie
- ✅ No token strings anywhere in localStorage, sessionStorage, or JS-accessible scope
- ✅ Ingest call still works (server-side token lookup succeeds)

### Notes / bugs
_(empty)_

---

## Phase 2 — App Shell: Glassmorphism Top Nav + Global Brain + Landing Redirect

**Status:** [✅] Verified by user
**Depends on:** Phase 1 ✅
**Architecture ref:** Section 2.1, 2.2

### What already exists ♻
- Dark theme CSS variables in `frontend/src/app/globals.css`
- `frontend/src/components/AppShell.tsx` auth gate logic (will be kept, inner layout rewritten)
- Existing routes: `/` (chat), `/repos`, `/graph`
- `GET /api/v1/graph/stats` endpoint (user-scoped node/edge counts)

### What needs modification 🔧
- `frontend/src/components/AppShell.tsx` — replace `<Sidebar />` with `<TopNav />` + `<GlobalBrainBar />` above `<main>`
- `frontend/src/app/page.tsx` (the current chat page at `/`) → **move to** `frontend/src/app/query/page.tsx`. The root `/` becomes a redirect to `/repos`.
- Post-login redirect in `AuthContext` and `callback/page.tsx`: `/` → `/repos`
- `frontend/src/app/globals.css` — add glassmorphism utility classes (`.glass`, `.glass-strong`, backdrop-filter)

### What is net-new 🆕
- `frontend/src/components/TopNav.tsx` — floating glassmorphism bar with routes `Dashboard (/repos)`, `Query (/query)`, `Knowledge Graph (/graph)` + user avatar/logout menu on the right
- `frontend/src/components/GlobalBrainBar.tsx` — horizontal stats strip: Total Chunks, Total Graph Nodes, Repos Indexed, Active Queries (placeholder)
- `backend/api/routes.py` — `GET /api/v1/stats/global` endpoint returning `{chunks, nodes, repos, relationships}` scoped to the authenticated user
- `frontend/src/app/page.tsx` — minimal file that just redirects to `/repos`

### What to delete 🗑
- `frontend/src/components/Sidebar.tsx` (move user menu logic into `TopNav` before deleting)

### Files touched
- 🔧 `frontend/src/components/AppShell.tsx`
- 🔧 `frontend/src/app/globals.css`
- 🔧 `frontend/src/app/page.tsx` (replaced with redirect)
- 🔧 `backend/api/routes.py`
- 🆕 `frontend/src/components/TopNav.tsx`
- 🆕 `frontend/src/components/GlobalBrainBar.tsx`
- 🆕 `frontend/src/app/query/page.tsx` (moved from current `/`)
- 🗑 `frontend/src/components/Sidebar.tsx`

### How you test
1. Log in → land on `/repos` automatically.
2. Top of page shows floating glass bar with 3 links + your avatar/logout.
3. Below nav: a stats row showing real numbers pulled from Qdrant + Neo4j.
4. Click each nav link — routes to `/repos`, `/query`, `/graph` correctly with active-state highlight.
5. Glass blur effect visible over colored background — not just a flat dark bar.

### Acceptance gate
- ✅ No sidebar visible anywhere
- ✅ Global Brain numbers match what's actually in your databases
- ✅ Hitting `/` auto-redirects to `/repos`

---

## Phase 3 — Repo Manager Overhaul (Vercel Dropdown + Public URL + Quick Prompts)

**Status:** [⏳] Code complete — awaiting user verification
**Depends on:** Phase 1 ✅ (needs server-side GitHub token), Phase 2 ✅ (shell)
**Architecture ref:** Section 2.3, 2.4, 2.5

### What already exists ♻
- `POST /api/v1/ingest` — full ingestion pipeline (reuse unchanged)
- `GET /api/v1/repos` — list indexed repos
- `DELETE /api/v1/repos/{owner}/{name}` — delete
- `backend/ingestion/github_client.py` with `httpx` + rate limiter
- Snapshot + audit endpoints (reused in drawer, Phase 4/9)

### What needs modification 🔧
- `frontend/src/app/repos/page.tsx` — full rewrite of the UI:
  - Remove manual `owner/repo` text input
  - Replace with two-tab panel: "My Repositories" (dropdown) + "Public URL"
  - Replace flat list rows with proper Repo Cards
  - Remove the center-screen modal (snapshot/audit results move to drawer in Phase 4)
- Card actions: Snapshot / Audit / Delete — same endpoints, just wired into cards

### What is net-new 🆕
- `backend/api/routes.py` — `GET /api/v1/github/my-repos` → uses `get_github_token_for_user()` to list the authenticated user's GitHub repos (name, full_name, private, language, stars, default_branch)
- `backend/ingestion/github_client.py` — new method `list_user_repos()` (paginated `/user/repos`)
- `frontend/src/app/utils/parseRepoUrl.ts` — util: extracts `owner/repo` from any GitHub URL variant
- `frontend/src/components/RepoCard.tsx` — card UI with Quick Prompts section
- `frontend/src/components/QuickPrompts.tsx` — renders 3–4 buttons; on click navigates `router.push('/query?repo=X&q=...&autorun=1')`
- `frontend/src/app/utils/quickPrompts.ts` — curated prompt list (per language or generic)
- `frontend/src/app/query/page.tsx` — must read `?repo` / `?q` / `?autorun` and auto-execute on mount (wired here, built fully in Phase 5)

### Files touched
- 🔧 `backend/api/routes.py`
- 🔧 `backend/ingestion/github_client.py`
- 🔧 `frontend/src/app/repos/page.tsx`
- 🔧 `frontend/src/app/query/page.tsx` (add URL-param autorun)
- 🆕 `frontend/src/app/utils/parseRepoUrl.ts`
- 🆕 `frontend/src/app/utils/quickPrompts.ts`
- 🆕 `frontend/src/components/RepoCard.tsx`
- 🆕 `frontend/src/components/QuickPrompts.tsx`

### How you test
1. On `/repos`, see two clearly separated input modes: a dropdown of your real GitHub repos, and a URL paste field.
2. Dropdown lists at least 10 of your actual repos (private ones present if you OAuth'd).
3. Paste `https://github.com/vercel/next.js` → URL is parsed to `vercel/next.js` → Add triggers ingest.
4. Each ingested repo shows as a card with 3–4 Quick Prompt buttons.
5. Click a Quick Prompt → navigate to `/query`, chat pane auto-sends the prompt, agent responds.
6. Snapshot / Audit / Delete buttons still work on each card.

### Acceptance gate
- ✅ No manual `owner/repo` text input anywhere
- ✅ `GET /api/v1/github/my-repos` returns your actual GitHub data
- ✅ Quick Prompt auto-execute works end-to-end

---

## Phase 4 — SSE Ingestion Streaming + Glassmorphic Slide-Out Drawer

**Status:** [⏳] Code complete — awaiting user verification
**Depends on:** Phase 3 ✅
**Architecture ref:** Section 3.5

### What already exists ♻
- `backend/ingestion/pipeline.py` — runs the full pipeline sequentially
- `backend/agents/summarizer.py` — `generate_repo_snapshot()` (called at end of ingest)
- `backend/api/routes.py` — `/ingest` endpoint (currently synchronous wait)

### What needs modification 🔧
- `backend/ingestion/pipeline.py` — instrument with a progress callback / async event emitter; do **not** restructure the pipeline itself, only add `yield` or `progress_cb(...)` calls at key checkpoints: `fetching_tree`, `fetching_files`, `chunking`, `embedding`, `upserting`, `graph_building`, `issues`, `prs`, `commits`, `snapshot`, `done`
- `backend/api/routes.py` — `/ingest` becomes a 2-step flow:
  - `POST /ingest` returns `{job_id}` immediately and starts task in background
  - `GET /ingest/stream?job_id=X` streams SSE events from the job's progress queue
- `frontend/src/app/repos/page.tsx` — trigger ingest → receive `job_id` → open `EventSource` → render toasts + progress bar → on `done` event, open drawer with snapshot

### What is net-new 🆕
- `backend/core/job_store.py` — in-memory `dict[job_id, asyncio.Queue]` for progress events + status
- `backend/api/routes.py` — `GET /ingest/stream` SSE endpoint using FastAPI `StreamingResponse`
- `frontend/src/components/Drawer.tsx` — right-side slide-out, glassmorphic, `open/close` state, generic children
- `frontend/src/components/IngestToasts.tsx` — live progress toasts fed by SSE events
- `frontend/src/lib/sse.ts` — thin `EventSource` wrapper with auto-cleanup

### Files touched
- 🔧 `backend/ingestion/pipeline.py`
- 🔧 `backend/api/routes.py`
- 🔧 `frontend/src/app/repos/page.tsx`
- 🆕 `backend/core/job_store.py`
- 🆕 `frontend/src/components/Drawer.tsx`
- 🆕 `frontend/src/components/IngestToasts.tsx`
- 🆕 `frontend/src/lib/sse.ts`

### How you test
1. Click Add on a repo → toasts appear in sequence: "Fetching tree", "Chunking 250/1400", "Embedding", "Graph building", "Done".
2. The ingest API call returns immediately (<2s), not after 30s.
3. When the `done` event fires, a glass drawer slides in from the right with the architectural snapshot.
4. Close drawer, reopen later via Snapshot button on the card → same drawer, same content (cached from Neo4j).
5. Clicking Audit opens the same drawer with the audit report in place of snapshot.

### Acceptance gate
- ✅ No static "this may take a few minutes" text
- ✅ SSE stream delivers ≥ 6 distinct progress events per ingest
- ✅ Drawer smoothly animates (no layout shift of main content)

---

## Phase 5 — Dual-Pane Query Workspace + Canvas State Machine

**Status:** [ ] Not started
**Depends on:** Phase 2 ✅
**Architecture ref:** Section 6.1

### What already exists ♻
- Current chat UI logic in the file moved to `/query/page.tsx` (input, history, message list, send)
- `POST /api/v1/agent_query` endpoint
- `MarkdownMessage.tsx` — markdown renderer

### What needs modification 🔧
- `frontend/src/app/query/page.tsx` — restructure into a two-pane flex layout: left chat column, right Canvas column
- Introduce a shared state container (React Context or Zustand — prefer a small Context) that holds `canvasView` + `canvasPayload`

### What is net-new 🆕
- `frontend/src/components/canvas/Canvas.tsx` — host that renders one of three views based on state
- `frontend/src/components/canvas/CodeView.tsx` — Shiki-based code viewer with line numbers + highlight ranges (Monaco later if needed)
- `frontend/src/components/canvas/GraphView.tsx` — wraps existing `GraphViewer` (moved in Phase 8)
- `frontend/src/components/canvas/AuditView.tsx` — markdown report renderer
- `frontend/src/context/CanvasContext.tsx` — `{ view: 'empty'|'code'|'graph'|'audit', payload }` + setter
- `frontend/src/components/canvas/EmptyState.tsx` — initial Canvas placeholder
- `frontend/src/components/ResizeHandle.tsx` — draggable vertical divider

### Files touched
- 🔧 `frontend/src/app/query/page.tsx`
- 🆕 `frontend/src/context/CanvasContext.tsx`
- 🆕 `frontend/src/components/canvas/*`
- 🆕 `frontend/src/components/ResizeHandle.tsx`

### How you test
1. `/query` shows left chat + right Canvas.
2. Canvas starts in empty state.
3. Manually toggle view via a test button → CodeView shows a sample file with Shiki highlighting; GraphView shows the 3D graph; AuditView shows markdown.
4. Drag the divider → both panes resize smoothly, no jank.

### Acceptance gate
- ✅ Both panes independently scrollable
- ✅ Canvas view state persists across messages within the session

---

## Phase 6 — Citation JSON → Ghost Highlight Handshake

**Status:** [ ] Not started
**Depends on:** Phase 5 ✅
**Architecture ref:** Section 6.2

### What already exists ♻
- `backend/agents/supervisor.py` — LangGraph runner
- `MarkdownMessage.tsx` — rendered markdown with code blocks
- Qdrant has chunks with `file_path`, `start_line`, `end_line`, `full_body` metadata

### What needs modification 🔧
- `backend/agents/supervisor.py` — update `SYSTEM_PROMPT` to enforce a citation JSON schema in the answer stream. Agent must emit, inline:
  `<cite file="path/to/file.py" lines="45-87" />` (XML-style for easy streaming parse) OR a json fence block. Pick one and document it.
- `backend/api/routes.py` — convert `POST /agent_query` to a streaming response (`StreamingResponse` / SSE) that chunks tokens as they're produced
- `frontend/src/app/query/page.tsx` — switch to streaming fetch (`ReadableStream` or `EventSource`), accumulate tokens, detect citation tags on-the-fly

### What is net-new 🆕
- `backend/api/routes.py` — `GET /api/v1/file?repo=X&path=Y` that assembles the full file content from Qdrant chunks (preferring `full_body` when present, else `text`)
- `frontend/src/lib/citationParser.ts` — streaming state machine that extracts `<cite .../>` tokens mid-stream and emits citation events
- `frontend/src/components/CitationPill.tsx` — inline clickable pill rendered in the chat message where the citation appeared
- On citation detected OR clicked → dispatches to `CanvasContext` → Canvas switches to `CodeView`, loads file, scrolls to `lines`, renders ghost highlight

### Files touched
- 🔧 `backend/agents/supervisor.py`
- 🔧 `backend/api/routes.py` (streaming)
- 🔧 `frontend/src/app/query/page.tsx`
- 🔧 `frontend/src/components/canvas/CodeView.tsx` (highlight range support)
- 🆕 `frontend/src/lib/citationParser.ts`
- 🆕 `frontend/src/components/CitationPill.tsx`

### How you test
1. Ask "where is the JWT decoding done?"
2. Tokens stream into chat left-to-right (not a batched dump).
3. Mid-answer, a citation pill appears like `auth.py:73-86`.
4. Canvas auto-swaps to CodeView and scrolls to lines 73–86 of `auth.py`, with a soft yellow highlight.
5. Click a different citation later → Canvas jumps to the new file/lines.
6. If the agent cites a file that doesn't exist in Qdrant → Canvas shows a clear "file not indexed" state, no crash.

### Acceptance gate
- ✅ Streaming works (first token visible in < 2s)
- ✅ At least one citation auto-opens in CodeView without any user click
- ✅ Ghost highlight renders on the correct line range

---

## Phase 7 — Agent Tools Refactor to "Big 7" + Best Effort Circuit Breaker

**Status:** [ ] Not started
**Depends on:** Phase 1 ✅ (user context); can run in parallel with Phase 5/6
**Architecture ref:** Section 5.2, 5.3, 5.4

### What already exists ♻
- `backend/agents/supervisor.py` — LangGraph state machine, `agent_node`, `critic_node`, `loop_count` tracked
- `backend/agents/tools.py` — 8 tools: `search_code`, `search_issues`, `get_file_content`, `get_call_graph`, `get_file_history`, `get_dependencies`, `calculate_math`, `ask_human_for_clarification`
- Qdrant stores `large_function: True` flag + `full_body` payload

### What needs modification 🔧
- `backend/agents/tools.py`
  - **Remove from `ALL_TOOLS`:** `search_issues`, `calculate_math`, `ask_human_for_clarification` (keep the functions; they're off the hot path)
  - **Modify `get_file_content`:** when called in "outline" mode, it already produces a structure-ish view — repurpose this for the new `get_file_structure` role or split
  - **Modify `search_code`:** ensure when a hit has `large_function: True` the result string visibly flags it so the agent knows to call `fetch_full_implementation`
- `backend/agents/supervisor.py`
  - Add a new node: `best_effort_node` — synthesizes a transparent "partial answer" from accumulated ToolMessages in state, with disclaimer text
  - Modify `route_from_critic` → when `loop_count >= 3`, route to `best_effort_node` → `END` instead of looping
  - Modify `critic_node` prompt to explicitly check: "did the agent answer about a function flagged `large_function` without calling `fetch_full_implementation`? If so, hallucination."

### What is net-new 🆕
- `backend/agents/tools.py`:
  - `fetch_full_implementation(repo, file_path, function_name)` → Qdrant search with filter `{large_function: True, ...}` → return `full_body`
  - `get_file_structure(repo)` → Neo4j query `MATCH (r:Repository {full_name: $repo})-[:CONTAINS]->(f:File) RETURN f.path ORDER BY f.path` → return directory-tree-formatted string
  - `run_security_audit(repo)` → calls the (Phase 9) auditor pipeline and returns its cached report
- Update `ALL_TOOLS` to the exact Big 7:
  1. `search_code`
  2. `get_call_graph`
  3. `get_dependencies`
  4. `fetch_full_implementation`
  5. `run_security_audit`
  6. `get_file_structure`
  7. `get_file_content`

### Files touched
- 🔧 `backend/agents/tools.py`
- 🔧 `backend/agents/supervisor.py`

### How you test
1. Ask a complex multi-step question → inspect backend logs → tool sequence uses only Big 7.
2. Ask about a known 150+ line function → agent must call `fetch_full_implementation` (visible in logs). If it doesn't, critic catches it.
3. Ask a deliberately impossible question → watch `loop_count` increment → at 3, `best_effort_node` triggers and returns a clearly-labeled partial answer instead of looping.
4. `ALL_TOOLS` list in `tools.py` has exactly 7 entries.

### Acceptance gate
- ✅ No infinite loops under any query
- ✅ Best Effort fallback text is visibly different from a normal answer
- ✅ Large-function critic rule triggers at least once in a targeted test

---

## Phase 8 — 3D Graph Embedded in Canvas + Contextual Pulse

**Status:** [ ] Not started
**Depends on:** Phase 5 ✅, Phase 7 ✅
**Architecture ref:** Section 6.3

### What already exists ♻
- `frontend/src/components/GraphViewer.tsx` — full 3D graph with react-force-graph-3d, node click → detail panel, repo selector, search bar
- `GET /api/v1/graph/explore` — Neo4j neighborhood query
- `GET /api/v1/graph/stats`

### What needs modification 🔧
- `frontend/src/components/GraphViewer.tsx`
  - Replace right-side detail panel with a compact floating card (panel conflicts with dual-pane layout)
  - Add `onNodePulse(node)` prop; on node click trigger a pulse animation + call the prop
  - Accept a `repo` prop so it can be driven by the host instead of its own state (standalone `/graph` page keeps current self-driving behavior via default prop)
- `frontend/src/app/graph/page.tsx` — unchanged (still standalone). `GraphView.tsx` (the Canvas variant) wraps `GraphViewer` with the pulse handler
- `frontend/src/components/canvas/GraphView.tsx` — on `onNodePulse`, inject a system message into the chat: "Summarize the role of `<node.name>` (`<node.type>`) in `<repo>`" and auto-send

### What is net-new 🆕
- Pulse animation CSS (keyframes) in `globals.css`
- Cross-component bridge: `CanvasContext` already holds chat-pane state OR add a new `ChatInjectionContext` for canvas → chat messaging

### Files touched
- 🔧 `frontend/src/components/GraphViewer.tsx`
- 🔧 `frontend/src/app/globals.css`
- 🔧 `frontend/src/components/canvas/GraphView.tsx`
- 🔧 `frontend/src/context/CanvasContext.tsx` (add injection helper)

### How you test
1. In `/query`, switch Canvas to Graph view.
2. Click any File node → node visibly pulses → chat pane receives an auto-message summarizing that module.
3. Standalone `/graph` page still works exactly as before (regression check).

### Acceptance gate
- ✅ Node click triggers exactly one agent summary, no duplicates
- ✅ Pulse animation visible for ~600ms
- ✅ Standalone `/graph` page unregressed

---

## Phase 9 — Proactive Security Auditor (3-Step Pipeline)

**Status:** [ ] Not started
**Depends on:** Phase 7 ✅ (tool wrapper), Phase 4 ✅ (drawer for display)
**Architecture ref:** Section 4

### What already exists ♻
- `backend/api/routes.py` — `POST /api/v1/repos/{owner}/{name}/audit` currently just invokes `run_agent()` with an audit prompt (not the deterministic 3-step pipeline)
- `backend/agents/summarizer.py` — pattern for LLM-on-graph summary (reference for implementation style)
- `AuditResponse` schema

### What needs modification 🔧
- `backend/api/routes.py` `/audit` endpoint → call new `SecurityAuditor` class instead of `run_agent` directly; return cached report if `last_audit_report` already present on Repository node (unless `?force=true`)
- Existing audit response schema stays; just the implementation changes

### What is net-new 🆕
- `backend/agents/auditor.py` → `SecurityAuditor`:
  1. **Recon (Neo4j):** Cypher queries for:
     - Files whose imports contain DB driver names (`sqlalchemy`, `psycopg2`, `mysql`, `pymongo`, `redis`)
     - Files whose path or function names match `auth`, `jwt`, `verify`, `session`, `token`, `password`, `admin`
     - Functions annotated as API route handlers (heuristic: decorators `@app.get`, `@app.post`, `@router.*`, Express `app.get/post`)
     - Output: deduped list of `{file_path, function_name, reason}`
  2. **Extraction (Qdrant):** For each identified hit, pull the chunk(s) with matching `file_path` + `function_name`. Cap at ~20 chunks total.
  3. **Interrogation (LLM):** Single Groq call with an OWASP-focused system prompt; return structured markdown report with risk levels.
- `backend/indexing/graph_builder/neo4j_manager.py` — new helper method(s) if needed for the recon queries
- Persist result: `SET r.last_audit_report = $report, r.last_audit_at = $timestamp` on the Repository node
- Tool wrapper `run_security_audit` in `tools.py` (Phase 7) calls this

### Files touched
- 🔧 `backend/api/routes.py`
- 🆕 `backend/agents/auditor.py`
- 🔧 `backend/agents/tools.py` (wire tool to auditor)
- 🔧 `backend/indexing/graph_builder/neo4j_manager.py` (optional helper)

### How you test
1. Click Audit on a freshly ingested repo → drawer opens, status "Auditing…", backend logs show 3 distinct phases (recon N files, extraction M chunks, 1 LLM call).
2. Report renders in `AuditView` inside the drawer with risk-level sections.
3. Click Audit again on same repo → opens instantly from cache (no LLM call in logs).
4. Append `?force=true` → re-runs pipeline, updates cached report.
5. Agent tool `run_security_audit` called from chat (`/query`) returns the same content.

### Acceptance gate
- ✅ Three deterministic phases observable in logs
- ✅ Cached path is instant (< 500ms)
- ✅ Report mentions at least one specific file path from the repo

---

## Phase 10 — Zero-Residual Deletion + Session Termination Hardening

**Status:** [ ] Not started
**Depends on:** Phase 1 ✅
**Architecture ref:** Section 7, Section 8 Scrub Gate

### What already exists ♻
- `DELETE /api/v1/repos/{owner}/{name}` — deletes from Qdrant + Neo4j with user ownership check
- `VectorStore.delete_by_repo()`
- Current `logout()` in `AuthContext` clears localStorage

### What needs modification 🔧
- `backend/api/routes.py` `/repos/{owner}/{name}` DELETE:
  - After deletion, run a **post-check**: count any remaining points in Qdrant with this `repo_id` AND any remaining nodes in Neo4j with this `repo` property. If non-zero, return 500 with details (instead of silent success).
  - Return `{deleted_chunks: N, deleted_nodes: M}` in response
- `backend/api/auth_routes.py` — `POST /auth/logout` (added in Phase 1) → also destroys session_store entry for `user_id`
- `frontend/src/app/repos/page.tsx` — replace browser `confirm()` with a proper modal: "This permanently deletes `X` from Cortex. Type the repo name to confirm."

### What is net-new 🆕
- `frontend/src/components/ConfirmDeleteModal.tsx` — styled confirmation requiring typed repo name
- Backend `verify_zero_residual(repo, user_id)` helper in `qdrant_store.py` / `neo4j_manager.py`

### Files touched
- 🔧 `backend/api/routes.py`
- 🔧 `backend/api/auth_routes.py`
- 🔧 `backend/indexing/qdrant_store.py`
- 🔧 `backend/indexing/graph_builder/neo4j_manager.py`
- 🔧 `frontend/src/app/repos/page.tsx`
- 🆕 `frontend/src/components/ConfirmDeleteModal.tsx`

### How you test
1. Delete a repo → modal forces you to type the name exactly.
2. Response body shows `{deleted_chunks: N, deleted_nodes: M}` with real numbers.
3. Immediately query Qdrant dashboard filtered by that `repo_id` → zero points.
4. In Neo4j Browser run `MATCH (n {repo: "X"}) RETURN count(n)` → 0.
5. Sign out → cookie gone, server-side session entry gone, `/auth/me` returns 401.

### Acceptance gate
- ✅ Deletion response includes real counts
- ✅ Post-check finds zero residual in both DBs
- ✅ Logout purges server-side session, not just client state

---

## Post-Launch Backlog (Not in Phase Scope)

- Streaming tokens character-by-character (already partial in Phase 6)
- Monaco editor upgrade from Shiki (richer code interactions)
- Redis-backed session store (replace dict)
- Per-user rate limiting on agent endpoint
- Telemetry on tool usage patterns
- Export subgraph as JSON/PNG
- Mobile responsive (current scope is desktop 1440px+)

---

## Quick Reference — New / Changed Endpoints

| Method | Path | Phase | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/logout` | 1 | 🆕 clears cookie + session |
| GET | `/api/v1/auth/me` | 1 | ♻ reused, now cookie-auth |
| GET | `/api/v1/stats/global` | 2 | 🆕 for Global Brain bar |
| GET | `/api/v1/github/my-repos` | 3 | 🆕 user's GitHub repo list |
| GET | `/api/v1/ingest/stream` | 4 | 🆕 SSE progress |
| POST | `/api/v1/ingest` | 4 | 🔧 returns `{job_id}` instead of blocking |
| GET | `/api/v1/file` | 6 | 🆕 reconstruct file from chunks for CodeView |
| POST | `/api/v1/agent_query` | 6 | 🔧 becomes streaming |
| POST | `/api/v1/repos/{o}/{r}/audit` | 9 | 🔧 uses 3-step pipeline + cache |
| DELETE | `/api/v1/repos/{o}/{r}` | 10 | 🔧 returns residual counts |

---

*Cortex v2 Tracker — created 2026-04-20. Update after every completed phase.*
