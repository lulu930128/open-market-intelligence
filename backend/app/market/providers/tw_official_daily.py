"""TWSE/TPEx official daily OHLCV parsing and provider descriptors.

The module is market-owned and storage-neutral. It accepts raw response text,
normalizes provider payloads, and produces canonical observations; it never
opens a database transaction or chooses cross-provider fallback.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    CanonicalModel,
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)

from . import tpex, twse


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
TW_DAILY_DATASET_ID = "tw.daily.ohlcv"
TW_BREADTH_DATASET_ID = "tw.market_breadth.daily"
TWSE_DAILY_RESOURCE_ID = "STOCK_DAY_ALL"
TPEX_DAILY_RESOURCE_ID = "tpex_mainboard_quotes"
TWSE_DAILY_PARSER_VERSION = "twse_stock_day_all.v2"
TPEX_DAILY_PARSER_VERSION = "tpex_mainboard_quotes.v2"
_EMPTY_VALUES = {"", "-", "--", "nan", "null", "none"}


class OfficialDailyRecord(CanonicalModel):
    venue: str = Field(pattern=r"^(TWSE|TPEX)$")
    trade_date: date
    symbol: str = Field(min_length=1, max_length=20)
    instrument_name: str | None = Field(default=None, max_length=120)
    open_price: Decimal = Field(gt=0)
    high_price: Decimal = Field(gt=0)
    low_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    trade_volume: int = Field(ge=0)
    trade_value: int | None = Field(default=None, ge=0)
    transaction_count: int | None = Field(default=None, ge=0)
    price_change: Decimal | None = None

    @model_validator(mode="after")
    def _validate_ohlc(self) -> OfficialDailyRecord:
        if self.high_price < max(
            self.open_price,
            self.low_price,
            self.close_price,
        ):
            raise ValueError("official daily high price is inconsistent")
        if self.low_price > min(
            self.open_price,
            self.high_price,
            self.close_price,
        ):
            raise ValueError("official daily low price is inconsistent")
        return self


class OfficialDailyParseIssue(CanonicalModel):
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    count: int = Field(ge=1)


class OfficialDailyParseResult(CanonicalModel):
    venue: str = Field(pattern=r"^(TWSE|TPEX)$")
    input_row_count: int = Field(ge=0)
    matched_row_count: int = Field(ge=0)
    records: tuple[OfficialDailyRecord, ...] = Field(default=(), max_length=20_000)
    issues: tuple[OfficialDailyParseIssue, ...] = Field(default=(), max_length=32)


TWSE_OFFICIAL_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=twse.OPENAPI_PROVIDER,
    market=Market.TW,
    capability_id="daily.ohlcv",
    resource_id=TWSE_DAILY_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.INSTRUMENT, DescriptorTargetKind.DATASET),
    dataset_ids=(TW_DAILY_DATASET_ID,),
    dataset_scope_keys=("TWSE",),
    venue_scope=("TWSE",),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1d",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=500,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=("OFFICIAL_COMPLETED_SESSION_ONLY",),
)

TPEX_OFFICIAL_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=tpex.PROVIDER,
    market=Market.TW,
    capability_id="daily.ohlcv",
    resource_id=TPEX_DAILY_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.INSTRUMENT, DescriptorTargetKind.DATASET),
    dataset_ids=(TW_DAILY_DATASET_ID,),
    dataset_scope_keys=("TPEX",),
    venue_scope=("TPEX",),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1d",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=500,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=("OFFICIAL_COMPLETED_SESSION_ONLY",),
)

TW_OFFICIAL_DAILY_DESCRIPTORS = (
    TWSE_OFFICIAL_DAILY_DESCRIPTOR,
    TPEX_OFFICIAL_DAILY_DESCRIPTOR,
)

TWSE_OFFICIAL_BREADTH_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=twse.OPENAPI_PROVIDER,
    market=Market.TW,
    capability_id="market.breadth",
    resource_id=TWSE_DAILY_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.DATASET,),
    dataset_ids=(TW_BREADTH_DATASET_ID,),
    dataset_scope_keys=("TWSE",),
    venue_scope=("TWSE",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=("OFFICIAL_COMPLETED_SESSION_ONLY",),
)

TPEX_OFFICIAL_BREADTH_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=tpex.PROVIDER,
    market=Market.TW,
    capability_id="market.breadth",
    resource_id=TPEX_DAILY_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.DATASET,),
    dataset_ids=(TW_BREADTH_DATASET_ID,),
    dataset_scope_keys=("TPEX",),
    venue_scope=("TPEX",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=("OFFICIAL_COMPLETED_SESSION_ONLY",),
)

TW_OFFICIAL_BREADTH_DESCRIPTORS = (
    TWSE_OFFICIAL_BREADTH_DESCRIPTOR,
    TPEX_OFFICIAL_BREADTH_DESCRIPTOR,
)


def _repair_text(value: str | None) -> str:
    if value is None:
        return ""
    if re.search(r"[\u4e00-\u9fff]", value):
        return value
    try:
        return value.encode("latin1").decode("utf-8-sig")
    except UnicodeError:
        return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _repair_text(str(value)).replace("\ufeff", "").strip()
    return None if normalized.lower() in _EMPTY_VALUES else normalized


def _integer(value: Any) -> int | None:
    normalized = _text(value)
    if normalized is None:
        return None
    match = re.search(r"-?\d+", normalized.replace(",", "").replace(" ", ""))
    return int(match.group()) if match else None


def _decimal(value: Any) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    match = re.search(
        r"-?\d+(?:\.\d+)?",
        normalized.replace(",", "").replace("+", "").replace(" ", ""),
    )
    if match is None:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    normalized = _text(value)
    if normalized is None:
        return None
    digits = re.sub(r"\D", "", normalized)
    try:
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
    except ValueError:
        return None
    return None


def _issues(counter: Counter[str]) -> tuple[OfficialDailyParseIssue, ...]:
    return tuple(
        OfficialDailyParseIssue(reason_code=code, count=count)
        for code, count in sorted(counter.items())
    )


def _record(
    *,
    venue: str,
    trade_date: date | None,
    symbol: str | None,
    instrument_name: str | None,
    open_price: Decimal | None,
    high_price: Decimal | None,
    low_price: Decimal | None,
    close_price: Decimal | None,
    trade_volume: int | None,
    trade_value: int | None,
    transaction_count: int | None,
    price_change: Decimal | None,
) -> tuple[OfficialDailyRecord | None, str | None]:
    if not symbol:
        return None, "SYMBOL_MISSING"
    if trade_date is None:
        return None, "TRADE_DATE_MISSING"
    if any(value is None for value in (open_price, high_price, low_price, close_price)):
        return None, "REQUIRED_OHLC_MISSING"
    if trade_volume is None:
        return None, "TRADE_VOLUME_MISSING"
    try:
        return (
            OfficialDailyRecord(
                venue=venue,
                trade_date=trade_date,
                symbol=symbol,
                instrument_name=instrument_name,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                trade_volume=trade_volume,
                trade_value=trade_value,
                transaction_count=transaction_count,
                price_change=price_change,
            ),
            None,
        )
    except ValueError:
        return None, "CANONICAL_OHLC_INVALID"


def parse_twse_official_daily_payload(
    raw_text: str,
    *,
    target_symbols: frozenset[str] | None = None,
) -> OfficialDailyParseResult:
    payload = json.loads(_repair_text(raw_text).lstrip("\ufeff").strip())
    if not isinstance(payload, list):
        raise ValueError("TWSE official daily payload must be a JSON list")
    issues: Counter[str] = Counter()
    records: list[OfficialDailyRecord] = []
    matched = 0
    seen: set[tuple[str, date]] = set()
    for row in payload:
        if not isinstance(row, dict):
            issues["ROW_NOT_OBJECT"] += 1
            continue
        symbol = _text(row.get("Code") or row.get("code") or row.get("證券代號"))
        if target_symbols is not None and symbol not in target_symbols:
            continue
        matched += 1
        record, issue = _record(
            venue="TWSE",
            trade_date=_date(
                row.get("Date")
                or row.get("date")
                or row.get("TradeDate")
                or row.get("交易日期")
            ),
            symbol=symbol,
            instrument_name=_text(row.get("Name") or row.get("name") or row.get("證券名稱")),
            open_price=_decimal(row.get("OpeningPrice") or row.get("open_price")),
            high_price=_decimal(row.get("HighestPrice") or row.get("high_price")),
            low_price=_decimal(row.get("LowestPrice") or row.get("low_price")),
            close_price=_decimal(row.get("ClosingPrice") or row.get("close_price")),
            trade_volume=_integer(row.get("TradeVolume") or row.get("trade_volume")),
            trade_value=_integer(row.get("TradeValue") or row.get("trade_value")),
            transaction_count=_integer(row.get("Transaction") or row.get("transaction_count")),
            price_change=_decimal(row.get("Change") or row.get("price_change")),
        )
        if issue is not None:
            issues[issue] += 1
            continue
        assert record is not None
        key = (record.symbol, record.trade_date)
        if key in seen:
            issues["DUPLICATE_SYMBOL_DATE"] += 1
            continue
        seen.add(key)
        records.append(record)
    if target_symbols is not None:
        missing_targets = target_symbols - {record.symbol for record in records}
        if missing_targets:
            issues["TARGET_SYMBOL_NOT_FOUND"] += len(missing_targets)
    return OfficialDailyParseResult(
        venue="TWSE",
        input_row_count=len(payload),
        matched_row_count=matched,
        records=tuple(records),
        issues=_issues(issues),
    )


def _first_tpex_table(payload: dict[str, Any]) -> list[Any]:
    tables = payload.get("tables") or payload.get("Tables") or []
    if isinstance(tables, list):
        for table in tables:
            if isinstance(table, dict) and isinstance(table.get("data"), list):
                return table["data"]
    data = payload.get("data")
    if isinstance(data, list):
        return data
    raise ValueError("TPEx official daily payload has no data table")


def parse_tpex_official_daily_payload(
    raw_text: str,
    *,
    target_symbols: frozenset[str] | None = None,
) -> OfficialDailyParseResult:
    payload = json.loads(_repair_text(raw_text).lstrip("\ufeff").strip())
    if not isinstance(payload, (dict, list)):
        raise ValueError("TPEx official daily payload must be a JSON object or list")
    rows = payload if isinstance(payload, list) else _first_tpex_table(payload)
    payload_date = None if isinstance(payload, list) else _date(payload.get("date"))
    issues: Counter[str] = Counter()
    records: list[OfficialDailyRecord] = []
    matched = 0
    seen: set[tuple[str, date]] = set()
    for row in rows:
        if isinstance(row, dict):
            symbol = _text(row.get("SecuritiesCompanyCode"))
            values = {
                "trade_date": _date(row.get("Date")) or payload_date,
                "instrument_name": _text(row.get("CompanyName")),
                "open_price": _decimal(row.get("Open")),
                "high_price": _decimal(row.get("High")),
                "low_price": _decimal(row.get("Low")),
                "close_price": _decimal(row.get("Close")),
                "trade_volume": _integer(row.get("TradingShares")),
                "trade_value": _integer(row.get("TransactionAmount")),
                "transaction_count": _integer(row.get("TransactionNumber")),
                "price_change": _decimal(row.get("Change")),
            }
        elif isinstance(row, list):
            def value(index: int) -> Any:
                return row[index] if index < len(row) else None

            symbol = _text(value(0))
            values = {
                "trade_date": payload_date,
                "instrument_name": _text(value(1)),
                "close_price": _decimal(value(2)),
                "open_price": _decimal(value(4)),
                "high_price": _decimal(value(5)),
                "low_price": _decimal(value(6)),
                "trade_volume": _integer(value(8)),
                "trade_value": _integer(value(9)),
                "transaction_count": _integer(value(10)),
                "price_change": _decimal(value(3)),
            }
        else:
            issues["ROW_INVALID_SHAPE"] += 1
            continue
        if target_symbols is not None and symbol not in target_symbols:
            continue
        matched += 1
        record, issue = _record(venue="TPEX", symbol=symbol, **values)
        if issue is not None:
            issues[issue] += 1
            continue
        assert record is not None
        key = (record.symbol, record.trade_date)
        if key in seen:
            issues["DUPLICATE_SYMBOL_DATE"] += 1
            continue
        seen.add(key)
        records.append(record)
    if target_symbols is not None:
        missing_targets = target_symbols - {record.symbol for record in records}
        if missing_targets:
            issues["TARGET_SYMBOL_NOT_FOUND"] += len(missing_targets)
    return OfficialDailyParseResult(
        venue="TPEX",
        input_row_count=len(rows),
        matched_row_count=matched,
        records=tuple(records),
        issues=_issues(issues),
    )


def official_daily_record_to_bar(
    record: OfficialDailyRecord,
    *,
    instrument: InstrumentKey,
    provider: str,
    source: str,
    parser_version: str,
    fetched_at: datetime,
    content_hash: str,
) -> BarObservation:
    if instrument.market is not Market.TW:
        raise ValueError("official Taiwan daily bars require market=TW")
    if instrument.symbol != record.symbol or instrument.venue != record.venue:
        raise ValueError("official daily record does not match requested instrument")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("official daily fetched_at must be timezone-aware")
    start_at = datetime.combine(record.trade_date, time(9), tzinfo=TAIWAN_TZ)
    end_at = datetime.combine(record.trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
    return BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=provider,
            source=source,
            authority=AuthorityClass.EXCHANGE,
            raw_contract_version=parser_version,
            event_at=end_at,
            fetched_at=fetched_at.astimezone(timezone.utc),
            cache_hit=False,
            content_hash=content_hash,
            observation_id=(
                f"acquired:{content_hash[:16]}:{record.venue}:"
                f"{record.symbol}:{record.trade_date.isoformat()}"
            ),
        ),
        interval="1d",
        start_at=start_at,
        end_at=end_at,
        open_price=record.open_price,
        high_price=record.high_price,
        low_price=record.low_price,
        close_price=record.close_price,
        volume=Quantity(value=Decimal(record.trade_volume), unit=QuantityUnit.SHARE),
        instrument_name=record.instrument_name,
        turnover_value=(Decimal(record.trade_value) if record.trade_value is not None else None),
        turnover_currency=("TWD" if record.trade_value is not None else None),
        trade_count=record.transaction_count,
        price_change=record.price_change,
        finalization=BarFinalization.FINAL,
    )


def source_name_for_resource(resource_id: str) -> str:
    if resource_id == TWSE_DAILY_RESOURCE_ID:
        return TWSE_DAILY_TRADING_SOURCE_NAME
    if resource_id == TPEX_DAILY_RESOURCE_ID:
        return TPEX_DAILY_QUOTES_SOURCE_NAME
    raise ValueError(f"unsupported Taiwan official daily resource: {resource_id}")


def parser_version_for_resource(resource_id: str) -> str:
    if resource_id == TWSE_DAILY_RESOURCE_ID:
        return TWSE_DAILY_PARSER_VERSION
    if resource_id == TPEX_DAILY_RESOURCE_ID:
        return TPEX_DAILY_PARSER_VERSION
    raise ValueError(f"unsupported Taiwan official daily resource: {resource_id}")


def endpoint_for_resource(resource_id: str) -> str:
    if resource_id == TWSE_DAILY_RESOURCE_ID:
        return twse.DAILY_QUOTES_URL
    if resource_id == TPEX_DAILY_RESOURCE_ID:
        return tpex.DAILY_QUOTES_URL
    raise ValueError(f"unsupported Taiwan official daily resource: {resource_id}")


__all__ = [
    "OfficialDailyParseIssue",
    "OfficialDailyParseResult",
    "OfficialDailyRecord",
    "TPEX_DAILY_PARSER_VERSION",
    "TPEX_DAILY_RESOURCE_ID",
    "TPEX_OFFICIAL_DAILY_DESCRIPTOR",
    "TPEX_OFFICIAL_BREADTH_DESCRIPTOR",
    "TW_BREADTH_DATASET_ID",
    "TWSE_DAILY_PARSER_VERSION",
    "TWSE_DAILY_RESOURCE_ID",
    "TWSE_OFFICIAL_DAILY_DESCRIPTOR",
    "TWSE_OFFICIAL_BREADTH_DESCRIPTOR",
    "TW_OFFICIAL_BREADTH_DESCRIPTORS",
    "TW_DAILY_DATASET_ID",
    "TW_OFFICIAL_DAILY_DESCRIPTORS",
    "endpoint_for_resource",
    "official_daily_record_to_bar",
    "parse_tpex_official_daily_payload",
    "parse_twse_official_daily_payload",
    "parser_version_for_resource",
    "source_name_for_resource",
]
