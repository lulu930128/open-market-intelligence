"""Cache-only persistence access for revisioned research geometry."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import StockMaster, TaiwanPriceMapSnapshot, TaiwanTechnicalInputRevision
from app.market.stock_price_map_schemas import METHODOLOGY_VERSION


def read_price_map_external_revision() -> str:
    from app.market.tw_corporate_events import taiwan_corporate_event_revision
    from app.market.exchange_calendar_cache import read_exchange_calendar_cache
    from app.market.technical_evidence import ADVANCED_ALGORITHM_VERSION, INDICATOR_ALGORITHM_VERSION
    from app.market.tw_bar_aggregation import TAIWAN_BAR_AGGREGATION_VERSION
    from app.market.tw_technical_service import INPUT_QUALITY_VERSION
    from app.market.trading_calendar import TAIWAN_MARKET_HOLIDAYS, TAIWAN_EMERGENCY_MARKET_CLOSURES
    return sha256(json.dumps({"corporate": taiwan_corporate_event_revision(),
        "algorithms": [INDICATOR_ALGORITHM_VERSION, ADVANCED_ALGORITHM_VERSION, TAIWAN_BAR_AGGREGATION_VERSION],
        "input_quality": INPUT_QUALITY_VERSION,
        "calendar_builtin": {
            str(year): {day.isoformat(): name for day, name in holidays.items()}
            for year, holidays in TAIWAN_MARKET_HOLIDAYS.items()
        },
        "calendar_emergency": {
            day.isoformat(): {"name": item.name, "reason_code": item.reason_code, "source": item.source}
            for day, item in TAIWAN_EMERGENCY_MARKET_CLOSURES.items()
        },
        "calendar": read_exchange_calendar_cache().get("markets", {}).get("tw", {})},
        sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def snapshot_matches(row: TaiwanPriceMapSnapshot, *, input_revision: int, parameter_revision: str, corporate_revision: str, basis_date: date) -> bool:
    return (row.input_revision == input_revision
            and row.parameter_revision == parameter_revision
            and row.corporate_revision == corporate_revision
            and row.basis_date == basis_date
            and row.methodology_version == METHODOLOGY_VERSION)


def snapshot_storage_available(db: Session) -> bool:
    inspector = inspect(db.connection())
    if not all(inspector.has_table(name) for name in (
        "taiwan_price_map_snapshot", "taiwan_technical_input_revision",
    )):
        return False
    # Metadata creation alone does not install the transactional invalidation contract.
    if db.bind.dialect.name == "sqlite":
        from sqlalchemy import text
        return db.execute(text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='tr_tw_technical_market_daily_price_update'")).first() is not None
    return db.bind.dialect.name == "postgresql"


def read_input_revisions(db: Session, stock_ids: list[str]) -> dict[str, int]:
    if len(stock_ids) > 5000:
        raise ValueError("Technical revision read exceeds bounded universe")
    rows = db.query(TaiwanTechnicalInputRevision).filter(TaiwanTechnicalInputRevision.stock_id.in_(stock_ids)).all()
    return {row.stock_id: row.generation for row in rows}


def read_price_map_snapshots(db: Session, stock_ids: list[str], timeframe: str) -> dict[str, TaiwanPriceMapSnapshot]:
    if len(stock_ids) > 5000:
        raise ValueError("Price Map snapshot read exceeds bounded universe")
    return {row.stock_id: row for row in db.query(TaiwanPriceMapSnapshot).filter(
        TaiwanPriceMapSnapshot.stock_id.in_(stock_ids),
        TaiwanPriceMapSnapshot.timeframe == timeframe,
    ).all()}


def read_price_map_universe(db: Session, *, markets: tuple[str, ...] = ("TWSE", "TPEX"), stock_ids: tuple[str, ...] = ()) -> list[StockMaster]:
    query = db.query(StockMaster).filter(StockMaster.is_active.is_(True), StockMaster.instrument_type == "stock", StockMaster.market.in_(markets))
    if stock_ids:
        query = query.filter(StockMaster.stock_id.in_(stock_ids))
    rows = query.order_by(StockMaster.stock_id).limit(5001).all()
    if len(rows) > 5000:
        raise ValueError("Price Map universe exceeds 5000; specify a bounded universe")
    return rows
