from ingestion.parsers import ParsedFile

def parse(pr: dict, files: list[dict] | None = None) -> ParsedFile:
    """Convert GitHub PR JSON into readable prose."""
    number = pr.get("number")
    title = pr.get("title", "")
    state = pr.get("state", "open")
    labels = [l.get("name") for l in pr.get("labels", []) if isinstance(l, dict) and l.get("name")]
    user = pr.get("user", {}).get("login", "unknown")
    created_at = pr.get("created_at", "")
    body = pr.get("body") or ""
    
    base_branch = pr.get("base", {}).get("ref", "unknown")
    head_branch = pr.get("head", {}).get("ref", "unknown")

    labels_str = f", labels: [{', '.join(labels)}]" if labels else ""
    
    content = (
        f"Pull Request #{number}: \"{title}\" (state: {state}{labels_str})\n"
        f"Base: {base_branch} <- Head: {head_branch}\n"
        f"Opened by: {user} on {created_at}\n"
        f"Body: {body}\n"
    )

    if files:
        content += "\nModified Files:\n"
        for f in files:
            content += f"- {f.get('filename')} (status: {f.get('status')}, additions: {f.get('additions')}, deletions: {f.get('deletions')})\n"

    return ParsedFile(
        path=f"pr_{number}",
        language="markdown",
        source_type="pr",
        content=content,
        metadata={
            "pr_number": number,
            "state": state,
            "labels": labels
        }
    )
