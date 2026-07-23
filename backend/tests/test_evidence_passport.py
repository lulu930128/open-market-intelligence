from __future__ import annotations

import unittest

from app.ai.evidence_passport import build_evidence_passport


class EvidencePassportTests(unittest.TestCase):
    def test_required_daily_trust_ignores_stale_fallback_provider_warning(self) -> None:
        passport = build_evidence_passport(
            kind="ai_ask",
            as_of="2026-07-17",
            source_refs=[{"type": "table", "name": "us_daily_price"}],
            missing=[],
            warnings=[
                "US fallback provider stale: daily_price via alphavantage - latest 2026-06-18"
            ],
            freshness={"is_current": True, "missing": [], "warnings": []},
            tool_runs=[],
            required_capabilities=("us_daily_price",),
        )

        self.assertEqual(passport["warnings"], [])
        self.assertEqual(len(passport["ignored_warnings"]), 1)
        self.assertEqual(passport["data_freshness"], "current")

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

    def test_minute_market_state_is_labeled_as_derived_evidence(self) -> None:
        passport = build_evidence_passport(
            kind="market_overview",
            as_of="2026-07-22T13:30:00+08:00",
            source_refs=[
                {"type": "table", "name": "taiwan_market_minute_state"}
            ],
            freshness={"is_current": True, "missing": [], "warnings": []},
        )

        self.assertEqual(passport["source_grade"], "derived")
        self.assertEqual(passport["source_breakdown"][0]["grade"], "derived")

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

    def test_question_required_capabilities_ignore_unrelated_failures(self) -> None:
        passport = build_evidence_passport(
            kind="us_index_context",
            as_of="2026-07-17",
            source_refs=[{"type": "table", "name": "us_daily_price"}],
            missing=["us_company_profile", "us_sec_company_fact"],
            warnings=[
                "US company profile cache is stale.",
                "SEC fundamental refresh failed.",
            ],
            freshness={"is_current": False, "refresh_recommended": True},
            tool_runs=[
                {"tool": "us.refresh_company_profile", "status": "failed"},
                {"tool": "us.refresh_sec_facts", "status": "blocked"},
            ],
            required_capabilities={"us_daily_price"},
        )

        self.assertEqual(passport["missing"], [])
        self.assertEqual(passport["warnings"], [])
        self.assertEqual(
            passport["ignored_missing"],
            ["us_company_profile", "us_sec_company_fact"],
        )
        self.assertEqual(passport["data_freshness"], "current")
        self.assertNotEqual(passport["trust_level"], "blocked")


if __name__ == "__main__":
    unittest.main()
