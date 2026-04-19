"""
Cortex Direct RAG Pipeline.
"""

from typing import Any

from google import genai
from google.genai import types

from core.config import settings
from core.logger import get_logger
from indexing.embedder import CortexEmbedder
from indexing.qdrant_store import VectorStore
from models.schemas import QueryResponse, SourceChunk, HistoryMessage

logger = get_logger(__name__)


class RAGPipeline:
    def __init__(self):
        self.embedder = CortexEmbedder()
        self.vector_store = VectorStore()
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY must be set in environment variables.")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = "gemini-2.5-flash"  # Flash for direct RAG speeds

    async def query(
        self,
        user_query: str,
        repo: str | None = None,
        language: str | None = None,
        top_k: int = 7,
        history: list[HistoryMessage] | None = None,
        user_id: str | None = None,
    ) -> QueryResponse:
        """
        Direct Qdrant retrieval -> Gemini generation pipeline.
        Returns the answer and the metadata of the retrieved sources.
        """
        logger.info(f"RAG query: '{user_query}' | Repo: {repo}")

        # 1. Embed query (using the same embedding logic)
        dense_vectors = await self.embedder.embed_batch([user_query])
        dense_query = dense_vectors[0]
        sparse_query = self.embedder.generate_sparse_vector(user_query)

        # 2. Setup filters
        filters = {}
        if repo:
            filters["repo"] = repo
        if language:
            filters["language"] = language

        # 3. Retrieve chunks (tenant-isolated)
        self.vector_store.ensure_collection()
        hits = self.vector_store.search(
            query_dense=dense_query,
            query_sparse=sparse_query,
            filters=filters,
            top_k=top_k,
            user_id=user_id,
        )

        # 4. Context Assembly
        context_parts = []
        source_chunks = []

        for offset, hit in enumerate(hits):
            p = hit["payload"]
            score = hit.get("score", 0.0)

            source_type = p.get("source_type", "unknown")
            file_path = p.get("file_path", "unknown")
            lang = p.get("language", "")
            text = p.get("text", "")
            
            # Additional code metadata
            func_name = p.get("function_name")
            start_line = p.get("start_line")
            end_line = p.get("end_line")

            # Collect source object for response
            source_chunks.append(
                SourceChunk(
                    text=text,
                    source=f"Source [{offset + 1}]",
                    file_path=file_path,
                    language=lang,
                    function_name=func_name,
                    start_line=start_line,
                    end_line=end_line,
                    score=score,
                    source_type=source_type
                )
            )

            # Build readable context block for LLM
            block = f"--- Source [{offset + 1}] ---\n"
            block += f"File: {file_path}\n"
            
            if source_type == "code":
                block += f"Type: Code ({lang})\n"
                if func_name:
                    block += f"Function/Class: {func_name}\n"
                if start_line and end_line:
                    block += f"Lines: {start_line}-{end_line}\n"
                
                # Full body fallback if large_function was used, else standard text
                content_text = p.get("full_body", text)
                block += f"```{lang}\n{content_text}\n```\n"

            elif source_type == "issue":
                issue_num = p.get("issue_number")
                state = p.get("state")
                block += f"Type: Issue #{issue_num} ({state})\n"
                block += f"Content:\n{text}\n"

            elif source_type == "pr":
                pr_num = p.get("pr_number")
                state = p.get("state")
                block += f"Type: Pull Request #{pr_num} ({state})\n"
                block += f"Content:\n{text}\n"

            else:
                # Docs, Config, etc.
                section_title = p.get("section_title")
                if section_title:
                    block += f"Section: {section_title}\n"
                block += f"Content:\n{text}\n"

            context_parts.append(block)

        assembled_context = "\n".join(context_parts)

        # 5. Build prompt
        system_prompt = (
            "You are Cortex, an expert programming assistant that answers questions based on a codebase.\n"
            "You will be provided with retrieved context from various source files, issues, or PRs.\n"
            "RULES:\n"
            "1. Answer ONLY using the provided context. If the answer is not in the context, say you don't know.\n"
            "2. Always cite evidence by explicitly mentioning the file path, function name, and line numbers.\n"
            "3. Format code blocks properly with language tags.\n"
            "4. Be concise, direct, and helpful."
        )

        prompt_text = (
            f"Context from codebase:\n"
            f"{assembled_context}\n\n"
            f"User Question:\n{user_query}\n"
        )

        # 6. Call Gemini
        try:
            logger.info("Calling Gemini 2.5 Flash for RAG generation...")
            # Prepare contents
            contents = []
            
            # System instruction
            generation_config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2, # Low temperature for accurate grounding
            )

            # Add history
            if history:
                messages = []
                for msg in history:
                    if msg.role != "system":
                        gemini_role = "user" if msg.role == "user" else "model"
                        messages.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=msg.content)]))
                
                messages.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)]))
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=messages,
                    config=generation_config
                )
            else:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt_text,
                    config=generation_config
                )

            answer = response.text
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            answer = f"Error generating answer: {e}"

        return QueryResponse(
            answer=answer,
            sources=source_chunks
        )
