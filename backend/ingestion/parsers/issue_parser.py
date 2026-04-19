from ingestion.parsers import ParsedFile

def parse(issue: dict) -> ParsedFile:
    """Convert GitHub issue JSON into readable prose."""
    number = issue.get("number")
    title = issue.get("title", "")
    state = issue.get("state", "open")
    labels = [l.get("name") for l in issue.get("labels", []) if isinstance(l, dict) and l.get("name")]
    user = issue.get("user", {}).get("login", "unknown")
    created_at = issue.get("created_at", "")
    body = issue.get("body") or ""

    labels_str = f", labels: [{', '.join(labels)}]" if labels else ""
    
    content = (
        f"Issue #{number}: \"{title}\" (state: {state}{labels_str})\n"
        f"Opened by: {user} on {created_at}\n"
        f"Body: {body}"
    )

    return ParsedFile(
        path=f"issue_{number}",
        language="markdown",
        source_type="issue",
        content=content,
        metadata={
            "issue_number": number,
            "state": state,
            "labels": labels
        }
    )
