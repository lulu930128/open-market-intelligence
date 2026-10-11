import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

from execution.contracts import Confirmation, ExecutionRejected, Funding, Lot
from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication
from execution_simulation.storage import temporary_sandbox
from execution_simulation.mock import Fixture, SimulatedCrash
from execution_simulation.fake_sdk import convert, FakeSDK, FakeUnits, invoke, normalize
from execution_simulation_gateway.security import SyntheticAuth
from execution_simulation_gateway.tests.http_driver import request
from execution_simulation_gateway.tests.support import draft, confirm_body, headers
from execution_manual_mock.fixtures import catalog, PRINCIPAL, ACCOUNT, ORIGIN, DEFAULT_SYMBOLS
from execution_manual_mock.gateway import ManualMockApp
from execution_manual_mock.runtime import worker_lock


class Manual(unittest.TestCase):
    def setUp(self):
        self.context = temporary_sandbox()
        self.sandbox = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.app = SimulationApplication(self.sandbox)
        self.auth = SyntheticAuth(origins={ORIGIN}, requests_per_minute=1000)
        self.credentials = self.auth.issue(PRINCIPAL, ACCOUNT, now=NOW)
        self.policy, self.scenarios = catalog(DEFAULT_SYMBOLS, NOW)
        self.gateway = ManualMockApp(self.app, self.auth, self.policy, lambda: NOW, self.scenarios)
        self.app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)

    def call(self, method, path, body=None, preview=None):
        return asyncio.run(request(self.gateway, method, '/test-execution/v1' + path,
                       headers=headers(self.credentials, preview), body=body))

    def preview(self, symbol='2330', **kwargs):
        code, response = self.call('POST', '/preview', draft(symbol=symbol, **kwargs))
        self.assertEqual(code, 200, response)
        return response['data']

    def confirmed(self, symbol='2330', **kwargs):
        p = self.preview(symbol, **kwargs)
        code, response = self.call('POST', '/confirm', confirm_body(p), p)
        self.assertEqual(code, 200, response)
        self.assertEqual(response['data']['phase'], 'CONFIRMED')
        return p

    def action(self, p, action):
        return self.call('POST', '/orders/' + p['preview_id'] + '/' + action, {'user_confirmed': True}, p)

    def test_accept_query_cancel_ack_final_and_pure_get(self):
        p = self.confirmed()
        _, result = self.action(p, 'submit')
        self.assertEqual(result['status'], 'BROKER_ACCEPTED')
        self.assertTrue(result['data']['broker']['order_id'].startswith('FAKE-'))
        self.assertEqual(result['data']['broker']['filled_shares'], 0)
        before = self.app.audit()
        self.call('GET', '/orders/' + p['preview_id'], preview=p)
        self.assertEqual(before, self.app.audit())
        self.assertEqual(self.action(p, 'query')[1]['status'], 'BROKER_ACCEPTED')
        self.assertEqual(self.action(p, 'cancel')[1]['status'], 'CANCEL_PENDING')
        self.assertEqual(self.action(p, 'reconcile')[1]['status'], 'CANCELLED')
        self.assertTrue(self.app.verify().value['verified'])

    def test_pending_reject_timeout_ambiguous(self):
        for symbol, expected in [('2317', 'PENDING'), ('2454', 'BROKER_REJECTED'),
                                 ('2303', 'UNKNOWN'), ('2882', 'UNKNOWN')]:
            with self.subTest(symbol=symbol):
                p = self.confirmed(symbol, client_request_id='request-' + symbol)
                _, response = self.action(p, 'submit')
                self.assertEqual(response['status'], expected, response)
                if symbol == '2454':
                    self.assertEqual(response['data']['broker']['errcode'], 'FAKE_REJECT')
                else:
                    _, response = self.action(p, 'reconcile')
                    self.assertEqual(response['status'], 'RECONCILING' if symbol == '2882' else 'BROKER_ACCEPTED')
                self.action(p, 'submit')
                self.assertEqual(self.app.status(p['preview_id']).value['commands'][0]['mock_effects'], 1)

    def test_admission_codes(self):
        cases = [({'symbol': '0000'}, 'INSTRUMENT_UNVERIFIED'),
                 ({'symbol': '2330/abc'}, 'INVALID_SYMBOL'),
                 ({'symbol': '9998'}, 'NOT_TRADABLE'),
                 ({'symbol': '9997'}, 'EVIDENCE_EXPIRED_OR_NOT_YET_VALID'),
                 ({'symbol': '9996'}, 'PERMISSION_DENIED'),
                 ({'symbol': '9995'}, 'SESSION_NOT_OPEN'),
                 ({'quantity': True}, 'INVALID_QUANTITY'),
                 ({'lot': 'ODD', 'quantity': 17}, 'LOT_UNVERIFIED'),
                 ({'funding': 'MARGIN'}, 'CREDIT_UNVERIFIED'),
                 ({'limit_price': '25.51'}, 'INVALID_PRICE_TICK')]
        for change, expected in cases:
            with self.subTest(change=change):
                _, result = self.call('POST', '/preview', draft(**change))
                self.assertIn(expected, result['reasonCodes'])
                self.assertEqual(result['status'], 'VALIDATION_BLOCKED')

    def test_market_arbitrary_symbol_and_credit_close_denied(self):
        p = self.confirmed(order_kind='MARKET', limit_price=None)
        self.assertEqual(self.action(p, 'submit')[1]['status'], 'BROKER_ACCEPTED')
        policy, scenarios = catalog(('6543',), NOW)
        self.gateway = ManualMockApp(self.app, self.auth, policy, lambda: NOW, scenarios)
        p = self.confirmed('6543', client_request_id='arbitrary')
        self.assertEqual(self.action(p, 'submit')[1]['status'], 'BROKER_ACCEPTED')

    def test_confirmation_and_submit_are_separate_and_kill_durable(self):
        p = self.preview()
        self.assertEqual(self.action(p, 'submit')[1]['status'], 'VALIDATION_BLOCKED')
        self.assertEqual(self.app.status(p['preview_id']).value['commands'], ())
        code, _ = self.call('POST', '/confirm', confirm_body(p, user_confirmed=False), p)
        self.assertNotEqual(code, 200)
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        self.assertEqual(self.call('POST', '/confirm', confirm_body(p), p)[1]['reasonCodes'], ['KILL_SWITCH_ACTIVE'])
        self.assertFalse(SimulationApplication(self.sandbox).mock_broker_status(p['preview_id']).value['order_id_verified'])

    def test_crash_reopen_never_resends_and_fences(self):
        p = self.confirmed()
        with self.assertRaises(SimulatedCrash):
            self.app.dispatch(p['preview_id'], now=NOW, fixture=Fixture.SDK_ACCEPT, crash_at='after_effect')
        reopened = SimulationApplication(self.sandbox)
        self.assertEqual(reopened.mock_broker_status(p['preview_id']).value['status'], 'UNKNOWN')
        reopened.dispatch(p['preview_id'], now=NOW, fixture=Fixture.SDK_ACCEPT)
        self.assertEqual(reopened.status(p['preview_id']).value['commands'][0]['mock_effects'], 1)
        reopened.reconcile(p['preview_id'], now=NOW, user_confirmed=True)
        self.assertEqual(reopened.mock_broker_status(p['preview_id']).value['status'], 'BROKER_ACCEPTED')

    def test_idempotency_resources_late_fill_and_cancel(self):
        p = self.confirmed(quantity=20000)
        self.call('POST', '/confirm', confirm_body(p), p)
        self.action(p, 'submit')
        self.action(p, 'submit')
        other = self.preview(client_request_id='second', quantity=20000)
        self.assertIn('INSUFFICIENT_CASH', self.call('POST', '/confirm', confirm_body(other), other)[1]['reasonCodes'])
        self.action(p, 'cancel')
        self.app.simulate_fill(p['preview_id'], cumulative_filled=1000, now=NOW)
        self.action(p, 'reconcile')
        self.app.simulate_fill(p['preview_id'], cumulative_filled=20000, now=NOW)
        state = self.app.mock_broker_status(p['preview_id']).value
        self.assertEqual((state['status'], state['filled_shares']), ('FILLED', 20000))

    def test_worker_mutex_and_auth(self):
        with worker_lock(self.sandbox):
            with self.assertRaisesRegex(RuntimeError, 'DEDICATED_WORKER_ALREADY_OWNED'):
                with worker_lock(self.sandbox):
                    pass
        with worker_lock(self.sandbox):
            pass
        p = self.confirmed()
        self.auth.revoke(self.credentials)
        self.assertEqual(self.action(p, 'submit')[0], 401)

    def test_units_identity_and_no_implicit_mapping(self):
        from execution.tests.expanded_fixtures import expanded_fixture
        draft_value, _ = expanded_fixture()
        with self.assertRaisesRegex(ExecutionRejected, 'BROKER_QUANTITY_UNIT_UNVERIFIED'):
            convert(draft_value, None)
        args = convert(draft_value, FakeUnits(Lot.BOARD, 1000))
        proof = invoke(draft_value, 'SDK_ACCEPT', 'command', preview_id='test', now=NOW, sequence=1, filled=0)
        raw = dict(proof['observation'], symbol='2317')
        with self.assertRaisesRegex(ExecutionRejected, 'BROKER_IDENTITY_MISMATCH'):
            normalize(args, raw, preview_id='test', now=NOW, sequence=1, event_id='bad')
        for funding in (Funding.MARGIN, Funding.SHORT_SELLING, Funding.LEND_SELLING):
            with self.subTest(funding=funding), self.assertRaises(ExecutionRejected):
                convert(replace(draft_value, funding=funding), FakeUnits(Lot.BOARD, 1000))

    def test_cross_process_dispatch_once_and_restart_after_crash(self):
        p = self.confirmed()
        ticket = self.sandbox.ticket()
        value = {'ticket': {'directory': ticket.directory, 'token': ticket.token}, 'preview': p['preview_id']}
        command = [sys.executable, '-B', '-m', 'execution_manual_mock.tests.process_worker']
        crash = subprocess.run(command, input=json.dumps(dict(value, crash='after_effect')),
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(crash.returncode, 17, crash.stderr)
        processes = [subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            process.stdin.write(json.dumps(value))
            process.stdin.close()
            process.stdin = None
        for process in processes:
            output, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual(json.loads(output)['effects'], 1)
        self.app.recover(p['preview_id'], now=NOW)
        self.assertEqual(self.app.mock_broker_status(p['preview_id']).value['status'], 'UNKNOWN')

    def test_confirm_crash_atomic_and_expired(self):
        p = self.preview()
        c = Confirmation(p['preview_id'], p['confirmation']['token'], p['confirmation']['digest'], PRINCIPAL, True)
        for boundary in ('before_outbox', 'before_commit'):
            with self.subTest(boundary=boundary), self.assertRaises(SimulatedCrash):
                self.app.confirm(c, now=NOW, crash_at=boundary)
            self.assertEqual(self.app.status(p['preview_id']).value['commands'], ())
        with self.assertRaisesRegex(ExecutionRejected, 'PREVIEW_EXPIRED'):
            self.app.confirm(c, now=NOW + timedelta(seconds=61))

    def test_kill_after_confirmation_retains_query_cancel_and_fences_claim(self):
        p = self.confirmed()
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        self.assertEqual(self.action(p, 'submit')[1]['reasonCodes'], ['KILL_SWITCH_ACTIVE'])
        self.app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
        with self.assertRaises(SimulatedCrash):
            self.app.dispatch(p['preview_id'], now=NOW, fixture=Fixture.SDK_ACCEPT, crash_at='after_claim')
        self.app.recover(p['preview_id'], now=NOW)
        self.action(p, 'submit')
        self.assertEqual(self.app.status(p['preview_id']).value['commands'][0]['mock_effects'], 0)

    def test_pending_id_is_not_acceptance_and_query_not_fill(self):
        p = self.confirmed('2317')
        self.action(p, 'submit')
        self.assertEqual(self.action(p, 'cancel')[1]['reasonCodes'], ['BROKER_ORDER_ID_UNVERIFIED'])
        self.action(p, 'query')
        result = self.app.mock_broker_status(p['preview_id']).value
        self.assertEqual((result['status'], result['filled_shares']), ('PENDING', 0))
        self.assertTrue(result['order_id_verified'])

    def test_second_principal_and_tampered_confirmation_denied(self):
        p = self.preview()
        bad = confirm_body(p, digest='bad')
        self.assertEqual(self.call('POST', '/confirm', bad, p)[1]['reasonCodes'], ['PAYLOAD_DIGEST_MISMATCH'])
        self.credentials = self.auth.issue('synthetic-other', ACCOUNT, now=NOW)
        self.assertEqual(self.action(p, 'submit')[1]['reasonCodes'], ['ORDER_ACCESS_DENIED'])

    def test_cancel_failure_not_order_rejection_or_final_cancel(self):
        from execution.tests.expanded_fixtures import expanded_fixture
        d, _ = expanded_fixture()
        args = convert(d, FakeUnits(Lot.BOARD, 1000))
        proof = invoke(d, 'SDK_CANCEL', 'cancel', preview_id='test', now=NOW, sequence=1, filled=0)
        self.assertIsNone(proof['report'])
        raw = dict(proof['observation'], status='Failed', errcode='FAKE_CANCEL_FAILURE')
        with self.assertRaisesRegex(ExecutionRejected, 'BROKER_CANCEL_OUTCOME_UNKNOWN'):
            normalize(args, raw, preview_id='test', now=NOW, sequence=1, event_id='failed-cancel')

    def test_read_replay_and_repeated_dispatch_never_call_sdk(self):
        p = self.confirmed()
        self.action(p, 'submit')
        with patch.object(FakeSDK, 'create_order', side_effect=AssertionError('send on replay')), \
             patch.object(FakeSDK, 'cancel_order', side_effect=AssertionError('cancel on replay')), \
             patch.object(FakeSDK, 'get_trades', side_effect=AssertionError('query on read')):
            reopened = SimulationApplication(self.sandbox)
            reopened.verify()
            reopened.mock_broker_status(p['preview_id'])
            self.assertEqual(self.call('GET', '/orders/' + p['preview_id'], preview=p)[0], 200)
            self.assertEqual(self.action(p, 'submit')[1]['status'], 'BROKER_ACCEPTED')

    def test_confirmed_but_unsent_expired_preview_cannot_send(self):
        p = self.confirmed()
        with self.assertRaisesRegex(ExecutionRejected, 'PREVIEW_EXPIRED'):
            self.app.dispatch(p['preview_id'], now=NOW + timedelta(seconds=61), fixture=Fixture.SDK_ACCEPT)
        self.assertEqual(self.app.status(p['preview_id']).value['commands'][0]['mock_effects'], 0)


if __name__ == '__main__':
    unittest.main()
