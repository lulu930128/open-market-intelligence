"""Provider-neutral Taiwan Data Core catalog and persisted-evidence API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_dataset_catalog import (
    TW_DATASET_CATALOG,
    TaiwanDatasetContract,
    TaiwanDatasetOperationSpec,
)
from app.market.tw_dataset_health import (
    TaiwanDatasetPlatformProjection,
    read_taiwan_dataset_health,
)


router = APIRouter()


@router.get(
    "/data-core/datasets",
    response_model=list[TaiwanDatasetContract],
)
def list_taiwan_data_core_datasets() -> list[TaiwanDatasetContract]:
    return list(TW_DATASET_CATALOG.all())


@router.get(
    "/data-core/operations",
    response_model=list[TaiwanDatasetOperationSpec],
)
def list_taiwan_data_core_operations() -> list[TaiwanDatasetOperationSpec]:
    """Describe bounded operations; this endpoint never executes them."""

    return list(TW_DATASET_CATALOG.operations())


@router.get(
    "/data-core/datasets/{dataset_id}/health",
    response_model=TaiwanDatasetPlatformProjection,
)
def get_taiwan_data_core_dataset_health(
    dataset_id: str,
    target: str | None = Query(default=None, min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> TaiwanDatasetPlatformProjection:
    try:
        normalized_target = (
            target.strip().upper() if isinstance(target, str) and target.strip() else None
        )
        return read_taiwan_dataset_health(
            db,
            dataset_id,
            scope_value=normalized_target,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


__all__ = ["router"]
