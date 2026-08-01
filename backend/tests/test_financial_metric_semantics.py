from __future__ import annotations

import unittest
from datetime import date, datetime
import json
from types import SimpleNamespace

from app.ai.evidence_builder import fundamental_evidence
from app.ai.market_context.taiwan_projection import (
    _build_stock_compact_evidence,
    _fundamentals_slot_status,
)
from app.market.financial_metric_semantics import source_reported_financial_semantics
from app.market.schemas import FinancialMetricQuarterlyRead
from app.parsers.financial_metrics import parse_financial_metrics_raw


class FinancialMetricSemanticsTests(unittest.TestCase):
    def test_q2_is_ytd_and_not_a_standalone_quarter(self) -> None:
        result = source_reported_financial_semantics(
            {"fiscal_year": 2025, "quarter": 2, "period": "2025Q2", "eps": 20.51}
        )

        self.assertEqual(result["period_scope"], "ytd")
        self.assertEqual(result["months_covered"], 6)
        self.assertEqual(result["raw_eps"], 20.51)
        self.assertIsNone(result["single_quarter_eps"])
        self.assertIsNone(result["ttm_eps"])
        self.assertEqual(result["valuation_status"], "blocked")
        self.assertIn("source_reported_eps_not_additive", result["normalization_warnings"])
        self.assertIn("share_basis_unverified", result["normalization_warnings"])

    def test_q4_is_annual_not_an_additive_quarter(self) -> None:
        result = source_reported_financial_semantics(
            {"fiscal_year": 2025, "quarter": 4, "period": "2025Q4", "eps": 11.51}
        )

        self.assertEqual(result["period_scope"], "annual")
        self.assertEqual(result["months_covered"], 12)
        self.assertEqual(result["eps_semantics"], "source_reported_annual")
        self.assertIsNone(result["single_quarter_eps"])

    def test_q1_can_equal_single_quarter_but_ttm_stays_blocked(self) -> None:
        result = source_reported_financial_semantics(
            {"fiscal_year": 2026, "quarter": 1, "period": "2026Q1", "eps": 3.9}
        )

        self.assertEqual(result["single_quarter_eps"], 3.9)
        self.assertEqual(result["normalization_status"], "raw_only")
        self.assertFalse(result["decision_usable"])
        self.assertIsNone(result["ttm_eps"])

    def test_api_schema_adds_compatible_semantic_fields(self) -> None:
        row = FinancialMetricQuarterlyRead.model_validate(
            {
                "id": 1,
                "source_id": 1,
                "raw_result_id": 1,
                "fiscal_year": 2025,
                "quarter": 3,
                "period": "2025Q3",
                "stock_id": "2327",
                "eps": 8.22,
                "created_at": datetime(2026, 7, 27),
                "updated_at": datetime(2026, 7, 27),
            }
        )

        self.assertEqual(row.period_scope, "ytd")
        self.assertEqual(row.months_covered, 9)
        self.assertEqual(row.raw_eps, 8.22)
        self.assertEqual(row.normalization_status, "raw_only")
        self.assertEqual(row.valuation_status, "blocked")

    def test_ai_evidence_exposes_scope_and_blocks_valuation(self) -> None:
        result = fundamental_evidence(
            latest_revenue=None,
            latest_financial={
                "fiscal_year": 2025,
                "quarter": 2,
                "period": "2025Q2",
                "eps": 20.51,
                "roe": 7.1,
            },
        )["financial"]

        self.assertEqual(result["period_scope"], "ytd")
        self.assertEqual(result["months_covered"], 6)
        self.assertEqual(result["tone"], "neutral")
        self.assertFalse(result["decision_usable"])
        self.assertIn("年初至今 6 個月", result["summary"])
        self.assertIn("不可直接推導單季、TTM 或估值", result["summary"])

    def test_openapi_output_date_is_not_company_release_date(self) -> None:
        raw_result = SimpleNamespace(
            id=2,
            source_id=1,
            url="https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
            raw_text=json.dumps(
                [
                    {
                        "出表日期": "1150727",
                        "年度": "115",
                        "季別": "1",
                        "公司代號": "2327",
                        "公司名稱": "國巨",
                        "基本每股盈餘（元）": "3.90",
                    }
                ],
                ensure_ascii=False,
            ),
        )

        rows, skipped = parse_financial_metrics_raw(raw_result)

        self.assertEqual(skipped, 0)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["report_date"])
        self.assertIsNone(rows[0]["released_at"])
        self.assertIsNone(rows[0]["filed_at"])

    def test_public_fundamentals_slot_is_partial_until_normalized(self) -> None:
        status = _fundamentals_slot_status(
            {
                "latest_revenue": {"period": "2026-06"},
                "latest_financial": {
                    "period": "2026Q1",
                    "normalization_status": "raw_only",
                },
            },
            missing=[],
        )

        self.assertEqual(status, "partial")

    def test_public_fundamentals_slot_uses_ready_backend_contract(self) -> None:
        status = _fundamentals_slot_status(
            {
                "latest_revenue": {"period": "2026-06"},
                "latest_financial": {
                    "period": "2026Q1",
                    "normalization_status": "raw_only",
                },
                "revenue_continuity": {
                    "status": "complete",
                    "decision_usable": True,
                },
                "financial_contract": {
                    "normalized": {"status": "ready"},
                    "quality": {"decision_usable": True},
                },
            },
            missing=[],
        )

        self.assertEqual(status, "ready")

    def test_public_compact_evidence_preserves_raw_semantics(self) -> None:
        latest_financial = SimpleNamespace(
            fiscal_year=2025,
            quarter=2,
            period="2025Q2",
            report_date=None,
            released_at=None,
            filed_at=None,
            revenue=55_553_865,
            gross_profit=18_234_567,
            operating_income=12_345_678,
            net_income=10_523_833,
            eps=20.51,
            book_value_per_share=110.0,
            roe=7.1,
            roa=4.2,
        )

        result = _build_stock_compact_evidence(
            stock=None,
            company_profile={},
            stock_id="2327",
            as_of="2026-07-30",
            latest_daily=None,
            latest_institutional=None,
            latest_margin=None,
            shareholding=[],
            branch_summary={},
            latest_revenue=SimpleNamespace(
                period=date(2026, 6, 1),
                monthly_revenue=10_000,
                month_over_month_pct=1.0,
                year_over_year_pct=2.0,
                cumulative_revenue=60_000,
                cumulative_year_over_year_pct=3.0,
            ),
            revenue_history=[
                SimpleNamespace(
                    period=date(2026, month, 1),
                    monthly_revenue=10_000 * month,
                    month_over_month_pct=1.0,
                    year_over_year_pct=2.0,
                    cumulative_revenue=10_000 * month,
                    cumulative_year_over_year_pct=3.0,
                )
                for month in (1, 2, 3, 4, 6)
            ],
            latest_financial=latest_financial,
            financial_history=[latest_financial],
            technical_reports={},
            technical_analysis={},
            technical_levels={},
            quote={},
            intraday_bars={},
            source_health={},
            overnight_impact=None,
            event_context=None,
            missing=[],
            warnings=[],
            source_refs=[],
        )

        latest = result["fundamentals"]["latest_financial"]
        self.assertEqual(latest["period_scope"], "ytd")
        self.assertEqual(latest["months_covered"], 6)
        self.assertEqual(latest["raw_eps"], 20.51)
        self.assertIsNone(latest["single_quarter_eps"])
        self.assertIsNone(latest["ttm_eps"])
        self.assertEqual(latest["valuation_status"], "blocked")
        self.assertFalse(latest["decision_usable"])
        self.assertEqual(
            result["fundamentals"]["revenue_continuity"]["status"],
            "interior_gap",
        )
        self.assertEqual(
            result["fundamentals"]["revenue_continuity"]["missing_periods"],
            ["2026-05"],
        )
        self.assertIn(
            "monthly_revenue_missing_2026_05",
            result["data_quality"]["warnings"],
        )
        self.assertEqual(
            result["fundamentals"]["financial_contract"]["contract_version"],
            "omi.financial.v1",
        )
        self.assertEqual(
            result["fundamentals"]["financial_contract"]["derived"]["ttm_eps_status"],
            "blocked",
        )
        self.assertFalse(
            result["fundamentals"]["financial_contract"]["quality"][
                "decision_usable"
            ]
        )
        self.assertEqual(result["slots"]["fundamentals"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
