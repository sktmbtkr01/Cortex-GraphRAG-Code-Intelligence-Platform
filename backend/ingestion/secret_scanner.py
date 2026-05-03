import re
from core.logger import get_logger

logger = get_logger(__name__)

SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}["\']?',
    r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?[A-Za-z0-9_\-\/+=]{12,}["\']?',
    r'ghp_[A-Za-z0-9]{36}',          # GitHub PAT
    r'sk-[A-Za-z0-9]{48}',            # OpenAI key
    r'AIza[A-Za-z0-9_\-]{35}',        # Google API key
    r'(?i)aws_access_key_id\s*=\s*[A-Z0-9]{20}',
]

COMPILED_SECRET_PATTERNS = [re.compile(pattern) for pattern in SECRET_PATTERNS]
REDACTION_PATTERNS = [
    (
        re.compile(r'(?i)((?:api[_-]?key|apikey)\s*[=:]\s*)["\']?[A-Za-z0-9_\-]{20,}["\']?'),
        r'\1"[REDACTED]"',
    ),
    (
        re.compile(r'(?i)((?:secret|password|passwd|pwd)\s*[=:]\s*)["\']?[A-Za-z0-9_\-\/+=]{12,}["\']?'),
        r'\1"[REDACTED]"',
    ),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "[REDACTED]"),
    (re.compile(r'sk-[A-Za-z0-9]{48}'), "[REDACTED]"),
    (re.compile(r'AIza[A-Za-z0-9_\-]{35}'), "[REDACTED]"),
    (
        re.compile(r'(?i)(aws_access_key_id\s*=\s*)[A-Z0-9]{20}'),
        r'\1"[REDACTED]"',
    ),
]


def count_secret_matches(text: str) -> int:
    """Return the number of suspected secret occurrences without exposing values."""
    return sum(len(pattern.findall(text)) for pattern in COMPILED_SECRET_PATTERNS)


def scan_text(text: str) -> bool:
    """Returns True if the text contains a suspected secret."""
    return count_secret_matches(text) > 0


def redact_text(text: str) -> str:
    """Replaces detected secrets with [REDACTED]."""
    redacted = text
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
