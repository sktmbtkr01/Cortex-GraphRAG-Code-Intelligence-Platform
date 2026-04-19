import re
from core.logger import get_logger

logger = get_logger(__name__)

SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}',
    r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?.{8,}',
    r'ghp_[A-Za-z0-9]{36}',          # GitHub PAT
    r'sk-[A-Za-z0-9]{48}',            # OpenAI key
    r'AIza[A-Za-z0-9_\-]{35}',        # Google API key
    r'(?i)aws_access_key_id\s*=\s*[A-Z0-9]{20}',
]

def scan_text(text: str) -> bool:
    """Returns True if the text contains a suspected secret."""
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

def redact_text(text: str) -> str:
    """Replaces detected secrets with [REDACTED]."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    return redacted
