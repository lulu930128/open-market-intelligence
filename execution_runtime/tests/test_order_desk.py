"""Phase 4 contract fixtures exercise Phase 2/3 owners, never native SDK."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from .order_desk_fake import OrderDeskFake, STEPS


class OrderDeskTests(unittest.TestCase):
    def setUp(self):
        self.fixture = OrderDeskFake()

    def tearDown(self):
        self.fixture.close()

    def pending(self):
        return next(r for r in self.fixture.read()["reviews"] if r["state"] == "PREVIEW")

    def test_pure_read_has_no_broker_query_and_both_spaces(self):
        count = self.fixture.sdk.query_count
        with patch.object(self.fixture.app, "query", side_effect=AssertionError("read must stay local")):
            value = self.fixture.read()
        self.assertEqual(count, self.fixture.sdk.query_count)
        self.assertEqual({"USER_SPACE", "AGENT_SPACE"}, {r["draft"]["command"]["space_id"] for r in value["reviews"]})
        self.assertEqual(("FAKE_ONLY", "NOT_DEPLOYED"), (value["mode"], value["live_broker"]))
        json.dumps(value, allow_nan=False)

    def test_revise_invalidates_old_confirm_and_preview_then_exact_confirm(self):
        old = self.pending()
        draft = deepcopy(old["draft"])
        draft["command"]["quantity"] = 80
        self.fixture.dispatch({"type": "revise", "review_id": old["review_id"], "expected_revision": 1, "draft": draft})
        with self.assertRaisesRegex(ValueError, "STALE_REVIEW_REVISION"):
            self.fixture.dispatch({"type": "confirm", "review_id": old["review_id"], "expected_revision": 1,
                                   "expected_digest": old["snapshot"]["digest"]})
        with self.assertRaisesRegex(ValueError, "REVIEW_NOT_CONFIRMABLE"):
            self.fixture.dispatch({"type": "confirm", "review_id": old["review_id"], "expected_revision": 2,
                                   "expected_digest": old["snapshot"]["digest"]})
        current = self.fixture.dispatch({"type": "preview", "review_id": old["review_id"], "expected_revision": 2})
        with self.assertRaisesRegex(ValueError, "REVIEW_DIGEST_MISMATCH"):
            self.fixture.dispatch({"type": "confirm", "review_id": old["review_id"], "expected_revision": 2,
                                   "expected_digest": old["snapshot"]["digest"]})
        confirm = {"type": "confirm", "review_id": old["review_id"], "expected_revision": 2,
                   "expected_digest": current["snapshot"]["digest"]}
        self.fixture.dispatch(confirm)
        self.fixture.dispatch(confirm)
        self.assertEqual(2, len(self.fixture.sdk.broker.attempts))  # seed + exactly one new order

    def test_exact_cancel_duplicate_ack_is_not_final_and_wrong_identity_rejected(self):
        entry = self.fixture.read()["strategies"][0]["entry"]
        key = {"account_id": "fixture-account", "trade_date": entry["trade_date"], "order_id": entry["broker_order_id"]}
        for field, bad in (("account_id", "wrong"), ("trade_date", "2026-10-28"), ("order_id", "wrong")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.fixture.dispatch({"type": "cancel", "execution_id": entry["execution_id"], "key": {**key, field: bad}})
        cancel = {"type": "cancel", "execution_id": entry["execution_id"], "key": key}
        self.fixture.dispatch(cancel)
        result = self.fixture.dispatch(cancel)
        self.assertEqual([entry["broker_order_id"]], self.fixture.sdk.broker.cancels)
        self.assertEqual("ACK_ONLY", result["cancel_stage"])
        self.assertNotEqual("CANCELLED", result["state"])

    def test_full_scenario_quantities_and_finality(self):
        trace = []
        for step in STEPS:
            trace.append(self.fixture.dispatch({"type": "fake_step", "step": step}))
        self.assertEqual(60, trace[0]["entry_filled"])
        self.assertEqual([60], [x["quantity"] for x in trace[1]["exits"]])
        self.assertEqual("ACK_ONLY", trace[1]["entry"]["cancel_stage"])
        self.assertEqual(40, trace[1]["entry_remaining"])
        self.assertNotEqual("CLOSED", trace[2]["state"])
        self.assertEqual(15, trace[3]["effective_position"])
        self.assertEqual([60, 15], [x["quantity"] for x in trace[3]["exits"]])
        self.assertNotEqual("CLOSED", trace[4]["state"])
        self.assertEqual(("CLOSED", 0, 0, 0), tuple(trace[5][k] for k in
            ("state", "entry_remaining", "effective_position", "reserved_exit_quantity")))
        self.assertTrue(self.fixture.runtime.verify())

    def test_snapshot_partial_unavailable_keep_known_orders(self):
        for status in ("PARTIAL", "UNAVAILABLE", "AVAILABLE"):
            result = self.fixture.dispatch({"type": "fake_snapshot", "status": status})
            self.assertEqual(status, result["status"])
            self.assertEqual(1, len(self.fixture.read()["strategies"]))
        self.assertFalse(result["fill_history_complete"])

    def test_strategy_revision_uses_exact_selector_and_keeps_command_snapshot(self):
        before = self.fixture.read()
        strategy = before["strategies"][0]
        review = next(r for r in before["reviews"] if r["review_id"] == strategy["review_id"])
        request = {"type": "revise_strategy", "strategy_id": strategy["strategy_id"], "expected_revision": 1,
            "request_id": "ui-edit", "rules": {**strategy["rules"], "stop_loss": "485"},
            "source": {k: strategy["source_snapshot"][k] for k in ("source_id", "observed_at", "content")}}
        result = self.fixture.dispatch(request)
        self.assertEqual(2, result["strategy_revision"])
        self.assertEqual(review["snapshot"], self.fixture.app.status(review["review_id"])["snapshot"])
        with self.assertRaisesRegex(ValueError, "STALE_STRATEGY_REVISION"):
            self.fixture.dispatch({**request, "request_id": "ui-stale"})
        with self.assertRaises(ValueError):
            self.fixture.dispatch({**request, "expected_revision": 2, "quantity": 200})

    def test_reject_never_submits_and_invalid_commands_do_not_mutate(self):
        review = self.pending()
        count = len(self.fixture.sdk.broker.attempts)
        self.fixture.dispatch({"type": "reject", "review_id": review["review_id"], "expected_revision": 1, "reason": "USER_REJECTED"})
        self.assertEqual("REJECTED", self.fixture.app.status(review["review_id"])["state"])
        for body in ({"type": "submit"}, {"type": "cancel_all"}, {"type": "query", "provider": "live"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.fixture.dispatch(body)
        self.assertEqual(count, len(self.fixture.sdk.broker.attempts))

    def test_unknown_retains_claim_and_never_replays(self):
        review = self.pending()
        self.fixture.dispatch({"type": "fake_submit_unknown"})
        confirm = {"type": "confirm", "review_id": review["review_id"], "expected_revision": 1,
                   "expected_digest": review["snapshot"]["digest"]}
        result = self.fixture.dispatch(confirm)
        self.assertEqual("UNKNOWN", result["execution"]["state"])
        self.assertIsNone(result["execution"]["broker_order_id"])
        self.fixture.dispatch(confirm)
        self.assertEqual(2, len(self.fixture.sdk.broker.attempts))


if __name__ == "__main__":
    unittest.main()
