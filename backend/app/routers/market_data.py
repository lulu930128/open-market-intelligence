from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import service as job_service
from app.jobs.eod_coverage import enqueue_eod_coverage_reconcile
from app.jobs.schemas import JobRunRead
from app.market_data.eod_coverage import cached_eod_coverage_projection
from app.market_data.eod_coverage_schemas import (
    EODCoverageListRead,
    EODCoverageReconcileRequest,
)


router = APIRouter()


@router.get("/eod-coverage", response_model=EODCoverageListRead)
def get_eod_coverage(
    market: Literal["TW", "US"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Read the latest saved checkpoints without provider or job side effects."""

    return cached_eod_coverage_projection(db, market=market)


@router.post(
    "/eod-coverage/reconcile",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def reconcile_eod_coverage(payload: EODCoverageReconcileRequest, db: Session = Depends(get_db)):
    job, _created = enqueue_eod_coverage_reconcile(
        db,
        market=payload.market,
        repair=payload.repair,
        expected_trade_date=payload.expected_trade_date,
        max_symbols=payload.max_symbols,
        max_runtime_seconds=payload.max_runtime_seconds,
        sleep_seconds=payload.sleep_seconds,
        max_consecutive_errors=payload.max_consecutive_errors,
    )
    return job_service.serialize_job(job)


__all__ = ["router"]
