from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class MarketDailyPriceRead(BaseModel):
    id: int

    source_id: int
    raw_result_id: int

    trade_date: date

    stock_id: str
    stock_name: str | None = None

    trade_volume: int | None = None
    trade_value: int | None = None

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None

    price_change: float | None = None
    transaction_count: int | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParseTwseDailyResultRead(BaseModel):
    raw_result_id: int
    source_id: int
    parser_type: str
    status: str

    parsed_count: int
    skipped_count: int
    inserted_count: int
    replaced_trade_dates: list[date]

    message: str | None = None


class MarketDailyChartRead(BaseModel):
    time: date

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    volume: int | None = None
    trade_value: int | None = None
    transaction_count: int | None = None


class TwseBackfillMonthRead(BaseModel):
    month: str
    url: str

    fetch_log_id: int | None = None
    raw_result_id: int | None = None

    http_status_code: int | None = None
    data_quality_status: str | None = None
    data_quality_message: str | None = None
    row_count: int | None = None

    parsed_count: int = 0
    skipped_count: int = 0

    status: str
    error_message: str | None = None


class TwseBackfillResultRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    source_id: int

    start_date: date
    end_date: date

    requested_month_count: int
    fetched_month_count: int

    parsed_count: int
    inserted_count: int
    skipped_count: int

    status: str
    message: str

    months: list[TwseBackfillMonthRead]