from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Why pydantic-settings?
      - Type validation: DATABASE_URL must be a str, DEBUG must be a bool.
        If you set DEBUG=not_a_bool, the app refuses to start with a clear error.
      - Single source of truth: every config value lives here, not scattered
        across the codebase as os.getenv() calls.
      - IDE autocomplete: settings.database_url is discoverable; a bare
        os.getenv("DATABASE_URL") is not.

    The env_file chain: Docker sets environment variables directly.
    Outside Docker (local dev), pydantic-settings reads .env automatically.
    Explicit env vars always win over .env file values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # don't error on unknown env vars
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "PathogenIQ API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    # asyncpg uses postgresql+asyncpg:// scheme — this tells SQLAlchemy to use
    # the asyncpg driver instead of the default synchronous psycopg2.
    database_url: str = Field(
        default="postgresql+asyncpg://pathogeniq:pathogeniq_secret@localhost:5432/pathogeniq"
    )
    db_pool_size: int = 10       # max persistent connections in the pool
    db_max_overflow: int = 20    # extra connections allowed above pool_size
    db_pool_timeout: int = 30    # seconds to wait before "no connection available"
    db_echo: bool = False        # set True to log every SQL query (very verbose)

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "pathogeniq_secret"

    # ── Qdrant ───────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM APIs (Phase 3) ────────────────────────────────────────────────────
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Biomedical APIs (Phase 2) ─────────────────────────────────────────────
    pubmed_api_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    @lru_cache means pydantic-settings reads the environment exactly once per
    process start, not on every request. This matters because env var reads and
    .env file parsing have overhead.

    In tests, call: app.dependency_overrides[get_settings] = lambda: TestSettings()
    to inject test configuration without touching real env vars.
    """
    return Settings()
