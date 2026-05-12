# Cortex Production Runbook: Google Cloud End-to-End

This document is a detailed implementation and deployment plan for taking the current local Cortex project to a controlled production demo on Google Cloud.

The target is not a full enterprise SaaS launch. The target is a public website where a small number of external users, around 20 maximum, can sign in with GitHub, ingest limited repositories, query them, inspect citations, view graph/snapshot/health outputs, and delete their data.

The plan keeps the current product architecture intact:

```text
GitHub login -> choose repo -> choose branch -> ingest -> query -> inspect citations -> explore graph
```

The production version adds the missing operational layers:

- Google Cloud Run deployment for backend and frontend.
- Vertex AI embeddings for production instead of local FastEmbed.
- Durable session/job/cache storage.
- Cloud Run Job based ingestion, separate from the API service.
- Hard usage limits.
- Better privacy and deletion controls.
- Safer secrets, logging, and tenant isolation.

No production launch should happen until the checklist at the end passes.

---

## 1. Current State Summary

Current local stack:

| Area | Current implementation |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Backend | FastAPI |
| Auth | GitHub OAuth, HttpOnly session cookie |
| GitHub token storage | In-memory backend session store |
| Ingestion jobs | In-memory async job store |
| Embeddings | Local FastEmbed |
| Vector DB | Qdrant |
| Graph DB | Neo4j |
| Generation | Gemini, with Groq-backed agent path where configured |
| Agent workflow | LangGraph single-agent tool workflow with critic loop |
| Deployment files | Dockerfile, docker-compose.yml, render.yaml |

What already works locally:

- GitHub OAuth login.
- Repo and branch selection.
- Background ingestion.
- File filtering, parsing, secret redaction, chunking.
- Qdrant dense/sparse hybrid retrieval.
- Neo4j graph extraction.
- Direct RAG query endpoint.
- LangGraph agent query endpoint.
- Architecture snapshot.
- Repository health check.
- 3D graph viewer.
- Repo deletion.
- Tenant-oriented `user_id` fields in Qdrant/Neo4j.

What is not production-safe yet:

- GitHub tokens are stored only in process memory.
- Ingestion jobs are stored only in process memory.
- Backend can lose active jobs when Cloud Run restarts.
- Local FastEmbed model download/cache is not ideal for stateless Cloud Run.
- Usage is not hard-limited enough for a public demo.
- Privacy copy and full account deletion need to be explicit.
- Logs need a strict no-raw-code/no-token policy.
- Cloud Run needs `$PORT` compatibility.

---

## 2. Production Target Architecture

Use Google Cloud end-to-end for app hosting and Google-managed AI.

Recommended production architecture:

```text
Browser
  |
  v
Cloud Run: cortex-web
  |
  v
Cloud Run: cortex-api
  |
  +--> GitHub OAuth/API
  +--> Vertex AI text embeddings
  +--> Gemini generation
  +--> Secret Manager
  +--> Redis-compatible store for sessions/jobs/cache/quotas
  +--> Qdrant Cloud
  +--> Neo4j AuraDB
  +--> Cloud Logging/Error Reporting

Cloud Run Job: cortex-ingest
  |
  +--> Shallow git clone selected repo branch into /tmp
  +--> Batch parse/chunk/graph/embed/upsert
  +--> Publish progress to Redis
  +--> Delete temporary clone on success/failure
```

Recommended service names:

```text
cortex-web
cortex-api
cortex-ingest
```

Recommended Google Cloud region:

```text
us-central1
```

Use one region consistently for Cloud Run, Artifact Registry, and Vertex AI.

Qdrant Cloud and Neo4j AuraDB are still managed external services. Running Qdrant and Neo4j yourself on Cloud Run is not recommended for this demo because persistent state, backups, and memory tuning become unnecessary complexity.

---

## 3. Feasibility With $300 Credits

For a maximum of around 20 testers, this is technically and financially feasible if hard limits are implemented.

The $300 Google Cloud credits should comfortably cover:

- Cloud Run backend usage.
- Cloud Run frontend usage.
- Vertex AI embedding calls.
- Gemini/Vertex generation calls, depending on model and usage.
- Secret Manager.
- Artifact Registry storage.
- Cloud Logging at modest volume.

The credits do not cover every external managed service unless those services are also using free tiers or separate credits. Qdrant Cloud and Neo4j AuraDB should start on their free/prototype tiers where possible.

The main financial risks are not normal query usage. The real risks are:

- Users ingesting large repositories.
- Users repeatedly re-ingesting.
- Health checks and snapshots being regenerated repeatedly.
- Huge Qdrant/Neo4j storage growth.
- Unbounded logs containing large payloads.
- Too many Cloud Run instances scaling up during ingestion.

Hard limits are not optional for an open demo.

---

## 4. Production Tech Stack

| Layer | Production choice |
| --- | --- |
| Frontend hosting | Cloud Run |
| Backend hosting | Cloud Run |
| Image registry | Artifact Registry |
| Build system | Cloud Build |
| Secrets | Secret Manager |
| Embeddings | Vertex AI `text-embedding-005` |
| Answer generation | Gemini API or Vertex Gemini |
| Vector database | Qdrant Cloud |
| Graph database | Neo4j AuraDB |
| Sessions/jobs/cache/quotas | Redis-compatible store |
| Logs | Cloud Logging |
| Errors | Error Reporting |
| Budget alerts | Google Cloud Billing budgets |

Use `text-embedding-005` first because it is a direct fit for English/code retrieval and keeps the current Qdrant dimension expectation simple. Do not switch to `gemini-embedding-001` in the first production deploy unless you deliberately migrate Qdrant dimensions.

---

## 5. Production Limits

The exact numbers can be decided later, but the system must support these limit categories before launch.

Recommended initial demo limits:

