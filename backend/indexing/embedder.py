"""
Cortex Embedder - Handles dense + sparse embedding generation.
"""

import asyncio
import hashlib
from typing import Any

from fastembed import TextEmbedding

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class CortexEmbedder:
    """Generates local FastEmbed dense vectors and BM25-style sparse vectors."""

    def __init__(self):
        if settings.embedding_backend.lower() != "fastembed":
            raise ValueError(
                "Only EMBEDDING_BACKEND=fastembed is supported for ingestion embeddings."
            )

        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.device = settings.embedding_device.lower().strip()
        embedding_kwargs = {}
        if self.device == "cuda":
            embedding_kwargs["providers"] = ["CUDAExecutionProvider"]
        self.client = TextEmbedding(
            model_name=self.model,
            cache_dir=settings.embedding_cache_dir,
            local_files_only=settings.embedding_local_files_only,
            **embedding_kwargs,
        )

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        vectors = self.client.embed(texts, batch_size=self.batch_size)
        dense_vectors = [vector.tolist() for vector in vectors]

        for idx, vector in enumerate(dense_vectors):
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension mismatch for item {idx}: "
                    f"model '{self.model}' returned {len(vector)} dimensions, "
                    f"but EMBEDDING_DIMENSIONS={self.dimensions}."
                )

        return dense_vectors

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts using local FastEmbed.

        FastEmbed is synchronous under the hood, so run it in a worker thread to avoid
        blocking the FastAPI event loop during ingestion and query-time embedding.
        """
        if not texts:
            return []

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
