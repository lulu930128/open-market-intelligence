"""Common bounded write-side preparation for Taiwan technical inputs.

Consumers supply identities and an event-date cap. Only this job boundary plans
repairs, invokes existing write owners and verifies canonical/technical rereads.
"""
from datetime import date, datetime, time, timedelta, timezone
import logging
from time import monotonic

from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.service import list_stock_ohlc_chart_data
from app.market.technical_report import build_stock_technical_report
from app.market.tw_corporate_events import refresh_taiwan_instrument_event_history, refresh_taiwan_price_basis_events
from app.market.tw_instrument import resolve_taiwan_instrument

logger = logging.getLogger(__name__)


def read_taiwan_middle_gaps(db, *, stock_id, basis, cutoff):
    """Exact internal gaps from canonical day-state, never natural-day subtraction."""
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_daily_day_state import TaiwanDailyState
    from app.market_data.contracts import InstrumentTradability
    from app.market.trading_calendar import TAIWAN_TZ
    series = TaiwanBarService(db).read_bars(instrument_id=stock_id, interval="1d",
        to_time=datetime.combine(basis, time.max, TAIWAN_TZ), requested_at=cutoff,
        include_partial=False, limit=300)
    dates = [bar.start_at.astimezone(TAIWAN_TZ).date() for bar in series.bars]
    gaps, blocked = [], []
    if not dates:
        blocked.append({"trade_date": str(basis), "reasons": ["CANONICAL_COMPLETED_HISTORY_MISSING"]})
    if dates:
        for state in series.day_states:
            if not min(dates) < state.trade_date < min(max(dates), basis):
                continue  # No pre-listing/leading, current-day or future backfill.
            if state.state == TaiwanDailyState.MISSING_EVIDENCE:
                if (state.market_open is True and state.expected_session
                        and state.instrument_status == InstrumentTradability.TRADABLE
                        and "OFFICIAL_DAILY_EVIDENCE_REQUIRED" in state.blockers
                        and "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN" not in state.blockers):
                    gaps.append(state.trade_date)
                else:
                    blocked.append({"trade_date": str(state.trade_date), "reasons": list(state.blockers)})
            elif state.blockers:
                blocked.append({"trade_date": str(state.trade_date), "reasons": list(state.blockers)})
    return {"missing_dates": [str(day) for day in gaps], "blocked": blocked}


def repair_taiwan_middle_gaps(db, *, stock_id, market, basis, cutoff, attempts, budget, persist, clock):
    """One short monthly-owner call per symbol/month/day, with canonical reread.

    The scheduler passes its existing checkpoint ledger and persists the claim
    before IO. This does not call the broader multi-month/event preparation.
    """
    before = read_taiwan_middle_gaps(db, stock_id=stock_id, basis=basis, cutoff=cutoff)
    result = {"stock_id": stock_id, "before": before, "after": before, "status": "not_attempted",
              "next_action": "REVIEW_CANONICAL_BLOCKERS"}
    if not before["missing_dates"]:
        result["status"] = "blocked" if before["blocked"] else "ready"
        return result
    start = date.fromisoformat(before["missing_dates"][0])
    key = f"{stock_id}:{start:%Y-%m}"
    if key in attempts:
        return {**result, "status": "deferred", "reason": "GAP_ALREADY_ATTEMPTED_TODAY", "next_action": "WAIT_NEXT_TRADING_DAY"}
    remaining = budget["deadline"] - monotonic()
    if budget["remaining_calls"] <= 0 or remaining <= 1:
        return {**result, "status": "deferred", "reason": "GAP_IO_OR_TIME_BUDGET", "next_action": "NEXT_BOUNDED_BATCH"}
    owner = {"TWSE": backfill_twse_stock_day, "TPEX": backfill_tpex_trading_stock}.get(market)
    if owner is None:
        return {**result, "status": "blocked", "reason": "UNSUPPORTED_OFFICIAL_HISTORY_OWNER"}
    # One month request; parse/write only this small range of known gap dates.
    days = [date.fromisoformat(value) for value in before["missing_dates"]]
    end = start
    while (end + timedelta(days=1) in days and end + timedelta(days=1) <= start + timedelta(days=6)
           and (end + timedelta(days=1)).strftime("%Y-%m") == start.strftime("%Y-%m")):
        end += timedelta(days=1)  # Never replace a known/unknown intervening day.
    attempts[key] = {"stock_id": stock_id, "start": str(start), "end": str(end),
                     "attempted_at": clock().isoformat(), "status": "attempting"}
    budget["remaining_calls"] -= 1
    persist()
    db.rollback()  # No read transaction is held across external IO.
    try:
        receipt = owner(db=db, stock_id=stock_id, start_date=start, end_date=end,
            skip_existing_months=False, sleep_seconds=0, timeout_seconds=min(8, remaining / 2))
        db.rollback()
        after = read_taiwan_middle_gaps(db, stock_id=stock_id, basis=basis, cutoff=clock())
        result.update(after=after, status="repaired" if not after["missing_dates"] else "unresolved",
                      owner_status=receipt.get("status"), owner_receipts=[
                          {key: row.get(key) for key in ("month", "status", "raw_result_id", "http_status_code", "error_message")}
                          for row in receipt.get("months", [])])
    except Exception as error:
        db.rollback()
        result.update(status="error", reason=type(error).__name__ + ":" + str(error)[:300],
                      next_action="REVIEW_PROVIDER_FAILURE_OR_NEXT_TRADING_DAY")
        logger.exception("Bounded Taiwan middle-gap repair failed symbol=%s", stock_id)
    attempts[key].update(result)
    persist()
    return result