```env
ACCESS_MODE=open_limited
MAX_REPOS_PER_USER=2
MAX_REPO_SIZE_MB=50
MAX_ELIGIBLE_FILES=500
MAX_CHUNKS_PER_REPO=3000
MAX_ACTIVE_INGESTS_PER_USER=1
MAX_GLOBAL_ACTIVE_INGESTS=2
MAX_INGESTS_PER_USER_PER_DAY=2
MAX_QUERIES_PER_USER_PER_DAY=30
MAX_HEALTH_CHECKS_PER_REPO_COMMIT=1
GITHUB_FETCH_CONCURRENCY=5
FILE_PROCESSING_CONCURRENCY=4
```

Behavior required:

- Check repository size before fetching file contents.
- Check eligible file count before fetching file contents.
- Stop chunking/indexing before exceeding max chunks.
- Allow only one active ingest per user.
- Allow only a small number of active ingests globally.
- Cache health checks and snapshots by commit.
- Return clear user-facing errors when limits are hit.
- Do not leave half-indexed data marked as ready.

For public demo safety, begin strict and loosen later.

---

## 6. Required Code Changes Before Deployment

### 6.1 Make Backend Cloud Run Compatible

Cloud Run injects a `PORT` environment variable. The backend container must listen on that port.

Current local Dockerfile hardcodes port `8000`. Production should use:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
```

Implementation detail:

- Update the backend Dockerfile or add a production Dockerfile.
- Keep `workers=1` initially.
- Do not use `--reload` in production.

Why `workers=1`:

The stronger beta architecture keeps long-running ingestion out of the API process. The API service should stay focused on auth, repo listing, job creation, query routes, SSE/polling, and lightweight status reads. Use `workers=1` initially to keep API behavior simple while Redis-backed sessions/jobs and the separate ingestion job are validated. Once the API is stateless and job state is fully Redis-backed, API worker count can be revisited independently from ingestion throughput.

### 6.2 Add Vertex Embedding Backend

Current embedder supports FastEmbed for local development. Production should use Vertex:

Status: implemented locally as a backend switch inside `CortexEmbedder`.

```env
EMBEDDING_BACKEND=vertex
VERTEX_PROJECT_ID=<project-id>
VERTEX_LOCATION=us-central1
VERTEX_EMBEDDING_MODEL=text-embedding-005
EMBEDDING_DIMENSIONS=768
```

Keep the public interface unchanged:

```python
embed_batch(texts: list[str]) -> list[list[float]]
generate_sparse_vector(text: str) -> dict
```

Required behavior:

- If `EMBEDDING_BACKEND=fastembed`, use current local FastEmbed.
- If `EMBEDDING_BACKEND=vertex`, call Vertex AI embeddings.
- Keep sparse vector generation local.
- Batch Vertex requests.
- Retry with backoff on `429`, `503`, timeout, and transient network errors.
- Validate returned vector dimension equals `EMBEDDING_DIMENSIONS`.
- Fail ingestion clearly if dimensions mismatch the Qdrant collection.

Implementation progress:

- Added `EMBEDDING_BACKEND=fastembed|vertex`.
- Added `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `VERTEX_EMBEDDING_MODEL`, `VERTEX_EMBEDDING_TASK_TYPE`, `VERTEX_EMBEDDING_MAX_TEXT_CHARS`, and `VERTEX_EMBEDDING_RETRY_ATTEMPTS`.
- `CortexEmbedder.embed_batch(...)` now preserves the same caller-facing interface for both local FastEmbed and Vertex.
- Vertex requests are batched with a maximum of 250 inputs per request.
- Vertex responses are dimension-checked against `EMBEDDING_DIMENSIONS`.
- Vertex embedding input text is hard-capped at 8,000 characters per chunk to avoid token-limit failures on dense source code.
- Vertex embedding requests are rate-spaced and 429 quota errors retry after a longer wait.
- Sparse vectors still remain local.

### 6.2.1 Add Vertex LLM Backend

Status: implemented locally as a generation backend switch.

Production should route quota-heavy generation through Vertex AI:

```env
LLM_BACKEND=vertex
VERTEX_LLM_MODEL=gemini-2.5-flash
VERTEX_LLM_FAST_MODEL=gemini-2.5-flash-lite
VERTEX_LLM_REASONING_MODEL=gemini-2.5-pro
LLM_RETRY_ATTEMPTS=3
```

Current routing:

- Snapshot generation uses the shared Cortex LLM client.
- Health generation uses the shared Cortex LLM client.
- Direct semantic RAG answer generation uses the shared Cortex LLM client.
- Existing LangGraph agent tool-calling path still uses Groq primary; Gemini API fallback remains separate.

Why:

- Avoids Google AI Studio API-key quota pressure for snapshot, health, and normal answers.
- Uses Cloud Run service-account auth with Vertex AI.
- Keeps prompts and response shape unchanged.

Recommended batching rules:

- Max 250 texts per embedding request.
- Keep `VERTEX_EMBEDDING_MAX_TEXT_CHARS=8000` unless production logs show a safe reason to raise it.
- Keep `VERTEX_EMBEDDING_MIN_REQUEST_INTERVAL_SECONDS=13` for a 5-request/minute quota.
- Keep `VERTEX_EMBEDDING_QUOTA_RETRY_SECONDS=65` so a quota hit waits for the next minute window.
- Truncate or pre-chunk text so each input stays under the model's effective per-input limit.

### 6.3 Add Durable Session Store

Current GitHub access tokens live in memory. Production needs durable server-side storage.

Status: implemented locally with Redis-backed encrypted GitHub token storage and 24-hour TTL.

Recommended shape:

```text
session:github:<github_user_id> -> encrypted GitHub token
TTL: 24 hours initially
```

Requirements:

- Browser never sees the GitHub token.
- Cookie stores only Cortex JWT/session reference.
- Logout deletes the Redis session key.
- Backend restart does not immediately log users out.
- Expired session returns a clear "sign in again" response.

Implementation progress:

- Added `SESSION_STORE_BACKEND=memory|redis`.
- Added `SESSION_TTL_SECONDS`.
- Added `SESSION_ENCRYPTION_KEY`.
- Redis session keys store encrypted GitHub tokens only.
- Session keys are hashed by user id.
- Logout clears the Redis session key and HttpOnly cookie.
- Startup logs now show the active job/session backends.

