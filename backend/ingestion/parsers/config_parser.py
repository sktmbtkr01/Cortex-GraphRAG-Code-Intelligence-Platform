import json
import tomllib

from ingestion.parsers import ParsedFile

def flatten_dict(d: dict, parent_key: str = '', sep: str = '.') -> dict:
    """Recursively flatten a nested dictionary into key-value pairs."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def parse(content: str, path: str, language: str) -> ParsedFile:
    """Parse JSON/TOML into flattened key-value strings. Leaves YAML/INI as-is."""
    flat_content = ""
    try:
        if path.endswith(".json"):
            data = json.loads(content)
            if isinstance(data, dict):
                flat_dict = flatten_dict(data)
                flat_content = "\n".join(f"{k} = {v}" for k, v in flat_dict.items())
            else:
                flat_content = content
        elif path.endswith(".toml"):
            data = tomllib.loads(content)
            flat_dict = flatten_dict(data)
            flat_content = "\n".join(f"{k} = {v}" for k, v in flat_dict.items())
        else:
            # YAML or INI, just return as is (unless we add pyyaml to requirements)
            flat_content = content
    except Exception:
        flat_content = content  # Fallback to plain string if invalid structure
        
    return ParsedFile(
        path=path,
        language=language,
        source_type="config",
        content=flat_content,
        metadata={}
    )
