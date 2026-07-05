from __future__ import annotations

import json
import time
from threading import RLock
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, load_only

from app.db.models import ResourceOhlcvBar, ResourceQuoteSnapshot, utc_now
from app.observability.provider_health import record_provider_event
from app.resource_market.contract import (
    YAHOO_CHART_PROVIDER,
    list_resource_instruments,
    normalize_resource_symbol,
    resource_provider_contract,
)
from app.resource_market.sources import (
    ResourceOhlcvRecord,
    ResourceQuoteRecord,
    fetch_yahoo_chart_payload_for_interval,
    normalize_resource_interval,
    parse_yahoo_ohlcv_records,
    parse_yahoo_quote_record,
)
from app.settings.market_data_subscription import market_data_subscription_skip_reason


RESOURCE_DB_LOCK_RETRY_DELAYS_SECONDS = (0.15, 0.35, 0.75)
_RESOURCE_MARKET_WRITE_LOCK = RLock()


RESOURCE_QUOTE_READ_COLUMNS = (
    ResourceQuoteSnapshot.id,
    ResourceQuoteSnapshot.provider,
    ResourceQuoteSnapshot.exchange,
    ResourceQuoteSnapshot.symbol,
    ResourceQuoteSnapshot.provider_symbol,
    ResourceQuoteSnapshot.name,
    ResourceQuoteSnapshot.root_folder,
    ResourceQuoteSnapshot.group,
    ResourceQuoteSnapshot.asset_class,
    ResourceQuoteSnapshot.base_asset,
    ResourceQuoteSnapshot.quote_asset,
    ResourceQuoteSnapshot.instrument_type,
    ResourceQuoteSnapshot.contract_key,
    ResourceQuoteSnapshot.contract_month,
    ResourceQuoteSnapshot.last_price,
    ResourceQuoteSnapshot.bid_price,
    ResourceQuoteSnapshot.ask_price,
    ResourceQuoteSnapshot.open_price,
    ResourceQuoteSnapshot.high_price,
    ResourceQuoteSnapshot.low_price,
    ResourceQuoteSnapshot.previous_close,
    ResourceQuoteSnapshot.price_change,
    ResourceQuoteSnapshot.price_change_pct,
    ResourceQuoteSnapshot.volume,
    ResourceQuoteSnapshot.open_interest,
    ResourceQuoteSnapshot.event_time,
    ResourceQuoteSnapshot.source_url,
    ResourceQuoteSnapshot.fetched_at,
    ResourceQuoteSnapshot.created_at,
    ResourceQuoteSnapshot.updated_at,
)

RESOURCE_OHLCV_READ_COLUMNS = (
    ResourceOhlcvBar.id,
    ResourceOhlcvBar.provider,
    ResourceOhlcvBar.exchange,
    ResourceOhlcvBar.symbol,
    ResourceOhlcvBar.provider_symbol,
    ResourceOhlcvBar.name,
    ResourceOhlcvBar.root_folder,
    ResourceOhlcvBar.group,
    ResourceOhlcvBar.asset_class,
    ResourceOhlcvBar.base_asset,
    ResourceOhlcvBar.quote_asset,
    ResourceOhlcvBar.instrument_type,
    ResourceOhlcvBar.contract_key,
    ResourceOhlcvBar.contract_month,
    ResourceOhlcvBar.interval,
    ResourceOhlcvBar.bar_time,
    ResourceOhlcvBar.open_price,
    ResourceOhlcvBar.high_price,
    ResourceOhlcvBar.low_price,
    ResourceOhlcvBar.close_price,
    ResourceOhlcvBar.volume,
    ResourceOhlcvBar.open_interest,
    ResourceOhlcvBar.source_url,
    ResourceOhlcvBar.fetched_at,
    ResourceOhlcvBar.created_at,
    ResourceOhlcvBar.updated_at,
)


def get_resource_provider_contract() -> dict[str, Any]:
    return resource_provider_contract()


