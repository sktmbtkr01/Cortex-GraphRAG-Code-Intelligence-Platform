import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from langchain_core.messages import AIMessage, ToolMessage

from core.auth import AuthenticatedUser, get_current_user
from core.config import settings
from models.schemas import (
    GraphExploreResponse,
    GraphStatsResponse,
    IngestRequest,
    IngestJobResponse,
    QueryRequest,
    QueryResponse,
    RetrievalTraceStep,
    RepoStatus,
    SnapshotResponse,
    AuditResponse,
    HealthCheckResponse,
)

router = APIRouter()


from indexing.qdrant_store import VectorStore
from indexing.embedder import CortexEmbedder
from indexing.graph_builder.neo4j_manager import Neo4jManager
from retrieval.rag_pipeline import RAGPipeline
from agents.supervisor import run_agent
from agents.tools import get_call_graph, get_dependencies, set_agent_user_context
from ingestion.github_client import GitHubClient
from ingestion.runner import run_ingest_job
from core.job_store import job_store
from core.cache_limits import (
    cache_get_json,
    cache_set_json,
    check_daily_health_quota,
    check_daily_ingest_quota,
    check_daily_query_quota,
    enforce_repo_count_limit,
    github_branches_cache_key,
    github_repos_cache_key,
    health_cache_key,
    snapshot_cache_key,
)
from core.tenant import tenant_scoped_id


def _repo_branch_id(repo: str, branch: str) -> str:
    return f"{repo}::{branch}"


def _json_safe_graph_value(value):
    if isinstance(value, dict):
        return {k: _json_safe_graph_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_graph_value(v) for v in value]
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


GRAPH_PROPERTY_EXCLUDE_FIELDS = {
    "health_report",
    "health_report_commit_sha",
    "health_checked_at",
    "snapshot",
}


def _json_safe_graph_properties(properties: dict) -> dict:
    return {
        key: _json_safe_graph_value(value)
        for key, value in properties.items()
        if key not in GRAPH_PROPERTY_EXCLUDE_FIELDS
    }


def _route_query_intent(query: str) -> str:
    """Small deterministic router for obvious tool-needed queries."""
    q = query.lower()
    if any(term in q for term in ("calls", "called by", "call graph", "who calls", "what calls")):
        return "graph"
    if any(term in q for term in ("import ", "imports", "imported by", "depends on", "dependency", "package", "module usage")):
        return "graph"
    if any(term in q for term in ("history", "modified", "changed", "pr ", "pull request", "commit")):
        return "agent"
    return "semantic"


def _graph_tool_intent(query: str) -> tuple[str, str] | None:
    """Return the deterministic graph tool and target entity for obvious queries."""
    q = query.strip()
    lowered = q.lower()

    call_match = re.search(
        r"(?:what|who)\s+calls\s+[`'\"]?([A-Za-z_][\w.]*)[`'\"]?|call graph\s+(?:for|of)\s+[`'\"]?([A-Za-z_][\w.]*)[`'\"]?",
        q,
        flags=re.IGNORECASE,
    )
    if call_match:
        return "get_call_graph", next(group for group in call_match.groups() if group)

    dep_match = re.search(
        r"(?:who\s+imports|what\s+imports|imported\s+by|dependency usage of|module usage of|depends on)\s+[`'\"]?([A-Za-z_][\w.-]*)[`'\"]?",
        q,
        flags=re.IGNORECASE,
    )
    if dep_match:
        return "get_dependencies", dep_match.group(1)

    if any(term in lowered for term in ("dependency", "package", "module usage", "imports")):
        tokens = re.findall(r"[A-Za-z_][\w.-]*", q)
        stopwords = {"who", "what", "where", "imports", "import", "imported", "by", "dependency", "usage", "of", "package", "module", "depends", "on"}
        candidates = [token for token in tokens if token.lower() not in stopwords]
        if candidates:
            return "get_dependencies", candidates[-1]

    return None


def _trace_kind(tool_name: str) -> str:
    if tool_name in {"get_call_graph", "get_dependencies"}:
        return "graph"
    if tool_name in {"get_file_history", "get_file_content"}:
        return "file"
    if tool_name in {"search_code", "search_issues"}:
        return "semantic"
    if tool_name == "calculate_math":
        return "utility"
    return "agent"


def _summarize_tool_result(content: str) -> str:
    text = content.strip().replace("\r", "")
    if not text:
        return "Returned no visible output"
    if text.startswith("No "):
        return text.splitlines()[0][:180]
    lines = [line for line in text.splitlines() if line.strip()]
    return f"Returned {len(lines)} lines of tool output"


def _tool_output_has_no_data(content: str) -> bool:
    text = content.strip().lower()
    return (
        not text
        or text.startswith("no ")
        or "no call graph data found" in text
        or "none found" in text
        or "no pr history found" in text
        or "not found in index" in text
    )


