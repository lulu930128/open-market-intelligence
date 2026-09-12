from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Callable

from sqlalchemy.orm import Session
from app.config import settings

from app.ai.agentic_common import _json_ready, _json_value, _list_rows, _row_dict, _safe_int
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
)
from app.ai.market_context.regional_params import (
    _market_data_bool,
    _market_data_int,
    _market_data_str,
)
from app.ai.market_payload_contract import (
    annotate_intraday_bar_contract as _annotate_intraday_bar_contract,
    intraday_point_limit as _market_intraday_point_limit,
    payload_level as _market_payload_level,
    requested_intraday_interval as _requested_intraday_interval,
)
from app.db.models import JPStockMaster
from app.jp_market.sources import normalize_jp_symbol
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE
from app.market.calendar_status import build_jp_calendar_status
from app.market.intraday_aggregation import aggregate_regular_session_ohlcv
from app.jp_market.quote_projection import project_jp_intraday_reference as _jp_intraday_quote


@dataclass(frozen=True)
class JPContextDependencies:
    jp_market_service: Any
    now: Callable[[], datetime]


def _latest_tool_result(
    tool_runs: list[dict[str, Any]],
    tool_name: str,
) -> dict[str, Any] | None:
    for run in reversed(tool_runs):
        if run.get("tool") != tool_name or run.get("status") != "success":
            continue
        summary = run.get("result_summary")
        if isinstance(summary, dict):
            return summary
    return None


