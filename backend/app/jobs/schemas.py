from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.us_market.intraday_profiles import (
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
)


class JobRunRead(BaseModel):
    id: int
    job_type: str
    status: str
    public_status: str | None = None
    target: str | None = None

    progress_current: int
    progress_total: int

    message: str | None = None
    error_message: str | None = None

    request: Any = None
    result: Any = None

    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    updated_at: datetime


class USCurrentMarketBootstrapJobRequest(BaseModel):
    equity_symbols: list[str] = Field(
        default_factory=lambda: ["AAPL", "TSM"],
        min_length=1,
        max_length=2,
    )
    index_symbols: list[str] = Field(
        default_factory=lambda: [
            "^GSPC",
            "^DJI",
            "^IXIC",
            "^SOX",
            "^NDX",
            "^VIX",
        ],
        min_length=1,
        max_length=6,
    )
    max_external_calls: int = Field(
        default=US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
        ge=1,
        le=20,
    )


class TaiwanIntradayBarBootstrapJobRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, max_length=10)
    max_symbols: int = Field(default=10, ge=1, le=10)


class TaiwanIndexDailyBootstrapJobRequest(BaseModel):
    index_ids: list[str] = Field(default_factory=lambda: ["TAIEX", "TPEX"], min_length=1, max_length=2)
    date_from: date
    date_to: date
    taiex_max_sessions: int = Field(default=260, ge=1, le=260)
    tpex_max_sessions: int = Field(default=20, ge=1, le=20)
