"""Typed operation profiles for US quote and intraday materialization."""

from __future__ import annotations

from dataclasses import dataclass

from app.market_data.integration_contracts import EvidenceTarget
from app.market_data.policies import DataPurpose


US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS = 16
US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM = 2
US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS = (
    US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS
    + US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM
)


@dataclass(frozen=True, slots=True)
class USIntradayOperationProfile:
    profile_id: str
    intraday_bars: int
    acquisition_history_days: int
    allow_outside_acquisition_window: bool = False
    cache_satisfied_noop: bool = False
    evidence_target: EvidenceTarget = EvidenceTarget.CURRENT
    purpose: DataPurpose = DataPurpose.BACKGROUND_COLLECTOR
    consumer_stale_after_seconds: int = 300
    producer_refresh_due_seconds: int = 180

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id is required")
        if self.intraday_bars < 1 or self.intraday_bars > 1000:
            raise ValueError("intraday_bars must be between 1 and 1000")
        if self.acquisition_history_days < 1 or self.acquisition_history_days > 5:
            raise ValueError("acquisition_history_days must be between 1 and 5")
        if self.consumer_stale_after_seconds < 1:
            raise ValueError("consumer_stale_after_seconds must be positive")
        if self.producer_refresh_due_seconds < 1:
            raise ValueError("producer_refresh_due_seconds must be positive")
        if self.producer_refresh_due_seconds >= self.consumer_stale_after_seconds:
            raise ValueError(
                "producer_refresh_due_seconds must be less than consumer_stale_after_seconds"
            )


US_RECURRING_INTRADAY_PROFILE = USIntradayOperationProfile(
    profile_id="recurring_current",
    intraday_bars=600,
    acquisition_history_days=1,
    consumer_stale_after_seconds=180,
    producer_refresh_due_seconds=45,
)
US_BOOTSTRAP_INTRADAY_PROFILE = USIntradayOperationProfile(
    profile_id="bootstrap_latest_available",
    intraday_bars=1000,
    acquisition_history_days=5,
    allow_outside_acquisition_window=True,
    cache_satisfied_noop=True,
    evidence_target=EvidenceTarget.LATEST_AVAILABLE,
    purpose=DataPurpose.REPAIR,
    consumer_stale_after_seconds=300,
    producer_refresh_due_seconds=180,
)


__all__ = [
    "US_BOOTSTRAP_INTRADAY_PROFILE",
    "US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS",
    "US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM",
    "US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS",
    "US_RECURRING_INTRADAY_PROFILE",
    "USIntradayOperationProfile",
]
