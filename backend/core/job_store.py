from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.config import settings
from core.logger import get_logger

TERMINAL_STATES = {"done", "error", "lost"}
logger = get_logger(__name__)


@dataclass
class JobState:
    job_id: str
    user_id: str
    repo: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    event_offset: int = 0
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)


class BaseJobStore(ABC):
    @abstractmethod
    def create_job(self, user_id: str, repo: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> JobState | None:
        raise NotImplementedError

    @abstractmethod
    def get_snapshot(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def lost_event(self, job_id: str | None = None, repo: str | None = None) -> dict[str, Any]:
        message = "Ingest job state was lost. The backend may have restarted or the job expired."
        if job_id:
            message += f" Job id: {job_id}."
        return {
            "type": "error",
            "state": "lost",
            "stage": "lost",
            "repo": repo,
            "message": message,
        }

    @abstractmethod
    async def wait_for_events(
        self,
        job_id: str,
        cursor: int,
        timeout_seconds: float = 15.0,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        raise NotImplementedError

    @abstractmethod
    def get_events_since(self, job_id: str, cursor: int) -> tuple[list[dict[str, Any]], int, bool]:
        raise NotImplementedError


class MemoryJobStore(BaseJobStore):
    def __init__(self, max_age_seconds: int = 3_600, max_events_per_job: int = 500) -> None:
        self._jobs: dict[str, JobState] = {}
        self._max_age_seconds = max_age_seconds
        self._max_events_per_job = max_events_per_job

    def _prune(self) -> None:
        now = time.time()
        to_delete = [
            job_id
            for job_id, state in self._jobs.items()
            if state.done and (now - state.created_at) > self._max_age_seconds
        ]
        for job_id in to_delete:
            self._jobs.pop(job_id, None)

    def create_job(self, user_id: str, repo: str) -> str:
        self._prune()
        job_id = str(uuid.uuid4())
        state = JobState(job_id=job_id, user_id=user_id, repo=repo)
        state.events.append(
            {
                "type": "status",
                "state": "queued",
                "stage": "queued",
                "message": f"Queued ingest for {repo}",
                "repo": repo,
            }
        )
        self._jobs[job_id] = state
        return job_id

    def get_job(self, job_id: str) -> JobState | None:
        self._prune()
        return self._jobs.get(job_id)

    def get_snapshot(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "repo": job.repo,
            "status": job.status,
            "done": job.done,
            "event_count": len(job.events),
            "event_offset": job.event_offset,
        }

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return

        state = str(event.get("state", ""))
        if state in TERMINAL_STATES:
            job.status = state
            job.done = True
        elif state:
            job.status = state

        async with job.cond:
            job.events.append(event)
            if len(job.events) > self._max_events_per_job:
                overflow = len(job.events) - self._max_events_per_job
                del job.events[:overflow]
                job.event_offset += overflow
            job.cond.notify_all()

    def _slice_events(self, job: JobState, cursor: int) -> tuple[list[dict[str, Any]], int]:
        if cursor < job.event_offset:
            cursor = job.event_offset

        start = max(0, cursor - job.event_offset)
        events = job.events[start:]
        new_cursor = job.event_offset + len(job.events)
        return events, new_cursor

    async def wait_for_events(
        self,
        job_id: str,
        cursor: int,
        timeout_seconds: float = 15.0,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        job = self._jobs.get(job_id)
        if not job:
            return [self.lost_event(job_id)], cursor, True

        async with job.cond:
            current_end = job.event_offset + len(job.events)
            if cursor >= current_end and not job.done:
                try:
                    await asyncio.wait_for(job.cond.wait(), timeout=timeout_seconds)
                except (TimeoutError, asyncio.TimeoutError):
                    pass

            events, new_cursor = self._slice_events(job, cursor)
            return events, new_cursor, job.done

    def get_events_since(self, job_id: str, cursor: int) -> tuple[list[dict[str, Any]], int, bool]:
        job = self._jobs.get(job_id)
        if not job:
            return [self.lost_event(job_id)], cursor, True

        events, new_cursor = self._slice_events(job, cursor)
        return events, new_cursor, job.done


class RedisJobStore(BaseJobStore):
    def __init__(self, redis_url: str, max_age_seconds: int, max_events_per_job: int) -> None:
        try:
            import redis
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise RuntimeError(
                "JOB_STORE_BACKEND=redis requires redis-py. Install backend requirements first."
            ) from exc

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._async_redis = aioredis.Redis.from_url(redis_url, decode_responses=True)
        self._max_age_seconds = max_age_seconds
        self._max_events_per_job = max_events_per_job

        try:
            self._redis.ping()
        except Exception as exc:
            raise RuntimeError(f"Could not connect to Redis job store at {redis_url}: {exc}") from exc

    def _job_key(self, job_id: str) -> str:
        return f"cortex:ingest:job:{job_id}"

    def _events_key(self, job_id: str) -> str:
        return f"cortex:ingest:job:{job_id}:events"

    def _queued_event(self, repo: str) -> dict[str, Any]:
        return {
            "type": "status",
            "state": "queued",
            "stage": "queued",
            "message": f"Queued ingest for {repo}",
            "repo": repo,
        }

    def _set_expiry(self, job_id: str) -> None:
        self._redis.expire(self._job_key(job_id), self._max_age_seconds)
        self._redis.expire(self._events_key(job_id), self._max_age_seconds)

    def create_job(self, user_id: str, repo: str) -> str:
        job_id = str(uuid.uuid4())
        now = time.time()
        pipe = self._redis.pipeline()
        pipe.hset(
            self._job_key(job_id),
            mapping={
                "job_id": job_id,
                "user_id": user_id,
                "repo": repo,
                "created_at": str(now),
                "status": "queued",
                "done": "0",
                "event_offset": "0",
            },
        )
        pipe.rpush(self._events_key(job_id), json.dumps(self._queued_event(repo)))
        pipe.expire(self._job_key(job_id), self._max_age_seconds)
        pipe.expire(self._events_key(job_id), self._max_age_seconds)
        pipe.execute()
        return job_id

    def get_job(self, job_id: str) -> JobState | None:
        data = self._redis.hgetall(self._job_key(job_id))
        if not data:
            return None
        return JobState(
            job_id=str(data["job_id"]),
            user_id=str(data["user_id"]),
            repo=str(data["repo"]),
            created_at=float(data.get("created_at") or 0),
            status=str(data.get("status") or "queued"),
            event_offset=int(data.get("event_offset") or 0),
            done=str(data.get("done") or "0") == "1",
        )

    def get_snapshot(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        event_count = int(self._redis.llen(self._events_key(job_id)) or 0)
        return {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "repo": job.repo,
            "status": job.status,
            "done": job.done,
            "event_count": event_count,
            "event_offset": job.event_offset,
        }

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        job_key = self._job_key(job_id)
        events_key = self._events_key(job_id)
        if not await self._async_redis.exists(job_key):
            return

        state = str(event.get("state", ""))
        updates: dict[str, str] = {}
        if state in TERMINAL_STATES:
            updates["status"] = state
            updates["done"] = "1"
        elif state:
            updates["status"] = state

        pipe = self._async_redis.pipeline()
        if updates:
            pipe.hset(job_key, mapping=updates)
        pipe.rpush(events_key, json.dumps(event))
        pipe.llen(events_key)
        results = await pipe.execute()
        event_count = int(results[-1] or 0)
        if event_count > self._max_events_per_job:
            overflow = event_count - self._max_events_per_job
            trim_pipe = self._async_redis.pipeline()
            trim_pipe.ltrim(events_key, overflow, -1)
            trim_pipe.hincrby(job_key, "event_offset", overflow)
            await trim_pipe.execute()

        await self._async_redis.expire(job_key, self._max_age_seconds)
        await self._async_redis.expire(events_key, self._max_age_seconds)

    def _slice_events(self, job: JobState, cursor: int) -> tuple[list[dict[str, Any]], int]:
        if cursor < job.event_offset:
            cursor = job.event_offset

        start = max(0, cursor - job.event_offset)
        raw_events = self._redis.lrange(self._events_key(job.job_id), start, -1)
        events = [json.loads(raw_event) for raw_event in raw_events]
        event_count = int(self._redis.llen(self._events_key(job.job_id)) or 0)
        new_cursor = job.event_offset + event_count
        return events, new_cursor

    def get_events_since(self, job_id: str, cursor: int) -> tuple[list[dict[str, Any]], int, bool]:
        job = self.get_job(job_id)
        if not job:
            return [self.lost_event(job_id)], cursor, True

        events, new_cursor = self._slice_events(job, cursor)
        return events, new_cursor, job.done

    async def wait_for_events(
        self,
        job_id: str,
        cursor: int,
        timeout_seconds: float = 15.0,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            events, new_cursor, done = self.get_events_since(job_id, cursor)
            if events or done or time.monotonic() >= deadline:
                return events, new_cursor, done
            await asyncio.sleep(0.5)


def create_job_store() -> BaseJobStore:
    backend = settings.job_store_backend.lower().strip()
    if backend == "redis":
        if not settings.redis_url:
            raise RuntimeError("JOB_STORE_BACKEND=redis requires REDIS_URL.")
        logger.info("Using Redis job store.")
        return RedisJobStore(
            redis_url=settings.redis_url,
            max_age_seconds=settings.ingest_job_max_age_seconds,
            max_events_per_job=settings.ingest_job_max_events,
        )
    if backend != "memory":
        raise RuntimeError(f"Unsupported JOB_STORE_BACKEND '{settings.job_store_backend}'.")
    logger.info("Using in-memory job store.")
    return MemoryJobStore(
        max_age_seconds=settings.ingest_job_max_age_seconds,
        max_events_per_job=settings.ingest_job_max_events,
    )


job_store = create_job_store()
