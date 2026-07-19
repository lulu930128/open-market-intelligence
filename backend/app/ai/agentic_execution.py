from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_common, agentic_policy, progress_events
from app.market import stock_selection_refresh
from app.us_market import service as us_market_service
from app.us_market.sources import normalize_us_symbol
from app.watchlists import backfill_service as watchlist_backfill_service


ToolDefinition = agentic_policy.ToolDefinition
ALLOWED_TOOLS = agentic_policy.ALLOWED_TOOLS


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
        "result_summary": {},
        "error": error,
        "started_at": now,
        "ended_at": now,
        "duration_ms": 0,
    }


def _execute_tool(db: Session, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
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


def execute_tool_plan(
    *,
    db: Session,
    plan: dict[str, Any],
    budget: dict[str, int],
    can_external_fetch: bool,
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

        if perf_counter() - started > budget["max_total_seconds"]:
            warnings.append(
                "OMI tool budget reached max_total_seconds; remaining planned tools were skipped."
            )
            break

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
            result = _execute_tool(db, tool_name, args)
            status = "success"
            error = None
        except Exception as exc:
            result = {}
            status = "error"
            error = str(exc)

        ended_at = agentic_common._now()
        duration_ms = int((perf_counter() - started_tick) * 1000)
        run = {
            "tool": tool_name,
            "status": status,
            "reason": step.get("reason"),
            "arguments": args,
            "external_fetch": definition.external_fetch,
            "writes_cache": definition.writes_cache,
            "result_summary": _compact_result(result),
            "error": error,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": duration_ms,
        }
        runs.append(run)
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
