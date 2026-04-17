from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class IngestRequest(BaseModel):
    repo: str = Field(..., examples=["owner/repo-name"])
    branch: str = "main"
    include_issues: bool = True
    include_prs: bool = True
    include_commits: bool = True
    max_commits: int = 500


class IngestResponse(BaseModel):
    status: str
    repo: str
    message: str


class QueryRequest(BaseModel):
    query: str
    repo: str | None = None
    language: str | None = None
    top_k: int = 7
    history: list[HistoryMessage] | None = None


class SourceChunk(BaseModel):
    text: str
    source: str
    file_path: str
    language: str | None = None
    function_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    score: float | None = None
    source_type: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk] = []


class RepoStatus(BaseModel):
    repo: str
    is_private: bool = False
    file_count: int = 0
    chunk_count: int = 0
    last_indexed: datetime | None = None
    languages: list[str] = []
    webhook_active: bool = False


class GraphStatsResponse(BaseModel):
    nodes: dict[str, int] = {}
    relationships: dict[str, int] = {}


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    properties: dict = {}


class GraphLink(BaseModel):
    source: str
    target: str
    type: str
    properties: dict = {}


class GraphExploreResponse(BaseModel):
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
