class IngestionPipeline:
    """Phase 1+ will coordinate GitHub fetch, parsing, chunking, indexing, and graph writes."""

    async def ingest_repo(self, repo: str, branch: str = "main") -> None:
        raise NotImplementedError("Ingestion pipeline is implemented in Phase 1.")
