"""JP-owned price-reference semantics consumed unchanged by AI contexts."""

from typing import Any
import math
from app.market.calendar_status import build_jp_calendar_status
from app.market.live_snapshot import classify_market_snapshot

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


def project_jp_intraday_reference(
    intraday_summary: dict[str, Any] | None,
    *,
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = _jp_intraday_latest(intraday_summary)
    if latest is None:
        return {}

    price = latest.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return {}
    previous_close = intraday_summary.get("previous_close") if intraday_summary else None
    change = None
    change_pct = None
    if (
        not isinstance(previous_close, bool)
        and isinstance(previous_close, (int, float))
        and math.isfinite(previous_close)
        and previous_close > 0
    ):
        change = float(price) - float(previous_close)
        change_pct = change / float(previous_close) * 100

    freshness = classify_market_snapshot(
        calendar_status=calendar_status or build_jp_calendar_status(),
        quote_time=latest.get("time"),
    )
    # An interval close is a price reference, never an observed last trade.
    current_session = freshness["is_current_session_quote"]
    latest_session = freshness["is_latest_session_quote"]
    freshness = {
        **freshness, "is_live": False, "is_realtime": False,
        "is_current_session_quote": False, "is_latest_session_quote": False,
        "bar_is_current_session": current_session, "bar_is_latest_session": latest_session,
        "quote_semantics": "intraday_bar_close_reference",
    }
    if freshness.get("status") == "live":
        freshness["status"] = "delayed"
        freshness["delivery_status"] = "delayed_current_session"
    quote_semantics = "intraday_bar_close_reference"
    return {
        "source": (
            intraday_summary.get("source") if intraday_summary else None
        )
        or "yahoo_finance_chart",
        "price": price,
        "latest_price": price,
        "last_price": price,
        "price_available": True,
        "last_trade_available": False,
        "last_trade_price": None,
        "last_trade_time": None,
        "last_trade_is_current_session": False,
        "depth_available": False,
        "depth_status": "unavailable",
        "indicative_match_available": False,
        "indicative_match_price": None,
        "indicative_match_volume_lots": None,
        "auction_indicative_available": False,
        "official_close_available": False,
        "official_close_status": "not_requested",
        "official_close_price": None,
        "fallback_used": True,
        "source_kind": "intraday_bar_close",
        "decision_usable": False,
        "bar_is_current_session": current_session,
        "bar_is_latest_session": latest_session,
        "limitations": ["QUOTE_SNAPSHOT_NOT_PROVIDED", "INTRADAY_BAR_CLOSE_REFERENCE_ONLY"],
        "change": change,
        "change_pct": change_pct,
        "volume": latest.get("volume"),
        "quote_time": latest.get("time"),
        "is_realtime": freshness["is_realtime"],
        "is_live": freshness["is_live"],
        "is_latest_session_quote": freshness["is_latest_session_quote"],
        "latency_ms": None,
        "session_phase": freshness["current_session_phase"],
        "current_session_phase": freshness["current_session_phase"],
        "market_status": freshness["market_status"],
        "quote_semantics": quote_semantics,
        "delivery_status": freshness["delivery_status"],
        "is_current_session_quote": freshness["is_current_session_quote"],
        "freshness": freshness,
        "provider": "yahoo_chart",
        "previous_close": previous_close,
        "change_reference": intraday_summary.get("change_reference") if intraday_summary else None,
        "previous_close_source": (
            intraday_summary.get("previous_close_source")
            if intraday_summary
            else None
        ),
        "previous_close_trade_date": (
            intraday_summary.get("previous_close_trade_date")
            if intraday_summary
            else None
        ),
        "volume_unit": (
            intraday_summary.get("volume_unit") if intraday_summary else None
        ),
        "volume_semantics": (
            intraday_summary.get("volume_semantics") if intraday_summary else None
        ),
        "volume_status": (
            intraday_summary.get("volume_status") if intraday_summary else None
        ),
        "point_count": (
            intraday_summary.get("point_count") if intraday_summary else None
        ),
    }
