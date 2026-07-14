from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import evidence_builder, technical_analysis, tool_catalog
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import (
    COMPACT_INTRADAY_BAR_LIMIT,
    PAYLOAD_LEVELS,
    bounded_int_param as _bounded_int_param,
    has_payload_value as _has_payload_value,
    intraday_point_limit as _intraday_point_limit,
    market_data_params as _market_data_params,
    payload_level as _payload_level,
    payload_slot_status as _payload_slot_status,
    slot_envelope as _slot_envelope,
)
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.market import service as market_service
from app.market.broker_branch import get_broker_branch_trade_summary
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.intraday import get_market_intraday_history
from app.market.quote_depth import get_taiwan_stock_quote_depth
from app.market.technical_report import build_stock_technical_report
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.market_chips import get_latest_market_chip_daily, market_chip_daily_to_dict
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.source_health import build_taiwan_source_health
from app.market.tw_futures import (
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    normalize_taiwan_futures_symbols,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
from app.market.taiwan_industries import normalize_tw_industry_label
from app.stocks import service as stock_service
from app.watchlists import radar_service, ranking_service
from app.watchlists import service as watchlist_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if row is None:
        return None

    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _stock_dict(stock: StockMaster | None) -> dict[str, Any] | None:
    return _row_dict(
        stock,
        (
            "stock_id",
            "stock_name",
            "market",
            "instrument_type",
            "industry",
            "category",
            "is_active",
            "notes",
            "last_seen_at",
            "updated_at",
        ),
    )


def _latest_financial_period(row: FinancialMetricQuarterly | None) -> str | None:
    if row is None:
        return None

    return row.period or f"{row.fiscal_year}Q{row.quarter}"


def _latest_date_string(values: list[Any]) -> str | None:
    valid_values = [_json_value(value) for value in values if value is not None]

    if not valid_values:
        return None

    return str(max(valid_values))


def _broker_branch_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {key: _json_value(value) for key, value in row.items()}

    return _row_dict(
        row,
        (
            "trade_date",
            "stock_id",
            "stock_name",
            "branch_code",
            "branch_name",
            "buy_lots",
            "sell_lots",
            "net_lots",
            "buy_avg_price",
            "sell_avg_price",
            "buy_rank",
            "sell_rank",
            "source_label",
        ),
    ) or {}


def _add_missing(missing: list[str], key: str, value: Any) -> None:
    if value is None or value == []:
        missing.append(key)


COMPACT_INTRADAY_INTERVALS = ("1m", "5m")
FRESHNESS_DOMAIN_RESOURCES = {
    "technical": {"market_daily_price"},
    "chips": {
        "institutional_trade_daily",
        "margin_trading_daily",
        "broker_branch_trade_daily",
        "shareholding_distribution_weekly",
        "market_chip_daily",
    },
    "fundamentals": {"monthly_revenue", "financial_metric_quarterly"},
}


def _quote_slot_status(quote: dict[str, Any]) -> str:
    if not quote or not _has_payload_value(quote):
        return "missing"
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    if quote.get("status") == "unavailable" or freshness.get("status") == "missing":
        return "missing"
    if bool(quote.get("is_realtime")) and not bool(freshness.get("is_stale")):
        return "ready"
    return "partial"


def _intraday_slot_status(intraday_bars: dict[str, Any]) -> str:
    if not intraday_bars:
        return "missing"
    if not intraday_bars.get("enabled"):
        return "not_requested"
    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    for item in series.values():
        if isinstance(item, dict) and (item.get("latest") or item.get("returned_point_count")):
            return "ready"
    return "missing"


def _build_tw_stock_slots(
    *,
    target: dict[str, Any],
    as_of: str | None,
    payload_level: str,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    technical: dict[str, Any],
    chips: dict[str, Any],
    fundamentals: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "identity": _slot_envelope(
            status="ready" if target.get("id") else "partial",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=as_of,
        ),
        "quote": _slot_envelope(
            status=_quote_slot_status(quote),
            capability="quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
            as_of=quote.get("quote_time") or quote.get("trade_date") or as_of,
            missing=[key for key in missing if key in {"quote_depth", "market_daily_price"}],
        ),
        "intraday": _slot_envelope(
            status=_intraday_slot_status(intraday_bars),
            capability="live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "intraday_bars"],
            warnings=intraday_bars.get("warnings") if isinstance(intraday_bars.get("warnings"), list) else [],
            next_fill="Request market_data_params.include_intraday=true with trusted external fetch policy.",
        ),
        "daily_chart": _slot_envelope(
            status="ready" if "market_daily_price" not in missing else "partial",
            capability="daily_ohlc_chart",
            payload_ref="full.data.chart",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "market_daily_price"],
        ),
        "technical": _slot_envelope(
            status=_payload_slot_status(
                technical,
                missing=[key for key in missing if key == "market_daily_price"],
            ),
            capability="technical_decision_evidence",
            payload_ref="technical",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "chips_flows": _slot_envelope(
            status=_payload_slot_status(
                chips,
                missing=[key for key in missing if key in FRESHNESS_DOMAIN_RESOURCES["chips"]],
            ),
            capability="tw_chips_and_flows",
            payload_ref="chips",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "fundamentals": _slot_envelope(
            status=_payload_slot_status(
                fundamentals,
                missing=[key for key in missing if key in FRESHNESS_DOMAIN_RESOURCES["fundamentals"]],
            ),
            capability="tw_fundamentals",
            payload_ref="fundamentals",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "cross_market": _slot_envelope(
            status="planned",
            capability="cross_market_context",
            payload_level=payload_level,
            next_fill="Attach US/JP/KR/crypto context as bounded auxiliary evidence, not as Taiwan-core replacement.",
        ),
        "news_events": _slot_envelope(
            status="planned",
            capability="news_and_event_context",
            payload_level=payload_level,
            next_fill="Requires provider policy, quota boundary, and source attribution before default use.",
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="data_quality",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _build_tw_index_slots(
    *,
    target: dict[str, Any],
    as_of: str | None,
    payload_level: str,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    technical: dict[str, Any],
    market_chip: dict[str, Any] | None,
    contributions: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "identity": _slot_envelope(
            status="ready" if target.get("id") else "partial",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=as_of,
        ),
        "quote": _slot_envelope(
            status=_quote_slot_status(quote),
            capability="index_quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
            as_of=quote.get("quote_time") or quote.get("trade_date") or as_of,
        ),
        "intraday": _slot_envelope(
            status=_intraday_slot_status(intraday_bars),
            capability="index_live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key.startswith("market_index_intraday")],
        ),
        "daily_chart": _slot_envelope(
            status="ready" if "market_index_ohlc.daily" not in missing else "partial",
            capability="index_daily_ohlc_chart",
            payload_ref="full.data.charts.daily",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "market_index_ohlc.daily"],
        ),
        "technical": _slot_envelope(
            status=_payload_slot_status(
                technical,
                missing=[key for key in missing if key.startswith("market_index_ohlc")],
            ),
            capability="index_technical_decision_evidence",
            payload_ref="technical",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "chips_flows": _slot_envelope(
            status="ready" if market_chip else "missing",
            capability="index_market_chip_daily",
            payload_ref="chips.market_chip",
            payload_level=payload_level,
            as_of=(market_chip or {}).get("trade_date") or as_of,
            missing=[] if market_chip else ["market_chip_daily"],
        ),
        "index_contributions": _slot_envelope(
            status="ready" if _has_payload_value(contributions) else "missing",
            capability="index_contribution_leaders",
            payload_ref="contributions",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="data_quality",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _build_tw_market_slots(
    *,
    as_of: str | None,
    payload_level: str,
    breadth: dict[str, Any],
    distribution: dict[str, Any],
    industry_rows: list[dict[str, Any]],
    index_intraday: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    intraday_missing = [
        key for key in missing if key.startswith("market_index_intraday")
    ]
    return {
        "identity": _slot_envelope(
            status="ready",
            capability="target_identity",
            payload_ref="scope",
            priority="core",
            as_of=as_of,
        ),
        "market_breadth": _slot_envelope(
            status=_payload_slot_status(
                breadth,
                missing=[key for key in missing if key.startswith("market_daily_price")],
            ),
            capability="tw_market_breadth",
            payload_ref="breadth",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "distribution": _slot_envelope(
            status=_payload_slot_status(distribution),
            capability="tw_market_distribution",
            payload_ref="distribution",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "sector_industry": _slot_envelope(
            status="ready" if industry_rows else "missing",
            capability="tw_industry_strength",
            payload_ref="top_industries,weak_industries",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "index_intraday": _slot_envelope(
            status=(
                "not_requested"
                if not index_intraday.get("enabled")
                else "ready"
                if _has_payload_value(index_intraday.get("indices"))
                else "missing"
            ),
            capability="tw_market_index_intraday",
            payload_ref="index_intraday",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=intraday_missing,
            warnings=index_intraday.get("warnings") if isinstance(index_intraday.get("warnings"), list) else [],
        ),
        "cross_market": _slot_envelope(
            status="planned",
            capability="cross_market_context",
            payload_level=payload_level,
            next_fill="Attach overseas index and crypto risk context as auxiliary evidence after provider boundaries are finalized.",
        ),
        "news_events": _slot_envelope(
            status="planned",
            capability="news_and_event_context",
            payload_level=payload_level,
            next_fill="Requires provider policy, quota boundary, and source attribution before default use.",
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="missing,warnings,source_refs,evidence_passport",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _compact_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    return _row_dict(row, fields)


def _compact_latest_daily_quote(
    latest_daily: Any,
    *,
    quote_error: str | None = None,
    session_phase: str | None = None,
) -> dict[str, Any]:
    if latest_daily is None:
        return {
            "kind": "quote_snapshot",
            "source": "market_daily_price",
            "provider": "local_daily_close",
            "status": "unavailable",
            "session_phase": session_phase,
            "trade_date": None,
            "quote_time": None,
            "latest_price": None,
            "price": None,
            "last_price": None,
            "is_realtime": False,
            "latency_ms": None,
            "freshness": {
                "status": "missing",
                "is_live": False,
                "is_stale": True,
                "message": quote_error or "No local daily close is available.",
            },
        }

    close_price = _json_value(getattr(latest_daily, "close_price", None))
    previous_close = (
        close_price - _json_value(getattr(latest_daily, "price_change", 0))
        if close_price is not None and getattr(latest_daily, "price_change", None) is not None
        else None
    )
    change_pct = (
        (_json_value(getattr(latest_daily, "price_change", None)) / previous_close) * 100
        if previous_close not in {None, 0}
        else None
    )

    return {
        "kind": "quote_snapshot",
        "source": "market_daily_price",
        "provider": "local_daily_close",
        "status": "delayed_daily_close",
        "session_phase": session_phase,
        "trade_date": _json_value(getattr(latest_daily, "trade_date", None)),
        "quote_time": None,
        "latest_price": close_price,
        "price": close_price,
        "last_price": close_price,
        "previous_close": previous_close,
        "open_price": _json_value(getattr(latest_daily, "open_price", None)),
        "high_price": _json_value(getattr(latest_daily, "high_price", None)),
        "low_price": _json_value(getattr(latest_daily, "low_price", None)),
        "change": _json_value(getattr(latest_daily, "price_change", None)),
        "change_pct": change_pct,
        "total_volume_lots": (
            int(getattr(latest_daily, "trade_volume", 0) / 1000)
            if getattr(latest_daily, "trade_volume", None) is not None
            else None
        ),
        "is_realtime": False,
        "latency_ms": None,
        "freshness": {
            "status": "daily_close",
            "is_live": False,
            "is_stale": False,
            "message": quote_error or "Live quote was not requested; using latest local daily close.",
        },
    }


def _compact_quote_snapshot(
    *,
    latest_daily: Any,
    quote_depth: dict[str, Any] | None,
    quote_error: str | None,
    session_phase: str | None = None,
) -> dict[str, Any]:
    if not quote_depth:
        return _compact_latest_daily_quote(
            latest_daily,
            quote_error=quote_error,
            session_phase=session_phase,
        )

    freshness = quote_depth.get("freshness") if isinstance(quote_depth.get("freshness"), dict) else {}
    age_seconds = freshness.get("age_seconds")
    latency_ms = int(age_seconds * 1000) if isinstance(age_seconds, (int, float)) else None
    is_realtime = bool(freshness.get("is_live")) and not bool(freshness.get("is_stale"))
    latest_price = quote_depth.get("last_price")
    return {
        "kind": "quote_snapshot",
        "source": quote_depth.get("source"),
        "provider": quote_depth.get("provider"),
        "status": freshness.get("status") or quote_depth.get("session_phase") or "quote",
        "session_phase": quote_depth.get("session_phase"),
        "phase_label": quote_depth.get("phase_label"),
        "trade_date": _json_value(quote_depth.get("trade_date")),
        "quote_time": _json_value(quote_depth.get("quote_time")),
        "fetched_at": _json_value(quote_depth.get("fetched_at")),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "previous_close": quote_depth.get("previous_close"),
        "open_price": quote_depth.get("open_price"),
        "high_price": quote_depth.get("high_price"),
        "low_price": quote_depth.get("low_price"),
        "change": quote_depth.get("change"),
        "change_pct": quote_depth.get("change_pct"),
        "total_volume_lots": quote_depth.get("total_volume_lots"),
        "best_bid_price": quote_depth.get("best_bid_price"),
        "best_bid_size_lots": quote_depth.get("best_bid_size_lots"),
        "best_ask_price": quote_depth.get("best_ask_price"),
        "best_ask_size_lots": quote_depth.get("best_ask_size_lots"),
        "spread": quote_depth.get("spread"),
        "spread_pct": quote_depth.get("spread_pct"),
        "depth_available": bool(quote_depth.get("depth_available")),
        "is_realtime": is_realtime,
        "latency_ms": latency_ms,
        "freshness": {
            "status": freshness.get("status"),
            "is_live": bool(freshness.get("is_live")),
            "is_stale": bool(freshness.get("is_stale")),
            "age_seconds": freshness.get("age_seconds"),
            "expected_trade_date": _json_value(freshness.get("expected_trade_date")),
            "message": freshness.get("message"),
            "source_error": freshness.get("source_error"),
        },
    }


def _compact_intraday_point(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": _json_value(point.get("time")),
        "price": point.get("price") if point.get("price") is not None else point.get("close"),
        "open": point.get("open"),
        "high": point.get("high"),
        "low": point.get("low"),
        "close": point.get("close"),
        "volume": point.get("volume"),
        "trade_value": point.get("trade_value"),
        "transaction_count": point.get("transaction_count"),
    }


def _compact_intraday_history(
    history: dict[str, Any],
    *,
    point_limit: int = COMPACT_INTRADAY_BAR_LIMIT,
) -> dict[str, Any]:
    raw_points = history.get("points") if isinstance(history.get("points"), list) else []
    points = [point for point in raw_points if isinstance(point, dict)]
    compact_points = [_compact_intraday_point(point) for point in points[-point_limit:]]
    first_point = points[0] if points else {}
    latest_point = compact_points[-1] if compact_points else None
    return {
        "interval": history.get("interval"),
        "range": history.get("range"),
        "provider": history.get("provider"),
        "source": history.get("source"),
        "from_time": _json_value(history.get("from_time") or first_point.get("time")),
        "to_time": _json_value(history.get("to_time") or (latest_point or {}).get("time")),
        "point_count": history.get("point_count") if history.get("point_count") is not None else len(points),
        "returned_point_count": len(compact_points),
        "cached_count": history.get("cached_count"),
        "refreshed_count": history.get("refreshed_count"),
        "latest": latest_point,
        "points": compact_points,
    }


def _compact_intraday_bars(
    *,
    db: Session,
    stock_id: str,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    if not include_intraday:
        return {
            "kind": "intraday_bars",
            "enabled": False,
            "intervals": list(COMPACT_INTRADAY_INTERVALS),
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [],
        }

    series: dict[str, Any] = {}
    warnings: list[str] = []
    for interval in COMPACT_INTRADAY_INTERVALS:
        try:
            history = get_market_intraday_history(
                db=db,
                stock_id=stock_id,
                interval=interval,
                range_value="1d",
                refresh=True,
            )
            series[interval] = _compact_intraday_history(history, point_limit=point_limit)
        except Exception as exc:
            warnings.append(f"{interval} intraday bars unavailable: {exc}")
            series[interval] = {
                "interval": interval,
                "range": "1d",
                "point_count": 0,
                "returned_point_count": 0,
                "latest": None,
                "points": [],
            }

    return {
        "kind": "intraday_bars",
        "enabled": True,
        "intervals": list(COMPACT_INTRADAY_INTERVALS),
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": series,
        "warnings": warnings,
    }


def _compact_single_intraday_series(
    *,
    raw_payload: dict[str, Any] | None,
    interval: str,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    if not include_intraday:
        return {
            "kind": "intraday_bars",
            "enabled": False,
            "intervals": [interval],
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [],
        }

    payload = raw_payload if isinstance(raw_payload, dict) else {}
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    history = {
        "interval": interval,
        "range": payload.get("range") or "1d",
        "provider": payload.get("provider"),
        "source": payload.get("source"),
        "point_count": payload.get("point_count") if payload.get("point_count") is not None else len(points),
        "points": points,
    }
    return {
        "kind": "intraday_bars",
        "enabled": True,
        "intervals": [interval],
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {interval: _compact_intraday_history(history, point_limit=point_limit)},
        "warnings": [],
    }


def _compact_technical_report(report: dict[str, Any]) -> dict[str, Any]:
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    daily_indicator = data.get("daily_indicator") if isinstance(data.get("daily_indicator"), dict) else {}
    intraday = data.get("intraday") if isinstance(data.get("intraday"), dict) else {}
    return {
        "timeframe": report.get("timeframe"),
        "phase": report.get("phase"),
        "title": report.get("title"),
        "summary": report.get("summary"),
        "score": report.get("score"),
        "confidence": report.get("confidence"),
        "value": report.get("value"),
        "value_label": report.get("value_label"),
        "latest_close": daily_indicator.get("close") or (intraday.get("latest_point") or {}).get("close"),
        "missing": report.get("missing") or [],
        "warnings": report.get("warnings") or [],
    }


def _compact_technical_evidence(
    *,
    analysis: dict[str, Any],
    technical_levels: dict[str, Any],
    technical_reports: dict[str, Any],
) -> dict[str, Any]:
    return {
        "analysis": {
            "requested_horizon": analysis.get("requested_horizon"),
            "selected_horizon": analysis.get("selected_horizon"),
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": analysis.get("selected_score"),
            "selected_title": analysis.get("selected_title"),
            "selected_summary": analysis.get("selected_summary"),
            "selected_confidence": analysis.get("selected_confidence"),
            "scores": analysis.get("scores") or {},
            "score_range": (analysis.get("score_model") or {}).get("score_range"),
        },
        "levels": {
            "latest_price": technical_levels.get("latest_price"),
            "basis_timeframe": technical_levels.get("basis_timeframe"),
            "context": technical_levels.get("context") or {},
            "entry": technical_levels.get("entry") or {},
            "risk": technical_levels.get("risk") or {},
        },
        "reports": {
            timeframe: _compact_technical_report(report)
            for timeframe, report in technical_reports.items()
            if isinstance(report, dict)
        },
    }


def _source_health_entries(source_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(source_health, dict):
        return []
    entries = source_health.get("entries")
    return entries if isinstance(entries, list) else []


def _compact_source_health_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource": entry.get("resource"),
        "label": entry.get("label"),
        "status": entry.get("status"),
        "ok": bool(entry.get("ok")),
        "row_count": entry.get("row_count"),
        "latest": _json_value(entry.get("latest_data_date") or entry.get("latest_data_key")),
        "expected": _json_value(entry.get("expected_data_date")),
        "release_status": entry.get("release_status"),
        "freshness_lag_days": entry.get("freshness_lag_days"),
        "reason": entry.get("reason"),
    }


def _status_from_resources(resources: list[dict[str, Any]], *, extra_missing: list[str] | None = None) -> str:
    if extra_missing:
        return "partial"
    if not resources:
        return "unknown"
    statuses = {str(resource.get("status") or "") for resource in resources}
    if any(status in {"error", "missing", "empty"} for status in statuses):
        return "missing"
    if "stale" in statuses:
        return "stale"
    if all(resource.get("ok") for resource in resources):
        return "current"
    return "partial"


def _freshness_domain_from_resources(
    *,
    source_health: dict[str, Any] | None,
    resources: set[str],
    missing: list[str],
) -> dict[str, Any]:
    domain_resources = [
        _compact_source_health_entry(entry)
        for entry in _source_health_entries(source_health)
        if entry.get("resource") in resources
    ]
    missing_resources = [key for key in missing if key in resources]
    status = _status_from_resources(domain_resources, extra_missing=missing_resources)
    latest_values = [item.get("latest") for item in domain_resources if item.get("latest")]
    expected_values = [item.get("expected") for item in domain_resources if item.get("expected")]
    return {
        "status": status,
        "is_current": status == "current" and not missing_resources,
        "latest": str(max(latest_values)) if latest_values else None,
        "expected": str(max(expected_values)) if expected_values else None,
        "missing": missing_resources,
        "resources": domain_resources,
    }


def _quote_freshness_domain(quote: dict[str, Any]) -> dict[str, Any]:
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    status = str(freshness.get("status") or quote.get("status") or "unknown")
    is_current = status not in {"missing", "unavailable"} and not bool(freshness.get("is_stale"))
    return {
        "status": status,
        "is_current": is_current,
        "latest": quote.get("quote_time") or quote.get("trade_date"),
        "expected": freshness.get("expected_trade_date"),
        "resources": [
            {
                "resource": "quote",
                "label": "Quote",
                "status": status,
                "ok": is_current,
                "latest": quote.get("quote_time") or quote.get("trade_date"),
                "expected": freshness.get("expected_trade_date"),
                "reason": freshness.get("message"),
            }
        ],
    }


def _intraday_bar_freshness_resource(intraday_bars: dict[str, Any]) -> dict[str, Any]:
    if not intraday_bars.get("enabled"):
        return {
            "resource": "intraday_bars",
            "label": "Intraday bars",
            "status": "not_requested",
            "ok": True,
            "latest": None,
            "expected": None,
            "reason": "Intraday bars were not requested or not allowed by policy.",
        }
    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    latest_values = [
        item.get("to_time")
        for item in series.values()
        if isinstance(item, dict) and item.get("to_time")
    ]
    missing_intervals = [
        interval
        for interval, item in series.items()
        if not isinstance(item, dict) or not item.get("returned_point_count")
    ]
    status = "current" if series and not missing_intervals else "missing"
    return {
        "resource": "intraday_bars",
        "label": "Intraday bars",
        "status": status,
        "ok": status == "current",
        "latest": str(max(latest_values)) if latest_values else None,
        "expected": None,
        "reason": (
            "Intraday bar cache has 1m and 5m data."
            if status == "current"
            else "Missing intraday bars for: " + ", ".join(missing_intervals)
        ),
    }


def _cross_market_freshness_domain(overnight_impact: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(overnight_impact, dict):
        return {
            "status": "unavailable",
            "is_current": False,
            "latest": None,
            "expected": None,
            "missing": ["us_overnight_tw_impact"],
            "resources": [],
        }
    missing = overnight_impact.get("missing") if isinstance(overnight_impact.get("missing"), list) else []
    warnings = overnight_impact.get("warnings") if isinstance(overnight_impact.get("warnings"), list) else []
    status = "current" if not missing else "partial"
    return {
        "status": status,
        "is_current": status == "current",
        "latest": overnight_impact.get("as_of"),
        "expected": None,
        "missing": missing,
        "warnings": warnings,
        "resources": [
            {
                "resource": "us_overnight_tw_impact",
                "label": "US overnight impact",
                "status": status,
                "ok": status == "current",
                "latest": overnight_impact.get("as_of"),
                "expected": None,
                "reason": "Cross-market context derived from mapped US/ADR/index evidence.",
            }
        ],
    }


def _build_freshness_by_domain(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    source_health: dict[str, Any] | None,
    overnight_impact: dict[str, Any] | None,
    missing: list[str],
) -> dict[str, Any]:
    technical = _freshness_domain_from_resources(
        source_health=source_health,
        resources=FRESHNESS_DOMAIN_RESOURCES["technical"],
        missing=missing,
    )
    technical["resources"] = [
        *technical.get("resources", []),
        _intraday_bar_freshness_resource(intraday_bars),
    ]
    if intraday_bars.get("enabled") and any(not item.get("ok") for item in technical["resources"]):
        technical["status"] = "partial"
        technical["is_current"] = False

    return {
        "quote": _quote_freshness_domain(quote),
        "technical": technical,
        "chips": _freshness_domain_from_resources(
            source_health=source_health,
            resources=FRESHNESS_DOMAIN_RESOURCES["chips"],
            missing=missing,
        ),
        "fundamentals": _freshness_domain_from_resources(
            source_health=source_health,
            resources=FRESHNESS_DOMAIN_RESOURCES["fundamentals"],
            missing=missing,
        ),
        "cross_market": _cross_market_freshness_domain(overnight_impact),
    }


def _latest_intraday_point(intraday: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(intraday, dict):
        return None
    points = intraday.get("points") if isinstance(intraday.get("points"), list) else []
    for point in reversed(points):
        if isinstance(point, dict):
            return point
    return None


def _intraday_source_is_live(source: str | None) -> bool:
    source_text = str(source or "")
    if not source_text:
        return False
    if source_text in {"twse_openapi_mi_index", "tpex_openapi_daily_trading_index"}:
        return False
    return any(key in source_text for key in ("intraday", "twse_index_5s", "twse_mis", "yahoo_finance_chart"))


def _compact_index_quote(
    *,
    index_id: str,
    index_snapshot: dict[str, Any] | None,
    intraday: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = index_snapshot if isinstance(index_snapshot, dict) else {}
    latest_point = _latest_intraday_point(intraday)
    source = (
        str(intraday.get("source"))
        if isinstance(intraday, dict) and intraday.get("source")
        else str(snapshot.get("source") or "market_index_summary")
    )
    latest_price = (
        latest_point.get("price")
        if latest_point and latest_point.get("price") is not None
        else snapshot.get("close")
    )
    previous_close = (
        intraday.get("previous_close")
        if isinstance(intraday, dict) and intraday.get("previous_close") is not None
        else snapshot.get("previous_close")
    )
    change = (
        latest_price - previous_close
        if isinstance(latest_price, (int, float)) and isinstance(previous_close, (int, float))
        else snapshot.get("change")
    )
    change_pct = (
        (change / previous_close) * 100
        if isinstance(change, (int, float)) and isinstance(previous_close, (int, float)) and previous_close != 0
        else snapshot.get("change_pct")
    )
    is_live = bool(latest_point) and _intraday_source_is_live(source)
    quote_time = latest_point.get("time") if latest_point else snapshot.get("as_of") or snapshot.get("time")

    return {
        "kind": "quote_snapshot",
        "source": source,
        "provider": source,
        "status": "live_intraday" if is_live else "delayed_index_summary",
        "index_id": index_id,
        "trade_date": snapshot.get("time"),
        "quote_time": _json_value(quote_time),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "previous_close": previous_close,
        "open_price": (latest_point or {}).get("open") or snapshot.get("open"),
        "high_price": (latest_point or {}).get("high") or snapshot.get("high"),
        "low_price": (latest_point or {}).get("low") or snapshot.get("low"),
        "change": change,
        "change_pct": change_pct,
        "volume": (latest_point or {}).get("volume") or snapshot.get("volume"),
        "trade_value": snapshot.get("trade_value") or snapshot.get("estimated_trade_value"),
        "is_realtime": is_live,
        "latency_ms": None,
        "freshness": {
            "status": "live" if is_live else "delayed",
            "is_live": is_live,
            "is_stale": False,
            "message": (
                "Index intraday point is included."
                if latest_point
                else "Index intraday was not requested or not available; using latest index summary."
            ),
        },
    }


def _index_freshness_by_domain(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    market_chip: dict[str, Any] | None,
    missing: list[str],
) -> dict[str, Any]:
    chip_status = "current" if market_chip else "missing"
    return {
        "quote": _quote_freshness_domain(quote),
        "technical": {
            "status": "current" if "market_index_ohlc.daily" not in missing else "partial",
            "is_current": "market_index_ohlc.daily" not in missing,
            "resources": [_intraday_bar_freshness_resource(intraday_bars)],
        },
        "chips": {
            "status": chip_status,
            "is_current": market_chip is not None,
            "latest": (market_chip or {}).get("trade_date"),
            "missing": [] if market_chip else ["market_chip_daily"],
            "resources": [
                {
                    "resource": "market_chip_daily",
                    "label": "Market chip daily",
                    "status": chip_status,
                    "ok": market_chip is not None,
                    "latest": (market_chip or {}).get("trade_date"),
                    "expected": None,
                    "reason": "Latest market chip row is available." if market_chip else "No market chip row is available.",
                }
            ],
        },
    }


def _build_tw_index_compact_evidence(
    *,
    index_id: str,
    as_of: str | None,
    index_snapshot: dict[str, Any] | None,
    intraday: dict[str, Any] | None,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    market_chip: dict[str, Any] | None,
    contributions: dict[str, Any] | None,
    technical_reports: dict[str, Any],
    technical_analysis: dict[str, Any],
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    intraday_bars = _compact_single_intraday_series(
        raw_payload=intraday,
        interval="1m",
        include_intraday=include_intraday,
        market_data_params=market_data_params,
    )
    quote = _compact_index_quote(
        index_id=index_id,
        index_snapshot=index_snapshot,
        intraday=intraday if include_intraday else None,
    )
    payload_level = _payload_level(market_data_params)
    target = {
        "type": "tw_index",
        "id": index_id,
        "label": (index_snapshot or {}).get("label") or index_id,
        "market": (index_snapshot or {}).get("market") or "TW",
    }
    technical = _compact_technical_evidence(
        analysis=technical_analysis,
        technical_levels={},
        technical_reports=technical_reports,
    )
    chips = {"market_chip": market_chip}
    data_quality = {
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    return {
        "kind": "tw_index_compact_evidence",
        "version": "tw_index_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "intraday_bars": intraday_bars,
        "technical": technical,
        "chips": chips,
        "contributions": contributions,
        "freshness_by_domain": _index_freshness_by_domain(
            quote=quote,
            intraday_bars=intraday_bars,
            market_chip=market_chip,
            missing=missing,
        ),
        "data_quality": data_quality,
        "slots": _build_tw_index_slots(
            target=target,
            as_of=as_of,
            payload_level=payload_level,
            quote=quote,
            intraday_bars=intraday_bars,
            technical=technical,
            market_chip=market_chip,
            contributions=contributions,
            missing=data_quality["missing"],
            warnings=data_quality["warnings"],
        ),
        "source_refs": source_refs,
    }


def _build_stock_compact_evidence(
    *,
    stock: StockMaster | None,
    stock_id: str,
    as_of: str | None,
    latest_daily: Any,
    latest_institutional: Any,
    latest_margin: Any,
    shareholding: list[Any],
    branch_summary: dict[str, Any],
    latest_revenue: Any,
    revenue_history: list[Any],
    latest_financial: Any,
    financial_history: list[Any],
    technical_reports: dict[str, Any],
    technical_analysis: dict[str, Any],
    technical_levels: dict[str, Any],
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    source_health: dict[str, Any],
    overnight_impact: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    target = {
        "type": "tw_stock",
        "id": stock_id,
        "label": stock.stock_name if stock else None,
        "market": stock.market if stock else "TW",
    }
    technical = _compact_technical_evidence(
        analysis=technical_analysis,
        technical_levels=technical_levels,
        technical_reports=technical_reports,
    )
    chips = {
        "institutional": _compact_row(
            latest_institutional,
            (
                "trade_date",
                "foreign_investor_net",
                "investment_trust_net",
                "dealer_net",
                "total_institutional_net",
            ),
        ),
        "margin": _compact_row(
            latest_margin,
            (
                "trade_date",
                "margin_buy",
                "margin_sell",
                "margin_today_balance",
                "short_sale",
                "short_covering",
                "short_today_balance",
            ),
        ),
        "shareholding": [
            _compact_row(
                row,
                (
                    "data_date",
                    "holding_level",
                    "holder_count",
                    "share_count",
                    "share_ratio",
                ),
            )
            for row in shareholding[:5]
        ],
        "broker_branch": {
            "trade_date": _json_value(branch_summary.get("trade_date")),
            "requested_days": branch_summary.get("requested_days"),
            "available_days": branch_summary.get("available_days"),
            "is_partial": branch_summary.get("is_partial"),
            "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])[:5]],
            "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])[:5]],
        },
    }
    fundamentals = {
        "latest_revenue": _compact_row(
            latest_revenue,
            (
                "period",
                "monthly_revenue",
                "month_over_month_pct",
                "year_over_year_pct",
                "cumulative_revenue",
                "cumulative_year_over_year_pct",
            ),
        ),
        "latest_financial": _compact_row(
            latest_financial,
            (
                "period",
                "report_date",
                "revenue",
                "gross_profit",
                "operating_income",
                "net_income",
                "eps",
                "book_value_per_share",
                "roe",
                "roa",
            ),
        ),
        "revenue_history": [
            _compact_row(
                row,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            )
            for row in revenue_history[-6:]
        ],
        "financial_history": [
            _compact_row(
                row,
                (
                    "period",
                    "report_date",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            )
            for row in financial_history[-4:]
        ],
    }
    data_quality = {
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    raw_payload_level = intraday_bars.get("payload_level") if isinstance(intraday_bars, dict) else None
    payload_level = str(raw_payload_level) if raw_payload_level in PAYLOAD_LEVELS else "compact"
    return {
        "kind": "stock_compact_evidence",
        "version": "stock_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "intraday_bars": intraday_bars,
        "technical": technical,
        "chips": chips,
        "fundamentals": fundamentals,
        "freshness_by_domain": _build_freshness_by_domain(
            quote=quote,
            intraday_bars=intraday_bars,
            source_health=source_health,
            overnight_impact=overnight_impact,
            missing=missing,
        ),
        "data_quality": data_quality,
        "slots": _build_tw_stock_slots(
            target=target,
            as_of=as_of,
            payload_level=payload_level,
            quote=quote,
            intraday_bars=intraday_bars,
            technical=technical,
            chips=chips,
            fundamentals=fundamentals,
            missing=data_quality["missing"],
            warnings=data_quality["warnings"],
        ),
        "source_refs": source_refs,
    }


def _with_evidence_passport(
    envelope: dict[str, Any],
    *,
    freshness: dict[str, Any] | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    envelope["evidence_passport"] = build_evidence_passport(
        kind=str(envelope.get("kind") or "ai_data"),
        as_of=envelope.get("as_of"),
        source_refs=envelope.get("source_refs") or [],
        missing=envelope.get("missing") or [],
        warnings=envelope.get("warnings") or [],
        freshness=freshness,
        tool_runs=tool_runs,
        analysis=analysis or data.get("analysis"),
        confidence=confidence,
    )
    return envelope



normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_report_score = technical_analysis._report_score
TECHNICAL_FACTOR_ROW_KEYS = technical_analysis.TECHNICAL_FACTOR_ROW_KEYS
TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON = technical_analysis.TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON
_score_direction = technical_analysis._score_direction
_factor_score_from_row = technical_analysis._factor_score_from_row
_timeframe_factor_scores = technical_analysis._timeframe_factor_scores
_weighted_factor_score = technical_analysis._weighted_factor_score
_technical_factor_score_model = technical_analysis._technical_factor_score_model
_weighted_score = technical_analysis._weighted_score
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_finite_number = technical_analysis._finite_number
_first_value = technical_analysis._first_value
_moving_average = technical_analysis._moving_average
_pct_change = technical_analysis._pct_change
_format_number = technical_analysis._format_number
_format_pct = technical_analysis._format_pct
_source_value = technical_analysis._source_value
_round_price = technical_analysis._round_price
_price_zone = technical_analysis._price_zone
_price_level = technical_analysis._price_level
_indicator_from_report = technical_analysis._indicator_from_report
_indicator_level_values = technical_analysis._indicator_level_values
_donchian_position = technical_analysis._donchian_position
_technical_price_levels = technical_analysis._technical_price_levels
_normalize_technical_points = technical_analysis._normalize_technical_points
_technical_report_from_points = technical_analysis._technical_report_from_points
_serialized_chart = technical_analysis._serialized_chart
_chart_from_points = technical_analysis._chart_from_points


def _stock_decision_evidence(
    *,
    latest_daily: Any,
    chart: dict[str, Any],
    latest_revenue: Any,
    latest_financial: Any,
    technical_reports: dict[str, Any],
    calendar_status: dict[str, Any] | None = None,
    missing: list[str],
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    return evidence_builder.build_stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=calendar_status,
        missing=missing,
        source_refs=source_refs,
    )


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    return tool_catalog.list_ai_tools(include_internal=include_internal)


def read_data_freshness(db: Session, stock_id: str | None = None) -> dict[str, Any]:
    def latest(model: Any, column: Any) -> Any:
        query = db.query(func.max(column))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return query.scalar()

    def count(model: Any) -> int:
        query = db.query(func.count(model.id))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return int(query.scalar() or 0)

    financial_latest = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
        if stock_id
        else db.query(FinancialMetricQuarterly)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )

    tables = {
        "market_daily_price": {
            "latest": _json_value(latest(MarketDailyPrice, MarketDailyPrice.trade_date)),
            "row_count": count(MarketDailyPrice),
        },
        "institutional_trade_daily": {
            "latest": _json_value(latest(InstitutionalTradeDaily, InstitutionalTradeDaily.trade_date)),
            "row_count": count(InstitutionalTradeDaily),
        },
        "margin_trading_daily": {
            "latest": _json_value(latest(MarginTradingDaily, MarginTradingDaily.trade_date)),
            "row_count": count(MarginTradingDaily),
        },
        "broker_branch_trade_daily": {
            "latest": _json_value(latest(BrokerBranchTradeDaily, BrokerBranchTradeDaily.trade_date)),
            "row_count": count(BrokerBranchTradeDaily),
        },
        "shareholding_distribution_weekly": {
            "latest": _json_value(
                latest(ShareholdingDistributionWeekly, ShareholdingDistributionWeekly.data_date)
            ),
            "row_count": count(ShareholdingDistributionWeekly),
        },
        "monthly_revenue": {
            "latest": _json_value(latest(MonthlyRevenue, MonthlyRevenue.period)),
            "row_count": count(MonthlyRevenue),
        },
        "financial_metric_quarterly": {
            "latest": _latest_financial_period(financial_latest),
            "row_count": count(FinancialMetricQuarterly),
        },
    }

    missing = [name for name, info in tables.items() if not info["latest"] or info["row_count"] == 0]

    envelope = {
        "kind": "data_freshness",
        "generated_at": _now(),
        "as_of": _latest_date_string([info["latest"] for info in tables.values()]),
        "scope": {"stock_id": stock_id},
        "data": {"tables": tables},
        "missing": missing,
        "warnings": [
            "Freshness is based on the local OMI database, not direct exchange availability.",
        ],
        "source_refs": [{"type": "database", "name": "open_market_intelligence.db"}],
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def _market_index_ids_from_params(params: dict[str, Any] | None) -> list[str]:
    data_params = _market_data_params(params)
    raw_value = data_params.get("index_ids") or data_params.get("indices") or ("TAIEX", "TPEX")
    if isinstance(raw_value, str):
        values = [item.strip().upper() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        values = [str(item).strip().upper() for item in raw_value]
    else:
        values = ["TAIEX", "TPEX"]
    supported = {"TAIEX", "TPEX"}
    selected = [value for value in values if value in supported]
    return list(dict.fromkeys(selected or ["TAIEX", "TPEX"]))[:2]


def _market_index_intraday_pack(
    *,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    index_ids = _market_index_ids_from_params(market_data_params)
    if not include_intraday:
        return {
            "kind": "market_index_intraday_pack",
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "index_ids": index_ids,
            "indices": [],
            "warnings": [],
        }

    rows: list[dict[str, Any]] = []
    local_warnings: list[str] = []
    _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})
    for index_id in index_ids:
        try:
            intraday = get_market_index_intraday(index_id)
        except Exception as exc:
            message = f"{index_id} index intraday unavailable: {exc}"
            warnings.append(message)
            local_warnings.append(message)
            missing.append(f"market_index_intraday.{index_id}")
            continue

        intraday_bars = _compact_single_intraday_series(
            raw_payload=intraday,
            interval="1m",
            include_intraday=True,
            market_data_params=market_data_params,
        )
        quote = _compact_index_quote(
            index_id=index_id,
            index_snapshot=None,
            intraday=intraday,
        )
        rows.append(
            {
                "index_id": index_id,
                "quote": quote,
                "intraday_bars": intraday_bars,
            }
        )
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append(f"market_index_intraday.{index_id}")

    return {
        "kind": "market_index_intraday_pack",
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "index_ids": index_ids,
        "indices": rows,
        "warnings": local_warnings,
    }


def read_market_overview(
    db: Session,
    limit: int = 10,
    *,
    include_intraday: bool = False,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_trade_date = market_service.get_latest_trade_date(db)
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = [{"type": "table", "name": "market_daily_price"}]
    payload_level = _payload_level(market_data_params)
    index_intraday = _market_index_intraday_pack(
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        missing=missing,
        warnings=warnings,
        source_refs=source_refs,
    )

    if latest_trade_date is None:
        envelope = {
            "kind": "market_overview",
            "generated_at": _now(),
            "as_of": None,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": {},
                "top_gainers": [],
                "top_losers": [],
                "index_intraday": index_intraday,
                "slots": _build_tw_market_slots(
                    as_of=None,
                    payload_level=payload_level,
                    breadth={},
                    distribution={},
                    industry_rows=[],
                    index_intraday=index_intraday,
                    missing=list(dict.fromkeys(["market_daily_price", *missing])),
                    warnings=[
                        "No market daily rows are available in the local database.",
                        *warnings,
                    ],
                ),
            },
            "missing": list(dict.fromkeys(["market_daily_price", *missing])),
            "warnings": [
                "No market daily rows are available in the local database.",
                *warnings,
            ],
            "source_refs": source_refs,
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
    stock_industries: dict[str, str | None] = {}
    for index in range(0, len(stock_ids), 500):
        chunk = stock_ids[index : index + 500]
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(chunk)).all():
            stock_industries[stock.stock_id] = normalize_tw_industry_label(
                stock.industry or stock.category,
                fallback="未分類",
            )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
            "industry": stock_industries.get(row.stock_id),
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]
    value_leaders = sorted(
        [row for row in ranked if row["trade_value"] is not None],
        key=lambda row: row["trade_value"] or 0,
        reverse=True,
    )[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None
    total_count = len(rows)
    average_change_pct = (
        sum(row["change_pct"] for row in ranked_with_change) / len(ranked_with_change)
        if ranked_with_change
        else None
    )
    positive_ratio = advance_count / len(ranked_with_change) if ranked_with_change else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    top_value_sum = sum(row["trade_value"] or 0 for row in value_leaders)
    top_value_share = (
        top_value_sum / total_trade_value
        if total_trade_value and value_leaders
        else None
    )
    breadth = {
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "trade_value": total_trade_value,
        "average_change_pct": average_change_pct,
        "positive_ratio": positive_ratio,
        "advance_decline_ratio": advance_decline_ratio,
        "top_value_share": top_value_share,
    }
    distribution = {
        "limit_up_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) >= 9.5
        ),
        "strong_up_count": sum(
            1 for row in ranked_with_change if 5 <= (row["change_pct"] or 0) < 9.5
        ),
        "mild_up_count": sum(
            1 for row in ranked_with_change if 0 < (row["change_pct"] or 0) < 5
        ),
        "flat_count": unchanged_count,
        "mild_down_count": sum(
            1 for row in ranked_with_change if -5 < (row["change_pct"] or 0) < 0
        ),
        "strong_down_count": sum(
            1 for row in ranked_with_change if -9.5 < (row["change_pct"] or 0) <= -5
        ),
        "limit_down_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) <= -9.5
        ),
    }
    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_with_change:
        industry = normalize_tw_industry_label(row.get("industry"), fallback="未分類")
        industry_groups.setdefault(industry, []).append(row)

    industry_summary = []
    for industry, group_rows in industry_groups.items():
        changes = [
            row["change_pct"]
            for row in group_rows
            if isinstance(row.get("change_pct"), (int, float))
        ]
        if not changes:
            continue
        trade_value = sum(row.get("trade_value") or 0 for row in group_rows) or None
        top_row = max(
            group_rows,
            key=lambda row: (
                row.get("trade_value") or 0,
                row.get("change_pct") or 0,
            ),
        )
        industry_summary.append(
            {
                "industry": industry,
                "count": len(group_rows),
                "advance_count": sum(1 for value in changes if value > 0),
                "decline_count": sum(1 for value in changes if value < 0),
                "average_change_pct": sum(changes) / len(changes),
                "trade_value": trade_value,
                "top_stock_id": top_row.get("stock_id"),
                "top_stock_name": top_row.get("stock_name"),
            }
        )
    top_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            row.get("trade_value") or 0,
        ),
        reverse=True,
    )[:6]
    weak_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            -(row.get("trade_value") or 0),
        ),
    )[:6]

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    warnings.extend(
        [
            (
                "This overview includes bounded Taiwan index intraday data, but stock breadth still uses latest local daily rows."
                if include_intraday
                else "This overview uses the latest local daily market rows and does not fetch live quotes."
            )
        ]
    )

    envelope = {
        "kind": "market_overview",
        "generated_at": _now(),
        "as_of": latest_trade_date.isoformat(),
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": breadth,
            "distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "value_leaders": value_leaders,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
            "index_intraday": index_intraday,
            "slots": _build_tw_market_slots(
                as_of=latest_trade_date.isoformat(),
                payload_level=payload_level,
                breadth=breadth,
                distribution=distribution,
                industry_rows=[*top_industries, *weak_industries],
                index_intraday=index_intraday,
                missing=missing,
                warnings=warnings,
            ),
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_tw_index_context(
    db: Session,
    index_id: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_index_id = index_id.strip().upper()
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan index context uses market index evidence, not stock_master or individual stock daily tables.",
    ]
    charts: dict[str, Any] = {}
    technical_reports: dict[str, Any] = {}
    chart_bars = _bounded_int_param(
        market_data_params,
        ("daily_bars", "bars"),
        default=bars,
        minimum=20,
        maximum=500,
    )

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            chart = get_market_index_ohlc_chart_data(
                index_id=normalized_index_id,
                timeframe=timeframe,
                bars=max(chart_bars, 1),
                db=db,
            )
        except ValueError:
            raise
        except Exception as exc:
            warnings.append(f"{timeframe.title()} index chart unavailable: {exc}")
            missing.append(f"market_index_ohlc.{timeframe}")
            continue

        serialized = _serialized_chart(chart)
        charts[timeframe] = serialized
        points = _normalize_technical_points(serialized.get("points", []))
        technical_reports[timeframe] = _technical_report_from_points(
            points=points,
            timeframe=timeframe,
            asset_label=normalized_index_id,
        )
        if not points:
            missing.append(f"market_index_ohlc.{timeframe}")
        backfill = chart.get("backfill") if isinstance(chart.get("backfill"), dict) else {}
        if backfill.get("status") == "error":
            warnings.append(str(backfill.get("message") or "Index daily stat refresh failed."))

    intraday: dict[str, Any] | None = None
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    if include_intraday or normalized_horizon == "intraday":
        try:
            intraday = get_market_index_intraday(normalized_index_id)
            intraday_points = _normalize_technical_points(intraday.get("points", []))
            technical_reports["today"] = _technical_report_from_points(
                points=intraday_points,
                timeframe="today",
                asset_label=normalized_index_id,
            )
            if not intraday_points:
                missing.append("market_index_intraday")
        except Exception as exc:
            warnings.append(f"Index intraday unavailable: {exc}")
            missing.append("market_index_intraday")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    summary_payload: dict[str, Any] = {}
    index_snapshot: dict[str, Any] | None = None
    try:
        summary_payload = get_market_index_summary(db, force_refresh=False)
        for item in summary_payload.get("indices", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("index_id") or item.get("stock_id") or "").upper() == normalized_index_id:
                index_snapshot = {key: _json_value(value) for key, value in item.items()}
                break
        if index_snapshot is None:
            missing.append("market_index_summary")
    except Exception as exc:
        warnings.append(f"Index summary unavailable: {exc}")
        missing.append("market_index_summary")

    market_chip: dict[str, Any] | None = None
    try:
        chip_row = get_latest_market_chip_daily(db, index_id=normalized_index_id)
        market_chip = _json_dict(market_chip_daily_to_dict(chip_row)) if chip_row is not None else None
        if market_chip is None:
            missing.append("market_chip_daily")
    except Exception as exc:
        warnings.append(f"Market chip context unavailable: {exc}")
        missing.append("market_chip_daily")

    contributions: dict[str, Any] | None = None
    try:
        contributions_payload = get_market_index_contributions(normalized_index_id, limit=10)
        contributions = {
            key: _json_value(value)
            for key, value in contributions_payload.items()
            if key not in {"positive", "negative"}
        }
        contributions["positive"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("positive", [])
            if isinstance(item, dict)
        ]
        contributions["negative"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("negative", [])
            if isinstance(item, dict)
        ]
    except Exception as exc:
        warnings.append(f"Index contribution context unavailable: {exc}")

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    intraday_latest_time = (_latest_intraday_point(intraday) or {}).get("time")
    as_of = _latest_date_string(
        [
            (charts.get("daily") or {}).get("to_date"),
            (index_snapshot or {}).get("time"),
            (index_snapshot or {}).get("as_of"),
            (market_chip or {}).get("trade_date"),
            intraday_latest_time,
        ]
    )
    source_refs = [
        {"type": "table", "name": "market_index_daily_stat"},
        {"type": "table", "name": "market_chip_daily"},
        {"type": "derived", "name": "app.market.indices"},
        {"type": "external_or_cache", "name": "yahoo_finance_chart"},
    ]
    if include_intraday or intraday is not None:
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})

    envelope = {
        "kind": "tw_index_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"index_id": normalized_index_id},
        "data": {
            "index": index_snapshot,
            "charts": charts,
            "intraday": intraday,
            "market_chip": market_chip,
            "contributions": contributions,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "compact": _build_tw_index_compact_evidence(
                index_id=normalized_index_id,
                as_of=as_of,
                index_snapshot=index_snapshot,
                intraday=intraday,
                include_intraday=include_intraday or normalized_horizon == "intraday",
                market_data_params=market_data_params,
                market_chip=market_chip,
                contributions=contributions,
                technical_reports=technical_reports,
                technical_analysis=technical_analysis,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
            ),
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan futures context uses TAIFEX futures quote and bar tables, not stock_master or stock daily tables.",
    ]

    quote_rows = get_latest_taiwan_futures_quotes(db, symbols=[normalized_symbol], refresh=False)
    quote_dicts = [_json_dict(taiwan_futures_quote_to_dict(row)) for row in quote_rows]
    latest_quote = quote_dicts[0] if quote_dicts else None
    if latest_quote is None:
        missing.append("taiwan_futures_quote_snapshot")

    daily_rows = list_taiwan_futures_daily_bars(
        db=db,
        symbol=normalized_symbol,
        limit=max(bars, 1),
        active_only=True,
    )
    daily_dicts = [
        _json_dict(taiwan_futures_daily_bar_to_dict(row))
        for row in daily_rows
    ]
    daily_points = _normalize_technical_points([row for row in daily_dicts if isinstance(row, dict)])
    if not daily_points:
        missing.append("taiwan_futures_daily_bar")

    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    intraday_dicts: list[dict[str, Any]] = []
    intraday_points: list[dict[str, Any]] = []
    if include_intraday or normalized_horizon == "intraday":
        intraday_rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=normalized_symbol,
            limit=390,
        )
        intraday_dicts = [
            _json_dict(taiwan_futures_intraday_bar_to_dict(row))
            for row in intraday_rows
        ]
        intraday_points = _normalize_technical_points(
            [row for row in intraday_dicts if isinstance(row, dict)]
        )
        if not intraday_points:
            missing.append("taiwan_futures_intraday_bar")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily futures evidence is used as fallback context."
        )

    technical_reports: dict[str, Any] = {
        "daily": _technical_report_from_points(
            points=daily_points,
            timeframe="daily",
            asset_label=normalized_symbol,
        ),
    }
    if intraday_points:
        technical_reports["today"] = _technical_report_from_points(
            points=intraday_points,
            timeframe="today",
            asset_label=normalized_symbol,
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    daily_chart = _chart_from_points(timeframe="daily", points=daily_points)
    intraday_chart = _chart_from_points(timeframe="today", points=intraday_points)
    as_of = _latest_date_string(
        [
            (latest_quote or {}).get("quote_time"),
            daily_chart.get("to_date"),
            intraday_chart.get("to_date"),
        ]
    )

    envelope = {
        "kind": "tw_futures_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"symbol": normalized_symbol},
        "data": {
            "latest_quote": latest_quote,
            "quotes": quote_dicts,
            "daily_chart": daily_chart,
            "intraday_chart": intraday_chart if intraday_points else None,
            "daily_bars": daily_dicts,
            "intraday_bars": intraday_dicts,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "taiwan_futures_quote_snapshot"},
            {"type": "table", "name": "taiwan_futures_daily_bar"},
            {"type": "table", "name": "taiwan_futures_intraday_bar"},
            {"type": "derived", "name": "app.market.tw_futures"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_stock_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    bars: int = 120,
    revenue_months: int = 12,
    financial_quarters: int = 8,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []

    try:
        stock = stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = market_service.get_latest_stock_daily_price(db, normalized_stock_id)
    latest_institutional = market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    latest_revenue = market_service.get_latest_stock_monthly_revenue(db, normalized_stock_id)
    latest_financial = market_service.get_latest_stock_financial_metric(db, normalized_stock_id)
    shareholding = market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = market_service.list_stock_monthly_revenue_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(revenue_months, 1),
    )
    financial_history = market_service.list_stock_financial_metric_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(financial_quarters, 1),
    )
    chart = market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
    )
    branch_summary = get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=timeframe,
                include_intraday=False,
            )
        except Exception as exc:
            warnings.append(f"{timeframe.title()} technical report unavailable: {exc}")
            missing.append(f"technical_report.{timeframe}")

    if include_intraday or normalized_horizon == "intraday":
        try:
            technical_reports["today"] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe="today",
                include_intraday=include_intraday,
            )
        except Exception as exc:
            warnings.append(f"Today technical report unavailable: {exc}")
            missing.append("technical_report.today")

    if normalized_horizon == "intraday" and not include_intraday:
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
    )
    overnight_impact: dict[str, Any] | None = None

    if stock is not None:
        try:
            overnight_impact = build_us_overnight_impact_report(
                db=db,
                stock_id=normalized_stock_id,
            )
            for warning in overnight_impact.get("warnings") or []:
                warnings.append(f"US overnight impact warning: {warning}")
            if overnight_impact.get("missing"):
                warnings.append(
                    "US overnight impact is partial: "
                    + ", ".join(str(value) for value in overnight_impact.get("missing", [])[:5])
                )
        except Exception as exc:
            warnings.append(f"US overnight impact unavailable: {exc}")
            missing.append("us_overnight_tw_impact")

    if branch_summary.get("is_partial"):
        warnings.append(
            "Broker branch data is partial for the requested window: "
            f"{branch_summary.get('available_days')} / {branch_summary.get('requested_days')} days."
        )

    _add_missing(missing, "market_daily_price", latest_daily)
    _add_missing(missing, "institutional_trade_daily", latest_institutional)
    _add_missing(missing, "margin_trading_daily", latest_margin)
    _add_missing(missing, "shareholding_distribution_weekly", shareholding)
    _add_missing(missing, "monthly_revenue", latest_revenue)
    _add_missing(missing, "financial_metric_quarterly", latest_financial)
    _add_missing(missing, "broker_branch_trade_daily", branch_summary.get("buy_top") or branch_summary.get("sell_top"))
    _add_missing(missing, "us_overnight_tw_impact", overnight_impact)

    as_of = _latest_date_string(
        [
            getattr(latest_daily, "trade_date", None),
            getattr(latest_institutional, "trade_date", None),
            getattr(latest_margin, "trade_date", None),
            branch_summary.get("trade_date"),
            getattr(latest_revenue, "period", None),
            getattr(latest_financial, "report_date", None),
            overnight_impact.get("as_of") if isinstance(overnight_impact, dict) else None,
        ]
    )

    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "institutional_trade_daily"},
        {"type": "table", "name": "margin_trading_daily"},
        {"type": "table", "name": "shareholding_distribution_weekly"},
        {"type": "table", "name": "broker_branch_trade_daily"},
        {"type": "table", "name": "monthly_revenue"},
        {"type": "table", "name": "financial_metric_quarterly"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.calendar_status"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    market_calendar_status = build_taiwan_calendar_status()
    source_health = build_taiwan_source_health(
        db=db,
        stock_id=normalized_stock_id,
    )
    source_refs.append({"type": "derived", "name": "app.market.source_health"})

    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if include_intraday:
        try:
            quote_depth = get_taiwan_stock_quote_depth(
                db=db,
                stock_id=normalized_stock_id,
                refresh=True,
            )
            _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "taiwan_quote_depth"})
        except Exception as exc:
            quote_error = str(exc) or exc.__class__.__name__
            warnings.append(f"Taiwan quote depth unavailable: {quote_error}")
            missing.append("quote_depth")

    quote = _compact_quote_snapshot(
        latest_daily=latest_daily,
        quote_depth=quote_depth,
        quote_error=quote_error,
        session_phase=market_calendar_status.get("phase"),
    )
    intraday_bars = _compact_intraday_bars(
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
    )
    if intraday_bars.get("enabled"):
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_intraday_bar"})
        for warning in intraday_bars.get("warnings") or []:
            warnings.append(str(warning))
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append("intraday_bars")
    intraday_latest_times = [
        item.get("to_time")
        for item in (intraday_bars.get("series") or {}).values()
        if isinstance(item, dict) and item.get("to_time")
    ]
    compact_as_of = _latest_date_string(
        [
            as_of,
            quote.get("quote_time"),
            quote.get("trade_date"),
            *intraday_latest_times,
        ]
    )

    decision_evidence = _stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=market_calendar_status,
        missing=missing,
        source_refs=source_refs,
    )

    envelope = {
        "kind": "stock_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "latest_daily": _row_dict(
                latest_daily,
                (
                    "trade_date",
                    "stock_id",
                    "stock_name",
                    "trade_volume",
                    "trade_value",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "price_change",
                    "transaction_count",
                ),
            ),
            "chart": {
                **chart,
                "from_date": _json_value(chart.get("from_date")),
                "to_date": _json_value(chart.get("to_date")),
                "points": [
                    {key: _json_value(value) for key, value in point.items()}
                    for point in chart.get("points", [])
                ],
            },
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "compact": _build_stock_compact_evidence(
                stock=stock,
                stock_id=normalized_stock_id,
                as_of=compact_as_of or as_of,
                latest_daily=latest_daily,
                latest_institutional=latest_institutional,
                latest_margin=latest_margin,
                shareholding=shareholding,
                branch_summary=branch_summary,
                latest_revenue=latest_revenue,
                revenue_history=revenue_history,
                latest_financial=latest_financial,
                financial_history=financial_history,
                technical_reports=technical_reports,
                technical_analysis=technical_analysis,
                technical_levels=technical_levels,
                quote=quote,
                intraday_bars=intraday_bars,
                source_health=source_health,
                overnight_impact=overnight_impact,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
            ),
            "market_calendar_status": market_calendar_status,
            "source_health": source_health,
            "decision_evidence": decision_evidence,
            "overnight_impact": overnight_impact,
            "latest_institutional": _row_dict(
                latest_institutional,
                (
                    "trade_date",
                    "foreign_investor_net",
                    "investment_trust_net",
                    "dealer_net",
                    "total_institutional_net",
                ),
            ),
            "latest_margin": _row_dict(
                latest_margin,
                (
                    "trade_date",
                    "margin_buy",
                    "margin_sell",
                    "margin_today_balance",
                    "short_sale",
                    "short_covering",
                    "short_today_balance",
                ),
            ),
            "latest_shareholding": [
                _row_dict(
                    row,
                    (
                        "data_date",
                        "holding_level",
                        "holder_count",
                        "share_count",
                        "share_ratio",
                    ),
                )
                for row in shareholding
            ],
            "broker_branch": {
                **branch_summary,
                "trade_date": _json_value(branch_summary.get("trade_date")),
                "trade_dates": [_json_value(value) for value in branch_summary.get("trade_dates", [])],
                "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])],
                "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])],
            },
            "latest_revenue": _row_dict(
                latest_revenue,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            ),
            "revenue_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "monthly_revenue",
                        "month_over_month_pct",
                        "year_over_year_pct",
                        "cumulative_revenue",
                        "cumulative_year_over_year_pct",
                    ),
                )
                for row in revenue_history
            ],
            "latest_financial": _row_dict(
                latest_financial,
                (
                    "period",
                    "report_date",
                    "revenue",
                    "gross_profit",
                    "operating_income",
                    "net_income",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            ),
            "financial_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "report_date",
                        "revenue",
                        "gross_profit",
                        "operating_income",
                        "net_income",
                        "eps",
                        "book_value_per_share",
                        "roe",
                        "roa",
                    ),
                )
                for row in financial_history
            ],
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
    radar_mode: str = "action",
    radar_limit: int = 12,
) -> dict[str, Any]:
    group = watchlist_service.get_group(db=db, group_id=group_id)
    ranking = ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        use_intraday=False,
    )
    radar = radar_service.build_watchlist_radar_from_ranking(
        ranking=ranking,
        include_children=include_children,
        mode=radar_mode,
        max_results=max(1, min(int(radar_limit or 12), 200)),
    )
    radar["group_id"] = group_id
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context and radar use local daily indicator data and do not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")
    if radar.get("error_count"):
        missing.append("watchlist_radar_error_items")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])
    radar_as_of = _latest_date_string(
        [item.get("time") or item.get("trade_date") for item in radar.get("results", [])]
    )

    envelope = {
        "kind": "watchlist_context",
        "generated_at": _now(),
        "as_of": ranked_as_of or radar_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
            "radar_mode": radar.get("mode") or radar_mode,
        },
        "data": {
            "ranking": ranking,
            "radar": radar,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "service", "name": "watchlist_radar"},
        ],
    }
    return _with_evidence_passport(envelope)
