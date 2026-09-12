"""Pure Japanese daily adapters with explicit rejection and immutable identity."""

from dataclasses import dataclass
from collections import Counter
from datetime import date, datetime, time
from hashlib import sha256
import json

from pydantic import ValidationError

from app.jp_market.market_data.descriptors import daily_descriptor
from app.jp_market.sources import JPDailyPriceRecord, parse_yahoo_daily_prices
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE
from app.jp_market.session_policy import jp_close_time
from app.market_data.contracts import (
    BarFinalization, BarObservation, InstrumentKey, InstrumentType, Market,
    Quantity, QuantityUnit, SourceLineage,
)
from app.market_data.integration_contracts import RawFetchReceiptV1


@dataclass(frozen=True)
class DailyAdapterResult:
    receipt: RawFetchReceiptV1
    bars: tuple[BarObservation, ...]
    rejections: tuple[tuple[str, str], ...]


def jp_daily_session_end(trade_date: date) -> datetime:
    close = jp_close_time(trade_date)
    return datetime.combine(trade_date, close, tzinfo=JP_MARKET_TIMEZONE)


def make_receipt(payload: dict, *, provider: str, fetched_at: datetime, url: str | None) -> RawFetchReceiptV1:
    descriptor = daily_descriptor(provider)
    raw_text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return RawFetchReceiptV1(
        provider=provider, source=descriptor.resource_id, resource_id=descriptor.resource_id,
        fetched_at=fetched_at, method="GET", url=url, status_code=200,
        content_type="application/json", content_hash=sha256(raw_text.encode("utf-8")).hexdigest(),
        raw_text=raw_text, parser_version=f"omi.jp.{provider}.daily.v1",
    )


def adapt_daily_records(records: list[JPDailyPriceRecord], *, instrument: InstrumentKey,
                        receipt: RawFetchReceiptV1) -> DailyAdapterResult:
    descriptor = daily_descriptor(receipt.provider)
    if (instrument.market is not Market.JP or instrument.venue not in descriptor.venue_scope
            or instrument.instrument_type not in descriptor.instrument_types):
        raise ValueError("JP daily instrument is outside provider coverage")
    accepted = []
    rejected = []
    date_counts = Counter(record.trade_date for record in records)
    for record in records:
        reason = None
        if record.symbol != instrument.symbol or record.provider != receipt.provider:
            reason = "INSTRUMENT_OR_PROVIDER_MISMATCH"
        elif record.currency != "JPY":
            reason = "CURRENCY_MISMATCH"
        elif date_counts[record.trade_date] > 1:
            reason = "DUPLICATE_TRADE_DATE"
        end_at = jp_daily_session_end(record.trade_date)
        if end_at > receipt.fetched_at:
            reason = "SESSION_NOT_COMPLETED"
        if reason:
            rejected.append((record.trade_date.isoformat(), reason))
            continue
        lineage = SourceLineage(
            provider=receipt.provider, source=receipt.source, authority=descriptor.authority,
            raw_contract_version=receipt.parser_version, event_at=end_at,
            received_at=receipt.fetched_at, fetched_at=receipt.fetched_at,
            raw_receipt_id=receipt.content_hash, content_hash=receipt.content_hash,
            observation_id=sha256(
                f"{instrument.model_dump_json()}|{record.trade_date}|raw|{receipt.parser_version}|{receipt.content_hash}|{receipt.fetched_at.isoformat()}".encode()
            ).hexdigest(),
        )
        try:
            is_index = instrument.instrument_type is InstrumentType.INDEX
            bar = BarObservation(
                instrument=instrument, lineage=lineage, interval="1d",
                start_at=datetime.combine(record.trade_date, time(9), tzinfo=JP_MARKET_TIMEZONE),
                end_at=end_at, open_price=record.open_price, high_price=record.high_price,
                low_price=record.low_price, close_price=record.close_price,
                volume=(Quantity(value=record.trade_volume, unit=QuantityUnit.SHARE)
                        if record.trade_volume is not None and not is_index else None),
                volume_status="not_applicable" if is_index else "observed" if record.trade_volume is not None else "missing",
                price_basis="raw", finalization=BarFinalization.FINAL,
            )
        except (ValueError, ValidationError):
            rejected.append((record.trade_date.isoformat(), "INVALID_CANONICAL_BAR"))
            continue
        accepted.append(bar)
    return DailyAdapterResult(receipt, tuple(sorted(accepted, key=lambda b: b.start_at)), tuple(rejected))