def list_supported_resource_instruments(
    *,
    root_folder: str | None = None,
    group: str | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    return [
        instrument.to_dict()
        for instrument in list_resource_instruments(
            root_folder=root_folder,
            group=group,
            symbol=symbol,
        )
    ]


def _split_symbols(symbols: str | None) -> list[str] | None:
    if not symbols:
        return None
    normalized: list[str] = []
    for symbol in symbols.split(","):
        item = normalize_resource_symbol(symbol)
        if item and item not in normalized:
            normalized.append(item)
    return normalized or None


def _supported_instrument_for_symbol(symbol: str | None):
    if not symbol:
        return None
    matches = list_resource_instruments(root_folder="commodity", symbol=symbol)
    return matches[0] if len(matches) == 1 else None


def _apply_supported_instrument_scope(query, model, symbol_values: list[str] | None):
    if not symbol_values:
        return query

    query = query.filter(model.provider == YAHOO_CHART_PROVIDER)
    if len(symbol_values) == 1:
        instrument = _supported_instrument_for_symbol(symbol_values[0])
        if instrument is not None:
            query = query.filter(model.instrument_type == instrument.instrument_type)
            query = query.filter(model.contract_key == instrument.contract_type)
    return query


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _short_status_message(value: str | None, *, max_length: int = 260) -> str | None:
    if not value:
        return None
    normalized = " ".join(str(value).split())
    if "database is locked" in normalized.lower():
        return "database is locked"
    return normalized if len(normalized) <= max_length else f"{normalized[:max_length - 1]}…"


def _is_sqlite_locked_error(error: OperationalError) -> bool:
    return "database is locked" in str(error).lower()


def _write_with_retry(db: Session, action):
    last_error: OperationalError | None = None
    for attempt, delay_seconds in enumerate((*RESOURCE_DB_LOCK_RETRY_DELAYS_SECONDS, 0.0)):
        try:
            with _RESOURCE_MARKET_WRITE_LOCK:
                result = action()
                db.commit()
                return result
        except OperationalError as exc:
            db.rollback()
            if not _is_sqlite_locked_error(exc) or attempt >= len(RESOURCE_DB_LOCK_RETRY_DELAYS_SECONDS):
                raise
            last_error = exc
            time.sleep(delay_seconds)

    if last_error is not None:
        raise last_error
    return None


def resource_quote_to_public_dict(row: ResourceQuoteSnapshot) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in RESOURCE_QUOTE_READ_COLUMNS}


def resource_ohlcv_bar_to_public_dict(row: ResourceOhlcvBar) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in RESOURCE_OHLCV_READ_COLUMNS}


def _refresh_status(
    *,
    requested_count: int,
    refreshed_count: int,
    error_count: int,
    skipped_count: int,
) -> str:
    if error_count > 0 and refreshed_count > 0:
        return "partial_success"
    if error_count > 0:
        return "error"
    if refreshed_count > 0:
        return "success"
    if skipped_count > 0 or requested_count == 0:
        return "empty"
    return "empty"


