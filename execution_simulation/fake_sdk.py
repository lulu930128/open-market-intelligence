"""Closed in-process fake SDK. No real SDK import, session, transport or live switch.

Draft is the canonical handoff; the old M3 ApprovedOrderFixture is not consumed.
All units and identities below describe this fake protocol, never KGI's units.
"""

from dataclasses import dataclass
from decimal import Decimal

from execution.contracts import Draft, EventKind, Funding, Lot, OrderKind, PositionAction, SimulationEvent
from execution.validation import digest_of, require


@dataclass(frozen=True)
class FakeUnits:
    lot: Lot
    shares_per_qty: int
    evidence: str = 'synthetic-fake-sdk-units-v1'


@dataclass(frozen=True)
class FakeOrderArguments:
    action: str
    symbol: str
    qty: int
    price: Decimal | str
    time_in_force: str
    order_cond: str
    odd_lot: str
    binding: str


def convert(draft: Draft, units: FakeUnits) -> FakeOrderArguments:
    require(type(draft) is Draft and draft.contract_version == 2, 'CANONICAL_V2_REQUIRED')
    require(type(units) is FakeUnits and units.lot is draft.lot
            and units.evidence == 'synthetic-fake-sdk-units-v1'
            and type(units.shares_per_qty) is int and units.shares_per_qty > 0,
            'BROKER_QUANTITY_UNIT_UNVERIFIED')
    require(draft.quantity % units.shares_per_qty == 0, 'NONINTEGRAL_BROKER_QUANTITY')
    blockers = {Funding.MARGIN: 'MARGIN_REPAYMENT_MAPPING_UNVERIFIED',
                Funding.SHORT_SELLING: 'CREDIT_COVER_MAPPING_UNVERIFIED',
                Funding.LEND_SELLING: 'BORROW_COVER_AND_RETURN_UNVERIFIED'}
    if draft.funding is not Funding.CASH:
        require(False, blockers[draft.funding] if draft.position_action is PositionAction.CLOSE
                else 'CREDIT_BROKER_MAPPING_UNVERIFIED')
    return FakeOrderArguments(draft.side.value, draft.instrument.symbol,
        draft.quantity // units.shares_per_qty,
        draft.limit_price if draft.order_kind is OrderKind.LIMIT else 'MKT',
        'ROD', 'CASH', 'Common' if draft.lot is Lot.BOARD else 'Odd', digest_of(draft))


class FakeSDK:
    """One bounded fake invocation. Rehydrated query uses the durable scenario.

    Binding is a fake correlation guarantee. Real KGI correlation remains unverified.
    This is not a pluggable production broker interface.
    """

    def __init__(self, args, scenario, command_id, filled=0):
        require(type(args) is FakeOrderArguments, 'FAKE_ARGUMENTS_REQUIRED')
        require(scenario in {'SDK_ACCEPT', 'SDK_PENDING', 'SDK_REJECT', 'SDK_TIMEOUT',
                             'SDK_AMBIGUOUS', 'SDK_CANCEL'}, 'INVALID_MOCK_FIXTURE')
        self.args, self.scenario, self.command_id, self.filled = args, scenario, command_id, filled
        self.order_id = 'FAKE-' + args.binding[:24]
        self._callback = None

    def set_event(self, callback):
        self._callback = callback

    def _event(self, task, status, *, order_id=None):
        return {'task': task, 'status': status, 'order_id': order_id,
                'binding': self.args.binding, 'symbol': self.args.symbol,
                'action': self.args.action, 'qty': self.args.qty,
                'price': self.args.price, 'order_cond': self.args.order_cond,
                'odd_lot': self.args.odd_lot, 'time_in_force': self.args.time_in_force,
                'errcode': None, 'msg': None, 'cumulative_shares': self.filled}

    def create_order(self, *, action, symbol, qty, price, time_in_force, order_cond, odd_lot):
        require((action, symbol, qty, price, time_in_force, order_cond, odd_lot) ==
                (self.args.action, self.args.symbol, self.args.qty, self.args.price,
                 self.args.time_in_force, self.args.order_cond, self.args.odd_lot), 'FAKE_ARGUMENT_MISMATCH')
        require(self._callback is not None, 'CALLBACK_REQUIRED')
        if self.scenario in {'SDK_TIMEOUT', 'SDK_AMBIGUOUS'}:
            raise TimeoutError('synthetic transport outcome unknown')
        event = self._event('NewOrder', 'Pending')
        if self.scenario == 'SDK_ACCEPT':
            event = self._event('NewOrder', 'Success', order_id=self.order_id)
        elif self.scenario == 'SDK_REJECT':
            event.update(status='Failed', errcode='FAKE_REJECT', msg='Synthetic broker rejection')
        self._callback(event)
        return {'operations': [{'task': 'NewOrder', 'status': 'Pending'}]}

    def cancel_order(self, order_id):
        require(order_id == self.order_id and self.scenario == 'SDK_CANCEL', 'BROKER_ORDER_ID_MISMATCH')
        self._callback(self._event('CancelOrder', 'Success', order_id=order_id))
        return {'operations': [{'task': 'CancelOrder', 'status': 'Pending'}]}

    def get_trades(self, *, full):
        require(full is True, 'FULL_QUERY_REQUIRED')
        if self.scenario == 'SDK_AMBIGUOUS':
            return []
        if self.scenario == 'SDK_REJECT':
            value = self._event('NewOrder', 'Failed')
            value.update(errcode='FAKE_REJECT', msg='Synthetic broker rejection')
        else:
            value = self._event('OrderStatus', 'Cancelled' if self.scenario == 'SDK_CANCEL'
                                else 'Submitted', order_id=self.order_id)
        return [value]


