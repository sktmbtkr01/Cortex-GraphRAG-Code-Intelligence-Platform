# Cortex Production Beta: Structural Architecture Changes

This document tracks the non-cloud-specific architecture changes we want before the production beta. These are not just deployment chores. They change how Cortex ingests, stores, routes, and verifies work so the system is faster, safer, and easier to test locally before Google Cloud rollout.

Goal:

```text
Prove the stronger production-beta architecture locally first.
Then deploy the already-tested shape to Google Cloud.
```

---

## 1. Separate Ingestion From The API Process

Status: implemented as a local runner boundary.

Current shape:

```text
FastAPI receives /ingest
-> creates asyncio background task
-> same API process fetches, parses, embeds, writes graph/vector data
```

Beta target:

```text
FastAPI receives /ingest
-> creates durable job record
-> triggers a separate ingestion runner
-> API only handles auth, queries, SSE/polling, and status
```

Why:

- Keeps the API responsive while ingestion is heavy.
- Makes ingestion easier to tune separately.
- Reduces risk from API restarts killing long jobs.
- Matches the later Cloud Run Job model.

Local test approach:

- Add a local ingestion runner entrypoint.
- API can still call it during local development, but the ingestion logic should be callable as a separate process/function.
- Confirm query routes still work while ingestion runs.

Implementation progress:

- Added `backend/ingestion/runner.py`.
- Moved the long-running ingestion job execution out of `backend/api/routes.py` into `run_ingest_job(...)`.
- Updated `/ingest` and branch update routes to create the job record, then delegate execution to `run_ingest_job(...)`.
- The API still starts the runner with `asyncio.create_task(...)` for local compatibility, but the ingestion logic now has a separate module boundary for a future process/Cloud Run Job entrypoint.

Verification:

- Passed: `python -m py_compile backend\ingestion\runner.py`
- Passed: `python -m py_compile backend\api\routes.py`
- Passed: `python -m py_compile backend\ingestion\pipeline.py`

---

## 2. Shallow Git Clone As The Default Ingestion Source

Status: feature-flagged local path added; default remains `github_api` until parity testing.

Current shape:

```text
GitHub tree API
-> filter eligible files
-> GitHub blob API per file
-> file contents become Python strings in backend memory
```

Beta target:

```text
shallow git clone selected branch into temp directory
-> walk local files
-> apply same filters
-> parse/chunk/graph/embed/upsert
-> delete temp clone
```

Recommended command shape:

```bash
git clone --depth 1 --single-branch --branch <branch> <authenticated_repo_url> <tmp_dir>
```

Why:

- Avoids hundreds of GitHub blob API calls for medium repos.
- Usually faster for full current-branch ingestion.
- Makes future incremental `git diff` updates easier.
- Fits the separate ingestion job model naturally.

Important constraints:

- Never log authenticated clone URLs.
- Clone only into temporary local storage.
- Delete the clone on success and failure.
- Keep the existing GitHub API fetch path as a fallback/local comparison mode.

Implementation progress:

- Added `INGEST_SOURCE=github_api|git_clone`.
- Added `GIT_CLONE_TIMEOUT_SECONDS`.
- Added `backend/ingestion/git_source.py`.
- The git source shallow-clones the selected branch into a temporary directory, walks local files, applies the existing `should_process_file(...)` filter, reads eligible files, and deletes the temporary clone in a `finally` block.
- `backend/ingestion/pipeline.py` now selects between the current GitHub tree/blob API source and the new git clone source.
- The default remains `github_api` to avoid changing existing local behavior until parity tests are complete.
- Authenticated clone URLs are redacted in helper logging.
- Local Windows subprocess compatibility was fixed by running `git clone` in a thread-backed subprocess call.
- Clone cleanup is now logged explicitly, and the UI progress message states that the temporary checkout was cleaned up after file selection.
- Frontend ingestion stage labels now distinguish metadata fetch, cloning, file selection, embedding, and upserting instead of collapsing clone completion into a generic complete state.

Local test approach:

```text
INGEST_SOURCE=github_api
INGEST_SOURCE=git_clone
```