Encryption recommendation:

- Store an app-level encryption key in Secret Manager.
- Encrypt GitHub tokens before writing them to Redis.
- Rotate the key later if this grows beyond demo.

### 6.4 Add Durable Job Store

Current job state lives in memory. Production needs Redis-backed jobs.

Recommended keys:

```text
job:<job_id> -> job metadata
job_events:<job_id> -> event list/stream
active_ingest:user:<user_id> -> job_id
active_ingest:global -> counter/set
```

Requirements:

- Job status survives backend restart.
- User can refresh and still see ingestion progress.
- Active ingest locks are released on terminal states.
- Jobs expire after a configured TTL.
- Lost/stale jobs are detected and marked cleanly.

Stronger beta requirement:

- The API must create the Redis job record and trigger ingestion execution outside the API process.
- Ingestion should run as a Cloud Run Job named `cortex-ingest`, or via Cloud Tasks dispatching to a dedicated ingestion worker endpoint.
- The ingestion worker/job publishes progress events to Redis.
- The API reads Redis events for SSE and polling, but does not perform the heavy ingestion work itself.

### 6.5 Add Cloud Run Job Ingestion With Shallow Clone

Current ingestion fetches all eligible GitHub file contents through the GitHub tree/blob APIs into backend memory before parsing, graph writes, embedding, and Qdrant upsert. This is acceptable for local testing with strict repo limits, but it is not the stronger beta production shape.

Production ingestion should default to a dedicated Cloud Run Job that performs a shallow git clone of the selected branch into temporary storage:

```text
API receives ingest request
-> API creates Redis job record
-> API triggers cortex-ingest Cloud Run Job
-> ingestion job shallow-clones selected repo branch into /tmp
-> ingestion job walks local files and applies filters
-> secret scan, parse, and chunk bounded batches
-> write batch graph nodes/edges to Neo4j
-> embed chunk batches
-> upsert chunk batches to Qdrant with ingest_run_id
-> release raw content and batch chunks from memory
-> repeat until all eligible files are processed
-> delete stale previous ingest runs
-> mark repo/branch ready
-> delete temporary clone
```

Recommended clone command shape:

```bash
git clone --depth 1 --single-branch --branch <branch> <authenticated_repo_url> <tmp_dir>
```

Implementation requirements:

- Keep the GitHub tree/blob API ingestion path as a local/fallback mode, but make shallow clone the production default.
- Install `git` in the ingestion image.
- Clone only the selected branch with `--depth 1 --single-branch`.
- Never log authenticated clone URLs or GitHub access tokens.
- Write the clone only to temporary job-local storage such as `/tmp`.
- Delete the temporary clone on success and failure.
- Apply the same file filters after clone before parsing/chunking.
- Enforce repository size, eligible file count, and chunk limits before expensive processing continues.
- Separate local file processing batch size from embedding batch size.
- Use a small file processing batch size, for example 5-20 files, depending on repo/file size limits.
- Use chunk-based embedding batches, for example 64-256 chunks, to preserve embedding throughput.
- Continue tagging every graph node, graph edge, and vector chunk with `user_id`, `branch`, `commit_sha`, and `ingest_run_id`.
- Ensure failed ingests delete data for the failed `ingest_run_id`.
- Ensure stale previous runs are deleted only after the new run completes successfully.
- Keep the repository marked as `processing` until all batches are complete.

Local validation before cloud rollout:

- Add an ingestion source flag such as `INGEST_SOURCE=github_api|git_clone`.
- Run old GitHub API ingestion and new git clone ingestion against the same small repo.
- Compare `files_parsed`, `chunks_created`, `graph_edges_created`, Qdrant chunk counts, and Neo4j node/edge counts.
- Test private repository cloning with token auth without logging the token.
- Test cleanup after both success and forced failure.

This reduces peak memory from "all eligible file contents plus all chunks plus all embeddings" to "one bounded local file batch plus one bounded chunk batch" and avoids hundreds of GitHub blob API calls for medium-sized repositories.

### 6.6 Add Cache Layer

Caching is required to reduce cost and avoid repeated expensive calls.

Status: implemented locally with Redis-backed JSON caches for GitHub repository lists, GitHub branch lists, snapshots, and health reports.

Cache these:

```text
github_repos:<user_id>
github_branches:<user_id>:<repo>
snapshot:<user_id>:<repo>:<branch>:<commit_sha>
health:<user_id>:<repo>:<branch>:<commit_sha>
query_embedding:<embedding_backend>:<model>:<hash>
repo_limits:<user_id>
daily_quota:<user_id>:<date>
global_quota:<date>
```

Rules:

- Include `user_id` in any cache key that can contain private data.
- Include `commit_sha` for snapshot and health cache.
- Do not cache raw OAuth codes.
- Do not cache raw GitHub tokens outside the encrypted session store.
- Do not cache raw LLM prompts.

Implementation progress:

- Added `CACHE_BACKEND=redis`.
- Added `GITHUB_CACHE_TTL_SECONDS`.
- Added `REPORT_CACHE_TTL_SECONDS`.
- GitHub repo and branch dropdown calls now use short-lived Redis cache entries.
- Snapshot and health report cache keys include user, repo, branch, and commit SHA.
- Health generation returns the cached report for repeated requests on the same commit.
- Snapshot generation writes a Redis cache entry after ingestion and refreshes it on snapshot reads.

### 6.7 Add Hard Limit Enforcement

Add a small quota/limits service used by ingestion and query routes.

Status: implemented locally with Redis-backed daily counters and active ingest locks.

The service should check:

- User indexed repo-branch count.
- User daily ingest count.
- User daily query count.
- Active user ingest lock.
- Global active ingest count.
- Repository size.
- Eligible file count.
- Chunk count.

The limit service should return structured errors:

```json
{
  "code": "repo_too_large",
  "message": "This demo currently supports repositories up to 50 MB.",
  "limit": 50,
  "unit": "MB"
}
```

The frontend should display the message without crashing.

Implementation progress:

