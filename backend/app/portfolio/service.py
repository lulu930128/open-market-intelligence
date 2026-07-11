from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JPStockMaster, KRStockMaster, PortfolioHolding, StockMaster, USStockMaster
from app.jp_market.sources import normalize_jp_symbol
from app.kr_market.sources import normalize_kr_symbol
from app.portfolio.schemas import PortfolioHoldingCreate, PortfolioHoldingUpdate
from app.us_market.sources import normalize_us_symbol


SUPPORTED_MARKETS = {"tw", "us", "jp", "kr"}
DEFAULT_CURRENCIES = {
    "tw": "TWD",
    "us": "USD",
    "jp": "JPY",
    "kr": "KRW",
}
SCOPE_TO_MARKET = {
    "stock": "tw",
    "us_stock": "us",
    "jp_stock": "jp",
    "kr_stock": "kr",
}


class PortfolioError(ValueError):
    pass


class PortfolioHoldingNotFoundError(PortfolioError):
    pass


class PortfolioSymbolNotFoundError(PortfolioError):
    pass


class PortfolioDuplicateHoldingError(PortfolioError):
    pass


def normalize_market(value: str) -> str:
    market = (value or "").strip().lower()
    if market not in SUPPORTED_MARKETS:
        raise PortfolioError(f"Unsupported portfolio market: {value}")
    return market


def normalize_symbol(market: str, symbol: str) -> str:
    cleaned = (symbol or "").strip()
    if market == "tw":
        return cleaned.upper()
    if market == "us":
        return normalize_us_symbol(cleaned)
    if market == "jp":
        return normalize_jp_symbol(cleaned)
    if market == "kr":
        return normalize_kr_symbol(cleaned)
    raise PortfolioError(f"Unsupported portfolio market: {market}")


def _symbol_master_record(db: Session, market: str, symbol: str) -> tuple[bool, str | None]:
    if market == "tw":
        stock = db.query(StockMaster).filter(StockMaster.stock_id == symbol).first()
        if stock is None:
            return False, None
        return True, stock.stock_name

    if market == "us":
        stock = db.query(USStockMaster).filter(USStockMaster.symbol == symbol).first()
        if stock is None:
            return False, None
        return True, stock.security_name

    if market == "jp":
        stock = db.query(JPStockMaster).filter(JPStockMaster.symbol == symbol).first()
        if stock is None:
            return False, None
        return True, stock.security_name

    if market == "kr":
        stock = db.query(KRStockMaster).filter(KRStockMaster.symbol == symbol).first()
        if stock is None:
            return False, None
        return True, stock.security_name or stock.security_name_kr

    return False, None


def ensure_symbol_exists(db: Session, market: str, symbol: str) -> str | None:
    exists, name = _symbol_master_record(db, market, symbol)
    if not exists:
        raise PortfolioSymbolNotFoundError(
            f"Symbol '{symbol}' was not found in {market} stock master."
        )
    return name


def average_cost(holding: PortfolioHolding) -> float | None:
    if holding.quantity <= 0:
        return None
    return holding.cost_amount / holding.quantity


def position_context_for_holding(holding: PortfolioHolding) -> dict[str, Any]:
    avg_cost = average_cost(holding)
    context: dict[str, Any] = {
        "kind": "position_context",
        "source": "portfolio_holding",
        "holding_id": holding.id,
        "has_position_context": avg_cost is not None,
        "entry_price": avg_cost,
        "entry_price_source": "portfolio_holding.average_cost",
        "decision_topic": "position",
        "position_side": "long",
        "market": holding.market,
        "symbol": holding.symbol,
        "symbol_name": holding.symbol_name,
        "quantity": holding.quantity,
        "cost_amount": holding.cost_amount,
        "currency": holding.currency,
        "strategy_horizon": holding.strategy_horizon,
        "opened_at": holding.opened_at.isoformat() if isinstance(holding.opened_at, date) else None,
    }
    return {key: value for key, value in context.items() if value is not None}


