from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, SourceRegistry, StockMaster, StockProfile, utc_now
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
        existing.instrument_type = (
            existing.instrument_type
            if existing.instrument_type != "unknown"
            else _infer_instrument_type(stock_id, stock_name)
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
        query = query.filter(StockMaster.instrument_type == instrument_type)

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
    pattern = f"%{keyword}%"

    return (
        db.query(StockMaster)
        .filter(
            or_(
                StockMaster.stock_id.ilike(pattern),
                StockMaster.stock_name.ilike(pattern),
                StockMaster.industry.ilike(pattern),
                StockMaster.category.ilike(pattern),
            )
        )
        .order_by(StockMaster.stock_id.asc())
        .limit(limit)
        .all()
    )


def get_stock(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

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

    latest_price = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.close_price.isnot(None))
        .order_by(MarketDailyPrice.trade_date.desc())
        .first()
    )

    close_price = latest_price.close_price if latest_price is not None else None
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
