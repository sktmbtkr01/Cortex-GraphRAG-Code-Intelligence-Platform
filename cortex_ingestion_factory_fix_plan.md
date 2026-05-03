# Cortex Ingestion Factory Fix Plan

Date: 2026-05-03

This plan turns `Cortex_Ingestion_Factory_Final_Report.md` into an implementation roadmap for the current Cortex workspace. It also includes the additional risks found during repo review: incomplete multi-tenant isolation, secret handling drift, webhook tenant gaps, stale tests, and configuration mismatch.

This document is now the execution plan plus implementation log for the ingestion factory recovery work.

---

## Current Diagnosis

### Already Mostly Working

- GitHub OAuth login now uses HttpOnly cookie auth.
- GitHub access tokens are stored server-side in `backend/core/session_store.py`.
- Frontend requests generally send `credentials: "include"`.
- Ingestion is now background-job based with SSE streaming plus polling fallback.
- Bulk GitHub blob fetching already uses a shared `httpx.AsyncClient` inside `fetch_file_contents_bulk()`.

### Still Broken Or Incomplete

- Phase 1 fixed the embedding backend: FastEmbed is installed and wired for local 768-dim embeddings.
- Older tracker docs may still contain historical Gemini/Jina embedding references.
- Retry logic exists only as manual retries for blob fetching; no consistent retry policy exists for other GitHub/network calls.
- In-memory `job_store` is vulnerable to dev reloads and process restarts.
- Multi-tenant isolation is payload-level only in some places; IDs and graph constraints are still globally shared.
- Webhook re-indexing is not tenant-aware.
- Secret handling skips whole files instead of redacting, despite docs describing a censor/redaction flow.
- Some tests are stale after auth became mandatory.

---

## Fix Principles

1. Preserve the working GitHub OAuth and cookie-session flow.
2. Keep ingestion RAM-only; do not clone or persist repository source to disk.
3. Prefer local embeddings for ingestion and query embedding to remove API-rate bottlenecks.
4. Make tenant isolation part of storage identity, not only filters.
5. Keep the first fix pass focused on reliability before broad feature expansion.
6. Add validation gates before calling a phase done.

---

## Phase 1: Embedding Backend Unification - Done

### Goal

Move dense embedding generation from Gemini API to local FastEmbed so ingestion is not capped by remote API RPM limits.

### Status

Completed on 2026-05-03.

Implemented:

- `CortexEmbedder` now uses local FastEmbed instead of Gemini embedding APIs.
- Standardized on `BAAI/bge-base-en-v1.5`.
- Kept dense vector size at 768 dimensions.
- Added `fastembed==0.7.3` to backend requirements.
- Added explicit embedding settings in `backend/core/config.py`, `.env`, and `.env.example`.
- Added `EMBEDDING_CACHE_DIR=C:\tmp\cortex_fastembed_cache`.
- Set local `.env` to `EMBEDDING_LOCAL_FILES_ONLY=true` after downloading the model cache.
- Added a Qdrant dimension guard so an existing non-768 collection fails clearly.
- Updated active README references from cloud embeddings to local FastEmbed.

Validation:

- FastEmbed dependency installed into `backend/.venv`.
- Model cache populated at `C:\tmp\cortex_fastembed_cache`.
- Local embedding smoke test returned two vectors with shape `2 x 768`.
- `compileall` passed for touched backend files.

Remaining caveat:

- If `C:\tmp\cortex_fastembed_cache` is deleted, set `EMBEDDING_LOCAL_FILES_ONLY=false` once to re-download the model, then switch it back to `true`.

### Target Files

- `backend/indexing/embedder.py`
- `backend/core/config.py`
- `backend/requirements.txt`
- `.env.example`
- `README.md`
- Any docs that mention Gemini/Jina embeddings as the current backend

### Implementation Plan

