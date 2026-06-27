from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ResourceProviderContractRead(BaseModel):
    kind: str
    market: str
    execution_enabled: bool
    ai_execution_enabled: bool
    trade_candidate_symbols: list[str]
    notes: list[str]
    root_folders: list[dict[str, Any]]
    providers: dict[str, Any]
    instruments: list[dict[str, Any]]


class ResourceInstrumentRead(BaseModel):
    key: str
    root_folder: str
    group: str
    asset_class: str
    name: str
    display_name: str
    symbol: str
    provider: str
    exchange: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_type: str
    resources: list[str]
    tradable: bool
    trade_candidate: bool
    provider_status: str
    role: str


class ResourceQuoteRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    name: str | None = None
    root_folder: str
    group: str
    asset_class: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_key: str
    contract_month: str | None = None

    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    previous_close: float | None = None
    price_change: float | None = None
    price_change_pct: float | None = None
    volume: float | None = None
    open_interest: float | None = None

    event_time: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResourceOhlcvBarRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    name: str | None = None
    root_folder: str
    group: str
    asset_class: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_key: str
    contract_month: str | None = None
    interval: str
    bar_time: datetime

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None

    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
