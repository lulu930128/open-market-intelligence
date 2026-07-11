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
    app_port: int = 8400

    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    enable_scheduler: bool = False
    timezone: str = "Asia/Taipei"
    job_worker_max_concurrency: int = 1
    job_dedupe_active: bool = True

    technical_ma_windows: str = "5,20,60"
    technical_volume_ma_windows: str = "5,20"
    technical_macd_fast_period: int = 12
    technical_macd_slow_period: int = 26
    technical_macd_signal_period: int = 9
    technical_rsi_period: int = 14
    technical_atr_period: int = 14
    technical_adx_period: int = 14
    technical_roc_period: int = 12
    technical_mfi_period: int = 14
    technical_donchian_period: int = 20
    technical_bollinger_period: int = 20
    technical_bollinger_std_dev: float = 2.0
    technical_kd_period: int = 9
    technical_kd_smooth_period: int = 3
    technical_kd_overbought_k: float = 80.0
    technical_kd_overbought_d: float = 70.0
    technical_kd_oversold_k: float = 20.0
    technical_kd_oversold_d: float = 30.0
    technical_support_resistance_period: int = 20
    technical_max_gap_days: int = 10
    technical_volume_ratio_threshold: float = 1.5
    technical_near_level_threshold_pct: float = 2.0
    technical_adx_trend_threshold: float = 25.0
    technical_rsi_bull_min: float = 50.0
    technical_rsi_bull_max: float = 70.0
    technical_rsi_weak_below: float = 40.0
    technical_rsi_overheated_at: float = 80.0
    technical_mfi_inflow_min: float = 50.0
    technical_mfi_inflow_max: float = 80.0
    technical_mfi_outflow_below: float = 35.0
    technical_atr_high_volatility_pct: float = 5.0
    technical_atr_expansion_multiplier: float = 1.2
    technical_atr_expansion_min_pct: float = 2.0
    technical_bollinger_squeeze_bandwidth_pct: float = 8.0

    scheduler_market_refresh_time: str = "15:15"
    scheduler_market_refresh_lookback_days: int = 7
    scheduler_market_refresh_sleep_seconds: float = 0.2
    scheduler_market_chip_refresh_time: str = "15:10"
    scheduler_market_chip_margin_refresh_time: str = "21:10"
    scheduler_market_margin_refresh_time: str = "21:10"
    scheduler_market_chip_refresh_index_ids: str = "TAIEX,TPEX"
    scheduler_market_chip_refresh_force: bool = False
    enable_taiwan_futures_scheduler: bool = True
    taiwan_futures_quote_provider: str = "taifex_mis"
    scheduler_taiwan_futures_symbols: str = "TXF,MXF,TMF"
    scheduler_taiwan_futures_session: str = "auto"
    scheduler_taiwan_futures_interval_seconds: int = 30
    scheduler_taiwan_futures_success_event_interval_seconds: int = 300
    enable_us_market_scheduler: bool = False
    scheduler_us_market_refresh_time: str = "06:30"
    scheduler_us_market_refresh_day_of_week: str = "tue-sat"
    scheduler_us_market_refresh_outputsize: str = "compact"
    scheduler_us_market_refresh_adjusted: bool = False
    scheduler_us_market_refresh_sleep_seconds: float = 12.0
    enable_jp_market_scheduler: bool = False
    scheduler_jp_market_refresh_time: str = "16:10"
    scheduler_jp_market_refresh_day_of_week: str = "mon-fri"
    scheduler_jp_market_refresh_outputsize: str = "compact"
    scheduler_jp_market_refresh_provider: str = "auto"
    scheduler_jp_market_refresh_include_fundamentals: bool = True
    scheduler_jp_market_refresh_sleep_seconds: float = 15.0
    enable_kr_market_scheduler: bool = False
    scheduler_kr_market_refresh_time: str = "16:20"
    scheduler_kr_market_refresh_day_of_week: str = "mon-fri"
    scheduler_kr_market_refresh_outputsize: str = "compact"
    scheduler_kr_market_refresh_provider: str = "auto"
    scheduler_kr_market_refresh_include_investors: bool = True
    scheduler_kr_market_refresh_include_fundamentals: bool = False
    scheduler_kr_market_refresh_sleep_seconds: float = 15.0
    enable_watchlist_radar_scheduler: bool = True
    scheduler_watchlist_radar_time: str = "15:45"
    scheduler_watchlist_radar_day_of_week: str = "mon-fri"
    scheduler_watchlist_radar_group_ids: str = ""
    scheduler_watchlist_radar_modes: str = "action"
    scheduler_watchlist_radar_include_children: bool = True
    scheduler_watchlist_radar_enabled_only: bool = True
    scheduler_watchlist_radar_max_results: int = 30
    scheduler_watchlist_radar_calculation_limit: int = 100
    scheduler_watchlist_radar_use_intraday: bool = False
    scheduler_watchlist_radar_intraday_limit: int = 30
    scheduler_watchlist_radar_evaluate_lookback_days: int = 10
    scheduler_watchlist_radar_require_daily_release: bool = True

    dispatch_smtp_host: str | None = None
    dispatch_smtp_port: int = 587
    dispatch_smtp_username: str | None = None
    dispatch_smtp_password: str | None = None
    dispatch_smtp_from_email: str | None = None
    dispatch_smtp_from_name: str = "Open Market Intelligence"
    dispatch_smtp_use_tls: bool = True
    dispatch_smtp_use_ssl: bool = False
    dispatch_smtp_timeout_seconds: int = 30
    enable_dispatch_scheduler: bool = True
    scheduler_dispatch_tick_interval_seconds: int = 60

    finmind_token: str | None = None
    alphavantage_api_key: str | None = None
    fred_api_key: str | None = None
    kgi_api_key: str | None = None
    kgi_api_secret: str | None = None
    kgi_account: str | None = None
    kgi_cert_path: str | None = None
    kgi_api_base_url: str | None = None
    us_sec_user_agent: str = "Open Market Intelligence local research; set US_SEC_USER_AGENT"
    us_market_http_timeout_seconds: int = 30
    jp_market_http_timeout_seconds: int = 30
    kr_market_http_timeout_seconds: int = 30
    resource_market_http_timeout_seconds: int = 15
    jquants_api_base_url: str = "https://api.jquants.com/v2"
    jquants_api_key: str | None = None
    jquants_id_token: str | None = None
    jquants_refresh_token: str | None = None
    jquants_mail_address: str | None = None
    jquants_password: str | None = None
    jquants_id_token_cache_seconds: int = 82800
    opendart_api_base_url: str = "https://opendart.fss.or.kr/api"
    opendart_api_key: str | None = None
    crypto_market_http_timeout_seconds: int = 15
    crypto_market_ticker_stale_seconds: int = 15
    enable_crypto_market_auto_refresh: bool = True
    crypto_market_auto_refresh_loop_seconds: float = 1.0
    crypto_market_auto_refresh_min_interval_seconds: float = 5.0
    crypto_market_auto_refresh_ohlcv_limit: int = 10
    crypto_market_auto_refresh_ohlcv_bundle_seconds: float = 900.0
    enable_crypto_market_ws_collector: bool = True
    crypto_market_ws_enabled_providers: str = "bitopro,binance"
    crypto_market_ws_message_stale_seconds: int = 10
    crypto_market_ws_reconnect_initial_seconds: float = 1.0
    crypto_market_ws_reconnect_max_seconds: float = 30.0
    crypto_market_ws_order_book_depth: int = 5
    enable_crypto_market_ws_persistence: bool = True
    crypto_market_ws_persistence_flush_seconds: float = 1.0
    crypto_market_ws_persistence_max_pending_keys: int = 500
    enable_crypto_market_history: bool = True
    crypto_market_history_sample_seconds: int = 10
    crypto_market_derivatives_history_sample_seconds: int = 60
    crypto_market_spread_history_sample_seconds: int = 10
    bitopro_api_base_url: str = "https://api.bitopro.com/v3"
    bitopro_ws_base_url: str = "wss://stream.bitopro.com:443/ws"
    binance_spot_api_base_url: str = "https://api.binance.com"
    binance_spot_ws_base_url: str = "wss://stream.binance.com:9443"
    binance_futures_api_base_url: str = "https://fapi.binance.com"
    binance_futures_ws_base_url: str = "wss://fstream.binance.com"
    okx_api_base_url: str = "https://www.okx.com"
    okx_ws_public_url: str = "wss://ws.okx.com:8443/ws/v5/public"
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: str | None = None
    coingecko_api_key_header: str = "x-cg-demo-api-key"
    coinglass_api_base_url: str = "https://open-api-v4.coinglass.com"
    coinglass_api_key: str | None = None
    crypto_market_liquidation_heatmap_range: str = "24h"
    crypto_market_liquidation_fallback_exchange: str = "Binance"
    crypto_market_liquidation_min_amount: float = 10000.0
    enable_crypto_market_liquidation_local_fallback: bool = True
    crypto_market_long_short_ratio_period: str = "5m"
    crypto_market_long_short_ratio_limit: int = 30
    omi_http_trust_env: bool = False
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
