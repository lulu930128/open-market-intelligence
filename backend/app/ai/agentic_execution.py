from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.ai import agentic_common, agentic_policy, progress_events
from app.crypto_market import service as crypto_market_service
from app.crypto_market.contract import normalize_provider as normalize_crypto_provider
from app.crypto_market.contract import normalize_symbol as normalize_crypto_symbol
from app.db.session import SessionLocal
from app.jobs import service as job_service
from app.jp_market import service as jp_market_service
from app.jp_market.sources import normalize_jp_symbol
from app.kr_market import service as kr_market_service
from app.kr_market.sources import normalize_kr_index_id, normalize_kr_symbol
from app.market import stock_selection_refresh
from app.market.cross_market import refresh as cross_market_refresh
from app.us_market import service as us_market_service
from app.us_market.daily_ohlcv_platform import refresh_us_daily_ohlcv
from app.us_market.sources import normalize_us_symbol
from app.watchlists import backfill_service as watchlist_backfill_service


ToolDefinition = agentic_policy.ToolDefinition
ALLOWED_TOOLS = agentic_policy.ALLOWED_TOOLS
BACKGROUND_TOOL_JOB_TYPE = "ai.tool_refresh"
_BACKGROUND_REFRESH_LOCK = Lock()
TW_GRANULAR_TOOL_STEPS = {
    "tw.refresh_daily_price": "daily_price",
    "tw.refresh_institutional": "institutional_trade",
    "tw.refresh_margin": "margin_trading",
    "tw.refresh_broker_branch": "broker_branch",
    "tw.refresh_shareholding": "shareholding_distribution",
    "tw.refresh_revenue": "monthly_revenue",
    "tw.refresh_financials": "financial_metrics",
}
_FAILED_RESULT_STATUSES = {
    "error",
    "failed",
    "failure",
    "timeout",
    "cancelled",
    "expired",
}
_PARTIAL_RESULT_STATUSES = {
    "partial",
    "partial_success",
    "completed_with_error",
}
_PENDING_TRANSPORT_STATUSES = {
    "background_running",
    "queued",
    "running",
}


