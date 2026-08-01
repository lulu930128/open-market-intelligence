from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.market.financial_metric_normalization import (
    PerShareFinancialFact,
    ShareAdjustmentAction,
    calculate_pe_snapshot,
    calculate_return_ratio,
    calculate_ttm_eps,
    derive_single_quarter_eps,
    display_decimal,
    normalize_per_share_series,
    reconcile_annual_to_discrete,
)


def _fact(
    fact_id: str,
    fiscal_year: int,
    fiscal_quarter: int,
    value: str,
    *,
    stock_id: str = "2327",
    source_restated_status: str,
    share_basis_id: str = "2327-source-basis",
    period_scope: str | None = None,
    source_decimal_places: int | None = 2,
    adjustment_treatment: str = "automatic",
) -> PerShareFinancialFact:
    period_end = {
        1: date(fiscal_year, 3, 31),
        2: date(fiscal_year, 6, 30),
        3: date(fiscal_year, 9, 30),
        4: date(fiscal_year, 12, 31),
    }[fiscal_quarter]
    resolved_period_scope = period_scope or {
        1: "ytd_3m",
        2: "ytd_6m",
        3: "ytd_9m",
        4: "annual_12m",
    }[fiscal_quarter]
    return PerShareFinancialFact(
        fact_id=fact_id,
        stock_id=stock_id,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        metric_code="basic_eps",
        period_scope=resolved_period_scope,
        period_end=period_end,
        value=Decimal(value),
        unit="TWD_per_share",
        source_share_basis_id=share_basis_id,
        source_restated_status=source_restated_status,
        known_at=datetime(fiscal_year, min(fiscal_quarter * 3 + 2, 12), 15, tzinfo=timezone.utc),
        source_decimal_places=source_decimal_places,
        adjustment_treatment=adjustment_treatment,
    )


class FinancialMetricNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.split = ShareAdjustmentAction(
            action_id="2327-split-2025-08-22",
            stock_id="2327",
            action_type="share_split",
            effective_date=date(2025, 8, 22),
            adjustment_ratio=Decimal("4"),
            adjustment_purpose="per_share_financials",
            status="confirmed",
            known_at=datetime(2025, 5, 27, tzinfo=timezone.utc),
        )
        self.facts = (
            _fact("2327-2025Q1", 2025, 1, "10.77", source_restated_status="not_restated"),
            _fact("2327-2025Q2", 2025, 2, "20.51", source_restated_status="not_restated"),
            _fact("2327-2025Q3", 2025, 3, "8.22", source_restated_status="confirmed"),
            _fact("2327-2025Q4", 2025, 4, "11.51", source_restated_status="confirmed"),
            _fact("2327-2026Q1", 2026, 1, "3.90", source_restated_status="confirmed"),
        )

    def _normalized(self):
        return normalize_per_share_series(
            facts=self.facts,
            actions=(self.split,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )

    def test_yageo_share_basis_single_quarters_ttm_and_pe(self) -> None:
        normalized = self._normalized()
        self.assertEqual(
            [item.normalized_value for item in normalized],
            [
                Decimal("2.6925"),
                Decimal("5.1275"),
                Decimal("8.22"),
                Decimal("11.51"),
                Decimal("3.90"),
            ],
        )
        self.assertEqual(normalized[0].action_ids, ("2327-split-2025-08-22",))
        self.assertEqual(normalized[1].adjustment_factor, Decimal("4"))

        discrete = derive_single_quarter_eps(normalized)
        self.assertEqual(
            [item.value for item in discrete],
            [
                Decimal("2.6925"),
                Decimal("2.4350"),
                Decimal("3.0925"),
                Decimal("3.29"),
                Decimal("3.90"),
            ],
        )

        ttm = calculate_ttm_eps(discrete, end_period=(2026, 1))
        self.assertEqual(ttm.status, "ready")
        self.assertEqual(ttm.value, Decimal("12.7175"))
        self.assertEqual(
            ttm.input_fact_ids,
            (
                "2327-2025Q2",
                "2327-2025Q1",
                "2327-2025Q3",
                "2327-2025Q4",
                "2327-2026Q1",
            ),
        )
        self.assertEqual(display_decimal(ttm.value), Decimal("12.72"))

        pe = calculate_pe_snapshot(
            price=Decimal("456.5"),
            price_as_of=datetime(2026, 7, 30, 13, 30, tzinfo=timezone.utc),
            price_basis="official_close",
            ttm_eps=ttm,
        )
        self.assertEqual(pe.status, "ready")
        self.assertEqual(display_decimal(pe.value), Decimal("35.90"))

        reconciliation = reconcile_annual_to_discrete(
            annual_fact=normalized[3],
            discrete_quarters=discrete,
        )
        self.assertEqual(reconciliation.status, "ready")
        self.assertEqual(reconciliation.discrete_sum, Decimal("11.5100"))
        self.assertEqual(reconciliation.difference, Decimal("0.0000"))

    def test_official_discrete_q2_q3_are_preserved_and_annual_residual_reconciles(
        self,
    ) -> None:
        facts = (
            _fact(
                "2327-2025Q1",
                2025,
                1,
                "10.77",
                source_restated_status="not_restated",
            ),
            _fact(
                "2327-2025Q2-discrete",
                2025,
                2,
                "9.74",
                source_restated_status="not_restated",
                period_scope="discrete_3m",
            ),
            _fact(
                "2327-2025Q3-discrete",
                2025,
                3,
                "3.10",
                source_restated_status="confirmed",
                period_scope="discrete_3m",
            ),
            _fact(
                "2327-2025Q4",
                2025,
                4,
                "11.51",
                source_restated_status="confirmed",
            ),
            _fact(
                "2327-2026Q1",
                2026,
                1,
                "3.90",
                source_restated_status="confirmed",
            ),
        )
        normalized = normalize_per_share_series(
            facts=facts,
            actions=(self.split,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )
        discrete = derive_single_quarter_eps(normalized)

        self.assertEqual(
            [item.value for item in discrete],
            [
                Decimal("2.6925"),
                Decimal("2.435"),
                Decimal("3.10"),
                Decimal("3.2825"),
                Decimal("3.90"),
            ],
        )
        self.assertEqual(
            discrete[1].input_fact_ids,
            ("2327-2025Q2-discrete",),
        )
        self.assertEqual(
            discrete[3].input_fact_ids,
            (
                "2327-2025Q4",
                "2327-2025Q1",
                "2327-2025Q2-discrete",
                "2327-2025Q3-discrete",
            ),
        )
        reconciliation = reconcile_annual_to_discrete(
            annual_fact=normalized[3],
            discrete_quarters=discrete,
        )
        self.assertEqual(reconciliation.status, "ready")
        self.assertEqual(reconciliation.difference, Decimal("0.0000"))
        ttm = calculate_ttm_eps(discrete, end_period=(2026, 1))
        self.assertEqual(ttm.status, "ready")
        self.assertEqual(ttm.value, Decimal("12.7175"))

    def test_yageo_v3_prefers_restated_q1_and_q3_ytd_for_annual_residual(
        self,
    ) -> None:
        facts = (
            _fact(
                "2327-2025Q1-restated",
                2025,
                1,
                "2.69",
                source_restated_status="confirmed",
                adjustment_treatment="official_restated",
            ),
            _fact(
                "2327-2025Q2-discrete",
                2025,
                2,
                "9.74",
                source_restated_status="not_restated",
                period_scope="discrete_3m",
            ),
            _fact(
                "2327-2025Q2-ytd",
                2025,
                2,
                "20.51",
                source_restated_status="not_restated",
                period_scope="ytd_6m",
            ),
            _fact(
                "2327-2025Q3-discrete",
                2025,
                3,
                "3.10",
                source_restated_status="confirmed",
                period_scope="discrete_3m",
            ),
            _fact(
                "2327-2025Q3-ytd",
                2025,
                3,
                "8.22",
                source_restated_status="confirmed",
                period_scope="ytd_9m",
            ),
            _fact(
                "2327-2025Q4-annual",
                2025,
                4,
                "11.51",
                source_restated_status="confirmed",
            ),
            _fact(
                "2327-2026Q1",
                2026,
                1,
                "3.90",
                source_restated_status="confirmed",
            ),
        )
        normalized = normalize_per_share_series(
            facts=facts,
            actions=(self.split,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )
        discrete = derive_single_quarter_eps(normalized)

        self.assertEqual(
            [item.value for item in discrete],
            [
                Decimal("2.69"),
                Decimal("2.435"),
                Decimal("3.10"),
                Decimal("3.29"),
                Decimal("3.90"),
            ],
        )
        self.assertEqual(
            discrete[3].input_fact_ids,
            ("2327-2025Q4-annual", "2327-2025Q3-ytd"),
        )

        reconciliation = reconcile_annual_to_discrete(
            annual_fact=next(
                fact
                for fact in normalized
                if fact.period_scope == "annual_12m"
            ),
            discrete_quarters=discrete,
        )
        self.assertEqual(reconciliation.status, "ready")
        self.assertEqual(reconciliation.discrete_sum, Decimal("11.515"))
        self.assertEqual(reconciliation.difference, Decimal("0.005"))
        self.assertEqual(reconciliation.tolerance, Decimal("0.02625"))
        self.assertLessEqual(
            abs(reconciliation.difference),
            reconciliation.tolerance,
        )

        ttm = calculate_ttm_eps(discrete, end_period=(2026, 1))
        self.assertEqual(ttm.status, "ready")
        self.assertEqual(ttm.value, Decimal("12.725"))
        self.assertEqual(display_decimal(ttm.value), Decimal("12.73"))

        pe = calculate_pe_snapshot(
            price=Decimal("456.5"),
            price_as_of=datetime(2026, 7, 30, 13, 30, tzinfo=timezone.utc),
            price_basis="official_close",
            ttm_eps=ttm,
        )
        self.assertEqual(pe.status, "ready")
        self.assertEqual(display_decimal(pe.value), Decimal("35.87"))

    def test_confirmed_restatement_blocks_second_split_adjustment(self) -> None:
        restated_old_fact = _fact(
            "2327-2025Q1-restated",
            2025,
            1,
            "2.69",
            source_restated_status="confirmed",
        )
        result = normalize_per_share_series(
            facts=(restated_old_fact,),
            actions=(self.split,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )[0]

        self.assertEqual(result.normalization_status, "blocked")
        self.assertIsNone(result.normalized_value)
        self.assertIn("F003_double_adjustment_risk", result.issue_codes)

    def test_bank_official_restatement_preserves_source_precision_and_ytd_q4(
        self,
    ) -> None:
        capitalization = ShareAdjustmentAction(
            action_id="2801-stock-dividend-2025-08-06",
            stock_id="2801",
            action_type="earnings_capitalization",
            effective_date=date(2025, 8, 6),
            adjustment_ratio=Decimal("1.05"),
            adjustment_purpose="per_share_financials",
            status="confirmed",
            known_at=datetime(2025, 8, 6, tzinfo=timezone.utc),
        )
        facts = (
            _fact(
                "2801-2025Q1-restated",
                2025,
                1,
                "0.35",
                stock_id="2801",
                source_restated_status="confirmed",
                adjustment_treatment="official_restated",
            ),
            _fact(
                "2801-2025Q2-discrete",
                2025,
                2,
                "0.42",
                stock_id="2801",
                source_restated_status="not_restated",
                period_scope="discrete_3m",
            ),
            _fact(
                "2801-2025Q3-discrete",
                2025,
                3,
                "0.43",
                stock_id="2801",
                source_restated_status="not_restated",
                period_scope="discrete_3m",
            ),
            _fact(
                "2801-2025Q3-ytd",
                2025,
                3,
                "1.20",
                stock_id="2801",
                source_restated_status="not_restated",
                period_scope="ytd_9m",
            ),
            _fact(
                "2801-2025Q4",
                2025,
                4,
                "1.51",
                stock_id="2801",
                source_restated_status="not_restated",
            ),
            _fact(
                "2801-2026Q1",
                2026,
                1,
                "0.44",
                stock_id="2801",
                source_restated_status="not_restated",
            ),
        )
        normalized = normalize_per_share_series(
            facts=facts,
            actions=(capitalization,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2801-current-share-basis-2025-08-06",
        )
        discrete = derive_single_quarter_eps(normalized)

        self.assertEqual(
            [item.value for item in discrete],
            [
                Decimal("0.35"),
                Decimal("0.4"),
                Decimal("0.43"),
                Decimal("0.31"),
                Decimal("0.44"),
            ],
        )
        self.assertEqual(
            discrete[3].input_fact_ids,
            ("2801-2025Q4", "2801-2025Q3-ytd"),
        )
        q1 = next(
            item
            for item in normalized
            if item.source_fact_id == "2801-2025Q1-restated"
        )
        self.assertEqual(q1.normalized_value, Decimal("0.35"))
        self.assertEqual(q1.adjustment_factor, Decimal("1"))
        self.assertEqual(
            q1.action_ids,
            ("2801-stock-dividend-2025-08-06",),
        )

        annual = next(
            item
            for item in normalized
            if item.period_scope == "annual_12m"
        )
        reconciliation = reconcile_annual_to_discrete(
            annual_fact=annual,
            discrete_quarters=discrete,
        )
        self.assertEqual(reconciliation.difference, Decimal("-0.02"))
        self.assertGreaterEqual(
            reconciliation.tolerance,
            abs(reconciliation.difference),
        )
        self.assertEqual(reconciliation.status, "ready")

        ttm = calculate_ttm_eps(discrete, end_period=(2026, 1))
        self.assertEqual(ttm.status, "ready")
        self.assertEqual(ttm.value, Decimal("1.58"))

    def test_unknown_share_basis_blocks_normalization(self) -> None:
        unknown = _fact(
            "2327-2026Q1-unknown",
            2026,
            1,
            "3.90",
            source_restated_status="unknown",
            share_basis_id="",
        )
        result = normalize_per_share_series(
            facts=(unknown,),
            actions=(),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )[0]

        self.assertEqual(result.normalization_status, "blocked")
        self.assertIn("F002_share_basis_unverified", result.issue_codes)
        self.assertIn("F003_source_restatement_unknown", result.issue_codes)

    def test_missing_ytd_predecessor_blocks_discrete_and_ttm(self) -> None:
        normalized = self._normalized()
        without_q2 = tuple(
            item
            for item in normalized
            if not (item.fiscal_year == 2025 and item.fiscal_quarter == 2)
        )

        discrete = derive_single_quarter_eps(without_q2)
        q3 = next(
            item
            for item in discrete
            if item.fiscal_year == 2025 and item.fiscal_quarter == 3
        )
        self.assertEqual(q3.status, "blocked")
        self.assertIn("F007_previous_ytd_period_missing_or_duplicate", q3.issue_codes)

        ttm = calculate_ttm_eps(discrete, end_period=(2026, 1))
        self.assertEqual(ttm.status, "blocked")
        self.assertIsNone(ttm.value)
        self.assertIn("F007_ttm_period_missing_or_duplicate", ttm.issue_codes)

    def test_point_in_time_mode_rejects_future_known_fact(self) -> None:
        result = normalize_per_share_series(
            facts=(self.facts[0],),
            actions=(self.split,),
            target_basis_date=date(2025, 8, 22),
            comparison_basis_id="2327-basis-as-of-2025-04-01",
            mode="as_reported_as_of",
            as_of=datetime(2025, 4, 1, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(result.normalization_status, "blocked")
        self.assertIn("fact_not_known_as_of", result.issue_codes)

    def test_informational_cash_dividend_never_changes_per_share_factor(self) -> None:
        dividend = ShareAdjustmentAction(
            action_id="2327-cash-dividend-2025",
            stock_id="2327",
            action_type="cash_dividend",
            effective_date=date(2025, 7, 1),
            adjustment_ratio=Decimal("0.9"),
            adjustment_purpose="informational_only",
            status="confirmed",
            known_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        )
        current = self.facts[-1]
        result = normalize_per_share_series(
            facts=(current,),
            actions=(dividend,),
            target_basis_date=date(2026, 3, 31),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
        )[0]

        self.assertEqual(result.adjustment_factor, Decimal("1"))
        self.assertEqual(result.normalized_value, Decimal("3.90"))
        self.assertEqual(result.action_ids, ())

    def test_return_ratio_uses_average_balance_and_explicit_annualization(self) -> None:
        period_roe = calculate_return_ratio(
            metric_code="roe",
            numerator=Decimal("120"),
            beginning_denominator=Decimal("900"),
            ending_denominator=Decimal("1100"),
            period_months=6,
            annualized=False,
        )
        annualized_roe = calculate_return_ratio(
            metric_code="roe",
            numerator=Decimal("120"),
            beginning_denominator=Decimal("900"),
            ending_denominator=Decimal("1100"),
            period_months=6,
            annualized=True,
        )

        self.assertEqual(period_roe.status, "ready")
        self.assertEqual(period_roe.value_percent, Decimal("12.00"))
        self.assertFalse(period_roe.annualized)
        self.assertEqual(annualized_roe.value_percent, Decimal("24.00"))
        self.assertTrue(annualized_roe.annualized)

    def test_return_ratio_blocks_missing_beginning_balance(self) -> None:
        result = calculate_return_ratio(
            metric_code="roa",
            numerator=Decimal("120"),
            beginning_denominator=None,
            ending_denominator=Decimal("1100"),
            period_months=3,
            annualized=True,
        )

        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.value_percent)
        self.assertIn("return_ratio_average_denominator_missing", result.issue_codes)


if __name__ == "__main__":
    unittest.main()
