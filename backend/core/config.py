from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    embedding_backend: str = "gemini"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768

    github_pat: str | None = None
    github_webhook_secret: str | None = None
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None

    # Multi-tenant safety: reject repos larger than this (in MB)
    max_repo_size_mb: int = 500

    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "cortex_kb"

    neo4j_uri: str | None = None
    neo4j_username: str = "neo4j"
    neo4j_password: str | None = None

    groq_api_key: str | None = None
    gemini_api_key: str | None = None

    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias="CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
