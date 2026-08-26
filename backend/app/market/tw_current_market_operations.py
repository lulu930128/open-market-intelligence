"""Application-owned refresh operations for Taiwan current-session aggregates."""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.index_parsers import regular_stock_code
from app.market.providers.tw_current_market import CurrentBreadthAdapter, CurrentIndexAdapter
from app.market.providers.twse_mis_current_breadth import read_twse_mis_current_breadth
from app.market.providers.twse_mis_current_index import read_twse_mis_current_index
from app.market.providers.yahoo_current_index import read_yahoo_current_index
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_current_market_acquisition import (
    TaiwanCurrentBreadthAcquisitionExecutor,
    TaiwanCurrentIndexAcquisitionExecutor,
)
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_BREADTH_CAPABILITY_ID,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    current_source_binding,
)
from app.market.tw_current_market_platform import (
    refresh_taiwan_current_breadth,
    refresh_taiwan_current_index,
)
from app.market_data.policies import RealtimePolicy


class TaiwanRegisteredStockUniverseReader:
    """Read the bounded registered stock universe without provider IO."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def __call__(self, market: str) -> list[str]:
        normalized = str(market or "").strip().upper()
        if normalized not in {"TWSE", "TPEX"}:
            raise ValueError("Taiwan breadth universe requires TWSE or TPEX")
        rows = (
            self._db.query(StockMaster.stock_id)
            .filter(func.upper(StockMaster.market) == normalized)
            .filter(StockMaster.instrument_type == "stock")
            .filter(StockMaster.is_active.is_(True))
            .order_by(StockMaster.stock_id.asc())
            .all()
        )
        return list(
            dict.fromkeys(
                code
                for row in rows
                for code in [regular_stock_code(row.stock_id)]
                if code is not None
            )
        )


def _binding(provider: str, source: str, capability: str):
    binding = current_source_binding(
        provider=provider,
        source=source,
        capability_id=capability,
    )
    if binding is None:
        raise RuntimeError("Taiwan current market source binding is missing")
    return binding


def build_current_market_executors(
    db: Session,
    *,
    clock,
) -> tuple[
    TaiwanCurrentIndexAcquisitionExecutor,
    TaiwanCurrentBreadthAcquisitionExecutor,
]:
    universe_reader = TaiwanRegisteredStockUniverseReader(db)
    index = TaiwanCurrentIndexAcquisitionExecutor(
        (
            CurrentIndexAdapter(
                _binding(
                    "twse_mis",
                    "twse_mis_index_snapshot",
                    TW_CURRENT_INDEX_CAPABILITY_ID,
                ),
                read_twse_mis_current_index,
                clock=clock,
            ),
            CurrentIndexAdapter(
                _binding(
                    "yahoo_finance_chart",
                    "yahoo_finance_chart",
                    TW_CURRENT_INDEX_CAPABILITY_ID,
                ),
                read_yahoo_current_index,
                clock=clock,
            ),
        )
    )
    breadth = TaiwanCurrentBreadthAcquisitionExecutor(
        (
            CurrentBreadthAdapter(
                _binding(
                    "twse_mis",
                    "twse_mis_live_breadth",
                    TW_CURRENT_BREADTH_CAPABILITY_ID,
                ),
                partial(
                    read_twse_mis_current_breadth,
                    universe_reader=universe_reader,
                ),
                clock=clock,
            ),
        )
    )
    return index, breadth


def refresh_taiwan_current_index_operation(
    db: Session,
    *,
    index_id: str,
    requested_at: datetime | None = None,
):
    now = requested_at or datetime.now(TAIWAN_TZ)
    index, _breadth = build_current_market_executors(
        db,
        clock=lambda: datetime.now(TAIWAN_TZ),
    )
    return refresh_taiwan_current_index(
        db,
        index_id=index_id,
        requested_at=now,
        policy=RealtimePolicy.PREFER_LIVE,
        acquisition=index,
    )


def refresh_taiwan_current_breadth_operation(
    db: Session,
    *,
    venue: str,
    requested_at: datetime | None = None,
):
    now = requested_at or datetime.now(TAIWAN_TZ)
    _index, breadth = build_current_market_executors(
        db,
        clock=lambda: datetime.now(TAIWAN_TZ),
    )
    return refresh_taiwan_current_breadth(
        db,
        venue=venue,
        requested_at=now,
        policy=RealtimePolicy.PREFER_LIVE,
        acquisition=breadth,
    )


__all__ = [
    "TaiwanRegisteredStockUniverseReader",
    "build_current_market_executors",
    "refresh_taiwan_current_breadth_operation",
    "refresh_taiwan_current_index_operation",
]
