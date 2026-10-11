"""SYNTHETIC typed envelopes inspired by docs; not a raw SDK deserializer.

Caller-owned correlation and cumulative shares are explicit fixture additions.
seqno is opaque, changes across operations and must never be sorted numerically.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from .contracts import Scope, aware, nonempty, positive_int, valid_scope


class State(Enum):
    REQUESTED = "requested"
    PENDING = "pending"
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EventFixture:
    event_id: str  # Local fabricated envelope ID, not a documented KGI field.
    request_id: str  # Explicit synthetic correlation; not inferred from seqno.
    scope: Scope
    generation: int
    task: str  # NewOrder / CancelOrder / Deal / OrderStatus (last is fixture tag).
    status: str
    arrival_at: datetime
    source_at: datetime | None = None
    source_ts: str | None = None  # Original ts/op_time/modified_time; never date-guessed.
    order_id: str | None = None
    seqno: str | None = None
    trade_id: str | None = None  # Deal.reportseq only if explicitly supplied.
    deal_shares: int | None = None  # Caller-converted shares, not raw SDK quantity.
    cumulative_shares: int | None = None  # NOT a documented Event field.
    quantity_evidence: str | None = None
    error_code: str | None = None
    message: str | None = None
    mode: str = "SYNTHETIC"


@dataclass(frozen=True)
class KgiEventNormalizerFixture:
    request_id: str
    scope: Scope
    generation: int
    ordered_shares: int
    complete_fill_history: bool = False
    state: State = State.REQUESTED
    cumulative_shares: int | None = None
    order_id: str | None = None
    seqnos: tuple[str, ...] = ()
    trades: tuple[tuple[str, int, str | None, datetime | None], ...] = ()
    events: tuple[EventFixture, ...] = ()
    reasons: tuple[str, ...] = ()
    cancelled_remainder: bool = False
    last_source_at: datetime | None = None
    last_arrival_at: datetime | None = None
    mode: str = "SYNTHETIC / no broker"


def requested(request_id: str, scope: Scope, generation: int, shares: int,
              *, complete_fill_history: bool = False) -> KgiEventNormalizerFixture:
    if (not nonempty(request_id) or not valid_scope(scope) or not positive_int(generation)
            or not positive_int(shares) or type(complete_fill_history) is not bool):
        raise ValueError("Invalid synthetic order identity/quantity")
    return KgiEventNormalizerFixture(
        request_id, scope, generation, shares, complete_fill_history,
        cumulative_shares=0 if complete_fill_history else None,
    )


def normalize(current: KgiEventNormalizerFixture, event: EventFixture) -> KgiEventNormalizerFixture:
    """Pure reducer. UNKNOWN is sticky until a future explicit reconciliation owner.

    Valid late fills remain evidence; neither late ACK nor replay erases fills.
    Every input is retained (including conflicts); no side effects or automatic retry.
    """
    if type(current) is not KgiEventNormalizerFixture or type(event) is not EventFixture:
        raise ValueError("Typed synthetic fixture required")

    def unknown(code: str) -> KgiEventNormalizerFixture:
        return replace(current, state=State.UNKNOWN, events=current.events + (event,),
                       reasons=current.reasons + (code,))

    if (event.mode != "SYNTHETIC" or current.mode != "SYNTHETIC / no broker"
            or not nonempty(event.event_id) or not nonempty(event.request_id)):
        return unknown("INVALID_SYNTHETIC_ENVELOPE")
    if (event.scope != current.scope or event.request_id != current.request_id
            or type(event.generation) is not int or event.generation != current.generation):
        return unknown("CORRELATION_OR_GENERATION_CONFLICT")
    if (not aware(event.arrival_at) or (event.source_at is not None and not aware(event.source_at))
            or (event.source_at is not None and event.source_at > event.arrival_at)):
        return unknown("INVALID_EVENT_TIME")
    if current.last_arrival_at is not None and event.arrival_at < current.last_arrival_at:
        return unknown("ARRIVAL_TIME_REGRESSION")
    for prior in current.events:
        if prior.event_id == event.event_id:
            if replace(prior, arrival_at=event.arrival_at) == event:
                return replace(current, events=current.events + (event,),
                               last_arrival_at=event.arrival_at,
                               reasons=current.reasons + ("DUPLICATE_EVENT",))
            return unknown("EVENT_ID_CONFLICT")
    for value in (event.order_id, event.seqno, event.trade_id):
        if value is not None and not nonempty(value):
            return unknown("EMPTY_ID")
    if current.order_id is not None and event.order_id is not None and event.order_id != current.order_id:
        return unknown("BROKER_ORDER_ID_CONFLICT")
    if event.task not in ("NewOrder", "CancelOrder", "Deal", "OrderStatus"):
        return unknown("UNSUPPORTED_TASK")
    if event.task != "NewOrder" or event.status == "Success":
        if event.order_id is None:
            return unknown("BROKER_ORDER_ID_REQUIRED")
    if event.task == "NewOrder" and event.status == "Pending" and event.seqno is None:
        return unknown("PENDING_SEQNO_REQUIRED")
    if event.status == "Success" and event.error_code not in (None, "0"):
        return unknown("SUCCESS_ERROR_CONFLICT")

    result = replace(current, events=current.events + (event,),
                     last_arrival_at=event.arrival_at,
                     seqnos=current.seqnos + ((event.seqno,) if event.seqno and event.seqno not in current.seqnos else ()))
    # Pending carrying an ID does not establish broker acceptance.
    if event.order_id and (event.task != "NewOrder" or event.status == "Success"):
        result = replace(result, order_id=event.order_id)
    late = event.source_at is not None and current.last_source_at is not None and event.source_at < current.last_source_at
    if event.source_at is not None and not late:
        result = replace(result, last_source_at=event.source_at)

    def fail(code: str) -> KgiEventNormalizerFixture:
        return replace(result, state=State.UNKNOWN, reasons=result.reasons + (code,))

    def finish(state: State, reason: str | None = None) -> KgiEventNormalizerFixture:
        return replace(result, state=State.UNKNOWN if current.state is State.UNKNOWN else state,
                       reasons=result.reasons + ((reason,) if reason else ()))

    if event.task == "Deal":
        if event.status != "Success" or not nonempty(event.trade_id):
            return fail("DEAL_STATUS_OR_TRADE_ID_UNVERIFIED")
        if not positive_int(event.deal_shares) or not nonempty(event.quantity_evidence):
            return fail("DEAL_QUANTITY_UNIT_UNVERIFIED")
        trade = (event.trade_id, event.deal_shares, event.source_ts, event.source_at)
        for old in current.trades:
            if old[0] == event.trade_id:
                if old != trade:
                    return fail("TRADE_ID_CONFLICT")
                prior = next(e for e in current.events if e.task == "Deal" and e.trade_id == event.trade_id)
                if event.cumulative_shares != prior.cumulative_shares or event.quantity_evidence != prior.quantity_evidence:
                    return fail("TRADE_EVIDENCE_CONFLICT")
                return finish(current.state, "DUPLICATE_TRADE")
        result = replace(result, trades=current.trades + (trade,))
        if not current.complete_fill_history or current.cumulative_shares is None:
            return fail("CUMULATIVE_FILL_UNKNOWN")
        total = current.cumulative_shares + event.deal_shares
        if total > current.ordered_shares:
            return fail("OVERFILL_CONFLICT")
        if event.cumulative_shares is not None and (type(event.cumulative_shares) is not int or event.cumulative_shares != total):
            return fail("CUMULATIVE_FILL_CONFLICT")
        result = replace(result, cumulative_shares=total,
                         cancelled_remainder=current.cancelled_remainder and total < current.ordered_shares)
        if current.state is State.REJECTED:
            return fail("FILL_AFTER_REJECTION")
        state = (State.FILLED if total == current.ordered_shares else
                 State.CANCELLED if current.cancelled_remainder else
                 State.CANCEL_PENDING if current.state is State.CANCEL_PENDING else State.PARTIAL)
        return finish(state, "LATE_FILL_RETAINED" if late or current.cancelled_remainder else None)

    if event.task == "OrderStatus":
        if event.status not in ("Submitted", "Filled", "PartFilled", "Cancelled", "PartFilled_Cancelled"):
            return fail("UNKNOWN_ORDER_STATUS")
        total = event.cumulative_shares
        # Status text does not invent quantities, and modified_quantity is not a fill.
        if type(total) is not int or not 0 <= total <= current.ordered_shares or not nonempty(event.quantity_evidence):
            return fail("ORDER_STATUS_CUMULATIVE_REQUIRED")
        if current.cumulative_shares is None or total != current.cumulative_shares:
            return fail("SNAPSHOT_FILL_LEDGER_RECONCILIATION_REQUIRED")
        if late:
            return finish(current.state, "OUT_OF_ORDER_STATUS_RETAINED")
        if event.status == "Filled":
            return finish(State.FILLED) if total == current.ordered_shares else fail("FILLED_QUANTITY_CONFLICT")
        if event.status == "PartFilled":
            if not 0 < total < current.ordered_shares or current.cancelled_remainder or current.state is State.REJECTED:
                return fail("PARTIAL_STATUS_CONFLICT")
            return finish(State.CANCEL_PENDING if current.state is State.CANCEL_PENDING else State.PARTIAL)
        if event.status in ("Cancelled", "PartFilled_Cancelled"):
            if event.status == "PartFilled_Cancelled" and not 0 < total < current.ordered_shares:
                return fail("PART_CANCEL_QUANTITY_CONFLICT")
            if current.state is State.REJECTED:
                return fail("TERMINAL_STATUS_CONFLICT")
            result = replace(result, cancelled_remainder=total < current.ordered_shares)
            return finish(State.FILLED if total == current.ordered_shares else State.CANCELLED)
        if current.state in (State.CANCELLED, State.REJECTED) or total != 0:
            return fail("SUBMITTED_STATUS_CONFLICT")
        return finish(State.CANCEL_PENDING if current.state is State.CANCEL_PENDING else State.ACCEPTED)

    if event.task == "CancelOrder":
        if event.status in ("Pending", "Success"):
            if current.state in (State.FILLED, State.CANCELLED):
                return finish(current.state, "LATE_CANCEL_ACK")
            if current.state is State.REJECTED:
                return fail("CANCEL_AFTER_REJECTION")
            return finish(State.CANCEL_PENDING, "CANCEL_ACK_NOT_FINAL" if event.status == "Success" else None)
        if event.status == "Failed":
            return fail("CANCEL_FAILED_ORDER_OUTCOME_UNKNOWN")
        return fail("UNKNOWN_CANCEL_STATUS")

    if event.status == "Pending":
        return finish(State.PENDING if current.state is State.REQUESTED else current.state,
                      "LATE_PENDING" if current.state not in (State.REQUESTED, State.PENDING) else None)
    if event.status == "Success":
        if current.state in (State.CANCELLED, State.REJECTED):
            return finish(current.state, "OUT_OF_ORDER_ACK") if late else fail("TERMINAL_ACK_CONFLICT")
        return finish(State.ACCEPTED if current.state in (State.REQUESTED, State.PENDING) else current.state)
    if event.status == "Failed":
        if current.state not in (State.REQUESTED, State.PENDING):
            return fail("REJECTION_AFTER_ACCEPTANCE")
        return finish(State.REJECTED)
    return fail("UNKNOWN_NEW_ORDER_STATUS")
