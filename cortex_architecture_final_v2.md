# Cortex Architecture & Implementation Specification

> **System Prompt / Note for AI Agents:** This document outlines the step-by-step user flows, technical requirements, and architectural decisions for the Cortex platform. It is designed to bridge the gap between AI/ML logic and full-stack SaaS infrastructure.

## Section 1: Authentication & Global Entry (Phase A)

### 1.1 Core Concept: What is Authentication?
Authentication (AuthN) is the process of verifying the identity of the user accessing the Cortex platform. In a multi-tenant AI system, it acts as the primary gatekeeper before any graph traversal or vector search occurs.

### 1.2 Why Cortex Needs Authentication
For an Agentic AI platform like Cortex, auth solves three critical infrastructure problems:
1. **Data Isolation (Row-Level Security):** Users will index proprietary codebases into Qdrant (vectors) and Neo4j (graph). Authentication ensures a user's prompt only retrieves chunks and nodes tagged with their specific `user_id`, physically preventing cross-tenant data bleed.
2. **Rate Limiting & API Cost Control:** LLM inferences (Groq/Gemini) are expensive. Auth tracks usage per user to prevent API exhaustion and rate-limit abuse.
3. **State Management:** It allows the LangGraph supervisor to remember user context, establishing ownership over ingested repositories and chat history.

### 1.3 Supported Authentication Methods
Cortex supports two entry paths at the `/login` route:

* **Guest Mode ("Explore as Guest"):** * *Flow:* User enters a guest moniker. The backend generates a random `guest:uuid`, mints a JSON Web Token (JWT), and passes it back to the client.
    * *Purpose:* Low-friction entry allowing users to explore the "Global Public Pool" of pre-indexed open-source repositories without linking a formal account.
* **GitHub OAuth ("Continue with GitHub"):**
    * *Flow:* Industry-standard secure login. Users delegate identity verification directly to GitHub.
    * *Purpose:* Grants Cortex the necessary permissions to securely fetch, ingest, and query the user's private repositories.

### 1.4 The GitHub OAuth Technical Flow (Next.js + FastAPI)
Because Cortex utilizes a decoupled architecture, Authentication bridges the frontend (Next.js) and the AI backend (FastAPI) using `NextAuth.js` and stateless JWTs.

1. **The Handshake:** The user clicks "Login w/ GitHub" on the Next.js UI. NextAuth redirects them to GitHub's authorization server.
2. **The Approval:** The user approves the Cortex application. GitHub redirects the browser back to the Cortex Callback URL, appending a temporary Auth Code.
3. **The Token Exchange:** The Next.js server silently trades this Auth Code with GitHub in exchange for an Access Token and profile data.
4. **The Session Mint:** Next.js generates a secure User Session and stores a cryptographically signed JWT inside an `HttpOnly` browser cookie.
5. **The AI Verification:** Every time the user sends a message to the LangGraph chat UI, the browser attaches this cookie. The FastAPI backend intercepts the request, mathematically verifies the JWT's signature, extracts the `user_id`, and safely processes the RAG/Graph retrieval using that isolated identity.

---

## Section 2: The Dashboard & Repository Manager (Phase B)

### 2.1 UX Overhaul: Glassmorphism Nav & Global Brain
* **Top Navigation:** The platform uses a floating, glassmorphism top navigation bar containing the core routes: `Dashboard`, `Query`, and `Knowledge Graph`. This frees up maximum screen width for the code editors and 3D graphs.
* **The "Global Brain" Metrics:** Right below the top nav is a sleek stats row showing exactly what is sitting in the databases at that moment (e.g., Total Vector Chunks, Total Graph Nodes, Active Connections). This visually proves the massive data engineering happening under the hood.

### 2.2 The Landing State
Once a user successfully authenticates, the system routes them directly to the **Repository Manager** (`/repos`) instead of the Chat interface. A LangGraph agent needs context to function. By forcing the user to land on the Repo Manager first, we guarantee they put some "books on the shelves" (into Qdrant/Neo4j) before they try to ask the librarian any questions.

