from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.config import settings

TERMINAL_STATES = {"done", "error", "lost"}


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


class JobStore:
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


job_store = JobStore(
    max_age_seconds=settings.ingest_job_max_age_seconds,
    max_events_per_job=settings.ingest_job_max_events,
)
