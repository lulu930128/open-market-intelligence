from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.agentic_common import _json_ready, _json_value, _list_rows, _row_dict, _safe_int
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
)
from app.ai.market_context.regional_params import _market_data_bool, _market_data_int, _market_data_str
from app.ai.market_payload_contract import (
    intraday_point_limit as _market_intraday_point_limit,
    payload_level as _market_payload_level,
)
from app.db.models import KRStockMaster
from app.market.calendar_status import build_kr_calendar_status
from app.kr_market.sources import (
    KR_INDEX_CONFIG_BY_ID,
    normalize_kr_index_id,
    normalize_kr_symbol,
)


@dataclass(frozen=True)
class KRContextDependencies:
    kr_market_service: Any
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


def _kr_intraday_latest(
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


def _kr_intraday_quote(
    intraday_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    latest = _kr_intraday_latest(intraday_summary)
    if latest is None:
        return {}
    price = latest.get("price")
    previous_close = intraday_summary.get("previous_close") if intraday_summary else None
    change = None
    change_pct = None
    if isinstance(price, (int, float)) and isinstance(previous_close, (int, float)) and previous_close:
        change = float(price) - float(previous_close)
        change_pct = change / float(previous_close) * 100
    return {
        "source": intraday_summary.get("source") or "unavailable",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "volume": latest.get("cumulative_volume", latest.get("volume")),
        "quote_time": latest.get("time"),
        "is_realtime": True,
        "session_phase": intraday_summary.get("session_phase"),
        "previous_close": previous_close,
        "previous_close_source": intraday_summary.get("previous_close_source"),
        "point_count": intraday_summary.get("point_count"),
    }


def _kr_intraday_compact(
    intraday_summary: dict[str, Any] | None,
    *,
    market_data_params: dict[str, Any] | None,
) -> dict[str, Any]:
    payload_level = _market_payload_level(market_data_params)
    point_limit = _market_intraday_point_limit(market_data_params)
    raw_points = (
        intraday_summary.get("points")
        if isinstance(intraday_summary, dict) and isinstance(intraday_summary.get("points"), list)
        else []
    )
    points = [point for point in raw_points if isinstance(point, dict)]
    latest = _kr_intraday_latest(intraday_summary)
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        return {
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": ["KR intraday trend was not requested or did not return data."],
        }
    compact_points = points[-point_limit:]
    point_count = _safe_int(
        intraday_summary.get("point_count"),
        len(points),
        minimum=0,
        maximum=100000,
    )
    return {
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {
            "1m": {
                "interval": "1m",
                "source": intraday_summary.get("source") or "unavailable",
                "session_scope": intraday_summary.get("session_scope") or "regular",
                "session_phase": intraday_summary.get("session_phase"),
                "point_count": point_count,
                "returned_point_count": len(compact_points),
                "latest": latest,
                "points": compact_points,
                "to_time": latest.get("time") if latest else None,
                "previous_close": intraday_summary.get("previous_close"),
                "previous_close_source": intraday_summary.get("previous_close_source"),
                "previous_close_trade_date": intraday_summary.get("previous_close_trade_date"),
                "source_url": intraday_summary.get("source_url"),
                "is_partial": bool(intraday_summary.get("is_partial")),
            }
        },
        "warnings": list(intraday_summary.get("warnings") or []),
    }


def _kr_expected_intraday_date(calendar_status: dict[str, Any]) -> str | None:
    if calendar_status.get("is_trading_day") and calendar_status.get("phase") != "pre_market_pending":
        value = calendar_status.get("date")
    else:
        value = calendar_status.get("previous_trading_day")
    return str(value) if value else None


def read_kr_stock_context(
    db: Session,
    *,
    symbol: str,
    is_index: bool = False,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    dependencies: KRContextDependencies,
) -> dict[str, Any]:
    tool_runs = tool_runs or []
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
    provider = _market_data_str(market_data_params, "provider", "auto") or "auto"
    include_intraday = _market_data_bool(market_data_params, "include_intraday", False)
    payload_level = _market_payload_level(market_data_params)
    intraday_summary = _latest_tool_result(tool_runs, "kr.read_intraday_trend")
    calendar_status = build_kr_calendar_status(now=dependencies.now())
    warnings: list[str] = [
        "Korea AI context is local-cache only; it does not fetch external data on the read path.",
    ]
    missing: list[str] = []
    source_refs: list[dict[str, Any]] = []
    stock: KRStockMaster | None = None
    daily_rows: list[Any] = []
    chart: dict[str, Any] = {}
    fundamentals: list[Any] = []
    investor_rows: list[Any] = []
    resource_summary: dict[str, Any] | None = None
    source_health: dict[str, Any] = {}
    normalized_id = ""

    if is_index:
        normalized_id = normalize_kr_index_id(symbol)
        index_config = KR_INDEX_CONFIG_BY_ID.get(normalized_id)
        if index_config is None:
            missing.append("kr_market_index")
            warnings.append(f"Unsupported KR index id: {symbol}.")
        try:
            chart = dependencies.kr_market_service.list_kr_index_ohlc_chart_data(
                db=db,
                index_id=normalized_id,
                timeframe=timeframe,
                bars=bars,
                ensure_history=False,
                outputsize="compact",
            )
        except Exception as exc:
            missing.append("kr_index_daily_price")
            warnings.append(f"KR index OHLC chart unavailable: {exc}")

        chart_points = chart.get("points") if isinstance(chart, dict) else []
        if not chart_points and "kr_index_daily_price" not in missing:
            missing.append("kr_index_daily_price")
        latest_point = chart_points[-1] if chart_points else None
        latest_trade_date = _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
        latest_close = latest_point.get("close") if isinstance(latest_point, dict) else None
        latest_volume = latest_point.get("volume") if isinstance(latest_point, dict) else None
        label = (
            index_config.short_name or index_config.name
            if index_config is not None
            else normalized_id
        )
        target = {"type": "kr_index", "id": normalized_id, "label": label, "market": "KR"}
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_market_index"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_index_daily_price"})
        data = {
            "stock": None,
            "daily_prices": [],
            "chart": _json_ready(chart),
            "fundamentals": [],
            "investor_trading": [],
            "resource_summary": None,
            "source_health": {},
            "tool_runs": tool_runs,
        }
    else:
        normalized_id = normalize_kr_symbol(symbol)
        stock = (
            db.query(KRStockMaster)
            .filter(KRStockMaster.symbol == normalized_id)
            .first()
        )
        if stock is None:
            missing.append("kr_stock_master")
            warnings.append("KR stock master row is missing; symbol-level cached evidence is still returned when available.")

        try:
            daily_rows = dependencies.kr_market_service.list_kr_daily_prices(
                db=db,
                symbol=normalized_id,
                provider=None if provider == "auto" else provider,
                limit=10,
            )
        except Exception as exc:
            missing.append("kr_daily_price")
            warnings.append(f"KR daily prices unavailable: {exc}")

        try:
            chart = dependencies.kr_market_service.list_kr_ohlc_chart_data(
                db=db,
                symbol=normalized_id,
                timeframe=timeframe,
                bars=bars,
                ensure_history=False,
                outputsize="compact",
                provider=provider,
            )
        except Exception as exc:
            if "kr_daily_price" not in missing:
                missing.append("kr_daily_price")
            warnings.append(f"KR OHLC chart unavailable: {exc}")

        try:
            fundamentals = dependencies.kr_market_service.list_kr_company_fundamentals(
                db=db,
                symbol=normalized_id,
                limit=20,
            )
        except Exception as exc:
            missing.append("kr_company_fundamental")
            warnings.append(f"KR company fundamentals unavailable: {exc}")

        try:
            investor_rows = dependencies.kr_market_service.list_kr_investor_trades(
                db=db,
                symbol=normalized_id,
                limit=10,
            )
        except Exception as exc:
            missing.append("kr_investor_trade_daily")
            warnings.append(f"KR investor trading unavailable: {exc}")

        try:
            resource_summary = dependencies.kr_market_service.get_kr_resource_summary(
                db=db,
                symbol=normalized_id,
            )
        except Exception as exc:
            warnings.append(f"KR resource summary unavailable: {exc}")

        try:
            source_health = dependencies.kr_market_service.build_kr_source_health(
                db=db,
                symbol=normalized_id,
            )
        except Exception as exc:
            warnings.append(f"KR source health unavailable: {exc}")

        if not daily_rows and not (chart.get("points") if isinstance(chart, dict) else None):
            if "kr_daily_price" not in missing:
                missing.append("kr_daily_price")
        if not fundamentals and "kr_company_fundamental" not in missing:
            missing.append("kr_company_fundamental")
        if not investor_rows and "kr_investor_trade_daily" not in missing:
            missing.append("kr_investor_trade_daily")

        latest_daily = daily_rows[0] if daily_rows else None
        chart_points = chart.get("points") if isinstance(chart, dict) else []
        latest_point = chart_points[-1] if chart_points else None
        latest_trade_date = (
            latest_daily.trade_date.isoformat()
            if latest_daily is not None
            else _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
        )
        latest_close = (
            latest_daily.adjusted_close if latest_daily and latest_daily.adjusted_close is not None
            else latest_daily.close_price if latest_daily is not None
            else latest_point.get("close") if isinstance(latest_point, dict) else None
        )
        latest_volume = (
            latest_daily.trade_volume
            if latest_daily is not None
            else latest_point.get("volume") if isinstance(latest_point, dict) else None
        )
        label = (
            stock.security_name
            if stock and stock.security_name
            else stock.security_name_kr
            if stock and stock.security_name_kr
            else normalized_id
        )
        target = {"type": "kr_stock", "id": normalized_id, "label": label, "market": "KR"}
        for row in daily_rows[:3]:
            if row.source_url:
                source_refs.append(
                    {
                        "kind": "kr_daily_price",
                        "provider": row.provider,
                        "symbol": row.symbol,
                        "date": row.trade_date.isoformat(),
                        "url": row.source_url,
                    }
                )
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_stock_master"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_daily_price"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_company_fundamental"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_investor_trade_daily"})
        _append_source_ref_once(source_refs, {"type": "derived", "name": "app.kr_market.source_health"})
        data = {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "local_code",
                    "security_name",
                    "security_name_kr",
                    "exchange",
                    "market_segment",
                    "sector",
                    "industry",
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
                    "price_change",
                    "change_pct",
                    "trade_volume",
                    "trade_value",
                    "market_cap",
                    "fetched_at",
                ),
            ),
            "chart": _json_ready(chart),
            "fundamentals": _list_rows(
                fundamentals,
                (
                    "provider",
                    "symbol",
                    "corp_code",
                    "stock_code",
                    "company_name",
                    "fiscal_year",
                    "report_code",
                    "report_name",
                    "statement_name",
                    "account_name",
                    "current_amount",
                    "previous_amount",
                    "currency",
                    "disclosed_date",
                    "fetched_at",
                ),
            ),
            "investor_trading": _list_rows(
                investor_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "investor_type",
                    "buy_value",
                    "sell_value",
                    "net_buy_value",
                    "buy_volume",
                    "sell_volume",
                    "net_buy_volume",
                    "fetched_at",
                ),
            ),
            "resource_summary": _json_ready(resource_summary),
            "source_health": _json_ready(source_health),
            "tool_runs": tool_runs,
        }

    if include_intraday and intraday_summary is None:
        try:
            if is_index:
                intraday_summary = dependencies.kr_market_service.get_kr_index_intraday_trend(
                    db=db,
                    index_id=normalized_id,
                )
            else:
                intraday_summary = dependencies.kr_market_service.get_kr_stock_intraday_trend(
                    db=db,
                    symbol=normalized_id,
                )
        except Exception as exc:
            missing.append("kr_intraday_trend")
            warnings.append(f"KR intraday trend unavailable: {exc}")

    intraday_requested = include_intraday or intraday_summary is not None
    intraday_quote = _kr_intraday_quote(intraday_summary)
    intraday_bars = _kr_intraday_compact(
        intraday_summary,
        market_data_params=market_data_params,
    )
    intraday_latest = _kr_intraday_latest(intraday_summary)
    intraday_as_of = (
        str(intraday_latest.get("time"))
        if isinstance(intraday_latest, dict) and intraday_latest.get("time")
        else None
    )
    intraday_trade_date = intraday_as_of[:10] if intraday_as_of else None
    expected_intraday_date = _kr_expected_intraday_date(calendar_status)
    intraday_is_current = bool(
        intraday_trade_date
        and expected_intraday_date
        and intraday_trade_date == expected_intraday_date
    )
    if intraday_requested and not intraday_quote:
        if "kr_intraday_trend" not in missing:
            missing.append("kr_intraday_trend")
    elif intraday_requested and not intraday_is_current:
        warnings.append(
            "KR intraday trend is stale: "
            f"latest={intraday_trade_date or 'missing'}, "
            f"expected={expected_intraday_date or 'unknown'}."
        )
    for warning in (intraday_summary or {}).get("warnings") or []:
        warnings.append(str(warning))
    if intraday_quote:
        _append_source_ref_once(
            source_refs,
            {
                "type": "external_or_cache",
                "name": intraday_summary.get("source") or "kr_intraday",
                "symbol": normalized_id,
                "url": intraday_summary.get("source_url"),
            },
        )
    data["intraday"] = _json_ready(intraday_summary)

    data["compact"] = _compact_market_context(
        kind="kr_index_compact_evidence" if is_index else "kr_stock_compact_evidence",
        target=target,
        quote={
            "source": intraday_quote.get("source") or ("kr_index_daily_price" if is_index else "kr_daily_price"),
            "price": intraday_quote.get("price", latest_close),
            "volume": intraday_quote.get("volume", latest_volume),
            "quote_time": intraday_quote.get("quote_time", latest_trade_date),
            "is_realtime": bool(intraday_quote),
            "provider": provider,
        },
        resources={
            "daily_rows": len(daily_rows),
            "chart_points": len(chart.get("points") or []) if isinstance(chart, dict) else 0,
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "fundamental_rows": len(fundamentals),
            "investor_trade_rows": len(investor_rows),
            "source_health": (source_health.get("summary") if isinstance(source_health, dict) else {}),
            "include_intraday": intraday_requested,
            "intraday_available": bool(intraday_quote),
        },
        freshness={
            "price": "current" if intraday_is_current or latest_trade_date else "missing",
            "intraday": (
                "current"
                if intraday_is_current
                else "stale"
                if intraday_quote and intraday_requested
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "fundamentals": "current" if fundamentals else "missing" if not is_index else "not_applicable",
            "investor_trading": "current" if investor_rows else "missing" if not is_index else "not_applicable",
        },
        payload_level=payload_level,
    )
    data["compact"]["intraday_bars"] = intraday_bars
    envelope = {
        "kind": "kr_index_context" if is_index else "kr_stock_context",
        "generated_at": dependencies.now().isoformat(),
        "as_of": intraday_as_of or latest_trade_date,
        "scope": {"target": target},
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
            },
            "source_health": source_health.get("summary") if isinstance(source_health, dict) else {},
        },
        "data": data,
        "data_limitations": [
            "No KR-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "KR daily/fundamental context uses local cache; optional intraday is a bounded provider read only when server policy allows external fetch.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    freshness_result = {
        "kind": "kr_index_freshness" if is_index else "kr_stock_freshness",
        "scope": {"target": target},
        "is_current": bool(intraday_is_current or latest_trade_date),
        "refresh_recommended": not bool(intraday_is_current or latest_trade_date),
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": intraday_as_of or latest_trade_date,
        "intraday": {
            "status": (
                "current"
                if intraday_is_current
                else "stale"
                if intraday_quote and intraday_requested
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "latest_trade_date": intraday_trade_date,
            "expected_trade_date": expected_intraday_date,
        },
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
