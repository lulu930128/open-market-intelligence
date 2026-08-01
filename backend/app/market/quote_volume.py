from __future__ import annotations

from datetime import date, datetime
from typing import Any


TAIWAN_STANDARD_LOT_SIZE_SHARES = 1_000
TAIWAN_MIS_VOLUME_SCOPE = "regular_session_board_lot_cumulative"
TAIWAN_OFFICIAL_DAILY_VOLUME_SCOPE = "official_daily_aggregate"


def _date_text(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    text = str(value or "").strip()
    return text or None


def _non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_taiwan_quote_volume_contract(
    *,
    snapshot_trade_date: Any,
    cumulative_volume_lots: Any,
    last_trade_volume_lots: Any = None,
    official_daily_trade_date: Any = None,
    official_daily_volume_shares: Any = None,
    official_daily_volume_source: Any = None,
) -> dict[str, Any]:
    """Normalize TWSE MIS volume fields without overstating their market scope."""

    snapshot_date = _date_text(snapshot_trade_date)
    official_date = _date_text(official_daily_trade_date)
    cumulative_lots = _non_negative_int(cumulative_volume_lots)
    last_trade_lots = _non_negative_int(last_trade_volume_lots)
    official_shares = _non_negative_int(official_daily_volume_shares)
    official_source = str(official_daily_volume_source or "").strip() or None
    cumulative_shares = (
        cumulative_lots * TAIWAN_STANDARD_LOT_SIZE_SHARES
        if cumulative_lots is not None
        else None
    )
    last_trade_shares = (
        last_trade_lots * TAIWAN_STANDARD_LOT_SIZE_SHARES
        if last_trade_lots is not None
        else None
    )

    reconciliation: dict[str, Any] = {
        "reference_dataset": "market_daily_price",
        "reference_source": official_source,
        "reference_trade_date": official_date,
        "reference_volume_shares": official_shares,
        "reference_volume_scope": TAIWAN_OFFICIAL_DAILY_VOLUME_SCOPE,
        "snapshot_trade_date": snapshot_date,
        "snapshot_volume_shares": cumulative_shares,
        "snapshot_volume_scope": TAIWAN_MIS_VOLUME_SCOPE,
        "difference_shares": None,
        "difference_pct": None,
        "difference_semantics": "informational_cross_scope_difference",
        "tolerance_pct": None,
        "status": "not_comparable",
        "reason": None,
        "decision_usable": False,
    }

    if cumulative_shares is None:
        reconciliation["reason"] = "provider_cumulative_volume_not_available"
    elif official_shares is None:
        reconciliation["reason"] = "official_daily_volume_not_available"
    elif snapshot_date is None or official_date is None:
        reconciliation["reason"] = "trade_date_not_available"
    elif snapshot_date != official_date:
        reconciliation["reason"] = "trade_dates_do_not_match"
    elif official_shares <= 0:
        reconciliation["reason"] = "official_daily_volume_not_positive"
    else:
        difference_shares = cumulative_shares - official_shares
        difference_pct = round((difference_shares / official_shares) * 100, 4)
        reconciliation.update(
            {
                "difference_shares": difference_shares,
                "difference_pct": difference_pct,
                "status": "scope_different",
                "reason": "provider_and_official_volume_scopes_differ",
            }
        )

    return {
        "total_volume_lots": cumulative_lots,
        "cumulative_volume_lots": cumulative_lots,
        "cumulative_volume_shares": cumulative_shares,
        "last_trade_volume_lots": last_trade_lots,
        "last_trade_volume_shares": last_trade_shares,
        "lot_size": TAIWAN_STANDARD_LOT_SIZE_SHARES,
        "volume_unit": "lots",
        "canonical_volume_unit": "shares",
        "provider_volume_unit": "lots",
        "volume_semantics": "session_cumulative_provider_volume",
        "volume_scope": TAIWAN_MIS_VOLUME_SCOPE,
        "volume_source": "twse_mis",
        "volume_source_field": "v",
        "volume_status": (
            "available" if cumulative_lots is not None else "unavailable"
        ),
        "provider_volume_available": cumulative_lots is not None,
        "last_trade_volume_semantics": "provider_reported_last_match_volume",
        "last_trade_volume_source_field": "tv",
        "last_trade_volume_status": (
            "available" if last_trade_lots is not None else "not_provided"
        ),
        "official_daily_volume_shares": official_shares,
        "official_daily_volume_trade_date": official_date,
        "official_daily_volume_source": official_source,
        "official_daily_volume_scope": TAIWAN_OFFICIAL_DAILY_VOLUME_SCOPE,
        "volume_includes_odd_lot": False,
        "volume_includes_after_hours": False,
        "volume_includes_closing_auction": None,
        "volume_reconciliation": reconciliation,
        "volume_decision_usable": reconciliation["decision_usable"],
    }
