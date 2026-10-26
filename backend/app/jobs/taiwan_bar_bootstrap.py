"""Tracked explicit commands for bounded Taiwan canonical Bar bootstrap."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as job_service
from app.jobs.owner_continuation import owner_continuation_arguments
from app.utils.owner_checkpoint import OwnerWork, OwnerOutcomeUnknown
from app.jobs.taiwan_intraday_demand import enqueue_consumer_demand, enqueue_intraday_materialization_demand
from app.jobs.job_types import (
    TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
    TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
)
from app.market.tw_index_daily_platform import (
    TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    bootstrap_taiex_official_daily_history,
    bootstrap_tpex_completed_derived_daily_history,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.tw_bar_contracts import TaiwanCurrentSessionSnapshotPhase
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_intraday_universe import resolve_taiwan_tier_a_target_plan


def _normalize_symbols(symbols: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value or "").strip().upper()
            for value in symbols
            if str(value or "").strip()
        )
    )


def run_taiwan_intraday_bar_bootstrap_job(
    job_id: int,
    symbols: tuple[str, ...],
    max_symbols: int,
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        continuation_args = owner_continuation_arguments(db, "tw_bootstrap_children")
        progress(0, max_symbols, "Running bounded Taiwan Base-1m bootstrap.")
        plan = resolve_taiwan_tier_a_target_plan(db, operation_profile="production_intraday",
            max_symbols=max_symbols, configured_symbols=symbols or None)
        requested_at = datetime.now(TAIWAN_TZ)
        target_date = taiwan_presentation_session(requested_at)["trade_date"].isoformat()
        items = list(plan.get("symbols") or [])
        work = OwnerWork("tw_bootstrap_children",
            dict(contract="tw.bootstrap.parent.v1", date=target_date, release=target_date,
                universe=items, budget=dict(symbols=max_symbols, calls=0, runtime=180, attempts=0),
                options=[list(symbols), max_symbols]), items, **continuation_args,
            context={"requested_at": requested_at.isoformat(), "target_plan": plan})
        requested_at = datetime.fromisoformat(work.state["context"]["requested_at"])
        work.notify("save")
        work.notify("checkpoint")
        for symbol in work.state["items"][len(work.state["results"]):]:
            if datetime.now(TAIWAN_TZ) >= requested_at + timedelta(seconds=180):
                break
            work.begin(0)
            try:
                child, created = enqueue_intraday_materialization_demand(db, stock_id=symbol,
                    requested_at=requested_at, consumer="operator", max_external_calls=2)
            except Exception as exc:
                raise OwnerOutcomeUnknown("TW_BOOTSTRAP_CHILD_ADMISSION_UNKNOWN") from exc
            work.finish(dict(admitted=1, calls=0),
                {"symbol": symbol, "job_id": child.id if child else None,
                 "status": child.status if child else "skipped", "created": created})
            # Child admission/dispatch has returned; its own state machine owns
            # completion. A crash in the admission gap leaves inflight blocked.
            work.notify("save")
            work.notify("checkpoint")
        results = []
        for entry in work.state["results"]:
            item = dict(entry["outcome"])
            child = db.get(JobRun, item["job_id"], populate_existing=True) if item["job_id"] is not None else None
            item["status"] = child.status if child else "skipped"
            results.append(item)
        # The compatibility parent records fan-out, never claims child coverage.
        payload = {"status": "pending", "results": results, "target_plan": work.state["context"]["target_plan"],
                   "owner_continuation_v1": work.state,
                   "remaining_symbols": work.state["items"][len(results):],
                   "admitted_count": len(results),
                   "children_completed_count": sum(item["status"] == "success" for item in results),
                   "postcondition_met": bool(results) and len(results) == len(work.state["items"])
                       and all(item["status"] == "success" for item in results)}
        if payload["postcondition_met"]:
            payload["status"] = "success"
        progress(
            len(results),
            max_symbols,
            "Taiwan Base-1m child admission finished; coverage follows child outcomes.",
        )
        if not payload["postcondition_met"]:
            raise job_service.JobExecutionError(
                "Taiwan Base-1m bootstrap did not satisfy its postcondition.",
                result=payload,
            )
        return payload

    job_service.run_tracked_job(job_id, worker)


def enqueue_taiwan_intraday_bar_bootstrap(
    db: Session,
    *,
    symbols: list[str] | tuple[str, ...] = (),
    max_symbols: int = 10,
    reuse_success_within_seconds: float = 0,
) -> tuple[JobRun, bool]:
    if max_symbols < 1 or max_symbols > 10:
        raise ValueError("Taiwan intraday bootstrap max_symbols must be between 1 and 10")
    normalized = _normalize_symbols(symbols)
    if len(normalized) > max_symbols:
        raise ValueError("requested symbols exceed Taiwan intraday bootstrap max_symbols")
    target_material = f"symbols={','.join(normalized) or 'tier-a'}|max={max_symbols}"
    target = "tw_intraday:" + hashlib.sha256(
        target_material.encode("utf-8")
    ).hexdigest()[:20]
    active = job_service.find_active_job_by_target(
        db,
        TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {"symbols": list(normalized), "max_symbols": max_symbols}
    return job_service.enqueue_job(
        db=db,
        job_type=TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
        target=target,
        request=request,
        progress_total=max_symbols,
        message="Queued bounded Taiwan Base-1m bootstrap.",
        task=run_taiwan_intraday_bar_bootstrap_job,
        task_args=(normalized, max_symbols),
        reuse_success_within_seconds=reuse_success_within_seconds,
    )


def enqueue_taiwan_intraday_viewer_warmup(
    db: Session,
    stock_id: str,
    requested_at: datetime,
) -> tuple[JobRun | None, bool]:
    """Signal one bounded baseline warmup from a viewer command boundary."""

    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("Taiwan viewer warmup requested_at must be timezone-aware")
    local_now = requested_at.astimezone(TAIWAN_TZ)
    target_date = taiwan_presentation_session(local_now)["trade_date"]
    if target_date == local_now.date() and local_now < datetime.combine(target_date, time(9), tzinfo=TAIWAN_TZ):
        return None, False
    coverage = TaiwanBarService(db).read_current_session_bars(
        instrument_id=stock_id,
        interval="1m",
        limit=1,
        requested_at=local_now,
    ).current_session_coverage
    if (
        coverage is None
        or (
            coverage.snapshot_phase is not TaiwanCurrentSessionSnapshotPhase.WARMING
            and not (
                coverage.snapshot_phase is TaiwanCurrentSessionSnapshotPhase.DEGRADED
                and coverage.repair_recommended
            )
        )
    ):
        return None, False

    return enqueue_consumer_demand(
        db, stock_id=stock_id, requested_at=local_now, consumer="viewer",
    )


def run_taiwan_index_daily_bootstrap_job(
    job_id: int,
    index_ids: tuple[str, ...],
    date_from: date,
    date_to: date,
    taiex_max_sessions: int,
    tpex_max_sessions: int,
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        progress(0, len(index_ids), "Running bounded Taiwan index Base-1d bootstrap.")
        results: list[dict] = []
        for index_id in index_ids:
            result = (
                bootstrap_taiex_official_daily_history(
                    db,
                    date_from=date_from,
                    date_to=date_to,
                    max_sessions=taiex_max_sessions,
                )
                if index_id == "TAIEX"
                else bootstrap_tpex_completed_derived_daily_history(
                    db,
                    date_from=date_from,
                    date_to=date_to,
                    max_sessions=tpex_max_sessions,
                )
            )
            results.append(result)
            progress(
                len(results),
                len(index_ids),
                f"Taiwan {index_id} Base-1d bootstrap finished.",
            )
        status = (
            "success"
            if results and all(item.get("status") == "success" for item in results)
            else "partial"
            if any(item.get("status") in {"success", "partial"} for item in results)
            else "failed"
        )
        payload = {
            "contract_version": "tw.index_daily.bootstrap_job.v1",
            "status": status,
            "results": results,
        }
        if status != "success":
            raise job_service.JobExecutionError(
                "Taiwan index Base-1d bootstrap did not satisfy its postcondition.",
                result=payload,
            )
        return payload

    job_service.run_tracked_job(job_id, worker)


def enqueue_taiwan_index_daily_bootstrap(
    db: Session,
    *,
    index_ids: list[str] | tuple[str, ...],
    date_from: date,
    date_to: date,
    taiex_max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    tpex_max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
) -> tuple[JobRun, bool]:
    normalized = tuple(
        dict.fromkeys(str(value or "").strip().upper() for value in index_ids)
    )
    if not normalized or any(value not in {"TAIEX", "TPEX"} for value in normalized):
        raise ValueError("Taiwan index bootstrap supports only TAIEX and TPEX")
    if date_from > date_to:
        raise ValueError("Taiwan index bootstrap date_from must not exceed date_to")
    if not (
        1
        <= taiex_max_sessions
        <= TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("taiex_max_sessions must be between 1 and 300")
    if not (
        1
        <= tpex_max_sessions
        <= TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("tpex_max_sessions must be between 1 and 300")
    material = (
        f"ids={','.join(normalized)}|from={date_from}|to={date_to}|"
        f"taiex={taiex_max_sessions}|tpex={tpex_max_sessions}"
    )
    target = "tw_index_daily:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    active = job_service.find_active_job_by_target(
        db,
        TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {
        "index_ids": list(normalized),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "taiex_max_sessions": taiex_max_sessions,
        "tpex_max_sessions": tpex_max_sessions,
    }
    return job_service.enqueue_job(
        db=db,
        job_type=TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
        target=target,
        request=request,
        progress_total=len(normalized),
        message="Queued bounded Taiwan index Base-1d bootstrap.",
        task=run_taiwan_index_daily_bootstrap_job,
        task_args=(
            normalized,
            date_from,
            date_to,
            taiex_max_sessions,
            tpex_max_sessions,
        ),
    )
__all__ = [
    "TAIWAN_VIEWER_WARMUP_SUCCESS_REUSE_SECONDS",
    "enqueue_taiwan_index_daily_bootstrap",
    "enqueue_taiwan_intraday_bar_bootstrap",
    "enqueue_taiwan_intraday_viewer_warmup",
    "run_taiwan_index_daily_bootstrap_job",
    "run_taiwan_intraday_bar_bootstrap_job",
]
