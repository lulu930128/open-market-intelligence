"""Selected daily research -> existing F03/F04 -> append-only F05 Journal."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.market.taiwan_price_rules import normalize_taiwan_stock_price
from app.market.trading_calendar import TAIWAN_TZ, next_taiwan_trading_day
from app.market.tw_swing_screening import (
    SwingScreenRequest, read_tw_swing_evidence, screen_tw_swing_candidates,
)
from app.market.tw_swing_prefilter import (
    SwingDiscoveryCheckpoint, SwingDiscoveryRequest, build_tw_swing_discovery_snapshot,
)
from app.market.taiwan_rules import taiwan_daily_price_release_at
from app.market.tw_trade_eligibility import (
    EligibilityPrice, EligibilityRequest, EvidenceStamp,
    evaluate_tw_trade_eligibility, read_tw_trade_eligibility_evidence,
)
from app.research import trade_journal
from app.research.trade_journal_http_service import JournalHttpError, _proposal_read, evaluate_strategy
from app.research.trade_proposal import (
    EvidenceItem, FrozenInput, PaperCosts, PaperStrategy, PaperTarget,
    ProposalEvidence, canonical_json, content_hash,
)


STRATEGY_VERSION = "tw.nomination.zone_rebound.v1"


class StockNomination(FrozenInput):
    market: Literal["TW", "US"] = Field(default="TW", exclude_if=lambda value: value == "TW")
    stock_ids: tuple[str, ...] = Field(min_length=1, max_length=5)
    direction: Literal["long", "short", "both"] = "both"
    horizon_sessions: Literal[10, 15] = 10
    as_of_trade_date: date
    requested_at: AwareDatetime
    nomination_origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] = "USER_NOMINATION"
    quantity: int = Field(default=1000, gt=0, strict=True)
    costs: PaperCosts = Field(default_factory=lambda: PaperCosts(version="research.nomination.costs.v1"))


def _levels(item, direction):
    """Choose support rebound / resistance rejection from published daily zones.

    No projected multiples or invented targets: TP1/2 must be two distinct
    favorable canonical zones. F03 owns tick/direction/RR validation.
    """
    zones = item.price_map.payload.get("zones") or []
    close = float(item.bars.bars[-1].close_price)
    down = sorted((z for z in zones if z.get("scanner_eligible") is True
                   and z.get("geometry_status") == "ready" and z["upper_bound"] < close),
                  key=lambda z: z["upper_bound"], reverse=True)
    up = sorted((z for z in zones if z.get("scanner_eligible") is True
                 and z.get("geometry_status") == "ready" and z["lower_bound"] > close),
                key=lambda z: z["lower_bound"])
    entries, targets = (down, up) if direction == "long" else (up, down)
    if not entries or len(targets) < 2:
        raise ValueError("CANONICAL_ENTRY_STOP_OR_TWO_TARGET_ZONES_MISSING")
    entry_zone = entries[0]
    entry_key, stop_key, target_key = (("upper_bound", "lower_bound", "lower_bound") if direction == "long"
                                       else ("lower_bound", "upper_bound", "upper_bound"))
    prices = [entry_zone[entry_key], entry_zone[stop_key], *(z[target_key] for z in targets[:2])]
    prices = [normalize_taiwan_stock_price(p, direction="nearest") for p in prices]
    if prices[2] == prices[3]:
        raise ValueError("DISTINCT_CANONICAL_TARGETS_MISSING")
    return prices, (entry_zone, *targets[:2])


def create_nominations(db: Session, request: StockNomination, *, automatic: bool = False,
                       discovery_context: dict | None = None,
                       screen_request: SwingScreenRequest | None = None) -> dict:
    if request.market == "US":
        from app.us_market.watchlist_research import create_nominations as create_us_nominations
        if "quantity" not in request.model_fields_set:
            request = request.model_copy(update={"quantity": 1})
        return create_us_nominations(db, request, automatic=automatic, discovery_context=discovery_context)
    now = utc_now()
    if request.requested_at > now:
        raise JournalHttpError(422, "FUTURE_KNOWLEDGE_TIME", "Knowledge time cannot be in the future.")
    try:
        selection = screen_request or SwingScreenRequest(stock_ids=request.stock_ids, direction=request.direction,
            as_of_trade_date=request.as_of_trade_date, requested_at=request.requested_at,
            horizon_sessions=request.horizon_sessions)
    except ValueError as exc:
        raise JournalHttpError(422, "INVALID_NOMINATION", str(exc)) from exc
    rows = []
    with db.begin():
        inputs = read_tw_swing_evidence(db, request=selection)
        screen = screen_tw_swing_candidates(selection, inputs)
        by_id = {item.stock_id: item for item in inputs}
        for assessment in screen.assessments:
            item = by_id.get(assessment.stock_id)
            directions = ("long", "short") if request.direction == "both" else (request.direction,)
            for direction in directions:
                reasons = [r.value for r in assessment.reason_codes]
                reasons.extend(r.value for r in assessment.excluded_directions.get(direction, ()))
                row = {"stock_id": assessment.stock_id, "direction": direction,
                       "status": "DATA_BLOCKED", "reason_codes": reasons, "proposal": None}
                rows.append(row)
                creation_id = None
                if automatic:
                    creation_id = str(uuid5(NAMESPACE_URL, canonical_json([
                        "omi.research.swing", assessment.stock_id, direction,
                        "support_rebound" if direction == "long" else "resistance_rejection",
                        request.as_of_trade_date.isoformat(), STRATEGY_VERSION,
                    ])))
                    versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=now)
                    if versions:
                        if versions[-1].deleted_at is not None:
                            row.update(status="DELETED", reason_codes=["PROPOSAL_DELETED"], deduplicated=True)
                            continue
                        read = _proposal_read(versions[-1], now).model_dump(mode="json")
                        row.update(status="WAITING_PRICE" if (read["eligibility"] or {}).get("research_eligible") is True
                                   else "WAITING_RESEARCH", proposal=read, deduplicated=True)
                        continue
                # Missing Price Map, daily/corporate/receipt/technical evidence
                # stays blocked. Optional flow/liquidity limitations remain visible.
                optional = {"NO_SETUP", "LIQUIDITY_UNKNOWN", "INSTITUTIONAL_UNKNOWN",
                            "INSTITUTIONAL_COUNTER_EVIDENCE"}
                if item is None or any(r not in optional for r in reasons):
                    continue
                if automatic and not any(c.stock_id == item.stock_id and c.direction == direction
                                         and c.stage == "research_qualified" for c in screen.candidates):
                    row["reason_codes"] = [*reasons, "NO_QUALIFIED_DIRECTION_SETUP"]
                    continue
                candidate = next((c for c in screen.candidates
                    if c.stock_id == item.stock_id and c.direction == direction), None)
                basis = assessment.basis
                published = item.price_map.published_at if item.price_map else None
                receipts = [t for t in (basis.source_received_at, basis.source_fetched_at) if t is not None]
                if basis.source_event_at is None or not receipts or published is None:
                    row["reason_codes"] = [*reasons, "SOURCE_TIME_UNKNOWN"]
                    continue
                try:
                    (entry, stop, tp1, tp2), zones = _levels(item, direction)
                    if direction == "short" and max(entry, float(item.bars.bars[-1].close_price)) >= 200:
                        raise ValueError("SHORT_PRICE_CAP")
                    strategy = PaperStrategy(version=STRATEGY_VERSION, direction=1 if direction == "long" else -1,
                        mode=candidate.mode if candidate else "aggressive",
                        entry_rule="at_or_below" if direction == "long" else "at_or_above",
                        entry_price=entry, stop_price=stop, targets=(PaperTarget(price=tp1, fraction=0.5),
                            PaperTarget(price=tp2, fraction=0.5)), shares=request.quantity,
                        thesis=("等待回測支撐帶；觸價後仍待回升確認" if direction == "long"
                                else "等待反彈壓力帶；觸價後仍待受阻確認"),
                        counter_evidence=(f"完成日線結構失效：{stop}", *reasons))
                    math = evaluate_strategy(item.stock_id, request.as_of_trade_date, strategy, request.costs,
                                             request.horizon_sessions)
                    eligibility_request = EligibilityRequest(stock_id=item.stock_id, market=item.market,
                        direction=direction, as_of_trade_date=request.as_of_trade_date, requested_at=request.requested_at,
                        entry_trade_date=next_taiwan_trading_day(now.astimezone(TAIWAN_TZ).date()),
                        horizon_sessions=request.horizon_sessions, quantity=request.quantity,
                        candidate_research_eligible=assessment.status == "qualified",
                        reference_price=EligibilityPrice(price=Decimal(str(item.bars.bars[-1].close_price)), qualified=True,
                            evidence=EvidenceStamp(source="completed_daily", as_of=request.as_of_trade_date,
                                available_at=assessment.basis.source_event_at, status="current")))
                    eligibility = evaluate_tw_trade_eligibility(eligibility_request,
                        read_tw_trade_eligibility_evidence(eligibility_request, db=db))
                except ValueError as exc:
                    row["reason_codes"] = [*reasons, str(exc)]
                    continue
                snapshot = {"request": request.model_dump(mode="json"), "assessment": assessment.model_dump(mode="json"),
                            "candidate": candidate.model_dump(mode="json") if candidate else None,
                            "selected_zones": zones, "price_map": item.price_map.model_dump(mode="json"),
                            "setup_evaluation": math, "eligibility": eligibility.model_dump(mode="json")}
                if discovery_context is not None:
                    snapshot["discovery"] = discovery_context
                evidence = ProposalEvidence(as_of_trade_date=request.as_of_trade_date, cutoff=request.requested_at,
                    price_basis=item.bars.bars[-1].price_basis or "unadjusted",
                    items=(EvidenceItem(source_ref="research.stock_nomination.v1",
                        source_available_at=max(basis.source_event_at, published),
                        received_at=max(*receipts, published),
                        data_revision=content_hash(snapshot), snapshot_json=canonical_json(snapshot)),))
                version = trade_journal.create_proposal(db, symbol=item.stock_id, evidence=evidence,
                    strategy=strategy, costs=request.costs, effective_at=now, now=now,
                    change_reason=request.nomination_origin, creation_id=creation_id)
                row.update(status="WAITING_PRICE" if eligibility.research_eligible is True else "WAITING_RESEARCH",
                    proposal=_proposal_read(version, now).model_dump(mode="json"),
                    entry_range={"lower": zones[0]["lower_bound"], "upper": zones[0]["upper_bound"]},
                    eligibility=eligibility.model_dump(mode="json"),
                    deduplicated=False,
                    rr_preference_met=all(Decimal(t["gross_rr"]) >= 2 for t in math["target_scenarios"]))
    return {"status": "saved" if any(r["proposal"] for r in rows) else "DATA_BLOCKED",
            "nomination_origin": request.nomination_origin, "scenarios": rows,
            "coverage": screen.coverage.model_dump(mode="json"), "execution_ready": False}


def discover_trade_proposals(db: Session, request: SwingDiscoveryRequest, *,
                            checkpoint: SwingDiscoveryCheckpoint | None = None) -> dict:
    """One bounded G4 continuation; original prefilter owns ranking and resume.

    The scheduler/caller retains its existing JSON checkpoint. Journal is the
    only proposal store; a repeated basis reuses the existing proposal head.
    """
    if request.requested_at < taiwan_daily_price_release_at(request.as_of_trade_date):
        raise JournalHttpError(422, "DAILY_NOT_RELEASED", "Completed daily evidence has not been released.")
    if request.requested_at > utc_now():
        raise JournalHttpError(422, "FUTURE_KNOWLEDGE_TIME", "Knowledge time cannot be in the future.")
    # Close the read transaction before entering G3's existing write boundary.
    with db.begin():
        discovery = build_tw_swing_discovery_snapshot(db, request=request, checkpoint=checkpoint, with_detail=True)
    context = {"snapshot_id": discovery.snapshot_id, "feature_revision": discovery.feature_revision,
               "coverage": discovery.coverage.model_dump(mode="json"),
               "sample_only": discovery.coverage.sample_only, "research_sample_only": True}
    rows = []
    for batch in discovery.detail_batches:
        for start in range(0, len(batch.request.stock_ids), 5):
            nominated = create_nominations(db, StockNomination(
                stock_ids=batch.request.stock_ids[start:start + 5], direction=request.direction,
                horizon_sessions=request.horizon_sessions, as_of_trade_date=request.as_of_trade_date,
                requested_at=request.requested_at, nomination_origin="OMI_SCREEN"),
                automatic=True, discovery_context=context,
                screen_request=request.detail_request(batch.request.stock_ids[start:start + 5]))
            rows.extend(nominated["scenarios"])
    blocked = sum(row["proposal"] is None for row in rows)
    return {"status": "in_progress" if discovery.status == "in_progress" else
            "partial" if not discovery.coverage.quality_complete or blocked else "ready",
            "basis_trade_date": request.as_of_trade_date.isoformat(), "nomination_origin": "OMI_SCREEN",
            **context, "checkpoint": discovery.checkpoint.model_dump(mode="json"),
            "request": request.model_dump(mode="json"), "candidates": rows,
            "created": sum(row["proposal"] is not None and not row["deduplicated"] for row in rows),
            "deduplicated": sum(row.get("deduplicated", False) for row in rows), "data_blocked": blocked,
            "limitations": list(discovery.limitations), "execution_ready": False}
