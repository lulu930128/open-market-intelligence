from dataclasses import replace
from datetime import timedelta
import unittest

from execution.contracts import ExecutionRejected, State
from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import temporary_sandbox, connection
from execution_kgi_simulator.fake import FakeSDK, FixtureQuantityUnits
from execution_kgi_simulator.wire import fixture_quantity, send_fixture


class UnitMetadataTests(unittest.TestCase):
    def test_each_surface_requires_explicit_nonboolean_metadata(self):
        sdk = FakeSDK()
        for surface in ('order', 'query', 'modified_quantity', 'deal'):
            self.assertEqual(fixture_quantity(sdk, surface, 2), 2000)
            for invalid in (None, True, 0, -1, 1.5):
                sdk.quantity_units = replace(FixtureQuantityUnits(1000, 1000, 1000, 1000), **{surface: invalid})
                with self.assertRaises(ExecutionRejected):
                    fixture_quantity(sdk, surface, 2)
            sdk.quantity_units = FixtureQuantityUnits(1000, 1000, 1000, 1000)
        sdk.quantity_units = None
        with self.assertRaises(ExecutionRejected):
            fixture_quantity(sdk, 'order', 1)

    def test_surface_quantity_overflow_unknown_and_real_sdk_denied(self):
        sdk = FakeSDK()
        for value in (True, -1, 1.0, '1', 1_000_000_000):
            with self.assertRaises(ExecutionRejected):
                fixture_quantity(sdk, 'deal', value)
        with self.assertRaises(ExecutionRejected):
            fixture_quantity(sdk, 'inferred', 1)
        with self.assertRaises(ExecutionRejected):
            fixture_quantity(object(), 'order', 1)


class FinalEffectChecks(unittest.TestCase):
    def setUp(self):
        self.scope = temporary_sandbox()
        self.box = self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)
        draft, evidence = fixture()
        self.p = self.app.preview(draft, evidence, now=NOW).value
        self.app.confirm(confirmation(self.p), now=NOW)
        self.app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
        self.sdk = FakeSDK(self.outside_transaction)

    def outside_transaction(self):
        with connection(self.box) as db:
            db.execute('BEGIN IMMEDIATE')
            db.rollback()

    def claim(self):
        return self.app.rehearsal_claim(self.p.preview_id, kind='SEND', generation='worker',
            digest=self.p.challenge.digest, request_id='send', now=NOW).value

    def test_kill_between_claim_and_effect_prevents_fixture_call(self):
        def hook(actual, boundary):
            if boundary == 'after_claim':
                self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        self.app._crash = hook
        with self.assertRaises(ExecutionRejected) as caught:
            send_fixture(self.app, self.p, self.sdk, 'worker', now=NOW)
        self.assertEqual(caught.exception.code, 'KILL_SWITCH_ACTIVE')
        self.assertEqual(self.sdk.Order.calls, [])
        self.app.rehearsal_fence('worker', now=NOW)
        self.assertIs(self.app.status(self.p.preview_id).value['order'].state, State.UNKNOWN)

    def test_fence_between_claim_and_effect_denied(self):
        claim = self.claim()
        self.app.rehearsal_fence('worker', now=NOW)
        with self.assertRaises(ExecutionRejected):
            self.app.rehearsal_check_effect(claim, now=NOW)
        self.assertEqual(self.sdk.Order.calls, [])

    def test_expiry_clock_regression_and_read_purity(self):
        claim = self.claim()
        before = self.box.database.read_bytes()
        self.app.rehearsal_check_effect(claim, now=NOW)
        self.assertEqual(before, self.box.database.read_bytes())
        for stamp in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=61)):
            with self.assertRaises(ExecutionRejected):
                self.app.rehearsal_check_effect(claim, now=stamp)
        self.assertEqual(self.sdk.Order.calls, [])

    def test_missing_unit_proof_denied_before_claim(self):
        self.sdk.quantity_units = None
        with self.assertRaises(ExecutionRejected):
            send_fixture(self.app, self.p, self.sdk, 'worker', now=NOW)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE operation='REHEARSAL_CLAIM'").fetchone()[0], 0)
        self.assertEqual(self.sdk.Order.calls, [])
