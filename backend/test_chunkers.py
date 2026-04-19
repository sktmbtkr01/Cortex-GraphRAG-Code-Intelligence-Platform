"""Phase 2 verification: test all chunkers against synthetic code samples."""

from chunkers.ast_chunker import ASTChunker
from chunkers.prose_chunker import ContentChunker


def divider(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── TEST 1: Python file with functions + class ───────────────────────

PYTHON_SOURCE = '''
import os
import sys

DB_URL = "postgresql://localhost:5432/mydb"

def connect_db(url: str) -> object:
    """Connect to the database and return a connection object."""
    print(f"Connecting to {url}")
    return {"connection": url}

def close_db(conn: object) -> None:
    """Close the database connection."""
    conn = None

class AuthManager:
    """Handles authentication logic."""

    def __init__(self, secret: str):
        self.secret = secret

    def verify_token(self, token: str) -> dict:
        """Verify a JWT token and return claims."""
        if not token:
            raise ValueError("Token is required")
        return {"sub": "user123", "exp": 9999}

def main():
    conn = connect_db(DB_URL)
    auth = AuthManager("my_secret")
    result = auth.verify_token("fake_token")
    print(result)
    close_db(conn)
'''

def test_python_chunking():
    divider("TEST 1: Python chunking (3 functions + 1 class with 2 methods)")
    chunker = ASTChunker()
    chunks = chunker.chunk(PYTHON_SOURCE, "test/repo", "src/db.py", "python")
    
    for c in chunks:
        print(f"  [{c.chunk_type}] {c.function_name or c.class_name or '(header)'} | lines {c.start_line}-{c.end_line} | {len(c.text)} chars")
    
    funcs = [c for c in chunks if c.chunk_type in ("function", "method")]
    headers = [c for c in chunks if c.chunk_type == "module_header"]
    
    print(f"\n  Total chunks: {len(chunks)}")
    print(f"  Functions/methods: {len(funcs)}")
    print(f"  Module headers: {len(headers)}")
    
    # Verify
    assert len(funcs) >= 5, f"Expected ≥5 function/method chunks, got {len(funcs)}"
    assert any(c.function_name == "verify_token" and c.class_name == "AuthManager" for c in chunks), \
        "verify_token should have class_name=AuthManager"
    print("  ✅ PASSED")


# ── TEST 2: Function boundaries intact ────────────────────────────────

def test_function_boundaries():
    divider("TEST 2: Function boundaries are intact")
    chunker = ASTChunker()
    chunks = chunker.chunk(PYTHON_SOURCE, "test/repo", "src/db.py", "python")
    
    for c in chunks:
        if c.chunk_type in ("function", "method"):
            first_line = c.text.splitlines()[0].strip()
            last_line = c.text.splitlines()[-1].strip()
            print(f"  {c.function_name}: first='{first_line[:50]}' | last='{last_line[:50]}'")
            assert "def " in first_line or "@" in first_line, f"Chunk doesn't start with def: {first_line}"
    
    print("  ✅ PASSED")


# ── TEST 3: Metadata populated ────────────────────────────────────────

def test_metadata():
    divider("TEST 3: Metadata is populated")
    chunker = ASTChunker()
    chunks = chunker.chunk(PYTHON_SOURCE, "test/repo", "src/db.py", "python")
    
    for c in chunks:
        if c.chunk_type in ("function", "method"):
            assert c.function_name is not None, f"Missing function_name on {c.text[:30]}"
            assert c.start_line is not None, f"Missing start_line on {c.function_name}"
            assert c.end_line is not None, f"Missing end_line on {c.function_name}"
            assert c.signature is not None, f"Missing signature on {c.function_name}"
            print(f"  ✓ {c.function_name}: sig='{c.signature[:60]}', lines={c.start_line}-{c.end_line}")
    
    print("  ✅ PASSED")


# ── TEST 4: JavaScript arrow functions ────────────────────────────────

JS_SOURCE = '''
import express from 'express';

const app = express();

const handler = async (req, res) => {
    const data = await fetchData();
    res.json(data);
};

function authenticate(token) {
    if (!token) throw new Error("No token");
    return { valid: true };
}

class UserService {
    constructor(db) {
        this.db = db;
    }

    async getUser(id) {
        return this.db.find(id);
    }
}

export default app;
'''

def test_js_chunking():
    divider("TEST 4: JavaScript arrow functions + classes")
    chunker = ASTChunker()
    chunks = chunker.chunk(JS_SOURCE, "test/repo", "src/app.js", "javascript")
    
    for c in chunks:
        print(f"  [{c.chunk_type}] {c.function_name or '(header)'} | {len(c.text)} chars")
    
    names = [c.function_name for c in chunks if c.function_name]
    print(f"\n  Captured names: {names}")
    assert "handler" in names, "Arrow function 'handler' should be captured"
    assert "authenticate" in names, "Function 'authenticate' should be captured"
    print("  ✅ PASSED")


# ── TEST 5: Markdown section-based chunking ───────────────────────────

MD_SOURCE = '''# My Project

This is the introduction to my project.

## Installation

Run `pip install myproject` to install.

### Requirements

- Python 3.10+
- PostgreSQL 14+

## Usage

```python
from myproject import run
run()
```

## Contributing

Please read CONTRIBUTING.md before submitting PRs.

## License

MIT License.
'''

def test_md_chunking():
    divider("TEST 5: Markdown section-based chunking")
    chunker = ContentChunker()
    chunks = chunker.chunk(MD_SOURCE, "test/repo", "README.md", "markdown", "docs")
    
    for c in chunks:
        print(f"  [{c.chunk_type}] title='{c.section_title}' | {len(c.text)} chars")
    
    section_chunks = [c for c in chunks if c.chunk_type == "section"]
    print(f"\n  Total section chunks: {len(section_chunks)}")
    assert len(section_chunks) >= 4, f"Expected ≥4 section chunks from a README with 5 headers, got {len(section_chunks)}"
    assert all(c.section_title is not None for c in section_chunks), "All section chunks should have section_title"
    print("  ✅ PASSED")


# ── TEST 6: Issues stay as whole documents ────────────────────────────

def test_issue_whole_doc():
    divider("TEST 6: Issues/PRs stay as whole documents")
    chunker = ContentChunker()
    
    issue_text = (
        'Issue #42: "Login fails on Safari" (state: open, labels: [bug, auth])\n'
        'Opened by: alice on 2026-03-15\n'
        'Body: When clicking the login button on Safari 17, the page redirects '
        'to a blank screen instead of the dashboard. This only happens when '
        'cookies are disabled. Steps to reproduce: 1) Open Safari 2) Disable '
        'cookies 3) Navigate to /login 4) Click "Sign In".'
    )
    
    chunks = chunker.chunk(
        issue_text, "test/repo", "issue_42", "markdown", "issue",
        metadata={"issue_number": 42, "state": "open", "labels": ["bug", "auth"]}
    )
    
    for c in chunks:
        print(f"  [{c.chunk_type}] issue_number={c.issue_number} | {len(c.text)} chars")
    
    assert len(chunks) == 1, f"Expected exactly 1 chunk for a short issue, got {len(chunks)}"
    assert chunks[0].chunk_type == "whole_doc", f"Expected chunk_type='whole_doc', got '{chunks[0].chunk_type}'"
    assert chunks[0].issue_number == 42, "issue_number should be 42"
    print("  ✅ PASSED")


# ── TEST 7: Generic fallback ─────────────────────────────────────────

def test_generic_fallback():
    divider("TEST 7: Generic fallback for unsupported languages")
    chunker = ASTChunker()
    
    # Simulate a long Rust file (no tree-sitter grammar in our setup)
    rust_source = "\n".join([f"fn line_{i}() {{ /* line {i} */ }}" for i in range(250)])
    
    chunks = chunker.chunk(rust_source, "test/repo", "src/main.rs", "rust")
    
    for c in chunks:
        print(f"  [{c.chunk_type}] lines {c.start_line}-{c.end_line} | {len(c.text)} chars")
    
    assert len(chunks) >= 3, f"Expected ≥3 window chunks for 250 lines, got {len(chunks)}"
    print("  ✅ PASSED")


# ── TEST 8: Giant function handling ───────────────────────────────────

def test_giant_function():
    divider("TEST 8: Giant function (>150 lines) handling")
    chunker = ASTChunker()
    
    body_lines = "\n".join([f"    x_{i} = {i}" for i in range(200)])
    giant_source = f'''
def giant_function(a: int, b: str, c: float) -> dict:
    """This is a very large function that processes data.
    
    Args:
        a: First parameter
        b: Second parameter
        c: Third parameter
    """
{body_lines}
    return {{"result": x_199}}
'''
    
    chunks = chunker.chunk(giant_source, "test/repo", "src/big.py", "python")
    
    for c in chunks:
        is_large = c.metadata.get("large_function", False)
        print(f"  [{c.chunk_type}] {c.function_name} | {len(c.text)} chars | large={is_large}")
    
    func_chunks = [c for c in chunks if c.function_name == "giant_function"]
    assert len(func_chunks) == 1, f"Expected 1 chunk for giant_function, got {len(func_chunks)}"
    assert func_chunks[0].metadata.get("large_function") is True, "Should be marked as large_function"
    assert "full_body" in func_chunks[0].metadata, "Should store full_body in metadata"
    assert len(func_chunks[0].text) < len(giant_source) // 2, "Embed text should be much shorter than full body"
    print("  ✅ PASSED")


# ── Run all tests ─────────────────────────────────────────────────────

if __name__ == "__main__":
    test_python_chunking()
    test_function_boundaries()
    test_metadata()
    test_js_chunking()
    test_md_chunking()
    test_issue_whole_doc()
    test_generic_fallback()
    test_giant_function()
    
    print(f"\n{'='*60}")
    print("  ALL PHASE 2 TESTS PASSED ✅")
    print(f"{'='*60}")