def _background_job_request(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    providers = args.get("providers")
    if not isinstance(providers, list):
        provider = args.get("provider")
        providers = [provider] if provider else []
    normalized_target = str(
        args.get("stock_id")
        or args.get("symbol")
        or args.get("index_id")
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
    result_status = str(result.get("status") or "").strip().lower()
    operation_status = _operation_status(status, result)
    error_message = _result_error_message(result)
    if operation_status == "failed":
        job_service.fail_job(
            db,
            job_id,
            error_message=error_message or f"{tool_name} refresh failed.",
            result={
                "status": "failed",
                "tool": tool_name,
                "result_status": result_status or None,
                "error": error_message,
                "result": _compact_result(result),
            },
        )
        return
    public_status = (
        "cancelled"
        if result.get("cancelled") is True
        else "partial"
        if operation_status == "partial"
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
    if max_points <= 0:
        return []
    if len(valid_points) <= max_points:
        return valid_points

    return valid_points[-max_points:]


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
        "refreshed_count_semantics",
        "completed_count",
        "partial_count",
        "unchanged_count",
        "changed_row_count",
        "refresh_outcome",
        "current_count",
        "success_count",
        "warning_count",
        "skipped_count",
        "error_count",
        "target_date",
        "lookback_days",
        "interval",
        "requested_interval",
        "source_interval",
        "effective_interval",
        "interval_status",
        "sampling_mode",
        "original_point_count",
        "returned_point_count",
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
        "error_message",
        "failed_steps",
        "attempted_count",
        "failed_count",
        "deferred_count",
        "cooldown_source_count",
        "cooldown_seconds",
        "max_symbols",
        "max_runtime_seconds",
        "volume_unit",
        "volume_semantics",
        "volume_status",
        "trade_value_unit",
        "is_partial",
        "continuity",
        "warnings",
    )
    summary = {
        key: agentic_common._json_value(value.get(key))
        for key in keys
        if key in value
    }
    if "points" in value and isinstance(value["points"], list):
        original_point_count = len(value["points"])
        points = _compact_intraday_points(value["points"])
        source_interval = (
            value.get("source_interval")
            or value.get("interval")
        )
        requested_interval = (
            value.get("requested_interval")
            or value.get("interval")
        )
        effective_interval = (
            value.get("effective_interval")
            or source_interval
        )
        summary["original_point_count"] = original_point_count
        summary["returned_point_count"] = len(points)
        summary["sampling_mode"] = (
            value.get("sampling_mode")
            or (
                "latest_n"
                if original_point_count > len(points)
                else "complete"
            )
        )
        if source_interval is not None:
            summary["source_interval"] = source_interval
        if requested_interval is not None:
            summary["requested_interval"] = requested_interval
        if effective_interval is not None:
            summary["effective_interval"] = effective_interval
        summary["points"] = points
        if points:
            summary["latest_point"] = points[-1]
        if "point_count" not in summary:
            summary["point_count"] = len(value["points"])
    resolved_market_data = value.get("_resolved_market_data")
    if isinstance(resolved_market_data, dict):
        summary["_resolved_market_data"] = agentic_common._json_value(
            resolved_market_data
        )
    if "metrics" in value and "metric_count" not in summary and isinstance(value["metrics"], list):
        summary["metric_count"] = len(value["metrics"])
    return summary


def _result_error_message(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("error_message", "error"):
        message = str(value.get(key) or "").strip()
        if message:
            return message[:1_000]
    failed_steps = value.get("failed_steps")
    if isinstance(failed_steps, list):
        for step in failed_steps:
            if not isinstance(step, dict):
                continue
            message = str(
                step.get("error_message")
                or step.get("error")
                or ""
            ).strip()
            if message:
                return message[:1_000]
    nested_results = value.get("results")
    nested_items = (
        list(nested_results.values())
        if isinstance(nested_results, dict)
        else nested_results
        if isinstance(nested_results, list)
        else []
    )
    for item in nested_items[:20]:
        if not isinstance(item, dict):
            continue
        message = str(
            item.get("error_message")
            or item.get("error")
            or ""
        ).strip()
        if message:
            return message[:1_000]
    if str(value.get("status") or "").strip().lower() in _FAILED_RESULT_STATUSES:
        message = str(value.get("message") or "").strip()
        if message:
            return message[:1_000]
    return None


def _operation_status(transport_status: str, result: Any) -> str:
    normalized_transport = str(transport_status or "").strip().lower()
    if normalized_transport in {"error", "failed"}:
        return "failed"
    if normalized_transport == "timeout":
        return "timeout"
    if normalized_transport in _PENDING_TRANSPORT_STATUSES:
        return "pending"
    if normalized_transport in {"blocked", "skipped"}:
        return normalized_transport
    result_status = (
        str(result.get("status") or "").strip().lower()
        if isinstance(result, dict)
        else ""
    )
    if result_status in _FAILED_RESULT_STATUSES:
        return "failed"
    if result_status in _PARTIAL_RESULT_STATUSES:
        return "partial"
    if result_status == "skipped" or result_status.startswith("skipped_"):
        return "skipped"
    return "succeeded"


def _evidence_status(operation_status: str, result: Any) -> str:
    if operation_status in {"failed", "timeout", "blocked", "skipped"}:
        return "unavailable"
    if operation_status == "pending":
        return "pending"
    if operation_status == "partial":
        return "partial"
    if not isinstance(result, dict):
        return "not_evaluated"
    if isinstance(result.get("points"), list) and result.get("points"):
        return "available"
    if any(
        isinstance(result.get(key), (int, float))
        and not isinstance(result.get(key), bool)
        and result.get(key) > 0
        for key in (
            "point_count",
            "returned_point_count",
            "fetched_count",
            "refreshed_count",
            "inserted_count",
            "updated_count",
            "changed_row_count",
        )
    ):
        return "available"
    return "not_evaluated"


def _empty_tool_run(
    *,
    step: dict[str, Any],
    definition: ToolDefinition | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    now = agentic_common._now().isoformat()
    operation_status = _operation_status(status, {})
    return {
        "tool": step.get("tool"),
        "status": status,
        "transport_status": status,
        "operation_status": operation_status,
        "evidence_status": _evidence_status(operation_status, {}),
        "result_status": None,
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
    crypto_symbol = normalize_crypto_symbol(args.get("symbol"))
    crypto_provider = normalize_crypto_provider(args.get("provider"))
    stock_id = str(args.get("stock_id") or "").strip()
    group_id_text = str(args.get("group_id") or "").strip()
    if (
        tool_name == "tw.refresh_stock_evidence"
        or tool_name in TW_GRANULAR_TOOL_STEPS
    ) and not stock_id:
        raise ValueError("stock_id is required for Taiwan stock tools.")
    if tool_name == "tw.refresh_watchlist_evidence" and not group_id_text:
        raise ValueError("group_id is required for Taiwan watchlist tools.")
    if tool_name == "cross_market.refresh_context" and not stock_id:
        raise ValueError("stock_id is required for cross-market refresh tools.")

    if tool_name.startswith("us.") and not symbol and tool_name != "us.refresh_macro_series":
        raise ValueError("symbol is required for US stock tools.")
    if tool_name.startswith("jp.") and not str(args.get("symbol") or "").strip():
        raise ValueError("symbol is required for Japan market tools.")
    if (
        tool_name in {"kr.read_stock_intraday_trend", "kr.refresh_daily_price"}
        and not str(args.get("symbol") or "").strip()
    ):
        raise ValueError("symbol is required for Korea stock tools.")
    if (
        tool_name
        in {"kr.read_index_intraday_trend", "kr.refresh_index_daily_price"}
        and not str(args.get("index_id") or "").strip()
    ):
        raise ValueError("index_id is required for Korea index tools.")
    if tool_name.startswith("crypto.") and (not crypto_symbol or not crypto_provider):
        raise ValueError("provider and symbol are required for crypto refresh tools.")

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

    if tool_name in TW_GRANULAR_TOOL_STEPS:
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
            steps=(TW_GRANULAR_TOOL_STEPS[tool_name],),
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

    if tool_name == "cross_market.refresh_context":
        return cross_market_refresh.refresh_cross_market_context_sources(
            db,
            [stock_id],
            max_symbols=agentic_common._safe_int(
                args.get("max_symbols"),
                default=8,
                minimum=1,
                maximum=8,
            ),
            provider=str(args.get("provider") or "auto"),
            outputsize=str(args.get("outputsize") or "compact"),
            max_runtime_seconds=agentic_common._safe_int(
                args.get("max_runtime_seconds"),
                default=120,
                minimum=10,
                maximum=120,
            ),
        )

    if tool_name == "us.read_intraday_trend":
        session_scope = str(args.get("session_scope") or "regular").strip().lower()
        if session_scope not in {"regular", "extended", "all"}:
            session_scope = "regular"
        interval = str(
            args.get("interval") or args.get("intraday_interval") or "1m"
        ).strip().lower()
        if interval not in {"1m", "5m", "15m", "30m", "1h", "4h"}:
            interval = "1m"
        return us_market_service.get_us_intraday_trend(
            symbol=symbol,
            session_scope=session_scope,
            interval=interval,
            db=db,
            persist_history=False,
        )

    if tool_name == "us.refresh_daily_price":
        return refresh_us_daily_ohlcv(
            db=db,
            symbol=symbol,
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

    if tool_name == "us.refresh_insider_transactions":
        return us_market_service.refresh_us_sec_insider_transactions(
            db=db,
            symbol=symbol,
            max_filings=agentic_common._safe_int(
                args.get("max_filings"),
                default=50,
                minimum=1,
                maximum=100,
            ),
        )

    if tool_name == "us.read_sec_fundamentals":
        return {
            "financial_contract": us_market_service.get_us_sec_financial_contract(
                db=db,
                symbol=symbol,
                periods=8,
            ),
            "sec_fundamentals": us_market_service.get_us_sec_fundamental_summary(
                db=db,
                symbol=symbol,
            ),
            "currency": "USD",
            "source_amount_unit": "USD",
            "normalized_amount_unit": "USD",
            "amount_scale": 1,
            "ratio_unit": "percent",
            "per_share_unit": "USD/share",
        }

    if tool_name == "us.refresh_corporate_actions":
        return us_market_service.refresh_us_corporate_actions_from_alphavantage(
            db=db,
            symbol=symbol,
        )

    if tool_name == "jp.read_intraday_trend":
        return jp_market_service.get_jp_intraday_trend(
            symbol=normalize_jp_symbol(str(args.get("symbol") or "")),
            db=db,
            refresh=True,
        )

    if tool_name == "jp.refresh_daily_price":
        return jp_market_service.refresh_jp_daily_prices(
            db=db,
            symbol=normalize_jp_symbol(str(args.get("symbol") or "")),
            provider=str(args.get("provider") or "auto"),
            outputsize=str(args.get("outputsize") or "compact"),
        )

    if tool_name == "kr.read_stock_intraday_trend":
        return kr_market_service.get_kr_stock_intraday_trend(
            db=db,
            symbol=normalize_kr_symbol(str(args.get("symbol") or "")),
            refresh=True,
        )

    if tool_name == "kr.read_index_intraday_trend":
        return kr_market_service.get_kr_index_intraday_trend(
            db=db,
            index_id=normalize_kr_index_id(str(args.get("index_id") or "")),
            refresh=True,
        )

    if tool_name == "kr.refresh_daily_price":
        return kr_market_service.refresh_kr_daily_prices(
            db=db,
            symbol=normalize_kr_symbol(str(args.get("symbol") or "")),
            provider=str(args.get("provider") or "auto"),
            outputsize=str(args.get("outputsize") or "compact"),
        )

    if tool_name == "kr.refresh_index_daily_price":
        return kr_market_service.refresh_kr_index_daily_prices(
            db=db,
            index_id=normalize_kr_index_id(str(args.get("index_id") or "")),
            outputsize=str(args.get("outputsize") or "compact"),
        )

    if tool_name == "crypto.refresh_ticker":
        return crypto_market_service.refresh_crypto_tickers(
            db=db,
            providers=[crypto_provider],
            symbols=[crypto_symbol],
        )

    if tool_name == "crypto.refresh_order_book":
        return crypto_market_service.refresh_crypto_order_books(
            db=db,
            providers=[crypto_provider],
            symbols=[crypto_symbol],
            depth_limit=agentic_common._safe_int(
                args.get("depth_limit"),
                default=5,
                minimum=1,
                maximum=20,
            ),
        )

    if tool_name == "crypto.refresh_ohlcv":
        return crypto_market_service.refresh_crypto_ohlcv(
            db=db,
            providers=[crypto_provider],
            symbols=[crypto_symbol],
            interval=str(args.get("interval") or "1m"),
            limit=agentic_common._safe_int(
                args.get("limit"),
                default=20,
                minimum=1,
                maximum=100,
            ),
        )

    if tool_name == "crypto.refresh_derivatives":
        return crypto_market_service.refresh_crypto_derivatives(
            db=db,
            providers=[crypto_provider],
            symbols=[crypto_symbol],
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
                    "status_url": f"/api/ai/refresh-status/{job.id}",
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
                "status_url": f"/api/ai/refresh-status/{job.id}",
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
                        "transport_status": "background_running",
                        "operation_status": "pending",
                        "evidence_status": "pending",
                        "result_status": None,
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
                            "status_url": (
                                "/api/ai/refresh-status/"
                                f"{existing_background_job.id}"
                            ),
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
        result_status = str(result.get("status") or "").strip().lower() or None
        operation_status = _operation_status(status, result)
        evidence_status = _evidence_status(operation_status, result)
        operation_error = error or (
            _result_error_message(result)
            if operation_status in {"failed", "partial"}
            else None
        )
        run = {
            "tool": tool_name,
            "status": status,
            "transport_status": status,
            "operation_status": operation_status,
            "evidence_status": evidence_status,
            "result_status": result_status,
            "reason": step.get("reason"),
            "arguments": args,
            "external_fetch": definition.external_fetch,
            "writes_cache": definition.writes_cache,
            "writes_market_cache": definition.writes_cache,
            "writes_user_data": False,
            "result_summary": _compact_result(result),
            "error": operation_error,
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
        elif tool_name == "cross_market.refresh_context" and operation_status in {
            "partial",
            "failed",
        }:
            warning = (
                "Cross-market refresh was incomplete; OMI kept the local cached context "
                "and its stale or missing limitations visible."
            )
            if operation_error:
                warning += f" Error: {operation_error}"
            warnings.append(warning)
        _emit_tool_progress(
            progress_callback,
            tool_name=tool_name,
            status=(
                "error"
                if operation_status == "failed"
                else "success"
                if operation_status == "partial"
                else status
            ),
            reason=step.get("reason"),
            external_fetch=definition.external_fetch,
            writes_cache=definition.writes_cache,
            error=operation_error,
            duration_ms=duration_ms,
        )

    return runs, warnings