### 2.3 Feature 1: The "Vercel-Style" Private Repo Dropdown
**Concept:** Allow users to select their own GitHub repositories from a UI dropdown with a single click.
**How it works:**
1. **The Fetch:** When the `/repos` page loads, the frontend uses the user's ephemeral GitHub Access Token (secured during login) to make a silent API call to GitHub for their repository list.
2. **The UI:** This list is mapped into a dropdown menu.
3. **The Handoff:** When the user selects a repo and clicks "Ingest", Next.js sends that repo name and the user's token to the FastAPI backend.
4. **The Ingestion:** The backend uses that token to bypass GitHub's private repository walls and ingest the code.

### 2.4 Feature 2: The Public URL Input
**Concept:** Allow users to paste a direct URL to any public GitHub repository (e.g., `https://github.com/facebook/react`) to explore open-source code.
**How it works:**
1. **The Parser:** When the user pastes a URL, the frontend extracts just the `owner/repo` format.
2. **The Handoff:** The frontend sends this to the FastAPI backend. Because it's public, it does *not* need the user's personal token.
3. **The Proxy:** To avoid strict GitHub rate limits on unauthenticated requests, the backend uses the developer's server-side `GITHUB_PAT` (Personal Access Token). This allows the server to download thousands of files rapidly without hitting limits.

### 2.5 Repo Cards & Quick Prompts
Successfully ingested repositories appear as interactive cards on the dashboard.
* **Actions:** Users can Audit, Snapshot, or Delete the repo.
* **Quick Prompts:** Each card features 3-4 pre-written prompts (e.g., "Explain the architecture", "Find API endpoints"). Clicking one immediately transitions the user to the `Query` page and auto-executes the LangGraph retrieval chain for that specific repository, reducing friction.

## Section 3: The Ingestion Pipeline (Phase C)