Run both modes on the same small repo and compare:

- files parsed
- chunks created
- graph edges created
- Qdrant chunk count
- Neo4j node/relationship counts
- sample query quality

Verification so far:

- Passed: `python -m py_compile backend\ingestion\git_source.py`
- Passed: `python -m py_compile backend\ingestion\pipeline.py`
- Passed: `python -m py_compile backend\core\config.py`
- Passed: local helper smoke for unauthenticated URL construction and authenticated URL log redaction.

Still to verify:

- Run `INGEST_SOURCE=git_clone` against a tiny public repo.
- Run `INGEST_SOURCE=git_clone` against a private repo with a GitHub token.
- Compare old-vs-new ingestion counts.

---

## 3. Memory-Efficient Batched Processing

Status: implemented for the shallow-clone source path and downstream parse/graph/embed/upsert batching; GitHub API fallback still fetches eligible file contents before downstream batching.

Current shape:

```text
fetch all eligible files
-> keep file contents in RAM
-> parse/chunk all
-> keep all chunks in RAM
-> embed all chunks
-> upsert all chunks
```

Beta target:

```text
walk selected files
-> process small file batch
-> graph-write batch
-> accumulate chunk batch
-> embed chunk batch
-> upsert chunk batch
-> release batch memory
-> repeat
```

Why:

- Peak memory depends on batch size, not repo size.
- Better fit for Cloud Run memory limits.
- Lets progress events be more granular.
- Reduces failure blast radius.

Recommended defaults to test:

```env
FILE_PROCESSING_BATCH_SIZE=10
EMBEDDING_BATCH_SIZE=128
```

Important design detail:

```text
File processing batch size != embedding batch size
```

One file can create many chunks, so embeddings should batch by chunk count/token budget, not by file count.

Implementation progress:

- Added `FILE_PROCESSING_BATCH_SIZE`.
- Kept `EMBEDDING_BATCH_SIZE` as the separate chunk/vector batch control.
- `backend/ingestion/git_source.py` now supports shallow-clone batch streaming: clone once, walk eligible paths, read only one file batch into Python memory, hand that batch to the pipeline, then read the next batch.
- `backend/ingestion/pipeline.py` now processes file batches from the clone source immediately instead of waiting for one full-repo `fetched_files` list.
- The GitHub API fallback still uses the old bulk content fetch, then applies downstream batching for parse/chunk/embed/upsert.
- Chunks are accumulated only until `EMBEDDING_BATCH_SIZE`, then embedded and upserted to Qdrant immediately.
- Progress events now include `processing_batch`, `embedding_batch`, `qdrant_upsert`, and `graph_write`.
- Timings now accumulate across batches for `parse_chunk_ms`, `graph_write_ms`, `embedding_ms`, `sparse_vector_ms`, and `qdrant_upsert_ms`; clone source timing now separates `clone_ms`, `file_walk_ms`, and `file_read_ms`.

Verification needed:

- Run one local ingestion with `INGEST_SOURCE=git_clone`.
- Confirm final chunk count is comparable with the previous step 2 run.
- Confirm citations still show source code and line ranges.
- Confirm final timing output shows multiple batch stages when repo size is large enough.

---

## 4. Incremental Indexing By Commit And File Identity

Status: implemented as a beta update path using stored file identities.

Current shape:

```text
update repo
-> usually re-ingest branch broadly
```

Beta target:

```text
store previous commit_sha and per-file identity
-> compare latest commit/tree
-> re-index changed files
-> delete removed files
-> leave unchanged chunks/graph alone
```

Useful identity fields:

```text
repo
branch
commit_sha
file_path
blob_sha or file hash
ingest_run_id
```

Why:

- Massive speedup for updates.
- Avoids paying embedding cost for unchanged files.
- Makes "update repo" feel quick.

Local test approach:

- Ingest a small repo.
- Modify one file on a test branch or test fixture.
- Confirm only that file is reprocessed.
- Confirm deleted files are removed from Qdrant/Neo4j.

Implementation progress:

