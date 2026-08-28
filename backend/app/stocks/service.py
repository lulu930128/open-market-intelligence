from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, SourceRegistry, StockMaster, StockProfile, utc_now
from app.market.daily_ohlcv_platform import read_taiwan_latest_daily_evidence
from app.parsers.twse_common import normalize_text
from app.stocks.instruments import (
    TAIWAN_INSTRUMENT_ETF,
    normalize_taiwan_instrument_type,
)
from app.stocks.schemas import StockMasterUpdate


class StockNotFoundError(Exception):
    pass


class StockProfileNotFoundError(Exception):
    pass


def _infer_market(source: SourceRegistry | None) -> str:
    if source is None:
        return "unknown"

    name = source.source_name.lower()
    source_type = source.source_type.lower()

    if "twse" in name or "twse" in source_type:
        return "TWSE"

    if "tpex" in name or "tpex" in source_type:
        return "TPEx"

    return "unknown"


def _infer_instrument_type(stock_id: str, stock_name: str | None) -> str:
    # First-pass heuristic. It can be refined later with official security master data.
    if stock_id.startswith("00"):
        return "ETF"

    if stock_id.isdigit() and len(stock_id) == 4:
        return "stock"

    if stock_name and "甈?" in stock_name:
        return "warrant"

    return "unknown"


def _upsert_stock_master_from_market_daily_row(
    db: Session,
    *,
    stock_id: str,
    stock_name: str | None,
    source_id: int | None,
    sources: dict[int, SourceRegistry] | None = None,
) -> StockMaster:
    stock_name = normalize_text(stock_name)
    source = sources.get(source_id) if sources and source_id is not None else None

    if source is None and source_id is not None:
        source = db.query(SourceRegistry).filter(SourceRegistry.id == source_id).first()

    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    inferred_market = _infer_market(source)
    inferred_type = _infer_instrument_type(stock_id, stock_name)

    if stock is None:
        stock = StockMaster(
            stock_id=stock_id,
            stock_name=stock_name,
            market=inferred_market,
            instrument_type=inferred_type,
            last_seen_at=utc_now(),
        )
        db.add(stock)
        db.flush()
        return stock

    stock.stock_name = stock_name or stock.stock_name
    stock.market = stock.market if stock.market != "unknown" else inferred_market
    existing_type = normalize_taiwan_instrument_type(
        stock.instrument_type,
        stock_id=stock.stock_id,
    )
    stock.instrument_type = (
        inferred_type if existing_type == "unknown" else stock.instrument_type
    )
    stock.last_seen_at = utc_now()
    stock.is_active = True
    db.flush()
    return stock


def ensure_stock_from_market_daily(db: Session, stock_id: str) -> StockMaster | None:
    row = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(MarketDailyPrice.trade_date.desc(), MarketDailyPrice.id.desc())
        .first()
    )

    if row is None:
        return None

    return _upsert_stock_master_from_market_daily_row(
        db=db,
        stock_id=row.stock_id,
        stock_name=row.stock_name,
        source_id=row.source_id,
    )


def _repair_stock_master_name(stock: StockMaster) -> bool:
    repaired_name = normalize_text(stock.stock_name)

    if repaired_name and repaired_name != stock.stock_name:
        stock.stock_name = repaired_name
        stock.updated_at = utc_now()
        return True

    return False


def sync_stocks_from_market_daily(db: Session) -> dict:
    rows = (
        db.query(
            MarketDailyPrice.stock_id,
            MarketDailyPrice.stock_name,
            MarketDailyPrice.source_id,
        )
        .distinct()
        .all()
    )

    source_ids = {row.source_id for row in rows}
    sources = {
        source.id: source
        for source in db.query(SourceRegistry).filter(SourceRegistry.id.in_(source_ids)).all()
    }

    created_count = 0
    updated_count = 0

    for row in rows:
        stock_id = row.stock_id
        stock_name = row.stock_name
        source = sources.get(row.source_id)

        existing = (
            db.query(StockMaster)
            .filter(StockMaster.stock_id == stock_id)
            .first()
        )

        if existing is None:
            stock = StockMaster(
                stock_id=stock_id,
                stock_name=stock_name,
                market=_infer_market(source),
                instrument_type=_infer_instrument_type(stock_id, stock_name),
                last_seen_at=utc_now(),
            )
            db.add(stock)
            created_count += 1
            continue

        existing.stock_name = stock_name or existing.stock_name
        existing.market = existing.market if existing.market != "unknown" else _infer_market(source)
        existing_type = normalize_taiwan_instrument_type(
            existing.instrument_type,
            stock_id=existing.stock_id,
        )
        existing.instrument_type = (
            _infer_instrument_type(stock_id, stock_name)
            if existing_type == "unknown"
            else existing.instrument_type
        )
        existing.last_seen_at = utc_now()
        existing.is_active = True
        updated_count += 1

    db.commit()

    return {
        "status": "success",
        "scanned_count": len(rows),
        "created_count": created_count,
        "updated_count": updated_count,
        "message": "Stock master synced from market daily data.",
    }


