"""Common bounded write-side preparation for Taiwan technical inputs.

Consumers supply identities and an event-date cap. Only this job boundary plans
repairs, invokes existing write owners and verifies canonical/technical rereads.
"""
from datetime import date
import logging

from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.service import list_stock_ohlc_chart_data
from app.market.technical_report import build_stock_technical_report
from app.market.tw_corporate_events import refresh_taiwan_instrument_event_history, refresh_taiwan_price_basis_events
from app.market.tw_instrument import resolve_taiwan_instrument

logger = logging.getLogger(__name__)


def read_taiwan_technical_input(db, *, stock_id, to_date, bars=90):
    chart = list_stock_ohlc_chart_data(db=db, stock_id=stock_id, timeframe="daily", bars=bars,
        ensure_history=False, include_intraday=False, to_date=to_date)
    report = build_stock_technical_report(db=db, stock_id=stock_id, timeframe="daily",
        include_intraday=False, include_volume_pace=False, to_date=to_date)
    quality = (report.get("data") or {}).get("input_quality") or {}
    return {**{key: chart.get(key) for key in (
        "available_bar_count", "expected_minimum_bar_count", "coverage_status", "from_date", "to_date")},
        "technical_decision_usable": quality.get("decision_usable") is True
            and report.get("decision_usable") is not False
            and report.get("status") not in {"partial", "missing", "unavailable"},
        "technical_status": report.get("status") or quality.get("status"),
        "technical_reasons": quality.get("reason_codes") or report.get("missing") or [],
        "day_state_blockers": [item for item in quality.get("day_state_blockers", [])
                               if item["trade_date"] <= to_date.isoformat()],
        "technical_limitations": quality.get("canonical_limitations") or []}


def _ready(value):
    return value.get("coverage_status") == "complete" and value.get("technical_decision_usable") is True


def plan_taiwan_technical_input_repairs(value):
    """Classify explicit canonical blockers; never infer market semantics."""
    blockers = {reason for item in value.get("day_state_blockers", []) for reason in item["reasons"]}
    actions = []
    if value.get("coverage_status") != "complete" or blockers & {"OFFICIAL_DAILY_EVIDENCE_REQUIRED", "PRIOR_CANONICAL_CLOSE_MISSING"}:
        actions.append("daily_backfill")
    if "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN" in blockers:
        actions.append("instrument_event_refresh")
    if "PRICE_BASIS_EVENT_COVERAGE_REQUIRED" in blockers:
        actions.append("corporate_event_refresh")
    if "ALTERNATE_OFFICIAL_PRICE_REQUIRED" in blockers:
        actions.append("alternate_official_price")
    return tuple(actions)


def resolve_alternate_taiwan_official_price(db, *, instrument, start_date, end_date):
    """Fail-closed acquisition seam until an alternate official price is qualified.

    Re-fetching the same null-price monthly row is not alternate price evidence.
    No price is synthesized and no parallel price store is introduced.
    """
    return {"status": "unresolved", "reason": "ALTERNATE_OFFICIAL_PRICE_ACQUISITION_UNAVAILABLE"}


def prepare_taiwan_technical_inputs(db, *, stock_ids, to_date: date, bars=90):
    selected = list(dict.fromkeys(stock_ids))
    if not 1 <= len(selected) <= 20 or not 1 <= bars <= 250:
        raise ValueError("technical readiness requires 1..20 instruments and 1..250 bars")
    results, attempted, repaired, unresolved = [], [], [], []
    for symbol in selected:
        item = {"stock_id": symbol, "status": "unresolved", "actions": []}
        results.append(item)
        try:
            before = read_taiwan_technical_input(db, stock_id=symbol, to_date=to_date, bars=bars)
            item["before"] = before
            if _ready(before):
                item.update(status="ready", after=before)
                continue
            start, end = before.get("from_date"), before.get("to_date")
            if not isinstance(start, date) or not isinstance(end, date) or not 0 <= (end - start).days <= 366 or end > to_date:
                raise ValueError("canonical readiness window exceeds bounds")
            instrument = resolve_taiwan_instrument(db, symbol)
            owner = {"TWSE": backfill_twse_stock_day, "TPEX": backfill_tpex_trading_stock}.get(instrument.venue)
            if owner is None:
                item["reason"] = "unsupported_or_missing_stock_market"
            else:
                actions = plan_taiwan_technical_input_repairs(before)
                if actions:
                    attempted.append(symbol)
                for action in actions:
                    db.rollback()  # Release read transaction before bounded external IO.
                    try:
                        if action == "daily_backfill":
                            result = owner(db=db, stock_id=symbol, start_date=start, end_date=end,
                                skip_existing_months=False)
                        elif action == "instrument_event_refresh":
                            result = refresh_taiwan_instrument_event_history(instrument=instrument, start_date=start, end_date=end)
                        elif action == "corporate_event_refresh":
                            result = refresh_taiwan_price_basis_events(instrument=instrument, start_date=start, end_date=end)
                        else:
                            result = resolve_alternate_taiwan_official_price(db, instrument=instrument, start_date=start, end_date=end)
                        item["actions"].append({"operation": action, **result})
                    except Exception as error:
                        db.rollback()
                        item["actions"].append({"operation": action, "status": "error", "error_type": type(error).__name__})
                        logger.exception("Technical readiness operation failed symbol=%s operation=%s", symbol, action)
                db.rollback()
                after = read_taiwan_technical_input(db, stock_id=symbol, to_date=to_date, bars=bars)
                item["after"] = after
                if _ready(after):
                    item["status"] = "repaired"
                    repaired.append(symbol)
                else:
                    item["reason"] = "technical_input_blockers_remaining"
        except Exception as error:
            db.rollback()
            item.update(reason="technical_readiness_exception", error_type=type(error).__name__)
            logger.exception("Technical readiness failed symbol=%s", symbol)
        if item["status"] == "unresolved":
            unresolved.append(symbol)
    return {"status": "partial" if unresolved else "ready", "selected": selected,
        "attempted": attempted, "repaired": repaired, "unresolved": unresolved, "results": results}
