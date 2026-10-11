from dataclasses import replace
from datetime import timedelta
import unittest

from execution.contracts import ExecutionRejected
from execution.validation import assess, digest_of
from .fixtures import NOW, fixture


class ReceiptTimeTests(unittest.TestCase):
    def test_optional_legacy_receipt_preserves_digest(self):
        draft, e = fixture()
        same = replace(e, market=replace(e.market, ref=replace(e.market.ref, received_at=None)))
        self.assertEqual(digest_of(e), digest_of(same))
        self.assertEqual(assess(draft, e, NOW), assess(draft, same, NOW))

    def test_receipt_time_is_bound_and_never_freshens_source(self):
        draft, e = fixture()
        current = replace(e, market=replace(e.market, ref=replace(e.market.ref, received_at=NOW)))
        self.assertNotEqual(digest_of(e), digest_of(current))
        assess(draft, current, NOW)
        with self.assertRaises(ExecutionRejected):
            assess(draft, current, NOW + timedelta(seconds=121))

    def test_receipt_order_future_naive_and_invalid_origin_denied(self):
        draft, e = fixture()
        for change in ({'received_at': NOW + timedelta(seconds=1)},
                       {'received_at': NOW - timedelta(seconds=2)},
                       {'received_at': NOW.replace(tzinfo=None)},
                       {'received_at': 'today'}, {'origin': 'REAL_SIM'}):
            with self.subTest(change=change), self.assertRaises(ExecutionRejected):
                assess(draft, replace(e, market=replace(e.market, ref=replace(e.market.ref, **change))), NOW)