def normalize(args, event, *, preview_id, now, sequence, event_id):
    """Validate correlated fake observation, then convert to the sole M1 reducer input."""
    require(type(event) is dict, 'BROKER_OBSERVATION_UNVERIFIED')
    for field in ('binding', 'symbol', 'action', 'qty', 'price', 'order_cond', 'odd_lot', 'time_in_force'):
        require(event.get(field) == getattr(args, field), 'BROKER_IDENTITY_MISMATCH')
    task, status = event.get('task'), event.get('status')
    if task == 'CancelOrder':
        require(event.get('order_id') == 'FAKE-' + args.binding[:24], 'BROKER_ORDER_ID_UNVERIFIED')
        require(status in {'Pending', 'Success'} and event.get('errcode') in (None, '0'),
                'BROKER_CANCEL_OUTCOME_UNKNOWN')
        return None
    if task == 'NewOrder' and status == 'Pending':
        return None
    if task == 'NewOrder' and status in {'Failed', 'Rejected'}:
        kind = EventKind.REJECTED
    else:
        require(event.get('order_id') == 'FAKE-' + args.binding[:24], 'BROKER_ORDER_ID_UNVERIFIED')
        require(event.get('errcode') in (None, '0'), 'BROKER_STATUS_CONFLICT')
        kinds = {('NewOrder', 'Success'): EventKind.ACCEPTED,
                 ('OrderStatus', 'Submitted'): EventKind.ACCEPTED,
                 ('OrderStatus', 'Cancelled'): EventKind.CANCELLED}
        require((task, status) in kinds, 'BROKER_STATUS_UNVERIFIED')
        kind = kinds[(task, status)]
    return SimulationEvent(event_id, preview_id, kind, now, sequence, event['cumulative_shares'])


def invoke(draft, scenario, command_id, *, preview_id, now, sequence, filled, query=False):
    # Explicit fake protocol units; no assumption about real SDK qty is encoded.
    units = FakeUnits(draft.lot, 1000 if draft.lot is Lot.BOARD else 1)
    args = convert(draft, units)
    sdk = FakeSDK(args, scenario, command_id, filled)
    events = []
    sdk.set_event(events.append)
    immediate, timed_out = None, False
    if query:
        events = sdk.get_trades(full=True)
    else:
        try:
            if scenario == 'SDK_CANCEL':
                immediate = sdk.cancel_order(sdk.order_id)
            else:
                immediate = sdk.create_order(action=args.action, symbol=args.symbol, qty=args.qty,
                    price=args.price, time_in_force=args.time_in_force, order_cond=args.order_cond,
                    odd_lot=args.odd_lot)
        except TimeoutError:
            timed_out = True
    raw = events[0] if len(events) == 1 else None
    report = normalize(args, raw, preview_id=preview_id, now=now, sequence=sequence,
                       event_id='fake-' + command_id + ('-query-' + str(sequence) if query else '')) if raw else None
    proof = {'scenario': scenario, 'binding': args.binding, 'source': 'query' if query else 'callback',
             'immediate': immediate, 'observation': raw, 'timed_out': timed_out,
             'unit_evidence': units.evidence, 'report': report, 'command_id': command_id}
    return proof


def validate_proof(draft, proof, *, preview_id, now, sequence, filled, query):
    """Pure replay validation. Never invoke SDK send/cancel/query during any read."""
    require(type(proof) is dict and set(proof) == {'scenario', 'binding', 'source', 'immediate',
            'observation', 'timed_out', 'unit_evidence', 'report', 'command_id'}, 'FAKE_PROOF_MISMATCH')
    scenario = proof['scenario']
    require(scenario in {'SDK_ACCEPT', 'SDK_PENDING', 'SDK_REJECT', 'SDK_TIMEOUT',
                          'SDK_AMBIGUOUS', 'SDK_CANCEL'}, 'INVALID_MOCK_FIXTURE')
    units = FakeUnits(draft.lot, 1000 if draft.lot is Lot.BOARD else 1)
    args = convert(draft, units)
    command_id = digest_of((preview_id, 'CANCEL' if scenario == 'SDK_CANCEL' else 'SEND'))
    timed_out = not query and scenario in {'SDK_TIMEOUT', 'SDK_AMBIGUOUS'}
    immediate = None if query or timed_out else {'operations': [
        {'task': 'CancelOrder' if scenario == 'SDK_CANCEL' else 'NewOrder', 'status': 'Pending'}]}
    require(proof['command_id'] == command_id and proof['binding'] == args.binding
            and proof['unit_evidence'] == units.evidence
            and proof['source'] == ('query' if query else 'callback')
            and type(proof['timed_out']) is bool and proof['timed_out'] == timed_out
            and proof['immediate'] == immediate, 'FAKE_PROOF_MISMATCH')
    raw = proof['observation']
    absent = (scenario == 'SDK_AMBIGUOUS') if query else timed_out
    require((raw is None) == absent, 'FAKE_PROOF_MISMATCH')
    report = None
    if raw is not None:
        require(raw.get('cumulative_shares') == filled, 'FAKE_PROOF_MISMATCH')
        report = normalize(args, raw, preview_id=preview_id, now=now, sequence=sequence,
            event_id='fake-' + command_id + ('-query-' + str(sequence) if query else ''))
    require(proof['report'] == report, 'FAKE_PROOF_MISMATCH')
