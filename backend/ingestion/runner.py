"""Ingestion job runner.

This module owns long-running ingestion execution so API routes can stay thin.
The current local mode still starts it with ``asyncio.create_task`` from FastAPI,
but the runner is now callable from a separate process/job entrypoint later.
"""

from __future__ import annotations

import time
import uuid

from agents.summarizer import generate_repo_snapshot
from core.auth import AuthenticatedUser
from core.cache_limits import active_ingest_lock, cache_set_json, enforce_repo_size_limit, snapshot_cache_key
from core.config import settings
from core.job_store import job_store
from core.logger import get_logger
from core.tenant import tenant_scoped_id
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.qdrant_store import VectorStore
from ingestion.github_client import GitHubClient
from ingestion.pipeline import IngestionPipeline
from models.schemas import IngestRequest

logger = get_logger(__name__)


def _repo_branch_id(repo: str, branch: str) -> str:
    return f"{repo}::{branch}"


def _format_timing_summary(timings_ms: dict) -> str:
    labels = {
        "clone_ms": "clone",
        "file_walk_ms": "walk",
        "file_read_ms": "file_read",
        "tree_fetch_ms": "tree",
        "filter_ms": "filter",
        "file_fetch_ms": "fetch",
        "parse_chunk_ms": "parse/chunk",
        "graph_write_ms": "graph",
        "embedding_ms": "embed",
        "sparse_vector_ms": "sparse",
        "qdrant_upsert_ms": "upsert",
        "snapshot_ms": "snapshot",
        "total_ms": "total",
    }
    parts = []
    for key, value in timings_ms.items():
        if not isinstance(value, int | float):
            continue
        label = labels.get(key, key.removesuffix("_ms"))
        parts.append((key == "total_ms", f"{label}: {value / 1000:.1f}s"))
    parts.sort(key=lambda item: item[0])
    return " | ".join(part for _, part in parts)


