"""
Cortex Content-Aware Chunker for non-code files.

Strategy (tailored to a code intelligence platform):
  - Docs (.md, .rst, .txt)  → Section-based: split at header boundaries
  - Issues / PRs             → Whole-document: one chunk per item (they're short)
  - Configs (.yaml, .json)   → Whole-document: one chunk per file

Why NOT parent-child?
  Parent-child chunking (FinIntel-style) is designed for long, dense PDFs.
  In Cortex, most non-code content is short (issues ~300 words, configs ~50 lines).
  Splitting them into parent/child fragments destroys context and doubles storage.
"""

import re
import uuid

from models.schemas import Chunk


class ContentChunker:
    """Routes non-code content to the appropriate chunking strategy."""

    def __init__(self, max_section_chars: int = 1500):
        self.max_section_chars = max_section_chars

    def chunk(
        self,
        text: str,
        repo: str,
        file_path: str,
        language: str,
        source_type: str,
        metadata: dict | None = None,
    ) -> list[Chunk]:
        """Dispatch to the right strategy based on source_type."""
        if metadata is None:
            metadata = {}

        if source_type == "docs":
            return self._chunk_doc(text, repo, file_path, language, metadata)
        else:
            # Issues, PRs, configs → whole-document, single chunk
            return self._chunk_whole(text, repo, file_path, language, source_type, metadata)

    # ------------------------------------------------------------------
    # Strategy 1: Section-based chunking for documentation
    # ------------------------------------------------------------------

    def _chunk_doc(
        self, text: str, repo: str, file_path: str, language: str, metadata: dict
    ) -> list[Chunk]:
        """Split markdown/rst at header boundaries. Sub-split oversized sections."""
        sections = self._split_at_headers(text)
        chunks: list[Chunk] = []

        for title, body in sections:
            # Skip trivially small sections
            if len(body.strip()) < 30:
                continue

            if len(body) <= self.max_section_chars:
                # Fits in one chunk — keep it whole
                chunks.append(
                    Chunk(
                        id=str(uuid.uuid4()),
                        text=body.strip(),
                        repo=repo,
                        file_path=file_path,
                        language=language,
                        source_type="docs",
                        chunk_type="section",
                        section_title=title,
                        metadata=metadata,
                    )
                )
            else:
                # Oversized section — sub-split at paragraph boundaries
                paragraphs = self._split_at_paragraphs(body, self.max_section_chars)
                for i, para in enumerate(paragraphs):
                    if len(para.strip()) < 30:
                        continue
                    chunks.append(
                        Chunk(
                            id=str(uuid.uuid4()),
                            text=para.strip(),
                            repo=repo,
                            file_path=file_path,
                            language=language,
                            source_type="docs",
                            chunk_type="section",
                            section_title=f"{title} (part {i + 1})" if title else None,
                            metadata=metadata,
                        )
                    )

        # Edge case: file with no headers at all → treat as whole doc
        if not chunks and len(text.strip()) >= 30:
            chunks.append(
                Chunk(
                    id=str(uuid.uuid4()),
                    text=text.strip(),
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    source_type="docs",
                    chunk_type="whole_doc",
                    metadata=metadata,
                )
            )

        return chunks

    def _split_at_headers(self, text: str) -> list[tuple[str | None, str]]:
        """Split markdown text at header lines (# ## ### etc.).

        Returns list of (section_title, section_body) tuples.
        Content before the first header gets title=None.
        """
        # Match lines that start with 1-6 '#' chars followed by a space
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        matches = list(header_pattern.finditer(text))

        if not matches:
            return [(None, text)]

        sections: list[tuple[str | None, str]] = []

        # Content before the first header
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append((None, preamble))

        for i, match in enumerate(matches):
            title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()

            # Prepend the header line itself so the chunk is self-contained
            full_body = f"{match.group(0).strip()}\n{body}" if body else match.group(0).strip()
            sections.append((title, full_body))

        return sections

    def _split_at_paragraphs(self, text: str, max_chars: int) -> list[str]:
        """Split text at double-newline paragraph boundaries, merging short ones."""
        paragraphs = re.split(r"\n\n+", text)
        result: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 <= max_chars:
                current = f"{current}\n\n{para}" if current else para
            else:
                if current:
                    result.append(current)
                # If a single paragraph exceeds max, include it as-is
                current = para

        if current:
            result.append(current)

        return result

    # ------------------------------------------------------------------
    # Strategy 2: Whole-document chunking (issues, PRs, configs)
    # ------------------------------------------------------------------

    def _chunk_whole(
        self,
        text: str,
        repo: str,
        file_path: str,
        language: str,
        source_type: str,
        metadata: dict,
    ) -> list[Chunk]:
        """One item = one chunk. Only split if body exceeds 2000 chars (rare)."""
        if len(text.strip()) < 30:
            return []

        if len(text) <= 2000:
            return [
                Chunk(
                    id=str(uuid.uuid4()),
                    text=text.strip(),
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    source_type=source_type,
                    chunk_type="whole_doc",
                    issue_number=metadata.get("issue_number"),
                    pr_number=metadata.get("pr_number"),
                    state=metadata.get("state"),
                    labels=metadata.get("labels", []),
                    metadata=metadata,
                )
            ]

        # Rare: oversized issue/PR body — split at paragraphs
        parts = self._split_at_paragraphs(text, 1500)
        chunks: list[Chunk] = []
        for part in parts:
            if len(part.strip()) < 30:
                continue
            chunks.append(
                Chunk(
                    id=str(uuid.uuid4()),
                    text=part.strip(),
                    repo=repo,
                    file_path=file_path,
                    language=language,
                    source_type=source_type,
                    chunk_type="whole_doc",
                    issue_number=metadata.get("issue_number"),
                    pr_number=metadata.get("pr_number"),
                    state=metadata.get("state"),
                    labels=metadata.get("labels", []),
                    metadata=metadata,
                )
            )
        return chunks
