"""
Server-side session store for per-user secrets.

The GitHub access token for an authenticated user MUST NOT be handed to the
browser. It lives only in this server-side store, keyed by user_id and looked
up inside the request lifecycle.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _SessionEntry:
    github_token: str | None
    expires_at: float


class BaseSessionStore(ABC):
    @abstractmethod
    def set_github_token(self, user_id: str, token: str | None, ttl: int | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_github_token(self, user_id: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def clear(self, user_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def size(self) -> int:
        raise NotImplementedError


class MemorySessionStore(BaseSessionStore):
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


class RedisSessionStore(BaseSessionStore):
    """Redis-backed session store that encrypts GitHub tokens before storage."""

    def __init__(
        self,
        redis_url: str,
        encryption_key: str,
        default_ttl_seconds: int = 86_400,
    ) -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                "SESSION_STORE_BACKEND=redis requires redis-py. Install backend requirements first."
            ) from exc

        self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
        self._default_ttl = default_ttl_seconds
        self._fernet = Fernet(_fernet_key(encryption_key))

        try:
            self._redis.ping()
        except Exception as exc:
            raise RuntimeError("Could not connect to Redis session store at configured REDIS_URL.") from exc

    def _key(self, user_id: str) -> str:
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        return f"cortex:session:github:{digest}"

    def set_github_token(
        self,
        user_id: str,
        token: str | None,
        ttl: int | None = None,
    ) -> None:
        if not token:
            self.clear(user_id)
            return
        encrypted = self._fernet.encrypt(token.encode("utf-8"))
        self._redis.setex(self._key(user_id), ttl or self._default_ttl, encrypted)

    def get_github_token(self, user_id: str) -> str | None:
        encrypted = self._redis.get(self._key(user_id))
        if not encrypted:
            return None
        try:
            return self._fernet.decrypt(encrypted).decode("utf-8")
        except InvalidToken:
            logger.warning("Encrypted GitHub session token could not be decrypted for user_id=%s", user_id)
            return None

    def clear(self, user_id: str) -> None:
        self._redis.delete(self._key(user_id))

    def size(self) -> int:
        return 0


def _fernet_key(secret: str) -> bytes:
    """Turn any strong app secret into a Fernet-compatible 32-byte urlsafe key."""
    try:
        decoded = base64.urlsafe_b64decode(secret.encode("utf-8"))
        if len(decoded) == 32:
            return secret.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def create_session_store() -> BaseSessionStore:
    backend = settings.session_store_backend.lower().strip()
    ttl = settings.session_ttl_seconds
    if backend == "redis":
        if not settings.redis_url:
            raise RuntimeError("SESSION_STORE_BACKEND=redis requires REDIS_URL.")
        if not settings.session_encryption_key:
            raise RuntimeError("SESSION_STORE_BACKEND=redis requires SESSION_ENCRYPTION_KEY.")
        logger.info("Using Redis session store.")
        return RedisSessionStore(
            redis_url=settings.redis_url,
            encryption_key=settings.session_encryption_key,
            default_ttl_seconds=ttl,
        )
    if backend != "memory":
        raise RuntimeError(f"Unsupported SESSION_STORE_BACKEND '{settings.session_store_backend}'.")
    logger.info("Using in-memory session store.")
    return MemorySessionStore(default_ttl_seconds=ttl)


session_store = create_session_store()
