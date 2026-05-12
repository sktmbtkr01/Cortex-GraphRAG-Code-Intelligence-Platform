"""
Cortex Embedder - Handles dense + sparse embedding generation.
"""

import asyncio
import hashlib
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class CortexEmbedder:
    """Generates dense vectors and BM25-style sparse vectors."""

    def __init__(self):
        self.backend = settings.embedding_backend.lower().strip()
        if self.backend not in {"fastembed", "vertex"}:
            raise ValueError(
                "Unsupported EMBEDDING_BACKEND. Expected 'fastembed' or 'vertex'."
            )

        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.client = None
        if self.backend == "fastembed":
            self.model = settings.embedding_model
            self.device = settings.embedding_device.lower().strip()
            self._init_fastembed()
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

    def _truncate_for_vertex(self, text: str) -> str:
        max_chars = settings.vertex_embedding_max_text_chars
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars]

    def _embed_vertex_sync_once(self, texts: list[str]) -> list[list[float]]:
        if self.client is None:
            raise RuntimeError("Vertex embedding client is not initialized.")
        response = self.client.models.embed_content(
            model=self.model,
            contents=[self._truncate_for_vertex(text) for text in texts],
            config=types.EmbedContentConfig(
                task_type=settings.vertex_embedding_task_type,
                output_dimensionality=self.dimensions,
                auto_truncate=True,
            ),
        )
        dense_vectors = [embedding.values for embedding in response.embeddings or []]
        if len(dense_vectors) != len(texts):
            raise ValueError(
                f"Vertex returned {len(dense_vectors)} embeddings for {len(texts)} inputs."
            )
        return self._validate_dimensions(dense_vectors)

    def _embed_vertex_sync(self, texts: list[str]) -> list[list[float]]:
        attempts = max(1, settings.vertex_embedding_retry_attempts)

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_not_exception_type(ValueError),
        )
        def call_vertex(batch: list[str]) -> list[list[float]]:
            return self._embed_vertex_sync_once(batch)

        dense_vectors: list[list[float]] = []
        request_batch_size = min(max(1, self.batch_size), 250)
        for offset in range(0, len(texts), request_batch_size):
            dense_vectors.extend(call_vertex(texts[offset : offset + request_batch_size]))
        return dense_vectors

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts using the configured dense embedding backend.

        FastEmbed and Vertex calls are synchronous under the hood here, so run them in a
        worker thread to avoid blocking the FastAPI event loop during ingestion and query-time embedding.
        """
        if not texts:
            return []

        if self.backend == "vertex":
            logger.info(
                "Embedding %s texts with Vertex model '%s' in %s.",
                len(texts),
                self.model,
                settings.vertex_location,
            )
            return await asyncio.to_thread(self._embed_vertex_sync, texts)

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