def _extract_trace(messages: list) -> list[RetrievalTraceStep]:
    trace: list[RetrievalTraceStep] = []
    pending: dict[str, dict] = {}

    for msg in messages:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls or []:
                call_id = call.get("id") or f"call-{len(pending) + 1}"
                pending[call_id] = {
                    "tool": call.get("name", "unknown_tool"),
                    "input": call.get("args") or {},
                }
        elif isinstance(msg, ToolMessage):
            call = pending.pop(msg.tool_call_id, None)
            tool_name = getattr(msg, "name", None) or (call or {}).get("tool") or "unknown_tool"
            trace.append(
                RetrievalTraceStep(
                    step=len(trace) + 1,
                    kind=_trace_kind(tool_name),
                    tool=tool_name,
                    input=(call or {}).get("input") or {},
                    summary=_summarize_tool_result(str(msg.content)),
                )
            )

    return trace


def _answer_from_trace(trace: list[RetrievalTraceStep]) -> str:
    if not trace:
        return "I could not produce an answer from the available retrieval steps."

    no_data = [
        step.summary
        for step in trace
        if step.summary.lower().startswith("no ") or "no " in step.summary.lower()
    ]
    if no_data:
        return "\n".join(f"- {item}" for item in no_data)

    return "Retrieval summary:\n\n" + "\n".join(
        f"- {step.tool}: {step.summary}" for step in trace
    )


