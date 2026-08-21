from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SA_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://searchagent:searchagent@localhost:5432/searchagent"
    secret_key: str = "dev-secret-change-me"
    app_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8000"

    # Auth
    auth_provider: str = "dev"  # "dev" | "google"
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_email_domains: str = ""  # comma-separated; empty = allow all

    # Files
    data_dir: str = "./data"
    max_upload_bytes: int = 10 * 1024 * 1024

    # Agent guardrails
    max_steps_per_run: int = 25
    tool_timeout_seconds: int = 60
    tool_result_max_chars: int = 20000

    # Providers
    openai_reasoning_effort: str = "medium"
    anthropic_thinking_budget: int = 4096

    # Rate limits (per user, per minute; 0 disables)
    rate_limit_runs_per_minute: int = 10
    rate_limit_uploads_per_minute: int = 30

    # Static frontend build (Docker deployment); empty = API-only
    static_dir: str = ""

    # Subagents
    max_subagents: int = 5
    subagent_concurrency: int = 3
    max_steps_per_subagent_run: int = 15
    subagent_timeout_seconds: int = 900  # per child run


@lru_cache
def get_settings() -> Settings:
    return Settings()
