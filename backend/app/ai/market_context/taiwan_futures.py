from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ai import technical_analysis
from app.ai.market_context.common import freshness_effective_status
from app.ai.market_context.taiwan_projection import (
    _json_value,
    _latest_date_string,
    _with_evidence_passport,
)
from app.ai.market_payload_contract import has_payload_value, payload_level, slot_envelope
from app.market.market_chips import market_chip_daily_to_dict
from app.market.tw_futures import (
    normalize_taiwan_futures_symbols,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)


normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_normalize_technical_points = technical_analysis._normalize_technical_points
_technical_report_from_points = technical_analysis._technical_report_from_points
_chart_from_points = technical_analysis._chart_from_points


@dataclass(frozen=True)
class TaiwanFuturesDependencies:
    get_latest_taiwan_futures_quotes: Callable[..., list[Any]]
    list_taiwan_futures_daily_bars: Callable[..., list[Any]]
    list_taiwan_futures_intraday_bars: Callable[..., list[Any]]
    get_latest_market_chip_daily: Callable[..., Any]
    list_market_chip_daily: Callable[..., list[Any]]
    now: Callable[[], datetime]
    build_taiwan_derivatives_summary: Callable[..., dict[str, Any]] | None = None


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def _finite_number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _window_change(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_finite_number(row.get(key)) for row in rows]
    available = [value for value in values if value is not None]
    if len(available) < 2:
        return None
    return available[-1] - available[0]


def _positioning_label(net_oi: float | None, net_change: float | None) -> str | None:
    if net_oi is None or net_change is None:
        return None
    if net_oi < 0 and net_change < 0:
        return "net_short_increasing"
    if net_oi < 0 and net_change > 0:
        return "net_short_covering"
    if net_oi > 0 and net_change > 0:
        return "net_long_increasing"
    if net_oi > 0 and net_change < 0:
        return "net_long_reducing"
    return "neutral"


def _nonzero_optional(value: Any) -> float | int | None:
    if not isinstance(value, (int, float)) or value == 0:
        return None
    return value


def _slot_status_from_payload(
    payload: Any,
    *,
    explicit_status: Any = None,
) -> str:
    normalized_status = freshness_effective_status(explicit_status)
    if normalized_status in {"partial", "missing", "stale", "blocked", "failed"}:
        return normalized_status
    if normalized_status in {"not_applicable", "not_requested"}:
        return normalized_status
    return "ready" if has_payload_value(payload) else "missing"


def _futures_slot(
    *,
    status: str,
    capability: str,
    payload_ref: str,
    payload_level_value: str,
    as_of: Any = None,
    priority: str = "support",
    missing_key: str | None = None,
    warning: str | None = None,
) -> dict[str, Any]:
    missing = [missing_key or capability] if status in {"missing", "blocked", "failed"} else []
    warnings = [warning] if warning else []
    if not warning and status in {"partial", "stale", "blocked", "failed"}:
        warnings.append(f"freshness_status={status}")
    return slot_envelope(
        status=status,
        capability=capability,
        payload_ref=payload_ref,
        payload_level=payload_level_value,
        priority=priority,
        as_of=str(as_of) if as_of is not None else None,
        missing=missing,
        warnings=warnings,
    )


