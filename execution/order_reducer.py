"""Pure order reducer shared by the M1 synthetic wrapper and execution runtime.

No broker/session/storage knowledge. Event ordering is supplied by each ingress;
real source timestamps and deduplication remain evidence, not invented sequence.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .contracts import EventKind
from .validation import identifier, instant, integer, require


class OrderStatus(str, Enum):
    PREVIEWED = "PREVIEWED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


@dataclass(frozen=True)
class OrderFact:
    event_id: str
    order_id: str
    kind: EventKind
    occurred_at: datetime
    sequence: int | None = None
    cumulative_filled: int = 0
    fill_price: Decimal | None = None


@dataclass(frozen=True)
class OrderProgress:
    order_id: str
    quantity: int
    state: OrderStatus
    admitted_at: datetime | None
    cumulative_filled: int = 0
    last_report_sequence: int = 0
    last_report_at: datetime | None = None
    cancel_requested: bool = False
    events: tuple[OrderFact, ...] = ()


TERMINAL = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})
CONTROLS = frozenset({EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED})


def reduce_order(order: OrderProgress, event: OrderFact, now: datetime) -> tuple[OrderProgress, str]:
    """Return new immutable state and an audit reason, or reject without mutation."""
    instant(now)
    require(type(event) is OrderFact, "INVALID_EVENT")
    identifier(event.event_id)
    require(event.order_id == order.order_id, "EVENT_IDENTITY_MISMATCH")
    require(type(event.kind) is EventKind, "INVALID_EVENT")
    instant(event.occurred_at)
    require(event.occurred_at <= now and
            (order.admitted_at is None or order.admitted_at <= event.occurred_at), "INVALID_EVENT_TIME")
    integer(event.cumulative_filled)
    require(event.cumulative_filled <= order.quantity, "OVERFILL")
    for previous in order.events:
        if previous.event_id == event.event_id:
            require(previous == event, "EVENT_ID_CONFLICT")
            return order, "DUPLICATE_EVENT"

    require(order.admitted_at is not None or event.kind is EventKind.CANCEL_REQUESTED,
            "CONFIRMATION_REQUIRED")

    if event.kind in CONTROLS:
        require(event.sequence is None and event.cumulative_filled == 0, "INVALID_CONTROL")
        require(order.state not in TERMINAL, "TERMINAL_STATE")
        if event.kind is EventKind.RECONCILE:
            require(order.state is OrderStatus.UNKNOWN, "INVALID_TRANSITION")
            updated = replace(order, state=OrderStatus.RECONCILING)
        elif event.kind is EventKind.TIMEOUT:
            require(order.state not in {OrderStatus.PREVIEWED, OrderStatus.UNKNOWN}, "INVALID_TRANSITION")
            updated = replace(order, state=OrderStatus.UNKNOWN)
        elif order.state is OrderStatus.PREVIEWED:
            updated = replace(order, state=OrderStatus.CANCELLED, cancel_requested=True)
        elif order.state in {OrderStatus.UNKNOWN, OrderStatus.RECONCILING}:
            updated = replace(order, cancel_requested=True)  # Intent only; outcome still unknown.
        else:
            updated = replace(order, state=OrderStatus.CANCEL_PENDING, cancel_requested=True)
        return replace(updated, events=order.events + (event,)), "CONTROL_APPLIED"

    integer(event.sequence, positive=True)
    require(order.state is not OrderStatus.PREVIEWED, "CONFIRMATION_REQUIRED")
    require(order.state is not OrderStatus.UNKNOWN, "RECONCILIATION_REQUIRED")
    for previous in order.events:
        if previous.sequence == event.sequence and previous.kind not in CONTROLS:
            require((previous.kind, previous.cumulative_filled, previous.occurred_at, previous.fill_price) ==
                    (event.kind, event.cumulative_filled, event.occurred_at, event.fill_price), "REPORT_SEQUENCE_CONFLICT")
    if event.sequence <= order.last_report_sequence:
        return replace(order, events=order.events + (event,)), "OUT_OF_ORDER_IGNORED"
    require(order.last_report_at is None or event.occurred_at >= order.last_report_at,
            "REPORT_TIME_REGRESSION")
    require(event.cumulative_filled >= order.cumulative_filled, "FILL_REGRESSION")
    if event.kind is EventKind.ACCEPTED:
        require(event.cumulative_filled == 0, "INVALID_REPORT")
        state = OrderStatus.CANCEL_PENDING if order.cancel_requested else OrderStatus.ACCEPTED
    elif event.kind is EventKind.PARTIAL_FILL:
        require(0 < event.cumulative_filled < order.quantity, "INVALID_REPORT")
        state = OrderStatus.CANCEL_PENDING if order.cancel_requested else OrderStatus.PARTIALLY_FILLED
    elif event.kind is EventKind.FILLED:
        require(event.cumulative_filled == order.quantity, "INVALID_REPORT")
        state = OrderStatus.FILLED
    elif event.kind is EventKind.REJECTED:
        require(event.cumulative_filled == 0, "INVALID_REPORT")
        state = OrderStatus.REJECTED
    else:
        require(event.kind is EventKind.CANCELLED and order.cancel_requested, "INVALID_TRANSITION")
        state = OrderStatus.FILLED if event.cumulative_filled == order.quantity else OrderStatus.CANCELLED

    reason = "REPORT_APPLIED"
    if order.state is OrderStatus.CANCELLED:
        if event.kind is EventKind.PARTIAL_FILL:
            state = OrderStatus.CANCELLED  # Late fill updates quantity, not cancelled remainder.
            reason = "LATE_FILL_AFTER_CANCEL"
        elif event.kind is EventKind.FILLED:
            reason = "LATE_FILL_AFTER_CANCEL"
        elif event.kind is not EventKind.CANCELLED:
            state, reason = OrderStatus.RECONCILING, "CONFLICTING_TERMINAL_REPORT"
    elif order.state is OrderStatus.REJECTED and event.kind is not EventKind.REJECTED:
        state, reason = OrderStatus.RECONCILING, "CONFLICTING_TERMINAL_REPORT"
    elif order.state is OrderStatus.FILLED:
        state = OrderStatus.FILLED  # A late cancellation cannot erase a full fill.

    return replace(
        order, state=state, cumulative_filled=event.cumulative_filled,
        last_report_sequence=event.sequence, last_report_at=event.occurred_at,
        events=order.events + (event,),
    ), reason
