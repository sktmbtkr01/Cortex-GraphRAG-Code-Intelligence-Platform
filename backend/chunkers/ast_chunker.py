"""
Cortex AST Chunker — Tree-sitter based code chunking.

Strategy:
  - Unit = one function or one class method (NEVER split mid-function)
  - Standalone functions → one chunk each
  - Class methods → one chunk each, with class_name metadata
  - Module-level code (imports, globals) → one "module_header" chunk
  - If function > 150 lines: signature+docstring for embedding, full body in metadata
  - If file has NO functions: fall back to ContentChunker or generic sliding window

Supported languages: Python, JavaScript, TypeScript, TSX, Go
Unsupported languages: 100-line sliding window with 20-line overlap
"""

import uuid
from typing import Any

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
import tree_sitter_go as tsgo
from tree_sitter import Language, Parser, Node

from models.schemas import Chunk
from core.logger import get_logger

logger = get_logger(__name__)

# ── Language registry ────────────────────────────────────────────────────

_LANGUAGES: dict[str, Language] = {
    "python": Language(tspython.language()),
    "javascript": Language(tsjavascript.language()),
    "typescript": Language(tstypescript.language_typescript()),
    "tsx": Language(tstypescript.language_tsx()),
    "go": Language(tsgo.language()),
}

# Map of language → node types that represent extractable units
_FUNCTION_TYPES: dict[str, list[str]] = {
    "python": ["function_definition", "class_definition"],
    "javascript": [
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ],
    "typescript": [
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ],
    "tsx": [
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ],
    "go": [
        "function_declaration",
        "method_declaration",
        "type_declaration",
    ],
}

LARGE_FUNCTION_THRESHOLD = 150  # lines
GENERIC_WINDOW = 100  # lines for fallback
GENERIC_OVERLAP = 20  # lines


