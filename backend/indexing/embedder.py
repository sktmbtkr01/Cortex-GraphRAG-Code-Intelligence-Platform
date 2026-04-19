"""
Cortex Embedder — Handles dense + sparse embedding generation.
"""

import asyncio
import hashlib
from typing import Any

from google import genai
from google.genai import types

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class CortexEmbedder:
    """Generates embeddings using Gemini (dense) and BM25-style hashing (sparse)."""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment variables.")

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.embedding_model  # Default: text-embedding-004
        self.dimensions = settings.embedding_dimensions  # Default: 768

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts using Gemini API.
        Automatically limits batch size.
        """
        if not texts:
            return []

        # The Gemini embed_content API can take a list of strings
        # We enforce a max batch size of 100
        BATCH_SIZE = 100
        all_embeddings = []

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            
            # Use exponential backoff for rate limits
            retries = 3
            delay = 2
            
            while retries > 0:
                try:
                    response = await asyncio.to_thread(
                        self.client.models.embed_content,
                        model=self.model,
                        contents=batch,
                        config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
                    )
                    
                    # response.embeddings is a list of Embedding objects
                    for emb in response.embeddings:
                        all_embeddings.append(emb.values)
                        
                    break  # Success
                    
                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        logger.warning(f"Rate limit hit embedding batch {i}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        retries -= 1
                        delay *= 2
                    else:
                        logger.error(f"Failed to embed batch: {e}")
                        raise e
            
            if retries == 0:
                logger.error("Failed to embed batch after 3 retries due to rate limits.")
                raise RuntimeError("Embedding rate limit exceeded.")

        return all_embeddings

    def generate_sparse_vector(self, text: str) -> dict[str, Any]:
        """
        Generates a simplistic sparse vector for hybrid search.
        Ports the FinIntel BM25 logic using token hashing.
        Returns format: {"indices": [int, ...], "values": [float, ...]}
        """
        # Lowercase, clean non-alphanumeric, split
        clean_text = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in text)
        tokens = clean_text.split()
        
        # We need a stable vocabulary space, usually 48000+ for Qdrant.
        # We'll use a hashing trick to map tokens to indices in a 1,000,000 dimensional space
        VOCAB_SIZE = 1_000_000
        
        counts: dict[int, int] = {}
        for token in tokens:
            if len(token) < 2:  # Skip single letters/digits
                continue
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % VOCAB_SIZE
            counts[idx] = counts.get(idx, 0) + 1
            
        # BM25-lite term frequency formulation: tf / (tf + 0.5)
        # (This is a naive approximation for Qdrant hybrid fusion)
        indices = []
        values = []
        for idx, count in sorted(counts.items()):
            indices.append(idx)
            values.append(count / (count + 0.5))
            
        return {"indices": indices, "values": values}