def _record_event(
    db: Session,
    *,
    resource: str,
    target: str,
    status: str,
    message: str | None = None,
    error_message: str | None = None,
    source_url: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        _write_with_retry(
            db,
            lambda: record_provider_event(
                db,
                market="resource",
                provider=YAHOO_CHART_PROVIDER,
                resource=resource,
                target=target,
                status=status,
                event_type="refresh",
                source_url=source_url,
                message=_short_status_message(message),
                error_message=_short_status_message(error_message),
                detail=detail,
                commit=False,
            ),
        )
    except Exception:
        db.rollback()


def _matching_resource_instruments(symbols: str | None) -> list:
    symbol_values = _split_symbols(symbols)
    if not symbol_values:
        return list_resource_instruments(root_folder="commodity")

    instruments = []
    for symbol in symbol_values:
        matches = list_resource_instruments(root_folder="commodity", symbol=symbol)
        instruments.extend(matches)
    return instruments


def _upsert_resource_quote(
    db: Session,
    record: ResourceQuoteRecord,
) -> ResourceQuoteSnapshot:
    row = (
        db.query(ResourceQuoteSnapshot)
        .filter(ResourceQuoteSnapshot.provider == record.provider)
        .filter(ResourceQuoteSnapshot.symbol == record.symbol)
        .filter(ResourceQuoteSnapshot.instrument_type == record.instrument_type)
        .filter(ResourceQuoteSnapshot.contract_key == record.contract_key)
        .one_or_none()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "name": record.name,
        "root_folder": record.root_folder,
        "group": record.group,
        "asset_class": record.asset_class,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "last_price": record.last_price,
        "bid_price": record.bid_price,
        "ask_price": record.ask_price,
        "open_price": record.open_price,
        "high_price": record.high_price,
        "low_price": record.low_price,
        "previous_close": record.previous_close,
        "price_change": record.price_change,
        "price_change_pct": record.price_change_pct,
        "volume": record.volume,
        "open_interest": record.open_interest,
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": _json_dumps(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = ResourceQuoteSnapshot(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            contract_key=record.contract_key,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _resource_ohlcv_values(record: ResourceOhlcvRecord) -> dict[str, Any]:
    return {
        "provider": record.provider,
        "exchange": record.exchange,
        "symbol": record.symbol,
        "provider_symbol": record.provider_symbol,
        "name": record.name,
        "root_folder": record.root_folder,
        "group": record.group,
        "asset_class": record.asset_class,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "instrument_type": record.instrument_type,
        "contract_key": record.contract_key,
        "interval": record.interval,
        "bar_time": record.bar_time,
        "open_price": record.open_price,
        "high_price": record.high_price,
        "low_price": record.low_price,
        "close_price": record.close_price,
        "volume": record.volume,
        "open_interest": record.open_interest,
        "source_url": record.source_url,
        "raw_payload_json": _json_dumps(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }


def _upsert_resource_ohlcv(
    db: Session,
    record: ResourceOhlcvRecord,
) -> ResourceOhlcvBar:
    row = (
        db.query(ResourceOhlcvBar)
        .filter(ResourceOhlcvBar.provider == record.provider)
        .filter(ResourceOhlcvBar.symbol == record.symbol)
        .filter(ResourceOhlcvBar.instrument_type == record.instrument_type)
        .filter(ResourceOhlcvBar.contract_key == record.contract_key)
        .filter(ResourceOhlcvBar.interval == record.interval)
        .filter(ResourceOhlcvBar.bar_time == record.bar_time)
        .one_or_none()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "name": record.name,
        "root_folder": record.root_folder,
        "group": record.group,
        "asset_class": record.asset_class,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "open_price": record.open_price,
        "high_price": record.high_price,
        "low_price": record.low_price,
        "close_price": record.close_price,
        "volume": record.volume,
        "open_interest": record.open_interest,
        "source_url": record.source_url,
        "raw_payload_json": _json_dumps(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = ResourceOhlcvBar(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            contract_key=record.contract_key,
            interval=record.interval,
            bar_time=record.bar_time,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _upsert_resource_ohlcv_many(
    db: Session,
    records: list[ResourceOhlcvRecord],
) -> None:
    if not records:
        return

    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        for record in records:
            _upsert_resource_ohlcv(db, record)
        return

    insert_values = [_resource_ohlcv_values(record) for record in records]
    stmt = sqlite_insert(ResourceOhlcvBar).values(insert_values)
    update_columns = [
        "exchange",
        "provider_symbol",
        "name",
        "root_folder",
        "group",
        "asset_class",
        "base_asset",
        "quote_asset",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "open_interest",
        "source_url",
        "raw_payload_json",
        "fetched_at",
        "updated_at",
    ]
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "provider",
            "symbol",
            "instrument_type",
            "contract_key",
            "interval",
            "bar_time",
        ],
        set_={column: getattr(stmt.excluded, column) for column in update_columns},
    )
    db.execute(stmt)


def list_latest_resource_quotes(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    limit: int = 100,
) -> list[ResourceQuoteSnapshot]:
    query = db.query(ResourceQuoteSnapshot).options(load_only(*RESOURCE_QUOTE_READ_COLUMNS))
    if provider:
        query = query.filter(ResourceQuoteSnapshot.provider == provider.strip().lower())
    symbol_values = _split_symbols(symbols)
    if symbol_values:
        query = query.filter(ResourceQuoteSnapshot.symbol.in_(symbol_values))
        if not provider:
            query = _apply_supported_instrument_scope(query, ResourceQuoteSnapshot, symbol_values)
    if group:
        query = query.filter(ResourceQuoteSnapshot.group == group.strip().lower())
    return (
        query.order_by(ResourceQuoteSnapshot.fetched_at.desc(), ResourceQuoteSnapshot.symbol.asc())
        .limit(limit)
        .all()
    )


def list_resource_ohlcv_bars(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    interval: str | None = None,
    limit: int = 500,
) -> list[ResourceOhlcvBar]:
    query = db.query(ResourceOhlcvBar).options(load_only(*RESOURCE_OHLCV_READ_COLUMNS))
    if provider:
        query = query.filter(ResourceOhlcvBar.provider == provider.strip().lower())
    symbol_values = _split_symbols(symbols)
    if symbol_values:
        query = query.filter(ResourceOhlcvBar.symbol.in_(symbol_values))
        if not provider:
            query = _apply_supported_instrument_scope(query, ResourceOhlcvBar, symbol_values)
    if group:
        query = query.filter(ResourceOhlcvBar.group == group.strip().lower())
    if interval:
        query = query.filter(ResourceOhlcvBar.interval == interval.strip())
    return (
        query.order_by(ResourceOhlcvBar.bar_time.desc(), ResourceOhlcvBar.symbol.asc())
        .limit(limit)
        .all()
    )


def refresh_resource_quotes(
    db: Session,
    *,
    symbols: str | None = None,
) -> dict[str, Any]:
    instruments = _matching_resource_instruments(symbols)
    requested_count = len(instruments)
    refreshed_count = 0
    skipped_count = 0
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    events: list[dict[str, Any]] = []

    for instrument in instruments:
        skip_reason = market_data_subscription_skip_reason(
            db,
            key=instrument.key,
            resource="quote",
        )
        if skip_reason:
            skipped_count += 1
            warnings.append(f"{instrument.symbol}: {skip_reason}")
            continue
        if instrument.provider != YAHOO_CHART_PROVIDER:
            skipped_count += 1
            warnings.append(f"{instrument.symbol}: unsupported provider {instrument.provider}")
            continue

        try:
            payload, source_url = fetch_yahoo_chart_payload_for_interval(
                instrument=instrument,
                interval="1m",
            )
            record = parse_yahoo_quote_record(
                payload,
                instrument=instrument,
                source_url=source_url,
            )
            _write_with_retry(db, lambda record=record: _upsert_resource_quote(db, record))
            refreshed_count += 1
            events.append(
                {
                    "resource": "quote",
                    "target": instrument.symbol,
                    "status": "success",
                    "message": "Resource quote refreshed from Yahoo chart.",
                    "source_url": source_url,
                    "detail": {
                        "symbol": instrument.symbol,
                        "provider_symbol": instrument.provider_symbol,
                    },
                }
            )
        except Exception as exc:  # network/API failures must stay per-symbol.
            error_message = _short_status_message(str(exc)) or "Resource quote refresh failed."
            db.rollback()
            errors.append({"symbol": instrument.symbol, "message": error_message})
            events.append(
                {
                    "resource": "quote",
                    "target": instrument.symbol,
                    "status": "error",
                    "error_message": error_message,
                    "detail": {
                        "symbol": instrument.symbol,
                        "provider_symbol": instrument.provider_symbol,
                    },
                }
            )

    for event in events:
        _record_event(db, **event)
    error_count = len(errors)
    return {
        "status": _refresh_status(
            requested_count=requested_count,
            refreshed_count=refreshed_count,
            error_count=error_count,
            skipped_count=skipped_count,
        ),
        "provider": YAHOO_CHART_PROVIDER,
        "resource": "quote",
        "requested_count": requested_count,
        "refreshed_count": refreshed_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "warnings": warnings,
        "errors": errors,
        "message": "Resource quotes refreshed from Yahoo chart.",
    }


def refresh_resource_ohlcv(
    db: Session,
    *,
    symbols: str | None = None,
    interval: str = "15m",
    limit: int = 120,
) -> dict[str, Any]:
    normalized_interval = normalize_resource_interval(interval)
    instruments = _matching_resource_instruments(symbols)
    requested_count = len(instruments)
    refreshed_count = 0
    skipped_count = 0
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    events: list[dict[str, Any]] = []

    for instrument in instruments:
        skip_reason = market_data_subscription_skip_reason(
            db,
            key=instrument.key,
            resource="ohlcv",
        )
        if skip_reason:
            skipped_count += 1
            warnings.append(f"{instrument.symbol}: {skip_reason}")
            continue
        if instrument.provider != YAHOO_CHART_PROVIDER:
            skipped_count += 1
            warnings.append(f"{instrument.symbol}: unsupported provider {instrument.provider}")
            continue

        try:
            payload, source_url = fetch_yahoo_chart_payload_for_interval(
                instrument=instrument,
                interval=normalized_interval,
            )
            records = parse_yahoo_ohlcv_records(
                payload,
                instrument=instrument,
                interval=normalized_interval,
                source_url=source_url,
                limit=limit,
            )
            _write_with_retry(db, lambda records=records: _upsert_resource_ohlcv_many(db, records))
            refreshed_count += len(records)
            events.append(
                {
                    "resource": "ohlcv",
                    "target": f"{instrument.symbol}:{normalized_interval}",
                    "status": "success" if records else "empty",
                    "message": "Resource OHLCV refreshed from Yahoo chart.",
                    "source_url": source_url,
                    "detail": {
                        "symbol": instrument.symbol,
                        "provider_symbol": instrument.provider_symbol,
                        "interval": normalized_interval,
                        "row_count": len(records),
                    },
                }
            )
        except Exception as exc:  # network/API failures must stay per-symbol.
            error_message = _short_status_message(str(exc)) or "Resource OHLCV refresh failed."
            db.rollback()
            errors.append({"symbol": instrument.symbol, "message": error_message})
            events.append(
                {
                    "resource": "ohlcv",
                    "target": f"{instrument.symbol}:{normalized_interval}",
                    "status": "error",
                    "error_message": error_message,
                    "detail": {
                        "symbol": instrument.symbol,
                        "provider_symbol": instrument.provider_symbol,
                        "interval": normalized_interval,
                    },
                }
            )

    for event in events:
        _record_event(db, **event)
    error_count = len(errors)
    return {
        "status": _refresh_status(
            requested_count=requested_count,
            refreshed_count=refreshed_count,
            error_count=error_count,
            skipped_count=skipped_count,
        ),
        "provider": YAHOO_CHART_PROVIDER,
        "resource": "ohlcv",
        "requested_count": requested_count,
        "refreshed_count": refreshed_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "warnings": warnings,
        "errors": errors,
        "interval": normalized_interval,
        "message": "Resource OHLCV refreshed from Yahoo chart.",
    }


def refresh_resource_market_snapshot(
    db: Session,
    *,
    symbols: str | None = None,
    intervals: str | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    interval_values = [
        normalize_resource_interval(value)
        for value in (intervals or "1m,15m").split(",")
        if value.strip()
    ]
    if not interval_values:
        interval_values = ["15m"]

    results = [refresh_resource_quotes(db, symbols=symbols)]
    for interval in dict.fromkeys(interval_values):
        results.append(
            refresh_resource_ohlcv(
                db,
                symbols=symbols,
                interval=interval,
                limit=limit,
            )
        )

    requested_count = sum(int(result["requested_count"]) for result in results)
    refreshed_count = sum(int(result["refreshed_count"]) for result in results)
    error_count = sum(int(result["error_count"]) for result in results)
    skipped_count = sum(int(result["skipped_count"]) for result in results)
    return {
        "status": _refresh_status(
            requested_count=requested_count,
            refreshed_count=refreshed_count,
            error_count=error_count,
            skipped_count=skipped_count,
        ),
        "provider": YAHOO_CHART_PROVIDER,
        "resource": "snapshot",
        "requested_count": requested_count,
        "refreshed_count": refreshed_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "warnings": [
            warning
            for result in results
            for warning in result.get("warnings", [])
        ],
        "errors": [
            error
            for result in results
            for error in result.get("errors", [])
        ],
        "results": results,
        "message": "Resource market snapshot refreshed from Yahoo chart.",
    }
