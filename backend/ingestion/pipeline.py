"""
Cortex Ingestion Pipeline — Phase 8 (Multi-Tenant).

Flow: GitHub fetch → parse → secret scan → chunk → embed → store (with user_id tagging)
All data is processed in-memory. No raw files are ever written to disk.
"""

from core.logger import get_logger
from ingestion.github_client import GitHubClient
from ingestion.file_router import should_process_file, route_file
from ingestion.secret_scanner import scan_text
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
        user_id: str | None = None,
        is_public: bool = False,
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
            # ── 1. Fetch file tree ────────────────────────────────────
            tree = await self.github_client.fetch_file_tree(owner, repo_name, branch)
            
            # Setup base repository node with user_id tagging
            if self.graph_enabled:
                self.neo4j.merge_node("Repository", repo, {
                    "full_name": repo, 
                    "owner": owner, 
                    "name": repo_name,
                    "default_branch": branch,
                    "user_id": user_id,
                    "is_public": is_public,
                })

            # ── 2. Filter, fetch, parse, chunk, graph files ───────────
            for item in tree:
                path = item["path"]
                size = item.get("size", 0)
                sha = item["sha"]

                if not should_process_file(path, size):
                    stats["files_skipped"] += 1
                    continue

                # Content is fetched in-memory — no disk writes
                try:
                    content = await self.github_client.fetch_file_content(owner, repo_name, sha)
                except Exception as e:
                    logger.warning(f"Failed to fetch content for {path}: {e}")
                    stats["files_skipped"] += 1
                    continue

                if scan_text(content):
                    logger.warning(f"Secret detected in {path}, skipping.")
                    stats["secrets_found"] += 1
                    stats["files_skipped"] += 1
                    continue

                parsed_file = route_file(path, content)
                stats["files_parsed"] += 1
                
                # Chunking — tag every chunk with user_id
                chunks = self._chunk_parsed_file(parsed_file, repo, user_id, is_public)
                all_chunks.extend(chunks)
                
                # Graph Extraction (Static)
                if self.graph_enabled:
                    file_id = f"{repo}::{path}"
                    self.neo4j.merge_node("File", file_id, {
                        "path": path, "repo": repo, "language": parsed_file.language,
                        "user_id": user_id, "is_public": is_public,
                    })
                    self.neo4j.merge_relationship("Repository", repo, "File", file_id, "CONTAINS")
                    
                    edges = []
                    if parsed_file.language == "python":
                        edges = NodeEdgeExtractor.extract_python_edges(path, repo, parsed_file.content)
                    elif parsed_file.language in ("javascript", "typescript", "tsx"):
                        edges = NodeEdgeExtractor.extract_js_ts_edges(path, repo, parsed_file.content)
                        
                    if path.endswith(("package.json", "requirements.txt", "go.mod")):
                        edges.extend(NodeEdgeExtractor.parse_manifest(path, repo, parsed_file.content))
                        
                    for edge in edges:
                        node_props = {"id": edge["to_id"], "user_id": user_id, "is_public": is_public}
                        if "properties" in edge:
                            node_props.update(edge["properties"])
                        self.neo4j.merge_node(edge["to_label"], edge["to_id"], node_props)
                        
                        self.neo4j.merge_relationship(
                            edge["from_label"], edge["from_id"],
                            edge["to_label"], edge["to_id"],
                            edge["rel_type"]
                        )
                    stats["graph_edges_created"] += len(edges)

            # ── 3. Issues ─────────────────────────────────────────────
            if include_issues:
                issues = await self.github_client.fetch_issues(owner, repo_name, state="all")
                
                if self.graph_enabled:
                    await self.git_graph.build_issue_graph(issues, repo)
                    
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
                prs = await self.github_client.fetch_pull_requests(owner, repo_name, state="all")
                
                if self.graph_enabled:
                    await self.git_graph.build_pr_graph(prs, repo)
                    
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
                # We fetch commits solely for graph history, not for RAG chunking
                commits = await self.github_client.fetch_commits(owner, repo_name, per_page=100)
                await self.git_graph.build_commit_graph(commits, repo)

            # ── 6. Embed and Upsert (with user_id in payload) ─────────
            if all_chunks:
                logger.info(f"Embedding {len(all_chunks)} chunks via Gemini...")
                
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
                f"Secrets: {stats['secrets_found']}, Chunks: {stats['chunks_created']}"
            )
            return stats

        except Exception as e:
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

    async def _register_webhook(self, owner: str, repo_name: str):
        from core.config import settings
        if not settings.github_webhook_secret:
             return
             
        import httpx
        url = f"https://api.github.com/repos/{owner}/{repo_name}/hooks"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": self.github_client.headers.get("Authorization", ""),
            "User-Agent": "Cortex-App"
        }
        
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
        
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 201:
                logger.info(f"Successfully registered webhook for {owner}/{repo_name}")
            elif res.status_code == 422:
                logger.info(f"Webhook already exists or invalid payload for {owner}/{repo_name}: {res.text}")
            else:
                logger.warning(f"Webhook registration returned {res.status_code}: {res.text}")