def adapt_yahoo_daily(payload: dict, *, instrument: InstrumentKey, fetched_at: datetime,
                      url: str | None = None) -> DailyAdapterResult:
    result = ((payload.get("chart") or {}).get("result") or [{}])[0]
    meta = result.get("meta") or {}
    if meta.get("symbol") != instrument.symbol:
        raise ValueError("Yahoo response symbol does not match JP instrument")
    if meta.get("currency") != "JPY":
        raise ValueError("Yahoo JP currency must be explicitly JPY")
    if meta.get("exchangeTimezoneName") not in (None, "Asia/Tokyo") or meta.get("gmtoffset") != 32400:
        raise ValueError("Yahoo JP timestamps require Tokyo timezone evidence")
    receipt = make_receipt(payload, provider="yahoo_chart", fetched_at=fetched_at, url=url)
    records = parse_yahoo_daily_prices(payload, symbol=instrument.symbol, source_url=url)
    adapted = adapt_daily_records(records, instrument=instrument, receipt=receipt)
    represented = {record.trade_date for record in records}
    skipped = tuple(
        (datetime.fromtimestamp(int(stamp), tz=JP_MARKET_TIMEZONE).date().isoformat(), "NO_TRADE_OR_MISSING_OHLC")
        for stamp in result.get("timestamp", [])
        if datetime.fromtimestamp(int(stamp), tz=JP_MARKET_TIMEZONE).date() not in represented
    )
    return DailyAdapterResult(receipt, adapted.bars, adapted.rejections + skipped)


def adapt_jquants_daily(payload: dict, *, instrument: InstrumentKey, fetched_at: datetime,
                        start_date: date, end_date: date, url: str | None = None) -> DailyAdapterResult:
    """Use V2 raw O/H/L/C/Vo; never fill raw fields from adjusted fields."""
    if not isinstance(payload.get("data"), list) or len(payload["data"]) > 5000:
        raise ValueError("J-Quants daily requires a bounded data array")
    receipt = make_receipt(payload, provider="jquants", fetched_at=fetched_at, url=url)
    local_code = instrument.symbol.removesuffix(".T")
    valid_codes = {local_code, local_code + "0"} if len(local_code) == 4 else {local_code}
    records = []
    rejected = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            rejected.append(("unknown", "MALFORMED_ROW"))
            continue
        try:
            trade_date = date.fromisoformat(str(item["Date"]))
        except (KeyError, ValueError):
            rejected.append(("unknown", "INVALID_TRADE_DATE"))
            continue
        if str(item.get("Code")) not in valid_codes:
            rejected.append((trade_date.isoformat(), "INSTRUMENT_MISMATCH"))
            continue
        if not start_date <= trade_date <= end_date:
            rejected.append((trade_date.isoformat(), "OUTSIDE_REQUESTED_RANGE"))
            continue
        records.append(JPDailyPriceRecord(
            provider="jquants", symbol=instrument.symbol, trade_date=trade_date, currency="JPY",
            open_price=item.get("O"), high_price=item.get("H"), low_price=item.get("L"),
            close_price=item.get("C"), adjusted_close=item.get("AdjC"), trade_volume=item.get("Vo"),
            source_url=url, raw_payload_hash=receipt.content_hash,
        ))
    result = adapt_daily_records(records, instrument=instrument, receipt=receipt)
    if payload.get("pagination_key"):
        rejected.append(("page", "PAGINATION_INCOMPLETE"))
    return DailyAdapterResult(receipt, result.bars, result.rejections + tuple(rejected))
