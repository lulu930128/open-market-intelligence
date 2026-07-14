from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import USStockMaster, utc_now
from app.us_market.errors import USStockNotFoundError
from app.us_market.sources import USSymbolRecord, normalize_us_symbol

def _apply_symbol_record(stock: USStockMaster, record: USSymbolRecord) -> None:
    stock.security_name = record.security_name or stock.security_name
    stock.exchange = record.exchange or stock.exchange
    stock.asset_type = record.asset_type
    stock.listing_source = record.listing_source
    stock.market_category = record.market_category
    stock.financial_status = record.financial_status
    stock.cqs_symbol = record.cqs_symbol
    stock.nasdaq_symbol = record.nasdaq_symbol
    stock.cik = record.cik or stock.cik
    stock.sec_company_name = record.sec_company_name or stock.sec_company_name
    stock.is_etf = record.is_etf
    stock.is_test_issue = record.is_test_issue
    stock.round_lot_size = record.round_lot_size
    stock.is_active = True
    stock.last_seen_at = utc_now()
    stock.updated_at = utc_now()


def upsert_us_symbol_records(
    db: Session,
    records: list[USSymbolRecord],
    *,
    deactivate_missing: bool = False,
) -> dict:
    scanned_count = len(records)
    created_count = 0
    updated_count = 0
    now = utc_now()
    seen_symbols = {record.symbol for record in records}

    existing_by_symbol = {
        stock.symbol: stock
        for stock in db.query(USStockMaster).filter(USStockMaster.symbol.in_(seen_symbols)).all()
    } if seen_symbols else {}

    for record in records:
        existing = existing_by_symbol.get(record.symbol)

        if existing is None:
            stock = USStockMaster(
                symbol=record.symbol,
                security_name=record.security_name,
                exchange=record.exchange,
                asset_type=record.asset_type,
                listing_source=record.listing_source,
                market_category=record.market_category,
                financial_status=record.financial_status,
                cqs_symbol=record.cqs_symbol,
                nasdaq_symbol=record.nasdaq_symbol,
                cik=record.cik,
                sec_company_name=record.sec_company_name,
                is_etf=record.is_etf,
                is_test_issue=record.is_test_issue,
                round_lot_size=record.round_lot_size,
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(stock)
            created_count += 1
            continue

        _apply_symbol_record(existing, record)
        updated_count += 1

    deactivated_count = 0
    if deactivate_missing and seen_symbols:
        missing_rows = (
            db.query(USStockMaster)
            .filter(USStockMaster.is_active.is_(True))
            .filter(~USStockMaster.symbol.in_(seen_symbols))
            .all()
        )
        for stock in missing_rows:
            stock.is_active = False
            stock.updated_at = utc_now()
            deactivated_count += 1

    db.commit()

    return {
        "status": "success",
        "scanned_count": scanned_count,
        "created_count": created_count,
        "updated_count": updated_count,
        "deactivated_count": deactivated_count,
        "message": "US stock master synced from Nasdaq Trader symbol directories.",
    }


def _apply_sec_company_data(stock: USStockMaster, item: dict[str, str | None]) -> bool:
    changed = False
    cik = item.get("cik")
    sec_company_name = item.get("sec_company_name")
    sec_exchange = item.get("sec_exchange")

    if cik and stock.cik != cik:
        stock.cik = cik
        changed = True
    if sec_company_name and stock.sec_company_name != sec_company_name:
        stock.sec_company_name = sec_company_name
        changed = True
    if sec_exchange and not stock.exchange:
        stock.exchange = sec_exchange
        changed = True

    if changed:
        stock.updated_at = utc_now()

    return changed


def list_us_stocks(
    db: Session,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[USStockMaster]:
    query = db.query(USStockMaster)

    if exchange is not None:
        query = query.filter(USStockMaster.exchange == exchange)

    if asset_type is not None:
        query = query.filter(USStockMaster.asset_type == asset_type)

    if is_active is not None:
        query = query.filter(USStockMaster.is_active.is_(is_active))

    return (
        query.order_by(USStockMaster.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_us_stock(db: Session, *, symbol: str) -> USStockMaster:
    normalized_symbol = normalize_us_symbol(symbol)
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )

    if stock is None:
        raise USStockNotFoundError(f"US symbol='{normalized_symbol}' not found.")

    return stock
