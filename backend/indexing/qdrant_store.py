"""
Cortex Vector Store — Manages Qdrant Cloud connectivity and schema.
"""

import datetime
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from core.config import settings
from core.logger import get_logger
from core.tenant import tenant_prefix
from models.schemas import Chunk

logger = get_logger(__name__)


def generate_chunk_id(chunk: Chunk) -> str:
    """
    Generate a deterministic UUID for a chunk based on its unique identity.
    This ensures we OVERWRITE exactly the same chunk on re-indexing, rather than duplicating.
    """
    import hashlib
    import uuid

    # Base identity includes tenant ownership to prevent same-repo overwrites
    # between users while preserving deterministic re-indexing for one user.
    identity_str = (
        f"{tenant_prefix(chunk.user_id, chunk.is_public)}::"
        f"{chunk.repo}::{chunk.branch}::{chunk.file_path}::{chunk.chunk_type}"
    )

    # Add specific discriminators
    if chunk.function_name:
        identity_str += f"::{chunk.function_name}"
    if chunk.class_name:
        identity_str += f"::{chunk.class_name}"
    if chunk.section_title:
        identity_str += f"::{chunk.section_title}"
    if chunk.start_line is not None:
        identity_str += f"::{chunk.start_line}"
    if chunk.issue_number is not None:
        identity_str += f"::issue{chunk.issue_number}"
    if chunk.pr_number is not None:
        identity_str += f"::pr{chunk.pr_number}"

    # Hash to UUID
    identity_hash = hashlib.md5(identity_str.encode("utf-8")).hexdigest()
    return str(uuid.UUID(identity_hash))