def holding_to_dict(holding: PortfolioHolding) -> dict[str, Any]:
    return {
        "id": holding.id,
        "market": holding.market,
        "symbol": holding.symbol,
        "symbol_name": holding.symbol_name,
        "quantity": holding.quantity,
        "cost_amount": holding.cost_amount,
        "currency": holding.currency,
        "average_cost": average_cost(holding),
        "note": holding.note,
        "tags": holding.tags,
        "strategy_horizon": holding.strategy_horizon,
        "opened_at": holding.opened_at,
        "is_active": holding.is_active,
        "position_context": position_context_for_holding(holding),
        "created_at": holding.created_at,
        "updated_at": holding.updated_at,
    }


def create_holding(db: Session, payload: PortfolioHoldingCreate) -> dict[str, Any]:
    market = normalize_market(payload.market)
    symbol = normalize_symbol(market, payload.symbol)
    symbol_name = ensure_symbol_exists(db, market, symbol)
    currency = (payload.currency or DEFAULT_CURRENCIES[market]).strip().upper()

    holding = PortfolioHolding(
        market=market,
        symbol=symbol,
        symbol_name=symbol_name,
        quantity=payload.quantity,
        cost_amount=payload.cost_amount,
        currency=currency,
        note=payload.note,
        tags=payload.tags,
        strategy_horizon=payload.strategy_horizon,
        opened_at=payload.opened_at,
        is_active=payload.is_active,
    )
    db.add(holding)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PortfolioDuplicateHoldingError(
            f"Holding for market='{market}' symbol='{symbol}' already exists."
        ) from exc

    db.refresh(holding)
    return holding_to_dict(holding)


def get_holding(db: Session, holding_id: int) -> PortfolioHolding:
    holding = db.query(PortfolioHolding).filter(PortfolioHolding.id == holding_id).first()
    if holding is None:
        raise PortfolioHoldingNotFoundError(f"Portfolio holding id={holding_id} not found.")
    return holding


def list_holdings(
    db: Session,
    *,
    market: str | None = None,
    symbol: str | None = None,
    is_active: bool | None = True,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = db.query(PortfolioHolding)
    normalized_market: str | None = None
    if market is not None:
        normalized_market = normalize_market(market)
        query = query.filter(PortfolioHolding.market == normalized_market)

    if symbol is not None:
        if normalized_market is None:
            raise PortfolioError("market is required when filtering portfolio holdings by symbol.")
        query = query.filter(PortfolioHolding.symbol == normalize_symbol(normalized_market, symbol))

    if is_active is not None:
        query = query.filter(PortfolioHolding.is_active.is_(is_active))

    holdings = (
        query.order_by(PortfolioHolding.market.asc(), PortfolioHolding.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [holding_to_dict(holding) for holding in holdings]


def update_holding(
    db: Session,
    holding_id: int,
    payload: PortfolioHoldingUpdate,
) -> dict[str, Any]:
    holding = get_holding(db, holding_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "currency" in update_data and update_data["currency"] is not None:
        update_data["currency"] = update_data["currency"].strip().upper()

    for key, value in update_data.items():
        setattr(holding, key, value)

    db.commit()
    db.refresh(holding)
    return holding_to_dict(holding)


def delete_holding(db: Session, holding_id: int) -> None:
    holding = get_holding(db, holding_id)
    db.delete(holding)
    db.commit()


def get_position_context_for_scope(
    db: Session | None,
    *,
    scope_type: str,
    scope_id: str | None,
) -> dict[str, Any]:
    market = SCOPE_TO_MARKET.get(scope_type)
    if db is None or market is None or not scope_id:
        return {}

    symbol = normalize_symbol(market, scope_id)
    holding = (
        db.query(PortfolioHolding)
        .filter(
            PortfolioHolding.market == market,
            PortfolioHolding.symbol == symbol,
            PortfolioHolding.is_active.is_(True),
        )
        .first()
    )
    if holding is None:
        return {}
    return position_context_for_holding(holding)