1. Done - Add `fastembed` to backend requirements.
2. Done - Update config defaults to a local embedding backend.
3. Done - Standardize on `BAAI/bge-base-en-v1.5` at 768 dimensions.
4. Done - Rework `CortexEmbedder` so `embed_batch()` uses FastEmbed locally.
5. Done - Keep `generate_sparse_vector()` for hybrid sparse search.
6. Done - Ensure query-time embedding uses the same embedder as ingestion.
7. Done - Add an explicit Qdrant collection dimension error if the existing collection does not match the configured embedding dimension.

### Important Decision

If the current Qdrant collection was created with Gemini 768-dim vectors, changing to a 384-dim local model requires either:

- Reset/recreate the Qdrant collection, or
- Use a 768-dim local model to avoid a schema reset.

Decision taken: use a 768-dim FastEmbed model first to reduce Qdrant schema disruption.

### Validation

- Done - Instantiate `CortexEmbedder()` without using Gemini embedding APIs.
- Done - Embed a small batch locally.
- Done - Confirm all vectors have the configured dimension.
- Pending - Run a full direct RAG query after a repo is ingested with the local vectors.
- Done - Confirm no Gemini embedding calls remain in ingestion/query embedding paths.

---

## Phase 2: GitHub Client Lifecycle And Retry Policy - Done

### Goal

Eliminate one-shot client usage in high-volume GitHub paths and add resilient retry/backoff to all transient network operations.

### Status

Completed on 2026-05-03.

Implemented:

- Added `tenacity==9.1.2` to backend requirements.
- Refactored `GitHubClient` to support `async with GitHubClient(...) as github`.
- Added a reusable `httpx.AsyncClient` lifecycle for ingestion jobs and other managed call sites.
- Preserved fallback safe behavior for one-off calls.
- Added retry/backoff for GitHub metadata, tree, blob, issues, PRs, PR files, commits, user repo listing, public repo listing, and webhook registration.
- Retry policy now retries transient connection/timeout errors plus HTTP `429`, `502`, `503`, and `504`.
- Retry policy does not retry hard failures like `401`, `403`, `404`, and `422`.
- Fixed `fetch_commits()` pagination so it stops when the returned page is smaller than the requested page size.
- Moved GitHub fetch concurrency, file processing concurrency, timeout, connection pool, and retry attempt defaults into settings.
- Updated ingestion to keep one shared GitHub client open for the whole repo ingest.
- Updated metadata/repo-listing routes to use the async client lifecycle.
- Updated webhook GitHub client usage and webhook registration to use the shared client/retry path.

Validation:

- `compileall` passed for Phase 2 touched backend files.
- Retry classification smoke test passed:
  - `429` retryable
  - `502`, `503`, `504` retryable
  - connection error retryable
  - `401`, `403`, `404`, `422` not retryable
- Live GitHub metadata smoke test passed with `octocat/Hello-World -> master`.

Remaining caveat:

- Full tiny/medium repo ingestion is still pending as the next end-to-end validation step. That test may uncover Qdrant/Neo4j/data issues outside Phase 2.

### Target Files

- `backend/ingestion/github_client.py`
- `backend/ingestion/pipeline.py`
- `backend/api/webhook.py`
- `backend/requirements.txt`

### Implementation Plan

1. Done - Add `tenacity` to backend requirements.
2. Done - Refactor `GitHubClient` to support an async lifecycle:
   - `async with GitHubClient(...) as github:`
   - one shared `httpx.AsyncClient` per ingestion job
   - fallback safe behavior for small one-off calls
3. Done - Apply retry/backoff to:
   - metadata fetch
   - tree fetch
   - blob fetch
   - issues
   - PRs
   - PR files
   - commits
   - user repo listing
   - webhook registration
4. Done - Retry only transient failures:
   - connection errors
   - timeouts
   - 429
   - 502/503/504
5. Done - Do not blindly retry hard failures:
   - 401/403 auth failures
   - 404 not found
   - 422 validation failures
6. Done - Fix commit pagination condition in `fetch_commits()`.
7. Done - Add bounded concurrency defaults in settings rather than hard-coding all values.

### Validation