def list_stocks(
    db: Session,
    market: str | None = None,
    instrument_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[StockMaster]:
    query = db.query(StockMaster)

    if market is not None:
        query = query.filter(StockMaster.market == market)

    if instrument_type is not None:
        normalized_type = normalize_taiwan_instrument_type(instrument_type)
        query = query.filter(func.lower(StockMaster.instrument_type) == normalized_type)

    if is_active is not None:
        query = query.filter(StockMaster.is_active.is_(is_active))

    return (
        query.order_by(StockMaster.stock_id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def search_stocks(
    db: Session,
    keyword: str,
    limit: int = 50,
) -> list[StockMaster]:
    keyword = keyword.strip()
    pattern = f"%{keyword}%"
    is_etf_keyword = keyword.lower() in {"etf", "etfs"}

    filters = [
        StockMaster.stock_id.ilike(pattern),
        StockMaster.stock_name.ilike(pattern),
        StockMaster.industry.ilike(pattern),
        StockMaster.category.ilike(pattern),
        StockMaster.instrument_type.ilike(pattern),
    ]

    if is_etf_keyword:
        filters.append(func.lower(StockMaster.instrument_type) == TAIWAN_INSTRUMENT_ETF)

    results = (
        db.query(StockMaster)
        .filter(or_(*filters))
        .order_by(StockMaster.stock_id.asc())
        .limit(limit)
        .all()
    )
    repaired_existing = False

    for stock in results:
        repaired_existing = _repair_stock_master_name(stock) or repaired_existing

    if len(results) >= limit:
        if repaired_existing:
            db.commit()

        return results

    seen_stock_ids = {stock.stock_id for stock in results}
    market_filters = [
        MarketDailyPrice.stock_id.ilike(pattern),
        MarketDailyPrice.stock_name.ilike(pattern),
    ]

    if is_etf_keyword:
        market_filters.append(MarketDailyPrice.stock_id.like("00%"))

    market_rows = (
        db.query(
            MarketDailyPrice.stock_id,
            func.max(MarketDailyPrice.stock_name).label("stock_name"),
            func.max(MarketDailyPrice.source_id).label("source_id"),
        )
        .filter(or_(*market_filters))
        .group_by(MarketDailyPrice.stock_id)
        .order_by(MarketDailyPrice.stock_id.asc())
        .limit(limit)
        .all()
    )

    source_ids = {row.source_id for row in market_rows if row.source_id is not None}
    sources = {
        source.id: source
        for source in db.query(SourceRegistry).filter(SourceRegistry.id.in_(source_ids)).all()
    }
    created_from_daily = False

    for row in market_rows:
        if row.stock_id in seen_stock_ids:
            continue

        stock = _upsert_stock_master_from_market_daily_row(
            db=db,
            stock_id=row.stock_id,
            stock_name=row.stock_name,
            source_id=row.source_id,
            sources=sources,
        )
        results.append(stock)
        seen_stock_ids.add(stock.stock_id)
        created_from_daily = True

        if len(results) >= limit:
            break

    if repaired_existing or created_from_daily:
        db.commit()

    return sorted(results, key=lambda stock: stock.stock_id)[:limit]


def get_stock(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        stock = ensure_stock_from_market_daily(db=db, stock_id=stock_id)

        if stock is not None:
            db.commit()
            db.refresh(stock)
    elif _repair_stock_master_name(stock):
        db.commit()
        db.refresh(stock)

    if stock is None:
        raise StockNotFoundError(f"Stock id='{stock_id}' not found.")

    return stock


def update_stock(
    db: Session,
    stock_id: str,
    payload: StockMasterUpdate,
) -> StockMaster:
    stock = get_stock(db, stock_id)

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(stock, key, value)

    db.commit()
    db.refresh(stock)

    return stock


def list_stock_profiles(
    db: Session,
    market: str | None = None,
    industry: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[StockProfile]:
    query = db.query(StockProfile)

    if market is not None:
        query = query.filter(StockProfile.market == market)

    if industry is not None:
        query = query.filter(StockProfile.industry == industry)

    return (
        query.order_by(StockProfile.stock_id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_stock_profile(db: Session, stock_id: str) -> StockProfile:
    profile = db.query(StockProfile).filter(StockProfile.stock_id == stock_id).first()

    if profile is None:
        raise StockProfileNotFoundError(f"Stock profile for stock_id='{stock_id}' not found.")

    return profile


def get_latest_stock_market_cap(db: Session, stock_id: str) -> dict:
    profile = get_stock_profile(db=db, stock_id=stock_id)
    try:
        latest_price = read_taiwan_latest_daily_evidence(db, stock_id).daily
    except ValueError:
        # A profile can temporarily outlive or precede its active StockMaster
        # identity.  The GET remains read-only and fails closed to an unknown
        # market price rather than bootstrapping identity from raw daily rows.
        latest_price = None
    close_price = (
        float(latest_price.close_price)
        if latest_price is not None and latest_price.close_price is not None
        else None
    )
    issued_shares = profile.issued_shares

    market_cap: float | None = None

    if close_price is not None and issued_shares is not None:
        market_cap = close_price * issued_shares

    return {
        "stock_id": profile.stock_id,
        "stock_name": profile.short_name or profile.company_name,
        "trade_date": latest_price.trade_date if latest_price is not None else None,
        "close_price": close_price,
        "issued_shares": issued_shares,
        "market_cap": market_cap,
        "profile_report_date": profile.report_date,
    }
