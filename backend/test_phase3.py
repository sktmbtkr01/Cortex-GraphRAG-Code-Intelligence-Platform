"""
Phase 3 Verification — Embedder + Qdrant Store end-to-end.
Tests 1-5 and 7 from the tracker. Test 6 (background task) is an API-level test.
"""
import asyncio
import sys

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

from indexing.embedder import CortexEmbedder
from indexing.qdrant_store import VectorStore, generate_chunk_id
from models.schemas import Chunk
from core.config import settings


def divider(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── Build some test chunks ───────────────────────────────────────────

TEST_CHUNKS = [
    Chunk(
        id="", text="def connect_db(url: str) -> object:\n    return create_engine(url)",
        repo="test/cortex-verify", file_path="src/db.py", language="python",
        source_type="code", chunk_type="function",
        function_name="connect_db", signature="def connect_db(url: str) -> object:",
        start_line=1, end_line=2,
    ),
    Chunk(
        id="", text="class AuthManager:\n    def verify_token(self, token):\n        return jwt.decode(token)",
        repo="test/cortex-verify", file_path="src/auth.py", language="python",
        source_type="code", chunk_type="method",
        function_name="verify_token", class_name="AuthManager",
        signature="def verify_token(self, token):",
        start_line=5, end_line=7,
    ),
    Chunk(
        id="", text="## Installation\n\nRun `pip install cortex` to install the package.",
        repo="test/cortex-verify", file_path="README.md", language="markdown",
        source_type="docs", chunk_type="section", section_title="Installation",
    ),
    Chunk(
        id="", text='Issue #42: "Login fails on Safari"\nOpened by alice\nBody: The login button redirects to a blank screen.',
        repo="test/cortex-verify", file_path="issue_42", language="markdown",
        source_type="issue", chunk_type="whole_doc",
        issue_number=42, state="open", labels=["bug", "auth"],
    ),
]


async def main():
    embedder = CortexEmbedder()
    store = VectorStore()

    # ── TEST 1: Embedding dimensions ──────────────────────────────
    divider(f"TEST 1: Embeddings are {settings.embedding_dimensions}-dimensional")
    
    texts = [c.text for c in TEST_CHUNKS]
    dense_vectors = await embedder.embed_batch(texts)
    
    for i, vec in enumerate(dense_vectors):
        print(f"  Chunk {i}: dim={len(vec)}")
        assert len(vec) == settings.embedding_dimensions, \
            f"Expected {settings.embedding_dimensions}, got {len(vec)}"
    print("  PASSED")

    # ── TEST 2: Qdrant collection created ─────────────────────────
    divider("TEST 2: Qdrant collection created successfully")
    
    store.ensure_collection()
    
    info = store.client.get_collection(store.collection_name)
    print(f"  Collection: {store.collection_name}")
    print(f"  Vector size: {info.config.params.vectors.size}")
    print(f"  Distance: {info.config.params.vectors.distance}")
    assert info.config.params.vectors.size == settings.embedding_dimensions
    print("  PASSED")

    # ── TEST 3: Upsert and verify payloads ────────────────────────
    divider("TEST 3: Points have correct payload")
    
    sparse_vectors = [embedder.generate_sparse_vector(t) for t in texts]
    store.upsert_chunks(TEST_CHUNKS, dense_vectors, sparse_vectors)
    
    # Read back a point
    point_id = generate_chunk_id(TEST_CHUNKS[0])
    points = store.client.retrieve(
        collection_name=store.collection_name,
        ids=[point_id],
        with_payload=True,
    )
    
    assert len(points) == 1, "Point not found in Qdrant"
    payload = points[0].payload
    print(f"  repo: {payload.get('repo')}")
    print(f"  file_path: {payload.get('file_path')}")
    print(f"  function_name: {payload.get('function_name')}")
    print(f"  chunk_type: {payload.get('chunk_type')}")
    print(f"  text present: {bool(payload.get('text'))}")
    print(f"  indexed_at: {payload.get('indexed_at')}")
    
    assert payload["repo"] == "test/cortex-verify"
    assert payload["function_name"] == "connect_db"
    assert payload["text"] is not None
    print("  PASSED")

    # ── TEST 4: Re-ingestion overwrites (no duplicates) ───────────
    divider("TEST 4: Re-ingestion overwrites (no duplicates)")
    
    # Count before
    info_before = store.client.get_collection(store.collection_name)
    count_before = info_before.points_count
    print(f"  Points before re-upsert: {count_before}")
    
    # Upsert again (same chunks)
    store.upsert_chunks(TEST_CHUNKS, dense_vectors, sparse_vectors)
    
    info_after = store.client.get_collection(store.collection_name)
    count_after = info_after.points_count
    print(f"  Points after re-upsert: {count_after}")
    
    assert count_after == count_before, f"Duplicates detected! {count_before} -> {count_after}"
    print("  PASSED")

    # ── TEST 5: Delete by repo ────────────────────────────────────
    divider("TEST 5: Delete by repo works")
    
    store.delete_by_repo("test/cortex-verify")
    
    # Allow Qdrant to process deletion
    import time
    time.sleep(2)
    
    info_deleted = store.client.get_collection(store.collection_name)
    count_deleted = info_deleted.points_count
    print(f"  Points after delete: {count_deleted}")
    
    assert count_deleted == 0, f"Expected 0 points after delete, got {count_deleted}"
    print("  PASSED")

    # ── TEST 7: Hybrid search returns results ─────────────────────
    divider("TEST 7: Hybrid search returns results")
    
    # Re-insert for search test
    store.upsert_chunks(TEST_CHUNKS, dense_vectors, sparse_vectors)
    time.sleep(1)
    
    # Search for "database connection"
    query = "How does the database connection work?"
    query_dense = (await embedder.embed_batch([query]))[0]
    query_sparse = embedder.generate_sparse_vector(query)
    
    results = store.search(
        query_dense=query_dense,
        query_sparse=query_sparse,
        filters={"repo": "test/cortex-verify"},
        top_k=5,
    )
    
    print(f"  Results returned: {len(results)}")
    for r in results:
        print(f"    score={r['score']:.4f} | {r['payload'].get('file_path')} | {r['payload'].get('function_name', r['payload'].get('section_title', ''))}")
    
    assert len(results) > 0, "No search results returned"
    print("  PASSED")

    # ── Cleanup ───────────────────────────────────────────────────
    store.delete_by_repo("test/cortex-verify")
    print(f"\n  Cleaned up test data from Qdrant.")

    print(f"\n{'='*60}")
    print("  ALL PHASE 3 TESTS PASSED")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
