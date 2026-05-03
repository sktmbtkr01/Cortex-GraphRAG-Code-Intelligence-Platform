import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from core.auth import AuthenticatedUser, get_current_user
from core.config import settings
from models.schemas import (
    GraphExploreResponse,
    GraphStatsResponse,
    IngestRequest,
    IngestJobResponse,
    QueryRequest,
    QueryResponse,
    RepoStatus,
    SnapshotResponse,
    AuditResponse,
)

router = APIRouter()


from indexing.qdrant_store import VectorStore
from indexing.graph_builder.neo4j_manager import Neo4jManager
from retrieval.rag_pipeline import RAGPipeline
from agents.supervisor import run_agent
from ingestion.pipeline import IngestionPipeline
from ingestion.github_client import GitHubClient
from agents.summarizer import generate_repo_snapshot
from core.job_store import job_store
from core.tenant import tenant_scoped_id


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


def _json_safe_graph_properties(properties: dict) -> dict:
    return {key: _json_safe_graph_value(value) for key, value in properties.items()}


async def _run_ingest_job(
    job_id: str,
    request: IngestRequest,
    user: AuthenticatedUser,
) -> None:
    async def emit_progress(stage: str, message: str, meta: dict | None = None) -> None:
        await job_store.publish(
            job_id,
            {
                "type": "progress",
                "state": "running",
                "stage": stage,
                "message": message,
                "meta": meta or {},
            },
        )

    try:
        await emit_progress("starting", f"Starting ingest for {request.repo}")

        owner, repo_name = request.repo.split("/")

        await emit_progress("fetching_tree", "Checking repository metadata")
        async with GitHubClient(token=user.github_token) as client:
            metadata = await client.fetch_repo_metadata(owner, repo_name)
        repo_size_kb = metadata.get("size", 0)
        repo_size_mb = repo_size_kb / 1024
        if repo_size_mb > settings.max_repo_size_mb:
            raise ValueError(
                f"Repository {request.repo} is too large ({repo_size_mb:.0f} MB). "
                f"Maximum allowed is {settings.max_repo_size_mb} MB."
            )

        default_branch = metadata.get("default_branch") or "main"
        neo4j = None
        try:
            neo4j = Neo4jManager()
            neo4j.merge_tenant_node(
                "Repository",
                request.repo,
                {
                    "full_name": request.repo,
                    "owner": owner,
                    "name": repo_name,
                    "default_branch": default_branch,
                    "is_private": bool(metadata.get("private", True)),
                    "ingestion_status": "processing",
                },
                user.user_id,
                metadata.get("private", True) is False,
            )
        except Exception:
            neo4j = None

        pipeline = IngestionPipeline(github_token=user.github_token)
        stats = await pipeline.ingest_repo(
            repo=request.repo,
            branch=default_branch,
            include_issues=False,
            include_prs=False,
            include_commits=False,
            max_commits=0,
            user_id=user.user_id,
            is_public=metadata.get("private", True) is False,
            progress_cb=emit_progress,
        )

        await emit_progress("snapshot", "Generating architectural snapshot")
        snapshot = await generate_repo_snapshot(request.repo, user.user_id)

        if neo4j is not None:
            neo4j.run_query(
                "MATCH (r:Repository {id: $repo}) SET r.ingestion_status = 'ready', r.last_ingest_at = datetime()",
                {"repo": tenant_scoped_id(request.repo, user.user_id, metadata.get("private", True) is False)},
            )

        await job_store.publish(
            job_id,
            {
                "type": "done",
                "state": "done",
                "stage": "done",
                "repo": request.repo,
                "message": "Ingestion complete",
                "stats": stats,
                "snapshot": snapshot,
            },
        )
    except Exception as e:
        try:
            neo4j = Neo4jManager()
            neo4j.run_query(
                "MATCH (r:Repository {id: $repo}) SET r.ingestion_status = 'failed', r.last_ingest_error = $error",
                {"repo": tenant_scoped_id(request.repo, user.user_id), "error": str(e)},
            )
        except Exception:
            pass

        await job_store.publish(
            job_id,
            {
                "type": "error",
                "state": "error",
                "stage": "error",
                "repo": request.repo,
                "message": str(e),
            },
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

    job_id = job_store.create_job(user_id=user.user_id, repo=request.repo)
    asyncio.create_task(_run_ingest_job(job_id=job_id, request=request, user=user))

    return IngestJobResponse(
        job_id=job_id,
        status="accepted",
        repo=request.repo,
        message="Ingestion started in background",
    )


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
            "RETURN r.full_name AS repo, r.is_private AS is_private, "
            "coalesce(r.ingestion_status, 'ready') AS ingestion_status, r.user_id AS owner_id",
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
                    is_private=is_priv,
                    ingestion_status=str(r.get("ingestion_status") or "ready"),
                )
            )
        return repos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/my-repos")
