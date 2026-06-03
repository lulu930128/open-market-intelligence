from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "open_market_intelligence.db"


def _clean_secret(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


def _read_env_file_secret(path_value: str | None, names: tuple[str, ...]) -> str | None:
    cleaned_path = _clean_secret(path_value)
    if not cleaned_path:
        return None

    path = Path(cleaned_path).expanduser()
    if not path.is_file():
        return None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        if key.strip() in names:
            secret = _clean_secret(value)
            if secret:
                return secret

    return None


class Settings(BaseSettings):
    app_name: str = "Open Market Intelligence"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8300

    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    enable_scheduler: bool = False
    timezone: str = "Asia/Taipei"
    job_worker_max_concurrency: int = 1
    job_dedupe_active: bool = True
    scheduler_market_refresh_time: str = "15:15"
    scheduler_market_refresh_lookback_days: int = 7
    scheduler_market_refresh_sleep_seconds: float = 0.2
    enable_us_market_scheduler: bool = False
    scheduler_us_market_refresh_time: str = "06:30"
    scheduler_us_market_refresh_day_of_week: str = "tue-sat"
    scheduler_us_market_refresh_outputsize: str = "compact"
    scheduler_us_market_refresh_adjusted: bool = False
    scheduler_us_market_refresh_sleep_seconds: float = 12.0

    finmind_token: str | None = None
    alphavantage_api_key: str | None = None
    fred_api_key: str | None = None
    us_sec_user_agent: str = "Open Market Intelligence local research; set US_SEC_USER_AGENT"
    us_market_http_timeout_seconds: int = 30
    openai_api_key: str | None = None
    openai_llm_api_key: str | None = None
    omi_openai_env_file: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_responses_url: str = "https://api.openai.com/v1/responses"
    openai_timeout_seconds: int = 120
    openai_max_output_tokens: int = 1800
    omi_ai_allow_local_trust: bool = True
    omi_ai_trusted_client_hosts: str = "127.0.0.1,::1"
    omi_ai_trust_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def effective_openai_api_key(self) -> str | None:
        direct_key = _clean_secret(self.openai_api_key)
        if direct_key:
            return direct_key

        alias_key = _clean_secret(self.openai_llm_api_key)
        if alias_key:
            return alias_key

        return _read_env_file_secret(
            self.omi_openai_env_file,
            ("OPENAI_API_KEY", "OPENAI_LLM_API_KEY"),
        )


settings = Settings()
