import ast
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest

from execution.contracts import EventKind, ExecutionRejected, Funding, Lot, OrderKind, SimulationEvent, State
from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import temporary_sandbox, connection
from execution_simulation.codec import dumps, loads
from execution.validation import digest_of
from execution_simulation.mock import SimulatedCrash
from execution_kgi_simulator.fake import FakeSDK, FakeOrder
from execution_kgi_simulator.gates import SIM_NAMES, TAIPEI, preflight, service_window
from execution_kgi_simulator.inspection import inspect_sdk
from execution_kgi_simulator.wire import (
    arguments, fixture_session, send_fixture, query_fixture, cancel_fixture,
)


ROOT = Path(__file__).resolve().parents[2]


class Gates(unittest.TestCase):
    def test_sdk_exact_version_signatures_enums_and_no_import(self):
        info = inspect_sdk(ROOT)
        self.assertEqual(info['status'], 'INSPECTED')
        self.assertEqual(info['installed_version'], '2.1.0')
        self.assertFalse(info['sdk_imported'])
        self.assertFalse(info['abi_verified'])
        for method in ('create_order', 'cancel_order', 'get_trades', 'set_event'):
            signature = info['signatures']['trading/Order.py:OrderAPI.' + method]
            args = ast.parse('def f(' + signature + '): pass').body[0].args
            self.assertEqual([p.arg for p in args.args],
                             list(inspect.signature(getattr(FakeOrder, method)).parameters))
        self.assertEqual(info['enums']['PriceType']['MKT'], '1')
        self.assertEqual(info['enums']['OddLot']['Common'], 0)
        self.assertEqual(info['enums']['OrderCond']['CASH_SELLING'], 9)
        self.assertEqual(info['signatures']['main.py:login.__init__'],
                         'self, person_id=None, person_pwd=None, simulation: bool=True')

    def test_weekend_and_cross_midnight_boundaries(self):
        business = frozenset({date(2026, 10, 9), date(2026, 10, 12)})
        covered = business | {date(2026, 10, 13)}
        cases = [('2026-10-11T14:00', 'CLOSED_SESSION'),
                 ('2026-10-12T01:00', 'CLOSED_SESSION'),
                 ('2026-10-12T08:29:59', 'CLOSED_SESSION'),
                 ('2026-10-12T08:30', 'OPEN'),
                 ('2026-10-13T04:59:59', 'OPEN'),
                 ('2026-10-13T05:00', 'CLOSED_SESSION'),
                 ('2026-10-13T08:30', 'CLOSED_SESSION'),
                 ('2026-10-10T04:59:59', 'OPEN')]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(service_window(datetime.fromisoformat(text).replace(tzinfo=TAIPEI),
                    business_dates=business, covered_dates=covered), expected)
        self.assertEqual(service_window(datetime(2026, 10, 12, 9, tzinfo=TAIPEI)),
                         'BUSINESS_CALENDAR_UNVERIFIED')
        self.assertEqual(service_window(datetime(2026, 10, 12, 9)), 'CLOCK_UNVERIFIED')

    def test_presence_is_not_auth_and_no_flags_unlock(self):
        for mode in ('Preflight', 'Probe', 'Send'):
            result = preflight({'reasonCodes': []}, dict.fromkeys(SIM_NAMES, True), NOW, mode=mode)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn('BROKER_ENV_UNKNOWN', result['probe']['reasonCodes'])
            self.assertIn('QTY_UNIT_UNPROVEN', result['order']['reasonCodes'])
            self.assertEqual(result['orders_sent'], 0)
            self.assertEqual(result['login_attempts'], 0)

    def test_canonical_identity_is_not_sim_entitlement_or_second_secret_source(self):
        result = preflight({}, {'KGI_SUPERPY_PERSON_ID': True, 'KGI_SUPERPY_PASSWORD': True}, NOW)
        self.assertFalse(any(result['dedicated_secret_presence'].values()))
        self.assertIn('SIM_ENTITLEMENT_UNVERIFIED', result['probe']['reasonCodes'])
        self.assertFalse(any(code.startswith('MISSING_KGI_SIM_') for code in result['probe']['reasonCodes']))
        self.assertEqual(result['credential_owner'], 'app.config.Settings')
        self.assertFalse(result['credential_values_read'])
        for code in ('NATIVE_ENDPOINT_ATTESTATION_MISSING', 'NATIVE_EGRESS_CONFINEMENT_UNVERIFIED',
                     'NATIVE_FILESYSTEM_CONFINEMENT_UNVERIFIED'):
            self.assertIn(code, result['probe']['reasonCodes'])
        self.assertEqual((result['broker_calls'], result['orders_sent']), (0, 0))

    def test_version_mismatch_propagates(self):
        result = preflight({'reasonCodes': ['SDK_VERSION_MISMATCH']}, {}, NOW)
        self.assertIn('SDK_VERSION_MISMATCH', result['probe']['reasonCodes'])

    def test_real_object_cannot_replace_fixture(self):
        class Trap:
            def login(self, *args, **kwargs):
                raise AssertionError('MUST NOT CALL')
        with self.assertRaises(ExecutionRejected), fixture_session(Trap()):
            self.fail('real SDK admitted')

    def test_literal_simulation_true_and_logout_on_failure(self):
        sdk = FakeSDK()
        with self.assertRaises(ValueError), fixture_session(sdk):
            raise ValueError('fixture')
        self.assertEqual((sdk.logins, sdk.logouts), (1, 1))
        tree = ast.parse((ROOT / 'execution_kgi_simulator/wire.py').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'login']
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(k.arg == 'simulation' and isinstance(k.value, ast.Constant)
                            and k.value.value is True for k in calls[0].keywords))

    def test_units_credit_odd_lot_and_precision_block(self):
        draft, _ = fixture()
        sdk = FakeSDK()
        for change, units in [(dict(funding=Funding.MARGIN), 1000), (dict(lot=Lot.ODD), 1),
                              ({}, None), ({}, True), (dict(quantity=1001), 1000),
                              (dict(limit_price=Decimal('25.50000000000000000001')), 1000)]:
            with self.subTest(change=change), self.assertRaises(ExecutionRejected):
                arguments(replace(draft, **change), sdk, fixture_shares_per_unit=units)
        args = arguments(draft, sdk, fixture_shares_per_unit=1000)
        self.assertEqual(args['qty'], 1)
        self.assertIs(args['odd_lot'], sdk.OddLot.Common)
        self.assertEqual(args['price'], 25.5)
        market = arguments(replace(draft, order_kind=OrderKind.MARKET, limit_price=None),
                           sdk, fixture_shares_per_unit=1000)
        self.assertIs(market['price'], sdk.PriceType.MKT)


