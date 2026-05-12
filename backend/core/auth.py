"""
Cortex Authentication & Authorization Module.

Provides:
- JWT token creation/validation for session management
- FastAPI dependency for extracting authenticated user from requests
- Support for GitHub OAuth users
- user_id extraction for row-level tenant isolation
"""

import time
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core.config import settings
from core.logger import get_logger
from core.session_store import session_store

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# JWT + Cookie Configuration
# ---------------------------------------------------------------------------

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 86400  # 24 hours

# Session cookie — HttpOnly, never readable by JS.
SESSION_COOKIE_NAME = "cortex_session"


def _cookie_is_secure() -> bool:
    """Use Secure cookies in production (HTTPS); disable for localhost dev."""
    return settings.environment.lower() not in ("development", "dev", "local")


def _cookie_samesite() -> str:
    """Cross-domain production frontend/backend calls require SameSite=None."""
    return "lax" if not _cookie_is_secure() else "none"


def set_session_cookie(response: Response, jwt_token: str) -> None:
    """Attach the JWT to the response as an HttpOnly cookie."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=jwt_token,
        max_age=JWT_EXPIRATION_SECONDS,
        httponly=True,
        secure=_cookie_is_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Invalidate the session cookie on the client."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite=_cookie_samesite(),
        secure=_cookie_is_secure(),
        httponly=True,
    )


def _get_jwt_secret() -> str:
    """Derive JWT secret from existing config. Never store a separate secret for MVP."""
    # Use a combination of existing secrets as the signing key
    base = settings.github_webhook_secret or settings.gemini_api_key or "cortex-dev-secret"
    return f"cortex-jwt-{base[:32]}"


# ---------------------------------------------------------------------------
# User model returned by auth dependency
# ---------------------------------------------------------------------------


class AuthenticatedUser(BaseModel):
    """Represents the currently authenticated user for request-scoped isolation."""
    user_id: str                    # Unique identifier, e.g. "github:12345"
    login: str                      # Display name / username
    provider: str                   # "github"
    avatar_url: str | None = None
    github_token: str | None = None  # Ephemeral, in-memory only — NEVER persisted


# ---------------------------------------------------------------------------
# JWT Token Helpers
# ---------------------------------------------------------------------------


def create_access_token(user: AuthenticatedUser) -> str:
    """Create a signed JWT for the authenticated user."""
    payload = {
        "sub": user.user_id,
        "login": user.login,
        "provider": user.provider,
        "avatar_url": user.avatar_url,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRATION_SECONDS,
    }
    # NOTE: github_token is intentionally EXCLUDED from the JWT.
    # It lives only in the session/cookie, never in a transferable token.
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises on expiry or tampering."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_jwt(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """Prefer HttpOnly session cookie; fall back to Bearer header for programmatic use."""
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    if credentials and credentials.credentials:
        return credentials.credentials
    return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """
    Extract the authenticated user from the request.

    Auth flow:
    1. Read JWT from the `cortex_session` HttpOnly cookie (primary path).
    2. Fall back to `Authorization: Bearer` header for programmatic/test clients.

    The ephemeral GitHub token is fetched from the server-side session store
    keyed by user_id — it is NEVER read from the request body/headers.
    """
    token = _extract_jwt(request, credentials)

    if token:
        payload = decode_access_token(token)

        user = AuthenticatedUser(
            user_id=payload["sub"],
            login=payload.get("login", "unknown"),
            provider=payload.get("provider", "unknown"),
            avatar_url=payload.get("avatar_url"),
            github_token=session_store.get_github_token(payload["sub"]),
        )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser | None:
    """
    Same as get_current_user but returns None instead of raising 401.
    Used for endpoints that work for both authenticated and anonymous users.
    """
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# GitHub OAuth Exchange (called by frontend callback)
# ---------------------------------------------------------------------------


async def exchange_github_code(code: str) -> dict[str, Any]:
    """
    Exchange a GitHub OAuth authorization code for an access token,
    then fetch the user's profile. Returns data needed to create a session.
    """
    import httpx

    client_id = (settings.github_oauth_client_id or "").strip()
    client_secret = (settings.github_oauth_client_secret or "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub OAuth not configured on the server",
        )

    # Step 1: Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        logger.warning(
            "GitHub OAuth token exchange failed: error=%s description=%s",
            token_data.get("error"),
            token_data.get("error_description"),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth failed: {token_data.get('error_description', 'unknown error')}",
        )

    # Step 2: Fetch user profile
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        user_data = user_response.json()

    github_id = user_data.get("id")
    login = user_data.get("login", "unknown")
    avatar_url = user_data.get("avatar_url")

    user = AuthenticatedUser(
        user_id=f"github:{github_id}",
        login=login,
        provider="github",
        avatar_url=avatar_url,
        github_token=access_token,  # Will be stored server-side; not returned to browser
    )

    # Store the GitHub token server-side — the browser never sees it.
    session_store.set_github_token(user.user_id, access_token)

    # Create our own JWT for subsequent API calls (will be set as HttpOnly cookie)
    jwt_token = create_access_token(user)

    return {
        "access_token": jwt_token,
        "user": {
            "user_id": user.user_id,
            "login": user.login,
            "provider": user.provider,
            "avatar_url": user.avatar_url,
        },
    }
