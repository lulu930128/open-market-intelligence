"""Bounded, restart-resumable producer for persisted technical geometry."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from time import monotonic
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import SessionLocal
from app.market.price_map_snapshot_repository import read_price_map_universe, snapshot_storage_available, read_price_map_external_revision
from app.market.price_map_snapshot_transaction import claim_price_map_snapshot, fail_price_map_snapshot, publish_price_map_snapshot
from app.market.stock_price_map import build_tw_stock_price_map
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.trading_calendar import latest_completed_taiwan_session_date

logger = logging.getLogger(__name__)


def produce_taiwan_price_map_snapshots(*, session_factory: Callable = SessionLocal,
        builder: Callable = build_tw_stock_price_map, clock: Callable = lambda: datetime.now(timezone.utc),
        batch_size: int = 12, time_budget_seconds: float = 45,
        timeframes: tuple[str, ...] = ("daily", "weekly", "monthly")) -> dict[str, Any]:
    if not 1 <= batch_size <= 50 or not 1 <= time_budget_seconds <= 120 or not timeframes or any(tf not in {"daily", "weekly", "monthly"} for tf in timeframes):
        raise ValueError("Invalid bounded Price Map production budget")
    started = monotonic()
    report = {"status": "completed_batch", "attempted": 0, "published": 0, "failed": 0, "superseded": 0,
              "scope_semantics": "bounded_batch_not_full_market"}
    with session_factory() as db:
        if not snapshot_storage_available(db):
            return {**report, "status": "migration_required"}
        stock_ids = [stock.stock_id for stock in read_price_map_universe(db)]
    # Published headers and retry_after are the durable checkpoint. Each pass skips
    # finished work, advancing through the universe without a process-local cursor.
    for stock_id in stock_ids:
        for timeframe in timeframes:
            if report["attempted"] >= batch_size or monotonic() - started >= time_budget_seconds:
                return report
            now = clock()
            parameters = get_technical_analysis_parameters()
            corporate_revision = read_price_map_external_revision()
            token = None
            try:
                with session_factory() as db:
                    token = claim_price_map_snapshot(db, stock_id=stock_id, timeframe=timeframe,
                        parameters=parameters, corporate_revision=corporate_revision,
                        basis_date=latest_completed_taiwan_session_date(now), now=now)
                    db.commit()
                if token is None:
                    continue
                report["attempted"] += 1
                with session_factory() as db:
                    payload = builder(db=db, stock_id=stock_id, timeframe=timeframe, now=now, parameters=parameters)
                with session_factory() as db:
                    published = publish_price_map_snapshot(db, stock_id=stock_id, timeframe=timeframe,
                        token=token, payload=payload, parameters=get_technical_analysis_parameters(),
                        corporate_revision=read_price_map_external_revision(), now=clock())
                    if not published:
                        fail_price_map_snapshot(db, stock_id=stock_id, timeframe=timeframe, token=token,
                            now=clock(), error_code="INPUT_REVISION_SUPERSEDED")
                    db.commit()
                report["published" if published else "superseded"] += 1
            except IntegrityError:
                if token is None:
                    continue  # Another process claimed this primary key.
                raise
            except Exception as exc:
                logger.exception("Price Map snapshot failed stock=%s timeframe=%s", stock_id, timeframe)
                report["failed"] += 1
                if token is not None:
                    with session_factory() as db:
                        fail_price_map_snapshot(db, stock_id=stock_id, timeframe=timeframe,
                            token=token, now=clock(), error_code=type(exc).__name__)
                        db.commit()
    return report


def add_taiwan_price_map_snapshot_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_price_map_snapshot_scheduler:
        return False
    scheduler.add_job(produce_taiwan_price_map_snapshots, trigger="interval", seconds=60,
        id="taiwan_price_map_snapshots", replace_existing=True, max_instances=1, coalesce=True)
    return True
