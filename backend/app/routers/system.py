import sys

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, settings
from app.db.session import get_db
from app.observability.provider_health import (
    list_provider_events,
    list_source_health_snapshots,
)
from app.observability.schemas import ProviderEventRead, SourceHealthSnapshotRead

router = APIRouter()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "runtime": {
            "project_root": str(PROJECT_ROOT),
            "backend_dir": str(PROJECT_ROOT / "backend"),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
        },
    }


@router.get("/provider-events", response_model=list[ProviderEventRead])
def get_provider_events(
    market: str | None = None,
    provider: str | None = None,
    resource: str | None = None,
    target: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_provider_events(
        db,
        market=market,
        provider=provider,
        resource=resource,
        target=target,
        status=status,
        limit=limit,
    )


@router.get("/source-health-snapshots", response_model=list[SourceHealthSnapshotRead])
def get_source_health_snapshots(
    market: str | None = None,
    provider: str | None = None,
    resource: str | None = None,
    target: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return list_source_health_snapshots(
        db,
        market=market,
        provider=provider,
        resource=resource,
        target=target,
        status=status,
        limit=limit,
    )
