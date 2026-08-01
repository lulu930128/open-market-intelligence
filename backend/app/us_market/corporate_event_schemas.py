from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class USCorporateEventRead(BaseModel):
    event_id: str
    event_uid: str
    symbol: str
    company_name: str | None = None
    exchange: str | None = None
    country: str = "US"
    currency: str | None = None

    event_type: str
    event_subtype: str | None = None
    title: str
    description: str | None = None
    event_status: str
    verification_status: str

    event_date: date
    event_time: time | None = None
    event_datetime_utc: datetime | None = None
    timezone: str = "America/New_York"
    market_session: str = "unknown"
    is_all_day: bool = True
    days_until: int | None = None

    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    fiscal_period_end: date | None = None
    estimated_eps: float | None = None

    declaration_date: date | None = None
    ex_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None
    dividend_amount: float | None = None
    dividend_currency: str | None = None

    split_from: float | None = None
    split_to: float | None = None
    split_ratio: float | None = None

    source: str
    source_type: str = "provider_api"
    source_event_id: str | None = None
    source_url: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    fetched_at: datetime

    freshness: str
    data_mode: str = "cached"
    is_stale: bool
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class USCorporateEventSourceRead(BaseModel):
    source: str
    status: str
    freshness: str
    coverage: str
    fetched_at: datetime | None = None
    entry_count: int = 0
    warning: str | None = None


class USCorporateEventListRead(BaseModel):
    kind: str = "us_corporate_events"
    generated_at: datetime
    as_of: date
    timezone: str = "America/New_York"
    date_from: date
    date_to: date
    symbol: str | None = None
    event_types: list[str] = Field(default_factory=list)
    offset: int = 0
    limit: int
    total_count: int
    result_count: int
    warning: str | None = None
    sources: dict[str, USCorporateEventSourceRead]
    results: list[USCorporateEventRead]


class USCorporateEventSummaryRead(BaseModel):
    symbol: str
    checked_at: datetime
    as_of: date
    timezone: str = "America/New_York"
    reminder_days: int
    cache_status: str
    cache_fetched_at: datetime | None = None
    warning: str | None = None
    result_count: int
    results: list[USCorporateEventRead]


class USCorporateEventRefreshRead(BaseModel):
    status: str
    provider: str
    horizon: str
    started_at: datetime
    completed_at: datetime
    fetched_count: int
    valid_count: int
    malformed_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    request_count: int
    request_limit: int
    source_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
    message: str
