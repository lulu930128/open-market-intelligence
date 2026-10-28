from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.market_data.contracts import Quantity, QuantityUnit, QuoteObservation


TAIWAN_STANDARD_LOT_SIZE_SHARES = 1_000
TAIWAN_MIS_VOLUME_SCOPE = "regular_session_board_lot_cumulative"
TAIWAN_OFFICIAL_DAILY_VOLUME_SCOPE = "official_daily_aggregate"


def project_taiwan_cumulative_totals(quote: QuoteObservation | None) -> dict[str, Any]:
    """Project independent amount clock and scope without changing price health."""
    if quote is None or quote.cumulative_event_at is None or quote.cumulative_scope != "regular_board_lot":
        return {"cumulative_trade_value": None, "cumulative_trade_value_evidence": None}
    quantity = quote.cumulative_quantity
    lineage = quote.cumulative_lineage or quote.lineage
    shares = float(quantity.value) if quantity is not None and quantity.unit is QuantityUnit.SHARE else None
    value = float(quote.cumulative_turnover_value) if quote.cumulative_turnover_value is not None else None
    return {
        "cumulative_trade_value": value,
        "cumulative_trade_value_evidence": {
            "value": value, "currency": quote.cumulative_turnover_currency,
            "volume_shares": shares, "volume_unit": "shares",
            "provider_volume_unit": quantity.original_unit.value if quantity and quantity.original_unit else None,
            "trade_date": quote.trade_date.isoformat() if quote.trade_date else None,
            "event_time": quote.cumulative_event_at.isoformat(),
            "received_at": lineage.received_at.isoformat() if lineage.received_at else None,
            "provider": lineage.provider, "source": lineage.source,
            "source_field": "total.tradeValue", "volume_source_field": "total.tradeVolume",
            "scope": TAIWAN_MIS_VOLUME_SCOPE, "authority": lineage.authority.value,
            "official": False, "method": "provider_reported_cumulative",
            "raw_result_id": lineage.raw_receipt_id,
            "freshness": quote.cumulative_freshness.value if quote.cumulative_freshness else "unknown",
            "freshness_basis": "cumulative_event_time",
            "checked_at": quote.cumulative_checked_at.isoformat() if quote.cumulative_checked_at else None,
            "fresh_amount_usable": value is not None and quote.cumulative_freshness is not None and quote.cumulative_freshness.value in {"live", "fresh"},
        },
        "cumulative_volume_shares": shares,
        "cumulative_volume_lots": shares / 1000 if shares is not None else None,
        "cumulative_volume_trade_date": quote.trade_date.isoformat() if quote.trade_date else None,
        "cumulative_volume_event_time": quote.cumulative_event_at.isoformat(),
        "cumulative_volume_source": lineage.provider,
        "cumulative_volume_source_field": "total.tradeVolume",
        "volume_scope": TAIWAN_MIS_VOLUME_SCOPE,
    }


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


def taiwan_standard_board_lots(quantity: Quantity | None) -> int | None:
    """Accept only exact canonical quantities with a proven 1,000-share lot.

    Shares alone do not establish board-lot scope. In particular, never round
    odd shares or truncate fractional lots into this legacy volume contract.
    """
    if quantity is None or quantity.scale != TAIWAN_STANDARD_LOT_SIZE_SHARES:
        return None
    if quantity.unit is QuantityUnit.SHARE:
        lots = quantity.original_value
        if (
            quantity.original_unit is not QuantityUnit.BOARD_LOT
            or lots is None
            or quantity.value != lots * quantity.scale
        ):
            return None
    elif quantity.unit is QuantityUnit.BOARD_LOT:
        lots = quantity.value
    else:
        return None
    if not lots.is_finite() or lots != lots.to_integral_value():
        return None
    return int(lots)


def build_taiwan_quote_volume_contract(
    *,
    snapshot_trade_date: Any,
    cumulative_volume_lots: Any,
    last_trade_volume_lots: Any = None,
    official_daily_trade_date: Any = None,
    official_daily_volume_shares: Any = None,
    official_daily_volume_source: Any = None,
    provider: str = "twse_mis",
    cumulative_volume_source_field: str = "v",
    last_trade_volume_source_field: str = "tv",
) -> dict[str, Any]:
    """Normalize board-lot quote volume without overstating market scope."""

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
        "volume_source": provider,
        "volume_source_field": cumulative_volume_source_field,
        "volume_status": (
            "available" if cumulative_lots is not None else "unavailable"
        ),
        "provider_volume_available": cumulative_lots is not None,
        "last_trade_volume_semantics": "provider_reported_last_match_volume",
        "last_trade_volume_source_field": last_trade_volume_source_field,
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
