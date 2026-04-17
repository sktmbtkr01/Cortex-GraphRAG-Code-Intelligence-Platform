from fastapi import APIRouter, HTTPException, status

from models.schemas import (
    GraphExploreResponse,
    GraphStatsResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    RepoStatus,
)

router = APIRouter()


def not_implemented(feature: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{feature} is planned for a later phase.",
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest_repo(request: IngestRequest) -> IngestResponse:
    not_implemented("Repository ingestion")


@router.get("/repos", response_model=list[RepoStatus])
async def list_repos() -> list[RepoStatus]:
    not_implemented("Repository listing")


@router.delete("/repos/{owner}/{repo_name}")
async def delete_repo(owner: str, repo_name: str) -> dict[str, str]:
    not_implemented(f"Repository deletion for {owner}/{repo_name}")


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    not_implemented("Direct RAG query")


@router.post("/agent_query", response_model=QueryResponse)
async def agent_query(request: QueryRequest) -> QueryResponse:
    not_implemented("Agent query")


@router.get("/graph/stats", response_model=GraphStatsResponse)
async def graph_stats() -> GraphStatsResponse:
    not_implemented("Graph statistics")


@router.get("/graph/explore", response_model=GraphExploreResponse)
async def graph_explore(
    repo: str | None = None,
    center: str | None = None,
    depth: int = 2,
) -> GraphExploreResponse:
    not_implemented("Interactive graph exploration")
