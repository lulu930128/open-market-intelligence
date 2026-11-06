"""HTTP application service; the F05 journal remains the only write owner.

Only create/revise/delete own transactions. Evaluation (GET or POST) is a pure read
and computation; its returned replay request carries the immutable bar snapshot.
No separate evaluation store, engine, provider acquisition or execution receipt.
"""
from __future__ import annotations

from datetime import datetime
from dataclasses import asdict
from decimal import Decimal
import json

from fastapi.encoders import jsonable_encoder

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.market.daily_ohlcv_platform import read_taiwan_official_daily
from app.market.taiwan_rules import taiwan_daily_price_release_at
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_trade_setup import TradeCosts, TradeSetup, evaluate_tw_trade_setup
from app.market.tw_trade_eligibility import EligibilityEvidence, EligibilityRequest, evaluate_tw_trade_eligibility
from app.market_data.contracts import BarFinalization, Market
from app.research import trade_journal
from app.research.candidate_service import CandidateService
from app.research.conditional_candidate import validate_raw
from app.research.paper_outcome import calculate_paper_outcomes
from app.research.trade_journal_http_schemas import (
    HorizonAssessment, PaperEvaluationRead, PaperEvaluationRequest, ProposalCreate,
    ProposalListRead, ProposalPromote, ProposalRead, ProposalRevise, RevisionListRead,
    ProposalDelete, ProposalDeleteRead,
    ProposalSummaryRead, ProposalSummaryListRead,
)
from app.research.trade_proposal import PaperBar, ProposalVersion, content_hash, utc_text


class JournalHttpError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _known_time(value: datetime, now: datetime) -> datetime:
    utc_text(value)
    if value > now:
        raise JournalHttpError(422, "FUTURE_KNOWLEDGE_TIME", "Knowledge time cannot be in the future.")
    return value


def _proposal_read(version: ProposalVersion, as_of: datetime) -> ProposalRead:
    if version.deleted_at is not None:
        raise JournalHttpError(410, "PROPOSAL_DELETED", "The research proposal was deleted.")
    horizon = None
    eligibility = None
    if version.market == "US":
        from app.us_market.watchlist_research import proposal_eligibility
        horizon = version.outcome_horizon_sessions or 10
        eligibility = proposal_eligibility(version)
    for item in version.evidence.items:
        if version.market == "TW" and item.source_ref == "research.stock_nomination.v1":
            snapshot = json.loads(item.snapshot_json)
            # Re-evaluate revisions against the frozen F04 evidence. GET never
            # acquires newer data or silently replaces the original assessment.
            try:
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("request"), dict):
                    raise ValueError("NOMINATION_SNAPSHOT_INVALID")
                candidate_horizon = snapshot["request"].get("horizon_sessions")
                if type(candidate_horizon) is not int or not 1 <= candidate_horizon <= len(version.planned_trade_dates):
                    raise ValueError("NOMINATION_HORIZON_INVALID")
                horizon = candidate_horizon
                request = EligibilityRequest.model_validate({**snapshot["eligibility"]["request"],
                    "quantity": version.strategy.shares, "entry_trade_date": version.planned_trade_dates[0]})
                eligibility = evaluate_tw_trade_eligibility(request,
                    EligibilityEvidence.model_validate(snapshot["eligibility"]["evidence"])).model_dump(mode="json")
            except ValueError as exc:
                eligibility = {"status": "DATA_BLOCKED", "reason_codes": [str(exc)]}
            except (KeyError, TypeError):
                eligibility = {"status": "DATA_BLOCKED", "reason_codes": ["NOMINATION_ELIGIBILITY_INVALID"]}
    try:
        math = evaluate_strategy(version.symbol, version.evidence.as_of_trade_date,
                                 version.strategy, version.costs, version.outcome_horizon_sessions or horizon or 10,
                                 market=version.market)
    except ValueError as exc:
        # Existing Journal inputs can exceed F03's two-target/tick scope. The
        # stored record remains readable; no historical strategy is rewritten.
        math = {"status": "DATA_BLOCKED", "reason_codes": [str(exc)]}
    return ProposalRead(status="scheduled" if version.effective_at > as_of else "proposed", proposal=version,
                        workflow_origin=trade_journal.workflow_origin(version),
                        currency="USD" if version.market == "US" else "TWD", promotion_supported=version.market == "TW",
                        setup_evaluation=math,
                        valid_from_date=version.planned_trade_dates[0].isoformat() if horizon else None,
                        valid_until_date=version.planned_trade_dates[horizon - 1].isoformat() if horizon else None,
                        eligibility=eligibility)