async def list_my_github_repos(
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    """List repositories from the authenticated user's GitHub account."""
    try:
        async with GitHubClient(token=user.github_token) as github:
            if user.github_token:
                repos = await github.list_user_repos(max_repos=200)
                warning = None
            elif user.provider == "github" and user.login:
                repos = await github.list_public_repos_for_user(user.login, max_repos=200)
                warning = "OAuth session expired on server. Showing public repositories only; sign in again to restore private repos."
            else:
                return []

        return [
            {
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "private": bool(r.get("private", False)),
                "language": r.get("language"),
                "stars": int(r.get("stargazers_count", 0) or 0),
                "default_branch": r.get("default_branch") or "main",
                "warning": warning,
            }
            for r in repos
            if r.get("full_name")
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/repos/{owner}/{repo_name}")
async def delete_repo(
    owner: str,
    repo_name: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a repository. Only the owner can delete their own repos."""
    full_name = f"{owner}/{repo_name}"
    try:
        # Verify ownership before deletion
        neo4j = Neo4jManager()
        ownership = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE r.user_id = $user_id "
            "RETURN r.user_id AS uid",
            {"repo": full_name, "user_id": user.user_id},
        )
        if not ownership:
            raise HTTPException(status_code=403, detail="You can only delete your own repositories")

        try:
            VectorStore().delete_by_repo(full_name, user_id=user.user_id)
        except Exception:
            # Interrupted ingests can leave Neo4j repo/status nodes before any
            # Qdrant collection or points exist. Deletion should still clear graph state.
            pass

        # Delete nodes that have this repo + user_id
        neo4j.run_query(
            "MATCH (n) WHERE n.repo = $repo AND n.user_id = $user_id DETACH DELETE n",
            {"repo": full_name, "user_id": user.user_id},
        )
        neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo, user_id: $user_id}) DETACH DELETE r",
            {"repo": full_name, "user_id": user.user_id},
        )
        return {"status": "success", "message": f"Deleted {full_name}"}
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
    pipeline = RAGPipeline()
    try:
        result = await pipeline.query(
            user_query=request.query,
            repo=request.repo,
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
    """Agent-powered query, scoped to user's accessible repos."""
    try:
        messages = await run_agent(
            query=request.query,
            repo=request.repo,
            history=request.history,
            user_id=user.user_id,
        )
        final_answer = messages[-1].content if messages else "No response generated."
        return QueryResponse(answer=final_answer, sources=[])
    except Exception as e:
        try:
            rag = RAGPipeline()
            result = await rag.query(
                user_query=request.query,
                repo=request.repo,
                language=request.language,
                top_k=request.top_k,
                history=request.history,
                user_id=user.user_id,
            )
            return QueryResponse(answer=result.answer, sources=result.sources)
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
            "WHERE r.user_id = $user_id OR r.is_public = true "
            "RETURN r.full_name AS name",
            {"repo": repo, "user_id": user.user_id},
        )
        if not access_check:
            raise HTTPException(status_code=403, detail="You don't have access to this repository")

        query = """
        MATCH (n)-[r]->(m)
        WHERE (n.repo = $repo OR n.full_name = $repo)
          AND (m.repo = $repo OR m.full_name = $repo)
          AND (n.user_id = $user_id OR n.is_public = true)
          AND (m.user_id = $user_id OR m.is_public = true)
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
    user: AuthenticatedUser = Depends(get_current_user),
) -> SnapshotResponse:
    """Retrieve the pre-computed architectural snapshot from Neo4j."""
    full_name = f"{owner}/{repo_name}"
    try:
        neo4j = Neo4jManager()
        
        # Verify access
        access_check = neo4j.run_query(
            "MATCH (r:Repository {full_name: $repo}) "
            "WHERE r.user_id = $user_id OR r.is_public = true "
            "RETURN r.snapshot AS snapshot",
            {"repo": full_name, "user_id": user.user_id},
        )
        
        if not access_check:
            raise HTTPException(status_code=403, detail="Repository not found or access denied")
            
        snapshot = access_check[0].get("snapshot")
        if not snapshot:
            return SnapshotResponse(repo=full_name, snapshot="Snapshot not available yet. Please allow a few minutes after ingestion.")
            
        return SnapshotResponse(repo=full_name, snapshot=snapshot)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/repos/{owner}/{repo_name}/audit", response_model=AuditResponse)
async def run_security_audit(
    owner: str,
    repo_name: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuditResponse:
    """Run an on-demand deep security and architectural audit via the agent."""
    full_name = f"{owner}/{repo_name}"
    
    # Run the standard agent but with a highly specific security prompt
    audit_prompt = (
        "Perform a comprehensive security and vulnerability audit of this repository. "
        "Analyze the code structure for common flaws (SQL injection, XSS, insecure direct object references, CSRF, etc.), "
        "improper secrets management (even if some were skipped, check auth logic), "
        "and architectural single points of failure. Detail any risky dependencies or exposed endpoints. "
        "Return a well-structured markdown report with actionable findings categorized by risk level."
    )
    
    try:
        messages = await run_agent(
            query=audit_prompt,
            repo=full_name,
            history=[],
            user_id=user.user_id,
        )
        final_answer = messages[-1].content if messages else "No report generated."
        return AuditResponse(repo=full_name, report=final_answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
