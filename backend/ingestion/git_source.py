"""Git clone based ingestion source.

This source fetches repository contents by shallow-cloning a selected branch into
a temporary directory, then returning eligible file contents in the same shape as
the GitHub API source used by ``IngestionPipeline``.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import quote

from core.config import settings
from core.logger import get_logger
from ingestion.file_router import should_process_file

logger = get_logger(__name__)


@dataclass
class GitCloneFetchResult:
    fetched_files: list[tuple[dict, str]]
    total_files: int
    eligible_files: int
    skipped_files: int


@dataclass
class GitCloneBatchResult:
    total_files: int
    eligible_files: int
    skipped_files: int
    batches_processed: int
    clone_ms: int
    file_walk_ms: int
    file_read_ms: int


def _authenticated_repo_url(repo: str, token: str | None) -> str:
    if token:
        encoded_token = quote(token, safe="")
        return f"https://x-access-token:{encoded_token}@github.com/{repo}.git"
    return f"https://github.com/{repo}.git"


def _safe_command_for_log(command: list[str]) -> list[str]:
    safe = []
    for part in command:
        if part.startswith("https://x-access-token:"):
            safe.append("https://x-access-token:[REDACTED]@github.com/REPO.git")
        else:
            safe.append(part)
    return safe


async def _run_git_clone(command: list[str]) -> None:
    logger.info("Running shallow clone command: %s", _safe_command_for_log(command))
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=settings.git_clone_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"git clone timed out after {settings.git_clone_timeout_seconds} seconds"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"failed to start git clone process: {type(exc).__name__}: {exc!r}"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            "git clone failed "
            f"(exit={completed.returncode}, stdout={completed.stdout[:500]}, stderr={completed.stderr[:500]})"
        )


async def fetch_repo_files_via_git_clone(
    repo: str,
    branch: str,
    token: str | None = None,
) -> GitCloneFetchResult:
    """Shallow clone a repo branch and return eligible file contents."""
    temp_root = Path(tempfile.mkdtemp(prefix="cortex-git-ingest-"))
    clone_dir = temp_root / "repo"
    try:
        clone_command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            _authenticated_repo_url(repo, token),
            str(clone_dir),
        ]
        await _run_git_clone(clone_command)

        fetched_files: list[tuple[dict, str]] = []
        total_files = 0
        skipped_files = 0
        for path in clone_dir.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(clone_dir).as_posix()
            try:
                size = path.stat().st_size
            except OSError:
                skipped_files += 1
                continue

            total_files += 1
            if not should_process_file(rel_path, size):
                skipped_files += 1
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped_files += 1
                continue

            fetched_files.append(({"path": rel_path, "size": size, "source": "git_clone"}, content))

        return GitCloneFetchResult(
            fetched_files=fetched_files,
            total_files=total_files,
            eligible_files=len(fetched_files),
            skipped_files=skipped_files,
        )
    finally:
        try:
            shutil.rmtree(temp_root)
            logger.info("Deleted temporary git clone directory: %s", temp_root)
        except FileNotFoundError:
            logger.info("Temporary git clone directory already removed: %s", temp_root)
        except Exception as exc:
            logger.warning("Failed to delete temporary git clone directory %s: %s", temp_root, exc)


async def process_repo_files_via_git_clone_batches(
    repo: str,
    branch: str,
    token: str | None,
    batch_size: int,
    batch_cb: Callable[[list[tuple[dict, str]], dict], Awaitable[None] | None],
) -> GitCloneBatchResult:
    """Shallow clone a branch and stream eligible file contents to a batch callback."""
    temp_root = Path(tempfile.mkdtemp(prefix="cortex-git-ingest-"))
    clone_dir = temp_root / "repo"
    batch_size = max(1, batch_size)
    try:
        clone_command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            _authenticated_repo_url(repo, token),
            str(clone_dir),
        ]
        clone_started_at = time.perf_counter()
        await _run_git_clone(clone_command)
        clone_ms = int((time.perf_counter() - clone_started_at) * 1000)

        walk_started_at = time.perf_counter()
        eligible_paths: list[tuple[Path, str, int]] = []
        total_files = 0
        skipped_files = 0
        for path in clone_dir.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(clone_dir).as_posix()
            try:
                size = path.stat().st_size
            except OSError:
                skipped_files += 1
                continue

            total_files += 1
            if not should_process_file(rel_path, size):
                skipped_files += 1
                continue
            eligible_paths.append((path, rel_path, size))
        file_walk_ms = int((time.perf_counter() - walk_started_at) * 1000)

        total_batches = max(1, (len(eligible_paths) + batch_size - 1) // batch_size)
        batches_processed = 0
        file_read_ms = 0
        for start in range(0, len(eligible_paths), batch_size):
            path_batch = eligible_paths[start : start + batch_size]
            file_batch: list[tuple[dict, str]] = []
            read_started_at = time.perf_counter()
            for path, rel_path, size in path_batch:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    skipped_files += 1
                    continue
                file_batch.append(
                    (
                        {
                            "path": rel_path,
                            "size": size,
                            "source": "git_clone",
                            "file_sha": hashlib.sha1(content.encode("utf-8")).hexdigest(),
                        },
                        content,
                    )
                )
            file_read_ms += int((time.perf_counter() - read_started_at) * 1000)

            if not file_batch:
                continue

            batches_processed += 1
            result = batch_cb(
                file_batch,
                {
                    "batch": batches_processed,
                    "total_batches": total_batches,
                    "files": len(file_batch),
                    "total_files": len(eligible_paths),
                },
            )
            if asyncio.iscoroutine(result):
                await result

        return GitCloneBatchResult(
            total_files=total_files,
            eligible_files=len(eligible_paths),
            skipped_files=skipped_files,
            batches_processed=batches_processed,
            clone_ms=clone_ms,
            file_walk_ms=file_walk_ms,
            file_read_ms=file_read_ms,
        )
    finally:
        try:
            shutil.rmtree(temp_root)
            logger.info("Deleted temporary git clone directory: %s", temp_root)
        except FileNotFoundError:
            logger.info("Temporary git clone directory already removed: %s", temp_root)
        except Exception as exc:
            logger.warning("Failed to delete temporary git clone directory %s: %s", temp_root, exc)
