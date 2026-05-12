from datetime import datetime, date

from pydantic import BaseModel, ConfigDict, Field


class WatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class WatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class WatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    children: list["WatchlistGroupTreeRead"] = []


class WatchlistItemCreate(BaseModel):
    group_id: int
    stock_id: str = Field(..., min_length=1, max_length=20)

    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class WatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    stock_id: str | None = Field(default=None, min_length=1, max_length=20)

    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class WatchlistItemRead(BaseModel):
    id: int

    group_id: int
    stock_id: str
    stock_name: str | None = None

    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool

    created_at: datetime
    updated_at: datetime


class WatchlistBackfillStockResultRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    status: str
    parsed_count: int = 0
    inserted_count: int = 0
    skipped_count: int = 0

    message: str | None = None
    error_message: str | None = None


class WatchlistGroupBackfillResultRead(BaseModel):
    group_id: int
    include_children: bool

    start_date: date
    end_date: date

    requested_stock_count: int
    success_count: int
    warning_count: int
    error_count: int
    skipped_count: int

    results: list[WatchlistBackfillStockResultRead]


class WatchlistLatestIndicatorRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    time: date | None = None
    close: float | None = None
    volume: int | None = None

    change: float | None = None
    change_pct: float | None = None

    ma: dict[str, float | None] = Field(default_factory=dict)
    volume_ma: dict[str, float | None] = Field(default_factory=dict)

    status: str
    error_message: str | None = None


class WatchlistGroupLatestIndicatorsRead(BaseModel):
    group_id: int
    include_children: bool

    requested_stock_count: int
    success_count: int
    no_data_count: int
    error_count: int

    results: list[WatchlistLatestIndicatorRead]


class WatchlistSignalRead(BaseModel):
    key: str
    label: str
    direction: str
    level: str
    message: str
    value: float | None = None
    reference: float | None = None


class WatchlistStockLatestSignalsRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    time: date | None = None
    close: float | None = None
    volume: int | None = None
    change_pct: float | None = None

    score: int
    status: str

    signals: list[WatchlistSignalRead] = Field(default_factory=list)
    error_message: str | None = None


class WatchlistGroupLatestSignalsRead(BaseModel):
    group_id: int
    include_children: bool

    requested_stock_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    no_data_count: int
    error_count: int

    results: list[WatchlistStockLatestSignalsRead]