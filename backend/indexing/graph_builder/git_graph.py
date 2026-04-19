"""
Cortex Graph Builder — Git Metadata Extraction.
Maps GitHub Issues, PRs, and Commits to the Neo4j Knowledge Graph.
"""

import re
from core.logger import get_logger
from indexing.graph_builder.neo4j_manager import Neo4jManager
from ingestion.github_client import GitHubClient

logger = get_logger(__name__)


class GitGraphBuilder:
    def __init__(self, neo4j_manager: Neo4jManager, github_client: GitHubClient):
        self.db = neo4j_manager
        self.github = github_client

    def _extract_linked_issues(self, text: str) -> list[int]:
        """Looks for 'fixes #42', 'closes #18', etc. in PR bodies."""
        if not text:
            return []
        
        # Regex to match GitHub close keywords
        pattern = re.compile(r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)", re.IGNORECASE)
        matches = pattern.findall(text)
        return [int(m) for m in matches]

    def _merge_contributor(self, user_dict: dict | None) -> str | None:
        """Helper to map a GitHub user to a Contributor node."""
        if not user_dict or "login" not in user_dict:
            return None
        
        login = user_dict["login"]
        self.db.merge_node("Contributor", login, {
            "login": login,
            "type": user_dict.get("type", "User")
        })
        return login

    async def build_issue_graph(self, issues: list[dict], repo: str) -> None:
        """
        Takes raw GitHub API issues and maps them.
        Nodes: :Issue, :Label, :Contributor
        Edges: (Contributor)-[:OPENED]->(Issue), (Issue)-[:LABELED]->(Label)
        """
        for issue in issues:
            if "pull_request" in issue:
                continue  # Skip PRs (handled separately)

            issue_number = issue["number"]
            issue_id = f"{repo}::issue::{issue_number}"
            author_login = self._merge_contributor(issue.get("user"))

            # Merge Issue Node
            self.db.merge_node("Issue", issue_id, {
                "repo": repo,
                "number": issue_number,
                "title": issue.get("title", ""),
                "state": issue.get("state", ""),
                "created_at": issue.get("created_at", ""),
            })

            # Author relationship
            if author_login:
                self.db.merge_relationship(
                    "Contributor", author_login,
                    "Issue", issue_id,
                    "OPENED"
                )

            # Labels relationship
            for label in issue.get("labels", []):
                label_name = label if isinstance(label, str) else label.get("name", "")
                if label_name:
                    label_id = f"{repo}::label::{label_name.lower()}"
                    self.db.merge_node("Label", label_id, {"name": label_name, "repo": repo})
                    self.db.merge_relationship(
                        "Issue", issue_id,
                        "Label", label_id,
                        "LABELED"
                    )

    async def build_pr_graph(self, prs: list[dict], repo: str) -> None:
        """
        Nodes: :PullRequest, :Contributor
        Edges: (Contributor)-[:OPENED]->(PR), (PR)-[:MODIFIES]->(File), (PR)-[:CLOSES]->(Issue)
        """
        owner, repo_name = repo.split('/')
        
        for pr in prs:
            pr_number = pr["number"]
            pr_id = f"{repo}::pr::{pr_number}"
            author_login = self._merge_contributor(pr.get("user"))

            body = pr.get("body") or ""
            
            # Merge PR Node
            self.db.merge_node("PullRequest", pr_id, {
                "repo": repo,
                "number": pr_number,
                "title": pr.get("title", ""),
                "state": pr.get("state", ""),
                "created_at": pr.get("created_at", ""),
                "merged_at": pr.get("merged_at"),
            })

            # Author
            if author_login:
                self.db.merge_relationship(
                    "Contributor", author_login,
                    "PullRequest", pr_id,
                    "OPENED"
                )

            # Extract linked issues
            linked_issues = self._extract_linked_issues(body)
            for iss_num in linked_issues:
                iss_id = f"{repo}::issue::{iss_num}"
                self.db.merge_relationship(
                    "PullRequest", pr_id,
                    "Issue", iss_id,
                    "CLOSES"
                )

            # Touched files (Fetch async, handled internally)
            try:
                pr_files = await self.github.fetch_pr_files(owner, repo_name, pr_number)
                for f in pr_files:
                    path = f.get("filename")
                    if path:
                        file_id = f"{repo}::{path}"
                        self.db.merge_node("File", file_id, {"path": path, "repo": repo})
                        self.db.merge_relationship(
                            "PullRequest", pr_id,
                            "File", file_id,
                            "MODIFIES",
                            {"status": f.get("status")}
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch files for PR #{pr_number}: {e}")

    async def build_commit_graph(self, commits: list[dict], repo: str) -> None:
        """
        Nodes: :Commit, :File, :Contributor
        Edges: (Contributor)-[:AUTHORED]->(Commit), (Commit)-[:TOUCHES]->(File)
        """
        for commit_obj in commits:
            sha = commit_obj["sha"]
            commit_id = f"{repo}::commit::{sha}"
            
            commit_data = commit_obj.get("commit", {})
            author_obj = commit_obj.get("author")
            
            # Use 'author' if exists (GitHub user), otherwise fallback to git name
            author_login = self._merge_contributor(author_obj)
            author_name = commit_data.get("author", {}).get("name", "Unknown")

            self.db.merge_node("Commit", commit_id, {
                "repo": repo,
                "sha": sha,
                "message": commit_data.get("message", "")[:200], # Trucate long messages
                "date": commit_data.get("author", {}).get("date", "")
            })

            if author_login:
                self.db.merge_relationship(
                    "Contributor", author_login,
                    "Commit", commit_id,
                    "AUTHORED"
                )

            # GitHub API files struct if fetched via `GET /repos/{o}/{r}/commits/{sha}`
            # (Note: Standard commits listing doesn't include files natively, must fetch individually,
            # but for graph building we use it if present, otherwise skip).
            for f in commit_obj.get("files", []):
                path = f.get("filename")
                if path:
                    file_id = f"{repo}::{path}"
                    self.db.merge_node("File", file_id, {"path": path, "repo": repo})
                    self.db.merge_relationship(
                        "Commit", commit_id,
                        "File", file_id,
                        "TOUCHES",
                        {"status": f.get("status")}
                    )
