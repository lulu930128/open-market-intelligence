from typing import Any, Literal

from pydantic import BaseModel, Field


class TechnicalAnalysisWindowsRead(BaseModel):
    ma: list[int] = Field(default_factory=list)
    volume_ma: list[int] = Field(default_factory=list)
    max_gap_days: int


class TechnicalAnalysisMacdPeriodsRead(BaseModel):
    fast: int
    slow: int
    signal: int


class TechnicalAnalysisKdPeriodsRead(BaseModel):
    period: int
    smooth: int


class TechnicalAnalysisBollingerPeriodsRead(BaseModel):
    period: int
    std_dev: float


class TechnicalAnalysisPeriodsRead(BaseModel):
    macd: TechnicalAnalysisMacdPeriodsRead
    rsi: int
    atr: int
    adx: int
    roc: int
    mfi: int
    donchian: int
    bollinger: TechnicalAnalysisBollingerPeriodsRead
    kd: TechnicalAnalysisKdPeriodsRead
    support_resistance: int


class TechnicalAnalysisKdThresholdsRead(BaseModel):
    overbought_k: float
    overbought_d: float
    oversold_k: float
    oversold_d: float


class TechnicalAnalysisRsiThresholdsRead(BaseModel):
    bull_min: float
    bull_max: float
    weak_below: float
    overheated_at: float


class TechnicalAnalysisMfiThresholdsRead(BaseModel):
    inflow_min: float
    inflow_max: float
    outflow_below: float


class TechnicalAnalysisAtrThresholdsRead(BaseModel):
    high_volatility_pct: float
    expansion_multiplier: float
    expansion_min_pct: float


class TechnicalAnalysisThresholdsRead(BaseModel):
    volume_ratio: float
    near_level_pct: float
    adx_trend: float
    rsi: TechnicalAnalysisRsiThresholdsRead
    mfi: TechnicalAnalysisMfiThresholdsRead
    kd: TechnicalAnalysisKdThresholdsRead
    atr: TechnicalAnalysisAtrThresholdsRead
    bollinger_squeeze_bandwidth_pct: float


class TechnicalAnalysisQueryDefaultsRead(BaseModel):
    ma_windows: str
    volume_ma_windows: str
    volume_ratio_threshold: float


class TechnicalAnalysisIndicatorKeysRead(BaseModel):
    ma_short: str | None = None
    ma_medium: str | None = None
    ma_long: str | None = None
    volume_ma_short: str | None = None
    volume_ma_medium: str | None = None
    ema_fast: str
    ema_slow: str
    rsi: str
    atr: str
    plus_di: str
    minus_di: str
    adx: str
    roc: str
    mfi: str
    donchian_upper: str
    donchian_lower: str
    bollinger_upper: str
    bollinger_middle: str
    bollinger_lower: str
    bollinger_bandwidth: str
    kd_k: str
    kd_d: str
    support: str
    resistance: str


class TechnicalAnalysisSettingsRead(BaseModel):
    kind: str
    version: str
    source: str
    windows: TechnicalAnalysisWindowsRead
    periods: TechnicalAnalysisPeriodsRead
    thresholds: TechnicalAnalysisThresholdsRead
    query_defaults: TechnicalAnalysisQueryDefaultsRead
    indicator_keys: TechnicalAnalysisIndicatorKeysRead


class TechnicalAnalysisSettingsWrite(BaseModel):
    windows: TechnicalAnalysisWindowsRead
    periods: TechnicalAnalysisPeriodsRead
    thresholds: TechnicalAnalysisThresholdsRead


class RefreshExecutionMarketPolicyRead(BaseModel):
    observed_stock_refresh_interval_seconds: float = Field(ge=0.1, le=3600)
    subresource_refresh_interval_seconds: float = Field(ge=0, le=3600)
    market_refresh_interval_seconds: float = Field(ge=0, le=3600)


class RefreshExecutionMarketsRead(BaseModel):
    tw: RefreshExecutionMarketPolicyRead
    us: RefreshExecutionMarketPolicyRead
    jp: RefreshExecutionMarketPolicyRead
    kr: RefreshExecutionMarketPolicyRead


class RefreshExecutionSettingsRead(BaseModel):
    kind: str
    version: str
    source: str
    markets: RefreshExecutionMarketsRead


class RefreshExecutionSettingsWrite(BaseModel):
    markets: RefreshExecutionMarketsRead


MarketDataSubscriptionMode = Literal["always_on", "on_select", "manual", "disabled"]


class MarketDataSubscriptionItemRead(BaseModel):
    key: str
    market: str
    group: str
    label: str
    mode: MarketDataSubscriptionMode
    resources: dict[str, bool] = Field(default_factory=dict)
    intervals: dict[str, float] = Field(default_factory=dict)
    provider_status: str | None = None
    note: str | None = None


class MarketDataSubscriptionSettingsRead(BaseModel):
    kind: str
    version: str
    source: str
    items: list[MarketDataSubscriptionItemRead] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=dict)


class MarketDataSubscriptionItemWrite(BaseModel):
    key: str
    mode: MarketDataSubscriptionMode
    resources: dict[str, bool] = Field(default_factory=dict)
    intervals: dict[str, float] = Field(default_factory=dict)


class MarketDataSubscriptionSettingsWrite(BaseModel):
    items: list[MarketDataSubscriptionItemWrite] = Field(default_factory=list)