- Added `QUOTA_BACKEND=redis`.
- Added demo limits for repo count, eligible files, chunks, active ingests, daily ingests, daily queries, and health generation per commit.
- Repo count means indexed repo-branch count. Two branches from the same GitHub repo consume two slots.
- Ingest creation checks daily ingest quota and per-user repo count before queuing a job.
- Update jobs check daily ingest quota before queuing.
- The ingestion runner uses a Redis active-ingest lock per user plus a global active-ingest counter.
- Ingestion enforces repository size, eligible file count, and chunk count.
- Query routes enforce daily query quota.
- Health checks are limited to one generation per repo/branch/commit, then served from Redis cache.

### 6.8 Add Privacy Notice And Consent

Before ingestion, users should see a short notice:

```text
Cortex will fetch the selected GitHub repository branch, redact detected secrets,
store indexed chunks in Qdrant, store structural metadata in Neo4j, and send
retrieved context to AI providers for embeddings and answers. Do not ingest repos
you are not allowed to process. You can delete indexed data at any time.
```

Add a checkbox or explicit confirmation before first ingestion:

```text
I understand Cortex will process and store indexed data from this repository.
```

Store consent timestamp in Redis or a future durable user table.

### 6.9 Add Delete My Data

Repo deletion already exists. Production also needs account-wide deletion.

Add endpoint:

```text
DELETE /api/v1/me/data
```

It should delete:

- All Qdrant chunks for `user_id`.
- All Neo4j nodes/relationships for `user_id`.
- Redis sessions for `user_id`.
- Redis job history for `user_id`.
- Redis cache entries for `user_id`.
- Ingest locks for `user_id`.
- Quota counters where appropriate.

Return:

```json
{
  "ok": true,
  "deleted": {
    "repos": 2,
    "chunks": "best_effort",
    "graph": "best_effort",
    "cache": "best_effort"
  }
}
```

### 6.10 Add Safe Logging Policy

Production logs must never include:

- GitHub OAuth codes.
- GitHub access tokens.
- API keys.
- Raw file contents.
- Raw Qdrant payload text.
- Raw cited chunks.
- Full LLM prompts.
- Secret scanner matches.

Logs may include:

- User ID hash or GitHub numeric ID.
- Repo full name only if acceptable for demo.
- Branch name.
- Counts.
- Durations.
- Status.
- Error classes.
- Job IDs.

Recommended log event examples:

```text
ingest_started user=github:123 repo=owner/name branch=main job=...
ingest_limit_hit user=github:123 code=repo_too_large limit=50
vertex_embedding_batch size=96 duration_ms=840
query_completed user=github:123 repo=owner/name mode=hybrid duration_ms=2100
```

---

## 7. Google Cloud Setup Step-by-Step

### 7.1 Install And Authenticate gcloud

Install Google Cloud CLI from:

```text
https://cloud.google.com/sdk/docs/install
```

Then authenticate:

```bash
gcloud auth login
gcloud auth application-default login
```

Set your project:

```bash
gcloud config set project YOUR_PROJECT_ID
```

Set your default region:

```bash
gcloud config set run/region us-central1
```

Confirm:

```bash
gcloud config list
```

### 7.2 Enable Billing And Budget Alerts

In Google Cloud Console:

1. Open Billing.
2. Link the project to billing/free trial credits.
3. Create a budget.
4. Set alerts at:
   - 25%
   - 50%
   - 75%
   - 90%
   - 100%

For a $300 credit pool, example alerts:

```text
$25
$50
$100
$200
$275
```

Do this before public sharing.

### 7.3 Enable Required APIs

Run:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  logging.googleapis.com \
  clouderrorreporting.googleapis.com
```

Verify:

```bash
gcloud services list --enabled
```

### 7.4 Create Artifact Registry Repository

Create a Docker repository:

```bash
gcloud artifacts repositories create cortex \
  --repository-format=docker \
  --location=us-central1 \
  --description="Cortex production containers"
```

Expected image path format:

```text
us-central1-docker.pkg.dev/YOUR_PROJECT_ID/cortex/IMAGE_NAME:TAG
```

### 7.5 Create Cloud Run Service Account

Create a dedicated runtime service account:

```bash
gcloud iam service-accounts create cortex-runner \
  --display-name="Cortex Cloud Run runtime"
```

Store the email:

```text
cortex-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Grant Vertex AI user:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:cortex-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

Grant Secret Manager secret accessor:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:cortex-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Keep permissions minimal. Do not run the app as project owner/editor.

---

## 8. External Managed Services Setup

### 8.1 Qdrant Cloud

Create a Qdrant Cloud cluster.

For demo:

- Start with free/prototype tier if available.
- Create one collection through the app on startup.
- Keep `QDRANT_COLLECTION=cortex_kb`.

Save:

```text
QDRANT_URL
QDRANT_API_KEY
QDRANT_COLLECTION=cortex_kb
```

Important:

- The Qdrant collection vector size must match the embedding dimension.
- If you change embedding model/dimension later, recreate or migrate the collection.
- Put payload indices on `user_id`, `repo`, `branch`, `commit_sha`, and `is_public`.

### 8.2 Neo4j AuraDB

Create a Neo4j AuraDB instance.

For demo:

- Free tier is okay if storage fits.
- Use one database.
- Keep credentials in Secret Manager.

Save:

```text
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
```

Important:

- Ensure tenant fields are included on nodes/relationships.
- Graph queries must filter by `user_id`.
- Deletion must delete only the current user's graph data.

### 8.3 Redis-Compatible Store

You need Redis-like storage for:

- GitHub token sessions.
- Ingestion job status/events.
- Cache.
- Quotas.
- Ingest locks.

Options:

1. Memorystore for Redis:
   - More native Google Cloud.
   - Usually needs VPC connector.
   - More setup.

2. Upstash Redis:
   - Simpler HTTP/TLS URL.
   - Good for small demo.
   - Not fully Google Cloud end-to-end, but easier.

If strict Google Cloud end-to-end matters, use Memorystore. If speed matters, use Upstash.