- Done - Smoke test retry decision logic.
- Pending - Run ingest of a tiny public repo.
- Pending - Run ingest of a medium repo and confirm no per-file client creation.
- Done - Confirm failed blob fetches are logged with path and final error in the blob fetch path.
- Pending - Confirm 401/403 failures return useful user-facing errors during an authenticated ingestion attempt.

---

## Phase 3: Multi-Tenant Storage Isolation

### Goal

Make user isolation part of the identity model for both Qdrant and Neo4j, not just a payload filter.

### Status

Completed on 2026-05-03.

Implemented:

- Added `backend/core/tenant.py` for consistent tenant prefixes and scoped IDs.
- Qdrant deterministic chunk IDs now include tenant ownership before repo/path identity.
- Neo4j nodes now support tenant-scoped IDs while preserving raw human-readable properties.
- Added tenant-aware merge helpers for Neo4j nodes and relationships.
- Updated repository, file, static-analysis, issue, PR, commit, contributor, label, dependency, and module graph writes to use tenant-scoped identities.
- Updated graph stats, global stats, graph explore, snapshot generation, and agent graph tools to filter by `user_id = current_user_id OR is_public = true`.
- Updated direct RAG, summarizer, and agent vector-search paths to pass the active user context.
- Repo deletion now requires ownership and deletes only the current user's Qdrant/Neo4j data.
- Webhook file graph writes are tenant-scoped into the public namespace for now, with full tenant mapping still reserved for Phase 6.

Validation:

- `compileall` passed for backend Python files touched by Phase 3.
- Tenant smoke test passed:
  - same repo/file/chunk for `github:1` and `github:2` generated different Qdrant point IDs
  - `tenant_scoped_id("owner/repo", "github:1")` produced `github:1::owner/repo`
  - public scoped IDs use the `public::` prefix

Remaining caveats:

- Full validation still requires a development Qdrant collection reset and Neo4j graph reset/re-ingest, because old unscoped data may already be merged.
- Existing Neo4j databases may still contain old uniqueness constraints on fields like contributor login or commit sha. Resetting the development graph is the clean path before testing Phase 3 end to end.
- Webhook tenant mapping is intentionally not fully solved here; Phase 6 will make webhook mutation conservative or tenant-mapped.

### Target Files

- `backend/indexing/qdrant_store.py`
- `backend/indexing/graph_builder/neo4j_manager.py`
- `backend/indexing/graph_builder/git_graph.py`
- `backend/indexing/graph_builder/static_analyzer.py` if edge IDs are created there
- `backend/ingestion/pipeline.py`
- `backend/retrieval/rag_pipeline.py`
- `backend/agents/tools.py`
- `backend/api/routes.py`
- `backend/api/webhook.py`

### Qdrant Plan

1. Done - Include tenant ownership in deterministic point IDs.
2. Done - Preserve `is_public` as a sharing flag, but do not let public/private ingests overwrite each other.
3. Done - Ensure `delete_by_repo(repo, user_id)` only deletes that user's chunks.
4. Done - Verify all primary search paths pass `user_id`.
5. Done - Fix tool paths that call vector search without `user_id`.

### Neo4j Plan

1. Done - Introduce tenant-scoped node IDs.
   - Example: `node_id = f"{user_id}::{repo}::{path_or_symbol}"`.
2. Done - Keep human-readable properties:
   - `repo`
   - `full_name`
   - `path`
   - `name`
   - `user_id`
   - `is_public`
3. Done - Update `merge_node()` usage so all ingested nodes receive tenant metadata.
4. Done - Update Git metadata graph nodes:
   - `Issue`
   - `PullRequest`
   - `Commit`
   - `Contributor`
   - `Label`
   - `Dependency`
5. Done - Update graph queries to filter by:
   - `user_id = current_user_id OR is_public = true`
6. Done - Revisit Neo4j constraints:
   - Current constraints are globally unique by `id`.
   - If `id` becomes tenant-scoped, existing constraints can remain.
   - If keeping raw IDs, create composite uniqueness constraints where supported.

### Migration Note

Existing Qdrant points and Neo4j nodes may not be safely migratable because current IDs may already be cross-user merged. Recommended path for development:

