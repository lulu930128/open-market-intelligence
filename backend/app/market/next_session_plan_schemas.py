from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaiwanNextSessionPlanMethodologyRead(BaseModel):
    id: str
    version: str
    price_series: str
    candidate_price_semantics: str
    transition_formula: str
    projected_ma_formula: str
    comparison_rule: str


class TaiwanNextSessionPlanFreshnessRead(BaseModel):
    status: Literal["missing", "current", "stale", "future"]
    expected_trade_date: date
    latest_trade_date: date | None = None
    calendar_day_lag: int | None = None
    trading_day_lag: int | None = None
    release_time: str
    release_timezone: str
    checked_at: datetime


class TaiwanNextSessionPlanHistoryRead(BaseModel):
    requested_limit: int
    raw_row_count: int
    distinct_trade_date_count: int
    duplicate_trade_date_count: int
    valid_close_count: int
    first_trade_date: date | None = None
    latest_trade_date: date | None = None
    source_ids: list[int] = Field(default_factory=list)
    max_gap_days: int


class TaiwanNextSessionPlanLevelRead(BaseModel):
    key: str
    period: int
    transition_price: float
    current_ma: float | None = None
    projected_ma_if_flat: float
    drift_if_flat: float | None = None
    dropped_close: float | None = None
    as_of_close_relation: Literal["above", "below", "at"]
    role_at_as_of_close: Literal["support", "reclaim", "pivot"]
    move_from_as_of_close_pct: float | None = None
    required_close_count: int
    available_close_count: int
    window_start_date: date
    window_end_date: date
    candidate_price_semantics: str
    comparison_rule: str


class TaiwanNextSessionKnownRangeRead(BaseModel):
    period: int
    support: float | None = None
    resistance: float | None = None
    previous_session_low: float | None = None
    previous_session_high: float | None = None
    previous_session_close: float | None = None
    window_start_date: date | None = None
    window_end_date: date | None = None
    method: str


class TaiwanNextSessionScenarioZoneRead(BaseModel):
    key: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    lower_bound_rule: Literal["inclusive", "exclusive"] | None = None
    upper_bound_rule: Literal["inclusive", "exclusive"] | None = None
    at_or_above_level_keys: list[str] = Field(default_factory=list)
    below_level_keys: list[str] = Field(default_factory=list)


class TaiwanNextSessionCorporateActionAdjustmentRead(BaseModel):
    status: Literal["not_applied"]
    event_check: Literal["not_performed"]
    price_series: str


class TaiwanNextSessionPlanReadinessRead(BaseModel):
    status: Literal[
        "ready",
        "partial",
        "pending",
        "stale",
        "missing",
        "not_applicable",
    ]
    decision_usable: bool
    reason_codes: list[str] = Field(default_factory=list)
    available_level_keys: list[str] = Field(default_factory=list)
    missing_level_keys: list[str] = Field(default_factory=list)


class TaiwanNextSessionSourceRefRead(BaseModel):
    type: Literal["table", "calendar", "derived"]
    name: str


class TaiwanNextSessionPlanRead(BaseModel):
    kind: str
    version: str
    market: str
    stock_id: str
    stock_name: str | None = None
    instrument_type: str | None = None
    currency: str
    price_unit: str
    status: Literal[
        "ready",
        "partial",
        "pending",
        "stale",
        "missing",
        "not_applicable",
    ]
    generated_at: datetime
    as_of_trade_date: date | None = None
    target_trade_date: date | None = None
    target_session_state: Literal[
        "unavailable",
        "upcoming",
        "active",
        "completed_waiting_refresh",
        "expired",
    ]
    as_of_close: float | None = None
    methodology: TaiwanNextSessionPlanMethodologyRead
    freshness: TaiwanNextSessionPlanFreshnessRead
    history: TaiwanNextSessionPlanHistoryRead
    readiness: TaiwanNextSessionPlanReadinessRead
    levels: list[TaiwanNextSessionPlanLevelRead] = Field(default_factory=list)
    known_range: TaiwanNextSessionKnownRangeRead
    scenario_zones: list[TaiwanNextSessionScenarioZoneRead] = Field(
        default_factory=list
    )
    corporate_action_adjustment: TaiwanNextSessionCorporateActionAdjustmentRead
    missing: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitation_codes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_refs: list[TaiwanNextSessionSourceRefRead] = Field(
        default_factory=list
    )
