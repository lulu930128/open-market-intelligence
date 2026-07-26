from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.market.schemas import (
    TaiwanDispositionStatusRead,
    TaiwanStockEventHistoryRead,
    TaiwanStockEventSummaryRead,
)


class StockMasterRead(BaseModel):
    id: int

    stock_id: str
    stock_name: str | None = None

    market: str
    instrument_type: str
    industry: str | None = None
    category: str | None = None

    is_active: bool
    notes: str | None = None
    disposition: TaiwanDispositionStatusRead | None = None
    upcoming_events: TaiwanStockEventSummaryRead | None = None
    event_history: TaiwanStockEventHistoryRead | None = None

    first_seen_at: datetime
    last_seen_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockMasterUpdate(BaseModel):
    stock_name: str | None = None
    market: str | None = None
    instrument_type: str | None = None
    industry: str | None = None
    category: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class StockSyncResultRead(BaseModel):
    status: str
    scanned_count: int
    created_count: int
    updated_count: int
    message: str


class StockProfileRead(BaseModel):
    id: int

    source_id: int
    raw_result_id: int

    report_date: date | None = None

    stock_id: str
    company_name: str | None = None
    short_name: str | None = None

    market: str
    industry: str | None = None

    listed_date: date | None = None
    established_date: date | None = None

    paid_in_capital: int | None = None
    issued_shares: int | None = None
    private_placement_shares: int | None = None
    preferred_shares: int | None = None

    chairman: str | None = None
    general_manager: str | None = None
    spokesman: str | None = None
    spokesman_title: str | None = None

    phone: str | None = None
    address: str | None = None
    website: str | None = None
    email: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockMarketCapRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    trade_date: date | None = None
    close_price: float | None = None

    issued_shares: int | None = None
    market_cap: float | None = None

    profile_report_date: date | None = None
