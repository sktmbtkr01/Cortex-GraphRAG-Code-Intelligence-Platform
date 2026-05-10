import base64
import asyncio
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from core.config import settings
from core.rate_limiter import GitHubRateLimiter
from core.logger import get_logger

logger = get_logger(__name__)

TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
HARD_STATUS_CODES = {401, 403, 404, 422}


def _is_retryable_github_error(exc: BaseException) -> bool:
    """Return True for transient network/GitHub failures only."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in HARD_STATUS_CODES:
            return False
        return status_code in TRANSIENT_STATUS_CODES

    return False


class GitHubClient:
    """Async client for GitHub REST API interactions."""

    def __init__(self, token: str | None = None):
        """
        Initialize GitHub client.

        Args:
            token: Optional ephemeral GitHub token (from OAuth user session).
                   If provided, takes priority over the env PAT.
                   This token is NEVER persisted; it lives only in memory.
        """
        self.rate_limiter = GitHubRateLimiter()
        self.headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Cortex-Code-Intelligence",
        }
        auth_token = token or settings.github_pat
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"

        self.base_url = "https://api.github.com"
        self._client: httpx.AsyncClient | None = None

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            settings.github_request_timeout_seconds,
            connect=settings.github_connect_timeout_seconds,
        )

    def _limits(self, concurrency: int | None = None) -> httpx.Limits:
        keepalive = settings.github_max_keepalive_connections
        connections = settings.github_max_connections
        if concurrency is not None:
            keepalive = max(keepalive, concurrency)
            connections = max(connections, concurrency * 2)

        return httpx.Limits(
            max_keepalive_connections=keepalive,
            max_connections=connections,
        )

    def _new_client(self, concurrency: int | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout(),
            limits=self._limits(concurrency),
        )

    async def __aenter__(self) -> "GitHubClient":
        if self._client is None:
            self._client = self._new_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def _client_scope(self, concurrency: int | None = None):
        if self._client is not None:
            yield self._client
            return

        async with self._new_client(concurrency=concurrency) as client:
            self._client = client
            try:
                yield client
            finally:
                self._client = None

    async def _request_once(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> Any:
        response = await client.request(method, url, headers=self.headers, **kwargs)
        await self.rate_limiter.wait_if_needed(response)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        retryer = AsyncRetrying(
            stop=stop_after_attempt(max(1, settings.github_retry_attempts)),
            wait=wait_exponential_jitter(initial=1, max=8),
            retry=retry_if_exception(_is_retryable_github_error),
            reraise=True,
        )

        async with self._client_scope() as client:
            async for attempt in retryer:
                with attempt:
                    try:
                        return await self._request_once(client, method, url, **kwargs)
                    except Exception as exc:
                        if attempt.retry_state.attempt_number >= settings.github_retry_attempts:
                            logger.warning(
                                "GitHub request failed after %s attempts: %s %s (%r)",
                                attempt.retry_state.attempt_number,
                                method,
                                url,
                                exc,
                            )
                        raise

        raise RuntimeError("Unreachable GitHub request state")

    async def fetch_repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch general info about a repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}"
        logger.info(f"Fetching metadata for {owner}/{repo}")
        return await self._request("GET", url)

    async def fetch_branches(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Fetch branches for a repository."""
        url = f"{self.base_url}/repos/{owner}/{repo}/branches"
        branches: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {"per_page": 100, "page": page}
            logger.info("Fetching branches page %s for %s/%s", page, owner, repo)
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break
            branches.extend(page_data)
            page += 1
            if len(page_data) < 100:
                break
        return branches

    async def fetch_branch(self, owner: str, repo: str, branch: str) -> dict[str, Any]:
        """Fetch a single branch and its current head commit metadata."""
        encoded_branch = quote(branch, safe="")
        url = f"{self.base_url}/repos/{owner}/{repo}/branches/{encoded_branch}"
        logger.info("Fetching branch %s for %s/%s", branch, owner, repo)
        return await self._request("GET", url)

    async def fetch_file_tree(self, owner: str, repo: str, branch: str = "main") -> list[dict[str, Any]]:
        """Fetch flat list of all files in the repository."""
        encoded_branch = quote(branch, safe="")
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{encoded_branch}?recursive=1"
        logger.info(f"Fetching file tree for {owner}/{repo} on branch {branch}")
        data = await self._request("GET", url)
        return [item for item in data.get("tree", []) if item["type"] == "blob"]

    async def fetch_file_content(self, owner: str, repo: str, sha: str) -> str:
        """Fetch raw content of a file using its blob SHA."""
        url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{sha}"
        data = await self._request("GET", url)
        content_b64 = data.get("content", "")
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")

    async def fetch_file_contents_bulk(
        self,
        owner: str,
        repo: str,
        items: list[dict[str, Any]],
        concurrency: int | None = None,
    ) -> list[tuple[dict[str, Any], str | None, Exception | None]]:
        """
        Fetch file blob contents concurrently with bounded parallelism.

        Returns a list aligned to input order:
        - (item, content, None) on success
        - (item, None, exception) on failure
        """
        if not items:
            return []

        concurrency = concurrency or settings.github_fetch_concurrency
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _fetch_one(item: dict[str, Any]) -> tuple[dict[str, Any], str | None, Exception | None]:
            sha = item.get("sha")
            if not sha:
                return item, None, ValueError("Missing blob SHA")

            async with semaphore:
                path = item.get("path", "unknown-path")
                try:
                    content = await self.fetch_file_content(owner, repo, sha)
                    return item, content, None
                except Exception as exc:
                    logger.warning("Failed to fetch blob for %s after retries: %r", path, exc)
                    return item, None, exc

        async with self._client_scope(concurrency=concurrency):
            tasks = [_fetch_one(item) for item in items]
            return await asyncio.gather(*tasks)

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
            per_page = min(100, limit - len(commits))
            params = {"per_page": per_page, "page": page}
            logger.info(f"Fetching commits page {page} for {owner}/{repo}")
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break
            commits.extend(page_data)
            page += 1
            if len(page_data) < per_page:
                break

        return commits[:limit]

    async def list_user_repos(self, max_repos: int = 200) -> list[dict[str, Any]]:
        """List repositories for the authenticated GitHub user (private + public)."""
        url = f"{self.base_url}/user/repos"
        repos: list[dict[str, Any]] = []
        page = 1

        while len(repos) < max_repos:
            params = {
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
                "sort": "updated",
                "per_page": min(100, max_repos - len(repos)),
                "page": page,
            }
            logger.info("Fetching user repos page %s", page)
            page_data = await self._request("GET", url, params=params)
            if not page_data:
                break

            repos.extend(page_data)
            page += 1
            if len(page_data) < params["per_page"]:
                break

        return repos[:max_repos]

    async def create_webhook(self, owner: str, repo_name: str, payload: dict[str, Any]) -> httpx.Response:
        """Create a GitHub webhook and return the raw response for status handling."""
        url = f"{self.base_url}/repos/{owner}/{repo_name}/hooks"
        retryer = AsyncRetrying(
            stop=stop_after_attempt(max(1, settings.github_retry_attempts)),
            wait=wait_exponential_jitter(initial=1, max=8),
            retry=retry_if_exception(_is_retryable_github_error),
            reraise=True,
        )

        async with self._client_scope() as client:
            async for attempt in retryer:
                with attempt:
                    response = await client.post(url, headers=self.headers, json=payload)
                    await self.rate_limiter.wait_if_needed(response)
                    if response.status_code in (201, 422):
                        return response
                    response.raise_for_status()

        raise RuntimeError("Unreachable GitHub webhook creation state")
