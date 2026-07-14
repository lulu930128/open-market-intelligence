from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.agentic_common import _json_ready, _json_value, _list_rows, _row_dict
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
)
from app.ai.market_context.regional_params import _market_data_int, _market_data_str
from app.ai.market_payload_contract import payload_level as _market_payload_level
from app.db.models import JPStockMaster
from app.jp_market.sources import normalize_jp_symbol


@dataclass(frozen=True)
class JPContextDependencies:
    jp_market_service: Any
    now: Callable[[], datetime]


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
    payload_level = _market_payload_level(market_data_params)
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
    warnings: list[str] = [
        "Japan AI context is local-cache only; it does not fetch external data on the read path.",
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
        )
    except Exception as exc:
        if "jp_daily_price" not in missing:
            missing.append("jp_daily_price")
        warnings.append(f"JP OHLC chart unavailable: {exc}")

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
    chart_points = chart.get("points") if isinstance(chart, dict) else []
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
    for row in daily_rows[:3]:
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

    _append_source_ref_once(source_refs, {"type": "table", "name": "jp_daily_price"})
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
        "as_of": latest_trade_date,
        "scope": {
            "target": {
                "type": target_type,
                "id": normalized_symbol,
                "label": label,
                "market": "JP",
            }
        },
        "summary": {
            "latest_close": latest_close,
            "latest_trade_date": latest_trade_date,
            "latest_volume": latest_volume,
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
            "tool_runs": tool_runs,
        },
        "data_limitations": [
            "No JP-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "Company fundamentals and chip resources depend on local cache coverage and free/provider availability.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    envelope["data"]["compact"] = _compact_market_context(
        kind="jp_index_compact_evidence" if is_index else "jp_stock_compact_evidence",
        target=envelope["scope"]["target"],
        quote={
            "source": "jp_daily_price",
            "price": latest_close,
            "volume": latest_volume,
            "quote_time": latest_trade_date,
            "is_realtime": False,
            "provider": latest_daily.provider if latest_daily else None,
        },
        resources={
            "daily_rows": len(daily_rows),
            "chart_points": len(chart_points),
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "fundamental_available": fundamental is not None,
            "resource_status": envelope["summary"].get("resource_status"),
        },
        freshness={
            "price": "current" if latest_trade_date else "missing",
            "fundamental": "current" if fundamental is not None else "missing" if not is_index else "not_applicable",
        },
        payload_level=payload_level,
    )
    freshness_result = {
        "kind": "jp_index_freshness" if is_index else "jp_stock_freshness",
        "scope": {"target": envelope["scope"]["target"]},
        "is_current": latest_trade_date is not None,
        "refresh_recommended": latest_trade_date is None,
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": latest_trade_date,
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
