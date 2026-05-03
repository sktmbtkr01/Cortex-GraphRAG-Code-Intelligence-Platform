import hmac
import hashlib
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, status
from core.config import settings
from core.logger import get_logger

from ingestion.github_client import GitHubClient
from ingestion.file_router import should_process_file, route_file
from ingestion.secret_scanner import count_secret_matches, redact_text
from indexing.embedder import CortexEmbedder
from indexing.qdrant_store import VectorStore
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.graph_builder.static_analyzer import NodeEdgeExtractor
from indexing.graph_builder.git_graph import GitGraphBuilder
from chunkers.ast_chunker import ASTChunker
from chunkers.prose_chunker import ContentChunker
from core.tenant import tenant_scoped_id

logger = get_logger(__name__)

router = APIRouter()


@dataclass(frozen=True)
class WebhookTarget:
    user_id: str | None
    is_public: bool = False


def resolve_webhook_targets(repo: str, payload: dict | None = None) -> list[WebhookTarget]:
    """
    Return tenant targets for a webhook event.

    Webhooks do not currently carry a Cortex user_id or installation mapping, so
    mutating index state would risk updating the wrong tenant. Phase 6 keeps this
    conservative until a real repo -> tenant ownership mapping exists.
    """
    return []


def redact_webhook_record(record: dict, fields: tuple[str, ...]) -> dict:
    sanitized = dict(record)
    for field in fields:
        value = sanitized.get(field)
        if isinstance(value, str) and count_secret_matches(value):
            sanitized[field] = redact_text(value)
    return sanitized


def verify_signature(payload: bytes, signature: str | None) -> bool:
    if not settings.github_webhook_secret:
        return True # If no secret configured, accept all (mostly for dev)
    if not signature:
        return False
        
    expected_mac = hmac.new(
        settings.github_webhook_secret.encode(),
        msg=payload,
        digestmod=hashlib.sha256
    )
    expected_signature = "sha256=" + expected_mac.hexdigest()
    return hmac.compare_digest(expected_signature, signature)

def delete_file_from_index(repo: str, file_path: str, target: WebhookTarget):
    try:
        vs = VectorStore()
        # Delete from qdrant
        vs.ensure_collection()
        # We need to delete points matching the repo and file_path
        # Qdrant supports delete by filter
        must_conditions = [
            {"key": "repo", "match": {"value": repo}},
            {"key": "file_path", "match": {"value": file_path}},
        ]
        if target.user_id:
            must_conditions.append({"key": "user_id", "match": {"value": target.user_id}})
        else:
            must_conditions.append({"key": "is_public", "match": {"value": target.is_public}})

        vs.client.delete(
            collection_name=vs.collection_name,
            points_selector={"filter": {"must": must_conditions}}
        )
        
        # Delete from Neo4j
        neo4j = Neo4jManager()
        file_id = f"{repo}::{file_path}"
        # Delete file node and its direct edges
        neo4j.run_query(
            "MATCH (f:File {id: $fid}) "
            "WHERE ($user_id IS NOT NULL AND f.user_id = $user_id) "
            "OR ($user_id IS NULL AND f.is_public = $is_public) "
            "DETACH DELETE f",
            {
                "fid": tenant_scoped_id(file_id, target.user_id, target.is_public),
                "user_id": target.user_id,
                "is_public": target.is_public,
            },
        )
    except Exception as e:
        logger.error(f"Failed to delete file {file_path} from {repo}: {e}")

async def process_added_modified_file(
    repo: str,
    owner: str,
    repo_name: str,
    file_path: str,
    sha: str,
    target: WebhookTarget,
    branch: str = "main",
):
    try:
        async with GitHubClient() as github:
            content = await github.fetch_file_content(owner, repo_name, sha)
        secrets_redacted = count_secret_matches(content)
        if secrets_redacted:
            logger.warning(f"Secret material detected and redacted in webhook update for {repo}/{file_path}.")
            content = redact_text(content)
        parsed = route_file(file_path, content)
        
        all_chunks = []
        if parsed.source_type == "code":
            chunker = ASTChunker()
            all_chunks = chunker.chunk(parsed.content, repo, parsed.path, parsed.language)
        else:
            chunker = ContentChunker()
            all_chunks = chunker.chunk(parsed.content, repo, parsed.path, parsed.language, parsed.source_type, parsed.metadata)
            
        if all_chunks:
            for chunk in all_chunks:
                chunk.user_id = target.user_id
                chunk.is_public = target.is_public
                if secrets_redacted:
                    chunk.metadata["secrets_redacted"] = secrets_redacted
                    chunk.metadata["security_censored"] = True

            embedder = CortexEmbedder()
            texts = [c.text for c in all_chunks]
            dense_vectors = await embedder.embed_batch(texts)
            sparse_vectors = [embedder.generate_sparse_vector(t) for t in texts]
            
            vs = VectorStore()
            vs.ensure_collection()
            vs.upsert_chunks(all_chunks, dense_vectors, sparse_vectors)
            
        # Update Neo4j Graph
        try:
            neo4j = Neo4jManager()
            file_id = f"{repo}::{file_path}"
            neo4j.merge_tenant_node(
                "Repository",
                repo,
                {"full_name": repo, "repo": repo, "is_private": not target.is_public},
                target.user_id,
                target.is_public,
            )
            neo4j.merge_tenant_node(
                "File",
                file_id,
                {"path": file_path, "repo": repo, "language": parsed.language},
                target.user_id,
                target.is_public,
            )
            neo4j.merge_tenant_relationship(
                "Repository",
                repo,
                "File",
                file_id,
                "CONTAINS",
                target.user_id,
                target.is_public,
            )
            
            edges = []
            if parsed.language == "python":
                edges = NodeEdgeExtractor.extract_python_edges(file_path, repo, parsed.content)
            elif parsed.language in ("javascript", "typescript", "tsx"):
                edges = NodeEdgeExtractor.extract_js_ts_edges(file_path, repo, parsed.content)
                
            for edge in edges:
                 node_props = {}
                 if "properties" in edge:
                     node_props.update(edge["properties"])
                 neo4j.merge_tenant_node(edge["to_label"], edge["to_id"], node_props, target.user_id, target.is_public)
                 neo4j.merge_tenant_relationship(
                     edge["from_label"], edge["from_id"],
                     edge["to_label"], edge["to_id"],
                     edge["rel_type"],
                     target.user_id,
                     target.is_public,
                 )
        except Exception as graph_err:
             logger.warning(f"Graph update failed for {file_path}: {graph_err}")
             
    except Exception as e:
        logger.error(f"Failed to process modified file {file_path} in {repo}: {e}")