def evaluate_strategy(symbol, basis_date, strategy, costs, horizon=10, *, market="TW") -> dict:
    """Use F03 for both generated and revised Journal strategies.

    Paper's absolute slippage cannot be represented by one F03 exit bps for
    different targets. Nonzero/unknown slippage stays unknown in this projection.
    """
    if market == "US":
        from app.us_market.research_math import evaluate_us_strategy
        return evaluate_us_strategy(strategy, costs, horizon)
    slippage = 0 if costs.slippage_per_share == 0 else None
    borrow = (Decimal(str(costs.short_borrow_per_share_session)) * strategy.shares * horizon
              if costs.short_borrow_per_share_session is not None else None)
    result = evaluate_tw_trade_setup(TradeSetup(symbol=symbol, as_of_trade_date=basis_date,
        direction="long" if strategy.direction == 1 else "short", entry=strategy.entry_price,
        stop=strategy.stop_price, targets=tuple(t.price for t in strategy.targets), quantity=strategy.shares),
        TradeCosts(commission_rate=costs.commission_rate, minimum_commission=costs.minimum_commission,
                   sell_tax_rate=costs.sell_tax_rate, entry_slippage_bps=slippage,
                   exit_slippage_bps=slippage, short_borrow_cost=borrow))
    payload = jsonable_encoder(asdict(result), custom_encoder={Decimal: str})
    # F03 has no Paper other-cost field. Do not publish a net estimate omitting it.
    if costs.other_cost != 0:
        payload["net_stop_loss"] = None
        for scenario in [payload["stop_scenario"], *payload["target_scenarios"]]:
            scenario["net_pnl"] = scenario["net_rr"] = None
            scenario["costs"]["total"] = None
        payload["missing_costs"].append("paper_other_cost")
    return payload


