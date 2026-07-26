from __future__ import annotations

from datetime import date
import logging
from time import monotonic, sleep
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import BrokerBranchTradeDaily, StockMaster
from app.market.broker_branch import (
    NSTOCK_BRANCH_SOURCE_NAME,
    NSTOCK_BRANCH_TOP15_URL,
    ensure_broker_branch_daily,
    probe_broker_branch_release,
)
from app.observability.provider_health import record_provider_event


logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int | None, int | None, str | None], None]
TAIWAN_STOCK_MARKETS = ("TWSE", "TPEX")
TAIWAN_STOCK_INSTRUMENT_TYPE = "stock"


def list_taiwan_broker_branch_stock_ids(db: Session) -> list[str]:
    """Return the active TWSE/TPEx ordinary-stock universe in stable order."""
    return [
        row[0]
        for row in (
            db.query(StockMaster.stock_id)
            .filter(StockMaster.is_active.is_(True))
            .filter(func.upper(StockMaster.market).in_(TAIWAN_STOCK_MARKETS))
            .filter(
                func.lower(StockMaster.instrument_type)
                == TAIWAN_STOCK_INSTRUMENT_TYPE
            )
            .order_by(StockMaster.stock_id.asc())
            .all()
        )
    ]


def _covered_stock_ids(
    db: Session,
    *,
    trade_date: date,
    universe: list[str],
) -> set[str]:
    if not universe:
        return set()

    return {
        row[0]
        for row in (
            db.query(BrokerBranchTradeDaily.stock_id)
            .filter(BrokerBranchTradeDaily.trade_date == trade_date)
            .filter(BrokerBranchTradeDaily.stock_id.in_(universe))
            .distinct()
            .all()
        )
    }


def get_taiwan_broker_branch_market_coverage(
    db: Session,
    *,
    trade_date: date,
) -> dict:
    universe = list_taiwan_broker_branch_stock_ids(db)
    covered = _covered_stock_ids(db, trade_date=trade_date, universe=universe)
    missing = [stock_id for stock_id in universe if stock_id not in covered]
    return {
        "trade_date": trade_date,
        "expected_count": len(universe),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "complete": bool(universe) and not missing,
    }


def _record_collection_event(
    db: Session,
    *,
    trade_date: date,
    status: str,
    message: str,
    detail: dict,
    job_run_id: int | None,
    error_message: str | None = None,
) -> None:
    try:
        record_provider_event(
            db,
            market="tw",
            provider="nstock",
            resource="broker_branch_trade_daily",
            target="all-stocks",
            status=status,
            event_type="scheduled_collection",
            source_url=NSTOCK_BRANCH_TOP15_URL,
            message=message,
            error_message=error_message,
            detail={"trade_date": trade_date.isoformat(), **detail},
            job_run_id=job_run_id,
        )
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to record Taiwan broker-branch collection event.",
            exc_info=True,
        )


