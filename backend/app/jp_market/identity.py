"""Japanese instrument identity at the market boundary, independent of consumers."""

from sqlalchemy.orm import Session

from app.db.models import JPStockMaster
from app.jp_market.symbols import normalize_jp_symbol
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


def read_jp_instrument(db: Session, symbol: str) -> InstrumentKey:
    symbol = normalize_jp_symbol(symbol)
    if symbol == "^N225":
        return InstrumentKey(market=Market.JP, symbol=symbol, venue="XJPX", instrument_type=InstrumentType.INDEX)
    with db.no_autoflush:
        master = db.query(JPStockMaster).filter_by(symbol=symbol).one_or_none()
    if master is None or master.currency != "JPY" or not symbol.endswith(".T"):
        raise ValueError("JP instrument requires persisted Tokyo instrument metadata")
    kind = {"stock": InstrumentType.STOCK, "equity": InstrumentType.STOCK,
            "etf": InstrumentType.ETF}.get((master.asset_type or "").strip().lower())
    if kind is None:
        raise ValueError("JP instrument type is unknown or not supported by daily integration")
    return InstrumentKey(market=Market.JP, symbol=symbol, venue="XJPX", instrument_type=kind)
