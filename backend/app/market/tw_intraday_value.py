"""Taiwan market-owned amount estimates over resolved canonical bars.

These are observed-window research facts. They never change bar eligibility,
price freshness, authority, or the resolver's decision/execution gates.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import CanonicalModel, QuantityUnit


class TaiwanBarValueRead(CanonicalModel):
    trade_value: float | None = None
    approx_trade_value: float | None = None
    trade_value_status: str = "missing"
    trade_value_method: str = "unavailable"
    trade_value_currency: str = "TWD"
    trade_value_authority: str
    trade_value_official: bool = False
    trade_value_asof: datetime
    trade_value_asof_basis: str


class TaiwanIntradayValueRead(CanonicalModel):
    points: tuple[TaiwanBarValueRead, ...]
    metadata: dict


def project_taiwan_intraday_values(series: TaiwanBarSeriesRead) -> TaiwanIntradayValueRead:
    if series.requested_interval in {"1d", "1w", "1mo"}:
        raise ValueError("DAILY_TURNOVER_NOT_INTRADAY_VALUE")
    states = {item.start_at: item for item in series.bar_states}
    values = []
    volume_sum = Decimal(0)
    covered_volume = Decimal(0)
    numerator = Decimal(0)
    actual_sum = Decimal(0)
    estimated_sum = Decimal(0)
    actual_count = estimated_count = volume_count = covered_count = 0
    inconsistent_count = 0
    dates = {bar.start_at.astimezone(TAIWAN_TZ).date() for bar in series.bars}
    latest_date = max(dates) if dates else None
    session_bars = [bar for bar in series.bars if bar.start_at.astimezone(TAIWAN_TZ).date() == latest_date]
    for bar in series.bars:
        state = states.get(bar.start_at)
        volume = bar.volume.value if bar.volume is not None and bar.volume.unit is QuantityUnit.SHARE else None
        actual = bar.turnover_value if bar.turnover_currency == "TWD" else None
        estimate = None
        if actual is None and volume is not None:
            # Canonical BarObservation has validated all OHLC and non-negative volume.
            estimate = (bar.high_price + bar.low_price + bar.close_price) / 3 * volume
        official = bool(actual is not None and state is not None and state.official)
        value = TaiwanBarValueRead(trade_value=float(actual) if actual is not None else None,
            approx_trade_value=float(estimate) if estimate is not None else None,
            trade_value_status="official" if official else "actual" if actual is not None else "estimated" if estimate is not None else "missing",
            trade_value_method="provider_reported" if actual is not None else "hlc3_times_volume_shares" if estimate is not None else "unavailable",
            trade_value_authority=bar.lineage.authority.value, trade_value_official=official,
            trade_value_asof=(bar.lineage.received_at or bar.lineage.fetched_at or bar.start_at)
                if bar.finalization.value == "provisional" else bar.end_at,
            trade_value_asof_basis="snapshot_received_time" if bar.finalization.value == "provisional" else "completed_interval_end")
        values.append(value)
        if bar.start_at.astimezone(TAIWAN_TZ).date() != latest_date:
            continue
        if volume is not None:
            volume_count += 1
            volume_sum += volume
        if actual is not None:
            actual_count += 1
            actual_sum += actual
        elif estimate is not None:
            estimated_count += 1
            estimated_sum += estimate
        selected = actual if actual is not None else estimate
        # Never divide amount by volume from a different bar/subset.
        inconsistent = selected is not None and volume == 0 and selected > 0
        inconsistent_count += int(inconsistent)
        if selected is not None and volume is not None and not inconsistent:
            numerator += selected
            covered_volume += volume
            covered_count += 1
    coverage = series.current_session_coverage
    full_prefix = bool(coverage is not None and coverage.status.value in {"complete_prefix", "complete_session"}
        and len(dates) == 1 and len(series.bars) == coverage.snapshot_bar_count
        and volume_count == len(session_bars)
        and all(bar.finalization.value != "provisional" for bar in session_bars))
    all_actual = bool(session_bars) and actual_count == len(session_bars) and covered_count == len(session_bars)
    all_official = all_actual and all(value.trade_value_official for value in values)
    amount_count = actual_count + estimated_count
    selected_total = actual_sum + estimated_sum if amount_count else None
    status = "mixed" if actual_count and estimated_count else "estimated" if estimated_count else "actual" if actual_count else "missing"
    first = session_bars[0] if session_bars else None
    last = session_bars[-1] if session_bars else None
    metadata = {
        "bar_volume_sum_shares": float(volume_sum) if volume_count else None,
        "bar_volume_sum_lots": float(volume_sum / 1000) if volume_count else None,
        "bar_volume_trade_date": latest_date.isoformat() if latest_date else None,
        "bar_volume_latest_time": (values[-1].trade_value_asof.isoformat() if last else None),
        "bar_volume_scope": "regular_session_board_lot_observed_window",
        "window_volume_sum_shares": float(volume_sum) if volume_count else None,
        "cumulative_trade_value": float(actual_sum) if full_prefix and all_actual else None,
        "available_cumulative_trade_value": float(actual_sum) if actual_count else None,
        "estimated_cumulative_trade_value": float(selected_total) if full_prefix and estimated_count and not inconsistent_count else None,
        "window_trade_value": float(selected_total) if selected_total is not None else None,
        "trade_value_unit": "TWD", "trade_value_status": status,
        "trade_value_coverage": {
            "scope": "session_prefix" if full_prefix else "observed_window",
            "trade_date": latest_date.isoformat() if latest_date else None,
            "from_time": first.start_at.isoformat() if first else None,
            "to_time": last.end_at.isoformat() if last else None,
            "observed_asof": values[-1].trade_value_asof.isoformat() if last else None,
            "bar_count": len(session_bars), "actual_count": actual_count,
            "estimated_count": estimated_count, "missing_count": len(session_bars) - amount_count,
            "estimated_coverage": estimated_count / len(session_bars) if session_bars else None,
            "covered_volume_shares": float(covered_volume),
            "amount_covered_bar_count": covered_count,
            "inconsistent_amount_volume_count": inconsistent_count,
            "providers": sorted({bar.lineage.provider for bar in session_bars}),
            "sources": sorted({bar.lineage.source for bar in session_bars}),
            "series_revision": series.identity.series_revision,
            "official": all_official,
            "limitations": ([] if full_prefix else ["PARTIAL_WINDOW_NOT_SESSION_TOTAL"])
                + (["ZERO_VOLUME_POSITIVE_AMOUNT_EXCLUDED_FROM_VWAP"] if inconsistent_count else [])
                + (["PROVISIONAL_BARS_INCLUDED"] if any(bar.finalization.value == "provisional" for bar in session_bars) else []),
        },
        "official_vwap": float(numerator / covered_volume) if all_official and covered_volume > 0 else None,
        "approx_vwap": float(numerator / covered_volume) if covered_volume > 0 else None,
        "vwap_method": "actual_first_hlc3_times_volume_shares" if covered_count else "unavailable",
        "vwap_confidence": "medium" if covered_count else "unavailable",
        "vwap_volume_scope": "session_prefix" if full_prefix else "observed_window",
        "volume_reconciliation": {"status": "unavailable", "reason": "quote_cumulative_unavailable"},
    }
    return TaiwanIntradayValueRead(points=tuple(values), metadata=metadata)


def reconcile_taiwan_intraday_volume(series: dict, quote: dict) -> dict:
    """Compare only a complete same-date prefix ending at the cumulative clock."""
    amount = quote.get("cumulative_trade_value_evidence") or {}
    coverage = series.get("trade_value_coverage") or {}
    total = amount.get("volume_shares", quote.get("cumulative_volume_shares"))
    event = amount.get("event_time") or quote.get("cumulative_volume_event_time") or quote.get("event_time")
    trade_date = amount.get("trade_date") or quote.get("cumulative_volume_trade_date") or quote.get("trade_date")
    scope = amount.get("scope") or quote.get("volume_scope")
    observed = series.get("bar_volume_sum_shares")
    result = {"status": "not_comparable", "exchange_cumulative_shares": total,
        "bar_volume_sum_shares": observed, "difference_shares": None,
        "trade_date": trade_date, "exchange_event_time": event,
        "bar_latest_time": series.get("bar_volume_latest_time"),
        "quote_provider": amount.get("provider") or quote.get("provider"),
        "bar_providers": coverage.get("providers", []), "decision_usable": False}
    reason = "quote_cumulative_unavailable"
    if total is not None and observed is not None:
        reason = "scope_different"
        if (scope == "regular_session_board_lot_cumulative"
                and series.get("bar_volume_scope") == "regular_session_board_lot_observed_window"):
            reason = "trade_date_mismatch"
            if str(trade_date) == series.get("bar_volume_trade_date"):
                reason = "partial_window"
                if coverage.get("scope") == "session_prefix":
                    reason = "event_time_unaligned"
                    try:
                        quote_at = datetime.fromisoformat(str(event).replace("Z", "+00:00"))
                        bar_at = datetime.fromisoformat(str(series.get("bar_volume_latest_time")).replace("Z", "+00:00"))
                        if quote_at.utcoffset() is not None and bar_at.utcoffset() is not None:
                            result["time_skew_seconds"] = (quote_at - bar_at).total_seconds()
                            if quote_at == bar_at:
                                difference = total - observed
                                result.update(status="matched" if difference == 0 else "difference",
                                    difference_shares=difference, difference_lots=difference / 1000)
                                reason = "aligned_prefix" if difference >= 0 else "source_correction_or_scope_difference"
                    except (ValueError, TypeError):
                        pass
    result["reason"] = reason
    return result
