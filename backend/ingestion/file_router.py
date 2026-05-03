import fnmatch
from ingestion.parsers import ParsedFile
from ingestion.parsers import code_parser, markdown_parser, config_parser

INCLUDE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cs", ".rb", ".php",
    ".md", ".rst", ".txt", ".mdx",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".ipynb"
}

EXCLUDE_PATTERNS = [
    "*/node_modules/*", "*/.git/*", "*/dist/*", "*/build/*", "*/__pycache__/*",
    "*.min.js", "*.min.css", "*.pb.go", "*_generated.*", "*.lock", "package-lock.json", "yarn.lock"
]

def should_process_file(path: str, size: int) -> bool:
    """Determine if a file should be ingested based on path and size."""
    # Exclude files larger than 500KB
    if size > 500 * 1024:
        return False
    
    leaf = path.split("/")[-1]
    
    # Check exact excluded filenames
    if leaf in ["package-lock.json", "yarn.lock"]:
        return False
        
    # Check glob patterns
    # Normalize path to ensure leading match if needed, though fnmatch expects exact match.
    # It's better to prepend with / to simulate absolute search for */ pattern.
    test_path = f"/{path}"
    for p in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(test_path, p) or fnmatch.fnmatch(leaf, p):
            return False
            
    # Check explicit inclusions
    if leaf == ".env.example":
        return True
        
    parts = leaf.rsplit(".", 1)
    if len(parts) == 1:
        return False  # Skip files with no extension
        
    ext = f".{parts[-1].lower()}"
    if ext not in INCLUDE_EXTS:
        return False
        
    return True

def route_file(path: str, content: str) -> ParsedFile:
    """Route file content to the appropriate parser based on extension."""
    leaf = path.split("/")[-1]
    
    if leaf == ".env.example":
        ext = ".env"
    else:
        parts = leaf.rsplit(".", 1)
        ext = f".{parts[-1].lower()}" if len(parts) > 1 else ""
        
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cs", ".rb", ".php"}
    doc_exts = {".md", ".rst", ".txt", ".mdx"}
    config_exts = {".yaml", ".yml", ".json", ".toml", ".ini", ".env", ".ipynb"}
    
    # Basic extension-to-language mapping
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "javascript", ".tsx": "typescript",
        ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".md": "markdown", ".rst": "restructuredtext", ".txt": "text", ".mdx": "markdown",
        ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml", ".ini": "ini", ".env": "env", ".ipynb": "notebook"
    }
    lang = lang_map.get(ext, "unknown")
    
    if ext in code_exts:
        return code_parser.parse(content, path, lang)
    elif ext in doc_exts:
        return markdown_parser.parse(content, path, lang)
    elif ext in config_exts:
        return config_parser.parse(content, path, lang)
    else:
        # Fallback
        return code_parser.parse(content, path, lang)
