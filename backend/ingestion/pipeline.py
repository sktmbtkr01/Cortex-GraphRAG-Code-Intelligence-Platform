"""
Cortex Ingestion Pipeline — Phase 8 (Multi-Tenant).

Flow: GitHub fetch → parse → secret scan → chunk → embed → store (with user_id tagging)
All data is processed in-memory. No raw files are ever written to disk.
"""

import asyncio
import hashlib
import inspect
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from core.config import settings
from core.logger import get_logger
from ingestion.git_source import process_repo_files_via_git_clone_batches
from ingestion.github_client import GitHubClient
from ingestion.file_router import should_process_file, route_file
from ingestion.secret_scanner import count_secret_matches, redact_text
from ingestion.parsers.issue_parser import parse as parse_issue
from ingestion.parsers.pr_parser import parse as parse_pr
from chunkers.ast_chunker import ASTChunker
from chunkers.prose_chunker import ContentChunker
from indexing.embedder import CortexEmbedder
from indexing.qdrant_store import VectorStore
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.graph_builder.static_analyzer import NodeEdgeExtractor
from indexing.graph_builder.git_graph import GitGraphBuilder
from models.schemas import Chunk

logger = get_logger(__name__)


class IngestionPipeline:
    """Coordinates GitHub fetch, parsing, chunking, indexing, and graph writes."""

    def __init__(self, github_token: str | None = None):
        """
        Initialize the pipeline.

        Args:
            github_token: Optional ephemeral GitHub token from the authenticated user.
                          Used instead of env PAT for per-user repo access.
        """
        self.github_client = GitHubClient(token=github_token)
        self.ast_chunker = ASTChunker()
        self.content_chunker = ContentChunker()
        self.embedder = CortexEmbedder()
        self.vector_store = VectorStore()
        self.github_fetch_concurrency = settings.github_fetch_concurrency
        self.file_processing_concurrency = settings.file_processing_concurrency
        self.file_processing_batch_size = max(1, settings.file_processing_batch_size)
        self.embedding_batch_size = max(1, settings.embedding_batch_size)
        self.ingest_source = settings.ingest_source.lower().strip()
        
        # Graph
        try:
            self.neo4j = Neo4jManager()
            self.neo4j.setup_constraints()
            self.git_graph = GitGraphBuilder(self.neo4j, self.github_client)
            self.graph_enabled = True
        except Exception as e:
            logger.warning(f"Neo4j disabled or unavailable: {e}")
            self.graph_enabled = False

    async def ingest_repo(
        self,
        repo: str,
        branch: str = "main",
        commit_sha: str | None = None,
        ingest_run_id: str | None = None,
        include_issues: bool = True,
        include_prs: bool = True,
        include_commits: bool = True,
        max_commits: int = 500,
        user_id: str | None = None,
        is_public: bool = False,
        previous_file_shas: dict[str, str] | None = None,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        """
        Full ingestion pipeline: fetch → parse → scan → chunk → embed → graph.
        
        All chunks and graph nodes are tagged with user_id for row-level isolation.
        Public repos are flagged with is_public=True for access checks and metadata.
        """
        logger.info(
            f"Starting ingestion for {repo} on branch {branch} "
            f"(commit={commit_sha}, run={ingest_run_id}, user={user_id}, public={is_public})"
        )

        run_started_at = time.perf_counter()
        timings_ms: dict[str, int] = {}

        def mark_timing(stage: str, started_at: float) -> None:
            timings_ms[stage] = int((time.perf_counter() - started_at) * 1000)

        def add_timing(stage: str, started_at: float) -> None:
            timings_ms[stage] = timings_ms.get(stage, 0) + int((time.perf_counter() - started_at) * 1000)

        stats: dict[str, Any] = {
            "files_parsed": 0,
            "files_skipped": 0,
            "secrets_found": 0,
            "files_with_secrets": 0,
            "secrets_redacted": 0,
            "files_skipped_for_secrets": 0,
            "chunks_created": 0,
            "graph_edges_created": 0,
            "files_unchanged": 0,
            "files_reindexed": 0,
            "current_file_paths": [],
            "timings_ms": timings_ms,
        }
        previous_file_shas = previous_file_shas or {}
        current_file_paths: set[str] = set()
        reindexed_file_paths: set[str] = set()
        try:
            owner, repo_name = repo.split("/")
        except ValueError:
            logger.error(f"Invalid repo format: {repo}. Expected 'owner/repo'.")
            raise ValueError("Repo must be in the format 'owner/repo'")

        graph_repo_id = f"{repo}::{branch}"

        try:
            await self.github_client.__aenter__()
            fetched_ok: list[tuple[dict, str]] = []
            pending_chunks: list[Chunk] = []
            chunk_batch_index_ref = {"value": 0}

            # Setup base repository node with user_id tagging
            if self.graph_enabled:
                await self._emit_progress(progress_cb, "graph_building", "Initializing repository graph node")
                self.neo4j.merge_tenant_node("Repository", graph_repo_id, {
                    "full_name": repo,
                    "owner": owner,
                    "name": repo_name,
                    "branch": branch,
                    "default_branch": branch,
                    "commit_sha": commit_sha,
                    "ingest_run_id": ingest_run_id,
                    "ingestion_status": "processing",
                }, user_id, is_public)

            if self.ingest_source == "git_clone":
                await self._emit_progress(progress_cb, "clone_start", "Shallow cloning repository branch")
                clone_result = await process_repo_files_via_git_clone_batches(
                    repo=repo,
                    branch=branch,
                    token=self.github_client.headers.get("Authorization", "").removeprefix("Bearer ") or None,
                    batch_size=self.file_processing_batch_size,
                    batch_cb=lambda file_batch, meta: self._process_fetched_file_batch(
                        file_batch=file_batch,
                        batch_index=int(meta["batch"]),
                        total_batches=int(meta["total_batches"]),
                        total_files=int(meta["total_files"]),
                        stats=stats,
                        pending_chunks=pending_chunks,
                        chunk_batch_index_ref=chunk_batch_index_ref,
                        current_file_paths=current_file_paths,
                        reindexed_file_paths=reindexed_file_paths,
                        previous_file_shas=previous_file_shas,
                        repo=repo,
                        branch=branch,
                        commit_sha=commit_sha,
                        ingest_run_id=ingest_run_id,
                        graph_repo_id=graph_repo_id,
                        user_id=user_id,
                        is_public=is_public,
                        progress_cb=progress_cb,
                        timings_ms=timings_ms,
                        add_timing=add_timing,
                    ),
                )
                timings_ms["clone_ms"] = clone_result.clone_ms
                timings_ms["file_walk_ms"] = clone_result.file_walk_ms
                timings_ms["file_read_ms"] = clone_result.file_read_ms
                stats["files_skipped"] += clone_result.skipped_files
                await self._emit_progress(
                    progress_cb,
                    "clone_done",
                    f"Cloned, processed {clone_result.batches_processed} file batches, and cleaned up temporary checkout",
                    {
                        "total": clone_result.total_files,
                        "eligible": clone_result.eligible_files,
                        "skipped": clone_result.skipped_files,
                        "batches": clone_result.batches_processed,
                    },
                )
            elif self.ingest_source == "github_api":
                # ── 1. Fetch file tree ────────────────────────────────────
                await self._emit_progress(progress_cb, "fetching_tree", "Fetching repository tree")
                stage_started_at = time.perf_counter()
                tree = await self.github_client.fetch_file_tree(owner, repo_name, branch)
                mark_timing("tree_fetch_ms", stage_started_at)
                await self._emit_progress(
                    progress_cb,
                    "fetching_files",
                    f"Fetched tree with {len(tree)} items",
                    {"total": len(tree), "processed": 0},
                )
                
                # ── 2. Filter, fetch, parse, chunk, graph files ───────────
                stage_started_at = time.perf_counter()
                total_files = len(tree)
                eligible_items: list[dict] = []
                for item in tree:
                    path = item["path"]
                    size = item.get("size", 0)
                    if should_process_file(path, size):
                        if item.get("sha"):
                            item["file_sha"] = item["sha"]
                        eligible_items.append(item)
                    else:
                        stats["files_skipped"] += 1
                mark_timing("filter_ms", stage_started_at)

                await self._emit_progress(
                    progress_cb,
                    "fetching_files",
                    f"Fetching {len(eligible_items)} eligible files with concurrency {self.github_fetch_concurrency}",
                    {"total": total_files, "eligible": len(eligible_items)},
                )

                stage_started_at = time.perf_counter()
                fetched_results = await self.github_client.fetch_file_contents_bulk(
                    owner,
                    repo_name,
                    eligible_items,
                    concurrency=self.github_fetch_concurrency,
                )
                mark_timing("file_fetch_ms", stage_started_at)

                total_fetched = len(fetched_results)
                for index, (item, content, err) in enumerate(fetched_results, start=1):
                    if index == 1 or index % 25 == 0 or index == total_fetched:
                        await self._emit_progress(
                            progress_cb,
                            "fetching_files",
                            f"Fetched file content {index}/{total_fetched}",
                            {"total": total_fetched, "processed": index},
                        )

                    if err is not None or content is None:
                        logger.warning(f"Failed to fetch content for {item.get('path')}: {err}")
                        stats["files_skipped"] += 1
                        continue
                    fetched_ok.append((item, content))
            else:
                raise ValueError(
                    f"Unsupported INGEST_SOURCE '{self.ingest_source}'. "
                    "Expected 'github_api' or 'git_clone'."
                )
            
            if fetched_ok:
                await self._emit_progress(
                    progress_cb,
                    "chunking",
                    f"Scanning and chunking {len(fetched_ok)} files in batches of {self.file_processing_batch_size}",
                    {"total": len(fetched_ok)},
                )

                total_batches = max(1, math.ceil(len(fetched_ok) / self.file_processing_batch_size))
                for offset in range(0, len(fetched_ok), self.file_processing_batch_size):
                    batch = fetched_ok[offset : offset + self.file_processing_batch_size]
                    await self._process_fetched_file_batch(
                        file_batch=batch,
                        batch_index=(offset // self.file_processing_batch_size) + 1,
                        total_batches=total_batches,
                        total_files=len(fetched_ok),
                        stats=stats,
                        pending_chunks=pending_chunks,
                        chunk_batch_index_ref=chunk_batch_index_ref,
                        current_file_paths=current_file_paths,
                        reindexed_file_paths=reindexed_file_paths,
                        previous_file_shas=previous_file_shas,
                        repo=repo,
                        branch=branch,
                        commit_sha=commit_sha,
                        ingest_run_id=ingest_run_id,
                        graph_repo_id=graph_repo_id,
                        user_id=user_id,
                        is_public=is_public,
                        progress_cb=progress_cb,
                        timings_ms=timings_ms,
                        add_timing=add_timing,
                    )

            # ── 3. Issues ─────────────────────────────────────────────
            if include_issues:
                stage_started_at = time.perf_counter()
                await self._emit_progress(progress_cb, "issues", "Fetching issues")
                issues = await self.github_client.fetch_issues(owner, repo_name, state="all")
                issues, issue_secret_stats = self._redact_github_records(issues, ("title", "body"))
                stats["files_with_secrets"] += issue_secret_stats["records_with_secrets"]
                stats["secrets_found"] += issue_secret_stats["secrets_redacted"]
                stats["secrets_redacted"] += issue_secret_stats["secrets_redacted"]
                
                if self.graph_enabled:
                    await self._emit_progress(progress_cb, "graph_building", "Building issue graph")
                    await self.git_graph.build_issue_graph(issues, repo, branch=branch, user_id=user_id, is_public=is_public)
                    
                for issue in issues:
                    if "pull_request" not in issue:
                        parsed_issue = parse_issue(issue)
                        stats["files_parsed"] += 1

                        chunks = self.content_chunker.chunk(
                            text=parsed_issue.content,
                            repo=repo,
                            file_path=parsed_issue.path,
                            language=parsed_issue.language,
                            source_type="issue",
                            metadata=parsed_issue.metadata,
                        )
                        # Tag with user_id
                        for c in chunks:
                            c.user_id = user_id
                            c.is_public = is_public
                            c.branch = branch
                            c.commit_sha = commit_sha
                            c.ingest_run_id = ingest_run_id
                        stats["chunks_created"] += len(chunks)
                        pending_chunks.extend(chunks)
                mark_timing("issues_ms", stage_started_at)

            # ── 4. Pull Requests ──────────────────────────────────────
            if include_prs:
                stage_started_at = time.perf_counter()
                await self._emit_progress(progress_cb, "prs", "Fetching pull requests")
                prs = await self.github_client.fetch_pull_requests(owner, repo_name, state="all")
                prs, pr_secret_stats = self._redact_github_records(prs, ("title", "body"))
                stats["files_with_secrets"] += pr_secret_stats["records_with_secrets"]
                stats["secrets_found"] += pr_secret_stats["secrets_redacted"]
                stats["secrets_redacted"] += pr_secret_stats["secrets_redacted"]
                
                if self.graph_enabled:
                    await self._emit_progress(progress_cb, "graph_building", "Building pull request graph")
                    await self.git_graph.build_pr_graph(prs, repo, branch=branch, user_id=user_id, is_public=is_public)
                    
                for pr in prs:
                    try:
                        pr_files = await self.github_client.fetch_pr_files(owner, repo_name, pr["number"])
                    except Exception as e:
                        logger.warning(f"Failed to fetch files for PR #{pr['number']}: {e}")
                        pr_files = []

                    parsed_pr = parse_pr(pr, pr_files)
                    stats["files_parsed"] += 1

                    chunks = self.content_chunker.chunk(
                        text=parsed_pr.content,
                        repo=repo,
                        file_path=parsed_pr.path,
                        language=parsed_pr.language,
                        source_type="pr",
                        metadata=parsed_pr.metadata,
                    )
                    # Tag with user_id
                    for c in chunks:
                        c.user_id = user_id
                        c.is_public = is_public
                        c.branch = branch
                        c.commit_sha = commit_sha
                        c.ingest_run_id = ingest_run_id
                    stats["chunks_created"] += len(chunks)
                    pending_chunks.extend(chunks)
                mark_timing("prs_ms", stage_started_at)
                    
            # ── 5. Commits ────────────────────────────────────────────
            if include_commits and self.graph_enabled:
                stage_started_at = time.perf_counter()
                await self._emit_progress(progress_cb, "commits", "Fetching commits")
                # We fetch commits solely for graph history, not for RAG chunking
                commits = await self.github_client.fetch_commits(owner, repo_name, limit=max_commits)
                await self._emit_progress(progress_cb, "graph_building", "Building commit graph")
                await self.git_graph.build_commit_graph(commits, repo, branch=branch, user_id=user_id, is_public=is_public)
                mark_timing("commits_ms", stage_started_at)

            # ── 6. Embed and Upsert (with user_id in payload) ─────────
            if pending_chunks:
                chunk_batch_index_ref["value"] += 1
                await self._embed_and_upsert_chunk_batch(
                    pending_chunks,
                    chunk_batch_index_ref["value"],
                    progress_cb,
                    timings_ms,
                    add_timing,
                )
                pending_chunks.clear()
            elif stats["chunks_created"] == 0:
                logger.warning("No chunks generated to embed.")
            else:
                logger.info("All chunks were embedded and upserted during batch processing.")

            mark_timing("total_ms", run_started_at)
            stats["current_file_paths"] = sorted(current_file_paths)

            logger.info(
                f"Ingestion complete for {repo}. "
                f"Parsed: {stats['files_parsed']}, Skipped: {stats['files_skipped']}, "
                f"Secrets redacted: {stats['secrets_redacted']}, Chunks: {stats['chunks_created']}, "
                f"timings_ms={timings_ms}"
            )
            await self.github_client.aclose()
            return stats

        except Exception as e:
            await self.github_client.aclose()
            logger.exception(
                "Ingestion failed for %s with %s: %r",
                repo,
                type(e).__name__,
                e,
            )
            raise

    async def _embed_and_upsert_chunk_batch(
        self,
        chunks: list[Chunk],
        batch_index: int,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None,
        timings_ms: dict[str, int],
        add_timing: Callable[[str, float], None],
    ) -> None:
        logger.info("Embedding chunk batch %s with %s chunks...", batch_index, len(chunks))
        await self._emit_progress(
            progress_cb,
            "embedding_batch",
            f"Embedding chunk batch {batch_index} ({len(chunks)} chunks)",
            {"batch": batch_index, "chunks": len(chunks)},
        )

        texts_to_embed = [chunk.text for chunk in chunks]
        stage_started_at = time.perf_counter()
        dense_vectors = await self.embedder.embed_batch(texts_to_embed)
        dense_ms = int((time.perf_counter() - stage_started_at) * 1000)
        add_timing("embedding_ms", stage_started_at)

        stage_started_at = time.perf_counter()
        sparse_vectors = [self.embedder.generate_sparse_vector(text) for text in texts_to_embed]
        sparse_ms = int((time.perf_counter() - stage_started_at) * 1000)
        add_timing("sparse_vector_ms", stage_started_at)

        await self._emit_progress(
            progress_cb,
            "qdrant_upsert",
            f"Upserting chunk batch {batch_index} to Qdrant",
            {"batch": batch_index, "chunks": len(chunks)},
        )
        stage_started_at = time.perf_counter()
        self.vector_store.ensure_collection()
        self.vector_store.upsert_chunks(
            chunks=chunks,
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
        )
        upsert_ms = int((time.perf_counter() - stage_started_at) * 1000)
        add_timing("qdrant_upsert_ms", stage_started_at)

        logger.warning(
            "INGEST_VECTOR_BATCH batch=%s chunks=%s dense=%.2fs sparse=%.2fs qdrant=%.2fs",
            batch_index,
            len(chunks),
            dense_ms / 1000,
            sparse_ms / 1000,
            upsert_ms / 1000,
        )

    async def _process_fetched_file_batch(
        self,
        file_batch: list[tuple[dict, str]],
        batch_index: int,
        total_batches: int,
        total_files: int,
        stats: dict[str, Any],
        pending_chunks: list[Chunk],
        chunk_batch_index_ref: dict[str, int],
        current_file_paths: set[str],
        reindexed_file_paths: set[str],
        previous_file_shas: dict[str, str],
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        graph_repo_id: str,
        user_id: str | None,
        is_public: bool,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None,
        timings_ms: dict[str, int],
        add_timing: Callable[[str, float], None],
    ) -> None:
        await self._emit_progress(
            progress_cb,
            "processing_batch",
            f"Processing file batch {batch_index}/{total_batches}",
            {
                "batch": batch_index,
                "total_batches": total_batches,
                "files": len(file_batch),
                "processed_files": stats["files_parsed"],
                "total_files": total_files,
            },
        )

        changed_file_batch: list[tuple[dict, str]] = []
        for item, content in file_batch:
            path = item.get("path")
            if not path:
                stats["files_skipped"] += 1
                continue

            file_sha = item.get("file_sha") or item.get("sha")
            if not file_sha:
                file_sha = hashlib.sha1(content.encode("utf-8")).hexdigest()
                item["file_sha"] = file_sha
            current_file_paths.add(path)

            if previous_file_shas.get(path) == file_sha:
                stats["files_unchanged"] += 1
                continue
            changed_file_batch.append((item, content))

        if not changed_file_batch:
            await self._emit_progress(
                progress_cb,
                "file_filtering",
                f"Skipped file batch {batch_index}/{total_batches}; all files unchanged",
                {
                    "batch": batch_index,
                    "total_batches": total_batches,
                    "unchanged_files": stats["files_unchanged"],
                    "total_files": total_files,
                },
            )
            return

        await self._emit_progress(
            progress_cb,
            "file_filtering",
            f"Selected {len(changed_file_batch)}/{len(file_batch)} changed files in batch {batch_index}",
            {
                "batch": batch_index,
                "changed_files": len(changed_file_batch),
                "batch_files": len(file_batch),
                "unchanged_files": stats["files_unchanged"],
            },
        )

        stage_started_at = time.perf_counter()
        processed_files = await self._process_files_concurrently(
            changed_file_batch,
            repo,
            branch,
            commit_sha,
            ingest_run_id,
            user_id,
            is_public,
        )
        add_timing("parse_chunk_ms", stage_started_at)

        processed_files.sort(key=lambda r: r["index"])
        graph_files = []
        for result in processed_files:
            path = result["path"]

            secret_count = int(result["secrets_redacted"])
            if secret_count:
                logger.warning(f"Secret material detected and redacted in {path}.")
                stats["secrets_found"] += secret_count
                stats["files_with_secrets"] += 1
                stats["secrets_redacted"] += secret_count

            parsed_file = result["parsed_file"]
            chunks = result["chunks"]
            stats["files_parsed"] += 1
            stats["chunks_created"] += len(chunks)
            stats["files_reindexed"] += 1
            if path in previous_file_shas and path not in reindexed_file_paths:
                self.vector_store.delete_by_file(repo, path, branch=branch, user_id=user_id)
                if self.graph_enabled:
                    self._delete_file_graph(path, graph_repo_id, user_id, is_public)
                reindexed_file_paths.add(path)
            pending_chunks.extend(chunks)

            if self.graph_enabled:
                graph_files.append((path, parsed_file))

            while len(pending_chunks) >= self.embedding_batch_size:
                chunk_batch_index_ref["value"] += 1
                chunk_batch = pending_chunks[: self.embedding_batch_size]
                del pending_chunks[: self.embedding_batch_size]
                await self._embed_and_upsert_chunk_batch(
                    chunk_batch,
                    chunk_batch_index_ref["value"],
                    progress_cb,
                    timings_ms,
                    add_timing,
                )

        if self.graph_enabled and graph_files:
            stage_started_at = time.perf_counter()
            edge_count = await self._write_file_graph_batch(
                progress_cb,
                graph_files,
                repo,
                branch,
                commit_sha,
                ingest_run_id,
                graph_repo_id,
                user_id,
                is_public,
            )
            add_timing("graph_write_ms", stage_started_at)
            stats["graph_edges_created"] += edge_count

    async def _write_file_graph(
        self,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None,
        path: str,
        parsed_file,
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        graph_repo_id: str,
        user_id: str | None,
        is_public: bool,
    ) -> int:
        return await self._write_file_graph_batch(
            progress_cb,
            [(path, parsed_file)],
            repo,
            branch,
            commit_sha,
            ingest_run_id,
            graph_repo_id,
            user_id,
            is_public,
        )

    async def _write_file_graph_batch(
        self,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None,
        graph_files: list[tuple[str, Any]],
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        graph_repo_id: str,
        user_id: str | None,
        is_public: bool,
    ) -> int:
        await self._emit_progress(
            progress_cb,
            "graph_write",
            f"Writing graph batch for {len(graph_files)} files",
            {"files": len(graph_files)},
        )
        nodes_by_label: dict[str, dict[str, dict[str, Any]]] = {}
        relationships_by_type: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        edge_count = 0

        for path, parsed_file in graph_files:
            edge_count += self._collect_file_graph(
                path,
                parsed_file,
                repo,
                branch,
                commit_sha,
                ingest_run_id,
                graph_repo_id,
                nodes_by_label,
                relationships_by_type,
            )

        for label, nodes_by_id in nodes_by_label.items():
            self.neo4j.merge_tenant_nodes_batch(label, list(nodes_by_id.values()), user_id, is_public)
        for rel_type, relationships_by_pair in relationships_by_type.items():
            self.neo4j.merge_tenant_relationships_batch(
                rel_type,
                list(relationships_by_pair.values()),
                user_id,
                is_public,
            )

        return edge_count

    def _collect_file_graph(
        self,
        path: str,
        parsed_file: Any,
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        graph_repo_id: str,
        nodes_by_label: dict[str, dict[str, dict[str, Any]]],
        relationships_by_type: dict[str, dict[tuple[str, str], dict[str, Any]]],
    ) -> int:
        file_id = f"{graph_repo_id}::{path}"

        self._queue_graph_node(
            nodes_by_label,
            "File",
            file_id,
            {
                "path": path,
                "repo": repo,
                "branch": branch,
                "commit_sha": commit_sha,
                "ingest_run_id": ingest_run_id,
                "language": parsed_file.language,
                "file_sha": getattr(parsed_file, "metadata", {}).get("file_sha"),
            },
        )
        self._queue_graph_relationship(
            relationships_by_type,
            "CONTAINS",
            graph_repo_id,
            file_id,
        )

        edges = []
        if parsed_file.language == "python":
            edges = NodeEdgeExtractor.extract_python_edges(path, graph_repo_id, parsed_file.content)
        elif parsed_file.language in ("javascript", "typescript", "tsx"):
            edges = NodeEdgeExtractor.extract_js_ts_edges(path, graph_repo_id, parsed_file.content)

        if path.endswith(("package.json", "requirements.txt", "go.mod")):
            edges.extend(NodeEdgeExtractor.parse_manifest(path, graph_repo_id, parsed_file.content))

        for edge in edges:
            base_props = {
                "repo": repo,
                "branch": branch,
                "commit_sha": commit_sha,
                "ingest_run_id": ingest_run_id,
            }
            source_props = dict(base_props)
            if edge["from_label"] == "File":
                source_props.update(
                    {
                        "path": path,
                        "language": parsed_file.language,
                    }
                )
            self._queue_graph_node(nodes_by_label, edge["from_label"], edge["from_id"], source_props)

            node_props = dict(base_props)
            if "properties" in edge:
                node_props.update(edge["properties"])
            self._queue_graph_node(nodes_by_label, edge["to_label"], edge["to_id"], node_props)

            self._queue_graph_relationship(
                relationships_by_type,
                edge["rel_type"],
                edge["from_id"],
                edge["to_id"],
            )

        return len(edges)

    def _delete_file_graph(
        self,
        path: str,
        graph_repo_id: str,
        user_id: str | None,
        is_public: bool,
    ) -> None:
        file_id = f"{graph_repo_id}::{path}"
        scoped_file_id = self.neo4j.scoped_id(file_id, user_id, is_public)
        file_prefix = f"{file_id}::"
        self.neo4j.run_query(
            "MATCH (n) "
            "WHERE n.id = $file_id OR n.raw_id = $raw_file_id OR n.raw_id STARTS WITH $file_prefix "
            "DETACH DELETE n",
            {
                "file_id": scoped_file_id,
                "raw_file_id": file_id,
                "file_prefix": file_prefix,
            },
        )

    def _queue_graph_node(
        self,
        nodes_by_label: dict[str, dict[str, dict[str, Any]]],
        label: str,
        raw_id: str,
        properties: dict[str, Any],
    ) -> None:
        nodes = nodes_by_label.setdefault(label, {})
        existing = nodes.get(raw_id)
        if existing:
            existing["properties"].update({k: v for k, v in properties.items() if v is not None})
            return
        nodes[raw_id] = {
            "raw_id": raw_id,
            "properties": {k: v for k, v in properties.items() if v is not None},
        }

    def _queue_graph_relationship(
        self,
        relationships_by_type: dict[str, dict[tuple[str, str], dict[str, Any]]],
        rel_type: str,
        from_raw_id: str,
        to_raw_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        relationships = relationships_by_type.setdefault(rel_type, {})
        relationships[(from_raw_id, to_raw_id)] = {
            "from_raw_id": from_raw_id,
            "to_raw_id": to_raw_id,
            "properties": {k: v for k, v in (properties or {}).items() if v is not None},
        }

    def _chunk_parsed_file(
        self,
        parsed_file,
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        user_id: str | None,
        is_public: bool,
    ) -> list[Chunk]:
        """Route a parsed file to the correct chunker based on source_type, tagging with user_id."""
        if parsed_file.source_type == "code":
            chunks = self.ast_chunker.chunk(
                source=parsed_file.content,
                repo=repo,
                file_path=parsed_file.path,
                language=parsed_file.language,
            )
        else:
            # docs, config → ContentChunker
            chunks = self.content_chunker.chunk(
                text=parsed_file.content,
                repo=repo,
                file_path=parsed_file.path,
                language=parsed_file.language,
                source_type=parsed_file.source_type,
                metadata=parsed_file.metadata,
            )
        
        # Tag every chunk with tenant isolation data
        for c in chunks:
            c.user_id = user_id
            c.is_public = is_public
            c.branch = branch
            c.commit_sha = commit_sha
            c.ingest_run_id = ingest_run_id
        
        return chunks

    def _process_single_file_content(
        self,
        item: dict,
        content: str,
        repo: str,
        user_id: str | None,
        is_public: bool,
        branch: str = "main",
        commit_sha: str | None = None,
        ingest_run_id: str | None = None,
    ) -> dict:
        path = item["path"]

        secrets_redacted = count_secret_matches(content)
        safe_content = redact_text(content) if secrets_redacted else content

        parsed_file = route_file(path, safe_content)
        chunks = self._chunk_parsed_file(parsed_file, repo, branch, commit_sha, ingest_run_id, user_id, is_public)
        file_sha = item.get("file_sha") or item.get("sha")
        if secrets_redacted:
            for chunk in chunks:
                chunk.metadata["secrets_redacted"] = secrets_redacted
                chunk.metadata["security_censored"] = True
        for chunk in chunks:
            chunk.file_sha = file_sha
            chunk.metadata["file_sha"] = file_sha
        parsed_file.metadata["file_sha"] = file_sha

        return {
            "path": path,
            "secrets_redacted": secrets_redacted,
            "parsed_file": parsed_file,
            "chunks": chunks,
        }

    def _redact_github_records(
        self,
        records: list[dict],
        text_fields: tuple[str, ...],
    ) -> tuple[list[dict], dict[str, int]]:
        sanitized_records: list[dict] = []
        records_with_secrets = 0
        secrets_redacted = 0

        for record in records:
            sanitized = dict(record)
            record_secret_count = 0
            for field in text_fields:
                value = sanitized.get(field)
                if not isinstance(value, str) or not value:
                    continue
                field_secret_count = count_secret_matches(value)
                if field_secret_count:
                    sanitized[field] = redact_text(value)
                    record_secret_count += field_secret_count

            if record_secret_count:
                records_with_secrets += 1
                secrets_redacted += record_secret_count
            sanitized_records.append(sanitized)

        return sanitized_records, {
            "records_with_secrets": records_with_secrets,
            "secrets_redacted": secrets_redacted,
        }

    async def _process_files_concurrently(
        self,
        fetched_files: list[tuple[dict, str]],
        repo: str,
        branch: str,
        commit_sha: str | None,
        ingest_run_id: str | None,
        user_id: str | None,
        is_public: bool,
    ) -> list[dict]:
        semaphore = asyncio.Semaphore(max(1, self.file_processing_concurrency))

        async def _run_one(index: int, item: dict, content: str) -> dict:
            async with semaphore:
                result = await asyncio.to_thread(
                    self._process_single_file_content,
                    item,
                    content,
                    repo,
                    user_id,
                    is_public,
                    branch,
                    commit_sha,
                    ingest_run_id,
                )
                result["index"] = index
                return result

        tasks = [
            _run_one(index, item, content)
            for index, (item, content) in enumerate(fetched_files)
        ]
        return await asyncio.gather(*tasks)

    async def _emit_progress(
        self,
        callback: Callable[[str, str, dict | None], Awaitable[None] | None] | None,
        stage: str,
        message: str,
        meta: dict | None = None,
    ) -> None:
        if not callback:
            return

        result = callback(stage, message, meta)
        if inspect.isawaitable(result):
            await result

    async def _register_webhook(self, owner: str, repo_name: str):
        from core.config import settings
        if not settings.github_webhook_secret:
             return
        
        backend_url = getattr(settings, "backend_url", None)
        if not backend_url:
             backend_url = "https://cortex-api.onrender.com"
             
        payload = {
            "name": "web",
            "active": True,
            "events": ["push", "pull_request", "issues"],
            "config": {
                "url": f"{backend_url}/api/v1/webhook/github",
                "content_type": "json",
                "secret": settings.github_webhook_secret
            }
        }
        
        res = await self.github_client.create_webhook(owner, repo_name, payload)
        if res.status_code == 201:
            logger.info(f"Successfully registered webhook for {owner}/{repo_name}")
        elif res.status_code == 422:
            logger.info(f"Webhook already exists or invalid payload for {owner}/{repo_name}: {res.text}")
        else:
            logger.warning(f"Webhook registration returned {res.status_code}: {res.text}")
