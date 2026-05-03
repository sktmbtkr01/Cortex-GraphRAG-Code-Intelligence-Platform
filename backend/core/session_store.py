"""
Server-side session store for ephemeral per-user secrets.

The GitHub access token for an authenticated user MUST NOT be handed to
the browser. It lives only in this in-memory store, keyed by user_id and
looked up inside the request lifecycle.

For MVP this is a process-local dict. For horizontal scaling this should
be backed by Redis with the same interface.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _SessionEntry:
    github_token: str | None
    expires_at: float  # epoch seconds


class SessionStore:
    """Thread-safe in-memory session store with TTL eviction."""

    def __init__(self, default_ttl_seconds: int = 86_400) -> None:
        self._default_ttl = default_ttl_seconds
        self._data: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()

    def _prune_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if v.expires_at < now]
        for k in expired:
            self._data.pop(k, None)

    def set_github_token(
        self,
        user_id: str,
        token: str | None,
        ttl: int | None = None,
    ) -> None:
        ttl = ttl or self._default_ttl
        with self._lock:
            self._data[user_id] = _SessionEntry(
                github_token=token,
                expires_at=time.time() + ttl,
            )

    def get_github_token(self, user_id: str) -> str | None:
        with self._lock:
            self._prune_expired()
            entry = self._data.get(user_id)
            return entry.github_token if entry else None

    def clear(self, user_id: str) -> None:
        with self._lock:
            self._data.pop(user_id, None)

    def size(self) -> int:
        with self._lock:
            self._prune_expired()
            return len(self._data)


# Module-level singleton — swap for Redis later without touching call sites.
session_store = SessionStore()