Required value:

```text
REDIS_URL
```

If using Memorystore, also plan VPC connector setup.

---

## 9. Secret Manager Setup

Create secrets.

Use this pattern:

```bash
printf "VALUE_HERE" | gcloud secrets create SECRET_NAME --data-file=-
```

Create these:

```bash
printf "..." | gcloud secrets create GITHUB_OAUTH_CLIENT_ID --data-file=-
printf "..." | gcloud secrets create GITHUB_OAUTH_CLIENT_SECRET --data-file=-
printf "..." | gcloud secrets create GITHUB_WEBHOOK_SECRET --data-file=-
printf "..." | gcloud secrets create GEMINI_API_KEY --data-file=-
printf "..." | gcloud secrets create QDRANT_URL --data-file=-
printf "..." | gcloud secrets create QDRANT_API_KEY --data-file=-
printf "..." | gcloud secrets create NEO4J_URI --data-file=-
printf "..." | gcloud secrets create NEO4J_USERNAME --data-file=-
printf "..." | gcloud secrets create NEO4J_PASSWORD --data-file=-
printf "..." | gcloud secrets create REDIS_URL --data-file=-
printf "..." | gcloud secrets create SESSION_ENCRYPTION_KEY --data-file=-
```

Generate `SESSION_ENCRYPTION_KEY` locally with a secure random generator. It should not be committed.

If a secret already exists, add a new version:

```bash
printf "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=-
```

Never commit `.env` production values.

---

## 10. GitHub OAuth Production Setup

Go to GitHub Developer Settings:

```text
GitHub -> Settings -> Developer settings -> OAuth Apps
```

Create or update the Cortex OAuth app.

Set:

```text
Application name: Cortex
Homepage URL: https://FRONTEND_CLOUD_RUN_URL
Authorization callback URL: https://FRONTEND_CLOUD_RUN_URL/auth/callback
```

Backend login flow builds GitHub auth URL using:

```text
FRONTEND_URL/auth/callback
```

So production `FRONTEND_URL` must exactly match the Cloud Run frontend URL or custom domain.

Current requested scope:

```text
read:user,repo
```

The `repo` scope is needed for private repositories, but it is broad. Add privacy copy in the UI explaining why it is requested.

---

## 11. Backend Deployment Steps

### 11.1 Prepare Backend Dockerfile

Production backend container requirements:

- Install Python dependencies.
- Copy backend source.
- Listen on Cloud Run `$PORT`.
- Do not use reload.
- Do not expose secrets in image.

Expected final command:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
```

Before building, confirm:

```bash
docker build -t cortex-api-local .
```

Run locally:

```bash
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  cortex-api-local
```

Check:

```bash
curl http://localhost:8080/health
```

Expected:

```json
{"status":"healthy"}
```

### 11.2 Build Backend Image

From repo root:

```bash
gcloud builds submit . \
  --tag us-central1-docker.pkg.dev/YOUR_PROJECT_ID/cortex/cortex-api:latest
```

If the Dockerfile expects repo root context, use repo root. If you later split backend/frontend Dockerfiles, pass the correct `--file` through Cloud Build config.

### 11.3 Deploy Backend To Cloud Run

Initial deploy:

```bash
gcloud run deploy cortex-api \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/cortex/cortex-api:latest \
  --region us-central1 \
  --service-account cortex-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2 \
  --concurrency 20 \
  --timeout 900 \
  --set-env-vars ENVIRONMENT=production,EMBEDDING_BACKEND=vertex,VERTEX_PROJECT_ID=YOUR_PROJECT_ID,VERTEX_LOCATION=us-central1,VERTEX_EMBEDDING_MODEL=text-embedding-005,EMBEDDING_DIMENSIONS=768,QDRANT_COLLECTION=cortex_kb,ACCESS_MODE=open_limited,MAX_REPO_SIZE_MB=50,GITHUB_FETCH_CONCURRENCY=5,FILE_PROCESSING_CONCURRENCY=4 \
  --set-secrets GITHUB_OAUTH_CLIENT_ID=GITHUB_OAUTH_CLIENT_ID:latest,GITHUB_OAUTH_CLIENT_SECRET=GITHUB_OAUTH_CLIENT_SECRET:latest,GITHUB_WEBHOOK_SECRET=GITHUB_WEBHOOK_SECRET:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,QDRANT_URL=QDRANT_URL:latest,QDRANT_API_KEY=QDRANT_API_KEY:latest,NEO4J_URI=NEO4J_URI:latest,NEO4J_USERNAME=NEO4J_USERNAME:latest,NEO4J_PASSWORD=NEO4J_PASSWORD:latest,REDIS_URL=REDIS_URL:latest,SESSION_ENCRYPTION_KEY=SESSION_ENCRYPTION_KEY:latest
```

After deploy, Cloud Run prints a backend URL:

```text
https://cortex-api-xxxxx-uc.a.run.app
```

Save this as:

```text
BACKEND_URL
```

### 11.4 Update Backend URL Env Var

Once you know the backend URL, update service env vars:

```bash
gcloud run services update cortex-api \
  --region us-central1 \
  --update-env-vars BACKEND_URL=https://BACKEND_CLOUD_RUN_URL
```

Later, after frontend is deployed, update:

```bash
gcloud run services update cortex-api \
  --region us-central1 \
  --update-env-vars FRONTEND_URL=https://FRONTEND_CLOUD_RUN_URL,CORS_ORIGINS=https://FRONTEND_CLOUD_RUN_URL
