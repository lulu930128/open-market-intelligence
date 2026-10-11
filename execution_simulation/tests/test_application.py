from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from execution.contracts import EventKind, ExecutionRejected, Side, SimulationEvent, State
from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.codec import dumps, loads
from execution_simulation.mock import Fixture, SimulatedCrash
from execution_simulation.storage import Sandbox, SandboxTicket, connection, reopen_sandbox
from execution_simulation.fixtures import symbol_fixture


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.scope = temporary_sandbox()
        self.box = self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)

    def preview(self, **kwargs):
        draft, evidence = fixture(**kwargs)
        return self.app.preview(draft, evidence, now=NOW).value

    def confirmed(self, **kwargs):
        p = self.preview(**kwargs)
        self.app.confirm(confirmation(p), now=NOW)
        return p

    def state(self, p):
        return self.app.status(p.preview_id).value['order'].state

    def event(self, p, kind, sequence, filled=0, event_id=None):
        return SimulationEvent(event_id or 'report-' + str(sequence), p.preview_id, kind, NOW, sequence, filled)

    def reject(self, code, function, *args, **kwargs):
        with self.assertRaises(ExecutionRejected) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def count(self, table):
        with connection(self.box, readonly=True) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_accepted_partial_full_restart_and_replay(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        self.assertEqual(self.state(p), State.SIMULATED_ACCEPTED)
        self.app.callback(self.event(p, EventKind.PARTIAL_FILL, 2, 400), now=NOW)
        self.assertEqual(self.state(p), State.SIMULATED_PARTIALLY_FILLED)
        self.app.callback(self.event(p, EventKind.FILLED, 3, 1000), now=NOW)
        self.app = SimulationApplication(self.box)
        self.assertEqual(self.state(p), State.SIMULATED_FILLED)
        self.assertTrue(self.app.verify().value['verified'])
        self.app.confirm(confirmation(p), now=NOW + timedelta(seconds=80))
        self.app.dispatch(p.preview_id, now=NOW + timedelta(seconds=80))
        self.assertEqual(self.count('mock_effects'), 1)

    def test_rejected(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW, fixture=Fixture.REJECT)
        self.assertEqual(self.state(p), State.SIMULATED_REJECTED)
        self.assertTrue(self.app.verify().value['verified'])

    def test_timeout_unknown_manual_reconcile(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW, fixture=Fixture.TIMEOUT)
        self.assertEqual(self.state(p), State.UNKNOWN)
        self.app.dispatch(p.preview_id, now=NOW)
        self.reject('RECONCILIATION_REQUIRED', self.app.callback,
                    self.event(p, EventKind.FILLED, 2, 1000), now=NOW)
        self.reject('EXPLICIT_CONFIRMATION_REQUIRED', self.app.reconcile,
                    p.preview_id, now=NOW, user_confirmed=False)
        self.assertEqual(self.app.query(p.preview_id, now=NOW).value['outcome'], 'AVAILABLE')
        self.assertEqual(self.state(p), State.UNKNOWN)
        self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.state(p), State.SIMULATED_ACCEPTED)
        self.assertEqual(self.count('mock_effects'), 1)

    def test_unavailable_and_error_queries_remain_unresolved(self):
        for index, scenario in enumerate((Fixture.QUERY_UNAVAILABLE, Fixture.QUERY_ERROR)):
            draft, evidence = fixture()
            p = self.app.preview(replace(draft, client_request_id='q-' + str(index)), evidence, now=NOW).value
            self.app.confirm(confirmation(p), now=NOW)
            self.app.dispatch(p.preview_id, now=NOW, fixture=scenario)
            self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
            self.assertEqual(self.state(p), State.RECONCILING)
            self.assertEqual(self.app.query(p.preview_id, now=NOW).value['outcome'],
                             'ERROR' if scenario is Fixture.QUERY_ERROR else 'UNAVAILABLE')
            self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
            self.assertEqual(self.state(p), State.RECONCILING)

    def test_cancel_pending_cancelled_late_fill_and_restart(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.state(p), State.CANCEL_PENDING)
        self.app.dispatch(p.preview_id, now=NOW, kind='CANCEL', fixture=Fixture.CANCEL)
        self.assertEqual(self.state(p), State.SIMULATED_CANCELLED)
        self.app.callback(self.event(p, EventKind.PARTIAL_FILL, 3, 400), now=NOW)
        self.assertEqual(self.state(p), State.SIMULATED_CANCELLED)
        self.app.callback(self.event(p, EventKind.FILLED, 4, 1000), now=NOW)
        self.app = SimulationApplication(self.box)
        self.assertEqual(self.state(p), State.SIMULATED_FILLED)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, now=NOW, kind='CANCEL', fixture=Fixture.CANCEL)
        self.assertEqual(self.count('mock_effects'), 2)

    def test_cancel_pending_fixture_and_timeout(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, now=NOW, kind='CANCEL', fixture=Fixture.CANCEL_PENDING)
        self.assertEqual(self.state(p), State.CANCEL_PENDING)
        self.app.timeout(p.preview_id, now=NOW)
        self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
        self.assertEqual(self.state(p), State.RECONCILING)

    def test_duplicate_out_of_order_conflicting_callbacks(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        event = self.event(p, EventKind.PARTIAL_FILL, 3, 400)
        self.app.callback(event, now=NOW)
        self.app = SimulationApplication(self.box)
        self.app.callback(event, now=NOW)
        self.app.callback(self.event(p, EventKind.ACCEPTED, 2), now=NOW)
        self.assertEqual(self.app.status(p.preview_id).value['order'].cumulative_filled, 400)
        self.reject('EVENT_ID_CONFLICT', self.app.callback, replace(event, cumulative_filled=500), now=NOW)
        self.reject('REPORT_SEQUENCE_CONFLICT', self.app.callback,
                    replace(event, event_id='conflict', cumulative_filled=500), now=NOW)
        self.assertTrue(self.app.verify().value['verified'])

    def test_unique_request_payload_and_evidence_conflicts(self):
        p = self.preview()
        self.assertEqual(self.app.preview(p.draft, p.evidence, now=NOW).value, p)
        self.reject('IDEMPOTENCY_CONFLICT', self.app.preview, replace(p.draft, quantity=2000), p.evidence, now=NOW)
        self.reject('EVIDENCE_CONFLICT', self.app.preview, p.draft,
                    replace(p.evidence, account=replace(p.evidence.account, available_cash=Decimal('900000'))), now=NOW)
        self.assertEqual(self.count('previews'), 1)

    def test_confirmation_tamper_expiry_and_atomic_consume(self):
        p = self.preview()
        c = confirmation(p)
        for altered, code in ((replace(c, user_confirmed=False), 'EXPLICIT_CONFIRMATION_REQUIRED'),
                              (replace(c, token='bad'), 'CHALLENGE_MISMATCH'),
                              (replace(c, digest='bad'), 'PAYLOAD_DIGEST_MISMATCH'),
                              (replace(c, principal_id='synthetic-other'), 'PRINCIPAL_MISMATCH')):
            self.reject(code, self.app.confirm, altered, now=NOW)
        self.assertEqual(self.count('outbox'), 0)
        self.reject('PREVIEW_EXPIRED', self.app.confirm, c, now=NOW + timedelta(seconds=60))
        self.assertEqual(self.count('confirmations'), 0)

    def test_two_owners_double_click_and_dispatch_race(self):
        p = self.preview()
        def run(_):
            app = SimulationApplication(self.box)
            app.confirm(confirmation(p), now=NOW)
            app.dispatch(p.preview_id, now=NOW)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(run, range(8)))
        self.assertEqual(self.count('confirmations'), 1)
        self.assertEqual(self.count('reservations'), 1)
        self.assertEqual(self.count('mock_effects'), 1)
        self.assertTrue(self.app.verify().value['verified'])

    def test_confirm_race_cannot_overreserve_cash(self):
        draft, evidence = fixture()
        evidence = replace(evidence, account=replace(evidence.account, available_cash=Decimal('30000')))
        previews = [self.app.preview(replace(draft, client_request_id='race-' + str(i)), evidence, now=NOW).value
                    for i in range(2)]
        def run(p):
            try:
                SimulationApplication(self.box).confirm(confirmation(p), now=NOW)
                return 'CONFIRMED'
            except ExecutionRejected as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, previews))
        self.assertCountEqual(results, ['CONFIRMED', 'INSUFFICIENT_CASH'])
        self.assertEqual(self.count('reservations'), 1)

    def test_delayed_worker_fenced_by_recovery_before_effect(self):
        p = self.confirmed()
        def recover_after_claim(actual, boundary):
            if boundary == 'after_claim':
                SimulationApplication(self.box).recover(p.preview_id, now=NOW)
        with patch.object(self.app, '_crash', side_effect=recover_after_claim):
            self.app.dispatch(p.preview_id, now=NOW)
        self.assertEqual(self.state(p), State.UNKNOWN)
        self.assertEqual(self.count('mock_effects'), 0)

    def test_ui_shaped_symbol_entirely_synthetic_e2e(self):
        draft, evidence = symbol_fixture('2330')
        self.assertEqual(draft.limit_price, Decimal('25.50'))
        p = self.app.preview(draft, evidence, now=NOW).value
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.callback(self.event(p, EventKind.PARTIAL_FILL, 2, 500), now=NOW)
        self.app.callback(self.event(p, EventKind.FILLED, 3, 1000), now=NOW)
        self.assertEqual(SimulationApplication(self.box).status(p.preview_id).value['order'].state,
                         State.SIMULATED_FILLED)
        self.assertTrue(self.app.verify().value['verified'])

    def test_real_process_crash_restart_and_no_resend(self):
        for crash in ('after_claim', 'after_effect'):
            with self.subTest(crash=crash), temporary_sandbox() as box:
                ticket = box.ticket()
                args = [sys.executable, '-B', '-m', 'execution_simulation.tests.process_worker',
                        ticket.directory, ticket.token]
                dead = subprocess.run(args + [crash], capture_output=True, text=True, timeout=20)
                self.assertEqual(dead.returncode, 73, dead.stderr)
                recovered = subprocess.run(args + ['recover'], capture_output=True, text=True, timeout=20)
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                app = SimulationApplication(box)
                draft, evidence = fixture()
                p = app.preview(draft, evidence, now=NOW).value
                result = app.status(p.preview_id).value
                self.assertEqual(result['commands'][0]['mock_effects'], 0 if crash == 'after_claim' else 1)
                self.assertEqual(result['order'].state,
                                 State.RECONCILING if crash == 'after_claim' else State.SIMULATED_ACCEPTED)

    def test_process_death_before_and_after_confirmation_commit(self):
        for crash in ('before_outbox', 'before_commit', 'after_commit'):
            with self.subTest(crash=crash), temporary_sandbox() as box:
                ticket = box.ticket()
                dead = subprocess.run([sys.executable, '-B', '-m', 'execution_simulation.tests.process_worker',
                                       ticket.directory, ticket.token, crash],
                                      capture_output=True, text=True, timeout=20)
                self.assertEqual(dead.returncode, 73, dead.stderr)
                app = SimulationApplication(box)
                draft, evidence = fixture()
                p = app.preview(draft, evidence, now=NOW).value
                self.assertEqual(app.status(p.preview_id).value['order'].state,
                                 State.SIMULATED_PENDING if crash == 'after_commit' else State.PREVIEWED)
                app.confirm(confirmation(p), now=NOW)
                app.dispatch(p.preview_id, now=NOW)
                self.assertEqual(app.status(p.preview_id).value['commands'][0]['mock_effects'], 1)
                self.assertTrue(app.verify().value['verified'])

    def test_unknown_before_claim_never_dispatches(self):
        p = self.confirmed()
        self.app.timeout(p.preview_id, now=NOW)
        self.reject('DISPATCH_STATE_BLOCKED', self.app.dispatch, p.preview_id, now=NOW)
        self.assertEqual(self.count('mock_effects'), 0)

    def test_later_noop_recover_completed_keeps_clock_audit_consistent(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.recover(p.preview_id, now=NOW + timedelta(seconds=1))
        self.assertEqual(self.state(p), State.SIMULATED_ACCEPTED)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_later_noop_timeout_unknown_keeps_clock_audit_consistent(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW, fixture=Fixture.TIMEOUT)
        self.app.timeout(p.preview_id, now=NOW + timedelta(seconds=1))
        self.assertEqual(self.state(p), State.UNKNOWN)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_later_noop_duplicate_cancel_keeps_clock_audit_consistent(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.cancel(p.preview_id, now=NOW + timedelta(seconds=1), user_confirmed=True)
        self.assertEqual(self.state(p), State.CANCEL_PENDING)
        self.assertEqual(self.count('outbox'), 2)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_cash_shared_across_different_symbols(self):
        first_draft, first_evidence = symbol_fixture('2330')
        second_draft, second_evidence = symbol_fixture('0050')
        first_evidence = replace(first_evidence, account=replace(first_evidence.account, available_cash=Decimal('30000')))
        second_evidence = replace(second_evidence, account=replace(second_evidence.account, available_cash=Decimal('30000')))
        first = self.app.preview(first_draft, first_evidence, now=NOW).value
        second = self.app.preview(replace(second_draft, client_request_id='etf-shaped'), second_evidence, now=NOW).value
        self.app.confirm(confirmation(first), now=NOW)
        self.reject('INSUFFICIENT_CASH', self.app.confirm, confirmation(second), now=NOW)

    def test_audit_tamper_detected_even_after_trigger_removed_by_test(self):
        self.confirmed()
        with connection(self.box) as db:
            db.execute('DROP TRIGGER immutable_audit_UPDATE')
            db.execute("UPDATE audit SET payload='{}' WHERE seq=1")
        self.reject('AUDIT_CHAIN_BROKEN', SimulationApplication, self.box)
        self.reject('AUDIT_CHAIN_BROKEN', self.app.audit)

    def test_corrupt_budget_and_clock_fail_closed(self):
        self.confirmed()
        with connection(self.box) as db:
            db.execute("UPDATE metadata SET value=? WHERE key='last_now'", (dumps(NOW + timedelta(days=1)),))
        self.reject('CLOCK_PROJECTION_MISMATCH', SimulationApplication, self.box)

    def test_confirmation_crashes_pre_and_post_outbox(self):
        p = self.preview()
        for point in ('before_outbox', 'before_commit'):
            with self.assertRaises(SimulatedCrash):
                self.app.confirm(confirmation(p), now=NOW, crash_at=point)
            self.app = SimulationApplication(self.box)
            for table in ('confirmations', 'outbox', 'reservations', 'orders'):
                self.assertEqual(self.count(table), 0)
        with self.assertRaises(SimulatedCrash):
            self.app.confirm(confirmation(p), now=NOW, crash_at='after_commit')
        self.app = SimulationApplication(self.box)
        self.app.confirm(confirmation(p), now=NOW)
        self.app.dispatch(p.preview_id, now=NOW)
        self.assertEqual(self.count('mock_effects'), 1)

    def test_dispatch_crashes_never_resend(self):
        for index, point in enumerate(('before_claim', 'after_claim', 'after_effect')):
            draft, evidence = fixture()
            p = self.app.preview(replace(draft, client_request_id='crash-' + str(index)), evidence, now=NOW).value
            self.app.confirm(confirmation(p), now=NOW)
            with self.assertRaises(SimulatedCrash):
                self.app.dispatch(p.preview_id, now=NOW, crash_at=point)
            self.app = SimulationApplication(self.box)
            self.app.recover(p.preview_id, now=NOW)
            self.app.dispatch(p.preview_id, now=NOW)
            if point == 'before_claim':
                self.assertEqual(self.state(p), State.SIMULATED_ACCEPTED)
            else:
                self.assertEqual(self.state(p), State.UNKNOWN)
                self.app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
                self.assertEqual(self.state(p), State.RECONCILING if point == 'after_claim' else State.SIMULATED_ACCEPTED)
            commands = self.app.status(p.preview_id).value['commands']
            self.assertEqual(commands[0]['mock_effects'], 0 if point == 'after_claim' else 1)

    def test_cash_and_sellable_reservations_across_orders(self):
        for side in (Side.BUY, Side.SELL):
            with temporary_sandbox() as box:
                app = SimulationApplication(box)
                draft, evidence = fixture(side=side)
                evidence = replace(evidence, account=replace(evidence.account,
                                   available_cash=Decimal('30000'), sellable_quantity=1000))
                first = app.preview(draft, evidence, now=NOW).value
                second = app.preview(replace(draft, client_request_id='request-2'), evidence, now=NOW).value
                app.confirm(confirmation(first), now=NOW)
                app.dispatch(first.preview_id, now=NOW, fixture=Fixture.REJECT)
                self.reject('INSUFFICIENT_CASH' if side is Side.BUY else 'INSUFFICIENT_SELLABLE',
                            app.confirm, confirmation(second), now=NOW)
                self.assertEqual(app.status(second.preview_id).value['order'].state, State.PREVIEWED)
                self.assertTrue(SimulationApplication(box).verify().value['verified'])

    def test_budget_reset_and_decimal_context_cannot_bypass_reservation(self):
        p = self.confirmed()
        evidence = replace(p.evidence, account=replace(p.evidence.account, available_cash=Decimal('2000000')))
        second = self.app.preview(replace(p.draft, client_request_id='new-budget'), evidence, now=NOW).value
        self.reject('BUDGET_BASELINE_CHANGED', self.app.confirm, confirmation(second), now=NOW)
        with localcontext() as ctx:
            ctx.prec = 2
            third = self.app.preview(replace(p.draft, client_request_id='low-precision'), p.evidence, now=NOW).value
            self.app.confirm(confirmation(third), now=NOW)
        self.assertTrue(self.app.verify().value['verified'])

    def test_readers_reopen_do_not_write_or_recover(self):
        p = self.confirmed()
        with self.assertRaises(SimulatedCrash):
            self.app.dispatch(p.preview_id, now=NOW, crash_at='after_claim')
        before = self.box.database.read_bytes()
        self.app = SimulationApplication(self.box)
        self.app.status(p.preview_id)
        self.app.audit()
        self.app.verify()
        self.assertEqual(self.box.database.read_bytes(), before)
        self.assertEqual(self.state(p), State.SIMULATED_PENDING)

    def test_immutable_history_mutable_projection_tamper_fail_closed(self):
        p = self.confirmed()
        self.app.dispatch(p.preview_id, now=NOW)
        with connection(self.box) as db:
            triggers = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
            self.assertNotIn('immutable_orders_UPDATE', triggers)
            for table in ('audit', 'outbox', 'outbox_events', 'mock_effects', 'reservations', 'budgets', 'confirmations'):
                for verb in ('UPDATE', 'DELETE'):
                    self.assertIn(f'immutable_{table}_{verb}', triggers)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('DELETE FROM ' + table)
            changed = replace(self.app.status(p.preview_id).value['order'], state=State.SIMULATED_FILLED)
            db.execute('UPDATE orders SET payload=? WHERE id=?', (dumps(changed), p.preview_id))
        self.reject('ORDER_PROJECTION_MISMATCH', SimulationApplication, self.box)
        self.reject('ORDER_PROJECTION_MISMATCH', self.app.status, p.preview_id)
        self.reject('ORDER_PROJECTION_MISMATCH', self.app.confirm, confirmation(p), now=NOW)

    def test_unknown_type_in_materialized_order_fails_closed(self):
        p = self.confirmed()
        value = json.loads(dumps(self.app.status(p.preview_id).value['order']))
        value['payload']['type'] = '__import__'
        with connection(self.box) as db:
            db.execute('UPDATE orders SET payload=?', (json.dumps(value),))
        self.reject('CORRUPT_LEDGER_PAYLOAD', SimulationApplication, self.box)
        self.reject('CORRUPT_LEDGER_PAYLOAD', self.app.status, p.preview_id)

    def test_untyped_enum_in_materialized_order_cannot_pass_dataclass_equality(self):
        p = self.confirmed()
        value = json.loads(dumps(self.app.status(p.preview_id).value['order']))
        value['payload']['fields']['state'] = 'SIMULATED_PENDING'
        with connection(self.box) as db:
            db.execute('UPDATE orders SET payload=?', (json.dumps(value),))
        self.reject('CORRUPT_LEDGER_PAYLOAD', SimulationApplication, self.box)

    def test_schema_version_rejected_without_migration(self):
        with connection(self.box) as db:
            db.execute('PRAGMA user_version=99')
        before = self.box.database.read_bytes()
        self.reject('NOT_SIMULATION_DATABASE', SimulationApplication, self.box)
        self.assertEqual(before, self.box.database.read_bytes())

    def test_flags_and_no_external_io(self):
        with patch('socket.socket', side_effect=AssertionError('NETWORK FORBIDDEN')), \
                patch('subprocess.Popen', side_effect=AssertionError('PROCESS FORBIDDEN')):
            p = self.confirmed()
            responses = (self.app.dispatch(p.preview_id, now=NOW), self.app.status(p.preview_id),
                         self.app.query(p.preview_id, now=NOW), self.app.audit(), self.app.verify())
        for response in responses:
            self.assertTrue(response.simulated)
            self.assertTrue(response.test_only)
            self.assertFalse(response.broker_connected)
            self.assertEqual(response.origin, 'SYNTHETIC')


class IsolationCodecTests(unittest.TestCase):
    def test_temporary_isolation_cleanup_and_arbitrary_path_denied(self):
        with temporary_sandbox() as one, temporary_sandbox() as two:
            first, second = one.database, two.database
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            with self.assertRaises(ExecutionRejected):
                SimulationApplication(str(second))
            fake = Sandbox(two.directory, two._lease)
            with self.assertRaises(ExecutionRejected):
                SimulationApplication(fake)
        self.assertFalse(first.parent.exists())
        self.assertFalse(second.parent.exists())
        with self.assertRaises(ExecutionRejected):
            SimulationApplication(one)

    def test_symlink_deny_before_sqlite_open(self):
        with temporary_sandbox() as box:
            with patch.object(Path, 'is_symlink', return_value=True), \
                    patch('sqlite3.connect', side_effect=AssertionError('MUST NOT OPEN')):
                with self.assertRaises(ExecutionRejected):
                    SimulationApplication(box)

    def test_physical_database_symlink_denied(self):
        with temporary_sandbox() as box:
            original = box.database
            target = box.directory / 'held.sqlite3'
            original.rename(target)
            try:
                original.symlink_to(target)
            except OSError as exc:
                target.rename(original)
                self.skipTest('Host does not permit creating test symlink: ' + str(exc.winerror if hasattr(exc, 'winerror') else exc.errno))
            try:
                with patch('sqlite3.connect', side_effect=AssertionError('MUST NOT OPEN')):
                    with self.assertRaises(ExecutionRejected):
                        SimulationApplication(box)
            finally:
                original.unlink()
                target.rename(original)

    def test_hardlinked_database_denied(self):
        with temporary_sandbox() as box:
            alias = box.directory / 'alias.sqlite3'
            alias.hardlink_to(box.database)
            with patch('sqlite3.connect', side_effect=AssertionError('MUST NOT OPEN')):
                with self.assertRaises(ExecutionRejected):
                    SimulationApplication(box)

    def test_reopen_ticket_and_arbitrary_database_denied(self):
        with temporary_sandbox() as box:
            ticket = box.ticket()
            with reopen_sandbox(ticket) as reopened:
                self.assertEqual(reopened.database, box.database)
            for bad in (SandboxTicket(ticket.directory, '0' * 64),
                        SandboxTicket(str(box.database), ticket.token),
                        SandboxTicket(str(box.directory.parent), ticket.token)):
                with self.assertRaises(ExecutionRejected), reopen_sandbox(bad):
                    self.fail('Invalid ticket opened')
            # A valid SQLite file alone, with no factory marker, grants no access.
            with patch('sqlite3.connect', side_effect=AssertionError('MUST NOT OPEN')):
                with self.assertRaises(ExecutionRejected), reopen_sandbox(SandboxTicket(str(box.database), ticket.token)):
                    self.fail('Arbitrary database opened')

    def test_codec_roundtrip_and_hostile_inputs(self):
        draft, evidence = fixture()
        self.assertEqual(loads(dumps((draft, evidence))), (draft, evidence))
        valid = json.loads(dumps(draft))
        variants = [dict(valid, version=2), dict(valid, version=True), dict(valid, schema='live'),
                    dict(valid, payload={'type': 'os.system', 'value': 'x'}),
                    dict(valid, payload={'type': ['Draft']}),
                    dict(valid, payload={'type': 'Draft', 'fields': {}})]
        boolean_quantity = json.loads(dumps(draft))
        boolean_quantity['payload']['fields']['quantity'] = True
        variants.append(boolean_quantity)
        for value in [json.dumps(x) for x in variants] + ['{', '{}', 'NaN', '{"version":1,"version":1}']:
            with self.subTest(value=value), self.assertRaises(ExecutionRejected) as caught:
                loads(value)
            self.assertEqual(caught.exception.code, 'CORRUPT_LEDGER_PAYLOAD')
