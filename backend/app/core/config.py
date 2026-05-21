from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_url: str = Field(..., alias="POSTGRES_URL")
    postgres_sync_url: str = Field(..., alias="POSTGRES_SYNC_URL")

    @field_validator("postgres_url", mode="before")
    @classmethod
    def _coerce_async_driver(cls, v: str) -> str:
        # Render/Heroku-style managed Postgres expose the URL with either
        # the legacy `postgres://` scheme or plain `postgresql://`. Our
        # SQLAlchemy engine wants an explicit asyncpg driver — rewrite
        # here so we don't force ops to know the URL-encoding gotcha.
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    @field_validator("postgres_sync_url", mode="before")
    @classmethod
    def _coerce_sync_driver(cls, v: str) -> str:
        # Alembic / psycopg2 want a sync driver. Strip any `+asyncpg` and
        # normalise the scheme.
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        return v.replace("postgresql+asyncpg://", "postgresql://")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    s3_endpoint: str = Field("http://localhost:9000", alias="S3_ENDPOINT")
    s3_access_key: str = Field("memoryminio", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field("memoryminio", alias="S3_SECRET_KEY")
    s3_bucket: str = Field("memory-attachments", alias="S3_BUCKET")
    s3_region: str = Field("us-east-1", alias="S3_REGION")

    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field("dynamiq-context-engine", alias="JWT_ISSUER")

    # Public URL the backend is reachable on, used for OAuth Protected
    # Resource Metadata (RFC 9728) and for stamping the `aud` claim on
    # tokens so they bind to this resource server.
    public_base_url: str = Field(
        "http://localhost:8000", alias="PUBLIC_BASE_URL"
    )

    # Public URL the WEB UI is reachable on. Used for OAuth callback
    # redirect URIs — Google sends the browser here, the frontend page
    # picks up code+state and POSTs to the backend.
    web_base_url: str = Field(
        "http://localhost:3000", alias="WEB_BASE_URL"
    )

    cors_origins: str = Field("http://localhost:3000", alias="CORS_ORIGINS")

    llm_provider: str = Field("anthropic", alias="LLM_PROVIDER")
    llm_model: str = Field("claude-sonnet-4-6", alias="LLM_MODEL")
    embedding_provider: str = Field("openai", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(1536, alias="EMBEDDING_DIM")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")

    # --- Google Docs integration (optional; whole feature is disabled
    # when GOOGLE_CLIENT_ID is unset). UI hides the "Connect Google"
    # button automatically in that case. ---
    google_client_id: str | None = Field(None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str | None = Field(None, alias="GOOGLE_REDIRECT_URI")

    # Fernet key (32-byte url-safe base64) used to encrypt OAuth tokens
    # at rest in `google_drive_connection`. Mint with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    integration_token_encryption_key: str | None = Field(
        None, alias="INTEGRATION_TOKEN_ENCRYPTION_KEY"
    )

    contradictor_similarity_threshold: float = Field(0.85, alias="CONTRADICTOR_SIMILARITY_THRESHOLD")
    hybrid_rrf_k: int = Field(60, alias="HYBRID_RRF_K")
    search_default_limit: int = Field(20, alias="SEARCH_DEFAULT_LIMIT")

    # Cross-encoder reranker (RFC §18). Off by default. When on, the
    # ``reranker_model`` is invoked once per query against the top hits
    # before MMR diversification.
    reranker_enabled: bool = Field(False, alias="RERANKER_ENABLED")
    reranker_model: str = Field(
        "cross-encoder/ms-marco-MiniLM-L-6-v2", alias="RERANKER_MODEL"
    )
    reranker_top_n: int = Field(30, alias="RERANKER_TOP_N")

    # Entity-resolution tier-3 LLM (RFC §16). Cheap-model default.
    entity_resolver_llm_model: str = Field(
        "claude-haiku-4-5", alias="ENTITY_RESOLVER_LLM_MODEL"
    )

    # Workers
    worker_drain_seconds: int = Field(30, alias="WORKER_DRAIN_SECONDS")

    # Audit-log retention. 0 disables purging entirely.
    audit_log_retention_days: int = Field(
        365, alias="AUDIT_LOG_RETENTION_DAYS"
    )

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    sentry_dsn: str | None = Field(None, alias="SENTRY_DSN")
    sentry_environment: str = Field("production", alias="SENTRY_ENVIRONMENT")
    sentry_traces_sample_rate: float = Field(
        0.1, alias="SENTRY_TRACES_SAMPLE_RATE"
    )

    # Hocuspocus internal endpoint for block-tree → Yjs conversion. Used
    # by the demo seeder so the BlockNote editor can render seeded docs
    # without a client-side hydration round-trip. If HYDRATE_SECRET is
    # unset, the seeder skips the step (block tree still populated, but
    # the editor will show blank pages for demo docs).
    hydrate_secret: str | None = Field(None, alias="HYDRATE_SECRET")
    collab_internal_url: str = Field(
        "http://hocuspocus:1234", alias="COLLAB_INTERNAL_URL"
    )

    # Playground (chat-style demo UI driving real Claude over our MCP).
    playground_model: str = Field(
        "claude-haiku-4-5", alias="PLAYGROUND_MODEL"
    )

    # In-memory rate limit on /api/mcp/* calls authenticated by an agent
    # token. Session JWTs are not rate-limited here — the BetterAuth
    # layer handles user sessions.
    mcp_rate_limit_rpm: int = Field(60, alias="MCP_RATE_LIMIT_RPM")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mcp_resource_url(self) -> str:
        """Canonical MCP resource URL used as JWT audience + RFC 9728 resource."""
        return f"{self.public_base_url.rstrip('/')}/api/mcp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
