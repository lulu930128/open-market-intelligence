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
    TWSE_INDEX_SOURCE_NAME,
    TW_INDEX_DATASET_ID,
)
from app.market.providers import tpex, twse
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
TPEX_INDEX_RESOURCE_ID = "tpex_daily_trading_index"
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

TW_OFFICIAL_INDEX_DESCRIPTORS = (
    TWSE_OFFICIAL_INDEX_DESCRIPTOR,
    TPEX_OFFICIAL_INDEX_DESCRIPTOR,
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


def parse_tpex_official_index_payload(raw_text: str) -> OfficialIndexParseResult:
    return _parse_official_index_payload(raw_text, index_id="TPEX")


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
    if resource_id == TWSE_INDEX_RESOURCE_ID:
        return TWSE_INDEX_SOURCE_NAME
    if resource_id == TPEX_INDEX_RESOURCE_ID:
        return TPEX_INDEX_SOURCE_NAME
    raise ValueError(f"unsupported Taiwan official index resource: {resource_id}")


def parser_version_for_index_resource(resource_id: str) -> str:
    if resource_id == TWSE_INDEX_RESOURCE_ID:
        return TWSE_INDEX_PARSER_VERSION
    if resource_id == TPEX_INDEX_RESOURCE_ID:
        return TPEX_INDEX_PARSER_VERSION
    raise ValueError(f"unsupported Taiwan official index resource: {resource_id}")


def endpoint_for_index_resource(resource_id: str) -> str:
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
    "TPEX_INDEX_SOURCE_NAME",
    "TWSE_INDEX_RESOURCE_ID",
    "TWSE_INDEX_SOURCE_NAME",
    "TW_INDEX_DATASET_ID",
    "TW_OFFICIAL_INDEX_DESCRIPTORS",
    "endpoint_for_index_resource",
    "official_index_record_to_observation",
    "parse_tpex_official_index_payload",
    "parse_twse_official_index_payload",
    "parser_version_for_index_resource",
    "source_name_for_index_resource",
]