1. Back up if needed.
2. Reset Qdrant collection.
3. Reset Neo4j graph.
4. Re-ingest after tenant-scoped IDs are implemented.

### Validation

- Pending - User A and User B ingest the same public repo.
- Done by smoke test - Qdrant contains separate point IDs per user.
- Pending real DB check - Neo4j contains separate tenant-scoped repository/file/function nodes.
- Pending real DB check - User A delete does not delete User B data.
- Pending real DB check - Guest can only see public data.
- Pending real DB check - Private repo data never appears in another user's query, graph stats, graph explore, or agent tools.

---

## Phase 4: Job Store And Dev Reload Resilience

### Goal

Make ingestion progress behavior predictable during long-running jobs and avoid false breakage from reloads.

### Status

Completed on 2026-05-03.

Implemented:

- Kept the ingestion job store in memory, matching the current development scope.
- Added explicit `queued`, `running`, `done`, `error`, and `lost` job states.
- Added an initial queued event when a job is created.
- Added capped per-job event buffering to prevent unbounded memory growth during long ingests.
- Added monotonic event cursors so polling/SSE can continue correctly after old buffered events are trimmed.
- Added configurable job-store limits:
  - `INGEST_JOB_MAX_AGE_SECONDS`
  - `INGEST_JOB_MAX_EVENTS`
- Updated missing/expired/restarted job behavior to return a `lost` event instead of a generic missing-job failure.
- Kept SSE streaming plus polling fallback in the repo ingestion UI.
- Updated the frontend ingestion event type and UI handling for `queued` and `lost`.
- Documented the development caveat: long ingestion should run without FastAPI `--reload`, because reload clears in-memory jobs.

Validation:

- Backend Python compile check passed for 48 backend files excluding `.venv`.
- Job-store smoke test passed:
  - capped event history keeps only the most recent events
  - cursor remains monotonic after trimming
  - terminal `done` state is preserved
  - missing job returns `lost`
- Frontend TypeScript check passed with `npx tsc --noEmit`.
- `npm run build` compiled the frontend successfully, then failed during the TypeScript build phase with Windows `spawn EPERM`; `npx tsc --noEmit` passed separately, so this appears environment/process-spawn related rather than a code type error.

### Target Files

- `backend/core/job_store.py`
- `backend/api/routes.py`
- frontend ingestion UI in `frontend/src/app/repos/page.tsx`
- dev docs / README

### Implementation Plan

1. Done - Keep in-memory job store for now, but document that long ingestion must run without `--reload`.
2. Done - Add clearer job states:
   - `queued`
   - `running`
   - `done`
   - `error`
   - `lost`
3. Done - Keep SSE plus polling fallback.
4. Done - Add job event cap to prevent memory growth.
5. Deferred - Consider optional Redis-backed job store later if deployment requires multi-process or reload-safe jobs.

### Validation

- Pending real ingest test - Start ingest and receive progress events.
- Pending browser/manual test - Disconnect SSE and confirm polling catches up.
- Done by missing-job path smoke - Restart/backend-lost equivalent returns a clear `lost` event.
- Pending real ingest test - No `socket.send()` crash loops from the server.

---

## Phase 5: Secret Scanner Behavior

### Goal

Align implementation with the documented "security censor" behavior.

### Status

Completed on 2026-05-03.

Implemented:

- Changed source-file ingestion from "detect secret and skip whole file" to "redact and continue".
- Added `count_secret_matches()` so the pipeline can report how many suspected secrets were censored without logging secret values.
- Improved assignment-style redaction so useful key context is preserved:
  - Example: `api_key = "..."` becomes `api_key = "[REDACTED]"`.
- Redacted content before parsing, chunking, static graph extraction, embedding, Qdrant upsert, and Neo4j graph writes.
- Added per-chunk metadata for censored files:
  - `security_censored=true`
  - `secrets_redacted=<count>`
- Added separate ingestion stats:
  - `files_with_secrets`
  - `secrets_redacted`
  - `files_skipped_for_secrets`
