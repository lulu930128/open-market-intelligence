from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PortfolioMarket = Literal["tw", "us", "jp", "kr"]


class PortfolioHoldingCreate(BaseModel):
    market: PortfolioMarket
    symbol: str = Field(..., min_length=1, max_length=32)
    quantity: float = Field(..., gt=0)
    cost_amount: float = Field(..., gt=0)
    currency: str | None = Field(default=None, max_length=10)
    note: str | None = None
    tags: str | None = None
    strategy_horizon: str | None = Field(default=None, max_length=40)
    opened_at: date | None = None
    is_active: bool = True


class PortfolioHoldingUpdate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    cost_amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=10)
    note: str | None = None
    tags: str | None = None
    strategy_horizon: str | None = Field(default=None, max_length=40)
    opened_at: date | None = None
    is_active: bool | None = None


class PortfolioHoldingRead(BaseModel):
    id: int
    market: PortfolioMarket
    symbol: str
    symbol_name: str | None = None
    quantity: float
    cost_amount: float | None
    currency: str
    average_cost: float | None = None
    source: str
    source_updated_at: datetime | None = None
    note: str | None = None
    tags: str | None = None
    strategy_horizon: str | None = None
    opened_at: date | None = None
    is_active: bool
    position_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class PortfolioHoldingSummaryRead(BaseModel):
    market: PortfolioMarket
    holding_count: int
    total_cost_amount: float
    cost_basis_count: int
    missing_cost_basis_count: int
    currencies: list[str]
    holdings: list[PortfolioHoldingRead]


class KgiPortfolioSyncRequest(BaseModel):
    market: Literal["tw", "us"]


class KgiPortfolioSyncRead(BaseModel):
    market: Literal["tw", "us"]
    status: Literal["synced"]
    source: Literal["kgi_superpy"]
    holding_count: int
    created_count: int
    updated_count: int
    removed_count: int
    missing_cost_basis_count: int
    warnings: list[str] = Field(default_factory=list)
    source_updated_at: datetime
