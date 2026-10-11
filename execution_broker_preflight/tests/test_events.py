from dataclasses import replace
from datetime import timedelta
import unittest

from execution_broker_preflight.events import State, normalize, requested
from execution_broker_preflight.tests.fixtures import NOW, ORDER, SCOPE, event


class EventTests(unittest.TestCase):
    def initial(self, complete=True):
        return requested(ORDER.request_id, SCOPE, 1, 12, complete_fill_history=complete)

    def accepted(self):
        return normalize(self.initial(), event("accepted"))

    def fill(self, state, qty, trade="fake-trade", **kwargs):
        return normalize(state, event("fill-" + trade, "Deal", "Success", trade_id=trade,
                                      deal_shares=qty, quantity_evidence="fake-shares-conversion", **kwargs))

    def cancel(self, state, status="Cancelled"):
        return normalize(state, event("final-cancel", "OrderStatus", status,
                                      cumulative_shares=state.cumulative_shares,
                                      quantity_evidence="fake-complete-ledger"))

    def test_requested_not_broker_accepted(self):
        self.assertEqual(self.initial().state, State.REQUESTED)
        self.assertIsNone(self.initial().order_id)
        self.assertIsNone(self.initial(False).cumulative_shares)

    def test_pending_seq_only_then_success_with_changed_seqno(self):
        pending = normalize(self.initial(), event("pending", status="Pending", order_id=None, seqno="pending-nid"))
        self.assertEqual(pending.state, State.PENDING)
        self.assertIsNone(pending.order_id)
        accepted = normalize(pending, event("accepted", seqno="different-success-seq"))
        self.assertEqual(accepted.state, State.ACCEPTED)
        self.assertEqual(accepted.seqnos, ("pending-nid", "different-success-seq"))

    def test_missing_and_contradictory_ids(self):
        for fixture in (event(order_id=None), event(status="Pending", order_id=None, seqno=None), event(order_id="")):
            self.assertEqual(normalize(self.initial(), fixture).state, State.UNKNOWN)
        state = normalize(self.accepted(), event("other", order_id="OTHER_ORDER"))
        self.assertEqual(state.state, State.UNKNOWN)
        self.assertEqual(state.order_id, "FAKE_ORDER")

    def test_scope_request_and_session_fencing(self):
        for fixture in (event(request_id="other"), event(generation=2), event(generation=True),
                        event(scope=replace(SCOPE, subaccount="other")), event(mode="LIVE")):
            self.assertEqual(normalize(self.initial(), fixture).state, State.UNKNOWN)

    def test_partial_full_and_report_status(self):
        state = self.fill(self.accepted(), 4)
        self.assertEqual((state.state, state.cumulative_shares), (State.PARTIAL, 4))
        state = normalize(state, event("partial-status", "OrderStatus", "PartFilled", cumulative_shares=4,
                                       quantity_evidence="fake-ledger"))
        self.assertEqual(state.state, State.PARTIAL)
        state = self.fill(state, 8, "second")
        self.assertEqual((state.state, state.cumulative_shares), (State.FILLED, 12))
        state = normalize(state, event("full-status", "OrderStatus", "Filled", cumulative_shares=12,
                                       quantity_evidence="fake-ledger"))
        self.assertEqual(state.state, State.FILLED)

    def test_cancel_pending_ack_and_final_are_different(self):
        state = normalize(self.accepted(), event("cancel-pending", "CancelOrder", "Pending"))
        state = normalize(state, event("cancel-ack", "CancelOrder", "Success"))
        self.assertEqual(state.state, State.CANCEL_PENDING)
        self.assertFalse(state.cancelled_remainder)
        state = self.cancel(state)
        self.assertEqual(state.state, State.CANCELLED)
        self.assertTrue(state.cancelled_remainder)

    def test_fill_during_cancel_and_part_cancel_final(self):
        state = normalize(self.accepted(), event("cancel", "CancelOrder", "Pending"))
        state = self.fill(state, 4)
        self.assertEqual((state.state, state.cumulative_shares), (State.CANCEL_PENDING, 4))
        state = self.cancel(state, "PartFilled_Cancelled")
        self.assertEqual((state.state, state.cumulative_shares), (State.CANCELLED, 4))

    def test_late_fill_after_cancel_preserves_fill_and_remainder(self):
        state = self.cancel(self.accepted())
        state = self.fill(state, 4, source_at=NOW - timedelta(seconds=2))
        self.assertEqual((state.state, state.cumulative_shares), (State.CANCELLED, 4))
        state = self.fill(state, 8, "second")
        self.assertEqual(state.state, State.FILLED)
        state = normalize(state, event("late-ack", "CancelOrder", "Success"))
        self.assertEqual((state.state, state.cumulative_shares), (State.FILLED, 12))

    def test_duplicate_event_rearrival_and_conflict(self):
        fixture = event("same")
        state = normalize(self.initial(), fixture)
        state = normalize(state, replace(fixture, arrival_at=NOW + timedelta(seconds=1)))
        self.assertEqual(state.state, State.ACCEPTED)
        self.assertIn("DUPLICATE_EVENT", state.reasons)
        state = normalize(state, replace(fixture, order_id="OTHER", arrival_at=NOW + timedelta(seconds=1)))
        self.assertEqual(state.state, State.UNKNOWN)

    def test_duplicate_trade_across_envelopes_does_not_double_count(self):
        state = self.fill(self.accepted(), 4)
        duplicate = event("other-envelope", "Deal", "Success", trade_id="fake-trade", deal_shares=4,
                          quantity_evidence="fake-shares-conversion")
        state = normalize(state, duplicate)
        self.assertEqual(state.cumulative_shares, 4)
        self.assertIn("DUPLICATE_TRADE", state.reasons)
        state = normalize(state, replace(duplicate, event_id="conflict", deal_shares=5))
        self.assertEqual(state.state, State.UNKNOWN)
        self.assertEqual(state.cumulative_shares, 4)

    def test_out_of_order_pending_and_status_do_not_regress(self):
        state = self.fill(self.accepted(), 4)
        state = normalize(state, event("late-pending", status="Pending", order_id=None,
                                       source_at=NOW - timedelta(seconds=2)))
        self.assertEqual(state.state, State.PARTIAL)
        late = event("old-status", "OrderStatus", "Submitted", cumulative_shares=4,
                     quantity_evidence="fake-ledger", source_at=NOW - timedelta(seconds=3))
        state = normalize(state, late)
        self.assertEqual(state.state, State.PARTIAL)

    def test_deal_missing_id_unit_history_or_cumulative_conflict(self):
        for fixture in (event(task="Deal", trade_id=None),
                        event(task="Deal", trade_id="t", deal_shares=1),
                        event(task="Deal", trade_id="t", deal_shares=True, quantity_evidence="fake")):
            self.assertEqual(normalize(self.accepted(), fixture).state, State.UNKNOWN)
        self.assertEqual(self.fill(self.initial(False), 4).state, State.UNKNOWN)
        self.assertEqual(self.fill(self.accepted(), 4, cumulative_shares=9).state, State.UNKNOWN)
        self.assertEqual(self.fill(self.accepted(), 13).state, State.UNKNOWN)

    def test_order_status_never_invents_quantities(self):
        for status in ("Submitted", "Filled", "PartFilled", "Cancelled", "PartFilled_Cancelled"):
            self.assertEqual(normalize(self.accepted(), event("s", "OrderStatus", status)).state, State.UNKNOWN)
        false_full = event("s", "OrderStatus", "Filled", cumulative_shares=0, quantity_evidence="fake")
        self.assertEqual(normalize(self.accepted(), false_full).state, State.UNKNOWN)

    def test_reject_errors_and_cancel_failure(self):
        rejected = normalize(self.initial(), event(status="Failed", order_id=None, error_code="FAKE_REJECT", message="synthetic denial"))
        self.assertEqual(rejected.state, State.REJECTED)
        self.assertEqual(rejected.events[-1].error_code, "FAKE_REJECT")
        self.assertEqual(self.fill(rejected, 4).state, State.UNKNOWN)
        self.assertEqual(normalize(self.accepted(), event("cancel-fail", "CancelOrder", "Failed")).state, State.UNKNOWN)
        self.assertEqual(normalize(self.initial(), event(error_code="FAKE_ERROR")).state, State.UNKNOWN)

    def test_unknown_sticky_and_absent_timestamp_preserved(self):
        state = normalize(self.initial(), event(task="UnknownTask", source_at=None, source_ts=None))
        state = normalize(state, event("good-ack"))
        self.assertEqual(state.state, State.UNKNOWN)
        self.assertIsNone(state.events[0].source_at)
        self.assertIsNone(state.events[0].source_ts)

    def test_duplicate_trade_conflicting_cumulative_is_unknown(self):
        state = self.fill(self.accepted(), 4, cumulative_shares=4)
        fixture = event("duplicate-conflict", "Deal", "Success", trade_id="fake-trade", deal_shares=4,
                        cumulative_shares=5, quantity_evidence="fake-shares-conversion")
        self.assertEqual(normalize(state, fixture).state, State.UNKNOWN)

    def test_filled_has_no_cancelled_remainder(self):
        state = self.fill(self.cancel(self.accepted()), 12)
        self.assertEqual(state.state, State.FILLED)
        self.assertFalse(state.cancelled_remainder)

    def test_input_is_immutable_and_unsupported_updates_are_unknown(self):
        original = self.accepted()
        changed = normalize(original, event("update", "UpdateQty", "Success"))
        self.assertEqual(original.state, State.ACCEPTED)
        self.assertEqual(changed.state, State.UNKNOWN)

    def test_naive_future_and_arrival_regression(self):
        for fixture in (event(arrival_at=NOW.replace(tzinfo=None)),
                        event(source_at=NOW + timedelta(seconds=1)),
                        event("old", arrival_at=NOW - timedelta(seconds=1))):
            self.assertEqual(normalize(self.accepted(), fixture).state, State.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
