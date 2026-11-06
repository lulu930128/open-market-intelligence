"""Pure TWSE/TPEx official completed-session market-index adapters."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field

from app.market.official_index_contract import (
    TPEX_INDEX_SOURCE_NAME,
    TPEX_HIGHLIGHT_INDEX_PARSER_VERSION,
    TWSE_INDEX_SOURCE_NAME,
    TWSE_RWD_INDEX_PARSER_VERSION,
    TW_INDEX_DATASET_ID,
)
from app.market.index_parsers import parse_twse_market_daily_history_rows
from app.market.providers import tpex, twse
from app.sources.defaults import TPEX_MARKET_HIGHLIGHT_SOURCE_NAME
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    CanonicalModel,
    Market,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
TWSE_INDEX_RESOURCE_ID = "twse_fmtqik"
TWSE_RWD_INDEX_RESOURCE_ID = "twse_rwd_fmtqik"
TPEX_INDEX_RESOURCE_ID = "tpex_daily_trading_index"
TPEX_HIGHLIGHT_INDEX_RESOURCE_ID = "tpex_after_trading_highlight"
TWSE_INDEX_PARSER_VERSION = "twse.fmtqik.v1"
TPEX_INDEX_PARSER_VERSION = "tpex.daily_trading_index.v1"


TWSE_OFFICIAL_INDEX_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=twse.OPENAPI_PROVIDER,
    market=Market.TW,
    capability_id="market.index.daily",
    resource_id=TWSE_INDEX_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.DATASET,),
    dataset_ids=(TW_INDEX_DATASET_ID,),
    dataset_scope_keys=("TAIEX",),
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

TPEX_OFFICIAL_INDEX_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=tpex.PROVIDER,
    market=Market.TW,
    capability_id="market.index.daily",
    resource_id=TPEX_INDEX_RESOURCE_ID,
    authority=AuthorityClass.EXCHANGE,
    target_kinds=(DescriptorTargetKind.DATASET,),
    dataset_ids=(TW_INDEX_DATASET_ID,),
    dataset_scope_keys=("TPEX",),
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

TPEX_HIGHLIGHT_INDEX_DESCRIPTOR = TPEX_OFFICIAL_INDEX_DESCRIPTOR.model_copy(update={
    "resource_id": TPEX_HIGHLIGHT_INDEX_RESOURCE_ID,
    "priority": 20,
    "limitations": ("OFFICIAL_COMPLETED_SESSION_ONLY", "INDEX_MARKET_TOTALS_PARTIAL"),
})

TWSE_RWD_INDEX_DESCRIPTOR = TWSE_OFFICIAL_INDEX_DESCRIPTOR.model_copy(update={
    "provider_key": twse.RWD_PROVIDER,
    "resource_id": TWSE_RWD_INDEX_RESOURCE_ID,
    "priority": 20,
})

TW_OFFICIAL_INDEX_DESCRIPTORS = (
    TWSE_OFFICIAL_INDEX_DESCRIPTOR,
    TWSE_RWD_INDEX_DESCRIPTOR,
    TPEX_OFFICIAL_INDEX_DESCRIPTOR,
    TPEX_HIGHLIGHT_INDEX_DESCRIPTOR,
)


class OfficialIndexDailyRecord(CanonicalModel):
    index_id: str = Field(min_length=1, max_length=32)
    venue: str = Field(min_length=1, max_length=32)
    trade_date: date
    close_value: Decimal = Field(gt=0)
    price_change: Decimal
    trade_volume: int | None = Field(default=None, ge=0)
    trade_value: int | None = Field(default=None, ge=0)
    transaction_count: int | None = Field(default=None, ge=0)


class OfficialIndexParseIssue(CanonicalModel):
    reason_code: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=1)


class OfficialIndexParseResult(CanonicalModel):
    index_id: str
    input_row_count: int = Field(ge=0)
    records: tuple[OfficialIndexDailyRecord, ...] = ()
    issues: tuple[OfficialIndexParseIssue, ...] = ()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    digits = "".join(character for character in text if character.isdigit())
    try:
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None
    return None


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None or text in {"--", "---", "-"}:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _integer(value: Any) -> int | None:
    parsed = _decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _issues(values: Counter[str]) -> tuple[OfficialIndexParseIssue, ...]:
    return tuple(
        OfficialIndexParseIssue(reason_code=reason, count=count)
        for reason, count in sorted(values.items())
    )


def _parse_official_index_payload(
    raw_text: str,
    *,
    index_id: str,
) -> OfficialIndexParseResult:
    payload = json.loads(str(raw_text or "").lstrip("\ufeff").strip())
    if not isinstance(payload, list):
        raise ValueError("official market-index payload must be a JSON list")
    if index_id == "TAIEX":
        venue = "TWSE"
        close_key = "TAIEX"
        trade_value_key = "TradeValue"
        transaction_key = "Transaction"
    elif index_id == "TPEX":
        venue = "TPEX"
        close_key = "TPExIndex"
        trade_value_key = "TradeAmount"
        transaction_key = "NumberOfTransactions"
    else:
        raise ValueError("official Taiwan index_id must be TAIEX or TPEX")
    issues: Counter[str] = Counter()
    records: list[OfficialIndexDailyRecord] = []
    seen_dates: set[date] = set()
    for raw_row in payload:
        if not isinstance(raw_row, dict):
            issues["ROW_NOT_OBJECT"] += 1
            continue
        trade_date = _date(raw_row.get("Date"))
        close_value = _decimal(raw_row.get(close_key))
        price_change = _decimal(raw_row.get("Change"))
        if trade_date is None:
            issues["TRADE_DATE_INVALID"] += 1
            continue
        if close_value is None or close_value <= 0:
            issues["INDEX_CLOSE_INVALID"] += 1
            continue
        if price_change is None:
            issues["PRICE_CHANGE_UNKNOWN"] += 1
            continue
        if trade_date in seen_dates:
            issues["DUPLICATE_TRADE_DATE"] += 1
            continue
        seen_dates.add(trade_date)
        records.append(
            OfficialIndexDailyRecord(
                index_id=index_id,
                venue=venue,
                trade_date=trade_date,
                close_value=close_value,
                price_change=price_change,
                trade_volume=_integer(raw_row.get("TradeVolume")),
                trade_value=_integer(raw_row.get(trade_value_key)),
                transaction_count=_integer(raw_row.get(transaction_key)),
            )
        )
    records.sort(key=lambda item: item.trade_date)
    return OfficialIndexParseResult(
        index_id=index_id,
        input_row_count=len(payload),
        records=tuple(records),
        issues=_issues(issues),
    )


def parse_twse_official_index_payload(raw_text: str) -> OfficialIndexParseResult:
    return _parse_official_index_payload(raw_text, index_id="TAIEX")


def parse_twse_rwd_index_payload(raw_text: str) -> OfficialIndexParseResult:
    """Qualify the dated monthly FMTQIK table, never its request/header date."""
    payload = json.loads(raw_text.lstrip("\ufeff").strip())
    if not isinstance(payload, dict) or str(payload.get("stat", "")).upper() != "OK":
        raise ValueError("TWSE RWD index payload status is not OK")
    fields = ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"]
    rows = payload.get("data")
    if payload.get("fields") != fields or not isinstance(rows, list):
        raise ValueError("TWSE RWD index table schema mismatch")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("TWSE RWD index row shape mismatch")
        # The legacy pure parser converts numeric aggregates to int. Require
        # actual nonnegative integers first, rather than accepting truncation.
        if any(_integer(row[i]) is None or _integer(row[i]) < 0 for i in (1, 2, 3)):
            raise ValueError("TWSE RWD index market totals invalid")
    parsed = parse_twse_market_daily_history_rows(payload)
    if len(parsed) != len(rows):
        raise ValueError("TWSE RWD index row date invalid")
    records = tuple(OfficialIndexDailyRecord(index_id="TAIEX", venue="TWSE", **item) for item in parsed)
    if len({record.trade_date for record in records}) != len(records):
        raise ValueError("TWSE RWD index duplicate trade date")
    return OfficialIndexParseResult(index_id="TAIEX", input_row_count=len(rows),
                                    records=tuple(sorted(records, key=lambda record: record.trade_date)))


def parse_tpex_official_index_payload(raw_text: str) -> OfficialIndexParseResult:
    return _parse_official_index_payload(raw_text, index_id="TPEX")


def parse_tpex_highlight_index_payload(raw_text: str) -> OfficialIndexParseResult:
    """Use only exact published close/change; rounded, scoped totals stay unknown."""
    payload = json.loads(raw_text.lstrip("\ufeff").strip())
    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        raise ValueError("TPEx highlight payload status is not OK")
    trade_date = _date(payload.get("date"))
    tables = [table for table in payload.get("tables", []) if isinstance(table, dict)
              and "收市指數" in table.get("fields", []) and "指數漲跌" in table.get("fields", [])]
    if trade_date is None or len(tables) != 1:
        raise ValueError("TPEx highlight index date/table is ambiguous")
    table = tables[0]
    fields, rows = table["fields"], table.get("data", [])
    if _date(table.get("date")) != trade_date or len(rows) != 1 or len(fields) != len(set(fields)):
        raise ValueError("TPEx highlight index table/date mismatch")
    row = rows[0]
    if not isinstance(row, list) or len(row) != len(fields):
        raise ValueError("TPEx highlight index row shape mismatch")
    close = _decimal(row[fields.index("收市指數")])
    change = _decimal(row[fields.index("指數漲跌")])
    if close is None or close <= 0 or change is None:
        raise ValueError("TPEx highlight index close/change missing")
    return OfficialIndexParseResult(
        index_id="TPEX", input_row_count=1,
        records=(OfficialIndexDailyRecord(index_id="TPEX", venue="TPEX", trade_date=trade_date,
                                         close_value=close, price_change=change),),
        issues=(OfficialIndexParseIssue(reason_code="INDEX_MARKET_TOTALS_PARTIAL", count=1),
                OfficialIndexParseIssue(reason_code="TPEX_HIGHLIGHT_TOTALS_OMITTED", count=1)),
    )


def official_index_record_to_observation(
    record: OfficialIndexDailyRecord,
    *,
    provider: str,
    source: str,
    parser_version: str,
    fetched_at: datetime,
    content_hash: str,
) -> MarketIndexObservation:
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("official index fetched_at must be timezone-aware")
    event_at = datetime.combine(
        record.trade_date,
        time(13, 30),
        tzinfo=TAIWAN_TZ,
    )
    incomplete = any(
        value is None
        for value in (
            record.trade_volume,
            record.trade_value,
            record.transaction_count,
        )
    )
    return MarketIndexObservation(
        market=Market.TW,
        index_id=record.index_id,
        venue=record.venue,
        lineage=SourceLineage(
            provider=provider,
            source=source,
            authority=AuthorityClass.EXCHANGE,
            raw_contract_version=parser_version,
            event_at=event_at,
            fetched_at=fetched_at.astimezone(timezone.utc),
            cache_hit=False,
            observation_id=(
                f"acquired:{content_hash[:16]}:{record.index_id}:"
                f"{record.trade_date.isoformat()}"
            ),
            content_hash=content_hash,
        ),
        session=MarketSession.CLOSED,
        trade_date=record.trade_date,
        close_value=record.close_value,
        price_change=record.price_change,
        trade_volume=(
            Quantity(value=Decimal(record.trade_volume), unit=QuantityUnit.SHARE)
            if record.trade_volume is not None
            else None
        ),
        trade_value=(
            Decimal(record.trade_value) if record.trade_value is not None else None
        ),
        currency=("TWD" if record.trade_value is not None else None),
        transaction_count=record.transaction_count,
        state=(ObservationState.PARTIAL if incomplete else ObservationState.AVAILABLE),
        value_semantics="official_market_index_close",
        finalization=BarFinalization.FINAL,
        official=True,
        provisional=False,
    )


def source_name_for_index_resource(resource_id: str) -> str:
    if resource_id == TPEX_HIGHLIGHT_INDEX_RESOURCE_ID:
        return TPEX_MARKET_HIGHLIGHT_SOURCE_NAME
    if resource_id in {TWSE_INDEX_RESOURCE_ID, TWSE_RWD_INDEX_RESOURCE_ID}:
        return TWSE_INDEX_SOURCE_NAME
    if resource_id == TPEX_INDEX_RESOURCE_ID:
        return TPEX_INDEX_SOURCE_NAME
    raise ValueError(f"unsupported Taiwan official index resource: {resource_id}")


def parser_version_for_index_resource(resource_id: str) -> str:
    if resource_id == TWSE_RWD_INDEX_RESOURCE_ID:
        return TWSE_RWD_INDEX_PARSER_VERSION
    if resource_id == TPEX_HIGHLIGHT_INDEX_RESOURCE_ID:
        return TPEX_HIGHLIGHT_INDEX_PARSER_VERSION
    if resource_id == TWSE_INDEX_RESOURCE_ID:
        return TWSE_INDEX_PARSER_VERSION
    if resource_id == TPEX_INDEX_RESOURCE_ID:
        return TPEX_INDEX_PARSER_VERSION
    raise ValueError(f"unsupported Taiwan official index resource: {resource_id}")


def endpoint_for_index_resource(resource_id: str) -> str:
    if resource_id == TWSE_RWD_INDEX_RESOURCE_ID:
        return twse.MARKET_DAILY_HISTORY_URL
    if resource_id == TPEX_HIGHLIGHT_INDEX_RESOURCE_ID:
        return tpex.MARKET_HIGHLIGHT_URL
    if resource_id == TWSE_INDEX_RESOURCE_ID:
        return twse.MARKET_DAILY_URL
    if resource_id == TPEX_INDEX_RESOURCE_ID:
        return tpex.DAILY_INDEX_URL
    raise ValueError(f"unsupported Taiwan official index resource: {resource_id}")


__all__ = [
    "OfficialIndexDailyRecord",
    "OfficialIndexParseIssue",
    "OfficialIndexParseResult",
    "TPEX_INDEX_RESOURCE_ID",
    "TPEX_HIGHLIGHT_INDEX_RESOURCE_ID",
    "TPEX_HIGHLIGHT_INDEX_DESCRIPTOR",
    "TPEX_INDEX_SOURCE_NAME",
    "TWSE_INDEX_RESOURCE_ID",
    "TWSE_RWD_INDEX_RESOURCE_ID",
    "TWSE_RWD_INDEX_DESCRIPTOR",
    "TWSE_INDEX_SOURCE_NAME",
    "TW_INDEX_DATASET_ID",
    "TW_OFFICIAL_INDEX_DESCRIPTORS",
    "endpoint_for_index_resource",
    "official_index_record_to_observation",
    "parse_tpex_official_index_payload",
    "parse_tpex_highlight_index_payload",
    "parse_twse_official_index_payload",
    "parse_twse_rwd_index_payload",
    "parser_version_for_index_resource",
    "source_name_for_index_resource",
]