- Added `file_sha` metadata to chunks and Qdrant payloads.
- File graph nodes now store `file_sha`.
- Update jobs load previous `File.path -> file_sha` identities from Neo4j.
- During ingestion, unchanged files are skipped before parse/chunk/graph/embed.
- Changed files are deleted from Qdrant and their old file-level graph is removed before re-indexing.
- Files missing from the latest eligible file set are deleted from Qdrant and Neo4j during cleanup.
- Full stale-run deletion still runs for first/full ingests, but is skipped during incremental updates so unchanged files are preserved.

Verification:

- Passed: `python -m py_compile backend\ingestion\runner.py backend\ingestion\pipeline.py backend\ingestion\git_source.py backend\indexing\qdrant_store.py backend\models\schemas.py`

---

## 5. Batched Neo4j Writes

Status: implemented for static file graph writes.

Current shape:

```text
for each extracted edge:
    merge target node
    merge relationship
```

This can produce many small Neo4j calls.

Beta target:

```text
collect nodes/edges per batch
-> use Cypher UNWIND to merge many nodes/relationships at once
```

Why:

- Fewer network round trips.
- Faster graph construction.
- Better behavior on larger repos.

Local test approach:

- Compare graph write time before/after batching.
- Verify uniqueness constraints still prevent duplicates.
- Verify tenant-scoped IDs are still applied consistently.

Implementation progress:

- Added `Neo4jManager.merge_tenant_nodes_batch(...)`.
- Added `Neo4jManager.merge_tenant_relationships_batch(...)`.
- Static file graph writes now collect extracted file/function/class/module/dependency nodes by label and relationships by type across each file-processing batch.
- Neo4j writes now use `UNWIND` batch merges instead of one merge call for every extracted edge.
- Tenant-scoped IDs still go through the same `tenant_scoped_id(...)` path.
- Restored the shallow-clone source to the memory-efficient file-batch path after the old all-at-once comparison run.
- The active beta ingestion path is now:

```text
shallow clone temp checkout
-> walk/filter eligible files
-> read one file batch
-> parse/chunk batch
-> write static graph with batched Neo4j merges
-> embed/upsert chunk batches
-> cleanup temp checkout
```

Verification:

- Passed: `python -m py_compile backend\ingestion\pipeline.py backend\indexing\graph_builder\neo4j_manager.py backend\ingestion\git_source.py`

---

## 6. Durable Job State Interface

Status: implemented with memory and Redis backends; Redis runtime verification needs a Redis server/URL.

Current shape:

```text
in-memory JobStore
```

Beta target:

```text
JobStore interface
-> memory implementation for local/simple tests
-> Redis implementation for durable local/prod-like tests
```

Why:

- SSE/polling should not depend on one Python process.
- Ingestion progress needs to survive process boundaries.
- Separate ingestion runner needs shared job state.

Events should remain cursor-based:

```text
job_id
status
event_offset/cursor
events[]
done
```

Local test approach:

- Start ingestion.
- Poll job status.
- Simulate runner crash/failure.
- Confirm terminal error event is visible.

Implementation progress:

- Added `JOB_STORE_BACKEND=memory|redis`.
- Added `REDIS_URL`.
- Kept the existing in-memory implementation as `MemoryJobStore`.
- Added `RedisJobStore` using Redis hashes for job metadata and Redis lists for cursor-based event streams.
- Preserved the existing job store API used by routes and ingestion runner:
  - `create_job(...)`
  - `get_job(...)`
  - `get_snapshot(...)`
  - `publish(...)`
  - `wait_for_events(...)`
  - `get_events_since(...)`
- Redis events keep the same cursor contract via `event_offset`.
- Redis event lists are capped by `INGEST_JOB_MAX_EVENTS`.
- Redis job metadata and event keys expire after `INGEST_JOB_MAX_AGE_SECONDS`.
- Added `redis==5.2.1` to backend requirements.

Verification:

- Passed: `python -m py_compile backend\core\job_store.py backend\core\config.py backend\api\routes.py backend\ingestion\runner.py`
- Passed in `cortex-gpu`: `python -m py_compile backend\core\job_store.py backend\core\config.py`
- Passed memory-store smoke test in `cortex-gpu`.
- Pending: set `JOB_STORE_BACKEND=redis` and `REDIS_URL`, then run an ingest while polling/SSE is connected.