def read_taiwan_technical_input(db, *, stock_id, to_date, bars=90, include_historical_states=False):
    chart = list_stock_ohlc_chart_data(db=db, stock_id=stock_id, timeframe="daily", bars=bars,
        ensure_history=False, include_intraday=False, to_date=to_date)
    report = build_stock_technical_report(db=db, stock_id=stock_id, timeframe="daily",
        include_intraday=False, include_volume_pace=False, to_date=to_date)
    quality = (report.get("data") or {}).get("input_quality") or {}
    value = {**{key: chart.get(key) for key in (
        "available_bar_count", "expected_minimum_bar_count", "coverage_status", "from_date", "to_date")},
        "technical_decision_usable": quality.get("decision_usable") is True
            and report.get("decision_usable") is not False
            and report.get("status") not in {"partial", "missing", "unavailable"},
        "technical_status": report.get("status") or quality.get("status"),
        "technical_reasons": quality.get("reason_codes") or report.get("missing") or [],
        "day_state_blockers": [item for item in quality.get("day_state_blockers", [])
                               if item["trade_date"] <= to_date.isoformat()],
        "technical_limitations": quality.get("canonical_limitations") or []}
    if include_historical_states:
        # Only the historical planner needs the large in-memory day-state graph.
        # Existing preparation/report receipts retain their original shape.
        value.update(required_bars=quality.get("required_bars"),
            decision_window=quality.get("decision_window") or {}, day_states=quality.get("day_states") or [],
            history_coverage=quality.get("history_coverage") or {},
            earliest_available_trade_date=chart.get("earliest_available_trade_date"))
    return value


def _ready(value):
    return value.get("coverage_status") == "complete" and value.get("technical_decision_usable") is True


def read_taiwan_historical_repair_input(db, *, stock_id, to_date):
    """Recover older blocker eligibility through the canonical Bar owner.

    Outward day_states may be a bounded recent projection while the blocker
    list names older dates. A blocker alone never proves calendar/tradability.
    Explicit from_time bypasses latest-candidate lookback discovery; only the
    named dates are consumed, with no provider or persistence side effects.
    """
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.trading_calendar import TAIWAN_TZ
    value = read_taiwan_technical_input(db, stock_id=stock_id, to_date=to_date, include_historical_states=True)
    states = {item["trade_date"]: item for item in value["day_states"]}
    missing = {item["trade_date"] for item in value["day_state_blockers"]
               if item["trade_date"] not in states
               and 0 <= (to_date - date.fromisoformat(item["trade_date"])).days <= 366}
    if missing:
        series = TaiwanBarService(db).read_bars(instrument_id=stock_id, interval="1d",
            from_time=datetime.combine(date.fromisoformat(min(missing)), time.min, TAIWAN_TZ),
            to_time=datetime.combine(date.fromisoformat(max(missing)), time.max, TAIWAN_TZ),
            requested_at=datetime.now(timezone.utc), include_partial=False, limit=400)
        states.update({item.trade_date.isoformat(): item.model_dump(mode="json")
                       for item in series.day_states if item.trade_date.isoformat() in missing})
    return {**value, "day_states": list(states.values())}