### 3.1 Architectural Philosophy: In-Memory Processing
Cortex fundamentally rejects disk-based repository cloning (e.g., downloading `.zip` files to the server's hard drive). This mitigates significant multi-tenant security risks and eliminates disk I/O bottlenecks.
* **The Mechanism:** The FastAPI backend utilizes the GitHub API to fetch repository file trees and raw file contents entirely into RAM (Random Access Memory).
* **Ephemeral Lifecycle:** Code exists as Python variables strictly for the duration of the chunking and embedding process, after which it is instantly garbage-collected.

### 3.2 Pre-Processing: Filtering & Security Censorship
Before semantic parsing begins, the raw code passes through a strict pre-flight gatekeeper:
1. **The Bouncer (Heuristics):** Ignores non-informational files based on path/extension (e.g., `node_modules/`, `.git/`, `*.min.js`, binary files, and files > 500KB).
2. **The Censor (Regex Secret Scanner):** Scans raw text for exposed credentials (AWS keys, OpenAI tokens, GitHub PATs). Detected secrets are aggressively replaced with `[REDACTED]` prior to embedding to prevent credential leakage into the Qdrant vector space.

### 3.3 The "Smart" Slicer (AST Chunking)
Standard RAG pipelines utilize arbitrary character-count chunking, which brutally severs code logic. Cortex utilizes **Tree-sitter** (Abstract Syntax Tree parsing) for structural awareness.
* **Functional Granularity:** Tree-sitter parses the code like a compiler, explicitly extracting `function_definition` and `class_definition` blocks. Each logically intact block becomes a single chunk.
* **Size Guardrails (The 150-Line Rule):** To prevent "semantic dilution" in large code blocks, Cortex implements a dynamic embedding strategy:
    * **Standard Chunks (≤ 150 lines):** The entire function body is embedded to capture full implementation context.
    * **Large Chunks (> 150 lines):** Only the "essence" (function name, signature, and docstring) is embedded. The metadata payload is marked with `large_function: True`, and the complete source is stored in the `full_body` field. This ensures high search precision without losing the ability to retrieve the full implementation.
* **The `module_header`:** Global variables, top-level comments, and standalone imports are swept up into a dedicated `module_header` chunk for that file. This preserves critical global context without duplicating tokens across every functional chunk.

### 3.4 The Grand Split: Dual-Database Routing
Once chunked, the pipeline forks into two parallel tracks:

**Track A: The Semantic Brain (Qdrant)**
* **Embedding:** Chunks are batched and sent to Google GenAI (`text-embedding-004`) to generate 768-dimensional dense vectors.
* **RLS Stamping:** Every payload is hard-stamped with the session's `user_id` and the `repo` identifier.
* **Upsertion:** Vectors are saved to the Qdrant cluster, optimizing for semantic natural language queries ("How does authentication work?").

**Track B: The Structural Brain (Neo4j)**
* **Native Parsing:** A secondary static analyzer runs over the Python AST using the native `ast.parse()` module (strictly LLM-free to ensure 0% hallucination and sub-20ms execution times).
* **Edge Mapping:** It identifies imports (`auth.py` -> `jwt.py`) and function callers, constructing deterministic Graph Edges (`[:IMPORTS]`, `[:CALLS]`).
* **Manifests:** Specialized parsers read `requirements.txt` or `package.json` to generate `Dependency` nodes and `[:DEPENDS_ON]` relationships.

### 3.5 Real-Time UX: Server-Sent Events (SSE) & The Slide-Out Drawer
Because the ingestion pipeline performs heavy data engineering, standard HTTP responses lead to unacceptable UX latency (e.g., a static 30-second loading spinner). 
* **SSE Stream:** The Next.js frontend opens an SSE connection to FastAPI (`GET /api/v1/ingest/stream`). FastAPI streams deterministic progress updates (`{"status": "chunking", "progress": "250/1400"}`) mapped to dynamic toast notifications.
* **The Architectural Snapshot:** Upon pipeline completion, a background LLM process analyzes Neo4j centrality metrics to generate a Markdown summary of the repository. This is cached directly onto the Neo4j `Repository` node.
* **The Reveal:** Without requiring a user click, a sleek, glassmorphic right-side drawer smoothly slides open in the UI, rendering this cached snapshot to deliver immediate "wow factor" and architectural context.

## Section 4: The Autonomous Security Auditor (Phase D)

### 4.1 Concept: Agentic Intelligence vs. Standard RAG
While standard RAG is reactive (responding only to user queries), the **Security Auditor** is a proactive, autonomous agentic loop. It does not attempt to read the entire codebase in a single prompt—which would exceed LLM context windows and induce hallucinations—but instead performs a multi-step "Targeted Sweep" using the dual-database architecture.

### 4.2 The Audit Pipeline Logic
When a user triggers an audit via the Repository Card, the following asynchronous pipeline is initialized:

**Step 1: Structural Reconnaissance (Neo4j)**
The Auditor first queries the Neo4j Graph to identify the "High-Value Attack Surface." It uses deterministic Cypher queries to locate nodes with high risk-profiles, such as:
* Functions that import database drivers (SQLAlchemy, psycopg2).
* Entry points decorated with API route handlers (FastAPI `@app.get`, Express routes).
* Files containing sensitive naming conventions (e.g., `auth`, `jwt`, `verify`, `session`).
* Result: A refined list of critical file paths and function signatures, ignoring low-risk boilerplate.

**Step 2: Semantic Extraction (Qdrant)**
Utilizing the list from Step 1, the Auditor performs targeted lookups in the Qdrant Vector database. Instead of broad semantic searching, it pulls the specific code chunks associated with the high-risk nodes. This ensures the LLM receives only the most critical code logic, maintaining high signal-to-noise ratio.

**Step 3: Deep-Reasoning Interrogation (Groq/Gemini)**
The retrieved chunks are fed into a specialized LLM instance with a strict security-focused system prompt. The LLM audits the code for:
* **OWASP Top 10:** SQL Injection, Cross-Site Scripting (XSS), Insecure Direct Object References (IDOR).
* **Logic Flaws:** Missing input validation, hardcoded secrets, and insecure session management.
* **Refactoring Needs:** Potential performance bottlenecks or non-idiomatic code patterns.

### 4.3 Persistence & Visualization
* **Caching:** The resulting Markdown report is saved directly to the `Repository` node in Neo4j as a persistent property (`last_audit_report`). This ensures that subsequent views load instantly without re-invoking the LLM.
* **UI Reveal:** The report is pushed to the frontend via the same glassmorphic right-side drawer used for snapshots, providing a unified location for deep repository insights.


## Section 5: Agentic Chat Retrieval & LangGraph Supervisor (Phase E)

### 5.1 The Supervisor-Critic Architecture
The retrieval layer is governed by a **LangGraph Supervisor**, powered by high-throughput LLMs (Groq/Llama-3.3-70B). Unlike standard RAG, which performs a single vector lookup, Cortex utilizes an iterative, multi-step agentic loop to ensure high-fidelity answers.

### 5.2 Deterministic Safety: The Loop Counter & Circuit Breaker
To prevent "Infinite Loop" bugs—where an Agent and Critic enter a repetitive cycle of rejection—Cortex implements a **Deterministic Circuit Breaker** within the Graph State.
* **The `loop_count` State:** A hard-coded integer variable in the LangGraph state that tracks the number of Critic rejections.
* **The Conditional Edge:** A logic gate that intercepts the flow. If `loop_count >= 3`, the edge triggers a "Hard Stop," bypassing further tool calls to prevent API credit exhaustion and latency spikes.
* **The "Best Effort" Fallback Node:** When the circuit breaker trips, the system routes to a specialized synthesis node. This node aggregates the current retrieval context and provides a transparent "Best Effort" answer, noting that the search was capped for safety.

### 5.3 The Agent's Toolkit (The "Big 7")
The Supervisor is equipped with 7 specialized tools to interrogate the Knowledge Base. Each tool is designed to provide a specific dimension of understanding: **Meaning, Structure, or Context.**

| Tool Name | Engine | Primary Purpose |
| :--- | :--- | :--- |
| **1. `search_code`** | Qdrant | Semantic + Keyword search for logic/functionality. |
| **2. `get_call_graph`** | Neo4j | Tracing "Who calls whom" to understand execution flow. |
| **3. `get_dependencies`** | Neo4j | Identifying third-party libraries and specific versions. |
| **4. `fetch_full_implementation`** | Qdrant | Reading the 150+ lines of a "Large Function" (triggered by `large_function` flag). |
| **5. `run_security_audit`** | Both | Autonomous, multi-step hunting for vulnerabilities. |
| **6. `get_file_structure`** | OS/DB | Seeing the directory layout to provide spatial orientation. |
| **7. `get_file_content`** | OS/DB | Reading a specific file in full. Includes a **100KB Size Guardrail** to prevent context window crashes. |

### 5.4 The Multi-Turn Logic Flow
1. **Planning:** The Supervisor analyzes the query and selects the optimal tool sequence.
2. **Execution:** Tools interact with Qdrant and Neo4j.
3. **Critique:** The **Critic Node** reviews the drafted response. It specifically verifies that the Agent hasn't "guessed" the logic of a `large_function` without using Tool #4.
4. **Self-Correction:** If the Critic finds an error, the `loop_count` increments, and the Supervisor is sent back to Step 1 with a specific corrective prompt.
5. **Synthesis:** Once approved (or if the Circuit Breaker trips), the final response is streamed to the UI with line-level code citations.

## Section 6: The Visualizer & 3D Universe View (Phase F)

### 6.1 The "Dual-Pane" Orchestration & Canvas State
Cortex rejects the "Single Chat Box" paradigm in favor of a **Context-Aware Workspace**. The UI is built on a split-pane layout where the left side handles the "Conversation" and the right side—the **Canvas**—acts as a multi-modal viewer.
* **The Canvas State Machine:** The right pane is not static. It utilizes a state machine to swap between three distinct views based on the user's intent:
    * **Code View:** A high-performance editor (Monaco or Shiki) for deep-diving into specific files.
    * **Graph View:** The 3D WebGL environment for structural exploration.
    * **Audit View:** The persistent Markdown renderer for security reports.

### 6.2 The Citation-Highlight Handshake
To eliminate the "Where is this code?" friction, Cortex implements a deterministic link between the LLM output and the Canvas.
* **The JSON Bridge:** The Supervisor Agent is strictly instructed to wrap citations in a structured JSON schema (e.g., `{"cite": {"file": "auth.py", "lines": [12, 45], "node_id": "uuid-123"}}`).
* **The Interceptor:** The Next.js frontend intercepts these tokens in the stream. When a citation is detected, the Canvas automatically swaps to **Code Mode**, fetches the file, and performs a **"Ghost Highlight"** on the specified lines, scrolling the user to the exact context.

### 6.3 3D Universe View (/graph): The "Explosion" Animation
The `/graph` route is the visual heart of Cortex, translating Neo4j imports and calls into a physical, interactive space.
* **The Physics Engine:** Utilizing a 3D Force-Directed Graph (Three.js), the codebase is rendered as a "Universe" of nodes (Files, Classes, Dependencies) and edges (Imports, Calls).
* **Singular Focus:** To optimize GPU performance, Cortex renders only one repository "Universe" at a time.
* **Interactivity:** Clicking a node in 3D triggers a "Contextual Pulse," highlighting the node and prompting the Agent to summarize that specific module in the chat pane.

## Section 7: Teardown & Security Lifecycle (Phase G)

### 7.1 The "Surgical" Deletion Protocol (/repos)
Cortex adheres to a **Zero-Residual Data** policy. When a user deletes a repository:
* **Authorization:** The backend verifies that the session's `guest:uuid` owns the repository node.
* **The Neo4j Scrub:** Executes a `DETACH DELETE` Cypher query to surgically remove the repository node and every associated file, function, and relationship node.
* **The Qdrant Scrub:** Issues a `delete_points` command to the Qdrant cluster, filtering by the `repo_id`, purging all associated vector embeddings instantly.

### 7.2 Session Termination & "Ghost" Prevention
* **JWT Destruction:** Clicking "Sign Out" triggers a client-side wipe and server-side invalidation of the JWT.
* **Cookie Clearance:** The `HttpOnly` cookie is cleared, returning the user to the `/login` state and ensuring no residual access persists on the client machine.

## Section 8: The "Surgical" Verification Protocol

To prevent the "Prompt-and-Break" cycle, utilize these **Hard Stop** verification gates during implementation:

1.  **Identity Gate (Phases A & B):** Verify JWT appears in Browser -> Application -> Cookies. If the JWT isn't `HttpOnly`, do not proceed.
2.  **Factory Gate (Phase C):** After ingestion, run `MATCH (n) RETURN n` in the Neo4j Browser. If nodes aren't linked by `[:CALLS]` edges, the AST slicer is broken. Check Qdrant for the `large_function: True` flag on 150+ line blocks.
3.  **Circuit Breaker Gate (Phase E):** Ask the chat a question and block the DB connection. If it loops more than 3 times without hitting the "Best Effort" node, the LangGraph logic is unsafe.
4.  **Scrub Gate (Phase G):** Delete a repo and immediately refresh the Qdrant Dashboard. If any vectors for that `repo_id` still exist, the deletion logic is failing.