- Preserved `secrets_found` as a backward-compatible alias for the redacted count.
- Redacted GitHub issue and PR title/body text before graph building and Qdrant chunking.
- Applied the same redaction path to webhook file updates so webhook re-indexing cannot bypass the censor.

Validation:

- Backend Python compile check passed for 48 backend files excluding `.venv`.
- Secret redaction smoke test passed:
  - fake API key was detected
  - file still produced chunks after redaction
  - indexed chunk text contained `[REDACTED]`
  - original secret was absent from chunk text and chunk metadata
  - censored chunks carried `security_censored` metadata
  - issue/PR record redaction removed the original secret before downstream parsing
- `git diff --check` passed, with only CRLF warnings.

### Target Files

- `backend/ingestion/secret_scanner.py`
- `backend/ingestion/pipeline.py`
- Tests for scanner/chunking

### Implementation Plan

1. Done - Decide file-level policy:
   - Redact and continue for ordinary text/code files.
   - Skip entire file only for high-confidence dangerous files, if needed.
2. Done - Use `redact_text()` before parsing/chunking/upserting.
3. Done - Track stats separately:
   - `files_with_secrets`
   - `secrets_redacted`
   - `files_skipped_for_secrets`
4. Done by smoke test - Ensure raw secret text is never sent to:
   - Qdrant
   - Neo4j
   - logs
   - LLM prompts

### Validation

- Done by smoke test - Test a file containing fake API keys.
- Done by smoke test - Confirm indexed text contains `[REDACTED]`.
- Done by smoke test before upsert - Confirm original secret is absent from chunk payload text/metadata.
- Done by smoke test - Confirm pipeline still produces chunks for redacted files.
- Pending real DB check - Confirm original secret is absent from Qdrant payloads after a live ingest.

---

## Phase 6: Webhook Tenant Safety

### Goal

Prevent webhook updates from bypassing user isolation and corrupting shared repo state.

### Status

Completed on 2026-05-03.

Implemented:

- Added an explicit webhook target resolution layer in `backend/api/webhook.py`.
- Webhook handlers now require a Cortex tenant target before mutating Qdrant or Neo4j.
- Because no repo-to-tenant ownership mapping exists yet, `resolve_webhook_targets()` intentionally returns no targets.
- Push, pull request, and issue webhooks are still accepted after signature validation, but mutation is skipped with a clear log message when no tenant mapping exists.
- Removed the unsafe Phase 3 interim behavior where webhook file updates were written into the public namespace by default.
- Kept tenant-aware mutation helpers in place for future webhook ownership mapping:
  - file delete accepts a `WebhookTarget`
  - file upsert accepts a `WebhookTarget`
  - PR/issue graph builders receive target `user_id` / `is_public`
- Preserved secret redaction in webhook file updates for the future mapped path.

Validation:

- Phase 7 webhook safety test passed: a push webhook without tenant mapping did not call file upsert or delete mutation paths.
- Backend compile passed for 49 backend files excluding `.venv`.

### Target Files

- `backend/api/webhook.py`
- `backend/ingestion/pipeline.py`
- `backend/indexing/qdrant_store.py`
- `backend/indexing/graph_builder/git_graph.py`

### Problem

Current webhook handlers receive repo-level GitHub events but do not know which Cortex user(s) indexed that repo. They update Qdrant and Neo4j without `user_id`.

### Implementation Options

1. Done - Disable webhook mutation until tenant mapping exists.
2. Deferred - Store webhook ownership mapping:
   - repo
   - installation/user owner
   - user_id
   - token source
3. Deferred - On webhook, update every tenant-owned index for that repo.
4. Deferred - For public repos, update public/shared copies according to the chosen public-pool model.

### Recommendation

Done: webhook processing is conservative. It does not mutate tenant data unless the target tenant mapping is known.

### Validation

- Done by unit test - Webhook event for repo without tenant mapping does not alter Qdrant/Neo4j.
- Pending future mapping work - Webhook event for mapped repo updates only the intended tenant data.
- Pending future mapping work - Removed files are deleted only for matching tenant/repo/file.

