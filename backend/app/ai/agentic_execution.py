from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.ai import agentic_common, agentic_policy, progress_events
from app.db.session import SessionLocal
from app.jobs import service as job_service
from app.market import stock_selection_refresh
from app.us_market import service as us_market_service
from app.us_market.sources import normalize_us_symbol
from app.watchlists import backfill_service as watchlist_backfill_service


ToolDefinition = agentic_policy.ToolDefinition
ALLOWED_TOOLS = agentic_policy.ALLOWED_TOOLS
BACKGROUND_TOOL_JOB_TYPE = "ai.tool_refresh"
_BACKGROUND_REFRESH_LOCK = Lock()


def _background_job_request(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    providers = args.get("providers")
    if not isinstance(providers, list):
        provider = args.get("provider")
        providers = [provider] if provider else []
    normalized_target = str(
        args.get("stock_id")
        or args.get("symbol")
        or args.get("group_id")
        or ""
    ).strip().upper()
    requested_capabilities = args.get("requested_capabilities")
    if not isinstance(requested_capabilities, list):
        requested_capabilities = []
    return {
        "normalized_target": normalized_target,
        "refresh_profile": str(
            args.get("profile") or args.get("outputsize") or "default"
        ).strip().lower(),
        "provider_set": sorted(
            {str(provider).strip().lower() for provider in providers if str(provider).strip()}
        ),
        "date_range": {
            "from": args.get("from_date") or args.get("start_date"),
            "to": args.get("to_date") or args.get("end_date"),
        },
        "include_today": args.get("include_today"),
        "requested_capabilities": sorted(
            {
                tool_name,
                *(
                    str(capability).strip()
                    for capability in requested_capabilities
                    if str(capability).strip()
                ),
            }
        ),
    }


def _public_job_status(job: Any) -> str:
    serialized = job_service.serialize_job(job)
    result = serialized.get("result") if isinstance(serialized.get("result"), dict) else {}
    result_status = str(result.get("status") or "").strip().lower()
    if result_status in {"completed", "partial", "failed", "cancelled", "expired"}:
        return result_status
    return {
        "queued": "queued",
        "running": "running",
        "success": "completed",
        "error": "failed",
    }.get(str(job.status), str(job.status))


def _finish_background_job_in_session(
    db: Session,
    job_id: int,
    *,
    tool_name: str,
    status: str,
    value: Any,
) -> None:
    if status == "error":
        job_service.fail_job(
            db,
            job_id,
            error_message=str(value),
            result={"status": "failed", "tool": tool_name, "error": str(value)},
        )
        return
    result = value if isinstance(value, dict) else {}
    public_status = (
        "cancelled"
        if result.get("cancelled") is True
        else "partial"
        if str(result.get("status") or "").lower() in {"partial", "partial_success"}
        else "completed"
    )
    job_service.complete_job(
        db,
        job_id,
        result={
            "status": public_status,
            "tool": tool_name,
            "result": _compact_result(result),
        },
        message=f"Detached {tool_name} finished with status {public_status}.",
    )


def _finish_background_job(
    job_id: int,
    *,
    tool_name: str,
    status: str,
    value: Any,
    session_factory: sessionmaker | None = None,
) -> None:
    db = (session_factory or SessionLocal)()
    try:
        _finish_background_job_in_session(
            db,
            job_id,
            tool_name=tool_name,
            status=status,
            value=value,
        )
    finally:
        db.close()


def _emit_tool_progress(
    progress_callback: progress_events.ProgressCallback | None,
    *,
    tool_name: str,
    status: str,
    reason: Any = None,
    external_fetch: bool | None = None,
    writes_cache: bool | None = None,
    error: Any = None,
    duration_ms: int | None = None,
) -> None:
    status_text = {
        "running": "執行中",
        "success": "已完成",
        "blocked": "已阻擋",
        "skipped": "已略過",
        "error": "失敗",
        "timeout": "逾時",
    }.get(status, status)
    progress_events.emit_progress(
        progress_callback,
        stage="tool_execution",
        message=f"{tool_name} {status_text}。",
        phase={
            "running": "running",
            "success": "completed",
            "blocked": "blocked",
            "skipped": "skipped",
            "error": "failed",
            "timeout": "failed",
        }.get(status, "completed"),
        dedupe_key=f"tool:{tool_name}:{status}",
        tool=tool_name,
        status=status,
        reason=reason,
        external_fetch=external_fetch,
        writes_cache=writes_cache,
        error=str(error) if error else None,
        duration_ms=duration_ms,
    )


def _compact_intraday_points(
    points: list[Any],
    *,
    max_points: int = 80,
) -> list[dict[str, Any]]:
    valid_points = [agentic_common._json_ready(point) for point in points if isinstance(point, dict)]
    valid_points = [point for point in valid_points if isinstance(point, dict)]
    if len(valid_points) <= max_points:
        return valid_points

    last_index = len(valid_points) - 1
    indexes = {round(index * last_index / (max_points - 1)) for index in range(max_points)}
    return [valid_points[index] for index in sorted(indexes)]


def _compact_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"value": agentic_common._json_value(value)}

    keys = (
        "status",
        "provider",
        "symbol",
        "stock_id",
        "series_id",
        "trade_date",
        "daily_price_date",
        "institutional_trade_date",
        "margin_trade_date",
        "fetched_count",
        "inserted_count",
        "updated_count",
        "requested_count",
        "requested_stock_count",
        "refreshed_count",
        "current_count",
        "success_count",
        "warning_count",
        "skipped_count",
        "error_count",
        "target_date",
        "lookback_days",
        "point_count",
        "previous_close",
        "previous_close_source",
        "previous_close_trade_date",
        "previous_close_provider",
        "session_scope",
        "session_phase",
        "has_extended_hours",
        "regular_point_count",
        "extended_point_count",
        "regular_session_close",
        "regular_session_close_time",
        "source",
        "source_url",
        "metric_count",
        "message",
    )
    summary = {
        key: agentic_common._json_value(value.get(key))
        for key in keys
        if key in value
    }
    if "points" in value and isinstance(value["points"], list):
        points = _compact_intraday_points(value["points"])
        summary["returned_point_count"] = len(points)
        summary["points"] = points
        if points:
            summary["latest_point"] = points[-1]
        if "point_count" not in summary:
            summary["point_count"] = len(value["points"])
    if "metrics" in value and "metric_count" not in summary and isinstance(value["metrics"], list):
        summary["metric_count"] = len(value["metrics"])
    return summary


