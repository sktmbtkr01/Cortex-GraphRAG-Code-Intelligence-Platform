from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()


@router.post("/webhook/github")
async def github_webhook(request: Request) -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GitHub webhook handling is planned for Phase 7.",
    )