def promote(db: Session, creation_id: str, request: ProposalPromote) -> dict:
    """Explicit Journal revision adoption into the existing Candidate owner only."""
    now = utc_now()
    with db.begin():
        versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=now)
    if not versions:
        raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", "No proposal is known at this time.")
    version = versions[-1]
    if version.deleted_at is not None:
        raise JournalHttpError(410, "PROPOSAL_DELETED", "The research proposal was deleted.")
    if version.revision_id != request.expected_revision_id:
        raise JournalHttpError(409, "REVISION_CONFLICT", "The expected revision is no longer the journal head.")
    result = {"creation_id": creation_id, "revision_id": version.revision_id,
              "status": "DATA_BLOCKED", "reason_codes": [], "warnings": [],
              "candidate": None, "preview": None, "execution_ready": False}
    reasons = result["reason_codes"]
    if version.market != "TW":
        reasons.append("US_RESEARCH_PROMOTION_UNSUPPORTED")
        return result
    strategy = version.strategy
    snapshot = next((json.loads(item.snapshot_json) for item in version.evidence.items
                     if item.source_ref == "research.stock_nomination.v1"), {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    nomination_request = snapshot.get("request")
    nomination_request = nomination_request if isinstance(nomination_request, dict) else {}
    origin = nomination_request.get("nomination_origin")
    horizon = version.outcome_horizon_sessions or nomination_request.get("horizon_sessions")
    if not isinstance(origin, str) or origin not in {"USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"}:
        reasons.append("RESEARCH_ORIGIN_MISSING")
    if version.effective_at > now:
        reasons.append("PROPOSAL_NOT_EFFECTIVE")
    if strategy.entry_rule not in {"at_or_above", "at_or_below"}:
        reasons.append("ENTRY_RULE_NOT_REPRESENTABLE")
    if strategy.mode != "aggressive":
        reasons.append("COMPLETED_DAILY_CONFIRMATION_NOT_REPRESENTABLE")
    read = _proposal_read(version, now)
    if read.setup_evaluation.get("status") == "DATA_BLOCKED":
        reasons.extend(read.setup_evaluation["reason_codes"])
    research_eligible = (read.eligibility or {}).get("research_eligible", "unknown")
    if strategy.paper_eligibility == "ineligible" or research_eligible is False:
        reasons.append("RESEARCH_INELIGIBLE")
    elif strategy.paper_eligibility != "eligible" and research_eligible is not True:
        reasons.append("RESEARCH_ELIGIBILITY_UNKNOWN")
    if reasons:
        return result

    # Never recompute a historical calendar or treat sessions as calendar days.
    dates = version.planned_trade_dates
    calendar_known = (version.calendar_verified and type(horizon) is int and 7 <= horizon <= len(dates))
    valid_from = dates[0].isoformat() if calendar_known else None
    valid_until = dates[horizon - 1].isoformat() if calendar_known else None
    if valid_until and valid_until < now.astimezone(TAIWAN_TZ).date().isoformat():
        reasons.append("PROPOSAL_EXPIRED")
        return result
    warnings = result["warnings"]
    if not calendar_known:
        warnings.append("FROZEN_CALENDAR_UNAVAILABLE_DRAFT")
    if len(strategy.targets) > 1:
        warnings.append("TP2_PROVENANCE_ONLY_NOT_ENABLED")
    # The existing Candidate has one full-quantity TP, not staged Paper targets.
    link = {"contract": "research.proposal_candidate_link.v1", "proposal_id": creation_id,
            "revision_id": version.revision_id, "revision": version.revision,
            "proposal_digest": content_hash(version.model_dump(mode="json")), "origin": origin,
            "horizon_sessions": horizon, "take_profit_mapping": "TP1_FULL_QUANTITY_ONLY",
            "proposal": version.model_dump(mode="json")}
    raw = {"symbol": version.symbol, "space_id": "AGENT_SPACE", "source": "AGENT_PROPOSAL",
           "direction": "long" if strategy.direction == 1 else "short",
           "action": "Buy" if strategy.direction == 1 else "Sell",
           "condition": "CASH" if strategy.direction == 1 else "SHORT_SELLING",
           "lot": "Common" if strategy.shares % 1000 == 0 else "Odd", "quantity": strategy.shares,
           "reference_entry": strategy.entry_price, "stop_loss": strategy.stop_price,
           "take_profit": strategy.targets[0].price, "price_basis": "explicit",
           "proposed_limit": strategy.entry_price, "valid_from_date": valid_from,
           "valid_until_date": valid_until, "hold_overnight": True,
           "conditions": {"kind": "compare", "metric": {"kind": "price", "field": "last_trade", "timeframe": "snapshot"},
                          "operator": ">=" if strategy.entry_rule == "at_or_above" else "<=", "value": strategy.entry_price},
           "reference_notes": {"research_proposal": link}}
    result["preview"] = raw
    _, validation = validate_raw(raw)
    if any(reason != "INCOMPLETE_DATE" for reason in validation):
        reasons.extend(validation)
        return result
    try:
        candidate = CandidateService(db).create(raw, owner_id=request.owner_id, research_revision=version)
    except ValueError as exc:
        if str(exc) != "STALE_RESEARCH_REVISION":
            raise
        raise JournalHttpError(409, "REVISION_CONFLICT", str(exc)) from exc
    result.update(status="PROMOTED", candidate=candidate)
    return result


def create(db: Session, request: ProposalCreate) -> ProposalRead:
    now = utc_now()
    try:
        with db.begin():
            version = trade_journal.create_proposal(
                db, **request.model_dump(exclude={"effective_at", "evidence", "strategy", "costs"}),
                evidence=request.evidence, strategy=request.strategy, costs=request.costs,
                effective_at=request.effective_at or now, now=now,
            )
    except ValueError as exc:
        raise JournalHttpError(422, "INVALID_PROPOSAL", str(exc)) from exc
    return _proposal_read(version, now)


def require_ai_scope(version):
    if trade_journal.workflow_origin(version) not in {"AI_NOMINATION", "OMI_SCREEN"}:
        raise JournalHttpError(403, "RESEARCH_OUTSIDE_AI_SCOPE", "AI can manage AI nominations and post-close research only.")


def move(db, creation_id, request, *, ai_scope=False):
    now = utc_now()
    try:
        with db.begin():
            version = trade_journal.move_proposal(db, creation_id=creation_id,
                expected_revision_id=request.expected_revision_id, origin=request.origin, now=now, ai_scope=ai_scope)
    except PermissionError as exc:
        raise JournalHttpError(403, "RESEARCH_OUTSIDE_AI_SCOPE", str(exc)) from exc
    except trade_journal.ProposalDeletedError as exc:
        raise JournalHttpError(410, "PROPOSAL_DELETED", str(exc)) from exc
    except LookupError as exc:
        raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", str(exc)) from exc
    except (ValueError, IntegrityError) as exc:
        raise JournalHttpError(409, "REVISION_CONFLICT", "The proposal changed; reload before moving.") from exc
    return _proposal_read(version, now)


def revise(db: Session, creation_id: str, request: ProposalRevise, *, ai_scope=False) -> ProposalRead:
    now = utc_now()
    try:
        with db.begin():
            # Also catch a stale writer before the original optimistic append.
            versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=now)
            if not versions:
                raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", "No proposal is known at this time.")
            if ai_scope:
                require_ai_scope(versions[-1])
            if versions[-1].deleted_at is not None:
                raise JournalHttpError(410, "PROPOSAL_DELETED", "The research proposal was deleted.")
            if versions[-1].revision_id != request.expected_revision_id:
                raise JournalHttpError(409, "REVISION_CONFLICT", "The expected revision is no longer the journal head.")
            previous = versions[-1]
            if request.strategy.direction != previous.strategy.direction:
                # A reversed thesis is a successor research idea, with its own
                # initial risk baseline; historical performance keeps its lineage.
                version = trade_journal.create_proposal(db, market=previous.market, symbol=previous.symbol,
                    evidence=previous.evidence, strategy=request.strategy, costs=request.costs,
                    effective_at=request.effective_at or now, now=now,
                    workflow_origin=trade_journal.workflow_origin(previous),
                    horizon_sessions=previous.outcome_horizon_sessions,
                    change_reason=f"Replaces {previous.creation_id}: {request.change_reason}")
                trade_journal.delete_proposal(db, creation_id=creation_id,
                    expected_revision_id=request.expected_revision_id, now=now)
            else:
                version = trade_journal.revise_proposal(
                    db, creation_id=creation_id, expected_revision_id=request.expected_revision_id,
                    strategy=request.strategy, costs=request.costs,
                    effective_at=request.effective_at or now, change_reason=request.change_reason, now=now,
                )
    except IntegrityError as exc:
        raise JournalHttpError(409, "REVISION_CONFLICT", "Another revision was appended concurrently.") from exc
    except ValueError as exc:
        raise JournalHttpError(422, "INVALID_REVISION", str(exc)) from exc
    return _proposal_read(version, now)


def read_at(db: Session, creation_id: str, decision_at: datetime | None = None, *, ai_scope=False) -> ProposalRead:
    now = utc_now()
    at = _known_time(decision_at or now, now)
    try:
        if ai_scope and decision_at is None:
            versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=at)
            if not versions:
                raise LookupError("Unknown proposal.")
            version = versions[-1]
            if version.deleted_at is not None:
                raise trade_journal.ProposalDeletedError("The research proposal was deleted.")
        else:
            version = trade_journal.proposal_at(db, creation_id=creation_id, decision_at=at)
        if ai_scope:
            require_ai_scope(version)
        return _proposal_read(version, at)
    except trade_journal.ProposalDeletedError as exc:
        raise JournalHttpError(410, "PROPOSAL_DELETED", str(exc)) from exc
    except LookupError as exc:
        raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", str(exc)) from exc


