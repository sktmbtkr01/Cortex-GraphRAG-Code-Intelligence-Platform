from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Internal pipeline data classes (not API-facing)
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A single chunk produced by a chunker, ready for embedding + Qdrant upsert.

    Content-aware chunking strategy:
      - Code  → AST chunker (function/class-level, tree-sitter)
      - Docs  → Section chunker (split at markdown headers)
      - Issues/PRs → Whole-document (one chunk per item, they're short)
      - Configs → Whole-document (one chunk per file)
    """

    id: str
    text: str
    repo: str
    file_path: str
    language: str
    source_type: str  # "code" | "docs" | "issue" | "pr" | "config"
    chunk_type: str  # "function" | "class" | "method" | "module_header" | "section" | "whole_doc"

    # Code-specific (None for non-code)
    function_name: str | None = None
    class_name: str | None = None
    signature: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    # Doc-specific (None for non-docs)
    section_title: str | None = None

    # Issue / PR specific
    issue_number: int | None = None
    pr_number: int | None = None
    state: str | None = None
    labels: list[str] = field(default_factory=list)

    # Multi-tenant isolation (Phase 8)
    user_id: str | None = None
    is_public: bool = False

    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# API-facing Pydantic models
# ---------------------------------------------------------------------------


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

# ── Phase 8.5: Summarization & Auditing ───────────────────────────────────

class SnapshotResponse(BaseModel):
    repo: str
    snapshot: str

class AuditResponse(BaseModel):
    repo: str
    report: str