def _empty_tool_run(
    *,
    step: dict[str, Any],
    definition: ToolDefinition | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    now = agentic_common._now().isoformat()
    return {
        "tool": step.get("tool"),
        "status": status,
        "reason": step.get("reason"),
        "arguments": step.get("args") or {},
        "external_fetch": bool(definition.external_fetch) if definition else False,
        "writes_cache": bool(definition.writes_cache) if definition else False,
        "writes_market_cache": bool(definition.writes_cache) if definition else False,
        "writes_user_data": False,
        "result_summary": {},
        "error": error,
        "started_at": now,
        "ended_at": now,
        "duration_ms": 0,
    }


def _execute_tool(
    db: Session,
    tool_name: str,
    args: dict[str, Any],
    *,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    symbol = normalize_us_symbol(args.get("symbol"))
    stock_id = str(args.get("stock_id") or "").strip()
    group_id_text = str(args.get("group_id") or "").strip()
    if tool_name == "tw.refresh_stock_evidence" and not stock_id:
        raise ValueError("stock_id is required for Taiwan stock tools.")
    if tool_name == "tw.refresh_watchlist_evidence" and not group_id_text:
        raise ValueError("group_id is required for Taiwan watchlist tools.")

    if tool_name.startswith("us.") and not symbol and tool_name != "us.refresh_macro_series":
        raise ValueError("symbol is required for US stock tools.")

    if tool_name == "tw.refresh_stock_evidence":
        sleep_seconds = agentic_common._safe_float(
            args.get("sleep_seconds"),
            default=0.05,
            minimum=0.0,
            maximum=3.0,
        )
        return stock_selection_refresh.refresh_selected_stock_data(
            db=db,
            stock_id=stock_id,
            include_today=agentic_common._optional_bool(args.get("include_today")),
            sleep_seconds=sleep_seconds,
            should_cancel=cancel_event.is_set if cancel_event is not None else None,
        )

    if tool_name == "tw.refresh_watchlist_evidence":
        sleep_seconds = agentic_common._safe_float(
            args.get("sleep_seconds"),
            default=0.05,
            minimum=0.0,
            maximum=3.0,
        )
        lookback_days = agentic_common._safe_int(
            args.get("lookback_days"),
            default=14,
            minimum=1,
            maximum=365,
        )
        include_today = agentic_common._optional_bool(args.get("include_today"))
        include_children = agentic_common._optional_bool(args.get("include_children"))
        enabled_only = agentic_common._optional_bool(args.get("enabled_only"))
        skip_existing_months = agentic_common._optional_bool(args.get("skip_existing_months"))
        return watchlist_backfill_service.refresh_watchlist_group_daily_prices(
            db=db,
            group_id=int(group_id_text),
            lookback_days=lookback_days,
            include_today=include_today if include_today is not None else False,
            include_children=include_children if include_children is not None else True,
            enabled_only=enabled_only if enabled_only is not None else True,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months if skip_existing_months is not None else True,
            should_cancel=cancel_event.is_set if cancel_event is not None else None,
        )

    if tool_name == "us.read_intraday_trend":
        return us_market_service.get_us_intraday_trend(symbol=symbol, db=db)

    if tool_name == "us.refresh_daily_price":
        return us_market_service.refresh_us_daily_prices(
            db=db,
            symbol=symbol,
            provider=str(args.get("provider") or "auto"),
            outputsize=str(args.get("outputsize") or "compact"),
            adjusted=bool(args.get("adjusted", False)),
        )

    if tool_name == "us.refresh_company_profile":
        return us_market_service.refresh_us_company_profile_from_alphavantage(
            db=db,
            symbol=symbol,
        )

    if tool_name == "us.refresh_sec_facts":
        return us_market_service.refresh_us_sec_companyfacts(db=db, symbol=symbol)

    if tool_name == "us.read_sec_fundamentals":
        return us_market_service.get_us_sec_fundamental_summary(db=db, symbol=symbol)

    if tool_name == "us.refresh_corporate_actions":
        return us_market_service.refresh_us_corporate_actions_from_alphavantage(
            db=db,
            symbol=symbol,
        )

    raise ValueError(f"Unsupported OMI tool: {tool_name}")


def _worker_session(db: Session) -> tuple[Session, bool]:
    bind = db.get_bind()
    database = str(getattr(getattr(bind, "url", None), "database", "") or "")
    if database in {"", ":memory:"}:
        return db, False
    return sessionmaker(autocommit=False, autoflush=False, bind=bind)(), True


def _execute_tool_with_deadline(
    *,
    db: Session,
    tool_name: str,
    args: dict[str, Any],
    timeout_seconds: float,
    tracking_job_id: int | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    outcome: Queue[tuple[str, Any]] = Queue(maxsize=1)
    cancel_event = Event()
    tracking_lock = Lock()
    tracking: dict[str, Any] = {
        "job_id": tracking_job_id,
        "done": False,
        "status": None,
        "value": None,
    }
    bind = db.get_bind()
    database = str(getattr(getattr(bind, "url", None), "database", "") or "")
    finish_in_worker = database not in {"", ":memory:"}
    finish_session_factory = (
        sessionmaker(autocommit=False, autoflush=False, bind=bind)
        if finish_in_worker
        else None
    )

    def worker() -> None:
        worker_db: Session | None = None
        owns_session = False
        try:
            worker_db, owns_session = _worker_session(db)
            result = _execute_tool(
                worker_db,
                tool_name,
                args,
                cancel_event=cancel_event,
            )
            outcome.put(("success", result))
            worker_status = "success"
            worker_value = result
        except Exception as exc:
            outcome.put(("error", str(exc)))
            worker_status = "error"
            worker_value = str(exc)
        finally:
            if owns_session and worker_db is not None:
                worker_db.close()
        with tracking_lock:
            tracking["done"] = True
            tracking["status"] = worker_status
            tracking["value"] = worker_value
            job_id = tracking.get("job_id")
        if isinstance(job_id, int) and finish_session_factory is not None:
            _finish_background_job(
                job_id,
                tool_name=tool_name,
                status=worker_status,
                value=worker_value,
                session_factory=finish_session_factory,
            )

    thread = Thread(target=worker, name=f"omi-tool-{tool_name}", daemon=True)
    thread.start()
    thread.join(max(0.0, timeout_seconds))
    if thread.is_alive():
        cancel_event.set()
        job_ref: dict[str, Any] = {}
        request = _background_job_request(tool_name, args)
        target = str(request.get("normalized_target") or "") or None
        try:
            if isinstance(tracking_job_id, int):
                job = job_service.get_job(db, tracking_job_id)
                job_ref = {
                    "job_id": job.id,
                    "status": _public_job_status(job),
                    "deduplicated": False,
                    "poll_url": f"/api/jobs/{job.id}",
                }
                return {
                    "__background_job": job_ref,
                }, "timeout", f"Tool exceeded the remaining wall-clock budget ({timeout_seconds:.2f}s)."
            existing = job_service.find_active_job(
                db,
                job_type=BACKGROUND_TOOL_JOB_TYPE,
                target=target,
                request=request,
            )
            job = existing or job_service.create_job(
                db,
                job_type=BACKGROUND_TOOL_JOB_TYPE,
                target=target,
                request=request,
                progress_total=1,
                message=f"Detached {tool_name} continues after request deadline.",
            )
            if existing is None:
                job_service.start_job(
                    db,
                    job.id,
                    message=f"Detached {tool_name} is running.",
                )
                db.refresh(job)
            with tracking_lock:
                if existing is None:
                    tracking["job_id"] = job.id
                already_done = bool(tracking.get("done"))
                completed_status = str(tracking.get("status") or "error")
                completed_value = tracking.get("value")
            if already_done and existing is None:
                if finish_session_factory is None:
                    _finish_background_job_in_session(
                        db,
                        job.id,
                        tool_name=tool_name,
                        status=completed_status,
                        value=completed_value,
                    )
                else:
                    _finish_background_job(
                        job.id,
                        tool_name=tool_name,
                        status=completed_status,
                        value=completed_value,
                        session_factory=finish_session_factory,
                    )
                db.refresh(job)
            job_ref = {
                "job_id": job.id,
                "status": _public_job_status(job),
                "deduplicated": existing is not None,
                "poll_url": f"/api/jobs/{job.id}",
            }
        except Exception as exc:
            job_ref = {
                "status": "untracked",
                "tracking_error": str(exc),
            }
        return {
            "__background_job": job_ref,
        }, "timeout", f"Tool exceeded the remaining wall-clock budget ({timeout_seconds:.2f}s)."

    try:
        status, value = outcome.get_nowait()
    except Empty:
        return {}, "error", "Tool worker ended without returning a result."
    if isinstance(tracking_job_id, int) and finish_session_factory is None:
        _finish_background_job_in_session(
            db,
            tracking_job_id,
            tool_name=tool_name,
            status=status,
            value=value,
        )
    if status == "error":
        return {}, "error", str(value)
    return value if isinstance(value, dict) else {}, "success", None


def execute_tool_plan(
    *,
    db: Session,
    plan: dict[str, Any],
    budget: dict[str, int],
    can_external_fetch: bool,
    fallback_to_cached: bool = True,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    external_fetches = 0
    started = perf_counter()

    for step in plan.get("tool_plan") or []:
        if len(runs) >= budget["max_calls"]:
            warnings.append("OMI tool budget reached max_calls; remaining planned tools were skipped.")
            break

        if not isinstance(step, dict):
            continue

        tool_name = str(step.get("tool") or "").strip()
        definition = ALLOWED_TOOLS.get(tool_name)
        if definition is None:
            run = _empty_tool_run(
                step=step,
                definition=None,
                status="skipped",
                error=f"Tool is not in OMI allowlist: {tool_name}",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name or "unknown",
                status="skipped",
                reason=step.get("reason"),
                error=run.get("error"),
            )
            continue

        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        key = (
            tool_name,
            tuple(sorted((str(k), str(v)) for k, v in args.items())),
        )
        if key in seen:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="skipped",
                error="Duplicate tool call skipped.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="skipped",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue
        seen.add(key)

        if definition.external_fetch and not can_external_fetch:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="blocked",
                error="External fetch is not allowed by request/server policy.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="blocked",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue

        if definition.external_fetch and external_fetches >= budget["max_external_fetches"]:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="skipped",
                error="External fetch budget reached.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="skipped",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue

        elapsed_seconds = perf_counter() - started
        if elapsed_seconds >= budget["max_total_seconds"]:
            warnings.append(
                "OMI tool budget reached max_total_seconds; remaining planned tools were skipped."
            )
            break

        tracking_job_id: int | None = None
        if definition.external_fetch:
            background_request = _background_job_request(tool_name, args)
            background_target = str(
                background_request.get("normalized_target") or ""
            ) or None
            with _BACKGROUND_REFRESH_LOCK:
                existing_background_job = job_service.find_active_job(
                    db,
                    job_type=BACKGROUND_TOOL_JOB_TYPE,
                    target=background_target,
                    request=background_request,
                )
                if existing_background_job is None:
                    new_background_job = job_service.create_job(
                        db,
                        job_type=BACKGROUND_TOOL_JOB_TYPE,
                        target=background_target,
                        request=background_request,
                        progress_total=1,
                        message=f"Tracked {tool_name} refresh queued.",
                    )
                    job_service.start_job(
                        db,
                        new_background_job.id,
                        message=f"Tracked {tool_name} refresh is running.",
                    )
                    tracking_job_id = new_background_job.id
            if existing_background_job is not None:
                runs.append(
                    {
                        "tool": tool_name,
                        "status": "background_running",
                        "request_status": "background_in_progress",
                        "reason": step.get("reason"),
                        "arguments": args,
                        "external_fetch": True,
                        "writes_cache": definition.writes_cache,
                        "writes_market_cache": definition.writes_cache,
                        "writes_user_data": False,
                        "result_summary": {},
                        "error": None,
                        "fallback_used": bool(fallback_to_cached),
                        "cached_data_returned": False,
                        "cancellation_requested": False,
                        "background_completion_possible": True,
                        "job": {
                            "job_id": existing_background_job.id,
                            "status": _public_job_status(existing_background_job),
                            "deduplicated": True,
                            "poll_url": f"/api/jobs/{existing_background_job.id}",
                        },
                    }
                )
                warnings.append(
                    f"{tool_name} already has an identical detached refresh job; reused the running job."
                )
                continue

        started_at = agentic_common._now()
        started_tick = perf_counter()
        if definition.external_fetch:
            external_fetches += 1

        _emit_tool_progress(
            progress_callback,
            tool_name=tool_name,
            status="running",
            reason=step.get("reason"),
            external_fetch=definition.external_fetch,
            writes_cache=definition.writes_cache,
        )
        try:
            result, status, error = _execute_tool_with_deadline(
                db=db,
                tool_name=tool_name,
                args=args,
                timeout_seconds=max(0.0, budget["max_total_seconds"] - elapsed_seconds),
                tracking_job_id=tracking_job_id,
            )
        except Exception as exc:
            result = {}
            status = "error"
            error = str(exc)
            if isinstance(tracking_job_id, int):
                try:
                    job_service.fail_job(
                        db,
                        tracking_job_id,
                        error_message=error,
                        result={"status": "failed", "tool": tool_name, "error": error},
                    )
                except Exception:
                    pass

        ended_at = agentic_common._now()
        duration_ms = int((perf_counter() - started_tick) * 1000)
        background_job = result.pop("__background_job", None)
        run = {
            "tool": tool_name,
            "status": status,
            "reason": step.get("reason"),
            "arguments": args,
            "external_fetch": definition.external_fetch,
            "writes_cache": definition.writes_cache,
            "writes_market_cache": definition.writes_cache,
            "writes_user_data": False,
            "result_summary": _compact_result(result),
            "error": error,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": duration_ms,
            "fallback_used": bool(status == "timeout" and fallback_to_cached),
            "cached_data_returned": False,
            "cancellation_requested": status == "timeout",
            "background_completion_possible": status == "timeout",
            "request_status": "deadline_exceeded" if status == "timeout" else "completed",
            "cancellation": {
                "deadline_exceeded": status == "timeout",
                "detached": status == "timeout",
                "cancel_attempted": status == "timeout",
                "cancel_confirmed": False,
                "background_completion_possible": status == "timeout",
            },
        }
        if isinstance(background_job, dict) and background_job:
            run["job"] = background_job
        runs.append(run)
        if status == "timeout":
            warnings.append(
                f"{tool_name} timed out at the OMI wall-clock deadline; "
                + (
                    "the answer will fall back to local cached evidence."
                    if fallback_to_cached
                    else "cached fallback was disabled by refresh_policy."
                )
            )
        _emit_tool_progress(
            progress_callback,
            tool_name=tool_name,
            status=status,
            reason=step.get("reason"),
            external_fetch=definition.external_fetch,
            writes_cache=definition.writes_cache,
            error=error,
            duration_ms=duration_ms,
        )

    return runs, warnings