---

## 7. Stronger Ingestion Progress Events

Status: implemented for the current local polling/SSE path; durable delivery still depends on Step 6.

Current progress is useful but phase-oriented.

Beta target should emit progress around concrete stages:

```text
queued
clone_start
clone_done
file_filtering
processing_batch
graph_write
embedding_batch
qdrant_upsert
snapshot
cleanup
done
error
```

Why:

- Easier debugging.
- Better UI trust.
- Easier local performance measurement.

Each event should include safe metadata only:

```json
{
  "stage": "embedding_batch",
  "message": "Embedding chunk batch 3",
  "meta": {
    "chunks": 128,
    "processed_files": 40,
    "total_files": 120
  }
}
```

Never include:

- raw file contents
- secrets
- tokenized clone URLs
- raw prompts

Implementation progress:

- Existing queued events are emitted when a job is created.
- Ingestion now emits concrete stages including `clone_start`, `clone_done`, `file_filtering`, `processing_batch`, `graph_write`, `embedding_batch`, `qdrant_upsert`, `cleanup`, `timing_summary`, `done`, and `error`.
- Incremental updates emit how many previous file identities were loaded, how many files were selected/skipped, and how many removed files were cleaned up.
- Frontend stage labels now recognize `file_filtering` and `cleanup`.
- Backend logs now include high-visibility `INGEST_VECTOR_BATCH` and `INGEST_TIMING_SUMMARY` lines for local testing.

Verification:

- Passed: `python -m py_compile backend\ingestion\runner.py backend\ingestion\pipeline.py`

---

## 8. Redis Cache And Demo Limits

Status: implemented locally for production-beta validation.

What changed:

- Added `backend/core/cache_limits.py`.
- Added Redis JSON cache helpers for GitHub repo lists, GitHub branch lists, snapshots, and health reports.
- Added Redis-backed daily counters for ingests, queries, and health checks.
- Added Redis-backed active ingest locks for one active ingest per user and a small global active ingest cap.
- Added guardrails for indexed repo count, repository size, eligible file count, and chunk count.
- Added cache/quota settings to `backend/core/config.py` and `.env.example`.
- Startup logs now include cache and quota backend settings.

Current cached data:

```text
github_repos:<hashed_user_id>
github_branches:<hashed_user_id>:<hashed_repo>
snapshot:<hashed_user_id>:<hashed_repo>:<branch>:<commit_sha>
health:<hashed_user_id>:<hashed_repo>:<branch>:<commit_sha>
```

Current limits:

```text
MAX_REPOS_PER_USER
MAX_ELIGIBLE_FILES
MAX_CHUNKS_PER_REPO
MAX_ACTIVE_INGESTS_PER_USER
MAX_GLOBAL_ACTIVE_INGESTS
MAX_INGESTS_PER_USER_PER_DAY
MAX_QUERIES_PER_USER_PER_DAY
MAX_HEALTH_CHECKS_PER_REPO_COMMIT
```

`MAX_REPOS_PER_USER` counts indexed repo-branches, not unique repository names. For example, indexing `owner/api@main` and `owner/api@dev` consumes two slots.

Verification:

- Passed: `python -m py_compile backend\core\cache_limits.py backend\core\config.py backend\api\routes.py backend\ingestion\runner.py backend\ingestion\pipeline.py backend\ingestion\git_source.py backend\main.py`

---

## 9. Stage Timing And Instrumentation

Add timings for ingestion stages:

```text
clone_ms
file_walk_ms
filter_ms
parse_chunk_ms
graph_write_ms
embedding_ms
qdrant_upsert_ms
snapshot_ms
cleanup_ms
total_ms
```

Why:

- We need to know what is actually slow before optimizing further.
- Helps compare GitHub API fetch vs shallow clone.
- Helps tune batch sizes.

Local test output should answer:

```text
Where did ingestion spend time?
How many files/chunks were processed?
Which stage dominates?
```

