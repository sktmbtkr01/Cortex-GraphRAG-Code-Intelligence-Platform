"""
Cortex Embedder - Handles dense + sparse embedding generation.
"""

import asyncio
import hashlib
import time
from typing import Any

from google import genai
from google.genai import types

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

_last_embedding_request_at = 0.0


class CortexEmbedder:
    """Generates dense vectors and BM25-style sparse vectors."""

    def __init__(self):
        self.backend = settings.embedding_backend.lower().strip()
        if self.backend not in {"fastembed", "vertex", "gemini_api"}:
            raise ValueError(
                "Unsupported EMBEDDING_BACKEND. Expected 'fastembed', 'vertex', or 'gemini_api'."
            )

        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.client = None
        if self.backend == "fastembed":
            self.model = settings.embedding_model
            self.device = settings.embedding_device.lower().strip()
            self._init_fastembed()
        elif self.backend == "gemini_api":
            self.model = settings.vertex_embedding_model
            self.device = "gemini_api"
            self._init_gemini_api()
        else:
            self.model = settings.vertex_embedding_model
            self.device = "vertex"
            self._init_vertex()

    def _init_fastembed(self) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_BACKEND=fastembed requires fastembed. "
                "Use EMBEDDING_BACKEND=vertex in production or install local dev requirements."
            ) from exc

        embedding_kwargs = {}
        if self.device == "cuda":
            embedding_kwargs["providers"] = ["CUDAExecutionProvider"]
        self.client = TextEmbedding(
            model_name=self.model,
            cache_dir=settings.embedding_cache_dir,
            local_files_only=settings.embedding_local_files_only,
            **embedding_kwargs,
        )

    def _init_gemini_api(self) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when EMBEDDING_BACKEND=gemini_api.")
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def _init_vertex(self) -> None:
        if not settings.vertex_project_id:
            raise ValueError("VERTEX_PROJECT_ID is required when EMBEDDING_BACKEND=vertex.")
        self.client = genai.Client(
            vertexai=True,
            project=settings.vertex_project_id,
            location=settings.vertex_location,
        )

    def _validate_dimensions(self, dense_vectors: list[list[float]]) -> list[list[float]]:
        for idx, vector in enumerate(dense_vectors):
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension mismatch for item {idx}: "
                    f"model '{self.model}' returned {len(vector)} dimensions, "
                    f"but EMBEDDING_DIMENSIONS={self.dimensions}."
                )
        return dense_vectors

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self.client is None:
            raise RuntimeError("FastEmbed client is not initialized.")
        vectors = self.client.embed(texts, batch_size=self.batch_size)
        dense_vectors = [vector.tolist() for vector in vectors]
        return self._validate_dimensions(dense_vectors)

    def _truncate_for_embedding(self, text: str) -> str:
        if self.backend == "gemini_api":
            max_chars = min(settings.gemini_api_embedding_max_text_chars, 8_000)
        else:
            max_chars = min(settings.vertex_embedding_max_text_chars, 4_000)
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars]

    def _build_request_batches(self, texts: list[str]) -> list[list[str]]:
        max_items = min(max(1, self.batch_size), 250)
        if self.backend == "gemini_api":
            max_chars = max(1, settings.gemini_api_embedding_max_request_chars)
        else:
            max_chars = max(1, settings.vertex_embedding_max_request_chars)
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_chars = 0

        for text in texts:
            truncated = self._truncate_for_embedding(text)
            text_chars = len(truncated)
            should_flush = (
                current_batch
                and (
                    len(current_batch) >= max_items
                    or current_chars + text_chars > max_chars
                )
            )
            if should_flush:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(truncated)
            current_chars += text_chars

        if current_batch:
            batches.append(current_batch)

        return batches

    def _embed_genai_sync_once(self, texts: list[str]) -> list[list[float]]:
        if self.client is None:
            raise RuntimeError("Embedding client is not initialized.")
        config_kwargs = {
            "task_type": settings.vertex_embedding_task_type,
            "output_dimensionality": self.dimensions,
        }
        if self.backend == "vertex":
            config_kwargs["auto_truncate"] = True
        response = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(**config_kwargs),
        )
        dense_vectors = [embedding.values for embedding in response.embeddings or []]
        if len(dense_vectors) != len(texts):
            raise ValueError(
                f"Embedding API returned {len(dense_vectors)} embeddings for {len(texts)} inputs."
            )
        return self._validate_dimensions(dense_vectors)

    def _wait_for_quota_slot(self) -> None:
        global _last_embedding_request_at

        if self.backend == "gemini_api":
            interval = max(0.0, settings.gemini_api_embedding_min_request_interval_seconds)
        else:
            interval = max(0.0, settings.vertex_embedding_min_request_interval_seconds)
        if interval <= 0:
            return

        now = time.monotonic()
        wait_seconds = interval - (now - _last_embedding_request_at)
        if wait_seconds > 0:
            logger.info(
                "Waiting %.1fs before next %s embedding request to respect quota.",
                wait_seconds,
                self.backend,
            )
            time.sleep(wait_seconds)
        _last_embedding_request_at = time.monotonic()

    def _is_quota_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "429" in text
            or "resource_exhausted" in text
            or "quota exceeded" in text
            or "online_prediction_requests_per_base_model" in text
        )

    def _embed_genai_sync(self, texts: list[str]) -> list[list[float]]:
        attempts = max(1, settings.vertex_embedding_retry_attempts)

        if self.backend == "gemini_api":
            quota_retry = settings.gemini_api_embedding_quota_retry_seconds
            interval = settings.gemini_api_embedding_min_request_interval_seconds
        else:
            quota_retry = settings.vertex_embedding_quota_retry_seconds
            interval = settings.vertex_embedding_min_request_interval_seconds

        def call_embed(batch: list[str]) -> list[list[float]]:
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    self._wait_for_quota_slot()
                    return self._embed_genai_sync_once(batch)
                except ValueError:
                    raise
                except Exception as exc:
                    last_error = exc
                    if attempt >= attempts:
                        break

                    if self._is_quota_error(exc):
                        wait_seconds = max(quota_retry, interval)
                    else:
                        wait_seconds = min(10.0, 2.0 ** (attempt - 1))

                    logger.warning(
                        "%s embedding request failed on attempt %s/%s; retrying in %.1fs: %s",
                        self.backend,
                        attempt,
                        attempts,
                        wait_seconds,
                        exc,
                    )
                    time.sleep(wait_seconds)

            if last_error is not None:
                raise last_error
            raise RuntimeError("Embedding request failed without an exception.")

        dense_vectors: list[list[float]] = []
        batches = self._build_request_batches(texts)
        logger.info(
            "Split %s texts into %s %s embedding requests.",
            len(texts),
            len(batches),
            self.backend,
        )
        for batch in batches:
            dense_vectors.extend(call_embed(batch))
        return dense_vectors

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts using the configured dense embedding backend.

        FastEmbed and Vertex calls are synchronous under the hood here, so run them in a
        worker thread to avoid blocking the FastAPI event loop during ingestion and query-time embedding.
        """
        if not texts:
            return []

        if self.backend in {"vertex", "gemini_api"}:
            logger.info(
                "Embedding %s texts with %s model '%s'.",
                len(texts),
                self.backend,
                self.model,
            )
            return await asyncio.to_thread(self._embed_genai_sync, texts)

        logger.info(
            "Embedding %s texts locally with FastEmbed model '%s' on %s.",
            len(texts),
            self.model,
            self.device,
        )
        return await asyncio.to_thread(self._embed_sync, texts)

    def generate_sparse_vector(self, text: str) -> dict[str, Any]:
        """
        Generates a simplistic sparse vector for hybrid search.
        Ports the FinIntel BM25 logic using token hashing.
        Returns format: {"indices": [int, ...], "values": [float, ...]}
        """
        clean_text = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in text)
        tokens = clean_text.split()

        vocab_size = 1_000_000

        counts: dict[int, int] = {}
        for token in tokens:
            if len(token) < 2:
                continue
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % vocab_size
            counts[idx] = counts.get(idx, 0) + 1

        indices = []
        values = []
        for idx, count in sorted(counts.items()):
            indices.append(idx)
            values.append(count / (count + 0.5))

        return {"indices": indices, "values": values}
