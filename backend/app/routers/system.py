import sys

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, settings
from app.db.session import get_db
from app.observability.provider_health import (
    list_provider_events,
    list_source_health_snapshots,
)
from app.observability.schemas import ProviderEventRead, SourceHealthSnapshotRead
from app.market.tw_realtime_lease_platform import summarize_fugle_realtime_runtime
from app.us_market.daily_rollout import us_daily_rollout_snapshot
from app.us_market.intraday_materializer import (
    US_RECURRING_MATERIALIZER_PROFILE,
    us_intraday_materializer_runtime_summary,
)
from app.us_market.ohlc_priority import PRIORITY_US_INDEX_SYMBOLS
from app.jobs.us_index_data_repair_gate import (
    us_index_data_repair_runtime_summary,
)

router = APIRouter()


def _us_canonical_shadow_symbol_count() -> int:
    return len(
        {
            item.strip().upper()
            for item in settings.us_canonical_shadow_symbols.split(",")
            if item.strip()
        }
    )


@router.get("/health")
def health_check():
    us_canary_symbol_count = _us_canonical_shadow_symbol_count()
    us_canonical_mode = (
        settings.us_canonical_market_data_mode
        or settings.canonical_market_data_mode
    )
    us_daily_rollout = us_daily_rollout_snapshot()
    fugle_health = summarize_fugle_realtime_runtime()
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "runtime": {
            "project_root": str(PROJECT_ROOT),
            "backend_dir": str(PROJECT_ROOT / "backend"),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "canonical_market_data_mode": settings.canonical_market_data_mode,
            "us_canonical_market_data_mode": us_canonical_mode,
            "canonical_market_data_rollout_stage": us_canonical_mode,
            "us_canonical_market_data_enabled": (
                us_canonical_mode != "off"
                and (
                    us_canonical_mode == "on"
                    or us_canary_symbol_count > 0
                )
            ),
            "us_canonical_shadow_enabled": (
                us_canonical_mode != "off"
                and us_canary_symbol_count > 0
            ),
            "us_canonical_shadow_symbol_count": us_canary_symbol_count,
            "us_canonical_canary_max_symbols": settings.us_canonical_canary_max_symbols,
            "us_daily_read_binding_mode": us_daily_rollout["read_binding_mode"],
            "us_daily_acquisition_rollout_mode": us_daily_rollout[
                "acquisition_rollout_mode"
            ],
            "us_daily_acquisition_enabled": us_daily_rollout[
                "acquisition_enabled"
            ],
            "us_daily_acquisition_scope": us_daily_rollout[
                "acquisition_scope"
            ],
            "us_daily_acquisition_canary_target_count": us_daily_rollout[
                "canary_target_count"
            ],
            "us_daily_acquisition_configuration_status": us_daily_rollout[
                "configuration_status"
            ],
            "us_daily_acquisition_limitations": us_daily_rollout["limitations"],
            "us_intraday_materializer": {
                "enabled": settings.enable_us_intraday_materializer,
                "configured_symbols": [
                    item.strip().upper()
                    for item in settings.scheduler_us_intraday_materializer_symbols.split(",")
                    if item.strip()
                ][: settings.scheduler_us_intraday_materializer_max_symbols],
                "max_symbols": settings.scheduler_us_intraday_materializer_max_symbols,
                "quote_interval_seconds": settings.scheduler_us_quote_materializer_interval_seconds,
                "intraday_interval_seconds": settings.scheduler_us_intraday_materializer_interval_seconds,
                "intraday_bars": settings.scheduler_us_intraday_materializer_bars,
                "max_provider_calls": settings.scheduler_us_intraday_materializer_max_provider_calls,
                "max_external_calls": settings.scheduler_us_intraday_materializer_max_external_calls,
                "equity_lane": {
                    "enabled": settings.enable_us_intraday_materializer,
                    "instrument_type": "stock",
                    "max_symbols": settings.scheduler_us_intraday_materializer_max_symbols,
                    "universe_owner": (
                        "configuration+portfolio+watchlist"
                        if settings.enable_us_dynamic_equity_materializer_universe
                        else "configuration"
                    ),
                },
                "index_lane": {
                    "enabled": (
                        settings.enable_us_index_quote_materializer
                        or settings.enable_us_index_intraday_materializer
                    ),
                    "quote_enabled": settings.enable_us_index_quote_materializer,
                    "intraday_enabled": settings.enable_us_index_intraday_materializer,
                    "instrument_type": "index",
                    "capabilities": ["quote.snapshot", "intraday.bars"],
                    "configured_symbols": [
                        item.strip().upper()
                        for item in settings.scheduler_us_index_quote_symbols.split(",")
                        if item.strip()
                    ][: settings.scheduler_us_index_quote_max_symbols],
                    "max_symbols": settings.scheduler_us_index_quote_max_symbols,
                    "max_external_calls": settings.scheduler_us_index_quote_max_external_calls,
                    "intraday_interval_seconds": settings.scheduler_us_index_intraday_materializer_interval_seconds,
                    "intraday_bars": settings.scheduler_us_index_intraday_materializer_bars,
                    "intraday_max_external_calls": settings.scheduler_us_index_intraday_max_external_calls,
                },
                "freshness_contract": {
                    "quote_basis": "fetched_time",
                    "intraday_basis": "event_time",
                    "producer_refresh_due_seconds": US_RECURRING_MATERIALIZER_PROFILE.producer_refresh_due_seconds,
                    "consumer_stale_after_seconds": US_RECURRING_MATERIALIZER_PROFILE.consumer_stale_after_seconds,
                },
                "retention_enabled": settings.enable_us_quote_retention_scheduler,
                "retention_days": settings.us_quote_snapshot_retention_days,
                **us_intraday_materializer_runtime_summary(),
            },
            "us_index_data_repair_gate": {
                "enabled": settings.enable_us_index_data_repair_gate,
                "owner": "scheduler_control_plane",
                "symbols": list(PRIORITY_US_INDEX_SYMBOLS),
                "interval_minutes": (
                    settings.scheduler_us_index_data_repair_interval_minutes
                ),
                "startup_delay_seconds": (
                    settings.scheduler_us_index_data_repair_startup_delay_seconds
                ),
                "cooldown_seconds": (
                    settings.scheduler_us_index_data_repair_cooldown_seconds
                ),
                "max_attempts": (
                    settings.scheduler_us_index_data_repair_max_attempts
                ),
                "manual_attention_backoff_seconds": (
                    settings.scheduler_us_index_data_repair_manual_attention_backoff_seconds
                ),
                "max_runtime_seconds": (
                    settings.scheduler_us_index_data_repair_max_runtime_seconds
                ),
                "daily_max_external_calls": (
                    settings.scheduler_us_index_data_repair_daily_max_external_calls
                ),
                "quote_max_external_calls": (
                    settings.scheduler_us_index_data_repair_quote_max_external_calls
                ),
                **us_index_data_repair_runtime_summary(),
            },
            "fugle_realtime": fugle_health,
        },
    }


@router.get("/livez")
def liveness_check():
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "checks": {
            "process": "ok",
        },
    }


@router.get("/readyz")
def readiness_check(request: Request, db: Session = Depends(get_db)):
    runtime = getattr(request.app.state, "runtime", None)
    runtime_ready = bool(runtime is not None and getattr(runtime, "started", False))
    database_ready = False

    try:
        db.execute(text("SELECT 1")).scalar_one()
        database_ready = True
    except Exception:
        database_ready = False

    checks = {
        "runtime": "ok" if runtime_ready else "not_ready",
        "database": "ok" if database_ready else "not_ready",
    }
    ready = runtime_ready and database_ready
    payload = {
        "status": "ready" if ready else "not_ready",
        "app_name": settings.app_name,
        "checks": checks,
    }

    if ready:
        return payload

    return JSONResponse(status_code=503, content=payload)


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
    include_historical: bool = False,
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
        include_historical=include_historical,
        limit=limit,
    )
