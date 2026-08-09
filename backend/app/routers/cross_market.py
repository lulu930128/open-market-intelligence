from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks
from app.jobs.job_types import CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE
from app.jobs.schemas import JobRunRead
from app.market.cross_market.context import build_cross_market_target_context
from app.market.cross_market.relation_store import build_relation_registry_read
from app.market.cross_market.refresh import normalize_refresh_stock_ids
from app.market.cross_market.schemas import (
    CrossMarketRelationRegistryRead,
    CrossMarketTargetContextRead,
)
from app.routers.market_family_helpers import enqueue_serialized_job


router = APIRouter()


@router.get(
    "/relations/{stock_id}",
    response_model=CrossMarketRelationRegistryRead,
)
def get_cross_market_relations(
    stock_id: str,
    as_of: date | None = None,
    db: Session = Depends(get_db),
) -> CrossMarketRelationRegistryRead:
    try:
        return build_relation_registry_read(
            db,
            stock_id,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/context/{stock_id}",
    response_model=CrossMarketTargetContextRead,
)
def get_cross_market_context(
    stock_id: str,
    db: Session = Depends(get_db),
) -> CrossMarketTargetContextRead:
    try:
        return build_cross_market_target_context(
            db,
            stock_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_cross_market_context(
    stock_ids: str = Query(min_length=1),
    max_symbols: int = Query(default=8, ge=1, le=8),
    provider: str = Query(
        default="auto",
        pattern="^(auto|alphavantage|yahoo_chart)$",
    ),
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    max_runtime_seconds: int = Query(default=120, ge=10, le=300),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        normalized_stock_ids = normalize_refresh_stock_ids(stock_ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    request = {
        "stock_ids": normalized_stock_ids,
        "max_symbols": max_symbols,
        "provider": provider,
        "outputsize": outputsize,
        "max_runtime_seconds": max_runtime_seconds,
    }
    return enqueue_serialized_job(
        db=db,
        job_type=CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE,
        target=",".join(normalized_stock_ids),
        request=request,
        progress_total=max_symbols,
        message="Queued bounded cross-market context refresh.",
        task=backfill_tasks.run_cross_market_context_refresh_job,
        task_args=(
            normalized_stock_ids,
            max_symbols,
            provider,
            outputsize,
            max_runtime_seconds,
        ),
    )
