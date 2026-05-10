"""
Cortex Graph Builder - Git Metadata Extraction.
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

        pattern = re.compile(
            r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)",
            re.IGNORECASE,
        )
        matches = pattern.findall(text)
        return [int(m) for m in matches]

    def _branch_repo_id(self, repo: str, branch: str) -> str:
        return f"{repo}::{branch}"

    def _merge_contributor(
        self,
        user_dict: dict | None,
        repo: str,
        branch: str,
        user_id: str | None,
        is_public: bool,
    ) -> str | None:
        """Map a GitHub user to a tenant-scoped Contributor node."""
        if not user_dict or "login" not in user_dict:
            return None

        login = user_dict["login"]
        graph_repo_id = self._branch_repo_id(repo, branch)
        contributor_id = f"{graph_repo_id}::contributor::{login}"
        self.db.merge_tenant_node(
            "Contributor",
            contributor_id,
            {
                "login": login,
                "name": login,
                "repo": repo,
                "branch": branch,
                "type": user_dict.get("type", "User"),
            },
            user_id,
            is_public,
        )
        return contributor_id

    async def build_issue_graph(
        self,
        issues: list[dict],
        repo: str,
        branch: str = "main",
        user_id: str | None = None,
        is_public: bool = False,
    ) -> None:
        """
        Takes raw GitHub API issues and maps them.
        Nodes: :Issue, :Label, :Contributor
        Edges: (Contributor)-[:OPENED]->(Issue), (Issue)-[:LABELED]->(Label)
        """
        graph_repo_id = self._branch_repo_id(repo, branch)
        for issue in issues:
            if "pull_request" in issue:
                continue

            issue_number = issue["number"]
            issue_id = f"{graph_repo_id}::issue::{issue_number}"
            author_id = self._merge_contributor(issue.get("user"), repo, branch, user_id, is_public)

            self.db.merge_tenant_node(
                "Issue",
                issue_id,
                {
                    "repo": repo,
                    "branch": branch,
                    "number": issue_number,
                    "title": issue.get("title", ""),
                    "state": issue.get("state", ""),
                    "created_at": issue.get("created_at", ""),
                },
                user_id,
                is_public,
            )

            if author_id:
                self.db.merge_tenant_relationship(
                    "Contributor",
                    author_id,
                    "Issue",
                    issue_id,
                    "OPENED",
                    user_id,
                    is_public,
                )

            for label in issue.get("labels", []):
                label_name = label if isinstance(label, str) else label.get("name", "")
                if label_name:
                    label_id = f"{graph_repo_id}::label::{label_name.lower()}"
                    self.db.merge_tenant_node(
                        "Label",
                        label_id,
                        {"name": label_name, "repo": repo, "branch": branch},
                        user_id,
                        is_public,
                    )
                    self.db.merge_tenant_relationship(
                        "Issue",
                        issue_id,
                        "Label",
                        label_id,
                        "LABELED",
                        user_id,
                        is_public,
                    )

    async def build_pr_graph(
        self,
        prs: list[dict],
        repo: str,
        branch: str = "main",
        user_id: str | None = None,
        is_public: bool = False,
    ) -> None:
        """
        Nodes: :PullRequest, :Contributor
        Edges: (Contributor)-[:OPENED]->(PR), (PR)-[:MODIFIES]->(File), (PR)-[:CLOSES]->(Issue)
        """
        owner, repo_name = repo.split("/")
        graph_repo_id = self._branch_repo_id(repo, branch)

        for pr in prs:
            pr_number = pr["number"]
            pr_id = f"{graph_repo_id}::pr::{pr_number}"
            author_id = self._merge_contributor(pr.get("user"), repo, branch, user_id, is_public)

            body = pr.get("body") or ""

            self.db.merge_tenant_node(
                "PullRequest",
                pr_id,
                {
                    "repo": repo,
                    "branch": branch,
                    "number": pr_number,
                    "title": pr.get("title", ""),
                    "state": pr.get("state", ""),
                    "created_at": pr.get("created_at", ""),
                    "merged_at": pr.get("merged_at"),
                },
                user_id,
                is_public,
            )

            if author_id:
                self.db.merge_tenant_relationship(
                    "Contributor",
                    author_id,
                    "PullRequest",
                    pr_id,
                    "OPENED",
                    user_id,
                    is_public,
                )

            linked_issues = self._extract_linked_issues(body)
            for iss_num in linked_issues:
                iss_id = f"{graph_repo_id}::issue::{iss_num}"
                self.db.merge_tenant_relationship(
                    "PullRequest",
                    pr_id,
                    "Issue",
                    iss_id,
                    "CLOSES",
                    user_id,
                    is_public,
                )

            try:
                pr_files = await self.github.fetch_pr_files(owner, repo_name, pr_number)
                for f in pr_files:
                    path = f.get("filename")
                    if path:
                        file_id = f"{graph_repo_id}::{path}"
                        self.db.merge_tenant_node(
                            "File",
                            file_id,
                            {"path": path, "repo": repo, "branch": branch},
                            user_id,
                            is_public,
                        )
                        self.db.merge_tenant_relationship(
                            "PullRequest",
                            pr_id,
                            "File",
                            file_id,
                            "MODIFIES",
                            user_id,
                            is_public,
                            {"status": f.get("status")},
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch files for PR #{pr_number}: {e}")

    async def build_commit_graph(
        self,
        commits: list[dict],
        repo: str,
        branch: str = "main",
        user_id: str | None = None,
        is_public: bool = False,
    ) -> None:
        """
        Nodes: :Commit, :File, :Contributor
        Edges: (Contributor)-[:AUTHORED]->(Commit), (Commit)-[:TOUCHES]->(File)
        """
        graph_repo_id = self._branch_repo_id(repo, branch)
        for commit_obj in commits:
            sha = commit_obj["sha"]
            commit_id = f"{graph_repo_id}::commit::{sha}"

            commit_data = commit_obj.get("commit", {})
            author_obj = commit_obj.get("author")

            author_id = self._merge_contributor(author_obj, repo, branch, user_id, is_public)

            self.db.merge_tenant_node(
                "Commit",
                commit_id,
                {
                    "repo": repo,
                    "branch": branch,
                    "sha": sha,
                    "message": commit_data.get("message", "")[:200],
                    "date": commit_data.get("author", {}).get("date", ""),
                },
                user_id,
                is_public,
            )

            if author_id:
                self.db.merge_tenant_relationship(
                    "Contributor",
                    author_id,
                    "Commit",
                    commit_id,
                    "AUTHORED",
                    user_id,
                    is_public,
                )

            for f in commit_obj.get("files", []):
                path = f.get("filename")
                if path:
                    file_id = f"{graph_repo_id}::{path}"
                    self.db.merge_tenant_node(
                        "File",
                        file_id,
                        {"path": path, "repo": repo, "branch": branch},
                        user_id,
                        is_public,
                    )
                    self.db.merge_tenant_relationship(
                        "Commit",
                        commit_id,
                        "File",
                        file_id,
                        "TOUCHES",
                        user_id,
                        is_public,
                        {"status": f.get("status")},
                    )