```

### 11.5 Backend Smoke Test

Run:

```bash
curl https://BACKEND_CLOUD_RUN_URL/health
```

Expected:

```json
{"status":"healthy"}
```

Add a richer readiness endpoint before final launch:

```text
GET /ready
```

It should verify:

- Qdrant reachable.
- Neo4j reachable.
- Redis reachable.
- Vertex credentials usable.
- Gemini key present.

---

## 12. Frontend Deployment Steps

### 12.1 Prepare Frontend Container

Create or update a frontend Dockerfile for Next.js production.

Requirements:

- Install dependencies.
- Build Next.js app.
- Start with `next start`.
- Listen on Cloud Run `$PORT`.
- Set `NEXT_PUBLIC_API_URL` at build/deploy time.

Production start command:

```bash
next start -p ${PORT:-8080}
```

Important:

If `NEXT_PUBLIC_API_URL` is used at build time, the image must be rebuilt when the backend URL changes. If possible, keep public runtime config simple and stable.

### 12.2 Build Frontend Image

From repo root or frontend directory depending on Dockerfile:

```bash
gcloud builds submit frontend \
  --tag us-central1-docker.pkg.dev/YOUR_PROJECT_ID/cortex/cortex-web:latest
```

### 12.3 Deploy Frontend To Cloud Run

Deploy:

```bash
gcloud run deploy cortex-web \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/cortex/cortex-web:latest \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2 \
  --concurrency 80 \
  --timeout 300 \
  --set-env-vars NEXT_PUBLIC_API_URL=https://BACKEND_CLOUD_RUN_URL
```

Cloud Run prints a frontend URL:

```text
https://cortex-web-xxxxx-uc.a.run.app
```

Save this as:

```text
FRONTEND_URL
```

### 12.4 Update Backend CORS And OAuth URL

Update backend:

```bash
gcloud run services update cortex-api \
  --region us-central1 \
  --update-env-vars FRONTEND_URL=https://FRONTEND_CLOUD_RUN_URL,CORS_ORIGINS=https://FRONTEND_CLOUD_RUN_URL
