from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import JobRun, utc_now
from app.jobs import service as job_service
from app.market.tw_futures import (
    KGI_PROVIDER,
    TaiwanFuturesFetchError,
    resolve_taiwan_futures_quote_provider,
)


TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE = "market.tw_futures_quote_refresh"


def _target_symbols(symbols: str) -> list[str]:
    normalized = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    return normalized or ["TXF", "MXF", "TMF"]


def _quote_source_name(provider: str | None) -> str:
    if resolve_taiwan_futures_quote_provider(provider) == KGI_PROVIDER:
        return "KGI"
    return "TAIFEX MIS"


def _quote_source_error_message(
    exc: TaiwanFuturesFetchError,
    *,
    provider: str | None = None,
) -> str:
    text = str(exc)
    source_name = _quote_source_name(provider)
    if "520" in text:
        return f"{source_name} 即時報價來源暫時回應 520，已改用快取資料。"
    return f"{source_name} 即時報價暫時無法讀取，已改用快取資料。"


def record_taiwan_futures_quote_refresh_issue(
    db: Session,
    *,
    symbols: str,
    session: str,
    provider: str | None,
    exc: TaiwanFuturesFetchError,
    cached_count: int,
) -> JobRun:
    symbol_list = _target_symbols(symbols)
    target = ",".join(symbol_list)
    requested_count = max(len(symbol_list), 1)
    source_name = _quote_source_name(provider)
    resolved_provider = resolve_taiwan_futures_quote_provider(provider)
    message = _quote_source_error_message(exc, provider=provider)
    has_cache = cached_count > 0
    status_value = "partial_success" if has_cache else "error"
    if not has_cache:
        message = f"{source_name} 即時報價暫時無法讀取，且目前沒有可用快取。"

    result = {
        "status": status_value,
        "message": message,
        "requested_count": requested_count,
        "success_count": cached_count if has_cache else 0,
        "warning_count": requested_count if has_cache else 0,
        "error_count": 0 if has_cache else requested_count,
        "results": [
            {
                "symbol": symbol,
                "resource": "台指期即時報價",
                "source_name": source_name,
                "status": "partial_success" if has_cache else "error",
                "message": message,
                "error_message": message,
            }
            for symbol in symbol_list
        ],
    }

    cutoff = utc_now() - timedelta(minutes=5)
    job = (
        db.query(JobRun)
        .filter(JobRun.job_type == TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE)
        .filter(JobRun.target == target)
        .filter(JobRun.updated_at >= cutoff)
        .order_by(JobRun.updated_at.desc(), JobRun.id.desc())
        .first()
    )

    if job is None:
        job = job_service.create_job(
            db=db,
            job_type=TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE,
            target=target,
            request={
                "symbols": symbol_list,
                "session": session,
                "source": source_name,
                "provider": resolved_provider,
            },
            progress_total=requested_count,
            message="Refreshing Taiwan futures quotes.",
        )
    else:
        job = job_service.update_progress(
            db=db,
            job_id=job.id,
            current=cached_count if has_cache else 0,
            total=requested_count,
        )

    if has_cache:
        return job_service.complete_job(db=db, job_id=job.id, result=result, message=message)
    return job_service.fail_job(db=db, job_id=job.id, error_message=message, result=result)


__all__ = [
    "TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE",
    "record_taiwan_futures_quote_refresh_issue",
]
