from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from fastapi import HTTPException

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


def _redis_client():
    if not settings.redis_url:
        return None
    try:
        import redis
    except ImportError:
        return None
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


_redis = _redis_client() if settings.cache_backend == "redis" or settings.quota_backend == "redis" else None


def _user_hash(user_id: str) -> str:
    return sha256(user_id.encode("utf-8")).hexdigest()


def _repo_hash(repo: str) -> str:
    return sha256(repo.encode("utf-8")).hexdigest()


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seconds_until_tomorrow() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
    return max(60, int((tomorrow - now).total_seconds()))


def cache_get_json(key: str) -> Any | None:
    if _redis is None:
        return None
    value = _redis.get(key)
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    if _redis is None:
        return
    _redis.setex(key, ttl_seconds, json.dumps(value, default=str))


def github_repos_cache_key(user_id: str) -> str:
    return f"cortex:cache:github_repos:{_user_hash(user_id)}"


def github_branches_cache_key(user_id: str, repo: str) -> str:
    return f"cortex:cache:github_branches:{_user_hash(user_id)}:{_repo_hash(repo)}"


def snapshot_cache_key(user_id: str, repo: str, branch: str, commit_sha: str | None) -> str:
    commit = commit_sha or "unknown"
    return f"cortex:cache:snapshot:{_user_hash(user_id)}:{_repo_hash(repo)}:{branch}:{commit}"


def health_cache_key(user_id: str, repo: str, branch: str, commit_sha: str | None) -> str:
    commit = commit_sha or "unknown"
    return f"cortex:cache:health:{_user_hash(user_id)}:{_repo_hash(repo)}:{branch}:{commit}"


def _limit_error(code: str, message: str, limit: int | float | None = None, unit: str | None = None) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if limit is not None:
        detail["limit"] = limit
    if unit:
        detail["unit"] = unit
    return HTTPException(status_code=429, detail=detail)


def _increment_daily_counter(key: str, limit: int, code: str, message: str) -> int:
    if _redis is None:
        return 0
    value = int(_redis.incr(key))
    if value == 1:
        _redis.expire(key, _seconds_until_tomorrow())
    if value > limit:
        raise _limit_error(code, message, limit, "per_day")
    return value


def check_daily_ingest_quota(user_id: str) -> int:
    key = f"cortex:quota:ingests:{_user_hash(user_id)}:{_today_key()}"
    return _increment_daily_counter(
        key,
        settings.max_ingests_per_user_per_day,
        "daily_ingest_limit",
        "This demo currently allows a limited number of ingests per day.",
    )


def check_daily_query_quota(user_id: str) -> int:
    key = f"cortex:quota:queries:{_user_hash(user_id)}:{_today_key()}"
    return _increment_daily_counter(
        key,
        settings.max_queries_per_user_per_day,
        "daily_query_limit",
        "This demo currently allows a limited number of queries per day.",
    )


def check_daily_health_quota(user_id: str, repo: str, branch: str, commit_sha: str | None) -> int:
    key = f"cortex:quota:health:{_user_hash(user_id)}:{_repo_hash(repo)}:{branch}:{commit_sha or 'unknown'}"
    return _increment_daily_counter(
        key,
        settings.max_health_checks_per_repo_commit,
        "health_check_limit",
        "Health checks are cached and limited to one generation per repository commit.",
    )


@contextmanager
def active_ingest_lock(user_id: str, job_id: str):
    if _redis is None:
        yield
        return

    user_key = f"cortex:lock:active_ingest:user:{_user_hash(user_id)}"
    global_key = "cortex:lock:active_ingest:global"
    lock_ttl = settings.ingest_job_max_age_seconds
    user_lock_acquired = False
    global_acquired = False
    try:
        user_lock_acquired = bool(_redis.set(user_key, job_id, nx=True, ex=lock_ttl))
        if not user_lock_acquired:
            raise _limit_error(
                "active_ingest_exists",
                "You already have an active ingestion running.",
                settings.max_active_ingests_per_user,
                "active_ingests",
            )

        active_count = int(_redis.incr(global_key))
        global_acquired = True
        if active_count == 1:
            _redis.expire(global_key, lock_ttl)
        if active_count > settings.max_global_active_ingests:
            raise _limit_error(
                "global_active_ingest_limit",
                "Cortex is already processing the maximum number of demo ingests.",
                settings.max_global_active_ingests,
                "active_ingests",
            )

        yield
    finally:
        if user_lock_acquired:
            _redis.delete(user_key)
        if global_acquired:
            try:
                remaining = int(_redis.decr(global_key))
                if remaining <= 0:
                    _redis.delete(global_key)
            except Exception:
                logger.warning("Failed to release global active ingest lock", exc_info=True)


def enforce_repo_count_limit(current_count: int) -> None:
    if current_count >= settings.max_repos_per_user:
        raise _limit_error(
            "repo_count_limit",
            "This demo currently supports a limited number of indexed repositories per user.",
            settings.max_repos_per_user,
            "repos",
        )


def enforce_repo_size_limit(repo_size_kb: int | float) -> None:
    repo_size_mb = repo_size_kb / 1024
    if repo_size_mb > settings.max_repo_size_mb:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "repo_too_large",
                "message": f"This demo currently supports repositories up to {settings.max_repo_size_mb} MB.",
                "limit": settings.max_repo_size_mb,
                "unit": "MB",
            },
        )


def enforce_eligible_file_limit(eligible_count: int) -> None:
    if eligible_count > settings.max_eligible_files:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "too_many_files",
                "message": "This demo currently supports a limited number of indexable files per repository.",
                "limit": settings.max_eligible_files,
                "unit": "files",
            },
        )


def enforce_chunk_limit(chunk_count: int) -> None:
    if chunk_count > settings.max_chunks_per_repo:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "too_many_chunks",
                "message": "This demo currently supports a limited number of chunks per repository.",
                "limit": settings.max_chunks_per_repo,
                "unit": "chunks",
            },
        )