class BoundaryE2E(unittest.TestCase):
    def setUp(self):
        context = temporary_sandbox()
        self.box = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)
        self.app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
        draft, evidence = fixture()
        self.preview = self.app.preview(draft, evidence, now=NOW).value
        self.app.confirm(confirmation(self.preview), now=NOW)
        self.sdk = FakeSDK(self.outside_transaction)
        self.gen = 'local-worker-1'

    def outside_transaction(self):
        # Independent writer lock succeeds only after the owner committed claim.
        with connection(self.box) as db:
            db.execute('PRAGMA busy_timeout=0')
            db.execute('BEGIN IMMEDIATE')
            self.assertGreater(db.execute("SELECT count(*) FROM outbox_events WHERE stage='CLAIMED'").fetchone()[0], 0)
            db.rollback()

    def claim(self, kind='SEND', request='send'):
        return self.app.rehearsal_claim(self.preview.preview_id, kind=kind, generation=self.gen,
            digest=self.preview.challenge.digest, request_id=request, now=NOW).value

    def send(self, **kwargs):
        return send_fixture(self.app, self.preview, self.sdk, self.gen, now=NOW, **kwargs)

    def send_claim(self):
        with connection(self.box, readonly=True) as db:
            return loads(db.execute("SELECT payload FROM audit WHERE operation='REHEARSAL_CLAIM' "
                                    "ORDER BY seq LIMIT 1").fetchone()[0])['value']

    def state(self):
        return self.app.status(self.preview.preview_id).value['order'].state

    def accept(self, claim):
        return self.app.rehearsal_report(claim, generation=claim['generation'], task='NewOrder',
            status='Success', order_id='LOCAL-ORDER', now=NOW)

    def finality(self, claim):
        return dict(origin='SYNTHETIC', scope='LOCAL_MOCK', command_id=claim['command_id'],
                    preview_id=claim['preview_id'], generation=claim['generation'],
                    order_id='LOCAL-ORDER', status='Cancelled', complete=True)

    def final_cancel(self, claim, **kwargs):
        return self.app.rehearsal_report(claim, generation=self.gen, task='OrderStatus',
            status='Cancelled', order_id='LOCAL-ORDER', now=NOW, **kwargs)

    def assert_process_parity(self):
        # Private factory ticket only; child reads/replays and never calls a wire.
        ticket = self.box.ticket()
        script = '''import json, sys, tempfile
from pathlib import Path
from execution_kgi_simulator.worker import offline_guard
sys.addaudithook(offline_guard)
from execution_simulation import SimulationApplication
from execution_simulation.storage import SandboxTicket, reopen_sandbox
from execution_simulation.codec import dumps
v = json.load(sys.stdin)
tempfile.tempdir = str(Path(v['directory']).parent)
with reopen_sandbox(SandboxTicket(v['directory'], v['token'])) as box:
    app = SimulationApplication(box)
    assert app.verify().value['verified']
    print(dumps((app.status(v['preview_id']).value, app.audit())))
'''
        before = (self.app.status(self.preview.preview_id).value, self.app.audit())
        child = subprocess.run([sys.executable, '-B', '-S', '-c', script], cwd=ROOT,
            input=json.dumps(dict(directory=ticket.directory, token=ticket.token,
                                 preview_id=self.preview.preview_id)),
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), dumps(before))
        self.assertEqual(before, (self.app.status(self.preview.preview_id).value, self.app.audit()))

    def fixture_fill(self, cumulative):
        # Inject a late synthetic report through the existing owner and M1 reducer.
        with self.app._command(NOW, 'LATE_FILL_FIXTURE', self.preview.preview_id) as db:
            order = self.app._order(db, self.preview.preview_id)
            self.app._event(db, SimulationEvent('late-fill-' + str(cumulative), order.preview_id,
                EventKind.FILLED if cumulative == order.quantity else EventKind.PARTIAL_FILL,
                NOW, order.last_report_sequence + 1, cumulative), NOW)

    def test_pending_later_accept_query_cancel_ack_final(self):
        with fixture_session(self.sdk):
            self.send()
            self.assertIs(self.state(), State.SIMULATED_PENDING)
            claim = self.send_claim()
            self.accept(claim)
            self.accept(claim)  # Duplicate callback is idempotent.
            self.assertIs(self.state(), State.SIMULATED_ACCEPTED)
            self.assertEqual(self.app.status(self.preview.preview_id).value['order'].cumulative_filled, 0)
            query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-1', now=NOW)
            cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-1', now=NOW)
            self.assertIs(self.state(), State.CANCEL_PENDING)
            query = query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-2', now=NOW)
            self.app.rehearsal_report(query, generation=self.gen, task='CancelOrder', status='Success',
                                      order_id='LOCAL-ORDER', now=NOW)
            self.assertIs(self.state(), State.CANCEL_PENDING)
            self.assert_process_parity()
            self.final_cancel(query, finality_fixture=self.finality(query))
            self.assertIs(self.state(), State.SIMULATED_CANCELLED)
            self.assert_process_parity()
            self.assertEqual(self.sdk.Order.calls, ['SEND', 'QUERY', 'CANCEL', 'QUERY'])
            self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_kill_switch_preserves_controlled_query_cancel_and_one_shot(self):
        self.send()
        self.accept(self.send_claim())
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        with self.assertRaises(ExecutionRejected) as caught:
            self.send()
        self.assertEqual(caught.exception.code, 'KILL_SWITCH_ACTIVE')
        for kind in ('QUERY', 'CANCEL'):
            with self.assertRaises(ExecutionRejected):
                self.app.rehearsal_claim(self.preview.preview_id, kind=kind, generation=self.gen,
                    digest='wrong', request_id='bad', now=NOW)
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-off', now=NOW)
        cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-off', now=NOW)
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-off', now=NOW)
        cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-off', now=NOW)
        self.assertEqual(self.sdk.Order.calls, ['SEND', 'QUERY', 'CANCEL'])
        self.assertIs(self.state(), State.CANCEL_PENDING)
        self.assert_process_parity()

    def test_kill_switch_unknown_query_allowed_unverified_cancel_denied(self):
        self.sdk.Order.scenario = 'Timeout'
        self.send()
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        with self.assertRaises(ExecutionRejected) as caught:
            cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-off', now=NOW)
        self.assertEqual(caught.exception.code, 'BROKER_ORDER_ID_UNVERIFIED')
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-off', now=NOW)
        self.assertIs(self.state(), State.RECONCILING)
        with self.assertRaises(ExecutionRejected):
            cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-off', now=NOW)
        self.assertEqual(self.sdk.Order.calls, ['SEND', 'QUERY'])
        self.assert_process_parity()

    def test_cancel_ack_is_persisted_idempotent_and_late_fill_survives_finality(self):
        self.send()
        self.accept(self.send_claim())
        cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-ack', now=NOW)
        for _ in range(2):
            self.app.rehearsal_report(cancel, generation=self.gen, task='CancelOrder',
                status='Success', order_id='LOCAL-ORDER', now=NOW)
        with connection(self.box, readonly=True) as db:
            proofs = [loads(r[0])['value'] for r in db.execute(
                "SELECT payload FROM audit WHERE operation='REHEARSAL_REPORT'")]
        self.assertEqual(sum(p.get('semantics') == 'ACK_ONLY' for p in proofs), 1)
        self.assertIs(self.state(), State.CANCEL_PENDING)
        self.fixture_fill(100)
        self.final_cancel(cancel, finality_fixture=self.finality(cancel))
        self.assertIs(self.state(), State.SIMULATED_CANCELLED)
        self.fixture_fill(200)
        self.assertIs(self.state(), State.SIMULATED_CANCELLED)
        self.assertEqual(self.app.status(self.preview.preview_id).value['order'].cumulative_filled, 200)
        self.assert_process_parity()
        self.fixture_fill(1000)
        self.assertIs(self.state(), State.SIMULATED_FILLED)
        self.final_cancel(cancel, finality_fixture=self.finality(cancel))
        self.assertIs(self.state(), State.SIMULATED_FILLED)
        self.assert_process_parity()

    def test_terminal_status_requires_complete_correlated_synthetic_fixture(self):
        self.send()
        self.accept(self.send_claim())
        cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-final', now=NOW)
        valid = self.finality(cancel)
        invalid = [None, {}, {k: v for k, v in valid.items() if k != 'complete'}]
        invalid += [dict(valid, **{key: value}) for key, value in (
            ('origin', 'BROKER'), ('scope', 'REAL'), ('command_id', 'other'),
            ('preview_id', 'other'), ('generation', 'old'), ('order_id', 'other'),
            ('status', 'Success'), ('complete', False), ('complete', 1))]
        for proof in invalid:
            with self.subTest(proof=proof), self.assertRaises(ExecutionRejected):
                self.final_cancel(cancel, finality_fixture=proof)
        with self.assertRaises(ExecutionRejected):
            self.final_cancel(self.send_claim(), finality_fixture=self.finality(self.send_claim()))
        self.assertIs(self.state(), State.CANCEL_PENDING)
        self.app.rehearsal_fence(self.gen, now=NOW)
        with self.assertRaises(ExecutionRejected):
            self.final_cancel(cancel, finality_fixture=valid)
        self.assert_process_parity()

    def test_historical_cancel_journal_replays_without_rewriting(self):
        self.send()
        self.accept(self.send_claim())
        cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'legacy', now=NOW)
        proof = dict(claim=cancel, task='CancelOrder', status='Success', order_id='LOCAL-ORDER')
        with self.app._command(NOW, 'HISTORICAL_FIXTURE', self.preview.preview_id) as db:
            order = self.app._order(db, self.preview.preview_id)
            self.app._audit(db, NOW, 'REHEARSAL_REPORT', self.preview.preview_id, proof)
            self.app._event(db, SimulationEvent('rehearsal-' + digest_of(proof), order.preview_id,
                EventKind.CANCELLED, NOW, order.last_report_sequence + 1, 0), NOW)
        self.assertIs(self.state(), State.SIMULATED_CANCELLED)
        self.assert_process_parity()

    def test_replay_rejects_ack_promoted_to_terminal(self):
        self.send()
        self.accept(self.send_claim())
        cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-forged', now=NOW)
        self.app.rehearsal_report(cancel, generation=self.gen, task='CancelOrder',
            status='Success', order_id='LOCAL-ORDER', now=NOW)
        proof = dict(claim=cancel, task='CancelOrder', status='Success',
                     order_id='LOCAL-ORDER', semantics='ACK_ONLY')
        with self.assertRaises(ExecutionRejected) as caught:
            with self.app._command(NOW, 'INVALID_TERMINAL_FIXTURE', self.preview.preview_id) as db:
                order = self.app._order(db, self.preview.preview_id)
                self.app._event(db, SimulationEvent('rehearsal-' + digest_of(proof), order.preview_id,
                    EventKind.CANCELLED, NOW, order.last_report_sequence + 1, 0), NOW)
                self.app._verify(db)
        self.assertEqual(caught.exception.code, 'REHEARSAL_REPORT_MISMATCH')
        self.assertIs(self.state(), State.CANCEL_PENDING)
        self.assert_process_parity()

    def test_ack_cannot_resolve_unknown_or_supply_finality(self):
        self.send()
        self.accept(self.send_claim())
        cancel = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-unknown', now=NOW)
        self.app.timeout(self.preview.preview_id, now=NOW)
        self.app.rehearsal_report(cancel, generation=self.gen, task='CancelOrder',
            status='Success', order_id='LOCAL-ORDER', now=NOW)
        self.assertIs(self.state(), State.UNKNOWN)
        with self.assertRaises(ExecutionRejected):
            self.app.rehearsal_report(cancel, generation=self.gen, task='CancelOrder',
                status='Success', order_id='LOCAL-ORDER', now=NOW,
                finality_fixture=self.finality(cancel))
        with self.assertRaises(ExecutionRejected) as caught:
            self.final_cancel(cancel, finality_fixture=self.finality(cancel))
        self.assertEqual(caught.exception.code, 'RECONCILIATION_REQUIRED')
        self.assert_process_parity()

    def test_crash_after_claim_and_effect_no_resend(self):
        for boundary in ('after_claim', 'after_effect'):
            with self.subTest(boundary=boundary):
                # Each subtest has an independent fixture/application.
                if boundary == 'after_effect':
                    self.setUp()
                with self.assertRaises(SimulatedCrash):
                    self.send(crash_at=boundary)
                before = list(self.sdk.Order.calls)
                self.app = SimulationApplication(self.box)
                self.app.rehearsal_fence(self.gen, now=NOW)
                self.gen = 'local-worker-2'
                self.send()
                self.assertEqual(self.sdk.Order.calls, before)
                self.assertIs(self.state(), State.UNKNOWN)
                self.assertTrue(self.app.verify().value['verified'])

    def test_timeout_empty_query_stays_reconciling(self):
        self.sdk.Order.scenario = 'Timeout'
        self.send()
        self.assertIs(self.state(), State.UNKNOWN)
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-1', now=NOW)
        self.assertIs(self.state(), State.RECONCILING)
        self.send()
        self.assertEqual(self.sdk.Order.calls.count('SEND'), 1)

    def test_reject_does_not_release_reservation(self):
        self.send()
        claim = self.send_claim()
        self.app.rehearsal_report(claim, generation=self.gen, task='NewOrder', status='Failed',
                                  order_id='LOCAL-ORDER', now=NOW)
        self.assertIs(self.state(), State.SIMULATED_REJECTED)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_digest_tamper_kill_switch_expiry_and_no_order_before_confirm(self):
        with self.assertRaises(ExecutionRejected):
            self.app.rehearsal_claim(self.preview.preview_id, kind='SEND', generation=self.gen,
                digest='changed', request_id='send', now=NOW)
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        with self.assertRaises(ExecutionRejected):
            self.send()
        self.app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
        with self.assertRaises(ExecutionRejected):
            send_fixture(self.app, self.preview, self.sdk, self.gen, now=NOW + timedelta(seconds=61))
        self.assertEqual(self.sdk.Order.calls, [])

    def test_wrong_generation_unknown_id_pending_not_accepted(self):
        self.send()
        claim = self.send_claim()
        for change in ({'generation': 'old'}, {'order_id': 'UNVERIFIED'}, {'status': 'Pending'}):
            kwargs = dict(generation=self.gen, task='NewOrder', status='Success', order_id='LOCAL-ORDER', now=NOW)
            kwargs.update(change)
            with self.assertRaises(ExecutionRejected):
                self.app.rehearsal_report(claim, **kwargs)
        self.app.rehearsal_fence(self.gen, now=NOW)
        with self.assertRaises(ExecutionRejected):
            self.accept(claim)

    def test_reads_reopen_duplicate_send_have_no_sdk_calls(self):
        self.send()
        before = self.app.audit()
        self.app = SimulationApplication(self.box)
        self.app.status(self.preview.preview_id)
        self.app.snapshot(self.preview.preview_id)
        self.app.verify()
        self.assertEqual(before, self.app.audit())
        self.send()
        self.assertEqual(self.sdk.Order.calls, ['SEND'])

    def test_claim_before_confirmation_denied(self):
        with temporary_sandbox() as box:
            app = SimulationApplication(box)
            draft, evidence = fixture()
            p = app.preview(draft, evidence, now=NOW).value
            with self.assertRaises(ExecutionRejected):
                app.rehearsal_claim(p.preview_id, kind='SEND', generation=self.gen,
                                   digest=p.challenge.digest, request_id='send', now=NOW)

    def test_fenced_generation_cannot_start_new_effect(self):
        self.app.rehearsal_fence(self.gen, now=NOW)
        with self.assertRaises(ExecutionRejected):
            self.send()
        self.assertEqual(self.sdk.Order.calls, [])

    def test_global_order_interval_is_strictly_greater_than_one_second(self):
        self.send()
        draft, evidence = fixture()
        second = self.app.preview(replace(draft, client_request_id='request-2'), evidence, now=NOW).value
        self.app.confirm(confirmation(second), now=NOW)
        with self.assertRaises(ExecutionRejected) as caught:
            send_fixture(self.app, second, self.sdk, self.gen, now=NOW + timedelta(seconds=1))
        self.assertEqual(caught.exception.code, 'ORDER_INTERVAL_NOT_GREATER_THAN_ONE_SECOND')
        send_fixture(self.app, second, self.sdk, self.gen, now=NOW + timedelta(milliseconds=1001))
        self.assertEqual(self.sdk.Order.calls, ['SEND', 'SEND'])

    def test_cancel_failed_cannot_reject_original_order(self):
        self.send()
        self.accept(self.send_claim())
        claim = cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-1', now=NOW)
        with self.assertRaises(ExecutionRejected):
            self.app.rehearsal_report(claim, generation=self.gen, task='NewOrder', status='Failed',
                                      order_id='LOCAL-ORDER', now=NOW)
        self.assertIs(self.state(), State.CANCEL_PENDING)

    def test_query_cancel_timeout_remain_unknown_without_retry(self):
        self.send()
        self.accept(self.send_claim())
        self.sdk.Order.cancel_scenario = 'Timeout'
        cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-1', now=NOW)
        self.assertIs(self.state(), State.UNKNOWN)
        self.assertTrue(self.app.status(self.preview.preview_id).value['order'].cancel_requested)
        cancel_fixture(self.app, self.preview, self.sdk, self.gen, 'cancel-1', now=NOW)
        self.assertEqual(self.sdk.Order.calls.count('CANCEL'), 1)
        self.sdk.Order.query_scenario = 'Timeout'
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-1', now=NOW)
        self.assertIs(self.state(), State.UNKNOWN)
        query_fixture(self.app, self.preview, self.sdk, self.gen, 'query-1', now=NOW)
        self.assertEqual(self.sdk.Order.calls.count('QUERY'), 1)