```

Then update GitHub OAuth callback:

```text
https://FRONTEND_CLOUD_RUN_URL/auth/callback
```

### 12.5 Frontend Smoke Test

Open:

```text
https://FRONTEND_CLOUD_RUN_URL
```

Check:

- Page loads.
- Login button appears.
- No frontend console errors.
- API calls target backend URL.
- CORS does not fail.

---

## 13. Cookies, CORS, And Auth Details

Production cookies must be:

```text
HttpOnly=true
Secure=true
SameSite=Lax
Path=/
```

Because frontend and backend are on different Cloud Run subdomains, confirm whether the browser sends cookies correctly with `credentials: "include"`.

Potential issue:

If frontend and backend are on different registrable domains/subdomains, cookie behavior can become tricky. Cloud Run service URLs are both under `run.app`, but different subdomains. For best long-term stability, use custom domains:

```text
https://app.yourdomain.com
https://api.yourdomain.com
```

Then configure cookies accordingly.

For initial demo, test carefully with the Cloud Run URLs. If login works locally but fails in production, inspect:

- `Set-Cookie` header.
- Cookie domain.
- `Secure`.
- `SameSite`.
- CORS `Access-Control-Allow-Origin`.
- CORS `Access-Control-Allow-Credentials`.
- Frontend `credentials: "include"`.

Backend CORS must not use wildcard origins with credentials.

Use:

```env
CORS_ORIGINS=https://FRONTEND_CLOUD_RUN_URL
```

---

## 14. Privacy And Security Implementation Details

### 14.1 Consent Before Ingestion

Add a modal or inline confirmation before the first ingest.

Text:

```text
Cortex will fetch this GitHub repository branch, redact detected secrets, store
indexed chunks in Qdrant, store structural metadata in Neo4j, and send retrieved
context to AI providers for embeddings and answers. Only ingest repositories you
are allowed to process. You can delete indexed data at any time.
```

Required button:

```text
I understand and want to ingest this repository
```

Store:

```text
consent:<user_id> -> timestamp/version
```

### 14.2 Data Deletion

Expose in UI:

- Delete this repo.
- Delete all my Cortex data.

Repo deletion:

```text
DELETE /api/v1/repos/{owner}/{repo_name}?branch=<branch>
```

Account deletion:

```text
DELETE /api/v1/me/data
```

Deletion must cover:

- Qdrant chunks.
- Neo4j graph nodes/relationships.
- Redis sessions.
- Redis jobs.
- Redis caches.
- Quota counters where appropriate.

### 14.3 Secret Redaction

Secret redaction must happen before:

- Embeddings.
- Qdrant storage.
- Neo4j graph extraction where source content may be stored.
- LLM prompts.
- Citation display.

Expand patterns for:

- GitHub tokens.
- Google API keys.
- Gemini/Groq/OpenAI keys.
- AWS access keys.
- Private key blocks.
- JWT-like strings.
- Database URLs.
- `.env` assignments.

Secret-related queries should not reveal values. They should answer safely:

```text
I can confirm this file appears to contain secret-like material, but Cortex does not expose secret values.
```

### 14.4 Logging Rules

Never log:

- GitHub access tokens.
- OAuth codes.
- Raw private file contents.
- Raw chunks.
- Full prompts.
- Full LLM responses if they may contain code.
- Secret values.

Allowed:

- Counts.
- IDs.
- Timings.
- Error types.
- Repo name if accepted for demo.
- Branch.
- Commit SHA.

### 14.5 Tenant Isolation

Every read/write/delete must be scoped by `user_id`.

Validate:

- Qdrant filters include `user_id`.
- Neo4j queries include `user_id`.
- Cache keys include `user_id`.
- Job lookup checks `job.user_id == current_user.user_id`.
- Repo deletion checks ownership.
- Graph exploration checks ownership.
- Snapshot and health check reads check ownership.

This is the most important privacy invariant.

---

## 15. Caching Strategy

### 15.1 GitHub Cache

Cache:

```text
github_repos:<user_id>
github_branches:<user_id>:<owner/repo>
```

TTL:

```text
5-15 minutes
```

Do not cache GitHub tokens here.

### 15.2 Snapshot Cache

Cache key:

```text
snapshot:<user_id>:<repo>:<branch>:<commit_sha>
```

Behavior:

- Generate once after ingestion.
- Store in Neo4j repository node.
- Also cache in Redis for quick UI fetch.
- Regenerate only when commit changes.

### 15.3 Health Check Cache

Cache key:

```text
health:<user_id>:<repo>:<branch>:<commit_sha>
```

Behavior:

- Generate once per commit.
- Return cached report on repeated clicks.
- Do not allow repeated generation to burn LLM credits.

### 15.4 Query Embedding Cache

Cache key:

```text
query_embedding:<backend>:<model>:<sha256(query)>
```

TTL:

```text
1-7 days
```

Only cache query embeddings, not document embeddings during ingestion unless there is a clear need. Ingestion chunks are already persisted in Qdrant.

### 15.5 Limit Counters

Counters:

```text
quota:queries:<user_id>:YYYY-MM-DD
quota:ingests:<user_id>:YYYY-MM-DD
quota:global_embeddings:YYYY-MM-DD
quota:global_ingests:YYYY-MM-DD
```

Use atomic Redis increments.

---

## 16. Operational Settings

Initial Cloud Run backend settings:

```text
CPU: 1
Memory: 2Gi
Min instances: 0
Max instances: 2
Concurrency: 20
Timeout: 900 seconds
Workers: 1
```

Initial Cloud Run frontend settings:

```text
CPU: 1
Memory: 1Gi
Min instances: 0
Max instances: 2
Concurrency: 80
Timeout: 300 seconds
```

Initial ingestion settings:

```env
GITHUB_FETCH_CONCURRENCY=5
FILE_PROCESSING_CONCURRENCY=4
MAX_REPO_SIZE_MB=50
```

Why conservative:

- Cloud Run instances are stateless.
- Ingestion is memory-heavy.
- Qdrant/Neo4j free tiers are limited.
- GitHub rate limits can interrupt large fetches.
- Public demo abuse is possible.

---

## 17. Monitoring And Alerts

### 17.1 Cloud Logging

Use structured logs for:

- Login success/failure.
- Ingest start/end/failure.
- Limit hits.
- Query start/end/failure.
- Vertex embedding batch failures.
- Qdrant/Neo4j failures.
- Deletion events.

Do not log raw content.

### 17.2 Error Reporting

Enable Error Reporting and inspect:

- 500s.
- Unhandled exceptions.
- Vertex quota errors.
- Qdrant schema mismatch.
- Neo4j connectivity errors.

### 17.3 Budget Alerts

Set budget alerts before launch.

Suggested:

```text
25%
50%
75%
90%
100%
```

### 17.4 Manual Daily Checks During Demo

During the first few days:

- Check Cloud Run request count.
- Check Cloud Run instance count.
- Check Vertex AI usage.
- Check Qdrant storage.
- Check Neo4j storage.
- Check error logs.
- Check Redis memory.
- Check number of indexed repos.

---

## 18. End-to-End Validation Checklist

Run these before sharing the link.

### 18.1 Single User Happy Path

1. Open frontend.
2. Click GitHub login.
3. Authorize app.
4. Confirm `/auth/me` returns current user.
5. List GitHub repos.
6. Select a small repo.
7. Select branch.
8. Accept privacy notice.
9. Start ingest.
10. Refresh page during ingest.
11. Confirm job status survives refresh.
12. Wait for ready state.
13. Ask a semantic question.
14. Confirm answer has citations.
15. Click citation.
16. Confirm cited chunk opens.
17. Open graph page.
18. Confirm graph loads.
19. Open architecture snapshot.
20. Open health check.
21. Run health check again and confirm cached result is used.
22. Delete repo.
23. Confirm repo disappears.

### 18.2 Two User Isolation Test

1. User A logs in.
2. User A ingests repo.
3. User B logs in in another browser/profile.
4. User B must not see User A's indexed repo.
5. User B must not access User A graph endpoint.
6. User B must not access User A snapshot.
7. User B must not access User A health report.
8. User B must not access User A citations.
9. User B can ingest their own repo.
10. User A cannot see User B data.

### 18.3 Limit Tests

Test:

- Repo too large.
- Too many files.
- Too many chunks.
- Too many daily queries.
- Too many daily ingests.
- Second active ingest blocked.
- Global active ingest cap.

Expected:

- No crash.
- Clear message.
- No ready status for failed partial ingest.
- No unbounded API calls after limit hit.

### 18.4 Security Tests

Check browser:

- No GitHub token in localStorage.
- No GitHub token in sessionStorage.
- No GitHub token in frontend JS.
- Cookie is HttpOnly.
- Cookie is Secure.

Check API:

- Unauthenticated calls return 401.
- Cross-user calls return 403 or 404.
- CORS only allows frontend origin.
- Credentials are required where needed.

Check logs:

- No raw source text.
- No OAuth code.
- No GitHub token.
- No full prompts.
- No secret values.

### 18.5 Failure Tests

Simulate:

- Redis unavailable.
- Qdrant unavailable.
- Neo4j unavailable.
- Vertex quota/permission error.
- GitHub rate limit.
- Backend restart during ingest.

Expected:

- Friendly failure.
- Job marked failed/lost/retryable.
- No silent data leak.
- No infinite retry loop.

---

## 19. Launch Sequence

Use this exact sequence.

1. Finish production code changes locally.
2. Run local backend tests.
3. Run local frontend build.
4. Create Google Cloud project.
5. Enable billing and budget alerts.
6. Enable APIs.
7. Create Artifact Registry.
8. Create service account.
9. Create Secret Manager secrets.
10. Create Qdrant cluster.
11. Create Neo4j AuraDB.
12. Create Redis store.
13. Build backend image.
14. Deploy backend to Cloud Run.
15. Smoke test backend `/health`.
16. Build frontend image.
17. Deploy frontend to Cloud Run.
18. Update backend `FRONTEND_URL` and `CORS_ORIGINS`.
19. Update GitHub OAuth callback URL.
20. Run single-user happy path.
21. Run two-user isolation test.
22. Run limit tests.
23. Run deletion test.
24. Inspect logs for sensitive data.
25. Share link with 1-2 trusted users.
26. Watch usage/errors.
27. Then share with the remaining test group.

Do not start with all 20 users.

---

## 20. Rollback Plan

If something breaks:

### Disable New Ingestion

Set:

```env
ACCESS_MODE=read_only
```

or:

```env
INGESTION_ENABLED=false
```

The app should still allow:

- Login.
- Viewing existing repos.
- Querying existing repos if safe.
- Deleting data.

### Reduce Cost Immediately

Run:

```bash
gcloud run services update cortex-api \
  --region us-central1 \
  --max-instances 1
