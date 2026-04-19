"""
Cortex Authentication & Authorization Module.

Provides:
- JWT token creation/validation for session management
- FastAPI dependency for extracting authenticated user from requests
- Support for GitHub OAuth users and guest users
- user_id extraction for row-level tenant isolation
"""

import time
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# JWT Configuration
# ---------------------------------------------------------------------------

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 86400  # 24 hours


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
    user_id: str                    # Unique identifier (e.g., "github:12345" or "guest:uuid")
    login: str                      # Display name / username
    provider: str                   # "github" | "guest"
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


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """
    Extract the authenticated user from the request.

    Auth flow:
    1. Check for Bearer token in Authorization header (JWT from our login flow)
    2. If no token, fall back to a default "anonymous" guest user for development

    In production, step 2 would be removed and all requests would require auth.
    """
    if credentials and credentials.credentials:
        token = credentials.credentials
        payload = decode_access_token(token)

        user = AuthenticatedUser(
            user_id=payload["sub"],
            login=payload.get("login", "unknown"),
            provider=payload.get("provider", "unknown"),
            avatar_url=payload.get("avatar_url"),
            github_token=None,  # Token is NOT stored in JWT — retrieved from session separately
        )

        # Check if the frontend passed the ephemeral GitHub token in a custom header
        gh_token = request.headers.get("X-GitHub-Token")
        if gh_token:
            user.github_token = gh_token

        return user

    # Development fallback: allow unauthenticated access with a default user
    if settings.environment == "development":
        logger.debug("No auth token provided — using development guest user")
        return AuthenticatedUser(
            user_id="dev:local",
            login="dev-user",
            provider="guest",
            github_token=settings.github_pat,  # Use env PAT in dev mode
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
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

    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub OAuth not configured on the server",
        )

    # Step 1: Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_response.json()

    access_token = token_data.get("access_token")
    if not access_token:
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
        github_token=access_token,  # Ephemeral — only lives in this response
    )

    # Create our own JWT for subsequent API calls
    jwt_token = create_access_token(user)

    return {
        "access_token": jwt_token,
        "user": {
            "user_id": user.user_id,
            "login": user.login,
            "provider": user.provider,
            "avatar_url": user.avatar_url,
        },
        "github_token": access_token,  # Frontend stores in-memory only
    }