---

## Phase 7: Tests And Verification Gates

### Goal

Replace stale phase scripts with tests that reflect current auth, ingestion jobs, local embeddings, and tenant isolation.

### Status

Completed on 2026-05-03.

Implemented:

- Added `backend/test_phase7_verification.py` as a focused no-network verification suite for the current ingestion recovery work.
- Covered local embedding config:
  - FastEmbed backend
  - `BAAI/bge-base-en-v1.5`
  - 768 dimensions
- Covered Qdrant tenant identity:
  - same repo/file/chunk for two users produces different deterministic point IDs
  - tenant-scoped Neo4j ID helper returns expected prefixes
- Covered secret redaction:
  - fake API key is redacted before chunking
  - redacted file still produces chunks
  - original secret is absent from chunk text and metadata
  - censored chunk metadata is set
- Covered GitHub retry classification:
  - retries `429`, `502`, `503`, `504`, and connection failures
  - does not retry `401`, `403`, `404`, `422`
- Covered job-store behavior:
  - event cap works
  - cursor remains monotonic after trimming
  - missing jobs return `lost`
- Covered webhook safety:
  - webhook without tenant mapping does not call mutation paths

Validation:

- `backend/test_phase7_verification.py` passed: 6 tests.
- Backend Python compile check passed for 49 backend files excluding `.venv`.
- Frontend TypeScript check passed with `npx tsc --noEmit`.

### Target Areas

- Auth cookie session
- GitHub client retry behavior
- Local embedding dimensions
- Qdrant deterministic tenant IDs
- Neo4j tenant-scoped node IDs
- Ingestion job status and SSE/polling
- Secret redaction
- Repo deletion zero-residual check

### Test Plan

1. Done - Unit tests:
   - embedder local output shape
   - secret scanner redaction
   - Qdrant chunk ID generation includes `user_id`
   - retryable/non-retryable HTTP classification
2. Partially done - Integration tests with mocked GitHub:
   - metadata/tree/blob fetch
   - partial blob failures
   - Done by classifier test - retry behavior
3. Pending broader API test pass - Authenticated API tests:
   - guest login
   - GitHub callback mocked
   - protected endpoint rejects unauthenticated users
4. Partially done - Tenant isolation tests:
   - same repo indexed by two fake users
   - Pending real DB check - search/delete does not cross user boundary
5. Pending one-go manual verification:
   - ingest a tiny repo
   - ingest a medium repo
   - query
   - graph explore
   - delete and verify zero residual

---

## Suggested Implementation Order

1. Align embedding config and implement FastEmbed.
2. Add tenant-safe Qdrant IDs and Neo4j node IDs.
3. Reset development Qdrant/Neo4j collections if needed.
4. Generalize GitHub client lifecycle and retry/backoff.
5. Fix secret redaction behavior.
6. Lock down webhook behavior.
7. Refresh tests and docs.

This order avoids embedding dimension mismatches and tenant data corruption before doing larger reliability improvements.

---

## Open Questions

1. Which local embedding model should Cortex standardize on first?
   - Prefer 768-dim to reduce Qdrant schema disruption?
   - Or prefer a smaller/faster 384-dim model and reset the collection?
2. Should public repos have one shared public index, or should every user still get their own copy marked `is_public=true`?
3. Should webhook support be kept active now, or disabled until tenant mapping is implemented?
4. Are we allowed to reset the current development Qdrant collection and Neo4j graph after storage identity changes?

---

## Done Criteria

The full fix set is complete when:

- Ingestion no longer depends on Gemini/Jina embedding APIs.
- A medium repo can ingest without embedding 429s.
- GitHub file fetching uses shared clients and retry/backoff.
- Qdrant and Neo4j identities are tenant-safe.
- Same-repo multi-user ingestion does not overwrite data.
- Repo deletion removes only the current user's data.
- Webhooks cannot mutate data without tenant ownership context.
- Secrets are redacted before indexing.
- Tests cover the new auth, ingestion, embedding, and tenant behavior.
