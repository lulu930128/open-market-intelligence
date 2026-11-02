"""Bounded, restart-resumable producer for persisted technical geometry."""
from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter
from bisect import bisect_right
import json
import logging
from math import isfinite
from time import monotonic
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import TaiwanPriceMapSnapshot
from app.market.price_map_snapshot_repository import (
    read_price_map_universe, snapshot_storage_available, read_price_map_external_revision,
    read_input_revisions, read_price_map_snapshots, snapshot_matches,
)
from app.market.price_map_snapshot_transaction import claim_price_map_snapshot, fail_price_map_snapshot, publish_price_map_snapshot, snapshot_claim_skip_reason
from app.market.stock_price_map import build_tw_stock_price_map
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.trading_calendar import latest_completed_taiwan_session_date
from app.jobs.taiwan_historical_input_repair import (
    historical_repair_candidate, admit_taiwan_historical_input_repair,
    read_pending_historical_repair_stocks, continue_existing_historical_input_repair,
)

logger = logging.getLogger(__name__)
# Fairness hint for the tiny payload-inspection budget only. Snapshot progress
# and repair identity/attempts remain durable in their existing DB owners.
_repair_after_stock = ""
REPAIR_ADMISSION_LIMIT = 2


def produce_taiwan_price_map_snapshots(*, session_factory: Callable = SessionLocal,
        builder: Callable = build_tw_stock_price_map, clock: Callable = lambda: datetime.now(timezone.utc),
        batch_size: int = 12, time_budget_seconds: float = 45,
        timeframes: tuple[str, ...] = ("daily",),
        stock_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
    global _repair_after_stock
    if (type(batch_size) is not int or not 1 <= batch_size <= 50
            or isinstance(time_budget_seconds, bool) or not isinstance(time_budget_seconds, (int, float))
            or not isfinite(time_budget_seconds) or not 1 <= time_budget_seconds <= 120
            or not isinstance(timeframes, tuple) or not timeframes
            or any(tf not in {"daily", "weekly", "monthly"} for tf in timeframes)):
        raise ValueError("Invalid bounded Price Map production budget")
    # None retains the existing full-universe rollout. An explicit empty or
    # malformed pilot must never silently expand to that universe.
    if stock_ids is not None and (not isinstance(stock_ids, tuple) or not 1 <= len(stock_ids) <= 10
            or any(not isinstance(s, str) or not s.strip() or len(s) > 20 for s in stock_ids)):
        raise ValueError("Price Map pilot requires 1 to 10 explicit stock_ids")
    targets = tuple(dict.fromkeys(s.strip() for s in stock_ids)) if stock_ids is not None else None
    timeframes = tuple(dict.fromkeys(timeframes))
    started = monotonic()
    report = {"status": "completed_batch", "attempted": 0, "published": 0, "failed": 0, "superseded": 0,
              "scope_semantics": "bounded_pilot" if targets is not None else "bounded_batch_not_full_market",
              "timeframes": list(timeframes), "requested_stock_ids": list(targets) if targets is not None else None,
              "selected_stock_ids": [], "unavailable_stock_ids": [], "publication_status_counts": {},
              "skipped_reason_counts": {}, "repair_inspected": 0, "repair_submitted": 0,
              "repair_admission_errors": 0}
    with session_factory() as db:
        if not snapshot_storage_available(db):
            return {**report, "status": "migration_required"}
        selected = [stock.stock_id for stock in read_price_map_universe(db, stock_ids=targets or ())]
        report["selected_stock_ids"] = selected if targets is not None else None
        report["unavailable_stock_ids"] = sorted(set(targets or ()) - set(selected))
        parameters = get_technical_analysis_parameters()
        corporate_revision = read_price_map_external_revision()
        now = clock()
        pending_repairs = read_pending_historical_repair_stocks(db, now=now)
        basis = latest_completed_taiwan_session_date(now)
        revisions = read_input_revisions(db, selected)
        headers = {tf: read_price_map_snapshots(db, selected, tf, include_payload=False) for tf in timeframes}
        states: Counter[str] = Counter()
        partials = []
        for timeframe in timeframes:
            for stock_id in selected:
                row = headers[timeframe].get(stock_id)
                state = "not_computed" if row is None else row.status if snapshot_matches(row,
                    input_revision=revisions.get(stock_id, 0), parameter_revision=parameters.revision,
                    corporate_revision=corporate_revision, basis_date=basis) else "stale"
                states[state] += 1
                if timeframe == "daily" and (state == "partial" or stock_id in pending_repairs):
                    partials.append(stock_id)  # Same existing header walk, no repair sweep.
        report["coverage_before"] = {"requested_items": len(selected) * len(timeframes),
            "status_counts": dict(sorted(states.items()))}
    offset = bisect_right(partials, _repair_after_stock)
    repair_window = set((partials[offset:] + partials[:offset])[:REPAIR_ADMISSION_LIMIT])
    admission_deadline = monotonic() + 3

    def consider_repair(stock_id, timeframe, payload=None):
        global _repair_after_stock
        if (timeframe != "daily" or report["repair_inspected"] >= REPAIR_ADMISSION_LIMIT
                or monotonic() >= admission_deadline
                or monotonic() - started >= time_budget_seconds):
            return
        report["repair_inspected"] += 1
        _repair_after_stock = stock_id
        try:
            if stock_id in pending_repairs:
                with session_factory() as db:
                    result = continue_existing_historical_input_repair(db, stock_id=stock_id, now=clock())
                report["repair_submitted"] += int(result["submitted"])
                return
            if payload is None:
                with session_factory() as db:
                    row = db.get(TaiwanPriceMapSnapshot, (stock_id, timeframe))
                    if row is None or row.status != "partial":
                        return
                    payload = json.loads(row.payload_json)
            if historical_repair_candidate(payload):
                with session_factory() as db:
                    result = admit_taiwan_historical_input_repair(db, stock_id=stock_id,
                        basis=basis, input_revision=revisions.get(stock_id, 0), now=clock())
                report["repair_submitted"] += int(result["submitted"])
        except Exception:
            report["repair_admission_errors"] += 1
            logger.exception("Price Map repair admission failed stock=%s", stock_id)
    # Published headers/retry_after remain the checkpoint. Finish the cheap skip
    # walk (and bounded repair admission) before spending the build budget.
    due = []
    for stock_id in selected:
        for timeframe in timeframes:
            skip = snapshot_claim_skip_reason(headers[timeframe].get(stock_id),
                input_revision=revisions.get(stock_id, 0), parameter_revision=parameters.revision,
                corporate_revision=corporate_revision, basis_date=basis, now=now)
            if skip:
                counts = report["skipped_reason_counts"]
                counts[skip] = counts.get(skip, 0) + 1
                if skip == "current_published" and stock_id in repair_window:
                    consider_repair(stock_id, timeframe)
                continue
            due.append((stock_id, timeframe))

    def work_order(item):
        stock_id, timeframe = item
        row = headers[timeframe].get(stock_id)
        claimed = row.claimed_at if row is not None else datetime.min.replace(tzinfo=timezone.utc)
        claimed = claimed.replace(tzinfo=timezone.utc) if claimed.tzinfo is None else claimed
        return claimed, stock_id, timeframes.index(timeframe)

    # Oldest attempt first: never-computed items can advance past a repeatedly
    # stale prefix. The existing durable claim time also rotates stale work;
    # restart needs no new cursor/store and claim still rechecks every gate.
    for stock_id, timeframe in sorted(due, key=work_order):
        if report["attempted"] >= batch_size or monotonic() - started >= time_budget_seconds:
            logger.info("Price Map bounded production: %s", report)
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
                else:
                    row = db.get(TaiwanPriceMapSnapshot, (stock_id, timeframe), populate_existing=True)
                    publication_status = row.status
                db.commit()
            if published:
                counts = report["publication_status_counts"]
                counts[publication_status] = counts.get(publication_status, 0) + 1
                if publication_status == "partial" or stock_id in pending_repairs:
                    consider_repair(stock_id, timeframe, payload)
            report["published" if published else "superseded"] += 1
        except Exception as exc:
            if isinstance(exc, IntegrityError) and token is None:
                continue  # Another process claimed this primary key.
            logger.exception("Price Map snapshot failed stock=%s timeframe=%s", stock_id, timeframe)
            report["failed"] += 1
            if token is not None:
                with session_factory() as db:
                    fail_price_map_snapshot(db, stock_id=stock_id, timeframe=timeframe,
                        token=token, now=clock(), error_code=type(exc).__name__)
                    db.commit()
    logger.info("Price Map bounded production: %s", report)
    return report


def add_taiwan_price_map_snapshot_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_price_map_snapshot_scheduler:
        return False
    configured_ids = settings.taiwan_price_map_snapshot_stock_ids
    stock_ids = tuple(s.strip() for s in configured_ids.split(",")) if configured_ids else None
    timeframes = tuple(s.strip() for s in settings.taiwan_price_map_snapshot_timeframes.split(","))
    if (not timeframes or any(tf not in {"daily", "weekly", "monthly"} for tf in timeframes)
            or (stock_ids is not None and (not 1 <= len(stock_ids) <= 10
                or any(not s or len(s) > 20 for s in stock_ids)))):
        raise ValueError("Invalid Price Map scheduler pilot selection")
    scheduler.add_job(produce_taiwan_price_map_snapshots, trigger="interval", seconds=60,
        id="taiwan_price_map_snapshots", replace_existing=True, max_instances=1, coalesce=True,
        kwargs={"stock_ids": stock_ids, "timeframes": timeframes})
    return True