class ASTChunker:
    """Extracts function/class-level chunks from source code using tree-sitter."""

    def chunk(
        self,
        source: str,
        repo: str,
        file_path: str,
        language: str,
    ) -> list[Chunk]:
        """Main entry point. Returns a list of Chunks for the given source file."""
        lang_key = self._normalize_language(language, file_path)

        if lang_key not in _LANGUAGES:
            logger.info(f"No tree-sitter grammar for '{language}', falling back to generic chunker for {file_path}")
            return self._chunk_generic(source, repo, file_path, language)

        ts_lang = _LANGUAGES[lang_key]
        parser = Parser(ts_lang)
        tree = parser.parse(bytes(source, "utf-8"))
        root = tree.root_node
        lines = source.splitlines(keepends=True)

        if lang_key == "python":
            return self._chunk_python(root, lines, source, repo, file_path)
        elif lang_key in ("javascript", "typescript", "tsx"):
            return self._chunk_js_ts(root, lines, source, repo, file_path, lang_key)
        elif lang_key == "go":
            return self._chunk_go(root, lines, source, repo, file_path)
        else:
            return self._chunk_generic(source, repo, file_path, language)

    # ── Python ────────────────────────────────────────────────────────

    def _chunk_python(
        self, root: Node, lines: list[str], source: str, repo: str, file_path: str
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        covered_ranges: list[tuple[int, int]] = []

        for child in root.children:
            if child.type == "function_definition":
                chunk = self._extract_function_chunk(
                    child, lines, source, repo, file_path, "python", class_name=None
                )
                if chunk:
                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "class_definition":
                class_name = self._get_child_by_field(child, "name")
                cls_name_text = class_name.text.decode("utf-8") if class_name else "UnknownClass"

                # Extract each method inside the class
                body = self._get_child_by_field(child, "body")
                if body:
                    for member in body.children:
                        if member.type == "function_definition":
                            chunk = self._extract_function_chunk(
                                member, lines, source, repo, file_path, "python",
                                class_name=cls_name_text,
                            )
                            if chunk:
                                chunks.append(chunk)

                covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "decorated_definition":
                # Handle @decorator\ndef func() or @decorator\nclass Foo
                inner = None
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        inner = sub
                        break
                if inner and inner.type == "function_definition":
                    chunk = self._extract_function_chunk(
                        child, lines, source, repo, file_path, "python", class_name=None
                    )
                    if chunk:
                        chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))
                elif inner and inner.type == "class_definition":
                    class_name = self._get_child_by_field(inner, "name")
                    cls_name_text = class_name.text.decode("utf-8") if class_name else "UnknownClass"
                    body = self._get_child_by_field(inner, "body")
                    if body:
                        for member in body.children:
                            if member.type == "function_definition":
                                chunk = self._extract_function_chunk(
                                    member, lines, source, repo, file_path, "python",
                                    class_name=cls_name_text,
                                )
                                if chunk:
                                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

        # Module header: everything NOT inside a function/class
        header = self._extract_module_header(lines, covered_ranges)
        if header and len(header.strip()) >= 30:
            chunks.insert(
                0,
                Chunk(
                    id=str(uuid.uuid4()),
                    text=header.strip(),
                    repo=repo,
                    file_path=file_path,
                    language="python",
                    source_type="code",
                    chunk_type="module_header",
                    metadata={},
                ),
            )

        if not chunks:
            # Pure script with no functions — use generic fallback
            return self._chunk_generic(source, repo, file_path, "python")

        return chunks

    # ── JavaScript / TypeScript / TSX ─────────────────────────────────

    def _chunk_js_ts(
        self, root: Node, lines: list[str], source: str, repo: str, file_path: str, lang: str
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        covered_ranges: list[tuple[int, int]] = []

        self._walk_js_ts_node(root, lines, source, repo, file_path, lang, chunks, covered_ranges, class_name=None)

        # Module header
        header = self._extract_module_header(lines, covered_ranges)
        if header and len(header.strip()) >= 30:
            chunks.insert(
                0,
                Chunk(
                    id=str(uuid.uuid4()),
                    text=header.strip(),
                    repo=repo,
                    file_path=file_path,
                    language=lang,
                    source_type="code",
                    chunk_type="module_header",
                    metadata={},
                ),
            )

        if not chunks:
            return self._chunk_generic(source, repo, file_path, lang)

        return chunks

    def _walk_js_ts_node(
        self, node: Node, lines: list[str], source: str, repo: str,
        file_path: str, lang: str, chunks: list[Chunk],
        covered_ranges: list[tuple[int, int]], class_name: str | None,
    ) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                chunk = self._extract_function_chunk(child, lines, source, repo, file_path, lang, class_name=class_name)
                if chunk:
                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "class_declaration":
                cls_name_node = self._get_child_by_field(child, "name")
                cls_name = cls_name_node.text.decode("utf-8") if cls_name_node else "UnknownClass"
                body = self._get_child_by_field(child, "body")
                if body:
                    self._walk_js_ts_node(body, lines, source, repo, file_path, lang, chunks, covered_ranges, class_name=cls_name)
                covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "method_definition":
                chunk = self._extract_function_chunk(child, lines, source, repo, file_path, lang, class_name=class_name)
                if chunk:
                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "export_statement":
                # Recurse into export to find the actual declaration
                self._walk_js_ts_node(child, lines, source, repo, file_path, lang, chunks, covered_ranges, class_name=class_name)

            elif child.type in ("lexical_declaration", "variable_declaration"):
                # Check for arrow functions: const foo = async () => { ... }
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        value = self._get_child_by_field(decl, "value")
                        if value and value.type == "arrow_function":
                            chunk = self._extract_function_chunk(
                                child, lines, source, repo, file_path, lang, class_name=class_name
                            )
                            if chunk:
                                chunks.append(chunk)
                                covered_ranges.append((child.start_point.row, child.end_point.row))
                            break

    # ── Go ────────────────────────────────────────────────────────────

    def _chunk_go(
        self, root: Node, lines: list[str], source: str, repo: str, file_path: str
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        covered_ranges: list[tuple[int, int]] = []

        for child in root.children:
            if child.type in ("function_declaration", "method_declaration"):
                chunk = self._extract_function_chunk(child, lines, source, repo, file_path, "go", class_name=None)
                if chunk:
                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

            elif child.type == "type_declaration":
                chunk = self._extract_function_chunk(child, lines, source, repo, file_path, "go", class_name=None)
                if chunk:
                    chunk.chunk_type = "class"  # struct/interface treated as class-level
                    chunks.append(chunk)
                    covered_ranges.append((child.start_point.row, child.end_point.row))

        # Module header (package + imports)
        header = self._extract_module_header(lines, covered_ranges)
        if header and len(header.strip()) >= 30:
            chunks.insert(
                0,
                Chunk(
                    id=str(uuid.uuid4()),
                    text=header.strip(),
                    repo=repo,
                    file_path=file_path,
                    language="go",
                    source_type="code",
                    chunk_type="module_header",
                    metadata={},
                ),
            )

        if not chunks:
            return self._chunk_generic(source, repo, file_path, "go")

        return chunks

    # ── Generic fallback (no AST) ─────────────────────────────────────

    def _chunk_generic(
        self, source: str, repo: str, file_path: str, language: str
    ) -> list[Chunk]:
        """Sliding window: 100-line chunks with 20-line overlap."""
        lines = source.splitlines(keepends=True)
        chunks: list[Chunk] = []

        if len(lines) <= GENERIC_WINDOW:
            if len(source.strip()) >= 30:
                chunks.append(
                    Chunk(
                        id=str(uuid.uuid4()),
                        text=source.strip(),
                        repo=repo,
                        file_path=file_path,
                        language=language,
                        source_type="code",
                        chunk_type="whole_doc",
                        start_line=1,
                        end_line=len(lines),
                        metadata={},
                    )
                )
            return chunks

        start = 0
        while start < len(lines):
            end = min(start + GENERIC_WINDOW, len(lines))
            text = "".join(lines[start:end])

            if len(text.strip()) >= 30:
                chunks.append(
                    Chunk(
                        id=str(uuid.uuid4()),
                        text=text.strip(),
                        repo=repo,
                        file_path=file_path,
                        language=language,
                        source_type="code",
                        chunk_type="function",  # best approximation
                        start_line=start + 1,
                        end_line=end,
                        metadata={"chunking": "generic_window"},
                    )
                )

            if end >= len(lines):
                break
            start = end - GENERIC_OVERLAP

        return chunks

    # ── Shared helpers ────────────────────────────────────────────────

    def _extract_function_chunk(
        self, node: Node, lines: list[str], source: str, repo: str,
        file_path: str, language: str, class_name: str | None,
    ) -> Chunk | None:
        """Extract a single function/method node into a Chunk."""
        start_row = node.start_point.row
        end_row = node.end_point.row
        text = "".join(lines[start_row : end_row + 1])

        if len(text.strip()) < 10:
            return None

        func_name = self._extract_name(node, language)
        signature = self._extract_signature(node, lines, language)
        line_count = end_row - start_row + 1

        chunk_type = "method" if class_name else "function"

        # Large function guardrail
        if line_count > LARGE_FUNCTION_THRESHOLD:
            docstring = self._extract_docstring(node, source, language)
            embed_text = signature
            if docstring:
                embed_text = f"{signature}\n{docstring}"

            return Chunk(
                id=str(uuid.uuid4()),
                text=embed_text.strip(),
                repo=repo,
                file_path=file_path,
                language=language,
                source_type="code",
                chunk_type=chunk_type,
                function_name=func_name,
                class_name=class_name,
                signature=signature,
                start_line=start_row + 1,
                end_line=end_row + 1,
                metadata={"full_body": text, "large_function": True},
            )

        return Chunk(
            id=str(uuid.uuid4()),
            text=text.strip(),
            repo=repo,
            file_path=file_path,
            language=language,
            source_type="code",
            chunk_type=chunk_type,
            function_name=func_name,
            class_name=class_name,
            signature=signature,
            start_line=start_row + 1,
            end_line=end_row + 1,
            metadata={},
        )

    def _extract_name(self, node: Node, language: str) -> str | None:
        """Extract function/class name from a node."""
        # Direct name field
        name_node = self._get_child_by_field(node, "name")
        if name_node:
            return name_node.text.decode("utf-8")

        # JS/TS: arrow function in variable declarator — walk up
        if node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = self._get_child_by_field(child, "name")
                    if name_node:
                        return name_node.text.decode("utf-8")

        # Decorated definition (Python)
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    inner_name = self._get_child_by_field(child, "name")
                    if inner_name:
                        return inner_name.text.decode("utf-8")

        return None

    def _extract_signature(self, node: Node, lines: list[str], language: str) -> str:
        """Extract just the first line(s) that form the signature."""
        start_row = node.start_point.row

        if language == "python":
            # Collect lines until we hit the colon that ends the def line
            sig_lines = []
            for i in range(start_row, min(start_row + 5, len(lines))):
                sig_lines.append(lines[i].rstrip())
                if lines[i].rstrip().endswith(":"):
                    break
            return "\n".join(sig_lines)
        else:
            # JS/TS/Go: first line is typically the full signature
            return lines[start_row].rstrip() if start_row < len(lines) else ""

    def _extract_docstring(self, node: Node, source: str, language: str) -> str | None:
        """Extract docstring from a function node (Python only for now)."""
        if language != "python":
            return None

        # In Python AST, the first expression_statement in the body
        # with a string child is the docstring
        body = self._get_child_by_field(node, "body")
        if not body:
            # Decorated definition
            for child in node.children:
                if child.type == "function_definition":
                    body = self._get_child_by_field(child, "body")
                    break

        if not body or not body.children:
            return None

        first_stmt = body.children[0]
        if first_stmt.type == "expression_statement":
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type == "string":
                return expr.text.decode("utf-8")

        return None

    def _extract_module_header(
        self, lines: list[str], covered_ranges: list[tuple[int, int]]
    ) -> str:
        """Extract lines NOT covered by any function/class definition."""
        header_lines: list[str] = []
        for i, line in enumerate(lines):
            in_range = any(start <= i <= end for start, end in covered_ranges)
            if not in_range:
                header_lines.append(line)

        return "".join(header_lines)

    def _get_child_by_field(self, node: Node, field_name: str) -> Node | None:
        """Safely get a child node by field name."""
        return node.child_by_field_name(field_name)

    def _normalize_language(self, language: str, file_path: str) -> str:
        """Normalize language string to match our registry keys."""
        lang = language.lower().strip()
        lang_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "go": "go",
            "golang": "go",
        }

        if lang in lang_map:
            # Check for TSX/JSX
            if lang == "typescript" and file_path.endswith(".tsx"):
                return "tsx"
            return lang_map[lang]

        # Extension-based fallback
        if file_path.endswith(".tsx"):
            return "tsx"
        elif file_path.endswith(".ts"):
            return "typescript"
        elif file_path.endswith((".js", ".jsx")):
            return "javascript"
        elif file_path.endswith(".py"):
            return "python"
        elif file_path.endswith(".go"):
            return "go"

        return lang  # unknown — will fall through to generic
