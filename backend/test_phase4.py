"""
Phase 4 Verification — Neo4j Knowledge Graph end-to-end.
"""
import sys
import asyncio

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

from indexing.graph_builder.neo4j_manager import Neo4jManager
from indexing.graph_builder.static_analyzer import NodeEdgeExtractor
from indexing.graph_builder.git_graph import GitGraphBuilder

def divider(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


TEST_PYTHON_FILE = """
import os
import requests
from .utils import helper

class BaseClient:
    pass

class GitHubClient(BaseClient):
    def fetch_repo(self):
        helper()
        return True
"""

TEST_PACKAGE_JSON = """
{
  "dependencies": {
    "react": "^18.2.0"
  }
}
"""

TEST_ISSUES = [
    {
        "number": 1,
        "title": "Bug in API",
        "state": "open",
        "user": {"login": "alice", "type": "User"},
        "labels": ["bug", "urgent"]
    }
]

TEST_PRS = [
    {
        "number": 2,
        "title": "Fix bug in API",
        "state": "merged",
        "user": {"login": "bob", "type": "User"},
        "body": "This closes #1 entirely."
    }
]

class MockGitHubClient:
    async def fetch_pr_files(self, owner, repo, pr_number):
        return [{"filename": "src/api.py", "status": "modified"}]


async def main():
    try:
        neo4j = Neo4jManager()
        neo4j.setup_constraints()
    except Exception as e:
        print(f"Skipping Phase 4 tests because Neo4j is unreachable: {e}")
        return

    # Clean test DB safely
    try:
        neo4j.run_query("MATCH (n) WHERE n.repo = 'test/neo4j' DETACH DELETE n")
        neo4j.run_query("MATCH (n:Contributor) WHERE n.login IN ['alice', 'bob'] DETACH DELETE n")
        neo4j.run_query("MATCH (n:Dependency) WHERE n.id CONTAINS 'react' DETACH DELETE n")
        neo4j.run_query("MATCH (n:Module) WHERE n.id CONTAINS 'os' OR n.id CONTAINS 'requests' DETACH DELETE n")
    except Exception:
        pass

    # ── TEST 1: AST Static Extraction ──────────────────────────────
    divider("TEST 1: Python AST static graph generation")
    
    repo = "test/neo4j"
    file_path = "src/client.py"
    file_id = f"{repo}::{file_path}"
    
    neo4j.merge_node("File", file_id, {"path": file_path, "repo": repo})
    
    edges = NodeEdgeExtractor.extract_python_edges(file_path, repo, TEST_PYTHON_FILE)
    
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

    # Verify
    imports = neo4j.run_query("""
        MATCH (f:File {id: $fid})-[r:IMPORTS]->(t) 
        RETURN t.id as tgt, r.type as type 
        ORDER BY t.id
    """, {"fid": file_id})
    
    print(f"  Imports extracted: {len(imports)}")
    assert len(imports) == 3
    print("  PASSED")

    # ── TEST 2: Dependency Parsing ─────────────────────────────────
    divider("TEST 2: package.json dependency extraction")
    
    neo4j.merge_node("Repository", repo, {"id": repo})
    deps = NodeEdgeExtractor.parse_manifest("package.json", repo, TEST_PACKAGE_JSON)
    for edge in deps:
        node_props = {"id": edge["to_id"]}
        if "properties" in edge:
            node_props.update(edge["properties"])
        neo4j.merge_node(edge["to_label"], edge["to_id"], node_props)
        neo4j.merge_relationship("Repository", repo, edge["to_label"], edge["to_id"], edge["rel_type"])

    # Because repo node from_id is directly passed, let's just make sure relationship exists
    res = neo4j.run_query("MATCH (:Repository {id: $r})-[rel:DEPENDS_ON]->(d:Dependency) RETURN d.name as name", {"r": repo})
    print(f"  Dependencies found: {[r['name'] for r in res]}")
    assert len(res) == 1 and res[0]["name"] == "react"
    print("  PASSED")
    
    # ── TEST 3: Git Issues and Contributors ────────────────────────
    divider("TEST 3: GitHub issues mapped to contributors and labels")
    
    mock_gh = MockGitHubClient()
    git_graph = GitGraphBuilder(neo4j, mock_gh)
    
    await git_graph.build_issue_graph(TEST_ISSUES, repo)
    
    issue_node = neo4j.run_query("MATCH (i:Issue {number: 1, repo: $r}) RETURN i.title as title", {"r": repo})
    print(f"  Issue title: {issue_node[0]['title']}")
    
    author = neo4j.run_query("MATCH (c:Contributor)-[:OPENED]->(i:Issue {number: 1, repo: $r}) RETURN c.login as login", {"r": repo})
    print(f"  Author login: {author[0]['login']}")
    assert author[0]['login'] == "alice"
    print("  PASSED")

    # ── TEST 4: PR tracking and automated closures ─────────────────
    divider("TEST 4: PRs track file modifications and closes issues")
    
    await git_graph.build_pr_graph(TEST_PRS, "test/neo4j")
    
    closed = neo4j.run_query("MATCH (p:PullRequest {number: 2, repo: $r})-[:CLOSES]->(i:Issue) RETURN i.number as num", {"r": repo})
    print(f"  PR 2 closes Issue #{closed[0]['num']}")
    assert closed[0]["num"] == 1
    
    modified = neo4j.run_query("MATCH (p:PullRequest {number: 2, repo: $r})-[:MODIFIES]->(f:File) RETURN f.path as path", {"r": repo})
    print(f"  PR 2 modifies: {modified[0]['path']}")
    assert modified[0]["path"] == "src/api.py"
    print("  PASSED")


    # ── Cleanup ───────────────────────────────────────────────────
    neo4j.run_query("MATCH (n) WHERE n.repo = 'test/neo4j' DETACH DELETE n")
    neo4j.run_query("MATCH (n:Contributor) WHERE n.login IN ['alice', 'bob'] DETACH DELETE n")
    neo4j.run_query("MATCH (n:Dependency) WHERE n.id CONTAINS 'react' DETACH DELETE n")
    neo4j.run_query("MATCH (n:Module) WHERE n.id CONTAINS 'os' OR n.id CONTAINS 'requests' DETACH DELETE n")
    print("\n  Cleaned up Neo4j test data.")

    print(f"\n{'='*60}")
    print("  ALL PHASE 4 TESTS PASSED")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