async def handle_push_event(payload: dict):
    repo_obj = payload.get("repository", {})
    repo = repo_obj.get("full_name")
    owner = repo_obj.get("owner", {}).get("login")
    repo_name = repo_obj.get("name")
    
    if not repo or not owner or not repo_name:
        return

    targets = resolve_webhook_targets(repo, payload)
    if not targets:
        logger.info("Skipping push webhook for %s because no Cortex tenant mapping exists.", repo)
        return
        
    branch = payload.get("ref", "").split("/")[-1]
    
    commits = payload.get("commits", [])
    added = []
    modified = []
    removed = []
    
    for c in commits:
        added.extend(c.get("added", []))
        modified.extend(c.get("modified", []))
        removed.extend(c.get("removed", []))
        
    # Deduplicate
    removed = list(set(removed))
    upserts = list(set(added + modified))
    
    # Process Removals
    for path in removed:
        for target in targets:
            delete_file_from_index(repo, path, target)
        
    # Process Upserts
    # Note: On a webhook, the sha for a file isn't directly given in the commit block unless we fetch the tree.
    # We can just fetch the file content from the branch directly.
    for path in upserts:
        if should_process_file(path, 10): # dummy size, not known from webhook push securely
             # fetch directly from branch
             for target in targets:
                 await process_added_modified_file(repo, owner, repo_name, path, branch, target, branch)


async def handle_pr_event(payload: dict):
    # E.g. re-index PR. To keep simple, we can just defer to pulling the PR directly
    from ingestion.github_client import GitHubClient
    from ingestion.parsers.pr_parser import parse as parse_pr
    
    repo_obj = payload.get("repository", {})
    repo = repo_obj.get("full_name")
    if not repo: return
    pr_data = payload.get("pull_request")
    targets = resolve_webhook_targets(repo, payload)
    if not targets:
        logger.info("Skipping pull_request webhook for %s because no Cortex tenant mapping exists.", repo)
        return
    
    # Re-indexing the PR
    if pr_data:
        pr_data = redact_webhook_record(pr_data, ("title", "body"))
        try:
             # Basic update in Neo4j
             neo4j = Neo4jManager()
             if neo4j:
                 async with GitHubClient() as github:
                     git_graph = GitGraphBuilder(neo4j, github)
                     for target in targets:
                         await git_graph.build_pr_graph(
                             [pr_data],
                             repo,
                             user_id=target.user_id,
                             is_public=target.is_public,
                         )
                 
             # We could also re-embed the PR content into Qdrant if text changed
        except Exception as e:
             logger.error(f"PR event handling failed: {e}")


async def handle_issue_event(payload: dict):
    repo_obj = payload.get("repository", {})
    repo = repo_obj.get("full_name")
    if not repo: return
    issue_data = payload.get("issue")
    targets = resolve_webhook_targets(repo, payload)
    if not targets:
        logger.info("Skipping issues webhook for %s because no Cortex tenant mapping exists.", repo)
        return
    
    if issue_data:
         issue_data = redact_webhook_record(issue_data, ("title", "body"))
         try:
             neo4j = Neo4jManager()
             if neo4j:
                  from ingestion.github_client import GitHubClient
                  async with GitHubClient() as github:
                      git_graph = GitGraphBuilder(neo4j, github)
                      for target in targets:
                          await git_graph.build_issue_graph(
                              [issue_data],
                              repo,
                              user_id=target.user_id,
                              is_public=target.is_public,
                          )
         except Exception as e:
              logger.error(f"Issue event handling failed: {e}")


@router.post("/webhook/github", status_code=200)
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    # Read payload
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    
    if not verify_signature(payload, signature):
        logger.warning("Invalid webhook signature received.")
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    event = request.headers.get("X-GitHub-Event")
    data = await request.json()
    
    if event == "push":
        background_tasks.add_task(handle_push_event, data)
    elif event == "pull_request":
        background_tasks.add_task(handle_pr_event, data)
    elif event == "issues":
        background_tasks.add_task(handle_issue_event, data)
    else:
        logger.info(f"Ignoring unhandled webhook event: {event}")
        
    return {"status": "accepted"}
