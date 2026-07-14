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
from app.db.models import KRStockMaster
from app.kr_market.sources import (
    KR_INDEX_CONFIG_BY_ID,
    normalize_kr_index_id,
    normalize_kr_symbol,
)


@dataclass(frozen=True)
class KRContextDependencies:
    kr_market_service: Any
    now: Callable[[], datetime]


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
    payload_level = _market_payload_level(market_data_params)
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

    data["compact"] = _compact_market_context(
        kind="kr_index_compact_evidence" if is_index else "kr_stock_compact_evidence",
        target=target,
        quote={
            "source": "kr_index_daily_price" if is_index else "kr_daily_price",
            "price": latest_close,
            "volume": latest_volume,
            "quote_time": latest_trade_date,
            "is_realtime": False,
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
        },
        freshness={
            "price": "current" if latest_trade_date else "missing",
            "fundamentals": "current" if fundamentals else "missing" if not is_index else "not_applicable",
            "investor_trading": "current" if investor_rows else "missing" if not is_index else "not_applicable",
        },
        payload_level=payload_level,
    )
    envelope = {
        "kind": "kr_index_context" if is_index else "kr_stock_context",
        "generated_at": dependencies.now().isoformat(),
        "as_of": latest_trade_date,
        "scope": {"target": target},
        "summary": {
            "latest_close": latest_close,
            "latest_trade_date": latest_trade_date,
            "latest_volume": latest_volume,
            "source_health": source_health.get("summary") if isinstance(source_health, dict) else {},
        },
        "data": data,
        "data_limitations": [
            "No KR-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "KR context is based on bounded local-cache evidence unless a separate refresh endpoint is called.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    freshness_result = {
        "kind": "kr_index_freshness" if is_index else "kr_stock_freshness",
        "scope": {"target": target},
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