@router.post("/ingest", response_model=IngestJobResponse)
async def ingest_repo(
    request: IngestRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> IngestJobResponse:
    """Start ingestion in the background and return a streamable job id immediately."""
    try:
        request.repo.split("/")
    except ValueError:
        raise HTTPException(status_code=400, detail="Repo must be 'owner/repo' format")

    neo4j = Neo4jManager()
    requested_branch = request.branch or "main"
    existing_rows = neo4j.run_query(
        "MATCH (r:Repository) WHERE r.user_id = $user_id "
        "WITH count(DISTINCT r.id) AS count "
        "OPTIONAL MATCH (existing:Repository {full_name: $repo}) "
        "WHERE existing.user_id = $user_id "
        "AND coalesce(existing.branch, existing.default_branch, 'main') = $branch "
        "RETURN count, count(existing) AS existing_repo_count",
        {"user_id": user.user_id, "repo": request.repo, "branch": requested_branch},
    )
    existing_count = int((existing_rows[0] if existing_rows else {}).get("count", 0) or 0)
    existing_repo_count = int((existing_rows[0] if existing_rows else {}).get("existing_repo_count", 0) or 0)
    if existing_repo_count == 0:
        enforce_repo_count_limit(existing_count)
    check_daily_ingest_quota(user.user_id)

    job_id = job_store.create_job(user_id=user.user_id, repo=request.repo)
    asyncio.create_task(run_ingest_job(job_id=job_id, request=request, user=user))

    return IngestJobResponse(
        job_id=job_id,
        status="accepted",
        repo=request.repo,
        branch=requested_branch,
        message=f"Ingestion started in background for {request.repo} @ {requested_branch}",
    )


@router.post("/repos/{owner}/{repo_name}/branches/{branch:path}/update", response_model=IngestJobResponse)
async def update_repo_branch(
    owner: str,
    repo_name: str,
    branch: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> IngestJobResponse:
    """Check a branch head SHA and queue re-ingestion only when it changed."""
    full_name = f"{owner}/{repo_name}"
    try:
        neo4j = Neo4jManager()
        rows = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE r.user_id = $user_id AND coalesce(r.branch, r.default_branch, 'main') = $branch "
            "RETURN r.commit_sha AS commit_sha, r.is_public AS is_public",
            {"repo": full_name, "branch": branch, "user_id": user.user_id},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Indexed branch not found")

        previous_commit_sha = rows[0].get("commit_sha")
        async with GitHubClient(token=user.github_token) as github:
            branch_data = await github.fetch_branch(owner, repo_name, branch)
        latest_commit_sha = (branch_data.get("commit") or {}).get("sha")

        if previous_commit_sha and latest_commit_sha == previous_commit_sha:
            return IngestJobResponse(
                job_id="",
                status="up_to_date",
                repo=full_name,
                branch=branch,
                previous_commit_sha=previous_commit_sha,
                latest_commit_sha=latest_commit_sha,
                message=f"{full_name} @ {branch} is already up to date",
            )

        check_daily_ingest_quota(user.user_id)
        job_id = job_store.create_job(user_id=user.user_id, repo=full_name)
        request = IngestRequest(
            repo=full_name,
            branch=branch,
            include_issues=False,
            include_prs=False,
            include_commits=False,
            max_commits=0,
        )
        asyncio.create_task(
            run_ingest_job(
                job_id=job_id,
                request=request,
                user=user,
                initial_status="updating",
                failure_status="update_failed",
                previous_commit_sha=previous_commit_sha,
            )
        )
        return IngestJobResponse(
            job_id=job_id,
            status="accepted",
            repo=full_name,
            branch=branch,
            previous_commit_sha=previous_commit_sha,
            latest_commit_sha=latest_commit_sha,
            message=f"Update started for {full_name} @ {branch}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/stream")
async def ingest_stream(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse:
    """Stream ingest progress events for a background ingestion job."""
    job = job_store.get_job(job_id)
    if not job:
        async def missing_job_event_gen():
            payload = job_store.lost_event(job_id)
            yield f"data: {json.dumps(payload)}\\n\\n"

        return StreamingResponse(
            missing_job_event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    if job.user_id != user.user_id:
        async def unauthorized_event_gen():
            payload = {
                "type": "error",
                "state": "error",
                "stage": "error",
                "repo": job.repo,
                "message": "Not authorized for this ingest job.",
            }
            yield f"data: {json.dumps(payload)}\\n\\n"

        return StreamingResponse(
            unauthorized_event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def event_gen():
        cursor = 0
        while True:
            if await request.is_disconnected():
                break

            events, cursor, done = await job_store.wait_for_events(job_id=job_id, cursor=cursor)
            if not events:
                yield ": keep-alive\n\n"
                if done:
                    break
                continue

            for event in events:
                yield f"data: {json.dumps(event)}\\n\\n"

            if done:
                break

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ingest/jobs/{job_id}")
async def ingest_job_status(
    job_id: str,
    cursor: int = 0,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, object]:
    """Polling-friendly ingest status endpoint with incremental events."""
    snapshot = job_store.get_snapshot(job_id)
    if not snapshot:
        event = job_store.lost_event(job_id)
        return {
            "job_id": job_id,
            "repo": None,
            "status": "lost",
            "done": True,
            "cursor": cursor,
            "events": [event],
        }
    if snapshot["user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized for this ingest job")

    events, new_cursor, done = job_store.get_events_since(job_id=job_id, cursor=cursor)
    return {
        "job_id": snapshot["job_id"],
        "repo": snapshot["repo"],
        "status": snapshot["status"],
        "done": done,
        "cursor": new_cursor,
        "events": events,
    }


@router.get("/repos", response_model=list[RepoStatus])
async def list_repos(
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[RepoStatus]:
    """List repositories accessible to this user (owned + public)."""
    try:
        neo4j = Neo4jManager()
        # Return repos owned by this user OR marked as public
        records = neo4j.run_query(
            "MATCH (r:Repository) "
            "WHERE (r.user_id = $user_id OR r.is_public = true) "
            "RETURN r.full_name AS repo, coalesce(r.branch, r.default_branch, 'main') AS branch, "
            "r.commit_sha AS commit_sha, r.is_private AS is_private, "
            "coalesce(r.ingestion_status, 'ready') AS ingestion_status, "
            "r.last_ingest_at AS last_indexed, r.user_id AS owner_id "
            "ORDER BY repo, branch",
            {"user_id": user.user_id},
        )
        repos = []
        for r in records:
            repo_name = r.get("repo")
            if not repo_name:
                continue
            is_priv = r.get("is_private")
            if is_priv is None:
                is_priv = False
            repos.append(
                RepoStatus(
                    repo=repo_name,
                    branch=str(r.get("branch") or "main"),
                    commit_sha=r.get("commit_sha"),
                    is_private=is_priv,
                    ingestion_status=str(r.get("ingestion_status") or "ready"),
                )
            )
        return repos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/repos/{owner}/{repo_name}/branches")
async def list_repo_branches(
    owner: str,
    repo_name: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    """List branches for a GitHub repository the user can access."""
    try:
        cache_key = github_branches_cache_key(user.user_id, f"{owner}/{repo_name}")
        cached = cache_get_json(cache_key)
        if cached is not None:
            return cached

        async with GitHubClient(token=user.github_token) as github:
            branches = await github.fetch_branches(owner, repo_name)
        response = [
            {
                "name": b.get("name"),
                "commit_sha": (b.get("commit") or {}).get("sha"),
            }
            for b in branches
            if b.get("name")
        ]
        cache_set_json(cache_key, response, settings.github_cache_ttl_seconds)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/my-repos")
async def list_my_github_repos(
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    """List repositories from the authenticated user's GitHub account."""
    try:
        if not user.github_token:
            raise HTTPException(
                status_code=401,
                detail="GitHub session expired. Sign in again to access repositories.",
            )
        cache_key = github_repos_cache_key(user.user_id)
        cached = cache_get_json(cache_key)
        if cached is not None:
            return cached

        async with GitHubClient(token=user.github_token) as github:
            repos = await github.list_user_repos(max_repos=200)

        response = [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "private": bool(r.get("private", False)),
                "language": r.get("language"),
                "stars": int(r.get("stargazers_count", 0) or 0),
                "default_branch": r.get("default_branch") or "main",
            }
            for r in repos
            if r.get("full_name")
        ]
        cache_set_json(cache_key, response, settings.github_cache_ttl_seconds)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/repos/{owner}/{repo_name}")
async def delete_repo(
    owner: str,
    repo_name: str,
    branch: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, object]:
    """Delete a repository branch index, or all branches when branch is omitted."""
    full_name = f"{owner}/{repo_name}"
    try:
        # Verify ownership before deletion
        neo4j = Neo4jManager()
        ownership_query = (
            "MATCH (r:Repository) "
            "WHERE (r.full_name = $repo OR r.repo = $repo) "
            "AND r.user_id = $user_id "
        )
        params = {"repo": full_name, "user_id": user.user_id, "branch": branch}
        if branch:
            ownership_query += "AND coalesce(r.branch, r.default_branch, 'main') = $branch "
        ownership_query += "RETURN r.user_id AS uid"
        ownership = neo4j.run_query(ownership_query, params)
        if not ownership:
            raise HTTPException(status_code=403, detail="You can only delete your own repositories")

        vector_store = None
        qdrant_remaining: int | None = None
        qdrant_delete_error: str | None = None
        try:
            vector_store = VectorStore()
            vector_store.delete_by_repo(full_name, user_id=user.user_id, branch=branch)
        except Exception as exc:
            # Interrupted ingests can leave Neo4j repo/status nodes before any
            # Qdrant collection or points exist. Deletion should still clear graph state.
            qdrant_delete_error = str(exc)

        if branch:
            neo4j.run_query(
                "MATCH (n) WHERE (n.repo = $repo OR n.full_name = $repo) "
                "AND n.user_id = $user_id "
                "AND coalesce(n.branch, 'main') = $branch DETACH DELETE n",
                {"repo": full_name, "branch": branch, "user_id": user.user_id},
            )
            neo4j.run_query(
                "MATCH (s:Snapshot) WHERE s.repo = $repo AND s.user_id = $user_id "
                "AND coalesce(s.branch, 'main') = $branch DETACH DELETE s",
                {"repo": full_name, "branch": branch, "user_id": user.user_id},
            )
            neo4j.run_query(
                "MATCH (n) WHERE (n.raw_id STARTS WITH $repo_prefix OR n.id STARTS WITH $tenant_repo_prefix) "
                "AND n.user_id = $user_id "
                "DETACH DELETE n",
                {
                    "repo_prefix": f"{full_name}::{branch}",
                    "tenant_repo_prefix": tenant_scoped_id(f"{full_name}::{branch}", user.user_id),
                    "user_id": user.user_id,
                },
            )
            message = f"Deleted {full_name} @ {branch}"
        else:
            neo4j.run_query(
                "MATCH (n) WHERE (n.repo = $repo OR n.full_name = $repo) "
                "AND n.user_id = $user_id DETACH DELETE n",
                {"repo": full_name, "user_id": user.user_id},
            )
            neo4j.run_query(
                "MATCH (s:Snapshot) WHERE s.repo = $repo AND s.user_id = $user_id DETACH DELETE s",
                {"repo": full_name, "user_id": user.user_id},
            )
            neo4j.run_query(
                "MATCH (n) WHERE (n.raw_id STARTS WITH $repo_prefix OR n.id STARTS WITH $tenant_repo_prefix) "
                "AND n.user_id = $user_id DETACH DELETE n",
                {
                    "repo_prefix": f"{full_name}::",
                    "tenant_repo_prefix": tenant_scoped_id(f"{full_name}::", user.user_id),
                    "user_id": user.user_id,
                },
            )
            neo4j.run_query(
                "MATCH (r:Repository) "
                "WHERE (r.full_name = $repo OR r.repo = $repo OR r.raw_id STARTS WITH $repo_prefix) "
                "AND r.user_id = $user_id DETACH DELETE r",
                {"repo": full_name, "repo_prefix": f"{full_name}::", "user_id": user.user_id},
            )
            neo4j.run_query(
                "MATCH (r:Repository {full_name: $repo, user_id: $user_id}) DETACH DELETE r",
                {"repo": full_name, "user_id": user.user_id},
            )
            message = f"Deleted all indexed branches for {full_name}"

        remaining_query = (
            "MATCH (n) WHERE n.user_id = $user_id "
            "AND (n.repo = $repo OR n.full_name = $repo "
            "OR n.raw_id STARTS WITH $repo_prefix OR n.id STARTS WITH $tenant_repo_prefix) "
        )
        remaining_params = {
            "repo": full_name,
            "branch": branch,
            "user_id": user.user_id,
            "repo_prefix": f"{full_name}::{branch}" if branch else f"{full_name}::",
            "tenant_repo_prefix": tenant_scoped_id(
                f"{full_name}::{branch}" if branch else f"{full_name}::",
                user.user_id,
            ),
        }
        if branch:
            remaining_query += "AND coalesce(n.branch, 'main') = $branch "
        remaining_query += "RETURN count(n) AS c"
        graph_remaining_rows = neo4j.run_query(remaining_query, remaining_params)
        graph_remaining = int(graph_remaining_rows[0]["c"]) if graph_remaining_rows else 0

        if vector_store is not None:
            try:
                qdrant_remaining = vector_store.count_by_repo(full_name, user_id=user.user_id, branch=branch)
            except Exception as exc:
                qdrant_delete_error = qdrant_delete_error or str(exc)
                qdrant_remaining = None

        status_value = "success" if graph_remaining == 0 and qdrant_remaining in (0, None) and not qdrant_delete_error else "partial"
        return {
            "status": status_value,
            "message": message,
            "graph_remaining": graph_remaining,
            "qdrant_remaining": qdrant_remaining,
            "qdrant_delete_error": qdrant_delete_error,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> QueryResponse:
    """Direct RAG query, scoped to the user's accessible repos."""
    check_daily_query_quota(user.user_id)
    pipeline = RAGPipeline()
    try:
        result = await pipeline.query(
            user_query=request.query,
            repo=request.repo,
            branch=request.branch,
            language=request.language,
            top_k=request.top_k,
            history=request.history,
            user_id=user.user_id,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent_query", response_model=QueryResponse)
async def agent_query(
    request: QueryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> QueryResponse:
    """Auto-routed query with visible retrieval/tool trace."""
    check_daily_query_quota(user.user_id)
    route = _route_query_intent(request.query)
    try:
        graph_intent = _graph_tool_intent(request.query)
        if graph_intent:
            tool_name, target = graph_intent
            set_agent_user_context(user.user_id, request.branch)
            if tool_name == "get_call_graph":
                tool_output = get_call_graph.invoke({"function_name": target, "repo": request.repo})
            else:
                tool_output = get_dependencies.invoke({"module_name": target, "repo": request.repo})

            graph_trace = RetrievalTraceStep(
                step=1,
                kind="graph",
                tool=tool_name,
                input={"target": target, "repo": request.repo, "branch": request.branch},
                summary=_summarize_tool_result(str(tool_output)),
            )

            if _tool_output_has_no_data(str(tool_output)):
                rag = RAGPipeline()
                result = await rag.query(
                    user_query=request.query,
                    repo=request.repo,
                    branch=request.branch,
                    language=request.language,
                    top_k=request.top_k,
                    history=request.history,
                    user_id=user.user_id,
                )
                result.fallback_used = True
                result.retrieval_mode = "semantic_fallback"
                result.trace = [
                    graph_trace,
                    *[
                        RetrievalTraceStep(
                            step=item.step + 1,
                            kind=item.kind,
                            tool=item.tool,
                            input=item.input,
                            summary=item.summary,
                        )
                        for item in result.trace
                    ],
                ]
                return result

            rag = RAGPipeline()
            result = await rag.query(
                user_query=request.query,
                repo=request.repo,
                branch=request.branch,
                language=request.language,
                top_k=request.top_k,
                history=request.history,
                user_id=user.user_id,
            )
            result.retrieval_mode = "hybrid"
            result.fallback_used = False
            result.trace = [
                graph_trace,
                *[
                    RetrievalTraceStep(
                        step=item.step + 1,
                        kind=item.kind,
                        tool=item.tool,
                        input=item.input,
                        summary=item.summary,
                    )
                    for item in result.trace
                ],
            ]
            return result

        if route == "semantic":
            rag = RAGPipeline()
            result = await rag.query(
                user_query=request.query,
                repo=request.repo,
                branch=request.branch,
                language=request.language,
                top_k=request.top_k,
                history=request.history,
                user_id=user.user_id,
            )
            result.retrieval_mode = "semantic"
            return result

        messages = await run_agent(
            query=request.query,
            repo=request.repo,
            branch=request.branch,
            history=request.history,
            user_id=user.user_id,
        )
        final_answer = messages[-1].content if messages else "No response generated."
        trace = _extract_trace(messages)
        if not trace:
            trace = [
                RetrievalTraceStep(
                    step=1,
                    kind="agent",
                    tool="agent_reasoning",
                    input={"query": request.query, "repo": request.repo, "branch": request.branch},
                    summary="Agent produced an answer without a recorded tool call",
                )
            ]
        if not str(final_answer or "").strip() or any(step.tool == "ask_human_for_clarification" for step in trace):
            final_answer = _answer_from_trace(
                [step for step in trace if step.tool != "ask_human_for_clarification"]
            )
        return QueryResponse(
            answer=final_answer,
            sources=[],
            trace=trace,
            retrieval_mode=route,
            fallback_used=False,
        )
    except Exception as e:
        try:
            rag = RAGPipeline()
            result = await rag.query(
                user_query=request.query,
                repo=request.repo,
                branch=request.branch,
                language=request.language,
                top_k=request.top_k,
                history=request.history,
                user_id=user.user_id,
            )
            result.fallback_used = True
            result.retrieval_mode = "semantic_fallback"
            result.trace = [
                RetrievalTraceStep(
                    step=1,
                    kind="fallback",
                    tool="agent_query",
                    input={"route": route},
                    summary=f"Agent route failed, used direct RAG fallback: {str(e)[:160]}",
                ),
                *[
                    RetrievalTraceStep(
                        step=item.step + 1,
                        kind=item.kind,
                        tool=item.tool,
                        input=item.input,
                        summary=item.summary,
                    )
                    for item in result.trace
                ],
            ]
            return result
        except Exception as fallback_error:
            raise HTTPException(
                status_code=500,
                detail=f"Agent query failed: {e} | RAG fallback failed: {fallback_error}",
            )


@router.get("/graph/stats", response_model=GraphStatsResponse)
async def graph_stats(
    user: AuthenticatedUser = Depends(get_current_user),
) -> GraphStatsResponse:
    """Graph statistics scoped to user's repos."""
    try:
        neo4j = Neo4jManager()
        # Only count nodes belonging to this user or public repos
        node_records = neo4j.run_query(
            "MATCH (n) WHERE n.user_id = $user_id OR n.is_public = true "
            "RETURN labels(n)[0] AS label, count(n) AS count",
            {"user_id": user.user_id},
        )
        nodes_dict = {r["label"]: r["count"] for r in node_records if r["label"]}

        rel_records = neo4j.run_query(
            "MATCH (a)-[r]->(b) "
            "WHERE (a.user_id = $user_id OR a.is_public = true) "
            "AND (b.user_id = $user_id OR b.is_public = true) "
            "RETURN type(r) AS type, count(r) AS count",
            {"user_id": user.user_id},
        )
        rels_dict = {r["type"]: r["count"] for r in rel_records if r["type"]}

        return GraphStatsResponse(nodes=nodes_dict, relationships=rels_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/global")
async def global_stats(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, int]:
    """Global Brain metrics row: chunks, graph nodes, repos, relationships."""
    try:
        neo4j = Neo4jManager()

        repo_row = neo4j.run_query(
            "MATCH (r:Repository) "
            "WHERE r.user_id = $user_id OR r.is_public = true "
            "RETURN count(r) AS c",
            {"user_id": user.user_id},
        )
        repos = int(repo_row[0]["c"]) if repo_row else 0

        node_row = neo4j.run_query(
            "MATCH (n) "
            "WHERE n.user_id = $user_id OR n.is_public = true "
            "RETURN count(n) AS c",
            {"user_id": user.user_id},
        )
        nodes = int(node_row[0]["c"]) if node_row else 0

        rel_row = neo4j.run_query(
            "MATCH (a)-[r]->(b) "
            "WHERE (a.user_id = $user_id OR a.is_public = true) "
            "AND (b.user_id = $user_id OR b.is_public = true) "
            "RETURN count(r) AS c",
            {"user_id": user.user_id},
        )
        relationships = int(rel_row[0]["c"]) if rel_row else 0

        chunks = 0
        if settings.qdrant_url and settings.qdrant_api_key:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels
            from qdrant_client.http.exceptions import UnexpectedResponse

            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
            qdrant_filter = qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="user_id",
                        match=qmodels.MatchValue(value=user.user_id),
                    ),
                    qmodels.FieldCondition(
                        key="is_public",
                        match=qmodels.MatchValue(value=True),
                    ),
                ],
            )
            try:
                count_response = client.count(
                    collection_name=settings.qdrant_collection,
                    count_filter=qdrant_filter,
                    exact=False,
                )
                chunks = int(count_response.count)
            except UnexpectedResponse:
                chunks = 0

        return {
            "chunks": chunks,
            "nodes": nodes,
            "repos": repos,
            "relationships": relationships,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/explore", response_model=GraphExploreResponse)
async def graph_explore(
    repo: str,  # Phase 8.4: Required parameter for single-repo visual constraint
    branch: str | None = None,
    center: str | None = None,
    depth: int = 2,
    user: AuthenticatedUser = Depends(get_current_user),
) -> GraphExploreResponse:
    """
    Explore graph neighborhood. Requires a repo parameter (single-repo visual constraint).
    Only returns data the user has access to.
    """
    try:
        neo4j = Neo4jManager()
        from models.schemas import GraphNode, GraphLink

        # Verify user has access to this repo
        access_check = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE (r.user_id = $user_id OR r.is_public = true) "
            "AND ($branch IS NULL OR coalesce(r.branch, r.default_branch, 'main') = $branch) "
            "RETURN r.full_name AS name",
            {"repo": repo, "branch": branch, "user_id": user.user_id},
        )
        if not access_check:
            raise HTTPException(status_code=403, detail="You don't have access to this repository")

        query = """
        MATCH (n)-[r]->(m)
        WHERE (n.repo = $repo OR n.full_name = $repo)
          AND (m.repo = $repo OR m.full_name = $repo)
          AND (n.user_id = $user_id OR n.is_public = true)
          AND (m.user_id = $user_id OR m.is_public = true)
          AND ($branch IS NULL OR coalesce(n.branch, 'main') = $branch)
          AND ($branch IS NULL OR coalesce(m.branch, 'main') = $branch)
          AND (
            $center IS NULL OR $center = ''
            OR toLower(coalesce(n.name, n.path, n.id, '')) CONTAINS toLower($center)
            OR toLower(coalesce(m.name, m.path, m.id, '')) CONTAINS toLower($center)
          )
        RETURN n, r, m
        LIMIT 300
        """

        records = neo4j.run_query(
            query,
            {
                "center": center or "",
                "repo": repo,
                "branch": branch,
                "user_id": user.user_id,
            },
        )

        nodes_map = {}
        links = []

        for record in records:
            n = record["n"]
            m = record["m"]
            r = record["r"]

            n_id = n.get("id")
            m_id = m.get("id")

            n_label = list(n.labels)[0] if n.labels else "Unknown"
            m_label = list(m.labels)[0] if m.labels else "Unknown"

            if n_id not in nodes_map:
                nodes_map[n_id] = GraphNode(
                    id=n_id,
                    label=n_label,
                    type=n_label,
                    properties=_json_safe_graph_properties(dict(n)),
                )
            if m_id not in nodes_map:
                nodes_map[m_id] = GraphNode(
                    id=m_id,
                    label=m_label,
                    type=m_label,
                    properties=_json_safe_graph_properties(dict(m)),
                )

            links.append(
                GraphLink(
                    source=n_id,
                    target=m_id,
                    type=r.type,
                    properties=_json_safe_graph_properties(dict(r)),
                )
            )

        return GraphExploreResponse(nodes=list(nodes_map.values()), links=links)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/repos/{owner}/{repo_name}/snapshot", response_model=SnapshotResponse)
async def get_repo_snapshot(
    owner: str,
    repo_name: str,
    branch: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
) -> SnapshotResponse:
    """Retrieve the pre-computed architectural snapshot from Neo4j."""
    full_name = f"{owner}/{repo_name}"
    try:
        neo4j = Neo4jManager()
        branch_name = branch or "main"
        snapshot_id = tenant_scoped_id(f"{full_name}::{branch_name}::snapshot", user.user_id)
        
        # Verify access
        access_check = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE (r.user_id = $user_id OR r.is_public = true) "
            "AND ($branch IS NULL OR coalesce(r.branch, r.default_branch, 'main') = $branch) "
            "OPTIONAL MATCH (s:Snapshot {id: $snapshot_id}) "
            "RETURN coalesce(s.snapshot, r.snapshot) AS snapshot, "
            "r.commit_sha AS commit_sha",
            {
                "repo": full_name,
                "branch": branch,
                "user_id": user.user_id,
                "snapshot_id": snapshot_id,
            },
        )
        
        if not access_check:
            raise HTTPException(status_code=403, detail="Repository not found or access denied")
            
        commit_sha = access_check[0].get("commit_sha")
        cache_key = snapshot_cache_key(user.user_id, full_name, branch_name, commit_sha)
        cached_snapshot = cache_get_json(cache_key)
        if cached_snapshot and cached_snapshot.get("snapshot"):
            return SnapshotResponse(repo=full_name, snapshot=str(cached_snapshot["snapshot"]))

        snapshot = access_check[0].get("snapshot")
        if not snapshot:
            return SnapshotResponse(repo=full_name, snapshot="Snapshot not available yet. Please allow a few minutes after ingestion.")

        cache_set_json(
            cache_key,
            {"repo": full_name, "snapshot": snapshot},
            settings.report_cache_ttl_seconds,
        )
        return SnapshotResponse(repo=full_name, snapshot=snapshot)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_repo_health_check(
    owner: str,
    repo_name: str,
    branch: str | None,
    user: AuthenticatedUser = Depends(get_current_user),
) -> HealthCheckResponse:
    """Generate an evidence-led repository health check, not a definitive audit."""
    full_name = f"{owner}/{repo_name}"
    branch_name = branch or "main"

    try:
        neo4j = Neo4jManager()
        repo_rows = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE (r.user_id = $user_id OR r.is_public = true) "
            "AND coalesce(r.branch, r.default_branch, 'main') = $branch "
            "RETURN r.commit_sha AS commit_sha, r.ingestion_status AS status, "
            "r.last_ingest_at AS last_ingest_at",
            {"repo": full_name, "branch": branch_name, "user_id": user.user_id},
        )
        if not repo_rows:
            raise HTTPException(status_code=404, detail="Indexed branch not found")

        repo_record = repo_rows[0]
        commit_sha = repo_record.get("commit_sha")
        cached_health = cache_get_json(health_cache_key(user.user_id, full_name, branch_name, commit_sha))
        if cached_health:
            cached_signals = cached_health.get("signals") or {}
            cached_signals["cache"] = "redis"
            return HealthCheckResponse(
                repo=full_name,
                branch=branch_name,
                report=str(cached_health.get("report") or ""),
                signals=cached_signals,
            )
        check_daily_health_quota(user.user_id, full_name, branch_name, commit_sha)

        node_rows = neo4j.run_query(
            "MATCH (n) WHERE (n.repo = $repo OR n.full_name = $repo) "
            "AND (n.user_id = $user_id OR n.is_public = true) "
            "AND coalesce(n.branch, 'main') = $branch "
            "RETURN labels(n)[0] AS label, count(n) AS count",
            {"repo": full_name, "branch": branch_name, "user_id": user.user_id},
        )
        rel_rows = neo4j.run_query(
            "MATCH (a)-[r]->(b) "
            "WHERE (a.repo = $repo OR a.full_name = $repo) "
            "AND (b.repo = $repo OR b.full_name = $repo) "
            "AND (a.user_id = $user_id OR a.is_public = true) "
            "AND (b.user_id = $user_id OR b.is_public = true) "
            "AND coalesce(a.branch, 'main') = $branch "
            "AND coalesce(b.branch, 'main') = $branch "
            "RETURN type(r) AS type, count(r) AS count",
            {"repo": full_name, "branch": branch_name, "user_id": user.user_id},
        )

        embedder = CortexEmbedder()
        vector_store = VectorStore()
        vector_store.ensure_collection()
        evidence_queries = [
            "authentication authorization middleware csrf jwt password token secret api key",
            "dependency package requirements package.json pyproject security config",
            "test coverage unit tests integration tests pytest jest",
            "todo fixme hack temporary risky deprecated",
            "database query sql raw execute eval subprocess shell command",
            "error handling logging retry timeout validation exception handling",
            "deployment docker ci cd environment configuration production",
        ]
        evidence = []
        secret_signal_count = 0
        for query_text in evidence_queries:
            dense_vectors = await embedder.embed_batch([query_text])
            hits = vector_store.search(
                query_dense=dense_vectors[0],
                query_sparse=embedder.generate_sparse_vector(query_text),
                filters={"repo": full_name, "branch": branch_name},
                top_k=4,
                user_id=user.user_id,
            )
            for hit in hits[:3]:
                payload = hit.get("payload", {})
                text = payload.get("text", "")
                if payload.get("security_censored") or "[REDACTED]" in text:
                    secret_signal_count += 1
                evidence.append(
                    {
                        "query": query_text,
                        "file_path": payload.get("file_path"),
                        "line_range": (
                            f"{payload.get('start_line')}-{payload.get('end_line')}"
                            if payload.get("start_line") and payload.get("end_line")
                            else None
                        ),
                        "source_type": payload.get("source_type"),
                        "language": payload.get("language"),
                        "score": hit.get("score"),
                        "excerpt": text[:900],
                    }
                )

        signals = {
            "repo": full_name,
            "branch": branch_name,
            "commit_sha": commit_sha,
            "ingestion_status": repo_record.get("status"),
            "node_counts": {row["label"]: row["count"] for row in node_rows if row.get("label")},
            "relationship_counts": {row["type"]: row["count"] for row in rel_rows if row.get("type")},
            "secret_redaction_evidence_count": secret_signal_count,
            "evidence_count": len(evidence),
            "cache": "disabled",
        }

        health_prompt = (
            "Generate an evidence-led Repository Health Check for this indexed branch.\n"
            "This is a deeper engineering review, not a repo overview. Do not summarize the README "
            "or repeat the architecture snapshot except where graph/evidence signals support a review point.\n"
            "This is NOT a definitive security audit and must not claim complete vulnerability coverage.\n"
            "Use only the deterministic signals and evidence excerpts below.\n\n"
            "Required Markdown sections:\n"
            "1. Overall Summary\n"
            "2. What Looks Present And Healthy\n"
            "3. Architecture And Coupling Review\n"
            "4. Security-Sensitive Areas To Review\n"
            "5. Secret Exposure Signals\n"
            "6. Dependency And Configuration Surface\n"
            "7. Testing, Error Handling, And Maintainability Signals\n"
            "8. Recommended Next Actions\n"
            "9. Evidence Reviewed\n\n"
            "Tag findings as [Evidence-backed], [Heuristic], or [Needs manual review]. "
            "Use careful language such as 'potential risk area' or 'worth manual review'. "
            "Include positive existing signals when evidence shows them, but do not turn this into marketing copy. "
            "Do not say the repository is secure, fully audited, or definitely vulnerable unless the evidence directly proves it.\n\n"
            f"Signals:\n{json.dumps(signals, default=str, indent=2)}\n\n"
            f"Evidence excerpts:\n{json.dumps(evidence[:21], default=str, indent=2)}"
        )

        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=health_prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are Cortex's repository health-check reporter. "
                    "Synthesize a careful, evidence-led engineering review from the provided signals only. "
                    "Focus on existing engineering signals, risks, gaps, and manual review priorities. "
                    "Do not call tools. Do not rely on README-style claims. Do not claim complete security coverage."
                ),
                temperature=0.2,
            ),
        )
        final_answer = response.text or "No report generated."
        signals["cache"] = "miss"
        cache_set_json(
            health_cache_key(user.user_id, full_name, branch_name, commit_sha),
            {
                "repo": full_name,
                "branch": branch_name,
                "report": final_answer,
                "signals": signals,
            },
            settings.report_cache_ttl_seconds,
        )
        neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE (r.user_id = $user_id OR r.is_public = true) "
            "AND coalesce(r.branch, r.default_branch, 'main') = $branch "
            "REMOVE r.health_report, r.health_report_commit_sha, r.health_checked_at",
            {
                "repo": full_name,
                "branch": branch_name,
                "user_id": user.user_id,
            },
        )
        return HealthCheckResponse(repo=full_name, branch=branch_name, report=final_answer, signals=signals)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repos/{owner}/{repo_name}/health-check", response_model=HealthCheckResponse)
async def run_repo_health_check(
    owner: str,
    repo_name: str,
    branch: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
) -> HealthCheckResponse:
    return await _run_repo_health_check(owner, repo_name, branch, user)


@router.post("/repos/{owner}/{repo_name}/audit", response_model=AuditResponse)
async def run_security_audit(
    owner: str,
    repo_name: str,
    branch: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuditResponse:
    """Backward-compatible alias for the older audit route."""
    result = await _run_repo_health_check(owner, repo_name, branch, user)
    return AuditResponse(repo=result.repo, report=result.report)
