from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import AuthenticatedUser, get_current_user
from core.config import settings
from models.schemas import (
    GraphExploreResponse,
    GraphStatsResponse,
    IngestRequest,
    IngestResponse,
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


@router.post("/ingest", response_model=IngestResponse)
async def ingest_repo(
    request: IngestRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> IngestResponse:
    """Ingest a repository. Requires authentication. Tags all data with user_id."""
    # ── Phase 8.2: Repo size ceiling ──────────────────────────────────
    from ingestion.github_client import GitHubClient

    client = GitHubClient(token=user.github_token)
    try:
        owner, repo_name = request.repo.split("/")
    except ValueError:
        raise HTTPException(status_code=400, detail="Repo must be 'owner/repo' format")

    try:
        metadata = await client.fetch_repo_metadata(owner, repo_name)
        repo_size_kb = metadata.get("size", 0)  # GitHub returns size in KB
        repo_size_mb = repo_size_kb / 1024
        if repo_size_mb > settings.max_repo_size_mb:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Repository {request.repo} is too large ({repo_size_mb:.0f} MB). "
                    f"Maximum allowed is {settings.max_repo_size_mb} MB. "
                    f"This limit protects API costs and server stability."
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        # If we can't check size, log warning and proceed
        pass

    pipeline = IngestionPipeline(github_token=user.github_token)
    try:
        stats = await pipeline.ingest_repo(
            repo=request.repo,
            branch=request.branch,
            include_issues=request.include_issues,
            include_prs=request.include_prs,
            include_commits=request.include_commits,
            user_id=user.user_id,
            is_public=metadata.get("private", True) is False if 'metadata' in dir() else False,
        )
        # Phase 8.5: Auto-generate snapshot in background
        from agents.summarizer import generate_repo_snapshot
        import asyncio
        asyncio.create_task(generate_repo_snapshot(request.repo, user.user_id))

        msg = f"Parsed {stats['files_parsed']} items. Skipped {stats['files_skipped']} files. Skipped {stats['secrets_found']} secrets. Auto-generating architectural snapshot..."
        return IngestResponse(status="success", repo=request.repo, message=msg)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
            "WHERE r.user_id = $user_id OR r.is_public = true "
            "RETURN r.full_name AS repo, r.is_private AS is_private, r.user_id AS owner_id",
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
            repos.append(RepoStatus(repo=repo_name, is_private=is_priv))
        return repos
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
            "MATCH (r:Repository {full_name: $repo}) RETURN r.user_id AS uid",
            {"repo": full_name},
        )
        if ownership and ownership[0].get("uid") != user.user_id:
            raise HTTPException(status_code=403, detail="You can only delete your own repositories")

        VectorStore().delete_by_repo(full_name, user_id=user.user_id)
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
        raise HTTPException(status_code=500, detail=str(e))


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
            "WHERE a.user_id = $user_id OR a.is_public = true "
            "RETURN type(r) AS type, count(r) AS count",
            {"user_id": user.user_id},
        )
        rels_dict = {r["type"]: r["count"] for r in rel_records if r["type"]}

        return GraphStatsResponse(nodes=nodes_dict, relationships=rels_dict)
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

        query = ""
        if center:
            query = f"MATCH (center) WHERE (center.name CONTAINS $center OR center.id CONTAINS $center) AND (center.repo = $repo OR center.full_name = $repo) WITH center LIMIT 1 MATCH (center)-[*1..{depth}]-(n)-[r]->(m) "
        else:
            query = "MATCH (n)-[r]->(m) "

        # Always enforce repo scope for visualization
        query += " WHERE (n.repo = $repo OR n.full_name = $repo) AND (m.repo = $repo OR m.full_name = $repo) "
        query += " RETURN n, r, m LIMIT 300"

        records = neo4j.run_query(query, {"center": center, "repo": repo})

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
                nodes_map[n_id] = GraphNode(id=n_id, label=n_label, type=n_label, properties=dict(n))
            if m_id not in nodes_map:
                nodes_map[m_id] = GraphNode(id=m_id, label=m_label, type=m_label, properties=dict(m))

            links.append(GraphLink(source=n_id, target=m_id, type=r.type, properties=dict(r)))

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

