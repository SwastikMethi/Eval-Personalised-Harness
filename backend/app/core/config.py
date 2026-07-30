from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str = "http://localhost:3000"
    openrouter_app_name: str = "Agent Stack Optimizer"

    data_dir: Path = Path("../data")
    database_url: str = "sqlite:///../data/aso.db"
    queue_concurrency: int = 1


settings = Settings()
