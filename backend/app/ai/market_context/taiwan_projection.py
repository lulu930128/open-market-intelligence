from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import (
    COMPACT_INTRADAY_BAR_LIMIT,
    PAYLOAD_LEVELS,
    has_payload_value as _has_payload_value,
    intraday_point_limit as _intraday_point_limit,
    payload_level as _payload_level,
    payload_slot_status as _payload_slot_status,
    requested_intraday_interval as _requested_intraday_interval,
    slot_envelope as _slot_envelope,
)
from app.db.models import FinancialMetricQuarterly, StockMaster
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.financial_contract import (
    FINANCIAL_CONTRACT_VERSION,
    build_legacy_financial_contract,
)
from app.market.financial_metric_semantics import source_reported_financial_semantics
from app.market.index_resolution import resolve_taiwan_index_quote_state
from app.market.live_snapshot import classify_market_snapshot
from app.market.monthly_revenue_continuity import analyze_monthly_revenue_continuity
from app.market.quote_volume import build_taiwan_quote_volume_contract
from app.market.trading_calendar import (
    normalize_taiwan_session_phase,
    taiwan_session_is_auction,
)


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
        payload = {
            key: _json_value(value) for key, value in row.items()
        }
    else:
        payload = _row_dict(
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
    payload.update(
        {
            "currency": "TWD",
            "price_unit": "TWD",
            "quantity_unit": "lots",
            "lot_size": 1000,
        }
    )
    return payload


def _broker_branch_metadata(summary: dict[str, Any]) -> dict[str, Any]:
    aggregation = (
        summary.get("aggregation_window")
        if isinstance(summary.get("aggregation_window"), dict)
        else {}
    )
    return {
        "aggregation_window": {
            **aggregation,
            "anchor_trade_date": _json_value(
                aggregation.get("anchor_trade_date")
            ),
            "included_trade_dates": [
                _json_value(value)
                for value in aggregation.get("included_trade_dates") or []
            ],
        },
        "date_semantics": (
            dict(summary.get("date_semantics"))
            if isinstance(summary.get("date_semantics"), dict)
            else {}
        ),
    }


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
CAPABILITY_FRESHNESS_RESOURCES = {
    "daily.ohlcv": "market_daily_price",
    "technical.structure": "market_daily_price",
    "technical.indicators": "market_daily_price",
    "technical.swings": "market_daily_price",
    "technical.fibonacci": "market_daily_price",
    "technical.divergence": "market_daily_price",
    "technical.breakout": "market_daily_price",
    "technical.volume_profile": "market_daily_price",
    "technical.anchored_vwap": "market_daily_price",
    "technical.relative_strength": "market_daily_price",
    "chips.institutional": "institutional_trade_daily",
    "chips.margin": "margin_trading_daily",
    "broker_branch.summary": "broker_branch_trade_daily",
    "ownership.distribution": "shareholding_distribution_weekly",
    "fundamentals.revenue": "monthly_revenue",
    "fundamentals.financials": "financial_metric_quarterly",
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


def _fundamentals_slot_status(
    fundamentals: dict[str, Any],
    *,
    missing: list[str],
) -> str:
    status = _payload_slot_status(fundamentals, missing=missing)
    latest_financial = fundamentals.get("latest_financial")
    financial_contract = fundamentals.get("financial_contract")
    contract_quality = (
        financial_contract.get("quality")
        if isinstance(financial_contract, dict)
        and isinstance(financial_contract.get("quality"), dict)
        else {}
    )
    normalized_contract_ready = bool(
        isinstance(financial_contract, dict)
        and isinstance(financial_contract.get("normalized"), dict)
        and financial_contract["normalized"].get("status") == "ready"
        and contract_quality.get("decision_usable") is True
    )
    if (
        status == "ready"
        and not normalized_contract_ready
        and isinstance(latest_financial, dict)
        and latest_financial.get("normalization_status") not in {"normalized", "unchanged"}
    ):
        return "partial"
    revenue_continuity = fundamentals.get("revenue_continuity")
    if (
        status == "ready"
        and isinstance(revenue_continuity, dict)
        and not revenue_continuity.get("decision_usable", False)
    ):
        return "partial"
    return status


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
    cross_market: dict[str, Any] | None,
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
            status=_fundamentals_slot_status(
                fundamentals,
                missing=[key for key in missing if key in FRESHNESS_DOMAIN_RESOURCES["fundamentals"]],
            ),
            capability="tw_fundamentals",
            payload_ref="fundamentals",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "cross_market": _slot_envelope(
            status=(
                "missing"
                if not isinstance(cross_market, dict)
                else "partial"
                if cross_market.get("missing") or cross_market.get("warnings")
                else "ready"
            ),
            capability="cross_market_context",
            payload_ref="cross_market",
            payload_level=payload_level,
            as_of=cross_market.get("as_of") if isinstance(cross_market, dict) else None,
            missing=(
                list(cross_market.get("missing") or [])
                if isinstance(cross_market, dict)
                else ["us_overnight_tw_impact"]
            ),
            warnings=(
                list(cross_market.get("warnings") or [])
                if isinstance(cross_market, dict)
                else []
            ),
            next_fill="Refresh the bounded US overnight mapping when its local evidence is missing or stale.",
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
    sample_coverage: dict[str, Any],
    distribution: dict[str, Any],
    industry_rows: list[dict[str, Any]],
    index_intraday: dict[str, Any],
    cross_market: dict[str, Any],
    market_chips: dict[str, Any],
    volume_state: dict[str, Any],
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
            status=(
                str(breadth.get("status"))
                if breadth.get("status") in {
                    "pending",
                    "partial",
                    "stale",
                    "failed",
                }
                else _payload_slot_status(
                    breadth,
                    missing=[key for key in missing if key.startswith("market_breadth")],
                )
            ),
            capability="tw_market_breadth",
            payload_ref="breadth",
            payload_level=payload_level,
            priority="core",
            as_of=breadth.get("as_of") or breadth.get("trade_date") or as_of,
            missing=[
                f"market_breadth.{market.lower()}"
                for market in breadth.get("missing_markets", [])
            ],
        ),
        "distribution": _slot_envelope(
            status=(
                "partial"
                if distribution and sample_coverage.get("status") != "complete"
                else _payload_slot_status(distribution)
            ),
            capability="tw_market_distribution",
            payload_ref="distribution",
            payload_level=payload_level,
            as_of=as_of,
            missing=(
                ["market_daily_price.full_market_coverage"]
                if distribution and sample_coverage.get("status") != "complete"
                else []
            ),
        ),
        "sector_industry": _slot_envelope(
            status=(
                "partial"
                if industry_rows and sample_coverage.get("status") != "complete"
                else "ready"
                if industry_rows
                else "missing"
            ),
            capability="tw_industry_strength",
            payload_ref="top_industries,weak_industries",
            payload_level=payload_level,
            as_of=as_of,
            missing=(
                ["market_daily_price.full_market_coverage"]
                if industry_rows and sample_coverage.get("status") != "complete"
                else []
            ),
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
        "market_chips": _slot_envelope(
            status=str(market_chips.get("status") or "missing"),
            capability="tw_market_chips_and_rankings",
            payload_ref="market_chips",
            payload_level=payload_level,
            as_of=(
                (market_chips.get("official_market_aggregate") or {}).get("trade_dates", [None])[-1]
                if (market_chips.get("official_market_aggregate") or {}).get("trade_dates")
                else None
            ),
            missing=list(market_chips.get("missing") or []),
            warnings=list(market_chips.get("warnings") or []),
        ),
        "market_volume": _slot_envelope(
            status=str(volume_state.get("status") or "missing"),
            capability="tw_market_same_time_volume_pace",
            payload_ref="volume_state",
            payload_level=payload_level,
            priority="core",
            as_of=volume_state.get("as_of"),
            missing=(
                ["market_volume.same_time_baseline_20d"]
                if volume_state.get("status") != "ready"
                else []
            ),
            warnings=list(volume_state.get("warnings") or []),
            next_fill=(
                "Minute history accumulates from the existing Taiwan index scheduler without extra provider calls."
                if volume_state.get("status") != "ready"
                else None
            ),
        ),
        "cross_market": _slot_envelope(
            status=str(cross_market.get("status") or "missing"),
            capability="cross_market_context",
            payload_ref="cross_market",
            payload_level=payload_level,
            as_of=cross_market.get("as_of"),
            missing=list(cross_market.get("missing") or []),
            warnings=list(cross_market.get("warnings") or []),
            next_fill="Refresh only the missing provider caches through their bounded write endpoints.",
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


def _quote_provider_path(
    *,
    selected_provider: str | None,
    live_quote_requested: bool,
    fallback_used: bool,
    quote_error: str | None,
    refresh_outcome: str | None,
) -> dict[str, Any]:
    primary_provider = (
        "twse_mis"
        if live_quote_requested
        else selected_provider
    )
    attempts: list[dict[str, Any]] = []
    if live_quote_requested:
        attempts.append(
            {
                "provider": "twse_mis",
                "status": (
                    "success"
                    if selected_provider == "twse_mis"
                    and not fallback_used
                    else "failed"
                ),
                "error": quote_error,
            }
        )
    if selected_provider and (
        not attempts
        or fallback_used
        or selected_provider != attempts[-1].get("provider")
    ):
        attempts.append(
            {
                "provider": selected_provider,
                "status": "success",
                "error": None,
            }
        )
    return {
        "primary_provider": primary_provider,
        "selected_provider": selected_provider,
        "fallback_used": fallback_used,
        "fallback_provider": (
            selected_provider if fallback_used else None
        ),
        "fallback_reason": (
            quote_error or "live_quote_unavailable"
            if fallback_used
            else None
        ),
        "provider_attempts": attempts,
        "source_grade": (
            "official_realtime"
            if selected_provider == "twse_mis" and not fallback_used
            else "official_cache"
            if selected_provider == "local_daily_close"
            else "unavailable"
        ),
        "cache_hit": refresh_outcome == "cache_hit",
        "cache_written": refresh_outcome == "updated",
    }


def _compact_latest_daily_quote(
    latest_daily: Any,
    *,
    quote_error: str | None = None,
    session_phase: str | None = None,
    current_session_date: str | None = None,
    is_trading_day: bool | None = None,
    live_quote_requested: bool = True,
) -> dict[str, Any]:
    if latest_daily is None:
        quote = {
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
            "price_available": False,
            "last_trade_available": False,
            "last_trade_price": None,
            "last_trade_time": None,
            "last_trade_is_current_session": False,
            "last_trade_before_auction": False,
            "facts_usable_for_current_session": False,
            "fallback_quote": None,
            "depth_available": False,
            "depth_status": "unavailable",
            "auction_book_available": False,
            "auction_book_status": "unavailable",
            "auction_book_time": None,
            "auction_best_bid": None,
            "auction_best_ask": None,
            "auction_indicative_available": False,
            "indicative_match_available": False,
            "indicative_match_price": None,
            "indicative_match_volume_lots": None,
            "indicative_price_available": False,
            "indicative_price": None,
            "indicative_bid": None,
            "indicative_ask": None,
            "official_close_available": False,
            "official_close_status": "unavailable",
            "official_close_price": None,
            "official_close_trade_date": None,
            "official_close_source": None,
            "quote_semantics": "unavailable",
            "delivery_status": "unavailable",
            "fallback_used": False,
            "is_realtime": False,
            "latency_ms": None,
            "freshness": {
                "status": "missing",
                "is_live": False,
                "is_stale": True,
                "message": quote_error or "No local daily close is available.",
            },
        }
        quote.update(
            _quote_provider_path(
                selected_provider=None,
                live_quote_requested=live_quote_requested,
                fallback_used=False,
                quote_error=quote_error,
                refresh_outcome=None,
            )
        )
        return quote

    close_price = _json_value(getattr(latest_daily, "close_price", None))
    trade_date = _json_value(getattr(latest_daily, "trade_date", None))
    daily_volume_shares = getattr(latest_daily, "trade_volume", None)
    prior_session_close = (
        close_price - _json_value(getattr(latest_daily, "price_change", 0))
        if close_price is not None and getattr(latest_daily, "price_change", None) is not None
        else None
    )
    change_pct = (
        (_json_value(getattr(latest_daily, "price_change", None)) / prior_session_close) * 100
        if prior_session_close not in {None, 0}
        else None
    )
    active_session = session_phase in {
        "preopen_pending",
        "preopen",
        "regular",
        "regular_live",
        "closing_auction",
    }
    post_close = session_phase in {"post_close", "post_close_snapshot"}
    current_close_available = bool(
        post_close
        and current_session_date
        and str(trade_date) == str(current_session_date)
    )
    latest_session_close_available = bool(
        (
            not live_quote_requested
            or (
                not active_session
                and not post_close
                and is_trading_day is False
            )
        )
        and close_price is not None
    )
    official_close_available = bool(
        current_close_available or latest_session_close_available
    )
    if not live_quote_requested and latest_session_close_available:
        official_close_status = "confirmed_latest_session"
        quote_semantics = "latest_completed_session_close"
        delivery_status = "latest_completed_session"
    elif current_close_available:
        official_close_status = "confirmed"
        quote_semantics = "official_close"
        delivery_status = "official_close"
    elif post_close:
        official_close_status = "pending"
        quote_semantics = "official_close_pending"
        delivery_status = "official_close_pending"
    elif latest_session_close_available:
        official_close_status = "confirmed_latest_session"
        quote_semantics = "latest_completed_session_close"
        delivery_status = "latest_completed_session"
    elif session_phase == "closing_auction":
        official_close_status = "closing_auction_pending"
        quote_semantics = "previous_close_fallback"
        delivery_status = "closing_auction"
    elif session_phase in {"preopen_pending", "preopen"}:
        official_close_status = "not_available_yet"
        quote_semantics = "previous_close_fallback"
        delivery_status = "previous_close"
    else:
        official_close_status = "not_available_yet"
        quote_semantics = "previous_close_fallback"
        delivery_status = "previous_close"
    previous_close = (
        prior_session_close if official_close_available else close_price
    )
    public_price = close_price if official_close_available else None
    quote = {
        "kind": "quote_snapshot",
        "source": "market_daily_price",
        "provider": "local_daily_close",
        "status": (
            "delayed_daily_close"
            if not live_quote_requested and latest_session_close_available
            else "official_close"
            if official_close_available
            else "official_close_pending"
            if post_close
            else "closing_auction_pending"
            if session_phase == "closing_auction"
            else "preopen_no_last_trade"
            if session_phase in {"preopen_pending", "preopen"}
            else "current_session_quote_unavailable"
        ),
        "session_phase": session_phase,
        "trade_date": trade_date,
        "quote_time": None,
        "latest_price": public_price,
        "price": public_price,
        "last_price": None,
        "previous_close": previous_close,
        "open_price": (
            _json_value(getattr(latest_daily, "open_price", None))
            if official_close_available
            else None
        ),
        "high_price": (
            _json_value(getattr(latest_daily, "high_price", None))
            if official_close_available
            else None
        ),
        "low_price": (
            _json_value(getattr(latest_daily, "low_price", None))
            if official_close_available
            else None
        ),
        "change": (
            _json_value(getattr(latest_daily, "price_change", None))
            if official_close_available
            else None
        ),
        "change_pct": change_pct if official_close_available else None,
        "total_volume_lots": (
            int(daily_volume_shares / 1000)
            if (
                official_close_available
                and daily_volume_shares is not None
            )
            else None
        ),
        "cumulative_volume_lots": (
            int(daily_volume_shares / 1000)
            if official_close_available
            and daily_volume_shares is not None
            else None
        ),
        "cumulative_volume_shares": (
            int(daily_volume_shares)
            if official_close_available
            and daily_volume_shares is not None
            else None
        ),
        "volume_unit": "lots",
        "canonical_volume_unit": "shares",
        "lot_size": 1000,
        "volume_semantics": "official_daily_total_volume",
        "volume_scope": "official_daily_all_reported_trades",
        "volume_source": "market_daily_price",
        "volume_includes_odd_lot": None,
        "volume_includes_after_hours": None,
        "volume_includes_closing_auction": True,
        "volume_reconciliation": {
            "reference_dataset": "market_daily_price",
            "reference_trade_date": trade_date,
            "reference_volume_shares": (
                int(daily_volume_shares)
                if daily_volume_shares is not None
                else None
            ),
            "snapshot_trade_date": trade_date,
            "snapshot_volume_shares": (
                int(daily_volume_shares)
                if daily_volume_shares is not None
                else None
            ),
            "difference_shares": 0
            if daily_volume_shares is not None
            else None,
            "difference_pct": 0.0
            if daily_volume_shares is not None
            else None,
            "status": "reconciled"
            if daily_volume_shares is not None
            else "not_comparable",
            "reason": "same_official_daily_dataset",
            "decision_usable": daily_volume_shares is not None,
        },
        "volume_decision_usable": daily_volume_shares is not None,
        "price_decision_usable": official_close_available,
        "currency": "TWD",
        "price_unit": "TWD",
        "price_available": official_close_available,
        "last_trade_available": False,
        "last_trade_price": None,
        "last_trade_time": None,
        "last_trade_is_current_session": False,
        "last_trade_before_auction": False,
        "facts_usable_for_current_session": bool(
            official_close_available and current_close_available
        ),
        "fallback_quote": (
            {
                "price": close_price,
                "trade_date": trade_date,
                "source": "market_daily_price",
                "provider": "local_daily_close",
                "semantics": "latest_completed_session_reference",
                "current_session": False,
            }
            if live_quote_requested
            and close_price is not None
            and not official_close_available
            else None
        ),
        "depth_available": False,
        "depth_status": "unavailable",
        "auction_book_available": False,
        "auction_book_status": "unavailable",
        "auction_book_time": None,
        "auction_best_bid": None,
        "auction_best_ask": None,
        "auction_indicative_available": False,
        "indicative_match_available": False,
        "indicative_match_price": None,
        "indicative_match_volume_lots": None,
        "indicative_price_available": False,
        "indicative_price": None,
        "indicative_bid": None,
        "indicative_ask": None,
        "official_close_available": official_close_available,
        "official_close_status": official_close_status,
        "official_close_price": (
            close_price if official_close_available else None
        ),
        "official_close_trade_date": (
            trade_date if official_close_available else None
        ),
        "official_close_source": (
            "market_daily_price.close_price"
            if official_close_available
            else None
        ),
        "quote_semantics": quote_semantics,
        "delivery_status": delivery_status,
        "fallback_used": live_quote_requested,
        "is_realtime": False,
        "latency_ms": None,
        "freshness": {
            "status": (
                "latest_completed_session"
                if not live_quote_requested and latest_session_close_available
                else "official_close"
                if official_close_available
                else "official_close_pending"
                if post_close
                else "latest_completed_session"
            ),
            "is_live": False,
            "is_stale": False,
            "message": quote_error
            or "No live quote was available for this response; using the latest local daily close.",
        },
    }
    quote.update(
        _quote_provider_path(
            selected_provider="local_daily_close",
            live_quote_requested=live_quote_requested,
            fallback_used=bool(live_quote_requested),
            quote_error=quote_error,
            refresh_outcome=None,
        )
    )
    return quote


def _component_freshness(
    quote: dict[str, Any],
    *,
    dataset: str,
    status: str,
    available: bool,
    event_time: Any,
) -> dict[str, Any]:
    quote_freshness = (
        quote.get("freshness")
        if isinstance(quote.get("freshness"), dict)
        else {}
    )
    normalized_status = str(status or "unavailable")
    is_stale = bool(quote_freshness.get("is_stale"))
    is_current = bool(
        available
        and not is_stale
        and normalized_status
        not in {"missing", "stale", "unavailable", "pending"}
    )
    return {
        "status": normalized_status,
        "dataset": dataset,
        "is_current": is_current,
        "latest": _json_value(event_time),
        "expected": _json_value(
            quote_freshness.get("expected_trade_date")
        ),
        "event_time_basis": (
            "provider_event_time"
            if event_time
            else "taiwan_completed_trade_date"
        ),
        "age_seconds": quote_freshness.get("age_seconds"),
        "latency_ms": quote.get("latency_ms"),
        "provider": quote.get("provider"),
        "source": quote.get("source"),
        "refresh_recommended": normalized_status
        in {
            "missing",
            "stale",
            "unavailable",
            "unavailable_after_release",
        },
        "reason": quote_freshness.get("message"),
    }


def _quote_components(quote: dict[str, Any]) -> dict[str, Any]:
    session_phase = str(
        quote.get("session_phase")
        or quote.get("current_session_phase")
        or ""
    )
    canonical_session_phase = normalize_taiwan_session_phase(session_phase)
    instrument_phase = str(quote.get("instrument_phase") or "").strip()
    post_close = canonical_session_phase in {
        "post_close",
        "market_closed",
    }
    data_core_components = (
        quote.get("data_core_components")
        if isinstance(quote.get("data_core_components"), dict)
        else {}
    )
    order_book_evidence = (
        data_core_components.get("quote.order_book")
        if isinstance(data_core_components.get("quote.order_book"), dict)
        else {}
    )
    auction_evidence = (
        data_core_components.get("quote.auction")
        if isinstance(data_core_components.get("quote.auction"), dict)
        else {}
    )
    official_close_evidence = (
        data_core_components.get("quote.official_close")
        if isinstance(data_core_components.get("quote.official_close"), dict)
        else {}
    )
    session_close_evidence = (
        data_core_components.get("quote.session_close")
        if isinstance(data_core_components.get("quote.session_close"), dict)
        else {}
    )
    depth_available = bool(quote.get("depth_available"))
    depth_status = (
        "current"
        if depth_available
        and not bool((quote.get("freshness") or {}).get("is_stale"))
        else "not_applicable"
        if post_close
        else str(quote.get("depth_status") or "unavailable")
    )
    snapshot_time = (
        quote.get("snapshot_time")
        or quote.get("provider_event_time")
        or quote.get("quote_time")
    )
    order_book_freshness = _component_freshness(
        quote,
        dataset="taiwan_quote_order_book",
        status=depth_status,
        available=depth_available,
        event_time=snapshot_time,
    )
    order_book_freshness.update(
        {
            "provider": order_book_evidence.get("provider") or quote.get("provider"),
            "source": order_book_evidence.get("source") or quote.get("source"),
            "resolved_health": order_book_evidence.get("resolved_health"),
            "dataset_health": order_book_evidence.get("dataset_health"),
        }
    )
    if post_close and not depth_available:
        order_book_freshness.update(
            {
                "status": "latest_completed_session",
                "is_current": True,
                "refresh_possible_now": False,
                "refresh_recommended": False,
                "applicability_status": "not_applicable",
                "reason_code": "MARKET_CLOSED_ORDER_BOOK_UNAVAILABLE",
            }
        )
    order_book = {
        "kind": "quote_order_book",
        "status": depth_status,
        "available": depth_available,
        "applicability_status": (
            "not_applicable"
            if post_close and not depth_available
            else "applicable"
        ),
        "availability_status": (
            "available" if depth_available else "unavailable"
        ),
        "unavailable_reason_code": (
            "MARKET_CLOSED_ORDER_BOOK_UNAVAILABLE"
            if post_close and not depth_available
            else None
        ),
        "market_session_status": session_phase or None,
        "canonical_session_phase": canonical_session_phase,
        "refresh_possible_now": not post_close,
        "refresh_recommended": bool(
            not depth_available and not post_close
        ),
        "best_bid_price": quote.get("best_bid_price"),
        "best_bid_size_lots": quote.get("best_bid_size_lots"),
        "best_ask_price": quote.get("best_ask_price"),
        "best_ask_size_lots": quote.get("best_ask_size_lots"),
        "spread": quote.get("spread"),
        "spread_pct": quote.get("spread_pct"),
        "bid_levels": list(quote.get("bid_levels") or []),
        "ask_levels": list(quote.get("ask_levels") or []),
        "top5_bid_volume_lots": quote.get("top5_bid_volume_lots"),
        "top5_ask_volume_lots": quote.get("top5_ask_volume_lots"),
        "top5_imbalance": quote.get("top5_imbalance"),
        "volume_unit": quote.get("depth_volume_unit") or "lots",
        "order_count_status": quote.get(
            "depth_order_count_status",
            "not_provided",
        ),
        "snapshot_time": _json_value(snapshot_time),
        "snapshot_time_basis": quote.get("snapshot_time_basis"),
        "provider_event_time": _json_value(
            quote.get("provider_event_time")
        ),
        "fetched_at": _json_value(quote.get("fetched_at")),
        "latency_ms": quote.get("latency_ms"),
        "provider": order_book_evidence.get("provider") or quote.get("provider"),
        "source": order_book_evidence.get("source") or quote.get("source"),
        "lineage": order_book_evidence.get("lineage"),
        "resolved_health": order_book_evidence.get("resolved_health"),
        "dataset_health": order_book_evidence.get("dataset_health"),
        "limitations": list(order_book_evidence.get("limitations") or []),
        "freshness": order_book_freshness,
    }

    cash_index = str(quote.get("instrument_type") or "") == "cash_index"
    auction_relevant = not cash_index and (
        instrument_phase
        in {
            "preopen_auction",
            "opening_auction_delayed",
            "closing_auction",
            "closing_auction_delayed",
        }
        or taiwan_session_is_auction(canonical_session_phase)
        or canonical_session_phase == "preopen_pending"
        or str(quote.get("trading_mode") or "")
        == "disposition_batch_auction"
    )
    auction_available = bool(
        quote.get("auction_book_available")
        or quote.get("auction_indicative_available")
        or quote.get("indicative_match_available")
    )
    raw_auction_status = str(
        quote.get("auction_book_status") or "unavailable"
    )
    auction_status = (
        "current"
        if auction_available
        and not bool((quote.get("freshness") or {}).get("is_stale"))
        else raw_auction_status
        if auction_relevant
        else "not_applicable"
    )
    auction_time = quote.get("auction_book_time") or snapshot_time
    auction_freshness = _component_freshness(
        quote,
        dataset="taiwan_quote_auction",
        status=auction_status,
        available=auction_available,
        event_time=auction_time,
    )
    auction_freshness.update(
        {
            "provider": auction_evidence.get("provider") or quote.get("provider"),
            "source": auction_evidence.get("source") or quote.get("source"),
            "resolved_health": auction_evidence.get("resolved_health"),
            "dataset_health": auction_evidence.get("dataset_health"),
        }
    )
    if auction_status == "not_applicable":
        auction_freshness["is_current"] = True
        auction_freshness["refresh_recommended"] = False
        auction_freshness["applicability_status"] = "not_applicable"
        auction_freshness["reason_code"] = (
            "CASH_INDEX_NO_ORDER_BOOK_AUCTION"
            if cash_index
            else "SESSION_NOT_AUCTION"
        )
    auction = {
        "kind": "quote_auction",
        "status": auction_status,
        "available": auction_available,
        "applicability_status": (
            "not_applicable"
            if auction_status == "not_applicable"
            else "applicable"
        ),
        "availability_status": (
            "available" if auction_available else "unavailable"
        ),
        "unavailable_reason_code": (
            "CASH_INDEX_NO_ORDER_BOOK_AUCTION"
            if cash_index
            else "SESSION_NOT_AUCTION"
            if not auction_relevant
            else "AUCTION_DATA_UNAVAILABLE"
            if not auction_available
            else None
        ),
        "market_session_status": session_phase or None,
        "refresh_possible_now": bool(auction_relevant),
        "refresh_recommended": bool(
            auction_relevant and not auction_available
        ),
        "session_phase": session_phase or None,
        "market_calendar_phase": quote.get("market_calendar_phase"),
        "instrument_phase": instrument_phase or None,
        "observation_reason_code": quote.get("observation_reason_code"),
        "auction_time": _json_value(auction_time),
        "best_bid": quote.get("auction_best_bid"),
        "best_ask": quote.get("auction_best_ask"),
        "indicative_available": bool(
            quote.get("auction_indicative_available")
        ),
        "indicative_match_available": bool(
            quote.get("indicative_match_available")
        ),
        "indicative_match_price": quote.get("indicative_match_price"),
        "indicative_match_volume_lots": quote.get(
            "indicative_match_volume_lots"
        ),
        "unmatched_buy_volume_lots": quote.get(
            "indicative_unmatched_buy_volume_lots"
        ),
        "unmatched_sell_volume_lots": quote.get(
            "indicative_unmatched_sell_volume_lots"
        ),
        "unmatched_status": quote.get(
            "indicative_unmatched_status",
            "not_provided",
        ),
        "trading_mode": quote.get("trading_mode") or "continuous",
        "analysis_basis": quote.get("analysis_basis"),
        "batch_interval_minutes": quote.get("batch_interval_minutes"),
        "next_batch_time": _json_value(quote.get("next_batch_time")),
        "provider_event_time": _json_value(
            quote.get("provider_event_time")
        ),
        "latency_ms": quote.get("latency_ms"),
        "provider": auction_evidence.get("provider") or quote.get("provider"),
        "source": auction_evidence.get("source") or quote.get("source"),
        "lineage": auction_evidence.get("lineage"),
        "resolved_health": auction_evidence.get("resolved_health"),
        "dataset_health": auction_evidence.get("dataset_health"),
        "limitations": list(auction_evidence.get("limitations") or []),
        "freshness": auction_freshness,
    }

    projected_close_available = bool(quote.get("official_close_available"))
    evidence_close_available = bool(official_close_evidence.get("available"))
    close_available = projected_close_available or evidence_close_available
    raw_close_status = (
        str(quote.get("official_close_status") or "unavailable")
        if projected_close_available
        else "confirmed_latest_session"
        if evidence_close_available
        else str(quote.get("official_close_status") or "unavailable")
    )
    close_status = (
        "latest_completed_session"
        if close_available
        and raw_close_status in {"confirmed", "confirmed_latest_session"}
        else "pending"
        if raw_close_status
        in {"pending", "closing_auction_pending", "not_available_yet"}
        else raw_close_status
    )
    close_time = (
        quote.get("official_close_trade_date")
        if projected_close_available
        else official_close_evidence.get("trade_date")
    )
    close_freshness = _component_freshness(
        quote,
        dataset="market_daily_price",
        status=close_status,
        available=close_available,
        event_time=close_time,
    )
    close_freshness.update(
        {
            "provider": official_close_evidence.get("provider"),
            "source": official_close_evidence.get("source"),
            "resolved_health": official_close_evidence.get("resolved_health"),
            "dataset_health": official_close_evidence.get("dataset_health"),
        }
    )
    official_close = {
        "kind": "quote_official_close",
        "status": close_status,
        "available": close_available,
        "price": (
            quote.get("official_close_price")
            if projected_close_available
            else official_close_evidence.get("price")
        ),
        "trade_date": _json_value(
            close_time
        ),
        "provider": official_close_evidence.get("provider"),
        "source": (
            quote.get("official_close_source")
            if projected_close_available
            else official_close_evidence.get("source")
        ),
        "raw": (
            quote.get("official_close_raw")
            if projected_close_available
            else official_close_evidence.get("raw")
        ),
        "display": (
            quote.get("official_close_display")
            if projected_close_available
            else official_close_evidence.get("display")
        ),
        "precision": (
            quote.get("official_close_precision")
            if projected_close_available
            else official_close_evidence.get("precision")
        ),
        "lineage": official_close_evidence.get("lineage"),
        "resolved_health": official_close_evidence.get("resolved_health"),
        "dataset_health": official_close_evidence.get("dataset_health"),
        "limitations": list(
            official_close_evidence.get("limitations") or []
        ),
        "quote_semantics": quote.get("quote_semantics"),
        "delivery_status": quote.get("delivery_status"),
        "freshness": close_freshness,
    }
    session_close = {
        **session_close_evidence,
        "kind": session_close_evidence.get("kind") or "quote_session_close",
        "status": session_close_evidence.get("status") or "unavailable",
        "available": bool(session_close_evidence.get("available")),
        "price": session_close_evidence.get("price"),
        "trade_date": _json_value(session_close_evidence.get("trade_date")),
        "event_time": _json_value(session_close_evidence.get("event_time")),
        "confirmed_at": _json_value(session_close_evidence.get("confirmed_at")),
        "official_close_trade_date": _json_value(
            session_close_evidence.get("official_close_trade_date")
        ),
    }
    return {
        "order_book": order_book,
        "auction": auction,
        "session_close": session_close,
        "official_close": official_close,
    }


def _quote_component_freshness_rows(
    quote: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    components = (
        quote.get("components")
        if isinstance(quote.get("components"), dict)
        else _quote_components(quote)
    )
    output: dict[str, dict[str, Any]] = {}
    for capability_id, key in (
        ("quote.order_book", "order_book"),
        ("quote.auction", "auction"),
        ("quote.session_close", "session_close"),
        ("quote.official_close", "official_close"),
    ):
        component = (
            components.get(key)
            if isinstance(components.get(key), dict)
            else {}
        )
        freshness = (
            component.get("freshness")
            if isinstance(component.get("freshness"), dict)
            else {}
        )
        output[capability_id] = dict(freshness)
    return output


def _quote_component_slots(
    quote: dict[str, Any],
    *,
    payload_level: str,
) -> dict[str, dict[str, Any]]:
    components = (
        quote.get("components")
        if isinstance(quote.get("components"), dict)
        else _quote_components(quote)
    )
    freshness_rows = _quote_component_freshness_rows(quote)
    output: dict[str, dict[str, Any]] = {}
    for slot_name, capability_id, key in (
        ("quote_order_book", "quote.order_book", "order_book"),
        ("quote_auction", "quote.auction", "auction"),
        (
            "quote_session_close",
            "quote.session_close",
            "session_close",
        ),
        (
            "quote_official_close",
            "quote.official_close",
            "official_close",
        ),
    ):
        component = (
            components.get(key)
            if isinstance(components.get(key), dict)
            else {}
        )
        freshness = freshness_rows[capability_id]
        output[slot_name] = _slot_envelope(
            status=str(component.get("status") or "missing"),
            capability=capability_id,
            payload_ref=f"quote.components.{key}",
            payload_level=payload_level,
            priority="core",
            as_of=freshness.get("latest"),
            freshness_status=str(
                freshness.get("status") or "missing"
            ),
            warnings=(
                [str(freshness.get("reason"))]
                if freshness.get("reason")
                and str(component.get("status"))
                in {"missing", "stale", "unavailable"}
                else []
            ),
        )
    return output


def _compact_quote_snapshot(
    *,
    latest_daily: Any,
    quote_depth: dict[str, Any] | None,
    quote_error: str | None,
    session_phase: str | None = None,
    current_session_date: str | None = None,
    is_trading_day: bool | None = None,
    live_quote_requested: bool = True,
) -> dict[str, Any]:
    if not quote_depth:
        quote = _compact_latest_daily_quote(
            latest_daily,
            quote_error=quote_error,
            session_phase=session_phase,
            current_session_date=current_session_date,
            is_trading_day=is_trading_day,
            live_quote_requested=live_quote_requested,
        )
        quote["components"] = _quote_components(quote)
        return quote

    freshness = quote_depth.get("freshness") if isinstance(quote_depth.get("freshness"), dict) else {}
    age_seconds = freshness.get("age_seconds")
    is_realtime = bool(freshness.get("is_live")) and not bool(freshness.get("is_stale"))
    last_trade_price = quote_depth.get(
        "last_trade_price",
        quote_depth.get("last_price"),
    )
    last_trade_available = bool(
        quote_depth.get(
            "last_trade_available",
            last_trade_price is not None,
        )
    )
    price_available = quote_depth.get("price_available")
    if not isinstance(price_available, bool):
        price_available = last_trade_price is not None
    latest_price = last_trade_price if price_available else None
    depth_available = bool(quote_depth.get("depth_available"))
    volume_contract = build_taiwan_quote_volume_contract(
        snapshot_trade_date=quote_depth.get("trade_date"),
        cumulative_volume_lots=quote_depth.get(
            "cumulative_volume_lots",
            quote_depth.get("total_volume_lots"),
        ),
        last_trade_volume_lots=quote_depth.get("last_trade_volume_lots"),
        official_daily_trade_date=quote_depth.get(
            "official_daily_volume_trade_date",
            getattr(latest_daily, "trade_date", None)
            if latest_daily is not None
            else None,
        ),
        official_daily_volume_shares=quote_depth.get(
            "official_daily_volume_shares",
            getattr(latest_daily, "trade_volume", None)
            if latest_daily is not None
            else None,
        ),
        official_daily_volume_source=quote_depth.get(
            "official_daily_volume_source"
        ),
    )
    for field in tuple(volume_contract):
        if field in quote_depth:
            volume_contract[field] = quote_depth[field]
    quote = {
        "kind": "quote_snapshot",
        "source": quote_depth.get("source"),
        "provider": quote_depth.get("provider"),
        "data_core_result_kinds": list(
            quote_depth.get("data_core_result_kinds") or []
        ),
        "data_core_components": (
            dict(quote_depth.get("data_core_components"))
            if isinstance(quote_depth.get("data_core_components"), dict)
            else {}
        ),
        "status": freshness.get("status") or quote_depth.get("session_phase") or "quote",
        "session_phase": quote_depth.get("session_phase"),
        "presentation_trade_date": _json_value(
            quote_depth.get("presentation_trade_date")
        ),
        "presentation_session_state": quote_depth.get(
            "presentation_session_state"
        ),
        "presentation_session_transition_at": _json_value(
            quote_depth.get("presentation_session_transition_at")
        ),
        "market_calendar_phase": quote_depth.get("market_calendar_phase"),
        "instrument_phase": quote_depth.get("instrument_phase"),
        "observation_reason_code": quote_depth.get(
            "observation_reason_code"
        ),
        "observation_semantics": quote_depth.get("observation_semantics"),
        "market_status": quote_depth.get("market_status"),
        "phase_label": quote_depth.get("phase_label"),
        "trade_date": _json_value(quote_depth.get("trade_date")),
        "quote_time": _json_value(quote_depth.get("quote_time")),
        "quote_time_basis": quote_depth.get("quote_time_basis"),
        "snapshot_time": _json_value(
            quote_depth.get("snapshot_time") or quote_depth.get("quote_time")
        ),
        "snapshot_time_basis": quote_depth.get("snapshot_time_basis"),
        "provider_event_time": _json_value(
            quote_depth.get("provider_event_time")
        ),
        "event_time": _json_value(
            quote_depth.get("event_time")
            or quote_depth.get("provider_event_time")
        ),
        "fetched_at": _json_value(quote_depth.get("fetched_at")),
        "received_at": _json_value(quote_depth.get("received_at")),
        "served_at": _json_value(quote_depth.get("served_at")),
        "event_age_seconds": quote_depth.get(
            "event_age_seconds",
            age_seconds,
        ),
        "provider_delay_ms": quote_depth.get("provider_delay_ms"),
        "network_latency_ms": quote_depth.get("network_latency_ms"),
        "refresh_outcome": quote_depth.get("refresh_outcome"),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "price_available": price_available,
        "last_trade_available": last_trade_available,
        "last_trade_price": (
            quote_depth.get("last_trade_price", last_trade_price)
            if last_trade_available
            else None
        ),
        "last_trade_time": _json_value(quote_depth.get("last_trade_time")),
        "last_trade_is_current_session": bool(
            quote_depth.get("last_trade_is_current_session")
        ),
        "last_trade_before_auction": bool(
            quote_depth.get("last_trade_before_auction")
        ),
        "actual_trade_occurred": bool(
            quote_depth.get("actual_trade_occurred")
        ),
        "actual_trade_price_cached": bool(
            quote_depth.get("actual_trade_price_cached")
        ),
        "actual_trade_price_source": quote_depth.get(
            "actual_trade_price_source"
        ),
        "actual_trade_price_as_of": _json_value(
            quote_depth.get("actual_trade_price_as_of")
        ),
        "session_close_available": bool(
            quote_depth.get("session_close_available")
        ),
        "session_close_status": quote_depth.get("session_close_status"),
        "session_close_price": quote_depth.get("session_close_price"),
        "session_close_trade_date": _json_value(
            quote_depth.get("session_close_trade_date")
        ),
        "session_close_event_time": _json_value(
            quote_depth.get("session_close_event_time")
        ),
        "session_close_confirmed_at": _json_value(
            quote_depth.get("session_close_confirmed_at")
        ),
        "facts_usable_for_current_session": bool(
            last_trade_available
            and quote_depth.get("last_trade_is_current_session")
        ),
        "fallback_quote": quote_depth.get("fallback_quote"),
        "previous_close": quote_depth.get("previous_close"),
        "open_price": quote_depth.get("open_price"),
        "high_price": quote_depth.get("high_price"),
        "low_price": quote_depth.get("low_price"),
        "change": quote_depth.get("change"),
        "change_pct": quote_depth.get("change_pct"),
        **volume_contract,
        "price_decision_usable": price_available,
        "currency": "TWD",
        "price_unit": "TWD",
        "best_bid_price": (
            quote_depth.get("best_bid_price") if depth_available else None
        ),
        "best_bid_size_lots": (
            quote_depth.get("best_bid_size_lots") if depth_available else None
        ),
        "best_ask_price": (
            quote_depth.get("best_ask_price") if depth_available else None
        ),
        "best_ask_size_lots": (
            quote_depth.get("best_ask_size_lots") if depth_available else None
        ),
        "spread": quote_depth.get("spread") if depth_available else None,
        "spread_pct": (
            quote_depth.get("spread_pct") if depth_available else None
        ),
        "bid_levels": (
            quote_depth.get("bid_levels") or []
            if depth_available
            else []
        ),
        "ask_levels": (
            quote_depth.get("ask_levels") or []
            if depth_available
            else []
        ),
        "bid_depth": (
            quote_depth.get("bid_depth")
            or quote_depth.get("bid_levels")
            or []
            if depth_available
            else []
        ),
        "ask_depth": (
            quote_depth.get("ask_depth")
            or quote_depth.get("ask_levels")
            or []
            if depth_available
            else []
        ),
        "top5_bid_volume_lots": (
            quote_depth.get("top5_bid_volume_lots")
            if depth_available
            else None
        ),
        "top5_ask_volume_lots": (
            quote_depth.get("top5_ask_volume_lots")
            if depth_available
            else None
        ),
        "top5_imbalance": (
            quote_depth.get("top5_imbalance")
            if depth_available
            else None
        ),
        "depth_volume_unit": quote_depth.get("depth_volume_unit"),
        "depth_order_count_status": quote_depth.get(
            "depth_order_count_status",
            "not_provided",
        ),
        "depth_available": depth_available,
        "depth_status": "available" if depth_available else "unavailable",
        "auction_book_available": bool(
            quote_depth.get("auction_book_available")
        ),
        "auction_book_status": quote_depth.get(
            "auction_book_status",
            "unavailable",
        ),
        "auction_book_time": _json_value(
            quote_depth.get("auction_book_time")
        ),
        "auction_best_bid": quote_depth.get("auction_best_bid"),
        "auction_best_ask": quote_depth.get("auction_best_ask"),
        "auction_indicative_available": bool(
            quote_depth.get("auction_indicative_available")
        ),
        "indicative_match_available": bool(
            quote_depth.get("indicative_match_available")
        ),
        "indicative_match_price": quote_depth.get(
            "indicative_match_price"
        ),
        "indicative_match_volume_lots": quote_depth.get(
            "indicative_match_volume_lots"
        ),
        "indicative_unmatched_buy_volume_lots": quote_depth.get(
            "indicative_unmatched_buy_volume_lots"
        ),
        "indicative_unmatched_sell_volume_lots": quote_depth.get(
            "indicative_unmatched_sell_volume_lots"
        ),
        "indicative_unmatched_status": quote_depth.get(
            "indicative_unmatched_status",
            "not_provided",
        ),
        "indicative_price_available": bool(
            quote_depth.get("indicative_price_available")
        ),
        "indicative_price": quote_depth.get("indicative_price"),
        "indicative_bid": quote_depth.get("indicative_bid"),
        "indicative_ask": quote_depth.get("indicative_ask"),
        "official_close_available": bool(
            quote_depth.get("official_close_available")
        ),
        "official_close_status": quote_depth.get(
            "official_close_status",
            "unavailable",
        ),
        "official_close_price": quote_depth.get("official_close_price"),
        "official_close_trade_date": _json_value(
            quote_depth.get("official_close_trade_date")
        ),
        "official_close_source": quote_depth.get("official_close_source"),
        "quote_semantics": quote_depth.get("quote_semantics"),
        "delivery_status": quote_depth.get(
            "delivery_status",
            freshness.get("status"),
        ),
        "fallback_used": bool(quote_depth.get("fallback_used")),
        "is_realtime": is_realtime,
        "latency_ms": quote_depth.get("network_latency_ms"),
        "latency_ms_semantics": "deprecated_network_latency_ms",
        "freshness": {
            "status": freshness.get("status"),
            "is_live": bool(freshness.get("is_live")),
            "is_stale": bool(freshness.get("is_stale")),
            "age_seconds": freshness.get("age_seconds"),
            "expected_trade_date": _json_value(freshness.get("expected_trade_date")),
            "message": freshness.get("message"),
            "source_error": freshness.get("source_error"),
            "source_error_detail": freshness.get("source_error_detail"),
            "fetch_age_seconds": freshness.get("fetch_age_seconds"),
        },
    }
    quote.update(
        _quote_provider_path(
            selected_provider=str(
                quote_depth.get("provider") or ""
            ).strip()
            or None,
            live_quote_requested=live_quote_requested,
            fallback_used=bool(quote_depth.get("fallback_used")),
            quote_error=quote_error,
            refresh_outcome=str(
                quote_depth.get("refresh_outcome") or ""
            ).strip()
            or None,
        )
    )
    quote["components"] = _quote_components(quote)
    return quote


def _compact_intraday_point(point: dict[str, Any]) -> dict[str, Any]:
    canonical_volume_unit = point.get("canonical_volume_unit") or (
        "shares" if point.get("volume_shares") is not None else None
    )
    provider_volume_unit = point.get("provider_volume_unit")
    return {
        "time": _json_value(point.get("time")),
        "price": point.get("price") if point.get("price") is not None else point.get("close"),
        "currency": point.get("currency") or "TWD",
        "price_unit": point.get("price_unit") or "TWD",
        "open": point.get("open"),
        "high": point.get("high"),
        "low": point.get("low"),
        "close": point.get("close"),
        "volume": point.get("volume"),
        "volume_unit": point.get("volume_unit")
        or canonical_volume_unit
        or provider_volume_unit,
        "volume_shares": point.get("volume_shares"),
        "volume_lots": point.get("volume_lots"),
        "canonical_volume_unit": canonical_volume_unit,
        "provider_volume_unit": provider_volume_unit,
        "volume_status": point.get("volume_status"),
        "trade_value": point.get("trade_value"),
        "trade_value_unit": point.get("trade_value_unit") or "TWD",
        "approx_trade_value": point.get("approx_trade_value"),
        "trade_value_status": point.get("trade_value_status"),
        "transaction_count": point.get("transaction_count"),
        "bar_close_time": _json_value(point.get("bar_close_time")),
        "elapsed_seconds": point.get("elapsed_seconds"),
        "is_partial": point.get("is_partial"),
        "finalized": point.get("finalized"),
        "bar_type": point.get("bar_type"),
        "synthetic": point.get("synthetic"),
        "source_interval": point.get("source_interval"),
        "source_point_count": point.get("source_point_count"),
        "quality_status": point.get("quality_status"),
        "indicator_eligible": point.get("indicator_eligible"),
        "session_phase": point.get("session_phase"),
        "market_event": point.get("market_event"),
        "source_event_type": point.get("source_event_type"),
        "gap_reason": point.get("gap_reason"),
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
    unit_point = next(
        (
            point
            for point in reversed(points)
            if point.get("canonical_volume_unit")
            or point.get("provider_volume_unit")
            or point.get("volume_shares") is not None
        ),
        first_point,
    )
    canonical_volume_unit = history.get("canonical_volume_unit") or (
        unit_point.get("canonical_volume_unit")
        or ("shares" if unit_point.get("volume_shares") is not None else None)
    )
    provider_volume_unit = (
        history.get("provider_volume_unit")
        or unit_point.get("provider_volume_unit")
    )
    latest_point = compact_points[-1] if compact_points else None
    refreshed_count = history.get("refreshed_count")
    empty_warning = (
        f"Provider refresh reported refreshed_count={refreshed_count} but returned no intraday points."
        if refreshed_count and not compact_points
        else None
    )
    effective_interval = str(
        history.get("effective_interval")
        or history.get("interval")
        or "1m"
    )
    source_interval = str(
        history.get("source_interval")
        or effective_interval
    )
    requested_interval = str(
        history.get("requested_interval")
        or effective_interval
    )
    return {
        "status": (
            "partial"
            if history.get("is_partial") and compact_points
            else "current"
            if compact_points
            else "empty"
        ),
        "interval": effective_interval,
        "requested_interval": requested_interval,
        "source_interval": source_interval,
        "effective_interval": effective_interval,
        "interval_status": (
            str(history.get("interval_status"))
            if history.get("interval_status")
            else "ready"
            if requested_interval == effective_interval
            else "unsupported"
        ),
        "range": history.get("range"),
        "provider": history.get("provider"),
        "source": history.get("source"),
        "from_time": _json_value(history.get("from_time") or first_point.get("time")),
        "to_time": _json_value(history.get("to_time") or (latest_point or {}).get("time")),
        "point_count": history.get("point_count") if history.get("point_count") is not None else len(points),
        "returned_point_count": len(compact_points),
        "bar_limit": point_limit,
        "truncated": len(points) > len(compact_points),
        "coverage_status": history.get("coverage_status"),
        "is_partial": bool(history.get("is_partial")),
        "synthetic": bool(history.get("synthetic")),
        "synthetic_semantics": history.get("synthetic_semantics"),
        "indicator_eligible": history.get("indicator_eligible"),
        "trade_date": _json_value(history.get("trade_date")),
        "currency": history.get("currency") or "TWD",
        "price_unit": history.get("price_unit") or "TWD",
        "volume_unit": history.get("volume_unit")
        or canonical_volume_unit
        or provider_volume_unit,
        "volume_status": history.get("volume_status") or unit_point.get("volume_status"),
        "volume_semantics": history.get("volume_semantics"),
        "canonical_volume_unit": canonical_volume_unit,
        "provider_volume_unit": provider_volume_unit,
        "volume_conversion": history.get("volume_conversion"),
        "volume_scope": history.get("volume_scope"),
        "bar_volume_sum_shares": history.get("bar_volume_sum_shares"),
        "bar_volume_sum_lots": history.get("bar_volume_sum_lots"),
        "bar_volume_trade_date": _json_value(
            history.get("bar_volume_trade_date")
        ),
        "bar_volume_latest_time": _json_value(
            history.get("bar_volume_latest_time")
        ),
        "bar_volume_scope": history.get("bar_volume_scope"),
        "bar_volume_provider": history.get("bar_volume_provider"),
        "window_volume_sum_shares": history.get("window_volume_sum_shares"),
        "window_volume_sum_lots": history.get("window_volume_sum_lots"),
        "window_volume_scope": history.get("window_volume_scope"),
        "window_trade_date_count": history.get("window_trade_date_count"),
        "session_cumulative_volume_shares": history.get(
            "session_cumulative_volume_shares"
        ),
        "session_cumulative_volume_lots": history.get(
            "session_cumulative_volume_lots"
        ),
        "session_cumulative_volume_trade_date": _json_value(
            history.get("session_cumulative_volume_trade_date")
        ),
        "session_cumulative_volume_source": history.get(
            "session_cumulative_volume_source"
        ),
        "session_cumulative_volume_source_field": history.get(
            "session_cumulative_volume_source_field"
        ),
        "session_cumulative_volume_event_time": _json_value(
            history.get("session_cumulative_volume_event_time")
        ),
        "session_cumulative_volume_status": history.get(
            "session_cumulative_volume_status"
        ),
        "cumulative_volume_shares": history.get("cumulative_volume_shares"),
        "cumulative_volume_lots": history.get("cumulative_volume_lots"),
        "cumulative_volume_trade_date": _json_value(
            history.get("cumulative_volume_trade_date")
        ),
        "cumulative_volume_source": history.get("cumulative_volume_source"),
        "cumulative_volume_source_field": history.get(
            "cumulative_volume_source_field"
        ),
        "cumulative_volume_event_time": _json_value(
            history.get("cumulative_volume_event_time")
        ),
        "cumulative_volume_status": history.get("cumulative_volume_status"),
        "unallocated_volume_shares": history.get("unallocated_volume_shares"),
        "unallocated_volume_lots": history.get("unallocated_volume_lots"),
        "volume_reconciliation": history.get("volume_reconciliation"),
        "cumulative_trade_value": history.get("cumulative_trade_value"),
        "available_cumulative_trade_value": history.get(
            "available_cumulative_trade_value"
        ),
        "estimated_cumulative_trade_value": history.get(
            "estimated_cumulative_trade_value"
        ),
        "trade_value_unit": history.get("trade_value_unit") or "TWD",
        "trade_value_status": history.get("trade_value_status"),
        "official_vwap": history.get("official_vwap"),
        "approx_vwap": history.get("approx_vwap"),
        "vwap_method": history.get("vwap_method"),
        "vwap_confidence": history.get("vwap_confidence"),
        "vwap_volume_scope": history.get("vwap_volume_scope"),
        "partial_bar_count": history.get("partial_bar_count"),
        "indicator_eligible_point_count": history.get(
            "indicator_eligible_point_count"
        ),
        "bar_classification_policy": history.get("bar_classification_policy"),
        "indicator_policy": history.get("indicator_policy"),
        "partial_bar_policy": history.get("partial_bar_policy"),
        "aggregation_method": history.get("aggregation_method"),
        "cached_count": history.get("cached_count"),
        "refreshed_count": refreshed_count,
        "cache_status": history.get("cache_status") or (
            "persisted_hit"
            if history.get("cached_count")
            else "persisted_miss"
        ),
        "cache_hit": (
            history.get("cache_hit")
            if isinstance(history.get("cache_hit"), bool)
            else bool(history.get("cached_count"))
        ),
        "cache_trade_date": history.get("cache_trade_date") or (
            str(history.get("to_time"))[:10]
            if history.get("to_time")
            else None
        ),
        "cache_latest_time": history.get("cache_latest_time")
        or _json_value(history.get("to_time")),
        "fallback_used": bool(history.get("fallback_used")),
        "latest": latest_point,
        "points": compact_points,
        "warnings": [empty_warning] if empty_warning else [],
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
    resolved_interval = str(payload.get("interval") or interval)
    requested_interval = str(
        payload.get("requested_interval")
        or _requested_intraday_interval(
            market_data_params,
            default=interval,
        )
        or interval
    )
    source_interval = str(payload.get("source_interval") or resolved_interval)
    effective_interval = str(
        payload.get("effective_interval") or resolved_interval
    )
    interval_status = str(
        payload.get("interval_status")
        or (
            "ready"
            if requested_interval == effective_interval
            else "unsupported"
        )
    )
    history = {
        "interval": resolved_interval,
        "requested_interval": requested_interval,
        "source_interval": source_interval,
        "effective_interval": effective_interval,
        "interval_status": interval_status,
        "aggregation_method": payload.get("aggregation_method"),
        "range": payload.get("range") or "1d",
        "provider": payload.get("provider"),
        "source": payload.get("source"),
        "point_count": payload.get("point_count") if payload.get("point_count") is not None else len(points),
        "trade_date": payload.get("trade_date"),
        "coverage_status": payload.get("coverage_status"),
        "is_partial": payload.get("is_partial"),
        "synthetic": payload.get("synthetic"),
        "synthetic_semantics": payload.get("synthetic_semantics"),
        "indicator_eligible": payload.get("indicator_eligible"),
        "volume_unit": payload.get("volume_unit"),
        "volume_status": payload.get("volume_status"),
        "volume_semantics": payload.get("volume_semantics"),
        "canonical_volume_unit": payload.get("canonical_volume_unit"),
        "provider_volume_unit": payload.get("provider_volume_unit"),
        "volume_conversion": payload.get("volume_conversion"),
        "cumulative_volume_shares": payload.get("cumulative_volume_shares"),
        "cumulative_volume_lots": payload.get("cumulative_volume_lots"),
        "cumulative_trade_value": payload.get("cumulative_trade_value"),
        "available_cumulative_trade_value": payload.get(
            "available_cumulative_trade_value"
        ),
        "estimated_cumulative_trade_value": payload.get(
            "estimated_cumulative_trade_value"
        ),
        "trade_value_unit": payload.get("trade_value_unit"),
        "trade_value_status": payload.get("trade_value_status"),
        "official_vwap": payload.get("official_vwap"),
        "approx_vwap": payload.get("approx_vwap"),
        "vwap_method": payload.get("vwap_method"),
        "vwap_confidence": payload.get("vwap_confidence"),
        "partial_bar_count": payload.get("partial_bar_count"),
        "indicator_eligible_point_count": payload.get(
            "indicator_eligible_point_count"
        ),
        "partial_bar_policy": payload.get("partial_bar_policy"),
        "points": points,
    }
    warnings = [
        str(item)
        for item in payload.get("warnings") or []
        if str(item).strip()
    ]
    if interval_status != "ready":
        warnings.append(
            f"Requested Taiwan index intraday interval {requested_interval} "
            f"is not fully provider-native; returned {effective_interval} "
            "without relabeling it as the requested interval, "
            f"with interval_status={interval_status}."
        )
    return {
        "kind": "intraday_bars",
        "enabled": True,
        "intervals": [resolved_interval],
        "interval": effective_interval,
        "requested_interval": requested_interval,
        "source_interval": source_interval,
        "effective_interval": effective_interval,
        "interval_status": interval_status,
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {
            resolved_interval: _compact_intraday_history(
                history,
                point_limit=point_limit,
            )
        },
        "warnings": warnings,
    }


def _technical_report_score_contract(
    *,
    report: dict[str, Any],
    timeframe: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    if report.get("kind") == "tw_stock_technical_report":
        bounds = {
            "today": (-3, 3, "tw_technical_intraday_raw_v1"),
            "daily": (-16, 16, "tw_technical_daily_raw_v1"),
            "weekly": (-6, 6, "tw_technical_aggregate_raw_v1"),
            "monthly": (-6, 6, "tw_technical_aggregate_raw_v1"),
        }.get(
            timeframe,
            (-16, 16, "tw_technical_stock_raw_v1"),
        )
        model_version = "tw_stock_technical_report.v1"
    else:
        bounds = (-5, 5, "omi_point_series_technical_raw_v1")
        model_version = "omi_point_series_technical.v1"
    components = (
        analysis.get("components")
        if isinstance(analysis.get("components"), list)
        else []
    )
    component = next(
        (
            item
            for item in components
            if isinstance(item, dict)
            and item.get("timeframe") == timeframe
        ),
        {},
    )
    return {
        "score": report.get("score"),
        "score_min": bounds[0],
        "score_max": bounds[1],
        "score_scale_id": bounds[2],
        "score_model_version": model_version,
        "normalization_method": "none_raw_additive",
        "weight_in_composite": component.get("weight"),
    }


def _compact_technical_report(
    report: dict[str, Any],
    *,
    timeframe: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    daily_indicator = data.get("daily_indicator") if isinstance(data.get("daily_indicator"), dict) else {}
    intraday = data.get("intraday") if isinstance(data.get("intraday"), dict) else {}
    current_observation = (
        data.get("current_observation")
        if isinstance(data.get("current_observation"), dict)
        else {}
    )
    current_indicator = (
        current_observation.get("indicator")
        if isinstance(current_observation.get("indicator"), dict)
        else {}
    )
    decision_state = (
        data.get("decision_state")
        if isinstance(data.get("decision_state"), dict)
        else {}
    )
    current_state = (
        current_observation.get("current_state")
        if isinstance(current_observation.get("current_state"), dict)
        else {}
    )
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
        "latest_finalized_close": daily_indicator.get("close"),
        "decision_state_time": data.get("decision_state_time"),
        "decision_state_status": data.get("decision_state_status"),
        "decision_state": {
            "headline": decision_state.get("headline"),
            "qualifier": decision_state.get("qualifier"),
            "position": decision_state.get("position"),
        },
        "current_observation": (
            {
                "status": current_observation.get("status"),
                "time": current_observation.get("time"),
                "decision_usable": current_observation.get("decision_usable"),
                "official_daily_confirmed": current_observation.get(
                    "official_daily_confirmed"
                ),
                "close": current_indicator.get("close"),
                "volume": current_indicator.get("volume"),
                "bar_status": current_indicator.get("bar_status"),
                "headline": current_state.get("headline"),
                "qualifier": current_state.get("qualifier"),
                "position": current_state.get("position"),
            }
            if current_observation
            else None
        ),
        "score_contract": _technical_report_score_contract(
            report=report,
            timeframe=timeframe,
            analysis=analysis,
        ),
        "missing": report.get("missing") or [],
        "warnings": report.get("warnings") or [],
    }


def _neutralize_insufficient_technical_report(
    report: dict[str, Any],
) -> dict[str, Any]:
    result = dict(report)
    result.update(
        {
            "title": "技術證據不足",
            "summary": "歷史或核心指標不足，僅保留非方向性的觀測值。",
            "score": None,
            "confidence": None,
            "value": None,
            "value_label": None,
        }
    )
    score_contract = dict(result.get("score_contract") or {})
    score_contract["score"] = None
    result["score_contract"] = score_contract
    decision_state = dict(result.get("decision_state") or {})
    decision_state.update({"headline": None, "qualifier": None, "position": None})
    result["decision_state"] = decision_state
    current_observation = result.get("current_observation")
    if isinstance(current_observation, dict):
        current_observation = dict(current_observation)
        current_observation.update(
            {
                "decision_usable": False,
                "headline": None,
                "qualifier": None,
                "position": None,
            }
        )
        result["current_observation"] = current_observation
    return result


def _compact_technical_evidence(
    *,
    analysis: dict[str, Any],
    technical_levels: dict[str, Any],
    technical_reports: dict[str, Any],
) -> dict[str, Any]:
    decision_usable = bool(analysis.get("decision_usable"))
    score_model = (
        analysis.get("score_model")
        if isinstance(analysis.get("score_model"), dict)
        else {}
    )
    composite_score_contract = {
        "score": analysis.get("selected_score"),
        "score_min": -7,
        "score_max": 7,
        "score_scale_id": "technical_factor_composite_v1",
        "score_model_version": (
            score_model.get("version")
            or "technical_factor_weight_v1"
        ),
        "normalization_method": (
            "available_factor_weighted_mean_scaled_to_7"
        ),
        "weight_in_composite": 1.0,
    }
    report_score_contracts = {
        timeframe: _technical_report_score_contract(
            report=report,
            timeframe=timeframe,
            analysis=analysis,
        )
        for timeframe, report in technical_reports.items()
        if isinstance(report, dict)
    }
    if not decision_usable:
        report_score_contracts = {
            timeframe: {**contract, "score": None}
            for timeframe, contract in report_score_contracts.items()
        }
    compact_reports = {
        timeframe: _compact_technical_report(
            report,
            timeframe=timeframe,
            analysis=analysis,
        )
        for timeframe, report in technical_reports.items()
        if isinstance(report, dict)
    }
    if not decision_usable:
        compact_reports = {
            timeframe: _neutralize_insufficient_technical_report(report)
            for timeframe, report in compact_reports.items()
        }
    insufficient_reason_codes = list(
        (analysis.get("sufficiency") or {}).get("reason_codes") or []
    )
    return {
        "status": analysis.get("status") or "partial",
        "decision_usable": decision_usable,
        "currency": "TWD",
        "price_unit": "TWD",
        "volume_unit": "shares",
        "source_capability": "daily.ohlcv",
        "measurement_lineage": {
            "price_unit": "TWD",
            "currency": "TWD",
            "volume_unit": "shares",
            "source_capability": "daily.ohlcv",
        },
        "score_unit": "model_points",
        "score_contracts": {
            "selected_composite": composite_score_contract,
            "reports": report_score_contracts,
        },
        "analysis": {
            "requested_horizon": analysis.get("requested_horizon"),
            "effective_horizon": analysis.get("effective_horizon"),
            "selected_horizon": analysis.get("selected_horizon"),
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": analysis.get("selected_score"),
            "selected_title": analysis.get("selected_title"),
            "composite_score_title": analysis.get("composite_score_title"),
            "selected_summary": analysis.get("selected_summary"),
            "selected_confidence": analysis.get("selected_confidence"),
            "today_state": analysis.get("today_state") or {},
            "historical_structure": analysis.get("historical_structure") or {},
            "composite_state": analysis.get("composite_state"),
            "fallback_reason": analysis.get("fallback_reason"),
            "scores": analysis.get("scores") or {},
            "score_range": (analysis.get("score_model") or {}).get("score_range"),
            "selected_score_contract": composite_score_contract,
            "decision_usable": decision_usable,
            "sufficiency": analysis.get("sufficiency") or {},
        },
        "levels": {
            "status": "ready" if decision_usable else "unavailable",
            "decision_usable": decision_usable,
            "reason_codes": [] if decision_usable else insufficient_reason_codes,
            "currency": "TWD",
            "price_unit": "TWD",
            "latest_price": technical_levels.get("latest_price"),
            "basis_timeframe": technical_levels.get("basis_timeframe"),
            "technical_price_basis": technical_levels.get("technical_price_basis"),
            "bid_ask_price_used": bool(technical_levels.get("bid_ask_price_used")),
            "context": technical_levels.get("context") or {},
            "entry": (technical_levels.get("entry") or {}) if decision_usable else {},
            "risk": (technical_levels.get("risk") or {}) if decision_usable else {},
        },
        "reports": compact_reports,
    }


def _source_health_entries(source_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(source_health, dict):
        return []
    entries = source_health.get("entries")
    return entries if isinstance(entries, list) else []


def _compact_source_health_entry(entry: dict[str, Any]) -> dict[str, Any]:
    latest_event_detail = (
        entry.get("latest_event_detail")
        if isinstance(entry.get("latest_event_detail"), dict)
        else {}
    )
    return {
        "resource": entry.get("resource"),
        "label": entry.get("label"),
        "status": entry.get("status"),
        "ok": bool(entry.get("ok")),
        "row_count": entry.get("row_count"),
        "latest": _json_value(entry.get("latest_data_date") or entry.get("latest_data_key")),
        "expected": _json_value(entry.get("expected_data_date")),
        "release_status": entry.get("release_status"),
        "release_at": entry.get("release_at"),
        "next_release_at": entry.get("next_release_at"),
        "next_eligible_refresh_at": entry.get("next_eligible_refresh_at"),
        "refresh_eligible": entry.get("refresh_eligible"),
        "last_refresh_attempt_at": entry.get("latest_event_at"),
        "last_refresh_outcome": latest_event_detail.get("refresh_outcome"),
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


def _freshness_for_resource(
    *,
    source_health: dict[str, Any] | None,
    resource: str,
    missing: list[str],
) -> dict[str, Any]:
    entry = next(
        (
            _compact_source_health_entry(item)
            for item in _source_health_entries(source_health)
            if item.get("resource") == resource
        ),
        None,
    )
    if entry is None:
        status = "missing" if resource in missing else "unknown"
        return {
            "status": status,
            "dataset": resource,
            "is_current": False,
            "latest": None,
            "expected": None,
            "release_status": None,
            "refresh_recommended": status == "missing",
            "reason": (
                f"{resource} is missing from the selected stock evidence."
                if status == "missing"
                else f"No source-health row is available for {resource}."
            ),
        }
    status = str(entry.get("status") or "unknown")
    release_status = str(entry.get("release_status") or "").strip() or None
    refresh_recommended = status in {
        "blocked",
        "empty",
        "error",
        "failed",
        "missing",
        "stale",
    }
    if release_status == "pending" and bool(entry.get("ok")):
        refresh_recommended = False
    if entry.get("refresh_eligible") is False:
        refresh_recommended = False
    return {
        "status": status,
        "dataset": resource,
        "is_current": bool(entry.get("ok")),
        "latest": entry.get("latest"),
        "expected": entry.get("expected"),
        "release_status": release_status,
        "release_at": entry.get("release_at"),
        "next_release_at": entry.get("next_release_at"),
        "next_eligible_refresh_at": entry.get("next_eligible_refresh_at"),
        "refresh_eligible": entry.get("refresh_eligible"),
        "last_refresh_attempt_at": entry.get("last_refresh_attempt_at"),
        "last_refresh_outcome": entry.get("last_refresh_outcome"),
        "refresh_recommended": refresh_recommended,
        "reason": entry.get("reason"),
    }


def _canonical_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _enum_value(value: Any) -> str | None:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    return text or None


def _canonical_daily_freshness(
    *,
    canonical_daily_evidence: Any,
    source_health: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project canonical daily truth while keeping provider health diagnostic."""

    dataset_health = _canonical_field(canonical_daily_evidence, "dataset_health")
    resolved_health = _canonical_field(canonical_daily_evidence, "resolved_health")
    if dataset_health is None and resolved_health is None:
        return None

    provider_entry = next(
        (
            _compact_source_health_entry(item)
            for item in _source_health_entries(source_health)
            if item.get("resource") == "market_daily_price"
        ),
        None,
    )
    provider_diagnostic = {
        "status": (
            str(provider_entry.get("status") or "unknown")
            if provider_entry is not None
            else "unknown"
        ),
        "reason": (
            provider_entry.get("reason")
            if provider_entry is not None
            else "No source-health row is available for market_daily_price."
        ),
    }

    resolved_status = _enum_value(_canonical_field(resolved_health, "status"))
    dataset_status = _enum_value(_canonical_field(dataset_health, "status"))
    if dataset_status is not None:
        status = {
            "healthy": "current",
            "stale": "stale",
            "partial": "partial",
            "missing": "missing",
            "not_applicable": "not_applicable",
            "unavailable": "unavailable",
            "unknown": "unknown",
        }.get(dataset_status, "unknown")
        if status == "current":
            status = {
                "partial": "partial",
                "stale": "stale",
                "missing": "missing",
                "policy_unsatisfied": "unavailable",
            }.get(resolved_status, status)
        return {
            "status": status,
            "dataset": (
                _canonical_field(dataset_health, "dataset_id")
                or "market_daily_price"
            ),
            "is_current": status == "current",
            "latest": _json_value(_canonical_field(dataset_health, "latest_date")),
            "expected": _json_value(
                _canonical_field(dataset_health, "expected_date")
            ),
            "refresh_recommended": bool(
                _canonical_field(dataset_health, "refreshable")
                and status in {"missing", "partial", "stale", "unavailable"}
            ),
            "reason": _canonical_field(dataset_health, "detail_code"),
            "canonical_status_ref": "dataset_health",
            "resolved_status": resolved_status,
            "provider_diagnostic": provider_diagnostic,
        }

    if resolved_status is None:
        return None
    status = {
        "selected": "current",
        "fallback": "current",
        "partial": "partial",
        "stale": "stale",
        "missing": "missing",
        "policy_unsatisfied": "unavailable",
    }.get(resolved_status, "unknown")
    return {
        "status": status,
        "dataset": "market_daily_price",
        "is_current": status == "current",
        "latest": _json_value(
            _canonical_field(resolved_health, "selected_event_at")
        ),
        "expected": None,
        "refresh_recommended": False,
        "reason": _canonical_field(resolved_health, "selection_reason"),
        "canonical_status_ref": "resolved_evidence_health",
        "provider": _canonical_field(resolved_health, "selected_provider"),
        "source": _canonical_field(resolved_health, "selected_source"),
        "provider_diagnostic": provider_diagnostic,
    }


def _build_freshness_by_capability(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    source_health: dict[str, Any] | None,
    overnight_impact: dict[str, Any] | None,
    missing: list[str],
    canonical_daily_evidence: Any = None,
) -> dict[str, Any]:
    quote_freshness = _quote_freshness_domain(quote)
    intraday_resource = _intraday_bar_freshness_resource(intraday_bars)
    cross_market = _cross_market_freshness_domain(overnight_impact)
    cross_market_relations = _canonical_cross_market_freshness_domain(
        overnight_impact
    )
    cross_market_parity = _cross_market_parity_freshness_domain(
        overnight_impact
    )
    output = {
        "target.identity": {
            "status": "current",
            "dataset": "stock_master",
            "is_current": True,
            "refresh_recommended": False,
        },
        "quote.snapshot": {
            **quote_freshness,
            "dataset": "quote",
            "refresh_recommended": quote_freshness.get("status")
            in {"missing", "stale", "unavailable"},
        },
        **_quote_component_freshness_rows(quote),
        "intraday.bars": {
            "status": intraday_resource.get("status"),
            "dataset": "intraday_bars",
            "is_current": bool(intraday_resource.get("ok")),
            "latest": intraday_resource.get("latest"),
            "expected": intraday_resource.get("expected"),
            "refresh_recommended": intraday_resource.get("status")
            in {"missing", "stale", "unavailable"},
            "reason": intraday_resource.get("reason"),
        },
        "cross_market.overnight": {
            **cross_market,
            "dataset": "us_overnight_tw_impact",
            "refresh_recommended": cross_market.get("status")
            in {"missing", "partial", "stale", "unavailable"},
        },
        "cross_market.relations": {
            **cross_market_relations,
            "dataset": "cross_market_relation_context",
        },
        "cross_market.parity": {
            **cross_market_parity,
            "dataset": "adr_parity",
        },
    }
    for capability_id, resource in CAPABILITY_FRESHNESS_RESOURCES.items():
        canonical_freshness = (
            _canonical_daily_freshness(
                canonical_daily_evidence=canonical_daily_evidence,
                source_health=source_health,
            )
            if resource == "market_daily_price"
            else None
        )
        output[capability_id] = canonical_freshness or _freshness_for_resource(
            source_health=source_health,
            resource=resource,
            missing=missing,
        )
    return output


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
    context = overnight_impact.get("cross_market_context")
    if isinstance(context, dict):
        canonical = _canonical_cross_market_freshness_domain(
            overnight_impact
        )
        missing = list(
            dict.fromkeys(
                [
                    *(
                        overnight_impact.get("missing")
                        if isinstance(overnight_impact.get("missing"), list)
                        else []
                    ),
                    *canonical.get("missing", []),
                ]
            )
        )
        warnings = list(
            dict.fromkeys(
                [
                    *(
                        overnight_impact.get("warnings")
                        if isinstance(overnight_impact.get("warnings"), list)
                        else []
                    ),
                    *canonical.get("warnings", []),
                ]
            )
        )
        status = str(canonical.get("status") or "unknown")
        return {
            **canonical,
            "missing": missing,
            "warnings": warnings,
            "resources": [
                {
                    "resource": "us_overnight_tw_impact",
                    "label": "US overnight impact",
                    "status": status,
                    "ok": bool(canonical.get("is_current")),
                    "latest": canonical.get("latest"),
                    "expected": canonical.get("expected"),
                    "reason": (
                        "Canonical cross-market context owns overnight "
                        "freshness and decision usability."
                    ),
                }
            ],
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


def _canonical_cross_market_freshness_domain(
    overnight_impact: dict[str, Any] | None,
) -> dict[str, Any]:
    context = (
        overnight_impact.get("cross_market_context")
        if isinstance(overnight_impact, dict)
        else None
    )
    if not isinstance(context, dict):
        return {
            "status": "unavailable",
            "is_current": False,
            "decision_usable": False,
            "latest": None,
            "expected": None,
            "refresh_recommended": False,
            "missing": ["cross_market_context"],
            "warnings": [],
            "limitations": ["canonical_context_unavailable"],
        }
    raw_status = str(context.get("status") or "unknown")
    decision_usable = bool(context.get("decision_usable"))
    status = (
        "current"
        if raw_status == "ready" and decision_usable
        else "partial"
        if raw_status == "ready"
        else raw_status
    )
    freshness = (
        context.get("freshness")
        if isinstance(context.get("freshness"), dict)
        else {}
    )
    return {
        "status": status,
        "context_status": raw_status,
        "is_current": status == "current" and decision_usable,
        "decision_usable": decision_usable,
        "latest": context.get("as_of"),
        "expected": freshness.get("expected_adr_trade_date"),
        "refresh_recommended": status in {"missing", "partial", "stale", "unavailable"},
        "missing": list(context.get("missing") or []),
        "warnings": list(context.get("warnings") or []),
        "limitations": list(context.get("limitations") or []),
        "snapshot_id": context.get("snapshot_id"),
        "projection_source": context.get("projection_source"),
        "source_cutoff_at": context.get("source_cutoff_at"),
        "materialized_at": context.get("materialized_at"),
        "materialized_by": context.get("materialized_by"),
        "payload_hash": context.get("payload_hash"),
        "methodology_version": context.get("methodology_version"),
        "relation_snapshot_version": context.get("relation_snapshot_version"),
    }


def _cross_market_parity_freshness_domain(
    overnight_impact: dict[str, Any] | None,
) -> dict[str, Any]:
    parity = (
        overnight_impact.get("adr_parity")
        if isinstance(overnight_impact, dict)
        else None
    )
    if not isinstance(parity, dict):
        return {
            "status": "not_applicable",
            "is_current": False,
            "decision_usable": False,
            "latest": None,
            "expected": None,
            "refresh_recommended": False,
            "missing": [],
            "warnings": [],
            "limitations": ["no_approved_direct_adr_relation"],
        }
    raw_status = str(parity.get("status") or "unknown")
    is_current = bool(parity.get("is_current"))
    return {
        "status": "current" if raw_status == "ready" and is_current else raw_status,
        "parity_status": raw_status,
        "is_current": is_current,
        "decision_usable": raw_status == "ready" and is_current,
        "latest": parity.get("adr_trade_date"),
        "expected": parity.get("expected_adr_trade_date"),
        "refresh_recommended": raw_status in {"missing", "partial", "stale"},
        "missing": list(parity.get("missing") or []),
        "warnings": list(parity.get("warnings") or []),
        "limitations": list(
            (parity.get("mapping_resolution") or {}).get("limitations") or []
        ),
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


def _index_candidate_datetime(
    value: Any,
    *,
    timezone_name: str,
) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value or "").strip()
        if not text_value or len(text_value) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    market_timezone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=market_timezone)
    return parsed.astimezone(market_timezone)


def _index_candidate_date(
    value: Any,
    *,
    timezone_name: str,
) -> date | None:
    parsed_at = _index_candidate_datetime(
        value,
        timezone_name=timezone_name,
    )
    if parsed_at is not None:
        return parsed_at.date()
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _legacy_resolve_taiwan_index_quote_state(
    *,
    intraday: dict[str, Any] | None,
    index_snapshot: dict[str, Any],
    calendar_status: dict[str, Any],
) -> dict[str, Any]:
    timezone_name = str(calendar_status.get("timezone") or "Asia/Taipei")
    checked_at = _index_candidate_datetime(
        calendar_status.get("checked_at"),
        timezone_name=timezone_name,
    ) or datetime.now(ZoneInfo(timezone_name))
    phase = str(calendar_status.get("phase") or "unknown")
    current_date = _index_candidate_date(
        calendar_status.get("date"),
        timezone_name=timezone_name,
    ) or checked_at.date()
    previous_trading_day = _index_candidate_date(
        calendar_status.get("previous_trading_day"),
        timezone_name=timezone_name,
    )
    expected_trade_date = (
        current_date
        if calendar_status.get("is_trading_day") is True
        and phase not in {"preopen_pending", "preopen", "market_closed"}
        else previous_trading_day
    )

    latest_point = _latest_intraday_point(intraday)
    intraday_time = (
        latest_point.get("event_time")
        or latest_point.get("bar_time")
        or latest_point.get("time")
        if latest_point
        else None
    )
    intraday_date = _index_candidate_date(
        intraday_time or (intraday or {}).get("trade_date"),
        timezone_name=timezone_name,
    )
    intraday_candidate = {
        "candidate": "intraday_last_trade",
        "value": latest_point.get("price") if latest_point else None,
        "event_time": _json_value(intraday_time),
        "trade_date": intraday_date.isoformat() if intraday_date else None,
        "source": (
            str((intraday or {}).get("source") or "market_index_intraday")
        ),
        "eligible": bool(
            latest_point
            and latest_point.get("price") is not None
            and expected_trade_date is not None
            and intraday_date == expected_trade_date
        ),
    }

    summary_time = index_snapshot.get("as_of")
    summary_date = _index_candidate_date(
        index_snapshot.get("time") or summary_time,
        timezone_name=timezone_name,
    )
    summary_candidate = {
        "candidate": "index_summary",
        "value": index_snapshot.get("close"),
        "event_time": _json_value(summary_time),
        "trade_date": summary_date.isoformat() if summary_date else None,
        "source": str(index_snapshot.get("source") or "market_index_summary"),
        "eligible": bool(
            index_snapshot.get("close") is not None
            and expected_trade_date is not None
            and summary_date == expected_trade_date
        ),
    }

    explicit_official_status = str(
        index_snapshot.get("official_close_status") or ""
    ).casefold()
    official_source = str(
        index_snapshot.get("official_close_source")
        or index_snapshot.get("source")
        or ""
    )
    official_source_key = official_source.casefold()
    source_is_official = any(
        marker in official_source_key
        for marker in (
            "twse_index_5s_snapshot",
            "twse_openapi",
            "tpex_openapi",
            "market_index_daily_stat",
        )
    )
    after_confirmation_deadline = bool(
        summary_date is not None
        and (
            summary_date < current_date
            or checked_at.time() >= time(13, 33)
        )
    )
    official_price = (
        index_snapshot.get("official_close_price")
        if index_snapshot.get("official_close_price") is not None
        else index_snapshot.get("close")
    )
    official_confirmed = bool(
        official_price is not None
        and summary_candidate["eligible"]
        and (
            explicit_official_status in {"confirmed", "official", "final"}
            or source_is_official and after_confirmation_deadline
        )
    )
    official_candidate = {
        "candidate": "official_close",
        "value": official_price if official_confirmed else None,
        "raw_value": official_price,
        "event_time": _json_value(
            index_snapshot.get("official_close_time") or summary_time
        ),
        "trade_date": summary_candidate["trade_date"],
        "source": official_source or None,
        "eligible": official_confirmed,
        "confirmation_evidence": (
            "explicit_official_status"
            if explicit_official_status in {"confirmed", "official", "final"}
            else "official_source_after_confirmation_deadline"
            if official_confirmed
            else None
        ),
    }

    warnings: list[str] = []
    candidate_dates = {
        str(candidate["trade_date"])
        for candidate in (intraday_candidate, summary_candidate)
        if candidate.get("value") is not None and candidate.get("trade_date")
    }
    if len(candidate_dates) > 1:
        warnings.append(
            "Taiwan index intraday and summary candidates belong to different trade dates."
        )

    selected_candidate: dict[str, Any] | None = None
    selection_reason = "no_eligible_candidate"
    if official_confirmed and phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }:
        selected_candidate = official_candidate
        selection_reason = "confirmed_official_close"
    elif phase in {"regular", "regular_live", "closing_auction"}:
        if intraday_candidate["eligible"]:
            selected_candidate = intraday_candidate
            selection_reason = "active_session_prefers_intraday_last_trade"
        elif summary_candidate["eligible"]:
            selected_candidate = summary_candidate
            selection_reason = "active_session_intraday_unavailable_summary_fallback"
    else:
        eligible = [
            candidate
            for candidate in (intraday_candidate, summary_candidate)
            if candidate["eligible"]
        ]
        if eligible:
            selected_candidate = max(
                eligible,
                key=lambda candidate: (
                    _index_candidate_datetime(
                        candidate.get("event_time"),
                        timezone_name=timezone_name,
                    )
                    or datetime.min.replace(tzinfo=ZoneInfo(timezone_name))
                ),
            )
            selection_reason = "latest_same_trade_date_candidate_pending_confirmation"

    closing_auction = phase == "closing_auction"
    post_close_current_day = bool(
        calendar_status.get("is_trading_day") is True
        and phase in {"post_close", "post_close_snapshot", "market_closed"}
    )
    official_close_status = (
        "confirmed"
        if official_confirmed
        else "closing_auction_pending"
        if closing_auction
        else "pending"
        if post_close_current_day
        else "confirmed_latest_session"
        if summary_candidate["eligible"]
        and summary_date is not None
        and summary_date < current_date
        and source_is_official
        else "not_available_yet"
    )
    selected_value = (
        selected_candidate.get("value")
        if isinstance(selected_candidate, dict)
        else None
    )
    quote_semantics = (
        "official_close"
        if official_close_status == "confirmed"
        else "closing_auction_last_trade"
        if closing_auction
        else "official_close_pending"
        if official_close_status == "pending"
        else "current_session_last_trade"
        if phase in {"regular", "regular_live"}
        else "latest_completed_session"
        if official_close_status == "confirmed_latest_session"
        else "unavailable"
    )
    delivery_status = (
        "official_close"
        if official_close_status == "confirmed"
        else "closing_auction"
        if closing_auction
        else "official_close_pending"
        if official_close_status == "pending"
        else "latest_completed_session"
        if official_close_status == "confirmed_latest_session"
        else "unavailable"
    )
    return {
        "selected_candidate": (
            selected_candidate.get("candidate")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_value": selected_value,
        "selected_source": (
            selected_candidate.get("source")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_event_time": (
            selected_candidate.get("event_time")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_trade_date": (
            selected_candidate.get("trade_date")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selection_reason": selection_reason,
        "expected_trade_date": (
            expected_trade_date.isoformat() if expected_trade_date else None
        ),
        "last_trade_available": intraday_candidate["eligible"],
        "last_trade_price": (
            intraday_candidate["value"]
            if intraday_candidate["eligible"]
            else None
        ),
        "last_trade_time": intraday_candidate["event_time"],
        "last_trade_is_current_session": intraday_candidate["eligible"],
        "official_close_available": official_confirmed,
        "official_close_status": official_close_status,
        "official_close_price": (
            official_candidate["value"] if official_confirmed else None
        ),
        "official_close_trade_date": (
            official_candidate["trade_date"] if official_confirmed else None
        ),
        "official_close_source": (
            official_candidate["source"] if official_confirmed else None
        ),
        "official_close_raw": (
            official_candidate["raw_value"] if official_confirmed else None
        ),
        "official_close_display": (
            f"{float(official_candidate['value']):,.2f}"
            if official_confirmed
            and isinstance(official_candidate["value"], (int, float))
            else None
        ),
        "official_close_precision": 2 if official_confirmed else None,
        "quote_semantics": quote_semantics,
        "delivery_status": delivery_status,
        "candidates": [
            intraday_candidate,
            summary_candidate,
            official_candidate,
        ],
        "warnings": warnings,
    }


def _compact_index_quote(
    *,
    index_id: str,
    index_snapshot: dict[str, Any] | None,
    intraday: dict[str, Any] | None,
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = index_snapshot if isinstance(index_snapshot, dict) else {}
    latest_point = _latest_intraday_point(intraday)
    intraday_points = (
        [point for point in intraday.get("points", []) if isinstance(point, dict)]
        if isinstance(intraday, dict)
        else []
    )
    effective_calendar = calendar_status or build_taiwan_calendar_status()
    resolution = resolve_taiwan_index_quote_state(
        intraday=intraday,
        index_snapshot=snapshot,
        calendar_status=effective_calendar,
        index_id=index_id,
        acquisition_policy=str(
            (intraday or {}).get("acquisition_policy")
            or snapshot.get("acquisition_policy")
            or "unspecified"
        ),
    )
    source = str(
        resolution.get("selected_source")
        or snapshot.get("source")
        or "market_index_summary"
    )
    latest_price = resolution.get("selected_value")
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
    # A rejected stale candidate still needs an observable age.  Selection and
    # freshness are separate concerns: the resolver may refuse to use the
    # value while the outward contract continues to explain why it was stale.
    quote_time = (
        resolution.get("selected_event_time")
        or resolution.get("last_trade_time")
    )
    freshness = classify_market_snapshot(
        calendar_status=effective_calendar,
        quote_time=quote_time,
    )
    source_supports_intraday = bool(latest_point) and _intraday_source_is_live(source)
    if not source_supports_intraday and freshness["status"] in {"live", "delayed"}:
        freshness = {
            **freshness,
            "status": "delayed",
            "is_live": False,
            "is_realtime": False,
        }
    timezone_name = str(effective_calendar.get("timezone") or "Asia/Taipei")
    selected_trade_date = resolution.get("selected_trade_date")
    selected_session_date = _index_candidate_date(
        selected_trade_date,
        timezone_name=timezone_name,
    )
    snapshot_session_date = _index_candidate_date(
        snapshot.get("time") or snapshot.get("as_of"),
        timezone_name=timezone_name,
    )
    snapshot_matches_selected_session = bool(
        selected_session_date is not None
        and snapshot_session_date == selected_session_date
    )

    def _point_matches_selected_session(point: dict[str, Any]) -> bool:
        if selected_session_date is None:
            return True
        point_date = _index_candidate_date(
            point.get("trade_date")
            or point.get("event_time")
            or point.get("bar_time")
            or point.get("time"),
            timezone_name=timezone_name,
        )
        return point_date == selected_session_date

    selected_intraday_points = [
        point
        for point in intraday_points
        if _point_matches_selected_session(point)
    ]
    open_values = [
        value
        for point in selected_intraday_points
        for value in [point.get("open") if point.get("open") is not None else point.get("price")]
        if isinstance(value, (int, float))
    ]
    high_values = [
        value
        for point in selected_intraday_points
        for value in [point.get("high") if point.get("high") is not None else point.get("price")]
        if isinstance(value, (int, float))
    ]
    if snapshot_matches_selected_session and isinstance(snapshot.get("high"), (int, float)):
        high_values.append(snapshot["high"])
    low_values = [
        value
        for point in selected_intraday_points
        for value in [point.get("low") if point.get("low") is not None else point.get("price")]
        if isinstance(value, (int, float))
    ]
    if snapshot_matches_selected_session and isinstance(snapshot.get("low"), (int, float)):
        low_values.append(snapshot["low"])
    volume_values = [
        int(point["volume"])
        for point in selected_intraday_points
        if isinstance(point.get("volume"), (int, float)) and point["volume"] > 0
    ]
    snapshot_volume = snapshot.get("volume")
    volume = (
        sum(volume_values)
        if volume_values
        else snapshot_volume
        if snapshot_matches_selected_session
        and isinstance(snapshot_volume, (int, float))
        and snapshot_volume > 0
        else None
    )
    intraday_volume_semantics = (
        intraday.get("volume_semantics")
        if isinstance(intraday, dict)
        else None
    )
    canonical_volume_unit = (
        intraday.get("canonical_volume_unit")
        if isinstance(intraday, dict) and intraday.get("canonical_volume_unit")
        else snapshot.get("canonical_volume_unit")
    )
    provider_volume_unit = (
        intraday.get("provider_volume_unit")
        if isinstance(intraday, dict) and intraday.get("provider_volume_unit")
        else snapshot.get("provider_volume_unit")
    )
    if (
        provider_volume_unit is None
        and isinstance(intraday, dict)
        and intraday.get("volume_unit")
        and not canonical_volume_unit
    ):
        provider_volume_unit = intraday.get("volume_unit")
    volume_unit = (
        canonical_volume_unit
        or provider_volume_unit
        or snapshot.get("volume_unit")
    )
    volume_status = (
        "not_provided"
        if volume is None
        else "provider_specific"
        if not volume_unit
        or not canonical_volume_unit
        or "provider" in str(intraday_volume_semantics or "")
        else "available"
    )
    trade_value = (
        snapshot.get("trade_value")
        if snapshot_matches_selected_session
        and snapshot.get("trade_value") is not None
        else snapshot.get("estimated_trade_value")
        if snapshot_matches_selected_session
        and snapshot.get("estimated_trade_value") is not None
        else None
    )
    trade_value_status = (
        "official"
        if trade_value is not None and snapshot.get("trade_value") is not None
        else "estimated"
        if trade_value is not None
        and snapshot.get("estimated_trade_value") is not None
        else "not_provided"
    )
    previous_session = (
        {
            "trade_date": snapshot_session_date.isoformat(),
            "source": snapshot.get("source"),
            "open_price": snapshot.get("open"),
            "high_price": snapshot.get("high"),
            "low_price": snapshot.get("low"),
            "close_price": snapshot.get("close"),
            "trade_value": (
                snapshot.get("trade_value")
                if snapshot.get("trade_value") is not None
                else snapshot.get("estimated_trade_value")
            ),
            "trade_value_unit": (
                "TWD"
                if snapshot.get("trade_value") is not None
                or snapshot.get("estimated_trade_value") is not None
                else None
            ),
            "trade_value_status": (
                "official"
                if snapshot.get("trade_value") is not None
                else "estimated"
                if snapshot.get("estimated_trade_value") is not None
                else "not_provided"
            ),
        }
        if snapshot_session_date is not None
        and selected_session_date is not None
        and snapshot_session_date != selected_session_date
        else None
    )

    quote = {
        "kind": "quote_snapshot",
        "instrument_type": "cash_index",
        "source": source,
        "provider": source,
        "status": (
            "official_close"
            if resolution["official_close_status"] == "confirmed"
            else "official_close_pending"
            if resolution["official_close_status"] == "pending"
            else "closing_auction"
            if resolution["official_close_status"] == "closing_auction_pending"
            else freshness["status"]
        ),
        "index_id": index_id,
        "trade_date": resolution.get("selected_trade_date"),
        "quote_time": _json_value(quote_time),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "price_available": latest_price is not None,
        "last_trade_available": resolution["last_trade_available"],
        "last_trade_price": resolution["last_trade_price"],
        "last_trade_time": resolution["last_trade_time"],
        "last_trade_is_current_session": resolution[
            "last_trade_is_current_session"
        ],
        "official_close_available": resolution["official_close_available"],
        "official_close_status": resolution["official_close_status"],
        "official_close_price": resolution["official_close_price"],
        "official_close_trade_date": resolution[
            "official_close_trade_date"
        ],
        "official_close_source": resolution["official_close_source"],
        "official_close_raw": resolution["official_close_raw"],
        "official_close_display": resolution["official_close_display"],
        "official_close_precision": resolution["official_close_precision"],
        "resolution_version": resolution["resolution_version"],
        "resolution_id": resolution["resolution_id"],
        "acquisition_policy": resolution["acquisition_policy"],
        "decision_usable": resolution["decision_usable"],
        "current_observation": resolution["current_observation"],
        "selected_candidate": resolution["selected_candidate"],
        "selection_reason": resolution["selection_reason"],
        "quote_candidates": resolution["candidates"],
        "previous_close": previous_close,
        "open_price": (
            open_values[0]
            if open_values
            else snapshot.get("open")
            if snapshot_matches_selected_session
            else None
        ),
        "high_price": (
            max(high_values)
            if high_values
            else snapshot.get("high")
            if snapshot_matches_selected_session
            else None
        ),
        "low_price": (
            min(low_values)
            if low_values
            else snapshot.get("low")
            if snapshot_matches_selected_session
            else None
        ),
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "volume_unit": volume_unit or (
            "provider_units" if volume is not None else None
        ),
        "canonical_volume_unit": canonical_volume_unit,
        "provider_volume_unit": provider_volume_unit or (
            "provider_units" if volume is not None and not canonical_volume_unit else None
        ),
        "volume_status": volume_status,
        "volume_semantics": (
            intraday_volume_semantics
            or "provider_index_volume_not_market_trade_value"
            if volume is not None
            else "not_available"
        ),
        "trade_value": trade_value,
        "trade_value_unit": "TWD" if trade_value is not None else None,
        "trade_value_status": trade_value_status,
        "trade_value_source": (
            snapshot.get("source") if trade_value is not None else None
        ),
        "trade_value_source_trade_date": (
            snapshot_session_date.isoformat()
            if trade_value is not None and snapshot_session_date is not None
            else None
        ),
        "official_vwap": (
            intraday.get("official_vwap")
            if isinstance(intraday, dict)
            else None
        ),
        "approx_vwap": (
            intraday.get("approx_vwap")
            if isinstance(intraday, dict)
            else None
        ),
        "vwap_method": (
            intraday.get("vwap_method")
            if isinstance(intraday, dict)
            else None
        ),
        "vwap_confidence": (
            intraday.get("vwap_confidence")
            if isinstance(intraday, dict)
            else None
        ),
        "is_realtime": freshness["is_realtime"],
        "is_live": freshness["is_live"],
        "is_latest_session_quote": freshness["is_latest_session_quote"],
        "market_status": freshness["market_status"],
        "current_session_phase": freshness["current_session_phase"],
        "last_quote_session": freshness["last_quote_session"],
        "quote_semantics": resolution["quote_semantics"],
        "delivery_status": resolution["delivery_status"],
        "session_reconciliation_status": (
            "separated" if previous_session is not None else "aligned"
        ),
        "current_session": {
            "trade_date": selected_trade_date,
            "source": source,
            "open_price": (
                open_values[0]
                if open_values
                else snapshot.get("open")
                if snapshot_matches_selected_session
                else None
            ),
            "high_price": (
                max(high_values)
                if high_values
                else snapshot.get("high")
                if snapshot_matches_selected_session
                else None
            ),
            "low_price": (
                min(low_values)
                if low_values
                else snapshot.get("low")
                if snapshot_matches_selected_session
                else None
            ),
            "latest_price": latest_price,
            "trade_value": trade_value,
            "trade_value_unit": "TWD" if trade_value is not None else None,
            "trade_value_status": trade_value_status,
        },
        "previous_session": previous_session,
        "warnings": resolution["warnings"],
        "latency_ms": None,
        "freshness": {
            **freshness,
            "status": (
                "latest_completed_session"
                if resolution["official_close_status"]
                in {"confirmed", "confirmed_latest_session"}
                else freshness["status"]
            ),
            "quote_semantics": resolution["quote_semantics"],
            "delivery_status": resolution["delivery_status"],
            "expected_trade_date": resolution["expected_trade_date"],
            "warnings": resolution["warnings"],
            "message": (
                "Index intraday freshness is derived from quote time and the Taiwan trading calendar."
                if latest_point
                else "Index intraday was not requested or not available; using latest index summary."
            ),
        },
    }
    quote["components"] = _quote_components(quote)
    return quote


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
    daily_chart: dict[str, Any] | None,
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
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quote = _compact_index_quote(
        index_id=index_id,
        index_snapshot=index_snapshot,
        intraday=intraday if include_intraday else None,
        calendar_status=calendar_status,
    )
    intraday_bars = _compact_single_intraday_series(
        raw_payload=intraday,
        interval="1m",
        include_intraday=include_intraday,
        market_data_params=market_data_params,
    )
    for series in intraday_bars.get("series", {}).values():
        if not isinstance(series, dict):
            continue
        series["session_phase"] = quote.get("current_session_phase")
        series["market_status"] = quote.get("market_status")
        series["official_close_status"] = quote.get("official_close_status")
        series["delivery_status"] = quote.get("delivery_status")
    warnings = [
        *warnings,
        *[
            str(item)
            for item in quote.get("warnings") or []
            if str(item).strip()
        ],
    ]
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
    freshness_by_domain = _index_freshness_by_domain(
        quote=quote,
        intraday_bars=intraday_bars,
        market_chip=market_chip,
        missing=missing,
    )
    freshness_by_capability = {
        "target.identity": {
            "status": "current",
            "dataset": "market_index_identity",
            "is_current": True,
            "refresh_recommended": False,
        },
        "quote.snapshot": {
            **_quote_freshness_domain(quote),
            "dataset": "market_index_quote",
        },
        **_quote_component_freshness_rows(quote),
        "intraday.bars": {
            **_intraday_bar_freshness_resource(intraday_bars),
            "dataset": "market_index_intraday",
        },
        "daily.ohlcv": {
            "status": (
                "current"
                if isinstance(daily_chart, dict)
                and bool(daily_chart.get("points"))
                else "missing"
            ),
            "dataset": "market_index_daily_stat",
            "latest": (
                daily_chart.get("latest_data_date")
                or daily_chart.get("as_of")
                if isinstance(daily_chart, dict)
                else None
            ),
            "is_current": bool(
                isinstance(daily_chart, dict)
                and daily_chart.get("points")
            ),
            "refresh_recommended": not bool(
                isinstance(daily_chart, dict)
                and daily_chart.get("points")
            ),
        },
    }
    slots = _build_tw_index_slots(
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
    )
    slots.update(
        _quote_component_slots(
            quote,
            payload_level=payload_level,
        )
    )
    return {
        "kind": "tw_index_compact_evidence",
        "version": "tw_index_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "daily_chart": daily_chart or {},
        "intraday_bars": intraday_bars,
        "technical": technical,
        "chips": chips,
        "contributions": contributions,
        "freshness_by_domain": freshness_by_domain,
        "freshness_by_capability": freshness_by_capability,
        "data_quality": data_quality,
        "slots": slots,
        "source_refs": source_refs,
    }


def _build_stock_compact_evidence(
    *,
    stock: StockMaster | None,
    company_profile: dict[str, Any],
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
    event_context: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
    technical_evidence: dict[str, Any] | None = None,
    financial_contract: dict[str, Any] | None = None,
    fundamentals_applicable: bool = True,
    latest_daily_evidence: Any = None,
) -> dict[str, Any]:
    target = {
        "type": "tw_stock",
        "id": stock_id,
        "label": stock.stock_name if stock else None,
        "market": stock.market if stock else "TW",
        "instrument_type": getattr(stock, "instrument_type", None),
    }
    technical = _compact_technical_evidence(
        analysis=technical_analysis,
        technical_levels=technical_levels,
        technical_reports=technical_reports,
    )
    technical_evidence = (
        technical_evidence if isinstance(technical_evidence, dict) else {}
    )
    technical["contract_version"] = "tw_technical_current_state_v2"
    technical["advanced_shadow"] = technical_evidence.get("structure_v2")
    technical_indicators = technical_evidence.get("indicators")
    technical_advanced = {
        key: technical_evidence.get(key)
        for key in (
            "structure_v2",
            "swings",
            "fibonacci",
            "divergence",
            "breakout",
            "volume_profile",
            "anchored_vwap",
            "relative_strength",
        )
        if isinstance(technical_evidence.get(key), dict)
    }
    margin_payload = (
        _compact_row(
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
        )
        or {}
    )
    margin_quantity_fields = (
        "margin_buy",
        "margin_sell",
        "margin_today_balance",
        "short_sale",
        "short_covering",
        "short_today_balance",
    )
    chips = {
        "institutional": {
            **(
                _compact_row(
                    latest_institutional,
                    (
                        "trade_date",
                        "foreign_investor_net",
                        "investment_trust_net",
                        "dealer_net",
                        "total_institutional_net",
                    ),
                )
                or {}
            ),
            "quantity_unit": "shares",
            "lot_size": 1000,
        },
        "margin": {
            **margin_payload,
            "quantity_unit": "lots",
            "raw_unit": "lots",
            "normalized_unit": "shares",
            "normalized_quantities": {
                field: margin_payload[field] * 1000
                for field in margin_quantity_fields
                if isinstance(margin_payload.get(field), (int, float))
            },
            "lot_size": 1000,
        },
        "shareholding": {
            "trade_date": (
                max(
                    (
                        str(getattr(row, "data_date", "") or "")
                        for row in shareholding
                        if getattr(row, "data_date", None)
                    ),
                    default=None,
                )
            ),
            "distribution": [
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
            "source": "shareholding_distribution_weekly",
            "freshness": {
                "status": "current" if shareholding else "missing",
            },
        },
        "broker_branch": {
            "trade_date": _json_value(branch_summary.get("trade_date")),
            "currency": "TWD",
            "price_unit": "TWD",
            "quantity_unit": "lots",
            "lot_size": 1000,
            "requested_days": branch_summary.get("requested_days"),
            "available_days": branch_summary.get("available_days"),
            "is_partial": branch_summary.get("is_partial"),
            **_broker_branch_metadata(branch_summary),
            "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])[:5]],
            "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])[:5]],
        },
    }
    latest_financial_payload = _compact_row(
        latest_financial,
        (
            "period",
            "report_date",
            "released_at",
            "filed_at",
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
    if latest_financial is not None:
        latest_financial_payload.update(source_reported_financial_semantics(latest_financial))

    financial_history_payload = []
    for row in financial_history[-4:]:
        payload = _compact_row(
            row,
            (
                "period",
                "report_date",
                "released_at",
                "filed_at",
                "eps",
                "book_value_per_share",
                "roe",
                "roa",
            ),
        )
        payload.update(source_reported_financial_semantics(row))
        financial_history_payload.append(payload)

    revenue_continuity = analyze_monthly_revenue_continuity(revenue_history)
    resolved_financial_contract = (
        financial_contract
        or build_legacy_financial_contract(
            stock_id=stock_id,
            financial_history=financial_history,
            revenue_history=revenue_history,
            mode="current_comparable",
            revenue_continuity=revenue_continuity,
        )
    )
    fundamentals = {
        "status": (
            "not_applicable"
            if not fundamentals_applicable
            else "ready"
            if latest_revenue is not None or latest_financial is not None
            else "missing"
        ),
        "applicability_status": (
            "applicable" if fundamentals_applicable else "not_applicable"
        ),
        "availability_status": (
            "available"
            if fundamentals_applicable
            and (latest_revenue is not None or latest_financial is not None)
            else "missing"
            if fundamentals_applicable
            else "not_applicable"
        ),
        "reason_codes": (
            []
            if fundamentals_applicable
            else ["ETF_FUNDAMENTALS_NOT_APPLICABLE"]
        ),
        "contract_version": FINANCIAL_CONTRACT_VERSION,
        "currency": "TWD",
        "source_amount_unit": "TWD_thousands",
        "normalized_amount_unit": "TWD_thousands",
        "amount_scale": 1000,
        "ratio_unit": "percent",
        "per_share_unit": "TWD_per_share",
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
        "revenue_continuity": revenue_continuity,
        "financial_contract": resolved_financial_contract,
        "latest_financial": latest_financial_payload,
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
        "financial_history": financial_history_payload,
    }
    data_quality = {
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(
            dict.fromkeys(warnings + list(revenue_continuity.get("issues") or []))
        ),
    }
    event_context = event_context if isinstance(event_context, dict) else {}
    event_data = (
        event_context.get("data")
        if isinstance(event_context.get("data"), dict)
        else {}
    )
    events = {
        key.split(".", 1)[1]: value
        for key, value in event_data.items()
        if str(key).startswith("events.")
    }
    regulation = {
        key.split(".", 1)[1]: value
        for key, value in event_data.items()
        if str(key).startswith("regulation.")
    }
    corporate_actions = event_data.get("corporate.actions")
    raw_payload_level = intraday_bars.get("payload_level") if isinstance(intraday_bars, dict) else None
    payload_level = str(raw_payload_level) if raw_payload_level in PAYLOAD_LEVELS else "compact"
    freshness_by_capability = _build_freshness_by_capability(
        quote=quote,
        intraday_bars=intraday_bars,
        source_health=source_health,
        overnight_impact=overnight_impact,
        missing=missing,
        canonical_daily_evidence=latest_daily_evidence,
    )
    freshness_by_capability.update(
        event_context.get("freshness_by_capability")
        if isinstance(event_context.get("freshness_by_capability"), dict)
        else {}
    )
    freshness_by_capability["company.profile"] = {
        "status": company_profile.get("status"),
        "dataset": company_profile.get("source"),
        "latest": company_profile.get("as_of"),
        "is_current": company_profile.get("status") in {"ready", "partial"},
        "coverage_status": (
            "complete"
            if company_profile.get("status") == "ready"
            else "partial"
            if company_profile.get("status") == "partial"
            else "missing"
        ),
        "refresh_recommended": False,
        "cache_policy": "read_only_no_refresh",
    }
    technical_payloads = {
        "technical.indicators": technical_indicators,
        "technical.swings": technical_advanced.get("swings"),
        "technical.fibonacci": technical_advanced.get("fibonacci"),
        "technical.divergence": technical_advanced.get("divergence"),
        "technical.breakout": technical_advanced.get("breakout"),
        "technical.volume_profile": technical_advanced.get("volume_profile"),
        "technical.anchored_vwap": technical_advanced.get("anchored_vwap"),
        "technical.relative_strength": technical_advanced.get("relative_strength"),
    }
    for capability_id, payload in technical_payloads.items():
        raw_status = (
            str(payload.get("status") or "missing")
            if isinstance(payload, dict)
            else "missing"
        )
        temporal_freshness = (
            payload.get("freshness")
            if isinstance(payload, dict)
            and isinstance(payload.get("freshness"), dict)
            else {}
        )
        status = (
            str(temporal_freshness.get("status") or "current")
            if raw_status in {"ready", "ready_empty"}
            else raw_status
        )
        freshness_by_capability[capability_id] = {
            "status": status,
            "evidence_status": raw_status,
            "dataset": "market_daily_price",
            "latest": (
                payload.get("as_of")
                if isinstance(payload, dict)
                else technical_evidence.get("as_of")
            )
            or technical_evidence.get("as_of"),
            "is_current": status not in {"missing", "stale", "unavailable"},
            "decision_usable": raw_status in {"ready", "ready_empty"},
            "coverage_status": (
                "complete"
                if raw_status in {"ready", "ready_empty"}
                else "partial"
                if raw_status == "partial"
                else "missing"
            ),
            "refresh_recommended": False,
            "cache_policy": "read_only_derived",
        }
    slots = _build_tw_stock_slots(
        target=target,
        as_of=as_of,
        payload_level=payload_level,
        quote=quote,
        intraday_bars=intraday_bars,
        technical=technical,
        chips=chips,
        fundamentals=fundamentals,
        cross_market=overnight_impact,
        missing=data_quality["missing"],
        warnings=data_quality["warnings"],
    )
    slots.update(
        _quote_component_slots(
            quote,
            payload_level=payload_level,
        )
    )
    slots.update(
        event_context.get("slots")
        if isinstance(event_context.get("slots"), dict)
        else {}
    )
    return {
        "kind": "stock_compact_evidence",
        "version": "stock_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "company_profile": company_profile,
        "intraday_bars": intraday_bars,
        "technical": technical,
        "technical_indicators": technical_indicators,
        "technical_advanced": technical_advanced,
        "chips": chips,
        "fundamentals": fundamentals,
        "events": events,
        "corporate_actions": corporate_actions,
        "regulation": regulation,
        "cross_market": overnight_impact,
        "freshness_by_domain": _build_freshness_by_domain(
            quote=quote,
            intraday_bars=intraday_bars,
            source_health=source_health,
            overnight_impact=overnight_impact,
            missing=missing,
        ),
        "freshness_by_capability": freshness_by_capability,
        "data_quality": data_quality,
        "slots": slots,
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
    if freshness is not None:
        envelope["freshness"] = freshness
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
