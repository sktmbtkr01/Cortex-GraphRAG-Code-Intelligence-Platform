from ingestion.parsers import ParsedFile

def parse(content: str, path: str, language: str) -> ParsedFile:
    line_count = len(content.splitlines())
    return ParsedFile(
        path=path,
        language=language,
        source_type="code",
        content=content,
        metadata={"line_count": line_count}
    )
