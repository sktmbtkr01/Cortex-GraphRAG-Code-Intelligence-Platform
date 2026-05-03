import asyncio
import sys
import unittest

import httpx

from api import webhook
from core.config import settings
from core.job_store import JobStore
from core.tenant import tenant_scoped_id
from ingestion.github_client import _is_retryable_github_error
from ingestion.pipeline import IngestionPipeline
from ingestion.secret_scanner import count_secret_matches, redact_text
from indexing.qdrant_store import generate_chunk_id
from models.schemas import Chunk
from chunkers.ast_chunker import ASTChunker
from chunkers.prose_chunker import ContentChunker


class Phase7VerificationTests(unittest.TestCase):
    def test_local_embedding_config_is_768_dimensional(self):
        self.assertEqual(settings.embedding_backend, "fastembed")
        self.assertEqual(settings.embedding_model, "BAAI/bge-base-en-v1.5")
        self.assertEqual(settings.embedding_dimensions, 768)

    def test_qdrant_chunk_ids_are_tenant_scoped(self):
        chunk_a = Chunk(
            id="",
            repo="owner/repo",
            file_path="src/app.py",
            text="def hello(): pass",
            language="python",
            source_type="code",
            chunk_type="function",
            user_id="github:1",
        )
        chunk_b = Chunk(
            id="",
            repo="owner/repo",
            file_path="src/app.py",
            text="def hello(): pass",
            language="python",
            source_type="code",
            chunk_type="function",
            user_id="github:2",
        )

        self.assertNotEqual(generate_chunk_id(chunk_a), generate_chunk_id(chunk_b))
        self.assertEqual(tenant_scoped_id("owner/repo", "github:1"), "github:1::owner/repo")

    def test_secret_redaction_happens_before_chunking(self):
        secret = 'api_key = "AAAAAAAAAAAAAAAAAAAA"'
        content = (
            'name = "demo-service"\n'
            'description = "configuration for phase seven verification"\n'
            f"{secret}\n"
        )

        self.assertEqual(count_secret_matches(content), 1)
        self.assertNotIn("AAAAAAAAAAAAAAAAAAAA", redact_text(content))

        pipeline = IngestionPipeline.__new__(IngestionPipeline)
        pipeline.ast_chunker = ASTChunker()
        pipeline.content_chunker = ContentChunker()
        result = pipeline._process_single_file_content(
            {"path": "settings.toml"},
            content,
            "owner/repo",
            "github:1",
            False,
        )

        self.assertEqual(result["secrets_redacted"], 1)
        self.assertTrue(result["chunks"])
        indexed_text = "\n".join(chunk.text for chunk in result["chunks"])
        indexed_metadata = "\n".join(str(chunk.metadata) for chunk in result["chunks"])
        self.assertIn("[REDACTED]", indexed_text)
        self.assertNotIn("AAAAAAAAAAAAAAAAAAAA", indexed_text)
        self.assertNotIn("AAAAAAAAAAAAAAAAAAAA", indexed_metadata)
        self.assertTrue(all(chunk.metadata.get("security_censored") for chunk in result["chunks"]))

    def test_github_retry_classifier_only_retries_transient_errors(self):
        request = httpx.Request("GET", "https://api.github.com/repos/octocat/Hello-World")

        def status_error(status_code: int) -> httpx.HTTPStatusError:
            response = httpx.Response(status_code, request=request)
            return httpx.HTTPStatusError("status", request=request, response=response)

        for status_code in (429, 502, 503, 504):
            self.assertTrue(_is_retryable_github_error(status_error(status_code)))

        for status_code in (401, 403, 404, 422):
            self.assertFalse(_is_retryable_github_error(status_error(status_code)))

        self.assertTrue(_is_retryable_github_error(httpx.ConnectError("boom", request=request)))

    def test_job_store_caps_events_and_reports_lost_jobs(self):
        async def run_check():
            store = JobStore(max_age_seconds=3600, max_events_per_job=3)
            job_id = store.create_job("github:1", "owner/repo")
            for index in range(5):
                await store.publish(
                    job_id,
                    {
                        "type": "progress",
                        "state": "running",
                        "stage": f"s{index}",
                        "message": str(index),
                    },
                )

            events, cursor, done = store.get_events_since(job_id, 0)
            self.assertEqual(len(events), 3)
            self.assertEqual(cursor, 6)
            self.assertEqual(events[0]["stage"], "s2")
            self.assertFalse(done)

            lost_events, _, lost_done = store.get_events_since("missing", 0)
            self.assertTrue(lost_done)
            self.assertEqual(lost_events[0]["state"], "lost")

        asyncio.run(run_check())

    def test_webhooks_do_not_mutate_without_tenant_mapping(self):
        async def run_check():
            calls = []
            original_process = webhook.process_added_modified_file
            original_delete = webhook.delete_file_from_index

            async def fake_process(*args, **kwargs):
                calls.append(("process", args, kwargs))

            def fake_delete(*args, **kwargs):
                calls.append(("delete", args, kwargs))

            try:
                webhook.process_added_modified_file = fake_process
                webhook.delete_file_from_index = fake_delete
                await webhook.handle_push_event(
                    {
                        "repository": {
                            "full_name": "owner/repo",
                            "owner": {"login": "owner"},
                            "name": "repo",
                        },
                        "ref": "refs/heads/main",
                        "commits": [
                            {
                                "added": ["src/app.py"],
                                "modified": ["README.md"],
                                "removed": ["old.py"],
                            }
                        ],
                    }
                )
            finally:
                webhook.process_added_modified_file = original_process
                webhook.delete_file_from_index = original_delete

            self.assertEqual(calls, [])

        asyncio.run(run_check())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
