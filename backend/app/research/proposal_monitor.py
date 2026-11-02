"""Read-only research assessment of one Journal revision; never creates Pending."""
from __future__ import annotations

from decimal import Decimal
import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_swing_screening import SwingScreenRequest, build_tw_swing_screening_snapshot
from app.market.tw_trade_eligibility import (
    EligibilityPrice, EligibilityRequest, EvidenceStamp,
    evaluate_tw_trade_eligibility, read_tw_trade_eligibility_evidence,
)
from app.research.candidate_evidence import read_research_price_evidence
from app.research.conditional_candidate import Comparison, Metric, Truth, digest, evaluate
from app.research.trade_journal_http_service import evaluate_strategy, read_at


def read_proposal_monitor(db: Session, creation_id: str) -> dict:
    now = utc_now()
    read = read_at(db, creation_id, now)
    version, strategy = read.proposal, read.proposal.strategy
    horizon, qualified, reference = 15, {"eligible": True, "ineligible": False}.get(strategy.paper_eligibility, "unknown"), None
    for item in version.evidence.items:
        if item.source_ref == "research.stock_nomination.v1":
            snapshot = json.loads(item.snapshot_json)
            horizon = snapshot["request"]["horizon_sessions"]
            qualified = snapshot["eligibility"]["research_eligible"]
            reference = snapshot["eligibility"]["request"].get("reference_price")
    first, last = version.planned_trade_dates[0], version.planned_trade_dates[horizon - 1]
    today = now.astimezone(TAIWAN_TZ).date()
    result = {"creation_id": creation_id, "revision_id": version.revision_id, "revision": version.revision,
        "checked_at": now.isoformat(), "valid_from_date": first.isoformat(), "valid_until_date": last.isoformat(),
        "status": "DATA_UNKNOWN", "reason_codes": [], "price_condition": "UNKNOWN", "confirmation": "UNKNOWN",
        "confirmation_basis": "price_only_aggressive" if strategy.mode == "aggressive" else "completed_daily_f01",
        "quote": {}, "setup_evaluation": None, "eligibility": None,
        "execution_ready": False, "cache_policy": "cache_only_no_refresh_no_write",
        "limitations": ["Research assessment only; no Pending, Native Preview, order or fill.",
                        "A snapshot does not establish an ordered touch/retest or a persisted trigger history.",
                        "REVIEWABLE assesses this research scenario; incomplete events and unknown regulation/borrow/funding/broker eligibility remain explicit."]}

    def finish(status, *reasons):
        result.update(status=status, reason_codes=list(reasons))
        # Do not include polling wall time: unchanged revision/evidence/state
        # yields the same observation identity and never appends a Journal row.
        result["observation_id"] = digest(jsonable_encoder({
            "revision_id": version.revision_id, "status": status, "reasons": reasons,
            "quote": {k: result["quote"].get(k) for k in ("trade_date", "quote_time", "trade_state", "source", "price_semantics")},
            "price_evidence": {k: result["quote"]["evidence"].get(k) for k in ("value", "source_at", "revision", "quality")}
                if result["quote"].get("evidence") else None, "price_condition": result["price_condition"],
            "confirmation": result["confirmation"], "confirmation_evidence": result.get("confirmation_evidence"),
            "math": result["setup_evaluation"], "eligibility": {
                k: result["eligibility"].get(k) for k in ("research_eligible", "regulation_eligible",
                    "current_price_eligible", "event_coverage_complete", "ineligibility_reason", "event_risk")
            } if result["eligibility"] else None,
        }, custom_encoder={Decimal: str}))
        return jsonable_encoder(result, custom_encoder={Decimal: str})

    if today > last:
        return finish("EXPIRED", "VALID_UNTIL_PASSED")
    if today < first:
        return finish("WAITING_PRICE", "VALID_FROM_NOT_REACHED")
    market = read_research_price_evidence(db, version.symbol, now)
    metric = Metric(kind="price", field="last_trade", timeframe="snapshot")
    price = market.values.get(metric.key)
    result["quote"] = {**market.price_evidence, "evidence": price.model_dump(mode="json") if price else None}
    usable = evaluate(Comparison(metric=metric, operator=">", value=0), market.values, now)
    if usable is Truth.UNKNOWN:
        return finish("DATA_UNKNOWN", "CURRENT_ACTUAL_TRADE_UNKNOWN")
    # Invalidation is assessed before entry, including a gap beyond the stop.
    sign = strategy.direction
    if sign * (price.value - Decimal(str(strategy.stop_price))) <= 0:
        return finish("INVALIDATED", "STOP_BREACHED")
    if strategy.entry_rule == "next_open":
        return finish("DATA_UNKNOWN", "UNSUPPORTED_MONITOR_ENTRY_RULE:next_open")
    operator = ">=" if strategy.entry_rule == "at_or_above" else "<="
    condition = evaluate(Comparison(metric=metric, operator=operator, value=Decimal(str(strategy.entry_price))), market.values, now)
    result["price_condition"] = condition.value
    if condition is Truth.FALSE:
        return finish("WAITING_PRICE", "ENTRY_CONDITION_FALSE")
    try:
        # This is the current observed entry scenario, not the frozen entry R/R.
        result["setup_evaluation"] = evaluate_strategy(version.symbol, version.evidence.as_of_trade_date,
            strategy.model_copy(update={"entry_price": float(price.value)}), version.costs, horizon)
    except ValueError as exc:
        return finish("INVALIDATED", "CURRENT_SETUP_INVALID:" + str(exc))
    stamp = EvidenceStamp(source=price.source, as_of=today, available_at=price.available_at,
                          status="current", source_ref=price.revision)
    try:
        request = EligibilityRequest(stock_id=version.symbol, market=market.price_evidence["market"],
            direction="long" if sign == 1 else "short", as_of_trade_date=version.evidence.as_of_trade_date,
            requested_at=now, entry_trade_date=today, horizon_sessions=horizon, quantity=strategy.shares,
            candidate_research_eligible=qualified,
            reference_price=EligibilityPrice.model_validate(reference) if reference else None,
            current_quote=EligibilityPrice(price=price.value, evidence=stamp, qualified=True))
        eligibility = evaluate_tw_trade_eligibility(request, read_tw_trade_eligibility_evidence(request, db=db))
    except ValueError as exc:
        return finish("DATA_UNKNOWN", "ELIGIBILITY_EVIDENCE_UNAVAILABLE:" + str(exc))
    result["eligibility"] = eligibility.model_dump(mode="json")
    if eligibility.research_eligible is False or eligibility.regulation_eligible is False or eligibility.current_price_eligible is False:
        return finish("INVALIDATED", *(r.code for r in eligibility.ineligibility_reason
                                      if r.axis in {"research", "regulation", "quote"}))
    if eligibility.research_eligible is not True or eligibility.current_price_eligible is not True:
        return finish("DATA_UNKNOWN", *(r.code for r in eligibility.ineligibility_reason
                                       if r.axis in {"research", "regulation", "quote", "events"}))
    confirmation = Truth.TRUE
    if strategy.mode == "confirmed":
        daily = build_tw_swing_screening_snapshot(db, request=SwingScreenRequest(
            stock_ids=(version.symbol,), as_of_trade_date=expected_daily_price_date(now=now), requested_at=now,
            horizon_sessions=horizon, direction=request.direction, mode="confirmed"))
        confirmation = (Truth.UNKNOWN if not daily.coverage.complete else Truth.TRUE
            if any(c.direction == request.direction and c.mode == "confirmed" and c.stage == "research_qualified"
                   for c in daily.candidates) else Truth.FALSE)
        result["confirmation_evidence"] = {"basis_trade_date": daily.request.as_of_trade_date.isoformat(),
            "technical_revisions": sorted({a.basis.technical_revision for a in daily.assessments if a.basis.technical_revision}),
            "reason_codes": sorted({r.value for a in daily.assessments for r in a.reason_codes})}
    result["confirmation"] = confirmation.value
    if confirmation is Truth.UNKNOWN:
        return finish("DATA_UNKNOWN", "COMPLETED_DAILY_CONFIRMATION_UNKNOWN")
    if confirmation is Truth.FALSE:
        return finish("WAITING_CONFIRMATION", "COMPLETED_DAILY_CONFIRMATION_FALSE")
    return finish("REVIEWABLE", *(r.code for r in eligibility.ineligibility_reason
        if r.axis in {"regulation", "events", "borrow", "funding", "broker"}))
