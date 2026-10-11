"""Pure synthetic event reducer. No sending, scheduling, clocks or persistence."""

from dataclasses import replace
from datetime import datetime

from .contracts import EventKind, OrderState, SimulationEvent, State
from .validation import identifier, instant, integer, require


TERMINAL = frozenset({State.SIMULATED_FILLED, State.SIMULATED_CANCELLED, State.SIMULATED_REJECTED})
CONTROLS = frozenset({EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED})


def transition(order: OrderState, event: SimulationEvent, now: datetime) -> tuple[OrderState, str]:
    """Return new immutable state and an audit reason, or reject without mutation."""
    instant(now)
    require(type(event) is SimulationEvent, "INVALID_EVENT")
    identifier(event.event_id)
    require(event.preview_id == order.preview_id, "EVENT_IDENTITY_MISMATCH")
    require(type(event.kind) is EventKind and event.simulated is True, "INVALID_EVENT")
    instant(event.occurred_at)
    require(event.occurred_at <= now and
            (order.confirmed_at is None or order.confirmed_at <= event.occurred_at), "INVALID_EVENT_TIME")
    integer(event.cumulative_filled)
    require(event.cumulative_filled <= order.quantity, "OVERFILL")
    for previous in order.events:
        if previous.event_id == event.event_id:
            require(previous == event, "EVENT_ID_CONFLICT")
            return order, "DUPLICATE_EVENT"

    require(order.confirmed_at is not None or event.kind is EventKind.CANCEL_REQUESTED,
            "CONFIRMATION_REQUIRED")

    if event.kind in CONTROLS:
        require(event.sequence is None and event.cumulative_filled == 0, "INVALID_CONTROL")
        require(order.state not in TERMINAL, "TERMINAL_STATE")
        if event.kind is EventKind.RECONCILE:
            require(order.state is State.UNKNOWN, "INVALID_TRANSITION")
            updated = replace(order, state=State.RECONCILING)
        elif event.kind is EventKind.TIMEOUT:
            require(order.state not in {State.PREVIEWED, State.UNKNOWN}, "INVALID_TRANSITION")
            updated = replace(order, state=State.UNKNOWN)
        elif order.state is State.PREVIEWED:
            updated = replace(order, state=State.SIMULATED_CANCELLED, cancel_requested=True)
        elif order.state in {State.UNKNOWN, State.RECONCILING}:
            updated = replace(order, cancel_requested=True)  # Intent only; outcome still unknown.
        else:
            updated = replace(order, state=State.CANCEL_PENDING, cancel_requested=True)
        return replace(updated, events=order.events + (event,)), "CONTROL_APPLIED"

    integer(event.sequence, positive=True)
    require(order.state is not State.PREVIEWED, "CONFIRMATION_REQUIRED")
    require(order.state is not State.UNKNOWN, "RECONCILIATION_REQUIRED")
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
        state = State.CANCEL_PENDING if order.cancel_requested else State.SIMULATED_ACCEPTED
    elif event.kind is EventKind.PARTIAL_FILL:
        require(0 < event.cumulative_filled < order.quantity, "INVALID_REPORT")
        state = State.CANCEL_PENDING if order.cancel_requested else State.SIMULATED_PARTIALLY_FILLED
    elif event.kind is EventKind.FILLED:
        require(event.cumulative_filled == order.quantity, "INVALID_REPORT")
        state = State.SIMULATED_FILLED
    elif event.kind is EventKind.REJECTED:
        require(event.cumulative_filled == 0, "INVALID_REPORT")
        state = State.SIMULATED_REJECTED
    else:
        require(event.kind is EventKind.CANCELLED and order.cancel_requested, "INVALID_TRANSITION")
        state = State.SIMULATED_FILLED if event.cumulative_filled == order.quantity else State.SIMULATED_CANCELLED

    reason = "REPORT_APPLIED"
    if order.state is State.SIMULATED_CANCELLED:
        if event.kind is EventKind.PARTIAL_FILL:
            state = State.SIMULATED_CANCELLED  # Late fill updates quantity, not cancelled remainder.
            reason = "LATE_FILL_AFTER_CANCEL"
        elif event.kind is EventKind.FILLED:
            reason = "LATE_FILL_AFTER_CANCEL"
        elif event.kind is not EventKind.CANCELLED:
            state, reason = State.RECONCILING, "CONFLICTING_TERMINAL_REPORT"
    elif order.state is State.SIMULATED_REJECTED and event.kind is not EventKind.REJECTED:
        state, reason = State.RECONCILING, "CONFLICTING_TERMINAL_REPORT"
    elif order.state is State.SIMULATED_FILLED:
        state = State.SIMULATED_FILLED  # A late cancellation cannot erase a full fill.

    return replace(
        order, state=state, cumulative_filled=event.cumulative_filled,
        last_report_sequence=event.sequence, last_report_at=event.occurred_at,
        events=order.events + (event,),
    ), reason