def read_revisions(db: Session, creation_id: str, as_of: datetime | None = None) -> RevisionListRead:
    now = utc_now()
    at = _known_time(as_of or now, now)
    versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=at)
    if not versions:
        raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", "No proposal is known at this time.")
    return RevisionListRead(creation_id=creation_id, as_of=at,
                            revisions=tuple(_proposal_read(version, at) for version in versions))


def _proposal_summary(version: ProposalVersion, as_of: datetime) -> ProposalSummaryRead:
    # Project the frozen journal only. Never relabel this as a complete ProposalVersion
    # or replace its evidence/hash with a truncated snapshot.
    snapshot = next((json.loads(item.snapshot_json) for item in version.evidence.items
        if item.source_ref in {"research.stock_nomination.v1", "research.us_watchlist_nomination.v1"}), {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    price_map = snapshot.get("price_map")
    identity = price_map.get("payload") if isinstance(price_map, dict) else None
    identity = identity if isinstance(identity, dict) else {}
    name = identity.get("stock_name") if identity.get("stock_id") == version.symbol else None
    assessment = snapshot.get("assessment")
    assessment = assessment if isinstance(assessment, dict) else {}
    assessment_status = assessment.get("status")
    reasons = assessment.get("reason_codes")
    reasons = tuple(reasons) if isinstance(reasons, list) and all(isinstance(code, str) for code in reasons) else ()
    return ProposalSummaryRead(
        creation_id=version.creation_id, revision_id=version.revision_id, revision=version.revision,
        market=version.market, symbol=version.symbol,
        stock_name=name.strip() if isinstance(name, str) and name.strip() else None,
        direction="long" if version.strategy.direction == 1 else "short",
        status="scheduled" if version.effective_at > as_of else "proposed",
        workflow_origin=trade_journal.workflow_origin(version),
        as_of_trade_date=version.evidence.as_of_trade_date.isoformat(), cutoff=version.evidence.cutoff,
        recorded_at=version.recorded_at, effective_at=version.effective_at,
        assessment_status=assessment_status if isinstance(assessment_status, str) else None, reason_codes=reasons,
        evidence_hash=version.evidence_hash,
    )


def read_list(db: Session, limit: int = 20, offset: int = 0, *, market=None, origin=None, direction=None, ai_scope=False,
              view: str = "full") -> ProposalListRead | ProposalSummaryListRead:
    now = utc_now()
    versions = trade_journal.list_proposal_heads(db, as_of=now, limit=limit + 1, offset=offset,
                                               market=market, origin=origin, direction=direction, ai_scope=ai_scope)
    if view == "summary":
        return ProposalSummaryListRead(as_of=now, items=tuple(_proposal_summary(v, now) for v in versions[:limit]),
                                       limit=limit, offset=offset, has_more=len(versions) > limit)
    return ProposalListRead(as_of=now, items=tuple(_proposal_read(v, now) for v in versions[:limit]),
                            limit=limit, offset=offset, has_more=len(versions) > limit)


def delete(db: Session, creation_id: str, request: ProposalDelete, *, ai_scope=False) -> ProposalDeleteRead:
    now = utc_now()
    try:
        with db.begin():
            if ai_scope:
                versions = trade_journal.list_versions(db, creation_id=creation_id, as_of=now)
                if not versions:
                    raise LookupError("Unknown proposal.")
                require_ai_scope(versions[-1])
            version = trade_journal.delete_proposal(db, creation_id=creation_id,
                expected_revision_id=request.expected_revision_id, now=now)
    except LookupError as exc:
        raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", str(exc)) from exc
    except (ValueError, IntegrityError) as exc:
        raise JournalHttpError(409, "REVISION_CONFLICT", "The proposal changed; reload before deleting.") from exc
    return ProposalDeleteRead(creation_id=version.creation_id, revision_id=version.revision_id,
                              deleted_at=version.deleted_at)


def _canonical_bars(db: Session, version: ProposalVersion, as_of: datetime) -> tuple[tuple[PaperBar, ...], tuple[str, ...]]:
    """Project already-resolved official bars; never select a provider or refresh.

    Canonical event time is not a receipt. Availability uses the existing daily
    release owner; actual receipt uses only lineage received/fetched timestamps.
    Unknown corporate-action coverage remains unknown (G1 owns that evidence).
    """
    if version.market == "US":
        from app.us_market.watchlist_research import read_outcome_bars
        return read_outcome_bars(db, version, as_of)
    dates = version.planned_trade_dates
    if as_of < taiwan_daily_price_release_at(dates[0]):
        return (), ("canonical_window_not_yet_released",)
    try:
        result = read_taiwan_official_daily(
            db, stock_id=version.symbol, from_date=dates[0], to_date=dates[-1],
            limit=len(dates), requested_at=as_of,
        )
    except ValueError:
        return (), ("canonical_daily_unavailable",)
    limitations = list(result.limitations)
    bars = []
    for bar in result.resolved.bars:
        day = bar.end_at.astimezone(TAIWAN_TZ).date()
        if day not in dates:
            continue
        lineage = bar.lineage
        receipts = [stamp for stamp in (lineage.received_at, lineage.fetched_at) if stamp is not None]
        revision = lineage.content_hash or lineage.raw_receipt_id
        if (bar.instrument.market is not Market.TW or bar.instrument.symbol != version.symbol
                or bar.interval != "1d" or not receipts or not revision or bar.price_basis is None):
            limitations.append("canonical_bar_identity_or_receipt_missing:" + day.isoformat())
            continue
        if bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}:
            limitations.append("canonical_bar_not_final:" + day.isoformat())
            continue
        available = max(taiwan_daily_price_release_at(day), bar.end_at, lineage.event_at or bar.end_at)
        received = max(receipts)
        if max(available, received) > as_of:
            limitations.append("canonical_bar_after_cutoff:" + day.isoformat())
            continue
        try:
            bars.append(PaperBar(
                symbol=version.symbol, trade_date=day, open_price=float(bar.open_price),
                high_price=float(bar.high_price), low_price=float(bar.low_price), close_price=float(bar.close_price),
                source_ref=f"{lineage.provider}:{lineage.source}", data_revision=revision,
                source_available_at=available, received_at=received, price_basis=bar.price_basis,
                final=True, corporate_action="unknown",
            ))
        except ValidationError:
            limitations.append("canonical_bar_invalid:" + day.isoformat())
        limitations.extend(bar.limitations)
    return tuple(bars), tuple(dict.fromkeys(limitations))


def evaluate(db: Session, creation_id: str, request: PaperEvaluationRequest) -> PaperEvaluationRead:
    now = utc_now()
    _known_time(request.decision_at, now)
    _known_time(request.outcome_as_of, now)
    if request.outcome_as_of < request.decision_at:
        raise JournalHttpError(422, "INVALID_OUTCOME_CUTOFF", "Outcome cutoff precedes decision_at.")
    proposal_read = read_at(db, creation_id, request.decision_at)
    version = proposal_read.proposal
    if request.expected_revision_id is not None and version.revision_id != request.expected_revision_id:
        raise JournalHttpError(409, "REVISION_CONFLICT", "The pinned revision does not match decision_at.")
    if request.bars is None:
        bars, owner_limitations = _canonical_bars(db, version, request.outcome_as_of)
        source = "canonical_cache"
    else:
        bars, owner_limitations = request.bars, ()
        source = "supplied_snapshot"
    try:
        result = calculate_paper_outcomes(version=version, decision_at=request.decision_at,
                                         outcome_as_of=request.outcome_as_of, bars=bars,
                                         horizon_sessions=request.horizon_sessions)
    except ValueError as exc:
        raise JournalHttpError(422, "INVALID_OUTCOME_EVIDENCE", str(exc)) from exc
    setup_evaluation = proposal_read.setup_evaluation
    if request.horizon_sessions is not None:
        try:
            setup_evaluation = evaluate_strategy(version.symbol, version.evidence.as_of_trade_date,
                                                 version.strategy, version.costs, request.horizon_sessions,
                                                 market=version.market)
        except ValueError as exc:
            setup_evaluation = {"status": "DATA_BLOCKED", "reason_codes": [str(exc)]}
    assessments = []
    reasons = []
    for outcome in result["outcomes"]:
        missing = tuple(reason for reason in outcome["limitations"] if reason.startswith((
            "missing_daily_bars:", "corporate_action_", "trading_calendar_", "cost_unknown",
            "paper_qualification:unknown", "entry_gap_outside_", "frozen_calendar_insufficient:",
        )))
        state = outcome["paper"]
        status = ("ambiguous" if state["fill_assessment"] == "ambiguous" else
                  "insufficient_evidence" if missing else
                  "unfilled" if state["fill_assessment"] == "unfilled" else "evaluated")
        assessments.append(HorizonAssessment(horizon_sessions=outcome["horizon_sessions"], status=status,
                                             insufficient_evidence=missing))
        reasons.extend(missing)
    overall = ("ambiguous" if any(item.status == "ambiguous" for item in assessments) else
               "insufficient_evidence" if reasons else
               "unfilled" if all(item.status == "unfilled" for item in assessments) else "evaluated")
    # Keep exactly the selected snapshots for replay; later/current canonical
    # rows are never needed to reproduce this returned pure evaluation payload.
    receipts = result["outcomes"][-1]["bar_receipts"]
    replay = PaperEvaluationRequest(decision_at=request.decision_at, outcome_as_of=request.outcome_as_of,
                                    expected_revision_id=version.revision_id,
                                    horizon_sessions=request.horizon_sessions,
                                    bars=tuple(PaperBar.model_validate(bar) for bar in receipts))
    return PaperEvaluationRead(status=overall, proposal=version, bar_source=source,
                               insufficient_evidence=tuple(dict.fromkeys(reasons)), assessments=tuple(assessments),
                               evaluation=result, owner_limitations=owner_limitations, replay_request=replay,
                               setup_evaluation=setup_evaluation)
