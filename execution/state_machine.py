"""M1 synthetic contract wrapper; admission and serialized contracts are unchanged."""

from dataclasses import replace
from datetime import datetime

from .contracts import EventKind, OrderState, SimulationEvent, State
from .order_reducer import OrderFact, OrderProgress, OrderStatus, reduce_order
from .validation import instant, require


TERMINAL = frozenset({State.SIMULATED_FILLED, State.SIMULATED_CANCELLED, State.SIMULATED_REJECTED})
CONTROLS = frozenset({EventKind.TIMEOUT, EventKind.RECONCILE, EventKind.CANCEL_REQUESTED})
_TO_CORE = {state: OrderStatus(state.value.removeprefix("SIMULATED_")) for state in State}
_FROM_CORE = {value: key for key, value in _TO_CORE.items()}


def _fact(event: SimulationEvent) -> OrderFact:
    return OrderFact(event.event_id, event.preview_id, event.kind, event.occurred_at,
                     event.sequence, event.cumulative_filled, event.fill_price)


def transition(order: OrderState, event: SimulationEvent, now: datetime) -> tuple[OrderState, str]:
    """Keep the original synthetic boundary and delegate all order reduction."""
    instant(now)
    require(type(event) is SimulationEvent, "INVALID_EVENT")
    require(event.simulated is True, "INVALID_EVENT")
    # Preserve M1 duplicate conflict semantics, including its complete envelope.
    for previous in order.events:
        if previous.event_id == event.event_id:
            require(previous == event, "EVENT_ID_CONFLICT")
    core = OrderProgress(order.preview_id, order.quantity, _TO_CORE[order.state],
                         order.confirmed_at, order.cumulative_filled,
                         order.last_report_sequence, order.last_report_at,
                         order.cancel_requested, tuple(_fact(e) for e in order.events))
    updated, reason = reduce_order(core, _fact(event), now)
    if reason == "DUPLICATE_EVENT":
        return order, reason
    return replace(order, state=_FROM_CORE[updated.state],
                   cumulative_filled=updated.cumulative_filled,
                   last_report_sequence=updated.last_report_sequence,
                   last_report_at=updated.last_report_at,
                   cancel_requested=updated.cancel_requested,
                   events=order.events + (event,)), reason