def plan_taiwan_historical_input_repair(value, *, to_date: date):
    """Exact canonical dates only; recent decision gaps precede older history.

    Chart count shortfall is deliberately not a date source. Positive official
    traded prices may resolve historical UNKNOWN, but the job first asks the
    instrument-event owner and always lets canonical readback make that decision.
    """
    reasons = set(value.get("technical_reasons") or ())
    history = (value.get("coverage_status") != "complete"
               or bool((value.get("history_coverage") or {}).get("missing_trading_day_count")))
    decision_gap = bool(reasons & {
        "TW_TECHNICAL_INSUFFICIENT_BARS", "TW_TECHNICAL_DECISION_WINDOW_GAP",
        "TW_TECHNICAL_BAR_STATE_NOT_ELIGIBLE",
    })
    dates = {}
    blocked = []
    # No pre-listing/leading repair from a chart count deficit. The first known
    # canonical bar or the technical decision window bounds historical intents.
    first = value.get("earliest_available_trade_date") or (value.get("decision_window") or {}).get("from_time")
    lower = date.fromisoformat(str(first)[:10]) if first else None
    sessions = sorted({item["trade_date"] for item in value.get("day_states", [])
                       if item.get("market_open") is True and item.get("expected_session") is True
                       and item["trade_date"] <= to_date.isoformat()})
    target = max(90, value.get("required_bars") or 60)
    if lower is not None and len(sessions) >= target:
        lower = max(lower, date.fromisoformat(sessions[-target]))
    for state in value.get("day_states") or ():
        day = date.fromisoformat(state["trade_date"])
        if lower is None or day < lower or day > to_date or (to_date - day).days > 366:
            continue
        blockers = set(state.get("blockers") or ())
        if not blockers:
            continue
        actions = []
        if state.get("market_open") is True and state.get("expected_session") is True:
            if state.get("state") == "MISSING_EVIDENCE" and (decision_gap or history):
                if "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN" in blockers:
                    actions.append("instrument_event_refresh")
                if "OFFICIAL_DAILY_EVIDENCE_REQUIRED" in blockers:
                    actions.append("daily_backfill")
            if (state.get("state") == "VERIFIED_NO_TRADE"
                    and "PRICE_BASIS_EVENT_COVERAGE_REQUIRED" in blockers):
                actions.extend(("instrument_event_refresh", "corporate_event_refresh"))
        if actions:
            dates[day.isoformat()] = list(dict.fromkeys(actions))
        else:
            blocked.append({"trade_date": day.isoformat(), "reasons": sorted(blockers)})
    return {"dates": dict(sorted(dates.items(), reverse=True)), "blocked": blocked,
            "decision_usable": value.get("technical_decision_usable") is True}


def execute_taiwan_historical_input_step(db, *, stock_id, basis, operation, days,
                                       timeout_seconds=8):
    """One stock, one month, one official call. Backfill owns Raw/Canonical commit."""
    parsed = sorted({date.fromisoformat(day) for day in days})
    if (not parsed or len({(day.year, day.month) for day in parsed}) != 1
            or parsed[-1] > basis or (basis - parsed[0]).days > 366
            or not 0 < timeout_seconds <= 8):
        raise ValueError("historical input step exceeds single-month bounds")
    instrument = resolve_taiwan_instrument(db, stock_id)
    db.rollback()  # End identity/read transaction before any external IO.
    if operation == "daily_backfill":
        owner = {"TWSE": backfill_twse_stock_day, "TPEX": backfill_tpex_trading_stock}.get(instrument.venue)
        if owner is None:
            return {"status": "unresolved", "reason": "UNSUPPORTED_OFFICIAL_HISTORY_OWNER"}
        return owner(db=db, stock_id=stock_id, start_date=parsed[0], end_date=parsed[-1],
                     skip_existing_months=False, sleep_seconds=0, timeout_seconds=timeout_seconds)
    if operation == "instrument_event_refresh":
        return refresh_taiwan_instrument_event_history(instrument=instrument,
            start_date=parsed[0], end_date=parsed[-1], timeout_seconds=timeout_seconds)
    if operation == "corporate_event_refresh":
        return refresh_taiwan_price_basis_events(instrument=instrument,
            start_date=parsed[0], end_date=parsed[-1], timeout_seconds=timeout_seconds)
    raise ValueError("unsupported historical input operation")


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