def _compact_derivatives_summary(derivatives: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(derivatives, dict):
        return None
    options_chain = derivatives.get("options_chain") if isinstance(derivatives.get("options_chain"), dict) else {}
    large_traders = derivatives.get("large_traders") if isinstance(derivatives.get("large_traders"), dict) else {}
    term_structure = derivatives.get("term_structure") if isinstance(derivatives.get("term_structure"), dict) else {}
    return {
        "status": derivatives.get("status"),
        "as_of": derivatives.get("as_of"),
        "expected_trade_date": derivatives.get("expected_trade_date"),
        "is_stale": derivatives.get("is_stale"),
        "options_chain": {
            key: options_chain.get(key)
            for key in (
                "status",
                "trade_date",
                "contract_month",
                "spot_reference",
                "total_rows_for_contract",
                "calculated_rows",
                "projected_strike_count",
                "iv_skew",
                "calculation",
            )
            if key in options_chain
        },
        "large_traders": {
            "status": large_traders.get("status"),
            "trade_date": large_traders.get("trade_date"),
            "row_count": len(large_traders.get("rows") or []),
            "semantics": large_traders.get("semantics"),
        },
        "term_structure": {
            "status": term_structure.get("status"),
            "trade_date": term_structure.get("trade_date"),
            "curve_shape": term_structure.get("curve_shape"),
            "front_next_spread_points": term_structure.get("front_next_spread_points"),
            "row_count": len(term_structure.get("rows") or []),
        },
        "missing": list(derivatives.get("missing") or []),
        "warnings": list(derivatives.get("warnings") or []),
    }


def _bounded_chart(chart: dict[str, Any] | None, *, point_limit: int) -> dict[str, Any] | None:
    if not isinstance(chart, dict):
        return None
    output = dict(chart)
    points = chart.get("points") if isinstance(chart.get("points"), list) else []
    if points:
        output["point_count"] = chart.get("point_count") or len(points)
        output["returned_point_count"] = min(len(points), point_limit)
        output["points"] = points[-point_limit:]
    return output


def _taipei_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return value
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return parsed.isoformat()


def _futures_volume_chart(
    chart: dict[str, Any] | None,
    *,
    point_limit: int,
) -> dict[str, Any] | None:
    output = _bounded_chart(chart, point_limit=point_limit)
    if not isinstance(output, dict):
        return None
    source_points = (
        chart.get("points")
        if isinstance(chart, dict) and isinstance(chart.get("points"), list)
        else []
    )
    points = output.get("points") if isinstance(output.get("points"), list) else []
    has_volume = False
    sessions: list[str] = []
    normalized_points: list[dict[str, Any]] = []
    for raw_point in points:
        if not isinstance(raw_point, dict):
            continue
        point = dict(raw_point)
        point["time"] = _taipei_timestamp(point.get("time"))
        volume_contracts = point.get("volume_contracts")
        if volume_contracts is None:
            volume_contracts = point.get("volume")
        point["volume_contracts"] = volume_contracts
        point["volume_unit"] = "contracts"
        point["volume_semantics"] = "interval_contracts"
        point["volume_status"] = (
            "available" if volume_contracts is not None else "missing"
        )
        has_volume = has_volume or volume_contracts is not None
        session = str(point.get("session") or "").strip()
        if session and session not in sessions:
            sessions.append(session)
        normalized_points.append(point)
    output["points"] = normalized_points
    output["volume_unit"] = "contracts"
    output["volume_semantics"] = "interval_contracts"
    output["volume_status"] = "available" if has_volume else "missing"
    output["session"] = sessions[0] if len(sessions) == 1 else None
    output["sessions"] = sessions
    latest_volume_point = next(
        (
            point
            for point in reversed(source_points)
            if isinstance(point, dict)
            and (
                point.get("volume_contracts") is not None
                or point.get("volume") is not None
            )
        ),
        None,
    )
    output["volume_contracts"] = (
        latest_volume_point.get("volume_contracts")
        if isinstance(latest_volume_point, dict)
        and latest_volume_point.get("volume_contracts") is not None
        else latest_volume_point.get("volume")
        if isinstance(latest_volume_point, dict)
        else None
    )
    output["volume_event_time"] = (
        _taipei_timestamp(latest_volume_point.get("time"))
        if isinstance(latest_volume_point, dict)
        else None
    )
    output["volume_status"] = (
        "available" if latest_volume_point is not None else "missing"
    )
    output["from_date"] = _taipei_timestamp(output.get("from_date"))
    output["to_date"] = _taipei_timestamp(output.get("to_date"))
    return output


def _build_tw_futures_compact(
    *,
    symbol: str,
    latest_quote: dict[str, Any] | None,
    latest_daily: dict[str, Any] | None,
    daily_chart: dict[str, Any],
    intraday_chart: dict[str, Any] | None,
    analysis: dict[str, Any],
    institutional_position: dict[str, Any] | None,
    options_sentiment: dict[str, Any] | None,
    market_chip_trend: dict[str, Any],
    derivatives: dict[str, Any] | None,
    payload_level_value: str,
) -> dict[str, Any]:
    raw_quote = latest_quote or {}
    quote_freshness = raw_quote.get("freshness") if isinstance(raw_quote.get("freshness"), dict) else {}
    quote_status = _slot_status_from_payload(
        raw_quote.get("last_price"),
        explicit_status=quote_freshness,
    )
    quote_domain_freshness = {
        **quote_freshness,
        "dataset": "quote.snapshot",
        "capability": "quote.snapshot",
        "latest": raw_quote.get("quote_time"),
    }
    quote_domain_freshness.setdefault("status", quote_status)
    quote_domain_freshness.setdefault(
        "is_current",
        quote_status == "ready" and quote_freshness.get("is_stale") is not True,
    )
    daily_status = _slot_status_from_payload((latest_daily or {}).get("close_price"))
    intraday_status = _slot_status_from_payload(intraday_chart) if intraday_chart else "not_requested"
    institutional_values = [
        (institutional_position or {}).get("foreign_futures_net_oi"),
        (institutional_position or {}).get("foreign_futures_net_oi_change"),
    ]
    institutional_status = (
        "missing"
        if all(value is None for value in institutional_values)
        else "partial"
        if any(value is None for value in institutional_values)
        else "ready"
    )
    option_values = [
        (options_sentiment or {}).get("put_call_volume_ratio_pct"),
        (options_sentiment or {}).get("put_call_open_interest_ratio_pct"),
    ]
    options_status = (
        "missing"
        if all(value is None for value in option_values)
        else "partial"
        if any(value is None for value in option_values)
        else "ready"
    )
    trend_status = _slot_status_from_payload(
        market_chip_trend.get("latest"),
        explicit_status=market_chip_trend.get("status"),
    )
    derivatives_status = _slot_status_from_payload(
        derivatives,
        explicit_status={
            "status": (derivatives or {}).get("status"),
            "is_stale": (derivatives or {}).get("is_stale"),
        },
    )
    statuses = [
        quote_status,
        daily_status,
        institutional_status,
        options_status,
        trend_status,
        derivatives_status,
    ]
    if "failed" in statuses:
        data_quality_status = "failed"
    elif "blocked" in statuses:
        data_quality_status = "blocked"
    elif "stale" in statuses:
        data_quality_status = "stale"
    elif any(status in {"missing", "partial"} for status in statuses):
        data_quality_status = "partial"
    else:
        data_quality_status = "ready"

    quote = {
        key: raw_quote.get(key)
        for key in (
            "provider",
            "symbol",
            "contract_symbol",
            "contract_month",
            "session",
            "trade_date",
            "quote_time",
            "open_price",
            "high_price",
            "low_price",
            "last_price",
            "reference_price",
            "change",
            "change_pct",
            "total_volume",
            "bid_price",
            "bid_size",
            "ask_price",
            "ask_size",
            "source",
            "source_url",
            "fetched_at",
            "freshness",
        )
        if key in raw_quote
    }
    quote["settlement_price"] = _nonzero_optional(raw_quote.get("settlement_price"))
    quote["open_interest"] = _nonzero_optional(raw_quote.get("open_interest"))
    quote["total_volume_contracts"] = raw_quote.get("total_volume")
    quote["volume_unit"] = "contracts"
    quote["volume_semantics"] = "session_cumulative_contracts"
    quote["volume_status"] = (
        "available"
        if quote["total_volume_contracts"] is not None
        else "missing"
    )
    quote["field_status"] = {
        "settlement_price": "ready" if quote["settlement_price"] is not None else "missing",
        "open_interest": "ready" if quote["open_interest"] is not None else "missing",
    }

    daily_close = {
        "label": "daily_k_close",
        "trade_date": (latest_daily or {}).get("trade_date"),
        "contract_symbol": (latest_daily or {}).get("contract_symbol"),
        "close_price": (latest_daily or {}).get("close_price"),
        "change": (latest_daily or {}).get("change"),
        "change_pct": (latest_daily or {}).get("change_pct"),
        "source": (latest_daily or {}).get("source"),
    }
    chip_as_of = (institutional_position or {}).get("trade_date") or (options_sentiment or {}).get("trade_date")
    slots = {
        "identity": _futures_slot(
            status="ready",
            capability="target_identity",
            payload_ref="target",
            payload_level_value=payload_level_value,
            priority="core",
        ),
        "latest_session_quote": _futures_slot(
            status=quote_status,
            capability="futures_latest_session_quote",
            payload_ref="quote",
            payload_level_value=payload_level_value,
            as_of=raw_quote.get("quote_time"),
            priority="core",
            missing_key="taiwan_futures_quote_snapshot",
        ),
        "daily_chart": _futures_slot(
            status=daily_status,
            capability="futures_daily_ohlc_chart",
            payload_ref="daily_close,daily_chart",
            payload_level_value=payload_level_value,
            as_of=(latest_daily or {}).get("trade_date"),
            priority="core",
            missing_key="taiwan_futures_daily_bar",
        ),
        "intraday": _futures_slot(
            status=intraday_status,
            capability="futures_intraday_chart",
            payload_ref="intraday_chart",
            payload_level_value=payload_level_value,
            as_of=(intraday_chart or {}).get("to_date") if intraday_chart else None,
            missing_key="taiwan_futures_intraday_bar",
        ),
        "institutional_position": _futures_slot(
            status=institutional_status,
            capability="taifex_futures_institutional_open_interest",
            payload_ref="institutional_position",
            payload_level_value=payload_level_value,
            as_of=chip_as_of,
            priority="core",
            missing_key="taifex_futures_institutional_open_interest",
            warning="official_daily_post_close_not_live_night_session"
            if institutional_status != "missing"
            else None,
        ),
        "options_sentiment": _futures_slot(
            status=options_status,
            capability="taifex_put_call_ratio",
            payload_ref="options_sentiment",
            payload_level_value=payload_level_value,
            as_of=chip_as_of,
            priority="core",
            missing_key="taifex_put_call_ratio",
            warning="official_daily_post_close_not_live_night_session"
            if options_status != "missing"
            else None,
        ),
        "market_chip_trend": _futures_slot(
            status=trend_status,
            capability="taifex_market_chip_trend",
            payload_ref="market_chip_trend",
            payload_level_value=payload_level_value,
            as_of=market_chip_trend.get("as_of"),
            missing_key="market_chip_daily_trend",
        ),
        "derivatives": _futures_slot(
            status=derivatives_status,
            capability="taifex_derivatives_context",
            payload_ref="derivatives",
            payload_level_value=payload_level_value,
            as_of=(derivatives or {}).get("as_of"),
            missing_key="taifex_derivatives_context",
        ),
        "data_quality": _futures_slot(
            status=data_quality_status,
            capability="data_quality_and_freshness",
            payload_ref="freshness_by_domain,slots",
            payload_level_value=payload_level_value,
            priority="core",
        ),
    }
    point_limit = {
        "summary": 1,
        "compact": 80,
        "standard": 160,
        "full": 500,
    }.get(payload_level_value, 80)
    return {
        "kind": "tw_futures_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": payload_level_value,
        "target": {
            "type": "tw_futures",
            "id": symbol,
            "label": f"{symbol} 台指期",
            "market": "TW",
        },
        "quote": quote,
        "quote_semantics": {
            "label": "latest_session_trade",
            "session": raw_quote.get("session"),
            "as_of": raw_quote.get("quote_time"),
        },
        "daily_close": daily_close,
        "daily_chart": _bounded_chart(daily_chart, point_limit=point_limit),
        "intraday_chart": _futures_volume_chart(
            intraday_chart,
            point_limit=point_limit,
        ),
        "technical": {"analysis": analysis},
        "institutional_position": institutional_position,
        "options_sentiment": options_sentiment,
        "market_chip_trend": {
            key: market_chip_trend.get(key)
            for key in ("status", "as_of", "coverage", "latest", "windows")
        },
        "derivatives": _compact_derivatives_summary(derivatives),
        "freshness_by_domain": {
            "quote": quote_domain_freshness,
            "chart": daily_status,
            "latest_session_quote": quote_status,
            "daily": daily_status,
            "intraday": intraday_status,
            "institutional_position": institutional_status,
            "options_sentiment": options_status,
            "market_chip_trend": trend_status,
            "derivatives": derivatives_status,
        },
        "slots": slots,
    }


def _market_chip_trend(rows: list[Any]) -> dict[str, Any]:
    history = [
        item
        for row in rows
        if isinstance(item := _json_dict(market_chip_daily_to_dict(row)), dict)
    ]
    if not history:
        return {
            "status": "missing",
            "as_of": None,
            "coverage": {"requested_days": 20, "available_days": 0, "is_partial": True},
            "latest": None,
            "windows": {},
            "daily": [],
        }

    latest = history[-1]
    windows: dict[str, Any] = {}
    for days in (3, 5, 20):
        window_rows = history[-days:]
        foreign_oi = _finite_number(latest.get("foreign_futures_net_oi"))
        foreign_oi_change = _window_change(window_rows, "foreign_futures_net_oi")
        pcr_oi_change = _window_change(window_rows, "put_call_open_interest_ratio_pct")
        index_change = _window_change(window_rows, "close_value")
        first_close = _finite_number(window_rows[0].get("close_value")) if window_rows else None
        index_change_pct = (
            index_change / first_close * 100
            if index_change is not None and first_close not in {None, 0}
            else None
        )
        windows[f"{days}d"] = {
            "requested_days": days,
            "available_days": len(window_rows),
            "is_partial": len(window_rows) < days,
            "from_date": window_rows[0].get("trade_date") if window_rows else None,
            "to_date": window_rows[-1].get("trade_date") if window_rows else None,
            "foreign_futures_net_oi": foreign_oi,
            "foreign_futures_net_oi_change": foreign_oi_change,
            "change_semantics": "latest_net_oi_minus_first_available_net_oi",
            "foreign_positioning": _positioning_label(foreign_oi, foreign_oi_change),
            "put_call_open_interest_ratio_pct": latest.get("put_call_open_interest_ratio_pct"),
            "put_call_open_interest_ratio_change_pct_points": pcr_oi_change,
            "put_call_volume_ratio_pct": latest.get("put_call_volume_ratio_pct"),
            "index_change_pct": index_change_pct,
            "short_price_divergence": bool(
                foreign_oi is not None
                and foreign_oi_change is not None
                and index_change_pct is not None
                and foreign_oi < 0
                and foreign_oi_change < 0
                and index_change_pct > 0
            ),
        }

    required_keys = (
        "foreign_futures_net_oi",
        "put_call_open_interest_ratio_pct",
        "put_call_volume_ratio_pct",
    )
    complete_days = sum(
        1 for row in history if all(row.get(key) is not None for key in required_keys)
    )
    status = "ready" if len(history) >= 20 and complete_days == len(history) else "partial"
    return {
        "status": status,
        "as_of": latest.get("trade_date"),
        "coverage": {
            "requested_days": 20,
            "available_days": len(history),
            "complete_days": complete_days,
            "is_partial": len(history) < 20 or complete_days < len(history),
        },
        "latest": {
            key: latest.get(key)
            for key in (
                "trade_date",
                "close_value",
                "price_change_pct",
                "foreign_futures_net_oi",
                "foreign_futures_net_oi_change",
                "retail_futures_net_oi",
                "put_call_volume_ratio_pct",
                "put_call_open_interest_ratio_pct",
                "source_grade",
            )
        },
        "windows": windows,
        "daily": [
            {
                key: row.get(key)
                for key in (
                    "trade_date",
                    "close_value",
                    "price_change_pct",
                    "foreign_futures_net_oi",
                    "foreign_futures_net_oi_change",
                    "retail_futures_net_oi",
                    "put_call_volume_ratio_pct",
                    "put_call_open_interest_ratio_pct",
                    "source_grade",
                )
            }
            for row in history
        ],
    }


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanFuturesDependencies,
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan futures context uses TAIFEX futures quote and bar tables, not stock_master or stock daily tables.",
    ]

    quote_rows = dependencies.get_latest_taiwan_futures_quotes(db, symbols=[normalized_symbol], refresh=False)
    quote_dicts = [_json_dict(taiwan_futures_quote_to_dict(row)) for row in quote_rows]
    latest_quote = quote_dicts[0] if quote_dicts else None
    if latest_quote is None:
        missing.append("taiwan_futures_quote_snapshot")

    market_chip_row = dependencies.get_latest_market_chip_daily(db, index_id="TAIEX")
    market_chip_rows = dependencies.list_market_chip_daily(
        db,
        index_id="TAIEX",
        limit=20,
    )
    market_chip_trend = _market_chip_trend(market_chip_rows)
    market_chip = (
        _json_dict(
            market_chip_daily_to_dict(
                market_chip_row,
                db=db,
                resolve_expected_margin=True,
            )
        )
        if market_chip_row is not None
        else None
    )
    institutional_position = None
    options_sentiment = None
    if market_chip is None:
        missing.extend(
            [
                "market_chip_daily",
                "taifex_futures_institutional_open_interest",
                "taifex_put_call_ratio",
            ]
        )
        if market_chip_trend.get("status") == "missing":
            missing.append("market_chip_daily_trend")
    else:
        institutional_position = {
            "trade_date": market_chip.get("trade_date"),
            "foreign_futures_net_oi": market_chip.get("foreign_futures_net_oi"),
            "foreign_futures_net_oi_change": market_chip.get(
                "foreign_futures_net_oi_change"
            ),
            "retail_futures_net_oi": market_chip.get("retail_futures_net_oi"),
            "retail_futures_net_oi_change": market_chip.get(
                "retail_futures_net_oi_change"
            ),
        }
        options_sentiment = {
            "trade_date": market_chip.get("trade_date"),
            "put_volume": market_chip.get("put_volume"),
            "call_volume": market_chip.get("call_volume"),
            "put_call_volume_ratio_pct": market_chip.get(
                "put_call_volume_ratio_pct"
            ),
            "put_open_interest": market_chip.get("put_open_interest"),
            "call_open_interest": market_chip.get("call_open_interest"),
            "put_call_open_interest_ratio_pct": market_chip.get(
                "put_call_open_interest_ratio_pct"
            ),
        }
        if institutional_position["foreign_futures_net_oi"] is None:
            missing.append("taifex_futures_institutional_open_interest")
        if (
            options_sentiment["put_call_volume_ratio_pct"] is None
            or options_sentiment["put_call_open_interest_ratio_pct"] is None
        ):
            missing.append("taifex_put_call_ratio")
        warnings.append(
            "Institutional futures open interest and Put/Call Ratio are official daily post-close chip data; they do not represent live changes during the current night session."
        )

    derivatives = None
    derivative_params = market_data_params or {}
    if normalized_symbol != "TXF":
        derivatives = {
            "status": "not_applicable",
            "as_of": None,
            "scope": {"symbol": normalized_symbol},
            "reason": "The connected TAIFEX option-chain, large-trader, and term-structure contract currently covers TX/TXO only.",
            "missing": [],
            "warnings": [],
        }
    elif dependencies.build_taiwan_derivatives_summary is not None:
        option_contract_month = str(
            derivative_params.get("option_contract_month") or ""
        ).strip() or None
        raw_strike_limit = derivative_params.get("option_strike_limit", 11)
        option_strike_limit = (
            int(raw_strike_limit)
            if isinstance(raw_strike_limit, (int, float))
            else 11
        )
        derivatives = dependencies.build_taiwan_derivatives_summary(
            db,
            option_contract_month=option_contract_month,
            option_strike_limit=option_strike_limit,
        )
        derivative_missing = derivatives.get("missing")
        if isinstance(derivative_missing, list):
            missing.extend(str(item) for item in derivative_missing if item)
        derivative_warnings = derivatives.get("warnings")
        if isinstance(derivative_warnings, list):
            warnings.extend(str(item) for item in derivative_warnings if item)
    elif normalized_symbol == "TXF":
        missing.extend(
            [
                "taifex_txo_option_chain",
                "taifex_large_trader_positions",
                "taifex_txf_term_structure",
            ]
        )

    daily_rows = dependencies.list_taiwan_futures_daily_bars(
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
        intraday_rows = dependencies.list_taiwan_futures_intraday_bars(
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
    if intraday_dicts:
        latest_intraday_row = intraday_dicts[-1]
        intraday_chart.update(
            {
                "interval": latest_intraday_row.get("interval") or "1m",
                "source": latest_intraday_row.get("source"),
                "provider": latest_intraday_row.get("provider"),
            }
        )
    as_of = _latest_date_string(
        [
            (latest_quote or {}).get("quote_time"),
            daily_chart.get("to_date"),
            intraday_chart.get("to_date"),
            (market_chip or {}).get("trade_date"),
            (derivatives or {}).get("as_of"),
        ]
    )
    compact = _build_tw_futures_compact(
        symbol=normalized_symbol,
        latest_quote=latest_quote,
        latest_daily=daily_dicts[-1] if daily_dicts else None,
        daily_chart=daily_chart,
        intraday_chart=intraday_chart if intraday_points else None,
        analysis=technical_analysis,
        institutional_position=institutional_position,
        options_sentiment=options_sentiment,
        market_chip_trend=market_chip_trend,
        derivatives=derivatives,
        payload_level_value=payload_level(market_data_params),
    )

    envelope = {
        "kind": "tw_futures_context",
        "generated_at": dependencies.now(),
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
            "market_chip": market_chip,
            "institutional_position": institutional_position,
            "options_sentiment": options_sentiment,
            "market_chip_trend": market_chip_trend,
            "derivatives": derivatives,
            "compact": compact,
            "slots": compact["slots"],
        },
        "data_limitations": [
            "Latest-session quote and daily K close use separate timestamps and must not be treated as the same price.",
            "Institutional futures open interest and Put/Call Ratio are official daily post-close data, not live night-session positioning.",
            "Unavailable quote fields remain null with field_status=missing; zero is not used as a success fallback.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "taiwan_futures_quote_snapshot"},
            {"type": "table", "name": "taiwan_futures_daily_bar"},
            {"type": "table", "name": "taiwan_futures_intraday_bar"},
            {"type": "table", "name": "market_chip_daily"},
            {"type": "table", "name": "taiwan_option_chain_daily"},
            {"type": "table", "name": "taiwan_derivatives_large_trader_daily"},
            {"type": "table", "name": "taiwan_futures_term_structure_daily"},
            {"type": "derived", "name": "app.market.tw_futures"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )
