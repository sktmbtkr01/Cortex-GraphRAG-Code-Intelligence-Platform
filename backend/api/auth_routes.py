"""
Cortex Auth API Routes.

Provides endpoints for:
- GitHub OAuth login initiation and callback
- Current user profile retrieval
"""

from fastapi import APIRouter, Depends, Response
from urllib.parse import urlencode

from core.auth import (
    AuthenticatedUser,
    clear_session_cookie,
    exchange_github_code,
    get_current_user,
    set_session_cookie,
)
from core.config import settings
from core.logger import get_logger
from core.session_store import session_store
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GitHubCallbackRequest(BaseModel):
    code: str  # The OAuth authorization code from GitHub redirect


class AuthResponse(BaseModel):
    """Session-bearing responses — JWT is in the HttpOnly cookie, not this body."""
    user: dict


class UserProfileResponse(BaseModel):
    user_id: str
    login: str
    provider: str
    avatar_url: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/github/login")
async def github_login_url() -> dict:
    """
    Returns the GitHub OAuth authorization URL.
    Frontend redirects the user to this URL to start the OAuth flow.
    """
    client_id = (settings.github_oauth_client_id or "").strip()
    if not client_id:
        return {
            "url": None,
            "error": "GitHub OAuth not configured. Set GITHUB_OAUTH_CLIENT_ID.",
        }

    redirect_uri = f"{settings.frontend_url}/auth/callback"
    scopes = "read:user,repo"  # repo scope lets us access private repos

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "allow_signup": "true",
        }
    )
    url = f"https://github.com/login/oauth/authorize?{query}"
    return {"url": url}


@router.post("/github/callback", response_model=AuthResponse)
async def github_callback(
    request: GitHubCallbackRequest,
    response: Response,
) -> AuthResponse:
    """
    Exchange the GitHub OAuth code for a session.
    The JWT is set as an HttpOnly cookie; the GitHub access token is stored
    server-side in the session store and NEVER returned to the browser.
    """
    result = await exchange_github_code(request.code)
    set_session_cookie(response, result["access_token"])
    return AuthResponse(user=result["user"])


@router.post("/logout")
async def logout(
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    """
    Terminate the current session: clear the HttpOnly cookie AND purge the
    server-side entry that holds the ephemeral GitHub token.
    """
    session_store.clear(user.user_id)
    clear_session_cookie(response)
    logger.info("Session terminated for user_id=%s", user.user_id)
    return {"ok": True}


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: AuthenticatedUser = Depends(get_current_user)) -> UserProfileResponse:
    """Return the profile of the currently authenticated user."""
    return UserProfileResponse(
        user_id=user.user_id,
        login=user.login,
        provider=user.provider,
        avatar_url=user.avatar_url,
    )
