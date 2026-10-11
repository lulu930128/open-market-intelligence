from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal as D
from itertools import product
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from execution.contracts import (
    EventKind, ExecutionRejected, Funding, OrderKind, PositionAction, Side, SimulationEvent, State,
)
from execution.tests.expanded_fixtures import expanded_fixture
from execution.tests.fixtures import NOW, confirmation, fixture
from execution.validation import digest_of
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.codec import dumps, loads
from execution_simulation.mock import Fixture, SimulatedCrash
from execution_simulation.storage import connection


class ExpandedApplicationTests(unittest.TestCase):
    def setUp(self):
        self.scope = temporary_sandbox()
        self.box = self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)

    def reject(self, code, fn, *args, **kwargs):
        with self.assertRaises(ExecutionRejected) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def counts(self):
        with connection(self.box, readonly=True) as db:
            return {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                    for table in ('confirmations', 'reservations', 'orders', 'outbox', 'mock_effects')}

    def test_preview_cancel_repeated_restart_consumes_without_dispatch(self):
        p = self.app.preview(*fixture(), now=NOW).value
        for seconds in (0, 1, 2):
            result = self.app.cancel(p.preview_id, now=NOW + timedelta(seconds=seconds), user_confirmed=True)
            self.assertEqual(result.value['order'].state, State.SIMULATED_CANCELLED)
            self.assertIsNone(result.value['order'].confirmed_at)
            self.assertEqual(result.value['commands'], ())
            self.assertEqual(result.value['simulation_attempts'], 0)
            self.app = SimulationApplication(self.box)
        self.assertEqual(self.counts(), dict(confirmations=0, reservations=0, orders=1, outbox=0, mock_effects=0))
        self.reject('CHALLENGE_CONSUMED', self.app.confirm, confirmation(p), now=NOW + timedelta(seconds=3))
        self.reject('CHALLENGE_CONSUMED', self.app.preview, p.draft, p.evidence, now=NOW + timedelta(seconds=3))
        self.reject('CHALLENGE_CONSUMED', self.app.confirm, confirmation(p), now=NOW + timedelta(days=1))
        for kind in ('SEND', 'CANCEL'):
            self.reject('NO_OUTBOX_COMMAND', self.app.dispatch, p.preview_id, now=NOW + timedelta(days=1), kind=kind)
        self.assertTrue(self.app.verify().value['verified'])
        with connection(self.box, readonly=True) as db:
            events = [loads(r[0])['value']['event'] for r in db.execute("SELECT payload FROM audit WHERE operation='EVENT'")]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].kind, EventKind.CANCEL_REQUESTED)

    def test_preview_cancel_requires_manual_confirmation_and_serializes_race(self):
        p = self.app.preview(*fixture(), now=NOW).value
        self.reject('EXPLICIT_CONFIRMATION_REQUIRED', self.app.cancel, p.preview_id, now=NOW, user_confirmed=False)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: SimulationApplication(self.box).cancel(p.preview_id, now=NOW, user_confirmed=True), range(4)))
        self.reject('CHALLENGE_CONSUMED', self.app.confirm, confirmation(p), now=NOW)
        self.assertEqual(self.counts()['outbox'], 0)
        self.assertTrue(self.app.verify().value['verified'])

    def test_unknown_cancel_before_effect_stays_intent_and_holds_resources(self):
        p = self.app.preview(*fixture(), now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        with self.assertRaises(SimulatedCrash):
            self.app.dispatch(p.preview_id, now=NOW, crash_at='after_claim')
        self.app.recover(p.preview_id, now=NOW)
        for _ in range(2):
            result = self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
            self.assertEqual(result.value['order'].state, State.UNKNOWN)
            self.assertTrue(result.value['order'].cancel_requested)
        self.assertEqual(self.counts(), dict(confirmations=1, reservations=1, orders=1, outbox=1, mock_effects=0))
        self.app = SimulationApplication(self.box)
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.app.status(p.preview_id).value['order'].state, State.RECONCILING)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.counts()['mock_effects'], 0)
        self.assertEqual(self.counts()['reservations'], 1)
        self.assertEqual(self.counts()['outbox'], 1)
        self.assertTrue(self.app.verify().value['verified'])

    def test_unknown_before_claim_cancel_prevents_send(self):
        p = self.app.preview(*fixture(), now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.timeout(p.preview_id, now=NOW)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.reject('DISPATCH_STATE_BLOCKED', self.app.dispatch, p.preview_id, now=NOW)
        self.assertEqual(self.counts()['mock_effects'], 0)

    def test_unknown_cancel_reconciles_then_explicit_cancel_ack(self):
        p = self.app.preview(*fixture(), now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW, fixture=Fixture.TIMEOUT)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.counts()['outbox'], 1)
        self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.app.status(p.preview_id).value['order'].state, State.CANCEL_PENDING)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, now=NOW, kind='CANCEL', fixture=Fixture.CANCEL)
        self.assertEqual(self.app.status(p.preview_id).value['order'].state, State.SIMULATED_CANCELLED)
        self.assertEqual(self.counts()['mock_effects'], 2)
        self.assertEqual(self.counts()['reservations'], 1)

    def test_outward_audit_status_no_secret_even_nested_caller_fields(self):
        p = self.app.preview(*fixture(), now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW)
        token = p.challenge.token
        # Deliberately smuggle the challenge into an otherwise-valid event identifier.
        self.app.callback(SimulationEvent(token, p.preview_id, EventKind.PARTIAL_FILL, NOW, 2, 500), now=NOW)
        for outward in (self.app.audit(), self.app.status(p.preview_id)):
            self.assertNotIn(token, repr(outward))
            self.assertNotIn(token, json.dumps(asdict(outward), default=str))
            self.assertNotIn(p.draft.account_id, repr(outward))
            self.assertNotIn('challenge', repr(outward).lower())
        with connection(self.box, readonly=True) as db:
            self.assertTrue(any(token in row[0] for row in db.execute('SELECT payload FROM audit')))
        before = self.box.database.read_bytes()
        SimulationApplication(self.box).audit()
        self.app.status(p.preview_id)
        self.assertEqual(before, self.box.database.read_bytes())
        self.assertTrue(self.app.verify().value['verified'])

    def test_all_modes_confirm_partial_fill_restart_no_external_io(self):
        with patch('socket.socket', side_effect=AssertionError('NO NETWORK')), \
                patch('subprocess.Popen', side_effect=AssertionError('NO PROCESS')):
            for funding, action, kind in product(Funding, PositionAction, OrderKind):
                with self.subTest(funding=funding, action=action, kind=kind), temporary_sandbox() as box:
                    app = SimulationApplication(box)
                    p = app.preview(*expanded_fixture(funding=funding, action=action, kind=kind), now=NOW).value
                    app.confirm(confirmation(p), now=NOW)
                    app.dispatch(p.preview_id, now=NOW)
                    result = app.simulate_fill(p.preview_id, cumulative_filled=400, now=NOW)
                    self.assertEqual(result.value['order'].state, State.SIMULATED_PARTIALLY_FILLED)
                    result = app.simulate_fill(p.preview_id, cumulative_filled=1000, now=NOW)
                    self.assertEqual(result.value['order'].state, State.SIMULATED_FILLED)
                    app.simulate_fill(p.preview_id, cumulative_filled=1000, now=NOW)
                    self.assertTrue(SimulationApplication(box).verify().value['verified'])
                    self.assertFalse(result.broker_connected)
                    self.assertTrue(result.simulated and result.test_only)

    def test_partial_cancel_late_fill_retains_v2_resources(self):
        d, e = expanded_fixture(funding=Funding.SHORT_SELLING, kind=OrderKind.MARKET)
        e = replace(e, account=replace(e.account, credit=replace(e.account.credit, short_borrow_available=1000)))
        p = self.app.preview(d, e, now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.simulate_fill(p.preview_id, cumulative_filled=400, now=NOW)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, now=NOW, kind='CANCEL', fixture=Fixture.CANCEL)
        self.assertEqual(self.app.status(p.preview_id).value['order'].state, State.SIMULATED_CANCELLED)
        q = self.app.preview(replace(d, client_request_id='cannot-reuse'), e, now=NOW).value
        self.reject('INSUFFICIENT_BORROW', self.app.confirm, confirmation(q), now=NOW)
        self.app.simulate_fill(p.preview_id, cumulative_filled=1000, now=NOW)
        self.assertEqual(self.app.status(p.preview_id).value['order'].state, State.SIMULATED_FILLED)
        self.reject('INSUFFICIENT_BORROW', self.app.confirm, confirmation(q), now=NOW)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_resource_holds_cannot_be_reused_after_reject_cancel_or_fill(self):
        cases = ((Funding.MARGIN, PositionAction.OPEN, 'available_credit', D('15300'), 'INSUFFICIENT_CREDIT'),
                 (Funding.SHORT_SELLING, PositionAction.OPEN, 'available_collateral', D('108000'), 'INSUFFICIENT_COLLATERAL'),
                 (Funding.SHORT_SELLING, PositionAction.OPEN, 'short_borrow_available', 1000, 'INSUFFICIENT_BORROW'),
                 (Funding.LEND_SELLING, PositionAction.OPEN, 'lend_borrow_available', 1000, 'INSUFFICIENT_BORROW'),
                 (Funding.MARGIN, PositionAction.CLOSE, 'margin_position', 1000, 'INSUFFICIENT_MARGIN_POSITION'),
                 (Funding.SHORT_SELLING, PositionAction.CLOSE, 'short_position', 1000, 'INSUFFICIENT_SHORT_POSITION'),
                 (Funding.LEND_SELLING, PositionAction.CLOSE, 'lend_position', 1000, 'INSUFFICIENT_SHORT_POSITION'))
        for funding, action, field, amount, code in cases:
            with self.subTest(field=field), temporary_sandbox() as box:
                app = SimulationApplication(box)
                d, e = expanded_fixture(funding=funding, action=action)
                e = replace(e, account=replace(e.account, credit=replace(e.account.credit, **{field: amount})))
                p = app.preview(d, e, now=NOW).value
                q = app.preview(replace(d, client_request_id='second'), e, now=NOW).value
                app.confirm(confirmation(p), now=NOW)
                app.dispatch(p.preview_id, now=NOW, fixture=Fixture.REJECT)
                self.reject(code, app.confirm, confirmation(q), now=NOW)
                self.assertTrue(SimulationApplication(box).verify().value['verified'])

    def test_credit_confirm_race_and_baseline_reset(self):
        d, e = expanded_fixture(funding=Funding.MARGIN)
        e = replace(e, account=replace(e.account, credit=replace(e.account.credit, available_credit=D('15300'))))
        previews = [self.app.preview(replace(d, client_request_id='race-' + str(i)), e, now=NOW).value for i in range(2)]
        def confirm(p):
            try:
                SimulationApplication(self.box).confirm(confirmation(p), now=NOW)
                return 'CONFIRMED'
            except ExecutionRejected as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(confirm, previews)), ['CONFIRMED', 'INSUFFICIENT_CREDIT'])
        e = replace(e, account=replace(e.account, credit=replace(e.account.credit, available_credit=D('100000'))))
        p = self.app.preview(replace(d, client_request_id='reset'), e, now=NOW).value
        self.reject('CREDIT_BASELINE_CHANGED', self.app.confirm, confirmation(p), now=NOW)
        self.assertTrue(self.app.verify().value['verified'])

    def test_intraday_risk_reserves_across_orders_and_no_version_downgrade(self):
        d, e = expanded_fixture()
        e = replace(e, permission=replace(e.permission, maximum_intraday_risk=D('25500')))
        p = self.app.preview(d, e, now=NOW).value
        q = self.app.preview(replace(d, client_request_id='next'), e, now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.reject('INTRADAY_RISK_LIMIT', self.app.confirm, confirmation(q), now=NOW)
        old, oe = fixture()
        # Same account, legacy symbol; must not evade the established v2 envelope.
        r = self.app.preview(replace(old, client_request_id='old'), oe, now=NOW).value
        self.reject('RESOURCE_CONTRACT_DOWNGRADE', self.app.confirm, confirmation(r), now=NOW)

    def test_price_guard_and_resource_projection_tamper(self):
        d, e = expanded_fixture(kind=OrderKind.MARKET)
        p = self.app.preview(d, e, now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW)
        self.reject('FILL_PRICE_GUARD', self.app.callback,
                    SimulationEvent('bad', p.preview_id, EventKind.FILLED, NOW, 2, 1000, D('91')), now=NOW)
        with connection(self.box) as db:
            db.execute('DROP TRIGGER immutable_reservations_UPDATE')
            db.execute("UPDATE reservations SET cash='0'")
        self.reject('RESERVATION_PROJECTION_MISMATCH', self.app.verify)

    def test_expanded_dispatch_expired_snapshot_never_claims(self):
        p = self.app.preview(*expanded_fixture(kind=OrderKind.MARKET), now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.reject('EVIDENCE_EXPIRED_OR_NOT_YET_VALID', self.app.dispatch, p.preview_id,
                    now=NOW + timedelta(seconds=120))
        self.assertEqual(self.counts()['mock_effects'], 0)
        self.assertEqual(self.app.status(p.preview_id).value['commands'][0]['stage'], 'READY')

    def test_legacy_bytes_and_digest_roundtrip(self):
        raw = (Path(__file__).parent / 'legacy_preview_v1.json').read_text(encoding='utf-8')
        p = loads(raw)
        self.assertEqual(dumps(p), raw)
        self.assertEqual(digest_of((p.preview_id, p.draft, p.evidence, p.assessment, p.created_at)), p.challenge.digest)
        with connection(self.box) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO previews VALUES(?,?,?,?,?,?)', (p.preview_id, p.draft.account_id,
                p.draft.client_request_id, digest_of(p.draft), digest_of(p.evidence), raw))
            self.app._audit(db, NOW, 'PREVIEW', p.preview_id, p)
            db.execute("INSERT INTO metadata VALUES('last_now',?)", (dumps(NOW),))
            db.commit()
        before = self.box.database.read_bytes()
        self.app = SimulationApplication(self.box)
        self.assertEqual(self.box.database.read_bytes(), before)
        self.app.confirm(confirmation(p), now=NOW)
        self.assertTrue(self.app.verify().value['verified'])
        d, e = expanded_fixture(kind=OrderKind.MARKET)
        self.assertEqual(loads(dumps((d, e))), (d, e))
        payload = json.loads(dumps(d))
        del payload['payload']['fields']['contract_version']
        downgraded = loads(json.dumps(payload))
        self.reject('EXPANDED_CONTRACT_REQUIRED', self.app.preview, downgraded, e, now=NOW)
