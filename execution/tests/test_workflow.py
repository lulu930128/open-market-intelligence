from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import unittest

from execution.contracts import EventKind as K, ExecutionRejected, SimulationEvent, State
from execution.service import OfflineExecution
from execution.state_machine import transition
from execution.tests.fixtures import FIXTURE_KEY, NOW, confirmation, fixture, service


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.service = service()
        self.draft, self.evidence = fixture()
        self.preview = self.service.preview(self.draft, self.evidence, now=NOW)
        self.confirmation = confirmation(self.preview)

    def confirm(self, now=NOW):
        return self.service.confirm(self.preview, self.confirmation, now=now)

    def event(self, kind, *, seq=None, filled=0, event_id=None, at=NOW):
        return SimulationEvent(event_id or f"event-{kind.value}-{seq}", self.preview.preview_id,
                               kind, at, seq, filled)

    def apply(self, kind, *, now=NOW, **kwargs):
        return self.service.apply(self.event(kind, **kwargs), now=now)

    def rejects(self, code, action):
        with self.assertRaises(ExecutionRejected) as exc:
            action()
        self.assertEqual(exc.exception.code, code)

    def test_complete_manual_synthetic_lifecycle(self):
        self.assertTrue(self.preview.simulated)
        self.assertEqual(self.preview.challenge.action, "CONFIRM_SYNTHETIC_DRY_RUN")
        self.assertEqual(self.preview.evidence, self.evidence)
        self.assertEqual(self.preview.assessment.required_cash, D("25520"))
        self.assertEqual(self.preview.challenge.expires_at, NOW + timedelta(seconds=60))
        result = self.confirm()
        self.assertEqual(result.state, State.SIMULATED_PENDING)
        self.assertTrue(result.simulated)
        self.assertFalse(result.durable)
        self.assertEqual(result.simulation_attempts, 1)
        self.assertEqual(self.apply(K.ACCEPTED, seq=1).state, State.SIMULATED_ACCEPTED)
        self.assertEqual(self.apply(K.PARTIAL_FILL, seq=2, filled=200).state, State.SIMULATED_PARTIALLY_FILLED)
        result = self.apply(K.FILLED, seq=3, filled=1000)
        self.assertEqual((result.state, result.cumulative_filled), (State.SIMULATED_FILLED, 1000))

    def test_cannot_apply_reports_before_confirmation(self):
        for kind in (K.ACCEPTED, K.PARTIAL_FILL, K.FILLED, K.REJECTED, K.CANCELLED):
            self.rejects("CONFIRMATION_REQUIRED", lambda: self.apply(kind, seq=1))
        self.assertEqual(self.service.result(self.preview.preview_id).simulation_attempts, 0)

    def test_preflight_failure_is_audited_and_creates_no_request(self):
        draft = replace(self.draft, client_request_id="bad", quantity=-1)
        self.rejects("INVALID_QUANTITY", lambda: self.service.preview(draft, self.evidence, now=NOW))
        self.assertEqual(self.service.audit[-1].reason, "INVALID_QUANTITY")
        self.assertIsNone(self.service.audit[-1].preview_id)
        good = self.service.preview(replace(draft, quantity=1000), self.evidence, now=NOW)
        self.assertTrue(good.simulated)

    def test_duplicate_preview_returns_same_evidence_and_challenge(self):
        other = self.service.preview(self.draft, self.evidence, now=NOW + timedelta(seconds=1))
        self.assertIs(other, self.preview)
        self.assertEqual(self.service.audit[-1].reason, "IDEMPOTENT_PREVIEW")

    def test_same_key_changed_payload_conflicts_before_and_after_confirmation(self):
        for consumed in (False, True):
            if consumed:
                self.confirm()
            for changes in ({"quantity": 2000}, {"limit_price": D("26.00")}):
                self.rejects("IDEMPOTENCY_CONFLICT", lambda: self.service.preview(
                    replace(self.draft, **changes), self.evidence, now=NOW))
        self.assertEqual(self.service.result(self.preview.preview_id).simulation_attempts, 1)

    def test_same_request_cannot_refresh_evidence_or_extend_expiry(self):
        evidence = replace(self.evidence, account=replace(self.evidence.account, available_cash=D("999999")))
        self.rejects("EVIDENCE_CONFLICT", lambda: self.service.preview(self.draft, evidence, now=NOW))
        self.rejects("PREVIEW_EXPIRED", lambda: self.service.preview(
            self.draft, self.evidence, now=NOW + timedelta(seconds=60)))

    def test_confirmation_requires_intent_principal_token_and_digest(self):
        for changes, code in (
            ({"user_confirmed": False}, "EXPLICIT_CONFIRMATION_REQUIRED"),
            ({"user_confirmed": 1}, "EXPLICIT_CONFIRMATION_REQUIRED"),
            ({"user_confirmed": "true"}, "EXPLICIT_CONFIRMATION_REQUIRED"),
            ({"principal_id": "other"}, "PRINCIPAL_MISMATCH"),
            ({"preview_id": "other"}, "CHALLENGE_MISMATCH"),
            ({"token": "wrong"}, "CHALLENGE_MISMATCH"),
            ({"token": "非ASCII"}, "CHALLENGE_MISMATCH"),
            ({"token": None}, "CHALLENGE_MISMATCH"),
            ({"digest": "wrong"}, "PAYLOAD_DIGEST_MISMATCH"),
        ):
            with self.subTest(changes=changes):
                self.rejects(code, lambda: self.service.confirm(
                    self.preview, replace(self.confirmation, **changes), now=NOW))
        self.assertEqual(self.service.result(self.preview.preview_id).simulation_attempts, 0)

    def test_tampered_preview_payload_price_account_evidence_and_ttl(self):
        for preview in (
            replace(self.preview, draft=replace(self.draft, quantity=2000)),
            replace(self.preview, draft=replace(self.draft, quantity=1000.0)),
            replace(self.preview, draft=replace(self.draft, limit_price=D("26.00"))),
            replace(self.preview, draft=replace(self.draft, account_id="other")),
            replace(self.preview, evidence=replace(self.evidence, market=replace(self.evidence.market, tradable=False))),
            replace(self.preview, assessment=replace(self.preview.assessment, required_cash=D(0))),
            replace(self.preview, challenge=replace(self.preview.challenge, expires_at=NOW + timedelta(days=1))),
            replace(self.preview, created_at=NOW + timedelta(seconds=1)),
        ):
            with self.subTest(preview=preview.preview_id):
                self.rejects("PREVIEW_TAMPERED", lambda: self.service.confirm(preview, self.confirmation, now=NOW))

    def test_preview_expiry_is_exclusive(self):
        self.rejects("PREVIEW_EXPIRED", lambda: self.confirm(NOW + timedelta(seconds=60)))
        self.assertEqual(self.service.result(self.preview.preview_id).simulation_attempts, 0)

    def test_shortest_evidence_window_caps_challenge(self):
        for part_name in ("market", "account", "permission"):
            current = service()
            part = getattr(self.evidence, part_name)
            changed = replace(part, ref=replace(part.ref, valid_until=NOW + timedelta(seconds=2)))
            preview = current.preview(self.draft, replace(self.evidence, **{part_name: changed}), now=NOW)
            self.assertEqual(preview.challenge.expires_at, NOW + timedelta(seconds=2))
            self.rejects("PREVIEW_EXPIRED", lambda: current.confirm(
                preview, confirmation(preview), now=NOW + timedelta(seconds=2)))

    def test_confirm_retry_returns_current_receipt_without_second_attempt_even_after_expiry(self):
        self.confirm()
        self.apply(K.ACCEPTED, seq=1)
        result = self.confirm(NOW + timedelta(days=1))
        self.assertEqual(result.state, State.SIMULATED_ACCEPTED)
        self.assertEqual(result.simulation_attempts, 1)
        self.assertEqual(sum(e.reason == "SIMULATION_STARTED" for e in self.service.audit), 1)
        self.assertEqual(self.service.audit[-1].reason, "IDEMPOTENT_RECEIPT")

    def test_used_challenge_cannot_authorize_another_order_or_account(self):
        self.confirm()
        draft = replace(self.draft, client_request_id="request-2")
        preview = self.service.preview(draft, self.evidence, now=NOW)
        self.rejects("CHALLENGE_MISMATCH", lambda: self.service.confirm(
            preview, replace(confirmation(preview), token=self.confirmation.token), now=NOW))
        draft = replace(self.draft, account_id="account-2")
        evidence = replace(self.evidence, account=replace(self.evidence.account, account_id="account-2"),
                           permission=replace(self.evidence.permission, account_id="account-2"))
        other = self.service.preview(draft, evidence, now=NOW)
        self.assertNotEqual(other.preview_id, self.preview.preview_id)
        self.rejects("CHALLENGE_MISMATCH", lambda: self.service.confirm(
            other, replace(confirmation(other), token=self.confirmation.token), now=NOW))

    def test_rejected_fixture_is_terminal_without_claiming_broker_submission(self):
        self.confirm()
        result = self.apply(K.REJECTED, seq=1)
        self.assertEqual(result.state, State.SIMULATED_REJECTED)
        self.assertTrue(result.simulated)
        self.rejects("TERMINAL_STATE", lambda: self.apply(K.TIMEOUT))
        self.assertEqual(self.confirm().simulation_attempts, 1)

    def test_timeout_requires_explicit_reconciliation_and_does_not_retry(self):
        self.confirm()
        self.assertEqual(self.apply(K.TIMEOUT).state, State.UNKNOWN)
        self.assertEqual(self.confirm().state, State.UNKNOWN)
        self.rejects("RECONCILIATION_REQUIRED", lambda: self.apply(K.ACCEPTED, seq=1))
        self.assertEqual(self.apply(K.RECONCILE).state, State.RECONCILING)
        self.assertEqual(self.confirm().simulation_attempts, 1)
        result = self.apply(K.ACCEPTED, seq=1)
        self.assertEqual(result.state, State.SIMULATED_ACCEPTED)
        self.assertEqual(result.simulation_attempts, 1)

    def test_reconciliation_can_resolve_late_full_fill_or_rejection(self):
        for kind, filled, expected in ((K.FILLED, 1000, State.SIMULATED_FILLED),
                                        (K.REJECTED, 0, State.SIMULATED_REJECTED)):
            self.setUp()
            self.confirm()
            self.apply(K.TIMEOUT)
            self.apply(K.RECONCILE)
            result = self.apply(kind, seq=1, filled=filled)
            self.assertEqual(result.state, expected)
            self.assertEqual(result.simulation_attempts, 1)

    def test_reconciliation_timeout_stays_unknown_without_dispatch(self):
        self.confirm()
        self.apply(K.TIMEOUT)
        self.apply(K.RECONCILE)
        self.assertEqual(self.apply(K.TIMEOUT, event_id="second-timeout").state, State.UNKNOWN)
        self.assertEqual(self.confirm().simulation_attempts, 1)

    def test_cancel_unconfirmed_preview_consumes_challenge_without_simulating(self):
        result = self.apply(K.CANCEL_REQUESTED)
        self.assertEqual(result.state, State.SIMULATED_CANCELLED)
        self.assertEqual(result.simulation_attempts, 0)
        self.rejects("CHALLENGE_CONSUMED", self.confirm)
        self.rejects("CONFIRMATION_REQUIRED", lambda: self.apply(K.FILLED, seq=1, filled=1000))
        self.assertEqual(self.service.result(self.preview.preview_id).simulation_attempts, 0)

    def test_report_sequence_reuse_with_different_content_is_conflict(self):
        self.confirm()
        self.apply(K.ACCEPTED, seq=1)
        self.rejects("REPORT_SEQUENCE_CONFLICT", lambda: self.apply(K.FILLED, seq=1, filled=1000))
        self.assertEqual(self.service.result(self.preview.preview_id).state, State.SIMULATED_ACCEPTED)

    def test_cancel_pending_does_not_claim_cancelled_before_report(self):
        self.confirm()
        self.apply(K.ACCEPTED, seq=1)
        self.assertEqual(self.apply(K.CANCEL_REQUESTED).state, State.CANCEL_PENDING)
        partial = self.apply(K.PARTIAL_FILL, seq=2, filled=200)
        self.assertEqual((partial.state, partial.cumulative_filled), (State.CANCEL_PENDING, 200))
        result = self.apply(K.CANCELLED, seq=3, filled=200)
        self.assertEqual((result.state, result.cumulative_filled), (State.SIMULATED_CANCELLED, 200))

    def test_cancel_while_unknown_records_intent_and_requires_reconciliation(self):
        self.confirm()
        self.apply(K.TIMEOUT)
        result = self.apply(K.CANCEL_REQUESTED)
        self.assertEqual(result.state, State.UNKNOWN)
        self.assertTrue(result.cancel_requested)
        self.apply(K.RECONCILE)
        self.assertEqual(self.apply(K.ACCEPTED, seq=1).state, State.CANCEL_PENDING)
        self.assertEqual(self.apply(K.CANCELLED, seq=2).state, State.SIMULATED_CANCELLED)

    def test_cancel_timeout_reconciles_to_cancelled(self):
        self.confirm()
        self.apply(K.CANCEL_REQUESTED)
        self.apply(K.TIMEOUT)
        self.apply(K.RECONCILE)
        self.assertEqual(self.apply(K.CANCELLED, seq=1).state, State.SIMULATED_CANCELLED)

    def test_late_full_fill_wins_cancel_race_in_both_orders(self):
        self.confirm()
        self.apply(K.CANCEL_REQUESTED)
        self.apply(K.CANCELLED, seq=1)
        self.assertEqual(self.apply(K.FILLED, seq=2, filled=1000).state, State.SIMULATED_FILLED)
        self.setUp()
        self.confirm()
        self.apply(K.CANCEL_REQUESTED)
        self.apply(K.FILLED, seq=1, filled=1000)
        self.assertEqual(self.apply(K.CANCELLED, seq=2, filled=1000).state, State.SIMULATED_FILLED)

    def test_late_partial_fill_preserves_cancelled_remainder(self):
        self.confirm()
        self.apply(K.CANCEL_REQUESTED)
        self.apply(K.CANCELLED, seq=1)
        result = self.apply(K.PARTIAL_FILL, seq=2, filled=300)
        self.assertEqual((result.state, result.cumulative_filled), (State.SIMULATED_CANCELLED, 300))
        self.assertEqual(self.service.audit[-1].reason, "LATE_FILL_AFTER_CANCEL")

    def test_conflicting_terminal_evidence_forces_reconciliation(self):
        self.confirm()
        self.apply(K.REJECTED, seq=1)
        result = self.apply(K.FILLED, seq=2, filled=1000)
        self.assertEqual(result.state, State.RECONCILING)
        self.assertEqual(result.cumulative_filled, 1000)
        self.assertEqual(self.service.audit[-1].reason, "CONFLICTING_TERMINAL_REPORT")

    def test_duplicate_event_is_idempotent_and_mutation_conflicts(self):
        self.confirm()
        event = self.event(K.PARTIAL_FILL, seq=1, filled=100)
        first = self.service.apply(event, now=NOW)
        self.assertEqual(first, self.service.apply(event, now=NOW))
        self.assertEqual(self.service.audit[-1].reason, "DUPLICATE_EVENT")
        self.rejects("EVENT_ID_CONFLICT", lambda: self.service.apply(replace(event, cumulative_filled=200), now=NOW))

    def test_out_of_order_event_cannot_erase_fill_or_resurrect_order(self):
        self.confirm()
        self.apply(K.FILLED, seq=3, filled=1000)
        result = self.apply(K.ACCEPTED, seq=1)
        self.assertEqual((result.state, result.cumulative_filled), (State.SIMULATED_FILLED, 1000))
        self.assertEqual(self.service.audit[-1].reason, "OUT_OF_ORDER_IGNORED")

    def test_overfill_regression_invalid_report_and_identity_fail_closed(self):
        self.confirm()
        self.apply(K.PARTIAL_FILL, seq=1, filled=300)
        for event, code in (
            (self.event(K.FILLED, seq=2, filled=1001), "OVERFILL"),
            (self.event(K.PARTIAL_FILL, seq=2, filled=100), "FILL_REGRESSION"),
            (self.event(K.FILLED, seq=2, filled=999), "INVALID_REPORT"),
            (self.event(K.PARTIAL_FILL, seq=2, filled=1000), "INVALID_REPORT"),
            (self.event(K.ACCEPTED, seq=2, filled=300), "INVALID_REPORT"),
            (self.event(K.FILLED, seq=True, filled=1000), "INVALID_QUANTITY"),
            (self.event(K.TIMEOUT, seq=2), "INVALID_CONTROL"),
            (replace(self.event(K.FILLED, seq=2, filled=1000), preview_id="other"), "UNKNOWN_PREVIEW"),
        ):
            with self.subTest(code=code):
                self.rejects(code, lambda: self.service.apply(event, now=NOW))
        self.assertEqual(self.service.result(self.preview.preview_id).cumulative_filled, 300)

    def test_invalid_transitions_do_not_change_state(self):
        self.confirm()
        self.rejects("INVALID_TRANSITION", lambda: self.apply(K.RECONCILE))
        self.rejects("INVALID_TRANSITION", lambda: self.apply(K.CANCELLED, seq=1))
        self.assertEqual(self.service.result(self.preview.preview_id).state, State.SIMULATED_PENDING)

    def test_future_events_and_clock_regression_rejected(self):
        self.confirm()
        self.rejects("INVALID_EVENT_TIME", lambda: self.apply(K.ACCEPTED, seq=1, at=NOW + timedelta(seconds=1)))
        self.service.result(self.preview.preview_id)
        self.rejects("CLOCK_REGRESSION", lambda: self.confirm(NOW - timedelta(seconds=1)))

    def test_report_time_cannot_move_backwards_with_increasing_sequence(self):
        self.confirm()
        later = NOW + timedelta(seconds=10)
        self.apply(K.ACCEPTED, seq=1, at=later, now=later)
        self.rejects("REPORT_TIME_REGRESSION", lambda: self.apply(K.FILLED, seq=2, filled=1000, now=later))

    def test_result_read_is_pure_and_audit_has_no_challenge_token(self):
        before = self.service.audit
        self.service.result(self.preview.preview_id)
        self.assertIs(before, self.service.audit)
        self.confirm()
        self.apply(K.TIMEOUT)
        audit = self.service.audit
        self.assertEqual([e.sequence for e in audit], list(range(1, len(audit) + 1)))
        self.assertTrue(all(e.simulated for e in audit))
        self.assertNotIn(self.preview.challenge.token, repr(audit))
        self.assertEqual(audit[-1].digest, self.preview.challenge.digest)
        self.assertEqual(audit[-1].event.kind, K.TIMEOUT)

    def test_event_reducer_is_pure(self):
        from execution.contracts import OrderState
        order = OrderState(self.preview.preview_id, 1000, State.SIMULATED_PENDING, NOW)
        event = self.event(K.ACCEPTED, seq=1)
        first = transition(order, event, NOW)
        self.assertEqual(first, transition(order, event, NOW))
        self.assertEqual(order.state, State.SIMULATED_PENDING)
        self.assertEqual(order.events, ())

    def test_memory_loss_is_explicitly_not_durable(self):
        self.confirm()
        fresh = service()
        self.rejects("UNKNOWN_PREVIEW", lambda: fresh.result(self.preview.preview_id))
        self.assertFalse(self.service.result(self.preview.preview_id).durable)

    def test_fixture_configuration_is_bounded(self):
        for key in (b"short", "not-bytes", None):
            self.rejects("INVALID_FIXTURE_KEY", lambda: OfflineExecution(fixture_challenge_key=key))
        for ttl in (timedelta(0), timedelta(seconds=61), None):
            self.rejects("INVALID_PREVIEW_TTL", lambda: OfflineExecution(
                fixture_challenge_key=FIXTURE_KEY, preview_ttl=ttl))
