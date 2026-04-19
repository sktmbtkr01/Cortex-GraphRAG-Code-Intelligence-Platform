from dataclasses import dataclass, field

@dataclass
class ParsedFile:
    path: str
    language: str
    source_type: str  # "code", "docs", "issue", "pr", "config"
    content: str
    metadata: dict = field(default_factory=dict)
