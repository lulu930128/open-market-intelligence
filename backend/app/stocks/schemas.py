from datetime import datetime

from pydantic import BaseModel, ConfigDict


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