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

    # Second provider (spec §4). Headroom against OpenRouter's ~50 free
    # requests/day, not a replacement — provider is chosen per combination.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    # How long to wait for one upstream completion. Reasoning models routinely
    # think for minutes: measured here, z-ai/glm-5.2 on NIM exceeded 120s on
    # every request, so a hardcoded 120s client timeout turned a slow model
    # into 10 consecutive 502s and an agent that retried for 18 minutes without
    # ever seeing a response. Waiting is cheaper than a retry whose answer we
    # abandon — that spends the same upstream quota and returns nothing.
    provider_timeout_seconds: float = 600.0

    # Setup-time analysis providers. Deciding how a repo can be evaluated is a
    # judgement made once per repository, and getting it wrong is invisible
    # until a run returns INSUFFICIENT_EVALUATION_SIGNAL — worth a capable
    # model. These are not restricted to analysis; a combination may benchmark
    # them too.
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Which provider analyses repositories. "auto" picks the first configured
    # key in order of preference rather than failing when one is absent.
    analyzer_provider: str = "auto"
    analyzer_model: str = ""

    # Model used for AI-assisted setup suggestions (one request per press).
    # A code-oriented free model; overridable per request from the UI.
    suggest_model: str = "cohere/north-mini-code:free"
    # Base image for agent sandboxes and for baseline/evaluation containers.
    # Per-repo "prepared" images are built FROM this with deps pre-installed.
    eval_image: str = "aso-sandbox-python:dev"
    backend_port: int = 8005
    data_dir: Path = Path("../data")
    database_url: str = "sqlite:///../data/aso.db"
    queue_concurrency: int = 1


settings = Settings()
