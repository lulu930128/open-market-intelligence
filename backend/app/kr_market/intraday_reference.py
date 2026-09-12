"""Market-owned intraday reference; bars never become independent trade quotes."""

from typing import Any
from math import isfinite
from app.market.calendar_status import build_kr_calendar_status
from app.market.live_snapshot import classify_market_snapshot


def _latest(summary):
    if not isinstance(summary, dict):
        return None
    points = summary.get("points")
    if isinstance(points, list) and points and isinstance(points[-1], dict):
        return points[-1]
    latest = summary.get("latest_point")
    return latest if isinstance(latest, dict) else None


def build_intraday_price_reference(
    intraday_summary: dict[str, Any] | None,
    *,
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = _latest(intraday_summary)
    if latest is None:
        return {}
    price = latest.get("price")
    if type(price) not in (int, float) or not isfinite(price) or price <= 0:
        return {}
    previous_close = intraday_summary.get("previous_close") if intraday_summary else None
    change = None
    change_pct = None
    if type(previous_close) in (int, float) and isfinite(previous_close) and previous_close > 0:
        change = float(price) - float(previous_close)
        change_pct = change / float(previous_close) * 100
    freshness = classify_market_snapshot(
        calendar_status=calendar_status or build_kr_calendar_status(),
        quote_time=latest.get("time"),
    )
    freshness = {**freshness, "is_live": False, "is_realtime": False}
    if freshness.get("status") == "live":
        freshness["status"] = "delayed"
        freshness["delivery_status"] = "delayed"
    last_trade_available = isinstance(price, (int, float))
    return {
        "source": intraday_summary.get("source") or "unavailable",
        "provider": intraday_summary.get("provider") or intraday_summary.get("source"),
        "price": price,
        "latest_price": price,
        "last_price": price,
        "price_available": last_trade_available,
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
        "fallback_used": bool(intraday_summary.get("fallback_used")),
        "facts_usable": last_trade_available,
        "status": "partial",
        "usable_for_intraday": False,
        "decision_usable": False,
        "limitations": ["KR_INTRADAY_IS_NOT_TRADE_QUOTE"],
        "change": change,
        "change_pct": change_pct,
        "volume": latest.get("cumulative_volume", latest.get("volume")),
        "quote_time": latest.get("time"),
        "is_realtime": False,
        "is_live": False,
        "is_latest_session_quote": freshness["is_latest_session_quote"],
        "session_phase": freshness["current_session_phase"],
        "current_session_phase": freshness["current_session_phase"],
        "market_status": freshness["market_status"],
        "quote_semantics": "intraday_bar_close_reference",
        "delivery_status": freshness["delivery_status"],
        "is_current_session_quote": freshness["is_current_session_quote"],
        "freshness": freshness,
        "previous_close": previous_close,
        "previous_close_source": intraday_summary.get("previous_close_source"),
        "previous_close_trade_date": intraday_summary.get(
            "previous_close_trade_date"
        ),
        "volume_unit": intraday_summary.get("volume_unit"),
        "volume_semantics": intraday_summary.get("volume_semantics"),
        "point_count": intraday_summary.get("point_count"),
    }