class VectorStore:
    def __init__(self):
        if not settings.qdrant_url or not settings.qdrant_api_key:
            raise ValueError("Qdrant credentials missing from environment.")

        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30.0,
        )
        self.collection_name = settings.qdrant_collection  # default: cortex_kb
        self.dense_dim = settings.embedding_dimensions     # default: 768

    def _get_collection_dense_size(self, collection_info: Any) -> int | None:
        """Best-effort extraction of the existing dense vector size from Qdrant."""
        vectors_config = collection_info.config.params.vectors

        if isinstance(vectors_config, dict):
            default_vector = vectors_config.get("") or vectors_config.get("default")
            return getattr(default_vector, "size", None)

        return getattr(vectors_config, "size", None)

    def ensure_collection(self) -> None:
        """Create the collection if it doesn't already exist, configuring dense + sparse vectors."""
        try:
            collection_info = self.client.get_collection(self.collection_name)
            existing_dense_dim = self._get_collection_dense_size(collection_info)
            if existing_dense_dim is not None and existing_dense_dim != self.dense_dim:
                raise ValueError(
                    f"Qdrant collection '{self.collection_name}' has dense vector "
                    f"dimension {existing_dense_dim}, but EMBEDDING_DIMENSIONS={self.dense_dim}. "
                    "Recreate the collection or switch to a matching embedding model."
                )
            self._create_payload_indices()
            logger.info(f"Qdrant collection '{self.collection_name}' exists.")
        except UnexpectedResponse as e:
            if "Not found" in str(e):
                logger.info(f"Creating Qdrant collection '{self.collection_name}'...")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.dense_dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                    sparse_vectors_config={
                        "sparse": qmodels.SparseVectorParams(
                            index=qmodels.SparseIndexParams(
                                on_disk=False,
                            )
                        )
                    },
                )
                
                # Payload indices for fast filtering
                self._create_payload_indices()
            else:
                raise

    def _create_payload_indices(self) -> None:
        """Create indices on payload fields used frequently in filtering operations."""
        indices = [
            ("repo", qmodels.PayloadSchemaType.KEYWORD),
            ("branch", qmodels.PayloadSchemaType.KEYWORD),
            ("commit_sha", qmodels.PayloadSchemaType.KEYWORD),
            ("file_sha", qmodels.PayloadSchemaType.KEYWORD),
            ("ingest_run_id", qmodels.PayloadSchemaType.KEYWORD),
            ("file_path", qmodels.PayloadSchemaType.KEYWORD),
            ("source_type", qmodels.PayloadSchemaType.KEYWORD),
            ("chunk_type", qmodels.PayloadSchemaType.KEYWORD),
            ("user_id", qmodels.PayloadSchemaType.KEYWORD),
            ("is_public", qmodels.PayloadSchemaType.BOOL),
        ]
        
        for field, schema_type in indices:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=schema_type,
                )
            except UnexpectedResponse as e:
                message = str(e).lower()
                if "already exists" in message or "conflict" in message:
                    continue
                raise
        logger.info("Created metadata payload indices in Qdrant.")

    def upsert_chunks(self, chunks: list[Chunk], dense_vectors: list[list[float]], sparse_vectors: list[dict]) -> None:
        """
        Upsert a batch of chunks into Qdrant.
        """
        if not chunks:
            return

        points = []
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors):
            # Deterministic UUID prevents duplication on re-indexing
            point_id = generate_chunk_id(chunk)
            chunk.id = point_id  # sync the object natively

            payload: dict[str, Any] = {
                "repo": chunk.repo,
                "branch": chunk.branch,
                "commit_sha": chunk.commit_sha,
                "file_sha": chunk.file_sha,
                "ingest_run_id": chunk.ingest_run_id,
                "file_path": chunk.file_path,
                "language": chunk.language,
                "source_type": chunk.source_type,
                "chunk_type": chunk.chunk_type,
                "function_name": chunk.function_name,
                "class_name": chunk.class_name,
                "signature": chunk.signature,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "section_title": chunk.section_title,
                "text": chunk.text,
                "issue_number": chunk.issue_number,
                "pr_number": chunk.pr_number,
                "state": chunk.state,
                "labels": chunk.labels,
                "indexed_at": now_str,
                # Multi-tenant isolation (Phase 8)
                "user_id": chunk.user_id,
                "is_public": chunk.is_public,
            }
            
            # Merge custom metadata (like large_function full_body)
            payload.update(chunk.metadata)

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector={
                        "": dense,  # Default dense vector
                        "sparse": qmodels.SparseVector(
                            indices=sparse["indices"],
                            values=sparse["values"],
                        )
                    },
                    payload=payload,
                )
            )

        # Upsert in bulk (Qdrant handles large batch splits gracefully for points < memory limit)
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )
        logger.info(f"Upserted {len(points)} chunks to Qdrant collection '{self.collection_name}'.")

    def delete_by_file(
        self,
        repo: str,
        file_path: str,
        branch: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Filter-delete all chunks associated with a specific file. Used for webhooks."""
        must_conditions = [
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo)
            ),
            qmodels.FieldCondition(
                key="file_path",
                match=qmodels.MatchValue(value=file_path)
            ),
        ]
        if branch:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="branch",
                    match=qmodels.MatchValue(value=branch)
                )
            )
        if user_id:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=user_id)
                )
            )
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(must=must_conditions)
            ),
            wait=True,
        )
        logger.info(f"Deleted chunks for {repo}/{file_path} (branch={branch}, user={user_id})")

    def delete_by_repo(self, repo: str, user_id: str | None = None, branch: str | None = None) -> None:
        """Filter-delete chunks associated with a repo, optionally scoped by branch and user_id."""
        try:
            self.client.get_collection(self.collection_name)
        except UnexpectedResponse as e:
            if "not found" in str(e).lower() or "404" in str(e):
                logger.info(
                    "Skipping Qdrant delete for %s because collection '%s' does not exist.",
                    repo,
                    self.collection_name,
                )
                return
            raise

        must_conditions = [
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo)
            ),
        ]
        if user_id:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=user_id)
                )
            )
        if branch:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="branch",
                    match=qmodels.MatchValue(value=branch)
                )
            )
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(must=must_conditions)
            ),
            wait=True,
        )
        logger.info(f"Deleted chunks for repo {repo} (branch={branch}, user={user_id})")

    def count_by_repo(self, repo: str, user_id: str | None = None, branch: str | None = None) -> int:
        """Count chunks associated with a repo, optionally scoped by branch and user_id."""
        try:
            self.client.get_collection(self.collection_name)
        except UnexpectedResponse as e:
            if "not found" in str(e).lower() or "404" in str(e):
                return 0
            raise

        must_conditions = [
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo),
            ),
        ]
        if user_id:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=user_id),
                )
            )
        if branch:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="branch",
                    match=qmodels.MatchValue(value=branch),
                )
            )

        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=qmodels.Filter(must=must_conditions),
            exact=True,
        )
        return int(result.count or 0)

    def delete_stale_branch_runs(
        self,
        repo: str,
        branch: str,
        active_ingest_run_id: str,
        user_id: str | None = None,
    ) -> None:
        """Delete chunks for a repo branch that do not belong to the active ingest run."""
        must_conditions = [
            qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)),
            qmodels.FieldCondition(key="branch", match=qmodels.MatchValue(value=branch)),
        ]
        if user_id:
            must_conditions.append(
                qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id))
            )

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=must_conditions,
                    must_not=[
                        qmodels.FieldCondition(
                            key="ingest_run_id",
                            match=qmodels.MatchValue(value=active_ingest_run_id),
                        )
                    ],
                )
            ),
            wait=True,
        )
        logger.info(
            "Deleted stale chunks for repo %s branch %s excluding run %s",
            repo,
            branch,
            active_ingest_run_id,
        )

    def delete_branch_run(
        self,
        repo: str,
        branch: str,
        ingest_run_id: str,
        user_id: str | None = None,
    ) -> None:
        """Delete chunks for one failed/incomplete ingest run."""
        must_conditions = [
            qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)),
            qmodels.FieldCondition(key="branch", match=qmodels.MatchValue(value=branch)),
            qmodels.FieldCondition(key="ingest_run_id", match=qmodels.MatchValue(value=ingest_run_id)),
        ]
        if user_id:
            must_conditions.append(
                qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id))
            )

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(must=must_conditions)
            ),
            wait=True,
        )
        logger.info(
            "Deleted chunks for failed repo %s branch %s run %s",
            repo,
            branch,
            ingest_run_id,
        )

    def search(
        self,
        query_dense: list[float],
        query_sparse: dict[str, Any],
        filters: dict[str, str] | None = None,
        top_k: int = 10,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search using default RRF (Reciprocal Rank Fusion) built into Qdrant.
        
        Row-level tenant isolation: results are automatically filtered to chunks
        owned by user_id OR marked as is_public=true.
        """
        must_conditions = []
        if filters:
            for k, v in filters.items():
                must_conditions.append(
                    qmodels.FieldCondition(
                        key=k, match=qmodels.MatchValue(value=v)
                    )
                )

        # Tenant isolation: user sees their own data + public data
        if user_id:
            must_conditions.append(
                qmodels.Filter(
                    should=[
                        qmodels.FieldCondition(
                            key="user_id",
                            match=qmodels.MatchValue(value=user_id)
                        ),
                        qmodels.FieldCondition(
                            key="is_public",
                            match=qmodels.MatchValue(value=True)
                        ),
                    ]
                )
            )

        qdrant_filters = qmodels.Filter(must=must_conditions) if must_conditions else None

        search_result = self.client.query_batch_points(
            collection_name=self.collection_name,
            requests=[
                # Dense search request
                qmodels.QueryRequest(
                    query=query_dense,
                    filter=qdrant_filters,
                    limit=top_k,
                    with_payload=True,
                ),
                # Sparse search request
                qmodels.QueryRequest(
                    query=qmodels.SparseVector(
                        indices=query_sparse["indices"],
                        values=query_sparse["values"],
                    ),
                    using="sparse",
                    filter=qdrant_filters,
                    limit=top_k,
                    with_payload=True,
                ),
            ],
        )

        # Merge, deduplicate, and sort using naïve score addition
        merged_scores = {}
        payloads = {}

        dense_results = search_result[0].points
        sparse_results = search_result[1].points

        # Rank-based scoring (RRF approximation: score = 1 / (rank + 60))
        for rank, hit in enumerate(dense_results):
            merged_scores[hit.id] = merged_scores.get(hit.id, 0.0) + (1.0 / (rank + 60.0))
            payloads[hit.id] = hit.payload

        for rank, hit in enumerate(sparse_results):
            merged_scores[hit.id] = merged_scores.get(hit.id, 0.0) + (1.0 / (rank + 60.0))
            payloads[hit.id] = hit.payload

        # Sort combined results
        sorted_ids = sorted(merged_scores.keys(), key=lambda i: merged_scores[i], reverse=True)
        
        final_results = []
        for sid in sorted_ids[:top_k]:
            final_results.append({
                "id": str(sid),
                "score": merged_scores[sid],
                "payload": payloads[sid]
            })

        return final_results

    def sample_payloads(
        self,
        filters: dict[str, str],
        limit: int = 20,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch stored chunk payloads by metadata without spending embedding quota."""
        must_conditions = [
            qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))
            for key, value in filters.items()
        ]
        if user_id:
            must_conditions.append(
                qmodels.Filter(
                    should=[
                        qmodels.FieldCondition(
                            key="user_id",
                            match=qmodels.MatchValue(value=user_id),
                        ),
                        qmodels.FieldCondition(
                            key="is_public",
                            match=qmodels.MatchValue(value=True),
                        ),
                    ]
                )
            )

        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=qmodels.Filter(must=must_conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [point.payload or {} for point in points]
