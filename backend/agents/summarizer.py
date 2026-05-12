"""
Cortex Repository Summarizer — Phase 8.5

Generates an instant architectural snapshot after ingestion by:
1. Running Cypher degree-centrality queries to identify core files/hubs
2. Retrieving the repo's README from Qdrant
3. Feeding both to an LLM for a concise, zero-BS summary

The snapshot is stored separately from graph visualization metadata.
"""

from core.config import settings
from core.logger import get_logger
from core.tenant import tenant_scoped_id
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.qdrant_store import VectorStore
from indexing.embedder import CortexEmbedder

logger = get_logger(__name__)


async def generate_repo_snapshot(repo: str, user_id: str | None = None, branch: str = "main") -> str:
    """
    Generate an instant architectural snapshot for a repository.
    
    Returns the snapshot text, also stores it in Neo4j outside Repository node metadata.
    """
    try:
        neo4j = Neo4jManager()
    except Exception as e:
        logger.warning(f"Snapshot graph unavailable for {repo}: {e}")
        return (
            f"Architecture snapshot unavailable for {repo} @ {branch} because Neo4j "
            "could not be reached during ingestion. The vector index may still be usable."
        )
    
    # ── 1. Degree centrality: find the most connected files ──────────
    repo_branch_id = f"{repo}::{branch}"
    scoped_repo_id = tenant_scoped_id(repo_branch_id, user_id)

    hub_query = """
    MATCH (f:File)-[r]-()
    WHERE f.repo = $repo
      AND coalesce(f.branch, 'main') = $branch
      AND (f.user_id = $user_id OR f.is_public = true)
    WITH f, count(r) AS degree
    ORDER BY degree DESC
    LIMIT 10
    RETURN f.path AS path, f.language AS language, degree
    """
    try:
        hubs = neo4j.run_query(hub_query, {"repo": repo, "branch": branch, "user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to collect snapshot hub files: {e}")
        hubs = []
    
    # ── 2. Entry points: files that are imported most ────────────────
    entry_query = """
    MATCH (importer:File)-[:IMPORTS]->(target:File)
    WHERE (importer.user_id = $user_id OR importer.is_public = true)
      AND (target.user_id = $user_id OR target.is_public = true)
      AND coalesce(importer.branch, 'main') = $branch
      AND target.repo = $repo
      AND coalesce(target.branch, 'main') = $branch
    WITH target, count(importer) AS import_count
    ORDER BY import_count DESC
    LIMIT 5
    RETURN target.path AS path, import_count
    """
    try:
        entry_points = neo4j.run_query(entry_query, {"repo": repo, "branch": branch, "user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to collect snapshot entry points: {e}")
        entry_points = []
    
    # ── 3. Dependency count ──────────────────────────────────────────
    dep_query = """
    MATCH (r:Repository)-[:DEPENDS_ON]->(d:Dependency)
    WHERE r.full_name = $repo
      AND coalesce(r.branch, r.default_branch, 'main') = $branch
      AND (r.user_id = $user_id OR r.is_public = true)
    RETURN d.name AS name, d.ecosystem AS ecosystem
    LIMIT 20
    """
    try:
        dependencies = neo4j.run_query(dep_query, {"repo": repo, "branch": branch, "user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to collect snapshot dependencies: {e}")
        dependencies = []
    
    # ── 4. Basic graph stats ─────────────────────────────────────────
    stats_query = """
    MATCH (n) WHERE (n.repo = $repo OR n.full_name = $repo)
      AND (n.user_id = $user_id OR n.is_public = true)
      AND coalesce(n.branch, 'main') = $branch
    RETURN labels(n)[0] AS label, count(n) AS count
    """
    try:
        stats = neo4j.run_query(stats_query, {"repo": repo, "branch": branch, "user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to collect snapshot stats: {e}")
        stats = []
    stats_dict = {s["label"]: s["count"] for s in stats if s["label"]}
    
    # ── 5. Find README content from Qdrant ───────────────────────────
    readme_text = ""
    try:
        vs = VectorStore()
        embedder = CortexEmbedder()
        dense = await embedder.embed_batch(["project overview README"])
        sparse = embedder.generate_sparse_vector("project overview README")
        vs.ensure_collection()
        hits = vs.search(
            query_dense=dense[0],
            query_sparse=sparse,
            filters={"repo": repo, "branch": branch, "source_type": "docs"},
            top_k=3,
            user_id=user_id,
        )
        for h in hits:
            p = h.get("payload", {})
            if "readme" in p.get("file_path", "").lower():
                readme_text = p.get("text", "")[:2000]
                break
        if not readme_text and hits:
            readme_text = hits[0].get("payload", {}).get("text", "")[:1500]
    except Exception as e:
        logger.warning(f"Failed to fetch README for snapshot: {e}")
    
    # ── 6. Build context for the LLM ────────────────────────────────
    context = f"Repository: {repo}\nBranch: {branch}\n\n"

    if readme_text:
        context += f"## README / Project Description (primary orientation source)\n{readme_text}\n"

    context += "## Graph Statistics\n"
    for label, count in stats_dict.items():
        context += f"- {label}: {count}\n"
    
    context += "\n## Core Files (by connection count)\n"
    for h in hubs:
        context += f"- {h['path']} ({h.get('language', '?')}) — {h['degree']} connections\n"
    
    context += "\n## Top Entry Points (most imported files)\n"
    for ep in entry_points:
        context += f"- {ep['path']} — imported by {ep['import_count']} files\n"
    
    context += "\n## External Dependencies\n"
    for d in dependencies:
        context += f"- {d['name']} ({d.get('ecosystem', 'unknown')})\n"

    # ── 7. Generate snapshot via LLM ─────────────────────────────────
    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=settings.gemini_api_key)
        
        system_prompt = (
            "You are Cortex's architecture snapshot writer. Create a repo orientation brief, "
            "not a health review and not a security audit. Rely first on the README/project "
            "description when it is present, then use graph statistics to ground the repo's "
            "shape. Include these Markdown sections: 1. What This Project Is, 2. Tech Stack, "
            "3. Global Brain Stats, 4. Core Files And Entry Points, 5. Key Dependencies, "
            "6. How To Read This Repo First. Keep it concise, descriptive, and useful. "
            "Mention uncertainty when the README or graph evidence is thin. Do not make risk "
            "or vulnerability claims here; save review language for the health check. Max 450 words."
        )
        
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=context,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            ),
        )
        snapshot = response.text
    except Exception as e:
        logger.error(f"Snapshot generation failed: {e}")
        # Fallback: return the raw metrics
        snapshot = f"**Auto-generated snapshot (raw metrics)**\n\n{context}"
    
    # ── 8. Store snapshot outside Repository graph metadata ──────────
    try:
        snapshot_id = f"{repo_branch_id}::snapshot"
        scoped_snapshot_id = tenant_scoped_id(snapshot_id, user_id)
        neo4j.run_query(
            "MERGE (s:Snapshot {id: $snapshot_id}) "
            "SET s.raw_id = $raw_id, s.repo = $repo, s.branch = $branch, "
            "s.user_id = $user_id, s.snapshot = $snapshot, s.updated_at = datetime() "
            "WITH s "
            "MATCH (r:Repository {id: $repo_id}) "
            "REMOVE r.snapshot "
            "RETURN s.id AS id",
            {
                "snapshot_id": scoped_snapshot_id,
                "raw_id": snapshot_id,
                "repo": repo,
                "branch": branch,
                "user_id": user_id,
                "snapshot": snapshot,
                "repo_id": scoped_repo_id,
            },
        )
        logger.info(f"Stored architectural snapshot for {repo}")
    except Exception as e:
        logger.warning(f"Failed to store snapshot: {e}")
    
    return snapshot
