import asyncio
from ingestion.pipeline import IngestionPipeline
from core.logger import configure_logging

configure_logging("DEBUG")

async def test():
    pipeline = IngestionPipeline()
    stats = await pipeline.ingest_repo("octocat/hello-world", "master", include_issues=False, include_prs=False)
    print(stats)

if __name__ == "__main__":
    asyncio.run(test())
