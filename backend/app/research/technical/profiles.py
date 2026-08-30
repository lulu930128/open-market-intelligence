"""Versioned market profiles for the shared technical engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class MarketAnalysisProfile:
    profile_id: str
    profile_version: str
    market: str
    timeframe: str
    price_basis: str
    currency: str
    volume_unit: str | None
    calendar_id: str
    timezone: str
    session_profile_id: str
    benchmark_symbol: str | None
    benchmark_status: str
    corporate_action_policy: str
    provisional_period_policy: str
    moving_average_periods: tuple[int, ...]
    exponential_moving_average_periods: tuple[int, ...]
    volume_average_period: int
    rsi_period: int
    atr_period: int
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    structure_window: int
    breakout_window: int
    facts_minimum_bars: int
    decision_minimum_bars: int

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "moving_average_periods",
            "exponential_moving_average_periods",
        ):
            payload[key] = list(payload[key])
        return payload


US_DAILY_PROFILE = MarketAnalysisProfile(
    profile_id="us.equity.daily",
    profile_version="us.equity.daily.v1",
    market="US",
    timeframe="1d",
    price_basis="raw_unadjusted",
    currency="USD",
    volume_unit="share",
    calendar_id="us.exchange_calendar.v1",
    timezone="America/New_York",
    session_profile_id="us.equity.regular.v1",
    benchmark_symbol=None,
    benchmark_status="not_configured",
    corporate_action_policy="require_complete_coverage_for_decision",
    provisional_period_policy="completed_daily_only",
    moving_average_periods=(5, 10, 20, 50, 60, 200),
    exponential_moving_average_periods=(12, 26),
    volume_average_period=20,
    rsi_period=14,
    atr_period=14,
    macd_fast_period=12,
    macd_slow_period=26,
    macd_signal_period=9,
    structure_window=20,
    breakout_window=20,
    facts_minimum_bars=35,
    decision_minimum_bars=200,
)


US_INDEX_DAILY_PROFILE = replace(
    US_DAILY_PROFILE,
    profile_id="us.index.daily",
    profile_version="us.index.daily.v1",
    volume_unit=None,
    session_profile_id="us.index.regular.v1",
    corporate_action_policy="not_applicable",
)


TW_DAILY_PROFILE = MarketAnalysisProfile(
    profile_id="tw.equity.daily",
    profile_version="tw.equity.daily.v1",
    market="TW",
    timeframe="1d",
    price_basis="raw_unadjusted",
    currency="TWD",
    volume_unit="share",
    calendar_id="tw.exchange_calendar.v1",
    timezone="Asia/Taipei",
    session_profile_id="tw.equity.regular.v1",
    benchmark_symbol="TAIEX",
    benchmark_status="configured_by_tw_compatibility_wrapper",
    corporate_action_policy="preserve_legacy_guard",
    provisional_period_policy="explicit_current_partial",
    moving_average_periods=(5, 20, 60),
    exponential_moving_average_periods=(12, 26),
    volume_average_period=20,
    rsi_period=14,
    atr_period=14,
    macd_fast_period=12,
    macd_slow_period=26,
    macd_signal_period=9,
    structure_window=20,
    breakout_window=20,
    facts_minimum_bars=35,
    decision_minimum_bars=60,
)


__all__ = [
    "MarketAnalysisProfile",
    "TW_DAILY_PROFILE",
    "US_DAILY_PROFILE",
    "US_INDEX_DAILY_PROFILE",
]
