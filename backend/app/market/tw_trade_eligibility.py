"""F04 internal, cache-only Taiwan swing research eligibility (public wiring: G6).

None is never coerced to cash, inventory or a clear event window. Boolean axes
use the literal ``unknown`` when evidence is insufficient. An eligibility result
is a research assessment, never an order, permission, trigger or fill receipt.

G2 supplies candidate identity, completed-session reference price and research
qualification. F03/caller supplies the all-in capital requirement; this module
does not duplicate trade-cost or margin-rate calculations. Public margin lots
are context only, never broker borrow shares. Quote freshness is supplied by
the existing quote owner, not recalculated here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Literal, Mapping

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from app.market.trading_calendar import (
    TAIWAN_TZ, has_taiwan_calendar_year, is_taiwan_trading_day,
    next_taiwan_trading_day,
)
from app.market_data.contracts import CanonicalModel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


Truth = StrictBool | Literal["unknown"]
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Price = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
EventType = Literal[
    "investor_conference", "financial_report", "ex_dividend",
    "shareholder_meeting", "short_sale_suspension", "mandatory_cover",
    "suspension", "other",
]
ReasonCode = Literal[
    "CANDIDATE_NOT_QUALIFIED", "CANDIDATE_QUALIFICATION_UNKNOWN",
    "REFERENCE_PRICE_UNKNOWN", "SHORT_REFERENCE_PRICE_CAP",
    "CURRENT_QUOTE_UNKNOWN", "SHORT_CURRENT_PRICE_CAP",
    "REGULATION_UNKNOWN", "ACTIVE_DISPOSITION", "MARGIN_TRADING_SUSPENDED",
    "HOLDING_WINDOW_RESTRICTED", "BORROW_UNKNOWN", "BORROW_UNAVAILABLE",
    "FUNDING_UNKNOWN", "FUNDING_INSUFFICIENT", "BROKER_ELIGIBILITY_UNKNOWN",
    "BROKER_INELIGIBLE", "BROKER_IDENTITY_MISMATCH", "EVENT_COVERAGE_INCOMPLETE",
    "EVENT_EVIDENCE_UNVERIFIED", "CALENDAR_UNKNOWN",
]


class EvidenceStamp(CanonicalModel):
    source: str = Field(min_length=1, max_length=200)
    provider: str | None = None
    as_of: date | None = None
    available_at: AwareDatetime | None = None
    status: Literal["current", "partial", "stale", "missing"] = "missing"
    source_ref: str | None = None


class EligibilityPrice(CanonicalModel):
    price: Price
    evidence: EvidenceStamp
    qualified: StrictBool = False


class EligibilityRequest(CanonicalModel):
    stock_id: str = Field(min_length=1, max_length=20)
    market: Literal["TWSE", "TPEX"]
    direction: Literal["long", "short"]
    as_of_trade_date: date
    requested_at: AwareDatetime
    entry_trade_date: date
    horizon_sessions: Literal[10, 15]
    quantity: int = Field(gt=0, strict=True)
    candidate_research_eligible: Truth = "unknown"
    reference_price: EligibilityPrice | None = None
    current_quote: EligibilityPrice | None = None

    @model_validator(mode="after")
    def _dates(self) -> EligibilityRequest:
        if self.as_of_trade_date > self.requested_at.astimezone(TAIWAN_TZ).date():
            raise ValueError("as_of_trade_date cannot follow requested_at")
        if not self.as_of_trade_date <= self.entry_trade_date <= self.as_of_trade_date + timedelta(days=31):
            raise ValueError("entry_trade_date must be within 31 days of the evidence date")
        if not is_taiwan_trading_day(self.entry_trade_date):
            raise ValueError("entry_trade_date must be a Taiwan trading session")
        return self


class EligibilityEvent(CanonicalModel):
    event_type: EventType
    start_date: date
    end_date: date
    evidence: EvidenceStamp
    event_id: str | None = None
    event_time: str | None = None
    status: str = "scheduled"

    @model_validator(mode="after")
    def _interval(self) -> EligibilityEvent:
        if self.end_date < self.start_date:
            raise ValueError("event end_date must not precede start_date")
        return self


class EventCoverage(CanonicalModel):
    status: Literal["complete", "partial", "missing"] = "missing"
    date_from: date | None = None
    date_to: date | None = None
    covered_event_types: tuple[EventType, ...] = ()
    truncated: StrictBool = False
    sources: tuple[EvidenceStamp, ...] = ()


class RegulationEvidence(CanonicalModel):
    evidence: EvidenceStamp
    disposition_active: StrictBool | None = None
    margin_trading_suspended: StrictBool | None = None
    effective_start: date | None = None
    effective_end: date | None = None


class BorrowEvidence(CanonicalModel):
    """A supplied, dated broker inventory response; quantities are shares."""
    broker_id: str = Field(min_length=1)
    evidence: EvidenceStamp
    available_shares: int = Field(ge=0, strict=True)
    valid_until: AwareDatetime


class CapitalAmount(CanonicalModel):
    amount_twd: Money
    evidence: EvidenceStamp


class FundingEvidence(CanonicalModel):
    available: CapitalAmount | None = None
    # Caller/F03 all-in cash or collateral + costs. No assumed margin ratio.
    required: CapitalAmount | None = None


class BrokerEligibilityEvidence(CanonicalModel):
    broker_id: str = Field(min_length=1)
    eligible: Truth = "unknown"
    evidence: EvidenceStamp


class MarginContext(CanonicalModel):
    evidence: EvidenceStamp
    margin_balance_lots: int | None = None
    short_balance_lots: int | None = None
    short_limit_lots: int | None = None


class EligibilityEvidence(CanonicalModel):
    stock_id: str = Field(min_length=1, max_length=20)
    market: Literal["TWSE", "TPEX"]
    events: tuple[EligibilityEvent, ...] = Field(default=(), max_length=100)
    event_coverage: EventCoverage = Field(default_factory=EventCoverage)
    regulation: RegulationEvidence | None = None
    margin: MarginContext | None = None
    borrow: BorrowEvidence | None = None
    funding: FundingEvidence = Field(default_factory=FundingEvidence)
    broker: BrokerEligibilityEvidence | None = None


class EventRiskPolicy(CanonicalModel):
    """Ordinal ranking penalties, not probabilities or a ban on research."""
    version: str = Field(default="tw.swing.event_risk.v1", min_length=1)
    investor_conference: int = Field(default=2, ge=0, le=100)
    financial_report: int = Field(default=3, ge=0, le=100)
    ex_dividend: int = Field(default=3, ge=0, le=100)
    shareholder_meeting: int = Field(default=1, ge=0, le=100)
    short_sale_suspension: int = Field(default=5, ge=0, le=100)
    mandatory_cover: int = Field(default=5, ge=0, le=100)
    suspension: int = Field(default=5, ge=0, le=100)
    other: int = Field(default=1, ge=0, le=100)

    @model_validator(mode="after")
    def _versioned_weights(self) -> EventRiskPolicy:
        if self.version == "tw.swing.event_risk.v1" and any(
            getattr(self, name) != field.default
            for name, field in type(self).model_fields.items() if name != "version"
        ):
            raise ValueError("custom event weights require a distinct policy version")
        return self


class EventRisk(CanonicalModel):
    event: EligibilityEvent
    verified: bool
    ranking_penalty: int | None
    blocks_planned_holding: bool


class EligibilityReason(CanonicalModel):
    code: ReasonCode
    axis: Literal["research", "regulation", "borrow", "funding", "broker", "quote", "events"]
    evidence_as_of: date | None = None
    source: str | None = None


class TradeEligibilityResult(CanonicalModel):
    version: Literal["tw.trade_eligibility.v1"] = "tw.trade_eligibility.v1"
    request: EligibilityRequest
    evidence: EligibilityEvidence
    research_eligible: Truth
    regulation_eligible: Truth
    borrow_available: Truth
    funding_sufficient: Truth
    broker_execution_eligible: Truth
    current_price_eligible: Truth
    holding_sessions: tuple[date, ...]
    event_risk: tuple[EventRisk, ...]
    event_coverage_complete: bool
    event_policy: EventRiskPolicy
    observed_event_risk_score: int
    event_risk_score: int | None
    ineligibility_reason: tuple[EligibilityReason, ...]
    cache_policy: Literal["cache_only"] = "cache_only"


def _visible(stamp: EvidenceStamp, cutoff: datetime) -> bool:
    return stamp.available_at is not None and stamp.available_at <= cutoff


def _current(stamp: EvidenceStamp, request: EligibilityRequest) -> bool:
    return (stamp.status == "current" and _visible(stamp, request.requested_at)
            and stamp.as_of == request.requested_at.astimezone(TAIWAN_TZ).date())


def _all_true(*values: Truth) -> Truth:
    if any(value is False for value in values):
        return False
    return True if all(value is True for value in values) else "unknown"


def holding_sessions(request: EligibilityRequest) -> tuple[date, ...]:
    """Entry is session 1; expiry is session 10/15, using the existing calendar."""
    sessions = [request.entry_trade_date]
    for _ in range(request.horizon_sessions - 1):
        sessions.append(next_taiwan_trading_day(sessions[-1]))
    if not all(has_taiwan_calendar_year(day.year) for day in sessions):
        return ()
    return tuple(sessions)


def evaluate_tw_trade_eligibility(
    request: EligibilityRequest,
    evidence: EligibilityEvidence,
    policy: EventRiskPolicy | None = None,
) -> TradeEligibilityResult:
    """Pure assessment: no DB, provider, broker SDK, order or wall-clock calls."""
    if (request.stock_id, request.market) != (evidence.stock_id, evidence.market):
        raise ValueError("candidate and eligibility evidence identities must match")
    policy = policy or EventRiskPolicy()
    reasons: list[EligibilityReason] = []

    def reason(code: ReasonCode, axis: Any, stamp: EvidenceStamp | None = None) -> None:
        reasons.append(EligibilityReason(code=code, axis=axis,
            evidence_as_of=stamp.as_of if stamp else None,
            source=stamp.source if stamp else None))

    research = request.candidate_research_eligible
    if research is not True:
        reason("CANDIDATE_NOT_QUALIFIED" if research is False else "CANDIDATE_QUALIFICATION_UNKNOWN", "research")
    if request.direction == "short":
        reference = request.reference_price
        reference_ok: Truth = "unknown"
        if (reference and reference.qualified and reference.evidence.status == "current"
                and reference.evidence.as_of == request.as_of_trade_date
                and _visible(reference.evidence, request.requested_at)):
            reference_ok = reference.price < Decimal("200")
        if reference_ok is not True:
            reason("SHORT_REFERENCE_PRICE_CAP" if reference_ok is False else "REFERENCE_PRICE_UNKNOWN",
                   "research", reference.evidence if reference else None)
        research = _all_true(research, reference_ok)

    quote = request.current_quote
    current_price: Truth = "unknown"
    if quote and quote.qualified and _current(quote.evidence, request):
        current_price = request.direction == "long" or quote.price < Decimal("200")
    if current_price is not True:
        reason("SHORT_CURRENT_PRICE_CAP" if current_price is False else "CURRENT_QUOTE_UNKNOWN",
               "quote", quote.evidence if quote else None)

    sessions = holding_sessions(request)
    coverage = evidence.event_coverage
    required_types = set(EventRiskPolicy.model_fields) - {"version", "other"}
    complete = bool(sessions and coverage.status == "complete" and not coverage.truncated
        and coverage.date_from is not None and coverage.date_from <= sessions[0]
        and coverage.date_to is not None and coverage.date_to >= sessions[-1]
        and required_types <= set(coverage.covered_event_types)
        and coverage.sources and all(s.status == "current" and _visible(s, request.requested_at)
                                     for s in coverage.sources))
    if not sessions:
        reason("CALENDAR_UNKNOWN", "events")
    risks: list[EventRisk] = []
    seen: set[tuple[str, date, date]] = set()
    seen_ids: set[str] = set()
    for event in sorted(evidence.events, key=lambda e: (e.start_date,
            not (e.evidence.status == "current" and _visible(e.evidence, request.requested_at)),
            -getattr(policy, e.event_type), e.event_type, e.end_date, e.evidence.source)):
        if not sessions or event.start_date > sessions[-1] or event.end_date < sessions[0]:
            continue
        if event.status == "cancelled":
            continue
        # A later cache cannot establish what was known at a historical cutoff.
        if event.evidence.available_at and event.evidence.available_at > request.requested_at:
            reason("EVENT_EVIDENCE_UNVERIFIED", "events", event.evidence)
            complete = False
            continue
        verified = event.evidence.status == "current" and _visible(event.evidence, request.requested_at)
        key = (event.event_type, event.start_date, event.end_date)
        if key in seen or event.event_id is not None and event.event_id in seen_ids:
            continue
        seen.add(key)
        if event.event_id is not None:
            seen_ids.add(event.event_id)
        if not verified:
            reason("EVENT_EVIDENCE_UNVERIFIED", "events", event.evidence)
            complete = False
        blocks = verified and (event.event_type == "suspension" or
            request.direction == "short" and event.event_type in {"short_sale_suspension", "mandatory_cover"})
        risks.append(EventRisk(event=event, verified=verified,
            ranking_penalty=getattr(policy, event.event_type) if verified else None,
            blocks_planned_holding=blocks))
    if not complete:
        reason("EVENT_COVERAGE_INCOMPLETE", "events")

    regulation: Truth = "unknown"
    reg = evidence.regulation
    if reg and _current(reg.evidence, request):
        # Active disposition is conservatively outside this swing strategy's
        # execution scope; it is not a claim of a universal legal trading ban.
        if reg.disposition_active is True:
            regulation = False
            reason("ACTIVE_DISPOSITION", "regulation", reg.evidence)
        elif (request.direction == "short" and reg.margin_trading_suspended is True
                and (reg.effective_start is None or sessions and reg.effective_start <= sessions[-1])
                and (reg.effective_end is None or reg.effective_end >= request.entry_trade_date)):
            regulation = False
            reason("MARGIN_TRADING_SUSPENDED", "regulation", reg.evidence)
        elif reg.disposition_active is False:
            regulation = True if request.direction == "long" else (
                True if reg.margin_trading_suspended is False else "unknown")
    if any(r.blocks_planned_holding for r in risks):
        regulation = False
        reason("HOLDING_WINDOW_RESTRICTED", "regulation")
    if regulation == "unknown":
        reason("REGULATION_UNKNOWN", "regulation", reg.evidence if reg else None)

    borrow: Truth = "unknown"
    b = evidence.borrow
    if b and _current(b.evidence, request) and b.valid_until >= request.requested_at:
        borrow = b.available_shares >= request.quantity
    if request.direction == "short":
        if borrow is not True:
            reason("BORROW_UNAVAILABLE" if borrow is False else "BORROW_UNKNOWN", "borrow",
                   b.evidence if b else None)

    funding: Truth = "unknown"
    available, required = evidence.funding.available, evidence.funding.required
    if (available and required and _current(available.evidence, request)
            and required.evidence.status == "current" and _visible(required.evidence, request.requested_at)
            and required.evidence.as_of == request.as_of_trade_date):
        funding = available.amount_twd >= required.amount_twd
    if funding is not True:
        reason("FUNDING_INSUFFICIENT" if funding is False else "FUNDING_UNKNOWN", "funding",
               available.evidence if available else None)

    broker: Truth = "unknown"
    if evidence.broker and _current(evidence.broker.evidence, request):
        broker = evidence.broker.eligible
    if (request.direction == "short" and evidence.borrow and evidence.broker
            and evidence.borrow.broker_id != evidence.broker.broker_id):
        broker = "unknown"
        reason("BROKER_IDENTITY_MISMATCH", "broker", evidence.broker.evidence)
    if broker is not True:
        reason("BROKER_INELIGIBLE" if broker is False else "BROKER_ELIGIBILITY_UNKNOWN", "broker",
               evidence.broker.evidence if evidence.broker else None)
    execution = _all_true(research, regulation, borrow if request.direction == "short" else True,
                          funding, broker, current_price, True if complete else "unknown")
    score = sum(r.ranking_penalty or 0 for r in risks)
    return TradeEligibilityResult(request=request, evidence=evidence,
        research_eligible=research, regulation_eligible=regulation, borrow_available=borrow,
        funding_sufficient=funding, broker_execution_eligible=execution,
        current_price_eligible=current_price, holding_sessions=sessions,
        event_risk=tuple(risks), event_coverage_complete=complete, event_policy=policy,
        observed_event_risk_score=score, event_risk_score=score if complete else None,
        ineligibility_reason=tuple(dict.fromkeys(reasons)))


def _stamp(source: str, data: Mapping[str, Any], *, as_of: date | None) -> EvidenceStamp:
    raw = data.get("fetched_at") or data.get("cache_fetched_at")
    try:
        fetched = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        fetched = None
    status = data.get("cache_status") or data.get("status")
    return EvidenceStamp(source=source, provider=data.get("provider"), as_of=as_of,
        available_at=fetched, status=("partial" if status == "degraded" else
            status if status in {"current", "stale", "partial"} else "missing"),
        source_ref=data.get("source_url"))


def read_tw_trade_eligibility_evidence(
    request: EligibilityRequest, *, db: Session | None = None,
) -> EligibilityEvidence:
    """One symbol, <=100 events, one regulation read and <=1 stored margin row.

    Reuses the owners behind taiwan_events; never imports the AI projection or
    calls refresh. Existing event listings do not cover stop-short/mandatory
    cover notices, so their absence always leaves full event coverage partial.
    Broker borrow, account funds and broker eligibility remain unknown. The
    caller owns the supplied read Session; no Session/transaction is created.
    """
    from app.market.tw_corporate_events import list_taiwan_corporate_events
    from app.market.tw_disposition import get_taiwan_disposition_status

    sessions = holding_sessions(request)
    events: list[EligibilityEvent] = []
    coverage = EventCoverage()
    if sessions:
        listing = list_taiwan_corporate_events(stock_id=request.stock_id, market=request.market,
            date_from=sessions[0], date_to=sessions[-1], limit=100, offset=0,
            now=request.requested_at)
        sources = listing.get("sources") or {}
        stamps = {key: _stamp(str(value.get("source") or key), value,
                              as_of=listing["as_of"]) for key, value in sources.items()}
        for row in listing.get("results") or []:
            if row.get("stock_id") != request.stock_id or row.get("market") != request.market:
                raise ValueError("event owner returned a different instrument")
            # Match existing owner source metadata, never parse MOPS content.
            stamp = next((stamps[key] for key, meta in sources.items()
                          if meta.get("provider") == row.get("provider")
                          and meta.get("source") == (row.get("source_name") or row.get("source"))), None)
            stamp = stamp or EvidenceStamp(source=str(row.get("source_name") or row.get("source")
                                                      or "taiwan_corporate_event_cache"))
            kind = row.get("event_type")
            if kind not in EventRiskPolicy.model_fields or kind == "version":
                kind = "other"
            events.append(EligibilityEvent(event_type=kind, start_date=row["start_date"],
                end_date=row["end_date"], evidence=stamp, event_id=row.get("event_id"),
                event_time=row.get("start_time"), status=str(row.get("status") or "scheduled")))
        coverage = EventCoverage(status="partial" if stamps else "missing",
            date_from=sessions[0], date_to=sessions[-1],
            covered_event_types=("investor_conference", "financial_report", "ex_dividend"),
            truncated=listing.get("total_count", 0) > len(events), sources=tuple(stamps.values()))
    raw_reg = get_taiwan_disposition_status(request.stock_id, market=request.market,
        now=request.requested_at, trade_date=request.requested_at.astimezone(TAIWAN_TZ).date())
    reg = RegulationEvidence(evidence=_stamp(str(raw_reg.get("source_name") or "taiwan_disposition_cache"),
        raw_reg, as_of=request.requested_at.astimezone(TAIWAN_TZ).date()),
        disposition_active=raw_reg.get("is_active"),
        margin_trading_suspended=raw_reg.get("margin_trading_suspended"),
        effective_start=raw_reg.get("start_date"), effective_end=raw_reg.get("end_date"))
    margin = None
    if db is not None:
        from app.market.service import list_stock_margin_trade_history

        rows = list_stock_margin_trade_history(db, request.stock_id,
            to_date=request.as_of_trade_date, limit=1, ascending=False)
        if rows:
            row = rows[0]
            stamp = _stamp("margin_trading_daily", {"fetched_at": row.updated_at,
                "status": "current" if row.trade_date == request.as_of_trade_date else "stale",
                "source_url": f"margin_trading_daily:{row.id}:raw:{row.raw_result_id}"}, as_of=row.trade_date)
            visible = _visible(stamp, request.requested_at)
            if not visible:
                stamp = stamp.model_copy(update={"status": "missing"})
            margin = MarginContext(evidence=stamp,
                margin_balance_lots=row.margin_today_balance if visible else None,
                short_balance_lots=row.short_today_balance if visible else None,
                short_limit_lots=row.short_next_limit if visible else None)
    return EligibilityEvidence(stock_id=request.stock_id, market=request.market,
        events=tuple(events), event_coverage=coverage, regulation=reg, margin=margin)
