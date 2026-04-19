import re
from bs4 import BeautifulSoup
from ingestion.parsers import ParsedFile


def parse(content: str, path: str, language: str) -> ParsedFile:
    """Strip HTML tags and normalize whitespace."""
    if bool(BeautifulSoup(content, "html.parser").find()):
        soup = BeautifulSoup(content, 'html.parser')
        clean_text = soup.get_text(separator=' ')
    else:
        clean_text = content

    # Normalize whitespace
    clean_text = re.sub(r'[ \t]+', ' ', clean_text)
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)

    return ParsedFile(
        path=path,
        language=language,
        source_type="docs",
        content=clean_text.strip(),
        metadata={}
    )
