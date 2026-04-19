import base64
import httpx
from typing import Any

from core.config import settings
from core.rate_limiter import GitHubRateLimiter
from core.logger import get_logger

logger = get_logger(__name__)


class GitHubClient:
    """Async client for GitHub REST API interactions."""

    def __init__(self, token: str | None = None):
        """
        Initialize GitHub client.

        Args:
            token: Optional ephemeral GitHub token (from OAuth user session).
                   If provided, takes priority over the env PAT.
                   This token is NEVER persisted — it lives only in memory.
        """
        self.rate_limiter = GitHubRateLimiter()
        self.headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Cortex-Code-Intelligence",
        }
        # Priority: ephemeral user token > env PAT
        auth_token = token or settings.github_pat
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.base_url = "https://api.github.com"

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=self.headers, **kwargs)
            await self.rate_limiter.wait_if_needed(response)
            response.raise_for_status()
            return response.json()

    async def fetch_repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch general info about a repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}"
        logger.info(f"Fetching metadata for {owner}/{repo}")
        return await self._request("GET", url)

    async def fetch_file_tree(self, owner: str, repo: str, branch: str = "main") -> list[dict[str, Any]]:
        """Fetch flat list of all files in the repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        logger.info(f"Fetching file tree for {owner}/{repo} on branch {branch}")
        data = await self._request("GET", url)
        # Filter out directories
        return [item for item in data.get("tree", []) if item["type"] == "blob"]

    async def fetch_file_content(self, owner: str, repo: str, sha: str) -> str:
        """Fetch raw content of a file using its blob SHA."""
        url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{sha}"
        data = await self._request("GET", url)
        content_b64 = data.get("content", "")
        # GitHub blobs are base64 encoded
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")

    async def fetch_issues(self, owner: str, repo: str, state: str = "all") -> list[dict[str, Any]]:
        """Fetch all issues for a repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues"
        issues = []
        page = 1
        while True:
            params = {"state": state, "per_page": 100, "page": page}
            logger.info(f"Fetching issues page {page} for {owner}/{repo}")
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break
            # GitHub API returns PRs in the issues list too, so filter them out if needed,
            # or keep them to process together. Here we just return all.
            issues.extend(page_data)
            page += 1
            if len(page_data) < 100:
                break
        return issues

    async def fetch_pull_requests(self, owner: str, repo: str, state: str = "all") -> list[dict[str, Any]]:
        """Fetch all pull requests for a repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        prs = []
        page = 1
        while True:
            params = {"state": state, "per_page": 100, "page": page}
            logger.info(f"Fetching PRs page {page} for {owner}/{repo}")
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break
            prs.extend(page_data)
            page += 1
            if len(page_data) < 100:
                break
        return prs

    async def fetch_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch list of files modified by a PR."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        return await self._request("GET", url)

    async def fetch_commits(self, owner: str, repo: str, limit: int = 500) -> list[dict[str, Any]]:
        """Fetch recent commits."""
        url = f"{self.base_url}/repos/{owner}/{repo}/commits"
        commits = []
        page = 1
        while len(commits) < limit:
            params = {"per_page": min(100, limit - len(commits)), "page": page}
            logger.info(f"Fetching commits page {page} for {owner}/{repo}")
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break
            commits.extend(page_data)
            page += 1
            if len(page_data) < len(commits):
                break # the requested limit or page size has not been reached. we're done downloading page
        
        return commits[:limit]
