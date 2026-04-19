"""
Cortex Auth API Routes.

Provides endpoints for:
- GitHub OAuth login initiation and callback
- Guest login (anonymous access to public repos)
- Current user profile retrieval
"""

from fastapi import APIRouter, Depends

from core.auth import (
    AuthenticatedUser,
    create_access_token,
    exchange_github_code,
    get_current_user,
)
from core.config import settings
from core.logger import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GitHubCallbackRequest(BaseModel):
    code: str  # The OAuth authorization code from GitHub redirect


class GuestLoginRequest(BaseModel):
    display_name: str = "Guest"


class AuthResponse(BaseModel):
    access_token: str
    user: dict
    github_token: str | None = None  # Only present for GitHub OAuth users


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
    client_id = settings.github_oauth_client_id
    if not client_id:
        return {
            "url": None,
            "error": "GitHub OAuth not configured. Set GITHUB_OAUTH_CLIENT_ID.",
        }

    redirect_uri = f"{settings.frontend_url}/auth/callback"
    scopes = "read:user,repo"  # repo scope lets us access private repos

    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes}"
    )
    return {"url": url}


@router.post("/github/callback", response_model=AuthResponse)
async def github_callback(request: GitHubCallbackRequest) -> AuthResponse:
    """
    Exchange the GitHub OAuth code for tokens.
    Returns our JWT + the ephemeral GitHub token for in-memory use.
    """
    result = await exchange_github_code(request.code)
    return AuthResponse(
        access_token=result["access_token"],
        user=result["user"],
        github_token=result["github_token"],
    )


@router.post("/guest", response_model=AuthResponse)
async def guest_login(request: GuestLoginRequest) -> AuthResponse:
    """
    Create a guest session for users who want to explore public repos
    without GitHub authentication.
    """
    import uuid

    guest_id = str(uuid.uuid4())[:8]
    user = AuthenticatedUser(
        user_id=f"guest:{guest_id}",
        login=request.display_name or f"guest-{guest_id}",
        provider="guest",
    )

    token = create_access_token(user)

    return AuthResponse(
        access_token=token,
        user={
            "user_id": user.user_id,
            "login": user.login,
            "provider": user.provider,
            "avatar_url": None,
        },
        github_token=None,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: AuthenticatedUser = Depends(get_current_user)) -> UserProfileResponse:
    """Return the profile of the currently authenticated user."""
    return UserProfileResponse(
        user_id=user.user_id,
        login=user.login,
        provider=user.provider,
        avatar_url=user.avatar_url,
    )