def _format_timing_breakdown(timings_ms: dict) -> str:
    numeric_timings = {
        key: value
        for key, value in timings_ms.items()
        if isinstance(value, int | float)
    }
    if not numeric_timings:
        return "{}"
    ordered = dict(
        sorted(
            numeric_timings.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    return ", ".join(f"{key}={value / 1000:.2f}s" for key, value in ordered.items())


def _load_previous_file_shas(
    neo4j: Neo4jManager,
    repo: str,
    branch: str,
    user_id: str,
) -> dict[str, str]:
    rows = neo4j.run_query(
        "MATCH (f:File) "
        "WHERE f.repo = $repo AND coalesce(f.branch, 'main') = $branch "
        "AND f.user_id = $user_id AND f.file_sha IS NOT NULL "
        "RETURN f.path AS path, f.file_sha AS file_sha",
        {"repo": repo, "branch": branch, "user_id": user_id},
    )
    return {
        str(row["path"]): str(row["file_sha"])
        for row in rows
        if row.get("path") and row.get("file_sha")
    }


def _delete_file_graph(
    neo4j: Neo4jManager,
    repo: str,
    branch: str,
    file_path: str,
    user_id: str,
    is_public: bool,
) -> None:
    graph_repo_id = _repo_branch_id(repo, branch)
    raw_file_id = f"{graph_repo_id}::{file_path}"
    neo4j.run_query(
        "MATCH (n) "
        "WHERE n.id = $file_id OR n.raw_id = $raw_file_id OR n.raw_id STARTS WITH $file_prefix "
        "DETACH DELETE n",
        {
            "file_id": tenant_scoped_id(raw_file_id, user_id, is_public),
            "raw_file_id": raw_file_id,
            "file_prefix": f"{raw_file_id}::",
        },
    )


async def run_ingest_job(
    job_id: str,
    request: IngestRequest,
    user: AuthenticatedUser,
    initial_status: str = "processing",
    failure_status: str = "failed",
    previous_commit_sha: str | None = None,
) -> None:
    """Run a complete ingestion job and publish progress to the shared job store."""
    ingest_run_id: str | None = None

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
        branch = request.branch or "main"
        ingest_run_id = str(uuid.uuid4())
        await emit_progress("starting", f"Starting ingest for {request.repo} @ {branch}")

        owner, repo_name = request.repo.split("/")

        await emit_progress("fetching_tree", "Checking repository metadata")
        async with GitHubClient(token=user.github_token) as client:
            metadata = await client.fetch_repo_metadata(owner, repo_name)
        repo_size_kb = metadata.get("size", 0)
        enforce_repo_size_limit(repo_size_kb)

        default_branch = metadata.get("default_branch") or "main"
        repo_branch_id = _repo_branch_id(request.repo, branch)
        neo4j = None
        try:
            neo4j = Neo4jManager()
            neo4j.merge_tenant_node(
                "Repository",
                repo_branch_id,
                {
                    "full_name": request.repo,
                    "owner": owner,
                    "name": repo_name,
                    "branch": branch,
                    "default_branch": default_branch,
                    "is_private": bool(metadata.get("private", True)),
                    "ingestion_status": initial_status,
                    "ingest_run_id": ingest_run_id,
                },
                user.user_id,
                metadata.get("private", True) is False,
            )
        except Exception:
            neo4j = None

        async with GitHubClient(token=user.github_token) as client:
            branch_data = await client.fetch_branch(owner, repo_name, branch)
        commit_sha = (branch_data.get("commit") or {}).get("sha")
        if neo4j is not None:
            neo4j.run_query(
                "MATCH (r:Repository {id: $repo}) SET r.commit_sha = $commit_sha",
                {
                    "repo": tenant_scoped_id(
                        repo_branch_id,
                        user.user_id,
                        metadata.get("private", True) is False,
                    ),
                    "commit_sha": commit_sha,
                },
            )

        pipeline = IngestionPipeline(github_token=user.github_token)
        is_public = metadata.get("private", True) is False
        previous_file_shas = {}
        if previous_commit_sha and neo4j is not None:
            previous_file_shas = _load_previous_file_shas(
                neo4j,
                request.repo,
                branch,
                user.user_id,
            )
            await emit_progress(
                "file_filtering",
                f"Loaded {len(previous_file_shas)} previous file identities for incremental update",
                {"previous_files": len(previous_file_shas)},
            )

        with active_ingest_lock(user.user_id, job_id):
            stats = await pipeline.ingest_repo(
                repo=request.repo,
                branch=branch,
                commit_sha=commit_sha,
                ingest_run_id=ingest_run_id,
                include_issues=False,
                include_prs=False,
                include_commits=False,
                max_commits=0,
                user_id=user.user_id,
                is_public=is_public,
                previous_file_shas=previous_file_shas,
                progress_cb=emit_progress,
            )

        await emit_progress("snapshot", "Generating architectural snapshot")
        snapshot_started_at = time.perf_counter()
        snapshot = await generate_repo_snapshot(request.repo, user.user_id, branch=branch)
        cache_set_json(
            snapshot_cache_key(user.user_id, request.repo, branch, commit_sha),
            {"repo": request.repo, "snapshot": snapshot},
            settings.report_cache_ttl_seconds,
        )
        stats.setdefault("timings_ms", {})["snapshot_ms"] = int(
            (time.perf_counter() - snapshot_started_at) * 1000
        )
        timing_summary = _format_timing_summary(stats.get("timings_ms", {}))
        timing_breakdown = _format_timing_breakdown(stats.get("timings_ms", {}))
        logger.info(
            "Ingest timing summary for %s @ %s: %s | stats=%s",
            request.repo,
            branch,
            timing_summary,
            stats,
        )
        logger.warning(
            "INGEST_TIMING_SUMMARY repo=%s branch=%s chunks=%s files=%s edges=%s :: %s",
            request.repo,
            branch,
            stats.get("chunks_created"),
            stats.get("files_parsed"),
            stats.get("graph_edges_created"),
            timing_breakdown,
        )
        await emit_progress(
            "timing_summary",
            timing_summary or "Timing summary unavailable",
            {
                "timings_ms": stats.get("timings_ms", {}),
                "files_parsed": stats.get("files_parsed"),
                "chunks_created": stats.get("chunks_created"),
                "graph_edges_created": stats.get("graph_edges_created"),
            },
        )

        current_file_paths = set(stats.get("current_file_paths") or [])
        removed_file_paths = sorted(set(previous_file_shas) - current_file_paths)
        if removed_file_paths:
            await emit_progress(
                "cleanup",
                f"Removing {len(removed_file_paths)} files deleted from the branch",
                {"removed_files": len(removed_file_paths)},
            )
            vector_store = VectorStore()
            for file_path in removed_file_paths:
                try:
                    vector_store.delete_by_file(
                        request.repo,
                        file_path,
                        branch=branch,
                        user_id=user.user_id,
                    )
                except Exception:
                    logger.exception("Failed to delete removed file chunks for %s", file_path)
                if neo4j is not None:
                    try:
                        _delete_file_graph(
                            neo4j,
                            request.repo,
                            branch,
                            file_path,
                            user.user_id,
                            is_public,
                        )
                    except Exception:
                        logger.exception("Failed to delete removed file graph for %s", file_path)
        stats["files_deleted"] = len(removed_file_paths)

        if neo4j is not None and not previous_file_shas:
            try:
                VectorStore().delete_stale_branch_runs(
                    request.repo,
                    branch,
                    active_ingest_run_id=ingest_run_id,
                    user_id=user.user_id,
                )
            except Exception:
                pass
        try:
            neo4j = neo4j or Neo4jManager()
            neo4j.merge_tenant_node(
                "Repository",
                repo_branch_id,
                {
                    "full_name": request.repo,
                    "owner": owner,
                    "name": repo_name,
                    "branch": branch,
                    "default_branch": default_branch,
                    "is_private": bool(metadata.get("private", True)),
                    "ingestion_status": "ready",
                    "ingest_run_id": ingest_run_id,
                    "commit_sha": commit_sha,
                },
                user.user_id,
                metadata.get("private", True) is False,
            )
        except Exception:
            pass

        if neo4j is not None and not previous_file_shas:
            neo4j.run_query(
                "MATCH (n) WHERE n.repo = $repo AND n.user_id = $user_id "
                "AND coalesce(n.branch, 'main') = $branch "
                "AND (n.ingest_run_id IS NULL OR n.ingest_run_id <> $ingest_run_id) "
                "DETACH DELETE n",
                {
                    "repo": request.repo,
                    "branch": branch,
                    "user_id": user.user_id,
                    "ingest_run_id": ingest_run_id,
                },
            )
            neo4j.run_query(
                "MATCH (r:Repository {id: $repo}) "
                "SET r.ingestion_status = 'ready', r.last_ingest_at = datetime(), "
                "r.ingest_run_id = $ingest_run_id, r.commit_sha = $commit_sha",
                {
                    "repo": tenant_scoped_id(
                        repo_branch_id,
                        user.user_id,
                        metadata.get("private", True) is False,
                    ),
                    "ingest_run_id": ingest_run_id,
                    "commit_sha": commit_sha,
                },
            )

        await job_store.publish(
            job_id,
            {
                "type": "done",
                "state": "done",
                "stage": "done",
                "repo": request.repo,
                "branch": branch,
                "previous_commit_sha": previous_commit_sha,
                "commit_sha": commit_sha,
                "message": "Ingestion complete",
                "stats": stats,
                "snapshot": snapshot,
            },
        )
    except Exception as e:
        error_message = f"{type(e).__name__}: {e!r}"
        logger.exception(
            "Ingest job %s failed for %s with %s",
            job_id,
            request.repo,
            error_message,
        )
        branch = request.branch or "main"
        try:
            if ingest_run_id:
                try:
                    VectorStore().delete_branch_run(
                        request.repo,
                        branch,
                        ingest_run_id=ingest_run_id,
                        user_id=user.user_id,
                    )
                except Exception:
                    pass

            neo4j = Neo4jManager()
            if ingest_run_id:
                neo4j.run_query(
                    "MATCH (n) WHERE n.repo = $repo AND n.user_id = $user_id "
                    "AND coalesce(n.branch, 'main') = $branch "
                    "AND n.ingest_run_id = $ingest_run_id DETACH DELETE n",
                    {
                        "repo": request.repo,
                        "branch": branch,
                        "user_id": user.user_id,
                        "ingest_run_id": ingest_run_id,
                    },
                )
            neo4j.run_query(
                "MATCH (r:Repository {id: $repo}) SET r.ingestion_status = $status, r.last_ingest_error = $error",
                {
                    "repo": tenant_scoped_id(_repo_branch_id(request.repo, branch), user.user_id),
                    "error": str(e),
                    "status": failure_status,
                },
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
                "branch": request.branch or "main",
                "message": error_message,
            },
        )
