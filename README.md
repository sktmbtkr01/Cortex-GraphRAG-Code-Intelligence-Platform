# 🌌 Cortex: AI-Powered Repository Intelligence

**Cortex** is a production-grade codebase analysis engine designed to bridge the gap between AI/ML logic and full-stack SaaS infrastructure. It translates complex, multi-tenant repositories into interactive, 3D architectural maps by fusing **GraphRAG** (Knowledge Graphs + Vector Search) with a stateful, multi-agent **Supervisor-Critic** loop.

Unlike standard RAG tools that treat code as flat text, Cortex understands the **structural hierarchy** of software, enabling deterministic interrogation of imports, function calls, and security vulnerabilities.

---

## 🏗️ System Design Philosophy: The "Twin-Engine" Model

Cortex operates on a dual-database backbone that separates **Semantic Meaning** from **Structural Fact**.

### 1. Semantic Anchoring (Qdrant)
* **High-Dimensional Embeddings**: Chunks are converted into 768-dimensional dense vectors using **Google’s text-embedding-004**.
* **Privacy-First Stamping**: Every vector payload is hard-stamped with the session's `user_id` and the `repo` identifier to ensure strict row-level isolation and prevent cross-tenant data bleed.
* **Contextual Discovery**: Vector search is utilized for "conceptual neighborhoods," finding relevant logic even when keywords do not match exactly.

### 2. Structural Mapping (Knowledge Graph)
* **AST Static Analysis**: A native Python analyzer traces the Abstract Syntax Tree (AST) to map imports and function calls without relying on LLM inference.
* **Deterministic Relationships**: Nodes represent Files, Classes, and Functions, connected by structural edges such as `[:IMPORTS]`, `[:CALLS]`, and `[:DEPENDS_ON]`.
* **Relational Expansion**: The graph provides the logical "map" that vector search misses, allowing the AI to trace execution paths across the entire repository.



---

## 🧠 Multi-Agent Orchestration (LangGraph)

Cortex utilizes **LangGraph** to govern a multi-agent retrieval team, moving beyond simple one-shot prompts into an iterative, self-correcting "reasoning" workflow.

### The Supervisor-Critic Duo
* **The Supervisor Node**: Acts as the strategist; it analyzes user queries, selects optimal sequences from the system's "Big 7" tools, and drafts responses.
* **The Critic Node**: Acts as a quality gatekeeper; it reviews drafts for hallucinations, specifically verifying that the Supervisor has not "guessed" logic for large functions without fetching the full implementation.
* **Deterministic Circuit Breaker**: To prevent infinite agent loops and API credit exhaustion, a `loop_count` state variable triggers a **"Hard Stop"** after 3 failed consensus attempts, routing to a "Best Effort" fallback node.



### The Autonomous Security Auditor
* **Proactive Watchdog**: An independent agent that performs "Targeted Sweeps" without user interaction.
* **Structural Reconnaissance**: Uses Neo4j to identify high-risk nodes like API route handlers and database drivers.
* **Deep-Reasoning Interrogation**: Audits code chunks for OWASP vulnerabilities (SQLi, XSS, Logic Flaws) and saves reports directly to the Neo4j `Repository` node for instant retrieval.

---

## 🏭 The Ingestion Factory (Phase C)

Our ingestion pipeline is engineered for high-performance and absolute security.

* **RAM-Only Lifecycle**: Repository data is fetched and processed entirely in RAM; code exists as Python variables for the duration of chunking and is instantly garbage-collected, ensuring no proprietary source files are written to the server's disk.
* **AST Smart Slicer**: Utilizes **Tree-sitter** for structural awareness. We implement a **"150-Line Rule"**: standard functions are embedded fully, while functions exceeding 150 lines are truncated to "Skeletons" (signature + docstring) in the vector space to prevent semantic dilution.
* **Security Censor**: A pre-processing gatekeeper scans raw text for exposed credentials (AWS keys, tokens) and redacts them prior to database upsertion.
* **SSE Progress Streaming**: Progress is streamed via Server-Sent Events (SSE) to the frontend, providing real-time status updates on the chunking and embedding process.

---

## 🎨 Visualization & UX (Phase F)

* **3D Universe View**: A high-performance WebGL engine (Three.js) renders the codebase as a force-directed map where node size corresponds to structural centrality.
* **Dual-Pane Handshake**: AI-generated citations (JSON-parsed) trigger the UI to automatically load the target file in the editor, scroll to context, and apply "Ghost Highlights" to the exact line range.
* **The "Global Brain" Metrics**: A glassmorphism stats ticker displays live database counts (Total Nodes, Semantic Vectors, and Analyzed LoC).

---

## 🚥 Surgical Verification Protocol (Section 8)

Cortex was built using a five-gate "Hard Stop" framework to ensure system integrity:
* **Gate 1 (Identity)**: JWT persistence and HttpOnly cookie security.
* **Gate 2 (The Factory)**: Validation of AST-based node generation and dual-routing logic.
* **Gate 3 (The Brain)**: Verification of the Supervisor-Critic loop and Circuit Breaker safety.
* **Gate 4 (UI Handshake)**: Real-time citation-highlighting and 3D graph synchronization.
* **Gate 5 (The Scrub)**: Complete data erasure verification upon repository deletion.

---

## 🛡️ Privacy & Teardown

We adhere to a **Zero-Residual Data** philosophy:
* **Ownership Validation**: Deletion requests are strictly verified against the session's identity.
* **Surgical Purge**: Executes `DETACH DELETE` in Neo4j and `delete_points` in Qdrant to remove all structural and semantic traces of the repository.
* **Session Termination**: Sign-out clears all `HttpOnly` cookies and invalidates the JWT.

---

## 🛠️ Technical Stack

| Category | Technology |
| :--- | :--- |
| **Frontend** | Next.js, Three.js, Shiki/Monaco, Tailwind CSS |
| **Backend** | FastAPI, LangGraph, Tree-sitter |
| **Databases** | Neo4j (Graph), Qdrant (Vector) |
| **Inference** | Groq (Llama 3.3), Google GenAI (Embeddings) |
| **Security** | JWT, HttpOnly Cookies, GitHub OAuth |

## 📄 License
This project is licensed under the MIT License.