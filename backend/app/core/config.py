"""Runtime configuration. Every value can be overridden with an environment variable
(prefix CM_) or a backend/.env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_", env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "ClearMetric"
    environment: str = "development"  # development | production | test

    # Persistence. SQLite for local development, PostgreSQL URL for multi-user deployment,
    # e.g. postgresql+psycopg://user:pass@host/clearmetric
    database_url: str = f"sqlite:///{BACKEND_DIR / 'storage' / 'clearmetric.db'}"
    storage_dir: Path = BACKEND_DIR / "storage"

    # Sessions
    session_cookie: str = "cm_session"
    session_days: int = 14
    cookie_secure: bool = False  # set true behind HTTPS

    # Upload and analytical limits (tune to deployment capacity)
    max_upload_mb: int = 50
    max_rows: int = 1_000_000
    max_columns: int = 300
    query_timeout_seconds: float = 15.0
    max_result_rows: int = 500
    preview_max_page_size: int = 200
    duckdb_memory_limit: str = "1GB"
    duckdb_threads: int = 2

    # AI provider. "local" = deterministic interpreter (no external calls).
    # "anthropic" = Claude, used only when an API key is present AND a workspace owner/admin
    # has enabled external AI in workspace settings.
    ai_provider: str = "local"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_timeout_seconds: float = 30.0

    # Contact form delivery is not configured by default: messages are stored, not emailed.
    smtp_configured: bool = False

    frontend_url: str = "http://localhost:3000"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def external_ai_available(self) -> bool:
        return self.ai_provider == "anthropic" and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("originals", "parquet", "reports"):
        (s.storage_dir / sub).mkdir(exist_ok=True)
    return s
