from __future__ import annotations

import unittest

from app.ai.evidence_passport import build_evidence_passport


class EvidencePassportTests(unittest.TestCase):
    def test_official_current_evidence_scores_high(self) -> None:
        passport = build_evidence_passport(
            kind="stock_context",
            as_of="2026-06-08",
            source_refs=[
                {"type": "table", "name": "market_daily_price"},
                {"type": "table", "name": "institutional_trade_daily"},
                {"type": "derived", "name": "app.market.technical_report"},
            ],
            freshness={"is_current": True, "missing": [], "warnings": []},
            analysis={"selected_confidence": "high"},
        )

        self.assertEqual(passport["trust_level"], "high")
        self.assertGreaterEqual(passport["trust_score"], 80)
        self.assertEqual(passport["data_freshness"], "current")
        self.assertEqual(passport["source_grade"], "official")
        self.assertTrue(passport["source_breakdown"])

    def test_mixed_stale_evidence_is_downgraded(self) -> None:
        passport = build_evidence_passport(
            kind="stock_context",
            as_of="2026-06-05",
            source_refs=[
                {"type": "table", "name": "market_daily_price"},
                {"type": "table", "name": "broker_branch_trade_daily"},
            ],
            missing=["broker_branch_trade_daily"],
            warnings=["US daily price cache is stale for the requested symbol."],
            freshness={"is_current": False, "refresh_recommended": True},
        )

        self.assertIn(passport["trust_level"], {"low", "blocked"})
        self.assertEqual(passport["source_grade"], "mixed")
        self.assertEqual(passport["data_freshness"], "stale")
        self.assertIn("broker_branch_trade_daily", passport["missing"])
        self.assertTrue(passport["quality_flags"])

    def test_critical_price_missing_caps_trust(self) -> None:
        passport = build_evidence_passport(
            kind="market_overview",
            source_refs=[{"type": "table", "name": "market_daily_price"}],
            missing=["market_daily_price"],
            warnings=["No market daily rows are available in the local database."],
        )

        self.assertLessEqual(passport["trust_score"], 35)
        self.assertIn(passport["trust_level"], {"low", "blocked"})
        self.assertEqual(passport["data_freshness"], "missing")


if __name__ == "__main__":
    unittest.main()