```

Set stricter limits:

```bash
gcloud run services update cortex-api \
  --region us-central1 \
  --update-env-vars MAX_GLOBAL_ACTIVE_INGESTS=0,MAX_QUERIES_PER_USER_PER_DAY=5
```

### Disable Public Access

If needed:

```bash
gcloud run services remove-iam-policy-binding cortex-api \
  --region us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

Do the same for frontend if the site must go offline.

### Revert Cloud Run Revision

List revisions:

```bash
gcloud run revisions list --service cortex-api --region us-central1
```

Route traffic back in the Cloud Console or with `gcloud run services update-traffic`.

---

## 21. Known Production Risks

### Risk: Ingestion Job Interruption

Impact:

- The ingestion job could be interrupted by Cloud Run Job failure, timeout, quota issues, or infrastructure restart.
- Partial Qdrant/Neo4j data for the active `ingest_run_id` could remain if cleanup fails.

Mitigation:

- Redis-backed job store.
- Run ingestion outside the API process as `cortex-ingest`.
- Tag every write with `ingest_run_id`.
- Delete failed-run data before marking the job terminal.
- Mark the repository ready only after all batches succeed.

### Risk: Agent Tool Context Is Process-Global

Impact:

- `backend/agents/tools.py` stores `_current_user_id` and `_current_branch` as module-level globals.
- The comment says thread-local, but the implementation is plain process-global state.
- Concurrent production requests could overwrite each other's tool context, causing incorrect tenant or branch scoping.

Mitigation:

- Replace the globals with request-scoped context before production.
- Prefer Python `contextvars` for the current async request, or pass user/branch context explicitly into tool execution.
- Add concurrent two-user tests that run agent/tool queries at the same time and verify Qdrant/Neo4j filters stay isolated.

### Risk: Private Repo Data Exposure

Impact:

- Serious trust/privacy issue.

Mitigation:

- Strict tenant filtering.
- Two-user isolation tests.
- No raw logs.
- Delete-all-data endpoint.
- Consent copy.

### Risk: Cost Spike

Impact:

- Credits consumed quickly.

Mitigation:

- Hard limits.
- Budget alerts.
- Max instances.
- Cached snapshots/health.
- Small repo size cap.

### Risk: OAuth Scope Concern

Impact:

- Users may hesitate to authorize broad private repo access.

Mitigation:

- Explain why `repo` scope is needed.
- Consider public-only mode later with narrower scopes.

### Risk: Qdrant Dimension Mismatch

Impact:

- Ingestion/query failures.

Mitigation:

- Keep `text-embedding-005` with current dimension config.
- Validate collection dimension at startup.
- Fail loudly with clear message.

### Risk: Free Tier Storage Limits

Impact:

- Ingestion fails once Qdrant/Neo4j fills.

Mitigation:

- Max repos/user.
- Max chunks/repo.
- Delete inactive data.
- Manual usage monitoring.

---

## 22. Documentation And Official References

Use these docs while implementing:

- Cloud Run deploy containers: https://cloud.google.com/run/docs/deploying
- gcloud run reference: https://cloud.google.com/sdk/gcloud/reference/run
- Cloud Run secrets with Secret Manager: https://docs.cloud.google.com/run/docs/configuring/services/secrets
- Artifact Registry Docker repositories: https://cloud.google.com/artifact-registry/docs/docker/store-docker-container-images
- Vertex AI text embeddings: https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings
- Vertex AI quotas: https://cloud.google.com/vertex-ai/generative-ai/docs/quotas
- Vertex AI pricing: https://cloud.google.com/vertex-ai/generative-ai/pricing
- Google Cloud free trial: https://cloud.google.com/free

---

## 23. Final Pre-Launch Checklist

Do not share the public link until every item below is true.

### Code readiness

- [ ] Backend listens on `$PORT`.
- [ ] Frontend listens on `$PORT`.
- [ ] Production Docker images build successfully.
- [ ] Vertex embedding backend implemented.
- [ ] FastEmbed still works locally.
- [ ] Redis session store implemented.
- [ ] Redis job store implemented.
- [ ] Cache layer implemented.
- [ ] Hard limits implemented.
- [ ] Privacy consent implemented.
- [ ] Delete-all-data endpoint implemented.
- [ ] Safe logging reviewed.

### Cloud readiness

- [ ] Billing enabled.
- [ ] Budget alerts configured.
- [ ] Required APIs enabled.
- [ ] Artifact Registry created.
- [ ] Cloud Run service account created.
- [ ] Minimal IAM granted.
- [ ] Secrets stored in Secret Manager.
- [ ] Backend deployed.
- [ ] Frontend deployed.
- [ ] GitHub OAuth callback updated.
- [ ] CORS set to exact frontend URL.

### Data readiness

- [ ] Qdrant reachable.
- [ ] Neo4j reachable.
- [ ] Redis reachable.
- [ ] Qdrant collection dimension validated.
- [ ] Neo4j tenant constraints/indexes created where needed.

### Security readiness

- [ ] No production secrets in repo.
- [ ] Existing dev secrets rotated if they were exposed.
- [ ] No GitHub token in browser storage.
- [ ] Cookies are HttpOnly and Secure.
- [ ] Cross-user access denied.
- [ ] Logs contain no raw code or secrets.
- [ ] Delete repo works.
- [ ] Delete all my data works.

### Product readiness

- [ ] Login works.
- [ ] Repo listing works.
- [ ] Ingestion works.
- [ ] Query works.
- [ ] Citations work.
- [ ] Graph works.
- [ ] Snapshot works.
- [ ] Health check works.
- [ ] Cached health check works.
- [ ] Limits display clean errors.

Once this checklist passes, share with 1-2 trusted testers first, then expand gradually.