def _jp_intraday_latest(
    intraday_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        return None

    latest = intraday_summary.get("latest_point")
    if isinstance(latest, dict):
        return latest

    points = intraday_summary.get("points")
    if isinstance(points, list) and points and isinstance(points[-1], dict):
        return points[-1]
    return None


def _jp_intraday_compact(
    intraday_summary: dict[str, Any] | None,
    *,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _market_payload_level(market_data_params)
    point_limit = _market_intraday_point_limit(market_data_params)
    requested_interval = (
        _requested_intraday_interval(market_data_params, default="1m")
        or "1m"
    )
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        interval_status = (
            "unavailable"
            if requested_interval in {"1m", "5m"}
            else "unsupported"
        )
        return {
            "enabled": False,
            "requested_interval": requested_interval,
            "source_interval": "1m",
            "effective_interval": None,
            "interval_status": interval_status,
            "sampling_mode": "not_available",
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [
                (
                    "JP intraday trend was not requested or did not return data."
                    if interval_status == "unavailable"
                    else (
                        f"Requested JP intraday interval {requested_interval} is "
                        "unsupported; the provider contract only exposes 1m bars."
                    )
                )
            ],
        }

    raw_points = (
        intraday_summary.get("points")
        if isinstance(intraday_summary.get("points"), list)
        else []
    )
    points = [point for point in raw_points if isinstance(point, dict)]
    point_count = len(points)
    raw_latest = _jp_intraday_latest(intraday_summary)
    raw_warnings = intraday_summary.get("warnings")
    warnings = raw_warnings if isinstance(raw_warnings, list) else []
    source = intraday_summary.get("source") or (
        "yahoo_finance_chart" if raw_latest or point_count > 0 else "not_available"
    )
    source_interval = str(
        intraday_summary.get("source_interval")
        or intraday_summary.get("interval")
        or "1m"
    )
    effective_interval = str(
        intraday_summary.get("effective_interval")
        or source_interval
    )
    aggregation_metadata: dict[str, Any] = {}
    if requested_interval == "5m" and source_interval == "1m":
        volume_semantics = str(
            intraday_summary.get("volume_semantics") or "interval_volume"
        )
        points, aggregation_metadata = aggregate_regular_session_ohlcv(
            points,
            interval_minutes=5,
            market_timezone=JP_MARKET_TIMEZONE,
            session_segments=(
                (time(9, 0), time(11, 30), "regular_am"),
                (time(12, 30), time(15, 30), "regular_pm"),
            ),
            volume_additive=(
                "interval" in volume_semantics
                or volume_semantics in {"", "shares", "not_provided"}
            ),
        )
        effective_interval = "5m"
    points, bar_metadata = _annotate_intraday_bar_contract(
        points,
        interval=effective_interval,
        default_ohlc_semantics="interval_ohlc",
        default_volume_status=intraday_summary.get("volume_status"),
    )
    compact_points = points[-point_limit:]
    latest = compact_points[-1] if compact_points else raw_latest
    if requested_interval != effective_interval:
        warnings = [
            *warnings,
            (
                f"Requested JP intraday interval {requested_interval} is not available; "
                f"returned {effective_interval} source bars without relabeling."
            ),
        ]

    return {
        "enabled": True,
        "requested_interval": requested_interval,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {
            effective_interval: {
                "interval": effective_interval,
                "requested_interval": requested_interval,
                "source_interval": source_interval,
                "effective_interval": effective_interval,
                "interval_status": (
                    "ready"
                    if requested_interval == effective_interval
                    else "unsupported"
                ),
                "source": source,
                "provider": "yahoo_chart"
                if source == "yahoo_finance_chart"
                else source,
                "session_scope": intraday_summary.get("session_scope") or "regular",
                "session_phase": intraday_summary.get("session_phase"),
                "point_count": point_count,
                "returned_point_count": len(compact_points),
                "latest": latest,
                "points": compact_points,
                "to_time": latest.get("time") if latest else None,
                "previous_close": intraday_summary.get("previous_close"),
                "previous_close_source": intraday_summary.get(
                    "previous_close_source"
                ),
                "previous_close_trade_date": intraday_summary.get(
                    "previous_close_trade_date"
                ),
                "volume_unit": intraday_summary.get("volume_unit"),
                "volume_semantics": intraday_summary.get("volume_semantics"),
                "volume_status": intraday_summary.get("volume_status"),
                **bar_metadata,
                **aggregation_metadata,
                "regular_session_close": intraday_summary.get(
                    "regular_session_close"
                ),
                "regular_session_close_time": intraday_summary.get(
                    "regular_session_close_time"
                ),
                "source_url": intraday_summary.get("source_url"),
                "cache_status": intraday_summary.get("cache_status"),
                "cache_hit": intraday_summary.get("cache_hit"),
                "cache_trade_date": intraday_summary.get("cache_trade_date"),
                "cache_latest_time": intraday_summary.get("cache_latest_time"),
                "cached_count": intraday_summary.get("cached_count"),
                "refreshed_count": intraday_summary.get("refreshed_count"),
                "fallback_used": bool(intraday_summary.get("fallback_used")),
            }
        },
        "warnings": warnings,
    }



def _jp_expected_intraday_date(calendar_status: dict[str, Any]) -> str | None:
    if (
        calendar_status.get("is_trading_day")
        and calendar_status.get("phase") != "pre_market_pending"
    ):
        value = calendar_status.get("date")
    else:
        value = calendar_status.get("previous_trading_day")
    return str(value) if value else None


def read_jp_stock_context(
    db: Session,
    *,
    symbol: str,
    is_index: bool = False,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    dependencies: JPContextDependencies,
) -> dict[str, Any]:
    normalized_symbol = normalize_jp_symbol(symbol)
    tool_runs = tool_runs or []
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
    provider = _market_data_str(market_data_params, "provider", "auto") or "auto"
    include_intraday = _market_data_bool(
        market_data_params,
        "include_intraday",
        False,
    )
    payload_level = _market_payload_level(market_data_params)
    intraday_summary = (_latest_tool_result(tool_runs, "jp.refresh_intraday_trend")
                        or _latest_tool_result(tool_runs, "jp.read_intraday_trend"))
    evaluation_at = dependencies.now()
    calendar_status = build_jp_calendar_status(now=evaluation_at)
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
        if normalized_symbol
        else None
    )
    daily_rows: list[Any] = []
    chart: dict[str, Any] = {}
    fundamental: Any = None
    resource_summary: dict[str, Any] | None = None
    source_health: dict[str, Any] = {}
    warnings: list[str] = [
        "Japan context reads local evidence only; acquisition requires a separate bounded refresh command.",
    ]
    missing: list[str] = []

    if is_index:
        warnings.append(
            "Japan index context is OHLC-only; company fundamentals and chip resources are skipped."
        )
    elif stock is None:
        missing.append("jp_stock_master")
        warnings.append("JP stock master row is missing; symbol-level cached evidence is still returned when available.")

    try:
        daily_rows = dependencies.jp_market_service.list_jp_daily_prices(
            db=db,
            symbol=normalized_symbol,
            limit=10,
            requested_at=evaluation_at,
        )
    except Exception as exc:
        missing.append("jp_daily_price")
        warnings.append(f"JP daily prices unavailable: {exc}")

    try:
        chart = dependencies.jp_market_service.list_jp_ohlc_chart_data(
            db=db,
            symbol=normalized_symbol,
            timeframe=timeframe,
            bars=bars,
            ensure_history=False,
            outputsize="compact",
            provider=provider,
            requested_at=evaluation_at,
        )
    except Exception as exc:
        if "jp_daily_price" not in missing:
            missing.append("jp_daily_price")
        warnings.append(f"JP OHLC chart unavailable: {exc}")

    chart_freshness_status = (
        str(chart.get("freshness_status") or "missing")
        if isinstance(chart, dict)
        else "missing"
    )
    daily_is_current = bool(
        isinstance(chart, dict) and chart.get("is_current") is True
    )
    if chart and not daily_is_current:
        warnings.append(
            "JP daily price is not current: "
            f"latest={chart.get('latest_data_date') or 'missing'}, "
            f"expected={chart.get('expected_data_date') or 'unknown'}."
        )

    if include_intraday and intraday_summary is None:
        try:
            intraday_summary = dependencies.jp_market_service.get_jp_intraday_trend(
                symbol=normalized_symbol,
                db=db,
                refresh=False,
                external_fetch_allowed=False,
            )
        except Exception as exc:
            missing.append("jp_intraday_trend")
            warnings.append(f"JP intraday trend unavailable: {exc}")

    try:
        source_health = dependencies.jp_market_service.build_jp_source_health(
            db=db,
            symbol=normalized_symbol,
            is_index=is_index,
            now=evaluation_at,
        )
    except Exception as exc:
        warnings.append(f"JP source health unavailable: {exc}")

    intraday_requested = include_intraday or intraday_summary is not None
    intraday_quote = _jp_intraday_quote(
        intraday_summary,
        calendar_status=calendar_status,
    )
    intraday_bars = _jp_intraday_compact(
        intraday_summary,
        market_data_params=market_data_params,
    )
    if intraday_quote:
        # Observation-session labels on individual bars do not describe the
        # current market session. Consume the JP owner's evaluated clock.
        intraday_bars.update({
            "market_status": intraday_quote.get("market_status"),
            "session_phase": intraday_quote.get("current_session_phase"),
            "freshness": intraday_quote.get("freshness"),
        })
    intraday_latest = _jp_intraday_latest(intraday_summary)
    intraday_as_of = (
        str(intraday_latest.get("time"))
        if isinstance(intraday_latest, dict) and intraday_latest.get("time")
        else None
    )
    expected_intraday_date = _jp_expected_intraday_date(calendar_status)
    intraday_trade_date = intraday_as_of[:10] if intraday_as_of else None
    intraday_freshness_status = str(
        (intraday_quote.get("freshness") or {}).get("status") or "missing"
    )
    intraday_is_current = intraday_freshness_status in {
        "live",
        "latest_completed_session",
    }
    intraday_readiness = {
        "requested": intraday_requested,
        "available": bool(intraday_quote),
        "status": (
            "ready"
            if intraday_requested and intraday_quote and intraday_is_current
            else "limited"
            if intraday_requested and intraday_quote
            else "missing"
            if intraday_requested
            else "not_requested"
        ),
        "freshness_status": (
            intraday_freshness_status
            if intraday_requested
            else "not_requested"
        ),
        "usable_for_intraday": bool(
            intraday_requested and intraday_quote and intraday_is_current
        ),
        "independent_of_daily": True,
        "daily_dependency": "none",
    }
    if intraday_requested and not intraday_quote:
        if "jp_intraday_trend" not in missing:
            missing.append("jp_intraday_trend")
        for warning in (intraday_summary or {}).get("warnings") or []:
            warnings.append(str(warning))
    elif intraday_requested and not intraday_is_current:
        warnings.append(
            "JP intraday trend is not live: "
            f"status={intraday_freshness_status}, "
            f"latest={intraday_trade_date or 'missing'}, "
            f"expected={expected_intraday_date or 'unknown'}."
        )
    if intraday_quote:
        for warning in (intraday_summary or {}).get("warnings") or []:
            warnings.append(str(warning))

    if not is_index:
        try:
            fundamental = dependencies.jp_market_service.get_jp_company_fundamental(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            missing.append("jp_company_fundamental")
            warnings.append(f"JP company fundamental summary unavailable: {exc}")

        try:
            resource_summary = dependencies.jp_market_service.get_jp_resource_summary(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            warnings.append(f"JP resource summary unavailable: {exc}")

    if not daily_rows and not (chart.get("points") if isinstance(chart, dict) else None):
        if "jp_daily_price" not in missing:
            missing.append("jp_daily_price")

    if not is_index and fundamental is None and "jp_company_fundamental" not in missing:
        missing.append("jp_company_fundamental")

    unavailable_resources: list[str] = []
    planned_resources: list[str] = []
    if resource_summary:
        for slot in resource_summary.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            key = str(slot.get("key") or "").strip()
            if not key:
                continue
            if slot.get("status") == "planned":
                planned_resources.append(key)
                continue
            if not slot.get("available"):
                unavailable_resources.append(key)
                missing.append(f"jp_resource.{key}")

    if unavailable_resources:
        warnings.append(
            "JP resource slots are empty in local cache: " + ", ".join(sorted(set(unavailable_resources)))
        )
    if planned_resources:
        warnings.append(
            "JP resource slots are planned but not implemented yet: " + ", ".join(sorted(set(planned_resources)))
        )

    latest_daily = daily_rows[0] if daily_rows else None
    canonical_daily = settings.jp_canonical_daily_mode == "on"
    daily_source_name = "jp.daily.ohlcv" if canonical_daily else "jp_daily_price"
    daily_limits = list(getattr(latest_daily, "limitations", ()) or ())
    warnings.extend(daily_limits)
    chart_points = (
        chart.get("points")
        if isinstance(chart, dict) and isinstance(chart.get("points"), list)
        else []
    )
    latest_point = chart_points[-1] if chart_points else None
    latest_trade_date = (
        latest_daily.trade_date.isoformat()
        if latest_daily is not None
        else _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
    )
    latest_close = (
        latest_daily.close_price
        if latest_daily is not None
        else latest_point.get("close") if isinstance(latest_point, dict) else None
    )
    latest_volume = (
        latest_daily.trade_volume
        if latest_daily is not None
        else latest_point.get("volume") if isinstance(latest_point, dict) else None
    )

    source_refs: list[dict[str, Any]] = []
    market_breadth: dict[str, Any] = {}
    for row in daily_rows[:3]:
        if getattr(row, "evidence_id", None):
            source_refs.append({
                "type": "database", "kind": "jp.daily.ohlcv", "provider": row.provider,
                "symbol": row.symbol, "date": row.trade_date.isoformat(),
                "evidence_id": row.evidence_id, "raw_receipt_id": row.raw_receipt_id,
                "price_basis": row.price_basis,
            })
        if row.source_url:
            source_refs.append(
                {
                    "kind": "jp_daily_price",
                    "provider": row.provider,
                    "symbol": row.symbol,
                    "date": row.trade_date.isoformat(),
                    "url": row.source_url,
                }
            )
    if fundamental is not None and getattr(fundamental, "source_url", None):
        source_refs.append(
            {
                "kind": "jp_company_fundamental",
                "provider": getattr(fundamental, "provider", None),
                "symbol": getattr(fundamental, "symbol", normalized_symbol),
                "fetched_at": _json_value(getattr(fundamental, "fetched_at", None)),
                "url": getattr(fundamental, "source_url", None),
            }
        )
    if intraday_quote:
        _append_source_ref_once(
            source_refs,
            {
                "type": "external_or_cache",
                "name": "yahoo_finance_chart",
                "symbol": normalized_symbol,
                "url": (intraday_summary or {}).get("source_url"),
            },
        )

    _append_source_ref_once(source_refs, {"type": "dataset" if canonical_daily else "table", "name": daily_source_name})
    if is_index:
        try:
            market_overview = dependencies.jp_market_service.get_jp_market_overview(
                db=db,
                now=evaluation_at,
            )
            candidate_breadth = market_overview.get("breadth")
            if isinstance(candidate_breadth, dict):
                market_breadth = _json_ready(candidate_breadth)
        except Exception as exc:
            warnings.append(f"JP direct market breadth unavailable: {exc}")
        if not market_breadth or market_breadth.get("status") == "missing":
            missing.append("jp_market_breadth")
        _append_source_ref_once(
            source_refs,
            {"type": "derived", "name": "app.jp_market.market_overview"},
        )
    if not is_index:
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_stock_master"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_company_fundamental"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_margin_interest"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_investor_type"})
        _append_source_ref_once(source_refs, {"type": "derived", "name": "app.jp_market.resource_summary"})

    target_type = "jp_index" if is_index else "jp_stock"
    label = (
        "Nikkei 225"
        if normalized_symbol == "^N225"
        else "TOPIX ETF"
        if normalized_symbol == "1306.T" and is_index
        else stock.security_name
        if stock and stock.security_name
        else normalized_symbol
    )
    resource_slots = resource_summary.get("slots") if isinstance(resource_summary, dict) else []
    envelope = {
        "kind": "jp_index_context" if is_index else "jp_stock_context",
        "generated_at": dependencies.now().isoformat(),
        "as_of": intraday_as_of or latest_trade_date,
        "scope": {
            "target": {
                "type": target_type,
                "id": normalized_symbol,
                "label": label,
                "market": "JP",
            }
        },
        "summary": {
            "latest_close": intraday_quote.get("price", latest_close),
            "latest_trade_date": latest_trade_date,
            "latest_volume": intraday_quote.get("volume", latest_volume),
            "intraday": {
                "requested": intraday_requested,
                "available": bool(intraday_quote),
                "is_current": intraday_is_current if intraday_requested else None,
                "expected_trade_date": expected_intraday_date,
                "latest": intraday_latest,
                "point_count": (intraday_summary or {}).get("point_count"),
                "source": (intraday_summary or {}).get("source"),
                "previous_close": (intraday_summary or {}).get("previous_close"),
                "previous_close_source": (intraday_summary or {}).get(
                    "previous_close_source"
                ),
            },
            "resource_status": {
                "available": [
                    slot.get("key")
                    for slot in resource_slots
                    if isinstance(slot, dict) and slot.get("available")
                ],
                "empty": sorted(set(unavailable_resources)),
                "planned": sorted(set(planned_resources)),
            },
        },
        "data": {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "local_code",
                    "security_name",
                    "exchange",
                    "market_segment",
                    "sector_33_name",
                    "sector_17_name",
                    "size_name",
                    "asset_type",
                    "currency",
                    "exchange_timezone_name",
                    "is_active",
                    "last_seen_at",
                    "updated_at",
                ),
            ),
            "daily_prices": _list_rows(
                daily_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "currency",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "adjusted_close",
                    "trade_volume",
                    "fetched_at",
                    "evidence_id",
                    "raw_receipt_id",
                    "price_basis",
                    "facts_usable",
                    "research_usable",
                    "resolved_status",
                    "limitations",
                ),
            ),
            "chart": _json_ready(chart),
            "fundamental": _row_dict(
                fundamental,
                (
                    "provider",
                    "symbol",
                    "company_name",
                    "exchange",
                    "sector",
                    "industry",
                    "currency",
                    "market_cap",
                    "enterprise_value",
                    "trailing_pe",
                    "forward_pe",
                    "price_to_book",
                    "dividend_yield",
                    "eps_ttm",
                    "forward_eps",
                    "revenue_ttm",
                    "net_sales",
                    "operating_profit",
                    "ordinary_profit",
                    "profit",
                    "forecast_net_sales",
                    "forecast_operating_profit",
                    "forecast_profit",
                    "return_on_equity",
                    "return_on_assets",
                    "profit_margin",
                    "debt_to_equity",
                    "current_ratio",
                    "book_value",
                    "earnings_date",
                    "ex_dividend_date",
                    "fetched_at",
                ),
            ),
            "resource_summary": _json_ready(resource_summary),
            "source_health": _json_ready(source_health),
            "breadth": market_breadth,
            "intraday_readiness": intraday_readiness,
            "intraday": {
                "requested": intraday_requested,
                "available": bool(intraday_quote),
                "expected_trade_date": expected_intraday_date,
                "latest_trade_date": intraday_trade_date,
                "source": (intraday_summary or {}).get("source"),
                "source_url": (intraday_summary or {}).get("source_url"),
                "warnings": list((intraday_summary or {}).get("warnings") or []),
            },
            "tool_runs": tool_runs,
        },
        "data_limitations": [
            *daily_limits,
            "No JP-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "Company fundamentals and chip resources depend on local cache coverage and free/provider availability.",
            "JP disclosures currently expose company-statement metadata from cached fundamentals, not a complete TDnet disclosure feed.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    envelope["data"]["compact"] = _compact_market_context(
        kind="jp_index_compact_evidence" if is_index else "jp_stock_compact_evidence",
        target=envelope["scope"]["target"],
        quote={
            **(
                intraday_quote
                or {
                    "source": daily_source_name,
                    "price": latest_close,
                    "volume": latest_volume,
                    "quote_time": latest_trade_date,
                    "is_realtime": False,
                    "is_live": False,
                    "quote_semantics": "daily_close_reference",
                    "source_kind": "daily_bar_close",
                    "last_trade_available": False,
                    "last_trade_price": None,
                    "decision_usable": False,
                    "fallback_used": True,
                    "evidence_id": getattr(latest_daily, "evidence_id", None),
                    "price_basis": getattr(latest_daily, "price_basis", None),
                    "facts_usable": getattr(latest_daily, "facts_usable", False),
                    "research_usable": getattr(latest_daily, "research_usable", False),
                    "limitations": [*daily_limits, "QUOTE_SNAPSHOT_NOT_PROVIDED", "DAILY_CLOSE_REFERENCE_ONLY"],
                    "provider": latest_daily.provider if latest_daily else None,
                    "fallback_reason": "intraday_not_available"
                    if intraday_requested
                    else None,
                }
            ),
        },
        resources={
            "daily_rows": len(daily_rows),
            "chart_points": len(chart_points),
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "fundamental_available": fundamental is not None,
            "resource_status": envelope["summary"].get("resource_status"),
            "source_health": (
                source_health.get("summary")
                if isinstance(source_health, dict)
                else {}
            ),
            "include_intraday": intraday_requested,
            "intraday_available": bool(intraday_quote),
            "intraday_readiness": intraday_readiness,
        },
        freshness={
            "price": intraday_freshness_status if intraday_quote else chart_freshness_status,
            "daily": chart_freshness_status,
            "intraday": (
                intraday_freshness_status
                if intraday_quote and intraday_requested
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "fundamental": "current" if fundamental is not None else "missing" if not is_index else "not_applicable",
        },
        payload_level=payload_level,
    )
    envelope["data"]["compact"]["intraday_bars"] = intraday_bars
    envelope["data"]["compact"]["intraday_readiness"] = intraday_readiness
    if is_index:
        envelope["data"]["compact"]["breadth"] = market_breadth
    context_is_current = daily_is_current and (
        not intraday_requested or intraday_is_current
    )
    freshness_result = {
        "kind": "jp_index_freshness" if is_index else "jp_stock_freshness",
        "scope": {"target": envelope["scope"]["target"]},
        "is_current": context_is_current,
        "refresh_recommended": not context_is_current,
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": envelope["as_of"],
        "daily": {
            "status": chart_freshness_status,
            "latest_data_date": chart.get("latest_data_date") if chart else None,
            "expected_data_date": chart.get("expected_data_date") if chart else None,
        },
        "intraday": {
            "status": (
                intraday_freshness_status
                if intraday_quote and intraday_requested
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "latest_trade_date": intraday_trade_date,
            "expected_trade_date": expected_intraday_date,
            "readiness": intraday_readiness,
        },
        "source_health": (
            source_health.get("summary")
            if isinstance(source_health, dict)
            else {}
        ),
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=freshness_result,
        tool_runs=tool_runs,
    )
    return envelope
