from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "open_market_intelligence.db"


class Settings(BaseSettings):
    app_name: str = "Open Market Intelligence"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    enable_scheduler: bool = False
    timezone: str = "Asia/Taipei"

    finmind_token: str | None = None
    openai_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()