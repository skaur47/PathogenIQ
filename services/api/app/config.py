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

    # ── LLM (Phase 3) ─────────────────────────────────────────────────────────
    # Default: Ollama running locally — free, no API key required.
    # Switch providers by changing only these three vars:
    #   Groq free tier:  base_url=https://api.groq.com/openai/v1, model=llama-3.3-70b-versatile, api_key=<groq key>
    #   OpenRouter:      base_url=https://openrouter.ai/api/v1, model=meta-llama/llama-3.2-3b-instruct:free, api_key=<key>
    #   LM Studio:       base_url=http://localhost:1234/v1, model=<loaded model>, api_key=lm-studio
    llm_base_url: str = "http://ollama:11434/v1"
    llm_model: str = "qwen2.5:0.5b"
    llm_api_key: str = "ollama"  # Ollama ignores this; set to real key for Groq/OpenRouter

    # ── Biomedical APIs (Phase 2) ─────────────────────────────────────────────
    # NCBI PubMed API key — free at https://www.ncbi.nlm.nih.gov/account/
    # Without key: 3 req/s rate limit. With key: 10 req/s.
    pubmed_api_key: str | None = None

    # ── Collector settings (Phase 2) ──────────────────────────────────────────
    # Default max documents to collect per source per run.
    # Increase after Phase 3 agents can process documents faster than they arrive.
    collector_max_results: int = 100

    # ── CORS ──────────────────────────────────────────────────────────────────
    # In development: "*" is used unconditionally (see main.py).
    # In production: set CORS_ORIGINS to a comma-separated list of allowed origins,
    # e.g. CORS_ORIGINS=https://pathogeniq.vercel.app,https://pathogeniq.io
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"]
    )

    # ── Newsletter / SMTP ─────────────────────────────────────────────────────
    # Leave smtp_host empty to disable email sending (subscribe still works,
    # emails just won't be delivered). Gmail example:
    #   SMTP_HOST=smtp.gmail.com  SMTP_PORT=587
    #   SMTP_USER=you@gmail.com   SMTP_PASSWORD=<16-char app password>
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "PathogenIQ <noreply@pathogeniq.io>"
    frontend_base_url: str = "http://localhost:3000"

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