---

## 10. Keep The Existing Retrieval Design

These changes are about ingestion architecture, not changing the main retrieval product behavior.

Keep:

- Qdrant dense/sparse hybrid retrieval.
- Neo4j graph tools.
- cited source chunks.
- snapshot generation.
- health check generation.
- direct semantic route plus graph/hybrid route plus LangGraph agent route.

Expected output should remain compatible with current frontend source citations.

---

## 11. Vertex Embedding Backend

Status: implemented locally behind `EMBEDDING_BACKEND=vertex`.

What changed:

- `CortexEmbedder` now supports both `fastembed` and `vertex`.
- Local development can continue using FastEmbed/GPU.
- Production can use Vertex AI embeddings without changing ingestion, query, health, snapshot, or agent callers.
- The dense vector interface remains `embed_batch(texts) -> list[list[float]]`.
- Sparse vector generation remains local.
- Vertex requests are batched and retried with exponential backoff.
- Returned vector dimensions are validated before Qdrant upsert/search.

Required production env:

```env
EMBEDDING_BACKEND=vertex
VERTEX_PROJECT_ID=<google-cloud-project-id>
VERTEX_LOCATION=us-central1
VERTEX_EMBEDDING_MODEL=text-embedding-005
EMBEDDING_DIMENSIONS=768
```

---

## Local Validation Checklist

Before cloud deployment, run local tests for:

- [ ] GitHub API ingestion still works as fallback.
- [ ] Shallow clone ingestion works for a small public repo.
- [ ] Shallow clone ingestion works for a private repo using a GitHub token.
- [ ] Temp clone directory is deleted after success.
- [ ] Temp clone directory is deleted after forced failure.
- [ ] Batched ingestion produces comparable chunks to current ingestion.
- [ ] Batched graph writes produce expected Neo4j nodes/relationships.
- [ ] Qdrant payloads still include code text, file path, line ranges, branch, commit, and tenant metadata.
- [ ] Citations still render correctly in the frontend.
- [ ] Job progress events are visible through polling/SSE.
- [ ] Stage timing logs show clone, parsing, graph, embedding, and upsert durations.
- [ ] Updating an unchanged repo avoids unnecessary re-indexing where possible.

---

## Recommended Implementation Order

1. Add stage timing instrumentation to current ingestion. `[implemented early: 2026-05-11]`
2. Add `INGEST_SOURCE=github_api|git_clone`.
3. Implement shallow clone local ingestion path.
4. Refactor shared downstream processing so both ingestion sources use the same parse/chunk/graph/embed code.
5. Add batch processing for files and embeddings.
6. Add batched Neo4j writes.
7. Add durable job store interface and Redis implementation.
8. Add separate ingestion runner entrypoint.
9. Add incremental update logic.
10. Run old-vs-new local parity tests.

---

## Implementation Progress

### Step 1: Stage Timing Instrumentation

Status: implemented early.

Files changed:

- `backend/ingestion/pipeline.py`
- `backend/api/routes.py`

What changed:

- Added `timings_ms` to ingestion stats.
- Timed the current GitHub API ingestion stages without changing behavior:
  - `tree_fetch_ms`
  - `filter_ms`
  - `file_fetch_ms`
  - `parse_chunk_ms`
  - `graph_write_ms`
  - `issues_ms` when issue ingestion runs
  - `prs_ms` when PR ingestion runs
  - `commits_ms` when commit graph ingestion runs
  - `embedding_ms`
  - `sparse_vector_ms`
  - `qdrant_upsert_ms`
  - `snapshot_ms`
  - `total_ms`
- Included timings in the existing ingestion completion log.
- Added snapshot timing around `generate_repo_snapshot(...)` in the API ingest job flow.

Verification:

- Passed: `python -m py_compile backend\ingestion\pipeline.py`
- Passed: `python -m py_compile backend\api\routes.py`
- Blocked: `python -m pytest backend\test_phase7_verification.py`

Blocked test reason:

```text
ModuleNotFoundError: No module named 'fastembed'
```

This happened during test collection while importing the existing embedder dependency, before tests ran.
