"""
Cortex Repository Summarizer — Phase 8.5

Generates an instant architectural snapshot after ingestion by:
1. Running Cypher degree-centrality queries to identify core files/hubs
2. Retrieving the repo's README from Qdrant
3. Feeding both to an LLM for a concise, zero-BS summary

The snapshot is stored on the Repository node in Neo4j.
"""

from core.config import settings
from core.logger import get_logger
from core.tenant import tenant_scoped_id
from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.qdrant_store import VectorStore
from indexing.embedder import CortexEmbedder

logger = get_logger(__name__)


async def generate_repo_snapshot(repo: str, user_id: str | None = None) -> str:
    """
    Generate an instant architectural snapshot for a repository.
    
    Returns the snapshot text, also stores it on the Neo4j Repository node.
    """
    neo4j = Neo4jManager()
    
    # ── 1. Degree centrality: find the most connected files ──────────
    scoped_repo_id = tenant_scoped_id(repo, user_id)

    hub_query = """
    MATCH (f:File {repo: $repo})-[r]-()
    WHERE f.user_id = $user_id OR f.is_public = true
    WITH f, count(r) AS degree
    ORDER BY degree DESC
    LIMIT 10
    RETURN f.path AS path, f.language AS language, degree
    """
    hubs = neo4j.run_query(hub_query, {"repo": repo, "user_id": user_id})
    
    # ── 2. Entry points: files that are imported most ────────────────
    entry_query = """
    MATCH (importer:File)-[:IMPORTS]->(target:File {repo: $repo})
    WHERE (importer.user_id = $user_id OR importer.is_public = true)
      AND (target.user_id = $user_id OR target.is_public = true)
    WITH target, count(importer) AS import_count
    ORDER BY import_count DESC
    LIMIT 5
    RETURN target.path AS path, import_count
    """
    entry_points = neo4j.run_query(entry_query, {"repo": repo, "user_id": user_id})
    
    # ── 3. Dependency count ──────────────────────────────────────────
    dep_query = """
    MATCH (r:Repository {full_name: $repo})-[:DEPENDS_ON]->(d:Dependency)
    WHERE r.user_id = $user_id OR r.is_public = true
    RETURN d.name AS name, d.ecosystem AS ecosystem
    LIMIT 20
    """
    dependencies = neo4j.run_query(dep_query, {"repo": repo, "user_id": user_id})
    
    # ── 4. Basic graph stats ─────────────────────────────────────────
    stats_query = """
    MATCH (n) WHERE (n.repo = $repo OR n.full_name = $repo)
      AND (n.user_id = $user_id OR n.is_public = true)
    RETURN labels(n)[0] AS label, count(n) AS count
    """
    stats = neo4j.run_query(stats_query, {"repo": repo, "user_id": user_id})
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
            filters={"repo": repo, "source_type": "docs"},
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
    context = f"Repository: {repo}\n\n"
    
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
    
    if readme_text:
        context += f"\n## README (excerpt)\n{readme_text}\n"

    # ── 7. Generate snapshot via LLM ─────────────────────────────────
    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=settings.gemini_api_key)
        
        system_prompt = (
            "You are an expert software architect. Generate a concise architectural snapshot "
            "of the repository based on the provided graph metrics and README. "
            "Include: overall purpose, tech stack, core modules/entry points, "
            "heavily coupled components (potential risks), and key dependencies. "
            "Be direct and useful. No fluff. Use bullet points. Max 400 words."
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
    
    # ── 8. Store snapshot on the Repository node ─────────────────────
    try:
        neo4j.run_query(
            "MATCH (r:Repository {id: $repo_id}) SET r.snapshot = $snapshot",
            {"repo_id": scoped_repo_id, "snapshot": snapshot},
        )
        logger.info(f"Stored architectural snapshot for {repo}")
    except Exception as e:
        logger.warning(f"Failed to store snapshot: {e}")
    
    return snapshot
