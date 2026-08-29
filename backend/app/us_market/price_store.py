from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice, utc_now
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, us_session_close_time
from app.us_market.chart_projection import should_skip_daily_price_update as _should_skip_us_daily_price_update
from app.us_market.sources import USDailyPriceRecord, normalize_us_symbol
from app.us_market.symbols import us_symbol_storage_candidates

def upsert_us_daily_price_records(
    db: Session,
    records: list[USDailyPriceRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    def lineage(record: USDailyPriceRecord, normalized_symbol: str) -> dict:
        source_name = f"legacy_compat.{record.provider}.daily"
        source = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == source_name)
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name=source_name,
                source_type="compatibility_adapter",
                category="market_data",
                endpoint_url=record.source_url,
                enabled=True,
            )
            db.add(source)
            db.flush()
        fetched_at = utc_now()
        content_hash = str(record.raw_payload_hash or "").strip() or (
            f"legacy:{record.provider}:{normalized_symbol}:{record.trade_date.isoformat()}"
        )
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=fetched_at,
            url=record.source_url,
            method="GET",
            content_hash=content_hash,
            parser_version="us_daily_legacy_compat.v1",
        )
        db.add(raw)
        db.flush()
        is_index = normalized_symbol.startswith("^")
        return {
            "fetched_at": fetched_at,
            "source_id": source.id,
            "raw_result_id": raw.id,
            "authority": "vendor",
            "raw_contract_version": f"{record.provider}.legacy_compat.v1",
            "event_at": datetime.combine(
                record.trade_date,
                us_session_close_time(record.trade_date),
                tzinfo=US_MARKET_TIMEZONE,
            ),
            "finalization": "final",
            "price_basis": "raw",
            "volume_unit": "shares" if record.trade_volume is not None else None,
            "volume_status": (
                "observed"
                if record.trade_volume is not None
                else "not_applicable"
                if is_index
                else "missing"
            ),
            "raw_payload_hash": content_hash,
        }

    for record in records:
        normalized_symbol = normalize_us_symbol(record.symbol)
        existing = (
            db.query(USDailyPrice)
            .filter(USDailyPrice.provider == record.provider)
            .filter(USDailyPrice.symbol == normalized_symbol)
            .filter(USDailyPrice.trade_date == record.trade_date)
            .first()
        )
        if existing is None:
            lineage_fields = lineage(record, normalized_symbol)
            db.add(
                USDailyPrice(
                    provider=record.provider,
                    symbol=normalized_symbol,
                    trade_date=record.trade_date,
                    open_price=record.open_price,
                    high_price=record.high_price,
                    low_price=record.low_price,
                    close_price=record.close_price,
                    adjusted_close=record.adjusted_close,
                    trade_volume=record.trade_volume,
                    dividend_amount=record.dividend_amount,
                    split_coefficient=record.split_coefficient,
                    source_url=record.source_url,
                    **lineage_fields,
                )
            )
            inserted_count += 1
            continue

        if (
            existing.source_id is not None
            and existing.raw_result_id is not None
            and _should_skip_us_daily_price_update(existing=existing, record=record)
        ):
            continue

        lineage_fields = lineage(record, normalized_symbol)

        existing.open_price = record.open_price
        existing.high_price = record.high_price
        existing.low_price = record.low_price
        existing.close_price = record.close_price
        existing.adjusted_close = record.adjusted_close
        existing.trade_volume = record.trade_volume
        existing.dividend_amount = record.dividend_amount
        existing.split_coefficient = record.split_coefficient
        existing.source_url = record.source_url
        for field, value in lineage_fields.items():
            setattr(existing, field, value)
        existing.updated_at = utc_now()
        updated_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def _us_daily_price_sample(row: USDailyPrice) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "symbol": row.symbol,
        "trade_date": row.trade_date,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "close_price": row.close_price,
        "trade_volume": row.trade_volume,
        "source_url": row.source_url,
    }


def list_us_daily_prices(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USDailyPrice]:
    normalized_symbol = normalize_us_symbol(symbol)
    symbol_candidates = us_symbol_storage_candidates(normalized_symbol)
    query = db.query(USDailyPrice).filter(USDailyPrice.symbol.in_(symbol_candidates))

    if provider is not None:
        query = query.filter(USDailyPrice.provider == provider)

    if from_date is not None:
        query = query.filter(USDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(USDailyPrice.trade_date <= to_date)

    rows = query.order_by(USDailyPrice.trade_date.desc()).all()
    canonical_rows: dict[tuple[str, date], USDailyPrice] = {}
    for row in rows:
        key = (row.provider, row.trade_date)
        current = canonical_rows.get(key)
        if current is None or (row.symbol == normalized_symbol and current.symbol != normalized_symbol):
            canonical_rows[key] = row

    ordered_rows = sorted(
        canonical_rows.values(),
        key=lambda row: row.trade_date,
        reverse=True,
    )
    return ordered_rows[offset : offset + limit]


def list_us_ohlc_source_rows(
    db: Session,
    *,
    symbol: str,
    from_date: date,
    to_date: date,
) -> list[USDailyPrice]:
    rows = list_us_daily_prices(
        db=db,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        limit=5000,
        offset=0,
    )
    return sorted(rows, key=lambda row: row.trade_date)


def list_us_ohlc_source_rows_for_symbols(
    db: Session,
    *,
    symbols: list[str],
    from_date: date,
    to_date: date,
) -> dict[str, list[USDailyPrice]]:
    """Load bounded provider rows for multiple canonical symbols in one query."""

    normalized_symbols = list(
        dict.fromkeys(
            normalized
            for symbol in symbols
            if (normalized := normalize_us_symbol(symbol))
        )
    )
    if len(normalized_symbols) > 500:
        raise ValueError("symbols must contain at most 500 canonical symbols")
    if not normalized_symbols:
        return {}
    candidate_owner: dict[str, str] = {}
    for normalized_symbol in normalized_symbols:
        for candidate in us_symbol_storage_candidates(normalized_symbol):
            candidate_owner.setdefault(candidate, normalized_symbol)
    rows = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol.in_(tuple(candidate_owner)))
        .filter(USDailyPrice.trade_date >= from_date)
        .filter(USDailyPrice.trade_date <= to_date)
        .order_by(USDailyPrice.trade_date.asc())
        .all()
    )
    canonical_rows: dict[str, dict[tuple[str, date], USDailyPrice]] = {
        symbol: {} for symbol in normalized_symbols
    }
    for row in rows:
        owner = candidate_owner.get(row.symbol)
        if owner is None:
            continue
        key = (row.provider, row.trade_date)
        current = canonical_rows[owner].get(key)
        if current is None or (row.symbol == owner and current.symbol != owner):
            canonical_rows[owner][key] = row
    return {
        symbol: sorted(items.values(), key=lambda row: row.trade_date)
        for symbol, items in canonical_rows.items()
    }


# Compatibility alias for older internal callers. New code uses the public,
# cache-only read name so research modules do not depend on private helpers.
_list_us_ohlc_source_rows = list_us_ohlc_source_rows
