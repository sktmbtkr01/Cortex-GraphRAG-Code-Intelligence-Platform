"""
Cortex Ingestion Pipeline — Phase 8 (Multi-Tenant).

Flow: GitHub fetch → parse → secret scan → chunk → embed → store (with user_id tagging)
All data is processed in-memory. No raw files are ever written to disk.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from core.config import settings
from core.logger import get_logger
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
        include_issues: bool = True,
        include_prs: bool = True,
        include_commits: bool = True,
        max_commits: int = 500,
        user_id: str | None = None,
        is_public: bool = False,
        progress_cb: Callable[[str, str, dict | None], Awaitable[None] | None] | None = None,
    ) -> dict[str, int]:
        """
        Full ingestion pipeline: fetch → parse → scan → chunk → embed → graph.
        
        All chunks and graph nodes are tagged with user_id for row-level isolation.
        Public repos are additionally flagged with is_public=True so guests can search them.
        """
        logger.info(f"Starting ingestion for {repo} on branch {branch} (user={user_id}, public={is_public})")

        stats = {
            "files_parsed": 0,
            "files_skipped": 0,
            "secrets_found": 0,
            "files_with_secrets": 0,
            "secrets_redacted": 0,
            "files_skipped_for_secrets": 0,
            "chunks_created": 0,
            "graph_edges_created": 0,
        }
        all_chunks: list[Chunk] = []

        try:
            owner, repo_name = repo.split("/")
        except ValueError:
            logger.error(f"Invalid repo format: {repo}. Expected 'owner/repo'.")
            raise ValueError("Repo must be in the format 'owner/repo'")

        try:
            await self.github_client.__aenter__()
            # ── 1. Fetch file tree ────────────────────────────────────
            await self._emit_progress(progress_cb, "fetching_tree", "Fetching repository tree")
            tree = await self.github_client.fetch_file_tree(owner, repo_name, branch)
            await self._emit_progress(
                progress_cb,
                "fetching_files",
                f"Fetched tree with {len(tree)} items",
                {"total": len(tree), "processed": 0},
            )
            
            # Setup base repository node with user_id tagging
            if self.graph_enabled:
                await self._emit_progress(progress_cb, "graph_building", "Initializing repository graph node")
                self.neo4j.merge_tenant_node("Repository", repo, {
                    "full_name": repo, 
                    "owner": owner, 
                    "name": repo_name,
                    "default_branch": branch,
                }, user_id, is_public)

            # ── 2. Filter, fetch, parse, chunk, graph files ───────────
            total_files = len(tree)
            eligible_items: list[dict] = []
            for item in tree:
                path = item["path"]
                size = item.get("size", 0)
                if should_process_file(path, size):
                    eligible_items.append(item)
                else:
                    stats["files_skipped"] += 1

            await self._emit_progress(
                progress_cb,
                "fetching_files",
                f"Fetching {len(eligible_items)} eligible files with concurrency {self.github_fetch_concurrency}",
                {"total": total_files, "eligible": len(eligible_items)},
            )

            fetched_results = await self.github_client.fetch_file_contents_bulk(
                owner,
                repo_name,
                eligible_items,
                concurrency=self.github_fetch_concurrency,
            )

            fetched_ok: list[tuple[dict, str]] = []
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

            await self._emit_progress(
                progress_cb,
                "chunking",
                f"Scanning and chunking {len(fetched_ok)} files with concurrency {self.file_processing_concurrency}",
                {"total": len(fetched_ok)},
            )

            processed_files = await self._process_files_concurrently(
                fetched_ok,
                repo,
                user_id,
                is_public,
            )

            # Maintain deterministic order for downstream embedding mapping
            processed_files.sort(key=lambda r: r["index"])

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
                all_chunks.extend(chunks)

                # Graph Extraction (Static)
                if self.graph_enabled:
                    await self._emit_progress(progress_cb, "graph_building", f"Extracting graph edges for {path}")
                    file_id = f"{repo}::{path}"
                    self.neo4j.merge_tenant_node("File", file_id, {
                        "path": path, "repo": repo, "language": parsed_file.language,
                    }, user_id, is_public)
                    self.neo4j.merge_tenant_relationship("Repository", repo, "File", file_id, "CONTAINS", user_id, is_public)

                    edges = []
                    if parsed_file.language == "python":
                        edges = NodeEdgeExtractor.extract_python_edges(path, repo, parsed_file.content)
                    elif parsed_file.language in ("javascript", "typescript", "tsx"):
                        edges = NodeEdgeExtractor.extract_js_ts_edges(path, repo, parsed_file.content)

                    if path.endswith(("package.json", "requirements.txt", "go.mod")):
                        edges.extend(NodeEdgeExtractor.parse_manifest(path, repo, parsed_file.content))

                    for edge in edges:
                        node_props = {}
                        if "properties" in edge:
                            node_props.update(edge["properties"])
                        self.neo4j.merge_tenant_node(edge["to_label"], edge["to_id"], node_props, user_id, is_public)

                        self.neo4j.merge_tenant_relationship(
                            edge["from_label"], edge["from_id"],
                            edge["to_label"], edge["to_id"],
                            edge["rel_type"],
                            user_id,
                            is_public,
                        )
                    stats["graph_edges_created"] += len(edges)

            # ── 3. Issues ─────────────────────────────────────────────
            if include_issues:
                await self._emit_progress(progress_cb, "issues", "Fetching issues")
                issues = await self.github_client.fetch_issues(owner, repo_name, state="all")
                issues, issue_secret_stats = self._redact_github_records(issues, ("title", "body"))
                stats["files_with_secrets"] += issue_secret_stats["records_with_secrets"]
                stats["secrets_found"] += issue_secret_stats["secrets_redacted"]
                stats["secrets_redacted"] += issue_secret_stats["secrets_redacted"]
                
                if self.graph_enabled:
                    await self._emit_progress(progress_cb, "graph_building", "Building issue graph")
                    await self.git_graph.build_issue_graph(issues, repo, user_id=user_id, is_public=is_public)
                    
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
                        all_chunks.extend(chunks)

            # ── 4. Pull Requests ──────────────────────────────────────
            if include_prs:
                await self._emit_progress(progress_cb, "prs", "Fetching pull requests")
                prs = await self.github_client.fetch_pull_requests(owner, repo_name, state="all")
                prs, pr_secret_stats = self._redact_github_records(prs, ("title", "body"))
                stats["files_with_secrets"] += pr_secret_stats["records_with_secrets"]
                stats["secrets_found"] += pr_secret_stats["secrets_redacted"]
                stats["secrets_redacted"] += pr_secret_stats["secrets_redacted"]
                
                if self.graph_enabled:
                    await self._emit_progress(progress_cb, "graph_building", "Building pull request graph")
                    await self.git_graph.build_pr_graph(prs, repo, user_id=user_id, is_public=is_public)
                    
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
                    all_chunks.extend(chunks)
                    
            # ── 5. Commits ────────────────────────────────────────────
            if include_commits and self.graph_enabled:
                await self._emit_progress(progress_cb, "commits", "Fetching commits")
                # We fetch commits solely for graph history, not for RAG chunking
                commits = await self.github_client.fetch_commits(owner, repo_name, limit=max_commits)
                await self._emit_progress(progress_cb, "graph_building", "Building commit graph")
                await self.git_graph.build_commit_graph(commits, repo, user_id=user_id, is_public=is_public)

            # ── 6. Embed and Upsert (with user_id in payload) ─────────
            if all_chunks:
                logger.info(f"Embedding {len(all_chunks)} chunks locally with FastEmbed...")
                await self._emit_progress(progress_cb, "embedding", f"Embedding {len(all_chunks)} chunks")
                
                texts_to_embed = []
                for c in all_chunks:
                    text = c.text
                    texts_to_embed.append(text)
                
                # Dense vectors
                dense_vectors = await self.embedder.embed_batch(texts_to_embed)
                
                # Sparse vectors
                sparse_vectors = [self.embedder.generate_sparse_vector(t) for t in texts_to_embed]
                
                # Upsert
                logger.info("Upserting vectors to Qdrant...")
                await self._emit_progress(progress_cb, "upserting", "Upserting vectors to Qdrant")
                self.vector_store.ensure_collection()
                self.vector_store.upsert_chunks(
                    chunks=all_chunks,
                    dense_vectors=dense_vectors,
                    sparse_vectors=sparse_vectors,
                )
            else:
                logger.warning("No chunks generated to embed.")

            stats["chunks_created"] = len(all_chunks)

            # Phase 7 Webhook Registration
            try:
                await self._register_webhook(owner, repo_name)
            except Exception as w_err:
                logger.warning(f"Failed to register webhook: {w_err}")

            logger.info(
                f"Ingestion complete for {repo}. "
                f"Parsed: {stats['files_parsed']}, Skipped: {stats['files_skipped']}, "
                f"Secrets redacted: {stats['secrets_redacted']}, Chunks: {stats['chunks_created']}"
            )
            await self.github_client.aclose()
            return stats

        except Exception as e:
            await self.github_client.aclose()
            logger.error(f"Ingestion failed for {repo}: {e}")
            raise

    def _chunk_parsed_file(self, parsed_file, repo: str, user_id: str | None, is_public: bool) -> list[Chunk]:
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
        
        return chunks

    def _process_single_file_content(
        self,
        item: dict,
        content: str,
        repo: str,
        user_id: str | None,
        is_public: bool,
    ) -> dict:
        path = item["path"]

        secrets_redacted = count_secret_matches(content)
        safe_content = redact_text(content) if secrets_redacted else content

        parsed_file = route_file(path, safe_content)
        chunks = self._chunk_parsed_file(parsed_file, repo, user_id, is_public)
        if secrets_redacted:
            for chunk in chunks:
                chunk.metadata["secrets_redacted"] = secrets_redacted
                chunk.metadata["security_censored"] = True

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
