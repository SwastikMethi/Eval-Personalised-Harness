from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `make backend` runs uvicorn from backend/, so a bare ".env" resolves to
# backend/.env and the repo-root .env is silently ignored — the API key simply
# never arrives. Anchor to this file's location instead of the process CWD.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str = "http://localhost:3000"
    openrouter_app_name: str = "Agent Stack Optimizer"

    # Model used for AI-assisted setup suggestions (one request per press).
    # A code-oriented free model; overridable per request from the UI.
    suggest_model: str = "cohere/north-mini-code:free"
    backend_port: int = 8005
    data_dir: Path = Path("../data")
    database_url: str = "sqlite:///../data/aso.db"
    queue_concurrency: int = 1


settings = Settings()
