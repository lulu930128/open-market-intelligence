"""Backend-owned Intraday Radar v1 research contracts; no acquisition policy."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel


class IntradayFeature(CanonicalModel):
    value: float | None = Field(default=None, allow_inf_nan=False)
    reason: str | None = None
    reference_time: datetime | None = None
    reference_raw_result_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def missing_requires_reason(self):
        if (self.value is None) != (self.reason is not None):
            raise ValueError("a missing feature requires a reason; a value cannot have a missing reason")
        return self


class IntradayFeatures(CanonicalModel):
    version: Literal["tw.intraday.features.v1"] = "tw.intraday.features.v1"
    change_pct: IntradayFeature
    return_1m: IntradayFeature
    return_3m: IntradayFeature
    return_5m: IntradayFeature
    return_15m: IntradayFeature
    distance_from_high_pct: IntradayFeature
    rebound_from_low_pct: IntradayFeature
    intraday_range_pct: IntradayFeature
    rvol_at_time: IntradayFeature = IntradayFeature(reason="TIME_OF_DAY_BASELINE_UNAVAILABLE")
    volume_velocity: IntradayFeature = IntradayFeature(reason="VOLUME_SERIES_UNAVAILABLE")


class IntradayLineage(CanonicalModel):
    provider: str
    source: str
    raw_result_ids: tuple[str, ...]
    state_version: str
    calculation_version: str
    complete: bool


class DiscoveryObservation(CanonicalModel):
    stock_id: str
    stock_name: str
    market: str
    trade_date: date
    as_of: datetime | None
    received_at: datetime | None
    freshness: str
    receipt_freshness: str
    ranking_eligible: bool
    research_eligible: bool
    cumulative_volume_lots: float | None = Field(default=None, allow_inf_nan=False)
    features: IntradayFeatures
    lineage: IntradayLineage
    exclusion_reasons: tuple[str, ...] = ()


class DiscoveryCoverage(CanonicalModel):
    version: Literal["tw.intraday.discovery.coverage.v1"] = "tw.intraday.discovery.coverage.v1"
    scope: Literal["active_twse_tpex_stocks"] = "active_twse_tpex_stocks"
    universe_revision: str
    universe_count: int = Field(ge=0)
    observed_count: int = Field(ge=0)
    coverage_count: int = Field(ge=0)
    ranking_eligible_count: int = Field(ge=0)
    research_eligible_count: int = Field(ge=0)
    actual_trade_price_count: int = Field(default=0, ge=0)
    actual_price_unavailable_count: int = Field(default=0, ge=0)
    verified_no_trade_count: int = Field(default=0, ge=0)
    count_ratios: dict[str, float] = Field(default_factory=dict)
    coverage_ratio: float = Field(ge=0, le=1)
    status: Literal["ready", "partial", "blocked"]
    is_full_market: bool
    as_of: datetime | None
    oldest_as_of: datetime | None
    freshness_counts: dict[str, int]
    missing_reasons: dict[str, str]
    exclusion_reasons: dict[str, tuple[str, ...]]


class IntradayDiscovery(CanonicalModel):
    version: Literal["tw.intraday.discovery.v1"] = "tw.intraday.discovery.v1"
    evaluated_at: datetime
    session_phase: str
    coverage: DiscoveryCoverage
    observations: tuple[DiscoveryObservation, ...]
    limitations: tuple[str, ...]


class IntradayCandidateConfig(CanonicalModel):
    version: Literal["tw.intraday.candidate_gate.v1"] = "tw.intraday.candidate_gate.v1"
    min_change_pct: float = Field(default=2, ge=0, allow_inf_nan=False)
    min_return_3m: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    max_distance_from_high_pct: float = Field(default=1, ge=0, allow_inf_nan=False)
    min_cumulative_volume_lots: float = Field(default=100, gt=0, allow_inf_nan=False)


class IntradayCandidate(CanonicalModel):
    observation: DiscoveryObservation
    strength: Literal["momentum_near_high"] = "momentum_near_high"
    timing: Literal["current_observation"] = "current_observation"
    quality: Literal["current_with_lineage"] = "current_with_lineage"
    action: Literal["research_candidate"] = "research_candidate"
    limitations: tuple[str, ...]


class IntradayRadarResult(CanonicalModel):
    version: Literal["tw.intraday.radar.v1"] = "tw.intraday.radar.v1"
    feature_version: Literal["tw.intraday.features.v1"] = "tw.intraday.features.v1"
    evaluated_at: datetime
    status: Literal["ready", "partial", "blocked"]
    config: IntradayCandidateConfig
    config_hash: str
    evaluation_id: str
    coverage: DiscoveryCoverage
    candidates: tuple[IntradayCandidate, ...]
    gate_exclusions: dict[str, tuple[str, ...]]
    limitations: tuple[str, ...]
