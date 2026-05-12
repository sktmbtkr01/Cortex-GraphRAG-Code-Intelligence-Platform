import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from api.auth_routes import router as auth_router
from api.webhook import router as webhook_router
from core.config import settings
from core.job_store import job_store
from core.session_store import session_store


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cortex API",
        description="GitHub codebase intelligence platform.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(webhook_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.on_event("startup")
    async def log_runtime_backends() -> None:
        logging.getLogger("uvicorn.error").info(
            "Runtime backends: job_store=%s (%s), session_store=%s (%s), cache=%s, quota=%s",
            settings.job_store_backend,
            type(job_store).__name__,
            settings.session_store_backend,
            type(session_store).__name__,
            settings.cache_backend,
            settings.quota_backend,
        )

    return app


app = create_app()