def refresh_taiwan_broker_branch_market(
    db: Session,
    *,
    trade_date: date,
    sleep_seconds: float = 0.5,
    max_stocks: int = 2500,
    max_runtime_seconds: int = 7200,
    progress: ProgressCallback | None = None,
    job_run_id: int | None = None,
) -> dict:
    """Collect the latest nStock Top15 snapshot for the ordinary-stock universe.

    The upstream endpoint exposes only its latest trading date, so this routine
    intentionally validates the provider date before starting the all-market
    loop. Existing stock/date rows are never fetched again.
    """
    universe = list_taiwan_broker_branch_stock_ids(db)
    covered_before = _covered_stock_ids(
        db,
        trade_date=trade_date,
        universe=universe,
    )
    missing = [stock_id for stock_id in universe if stock_id not in covered_before]
    request_budget = max(int(max_stocks), 1)
    candidates = missing[:request_budget]
    total = max(len(candidates), 1)

    if not universe:
        result = {
            "status": "partial",
            "reason": "empty_universe",
            "trade_date": trade_date,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "expected_count": 0,
            "covered_before_count": 0,
            "covered_count": 0,
            "remaining_count": 0,
            "request_count": 0,
            "success_count": 0,
            "no_data_count": 0,
            "no_data_stock_ids": [],
            "no_data_samples_are_capped": False,
            "error_count": 0,
            "error_samples_are_capped": False,
            "errors": [],
        }
        _record_collection_event(
            db,
            trade_date=trade_date,
            status="error",
            message="Taiwan broker-branch collection has no eligible stock universe.",
            detail=result,
            job_run_id=job_run_id,
            error_message="No active TWSE/TPEx ordinary stocks were found.",
        )
        return result

    if not missing:
        if progress:
            progress(1, 1, "Taiwan broker-branch daily coverage is already complete.")
        return {
            "status": "completed",
            "reason": "already_complete",
            "trade_date": trade_date,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "expected_count": len(universe),
            "covered_before_count": len(covered_before),
            "covered_count": len(covered_before),
            "remaining_count": 0,
            "request_count": 0,
            "success_count": 0,
            "no_data_count": 0,
            "no_data_stock_ids": [],
            "no_data_samples_are_capped": False,
            "error_count": 0,
            "error_samples_are_capped": False,
            "errors": [],
        }

    probe_stock_id = "2330" if "2330" in universe else universe[0]
    try:
        probe = probe_broker_branch_release(probe_stock_id)
    except Exception as exc:
        db.rollback()
        result = {
            "status": "partial",
            "reason": "provider_probe_failed",
            "trade_date": trade_date,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "expected_count": len(universe),
            "covered_before_count": len(covered_before),
            "covered_count": len(covered_before),
            "remaining_count": len(missing),
            "request_count": 1,
            "success_count": 0,
            "no_data_count": 0,
            "no_data_stock_ids": [],
            "no_data_samples_are_capped": False,
            "error_count": 1,
            "error_samples_are_capped": False,
            "errors": [{"stock_id": probe_stock_id, "error": str(exc)}],
        }
        _record_collection_event(
            db,
            trade_date=trade_date,
            status="error",
            message="Taiwan broker-branch provider readiness probe failed.",
            detail=result,
            job_run_id=job_run_id,
            error_message=str(exc),
        )
        return result

    provider_trade_date = probe["trade_date"]
    if provider_trade_date != trade_date:
        result = {
            "status": "partial",
            "reason": "provider_not_ready",
            "trade_date": trade_date,
            "provider_trade_date": provider_trade_date,
            "source_name": NSTOCK_BRANCH_SOURCE_NAME,
            "expected_count": len(universe),
            "covered_before_count": len(covered_before),
            "covered_count": len(covered_before),
            "remaining_count": len(missing),
            "request_count": 1,
            "success_count": 0,
            "no_data_count": 0,
            "no_data_stock_ids": [],
            "no_data_samples_are_capped": False,
            "error_count": 0,
            "error_samples_are_capped": False,
            "errors": [],
        }
        _record_collection_event(
            db,
            trade_date=trade_date,
            status="stale",
            message="Taiwan broker-branch provider has not released the expected date yet.",
            detail=result,
            job_run_id=job_run_id,
        )
        return result

    started_at = monotonic()
    attempted_count = 0
    success_count = 0
    no_data_count = 0
    error_count = 0
    no_data_stock_ids: list[str] = []
    errors: list[dict[str, str]] = []
    stopped_reason: str | None = None
    delay_seconds = max(float(sleep_seconds), 0.0)
    runtime_limit = max(int(max_runtime_seconds), 1)

    for index, stock_id in enumerate(candidates, start=1):
        if monotonic() - started_at >= runtime_limit:
            stopped_reason = "max_runtime_reached"
            break

        attempted_count += 1
        try:
            rows = ensure_broker_branch_daily(
                db,
                stock_id=stock_id,
                trade_date=trade_date,
                force=False,
            )
            if rows:
                success_count += 1
            else:
                no_data_count += 1
                if len(no_data_stock_ids) < 100:
                    no_data_stock_ids.append(stock_id)
        except Exception as exc:
            db.rollback()
            error_count += 1
            if len(errors) < 50:
                errors.append({"stock_id": stock_id, "error": str(exc)})
            logger.warning(
                "Taiwan broker-branch collection failed stock_id=%s trade_date=%s: %s",
                stock_id,
                trade_date,
                exc,
            )

        if progress and (index == 1 or index % 10 == 0 or index == len(candidates)):
            progress(
                index,
                total,
                (
                    "Collecting Taiwan broker-branch daily snapshots "
                    f"({index}/{len(candidates)}; saved={success_count}; "
                    f"empty={no_data_count}; errors={error_count})."
                ),
            )

        if delay_seconds > 0 and index < len(candidates):
            sleep(delay_seconds)

    covered_after = _covered_stock_ids(
        db,
        trade_date=trade_date,
        universe=universe,
    )
    remaining_count = len(universe) - len(covered_after)
    if remaining_count == 0:
        status = "completed"
        reason = "coverage_complete"
    else:
        status = "partial"
        reason = stopped_reason or (
            "batch_limit_reached"
            if len(missing) > len(candidates)
            else "missing_provider_data"
        )

    result = {
        "status": status,
        "reason": reason,
        "trade_date": trade_date,
        "provider_trade_date": provider_trade_date,
        "source_name": NSTOCK_BRANCH_SOURCE_NAME,
        "expected_count": len(universe),
        "covered_before_count": len(covered_before),
        "covered_count": len(covered_after),
        "remaining_count": remaining_count,
        "request_count": attempted_count + 1,
        "success_count": success_count,
        "no_data_count": no_data_count,
        "no_data_stock_ids": no_data_stock_ids,
        "no_data_samples_are_capped": no_data_count > len(no_data_stock_ids),
        "error_count": error_count,
        "error_samples_are_capped": error_count > len(errors),
        "errors": errors,
        "max_stocks": request_budget,
        "max_runtime_seconds": runtime_limit,
        "sleep_seconds": delay_seconds,
    }
    _record_collection_event(
        db,
        trade_date=trade_date,
        status="success" if status == "completed" else "partial_success",
        message=(
            "Taiwan broker-branch daily coverage completed."
            if status == "completed"
            else "Taiwan broker-branch daily coverage remains partial."
        ),
        detail=result,
        job_run_id=job_run_id,
        error_message=(
            f"{remaining_count} stock(s) remain without broker-branch rows."
            if remaining_count
            else None
        ),
    )
    return result
