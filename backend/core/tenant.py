from __future__ import annotations


PUBLIC_TENANT_ID = "public"


def tenant_prefix(user_id: str | None, is_public: bool = False) -> str:
    """Return the storage tenant prefix for graph/vector identities."""
    if user_id:
        return user_id
    if is_public:
        return PUBLIC_TENANT_ID
    return "anonymous"


def tenant_scoped_id(raw_id: str, user_id: str | None, is_public: bool = False) -> str:
    """Prefix a storage id with tenant information unless already scoped."""
    prefix = tenant_prefix(user_id, is_public)
    marker = f"{prefix}::"
    if raw_id.startswith(marker):
        return raw_id
    return f"{marker}{raw_id}"


def strip_tenant_prefix(scoped_id: str) -> str:
    """Best-effort helper for display/debug paths."""
    parts = scoped_id.split("::", 1)
    return parts[1] if len(parts) == 2 else scoped_id
