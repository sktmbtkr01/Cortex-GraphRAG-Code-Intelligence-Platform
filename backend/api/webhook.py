import hmac
import hashlib
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, status
from core.config import settings
from core.logger import get_logger

from ingestion.github_client import GitHubClient
from ingestion.file_router import should_process_file, route_file
from indexing.embedder import CortexEmbedder
from indexing.qdrant_store import VectorStore
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.graph_builder.static_analyzer import NodeEdgeExtractor
from indexing.graph_builder.git_graph import GitGraphBuilder
from chunkers.ast_chunker import ASTChunker
from chunkers.prose_chunker import ContentChunker

logger = get_logger(__name__)

router = APIRouter()

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

def delete_file_from_index(repo: str, file_path: str):
    try:
        vs = VectorStore()
        # Delete from qdrant
        vs.ensure_collection()
        # We need to delete points matching the repo and file_path
        # Qdrant supports delete by filter
        vs.client.delete(
            collection_name=vs.collection_name,
            points_selector={"filter": {"must": [
                {"key": "repo", "match": {"value": repo}},
                {"key": "file_path", "match": {"value": file_path}}
            ]}}
        )
        
        # Delete from Neo4j
        neo4j = Neo4jManager()
        file_id = f"{repo}::{file_path}"
        # Delete file node and its direct edges
        neo4j.run_query("MATCH (f:File {id: $fid}) DETACH DELETE f", {"fid": file_id})
    except Exception as e:
        logger.error(f"Failed to delete file {file_path} from {repo}: {e}")

async def process_added_modified_file(repo: str, owner: str, repo_name: str, file_path: str, sha: str, branch: str = "main"):
    try:
        github = GitHubClient()
        content = await github.fetch_file_content(owner, repo_name, sha)
        parsed = route_file(file_path, content)
        
        all_chunks = []
        if parsed.source_type == "code":
            chunker = ASTChunker()
            all_chunks = chunker.chunk(parsed.content, repo, parsed.path, parsed.language)
        else:
            chunker = ContentChunker()
            all_chunks = chunker.chunk(parsed.content, repo, parsed.path, parsed.language, parsed.source_type, parsed.metadata)
            
        if all_chunks:
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
            neo4j.merge_node("File", file_id, {"path": file_path, "repo": repo, "language": parsed.language})
            neo4j.merge_relationship("Repository", repo, "File", file_id, "CONTAINS")
            
            edges = []
            if parsed.language == "python":
                edges = NodeEdgeExtractor.extract_python_edges(file_path, repo, parsed.content)
            elif parsed.language in ("javascript", "typescript", "tsx"):
                edges = NodeEdgeExtractor.extract_js_ts_edges(file_path, repo, parsed.content)
                
            for edge in edges:
                 node_props = {"id": edge["to_id"]}
                 if "properties" in edge:
                     node_props.update(edge["properties"])
                 neo4j.merge_node(edge["to_label"], edge["to_id"], node_props)
                 neo4j.merge_relationship(
                     edge["from_label"], edge["from_id"],
                     edge["to_label"], edge["to_id"],
                     edge["rel_type"]
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
        delete_file_from_index(repo, path)
        
    # Process Upserts
    # Note: On a webhook, the sha for a file isn't directly given in the commit block unless we fetch the tree.
    # We can just fetch the file content from the branch directly.
    for path in upserts:
        if should_process_file(path, 10): # dummy size, not known from webhook push securely
             # fetch directly from branch
             await process_added_modified_file(repo, owner, repo_name, path, branch, branch)


async def handle_pr_event(payload: dict):
    # E.g. re-index PR. To keep simple, we can just defer to pulling the PR directly
    from ingestion.github_client import GitHubClient
    from ingestion.parsers.pr_parser import parse as parse_pr
    
    repo_obj = payload.get("repository", {})
    repo = repo_obj.get("full_name")
    if not repo: return
    action = payload.get("action")
    pr_data = payload.get("pull_request")
    
    # Re-indexing the PR
    if pr_data:
        try:
             # Basic update in Neo4j
             neo4j = Neo4jManager()
             if neo4j:
                 github = GitHubClient()
                 git_graph = GitGraphBuilder(neo4j, github)
                 await git_graph.build_pr_graph([pr_data], repo)
                 
             # We could also re-embed the PR content into Qdrant if text changed
        except Exception as e:
             logger.error(f"PR event handling failed: {e}")


async def handle_issue_event(payload: dict):
    repo_obj = payload.get("repository", {})
    repo = repo_obj.get("full_name")
    if not repo: return
    issue_data = payload.get("issue")
    
    if issue_data:
         try:
             neo4j = Neo4jManager()
             if neo4j:
                  from ingestion.github_client import GitHubClient
                  github = GitHubClient()
                  git_graph = GitGraphBuilder(neo4j, github)
                  await git_graph.build_issue_graph([issue_data], repo)
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
