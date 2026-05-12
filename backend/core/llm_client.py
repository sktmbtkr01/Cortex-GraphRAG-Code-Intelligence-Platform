from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class CortexLLMClient:
    """Switches Cortex generation between Gemini API keys and Vertex AI Gemini."""

    def __init__(self, model: str | None = None):
        self.backend = settings.llm_backend.lower().strip()
        self.model = model or settings.vertex_llm_model
        if self.backend == "vertex":
            if not settings.vertex_project_id:
                raise ValueError("VERTEX_PROJECT_ID is required when LLM_BACKEND=vertex.")
            self.client = genai.Client(
                vertexai=True,
                project=settings.vertex_project_id,
                location=settings.vertex_location,
            )
        elif self.backend == "gemini_api":
            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_BACKEND=gemini_api.")
            self.client = genai.Client(api_key=settings.gemini_api_key)
        else:
            raise ValueError("Unsupported LLM_BACKEND. Expected 'gemini_api' or 'vertex'.")

    async def generate_content(
        self,
        contents: str | Sequence[types.Content],
        system_instruction: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        attempts = max(1, settings.llm_retry_attempts)

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_not_exception_type((ValueError, TypeError)),
        )
        async def call_llm() -> Any:
            active_model = model or self.model
            logger.info("Calling %s LLM model '%s'.", self.backend, active_model)
            return await self.client.aio.models.generate_content(
                model=active_model,
                contents=contents,
                config=config,
            )

        response = await call_llm()
        return response.text or ""
