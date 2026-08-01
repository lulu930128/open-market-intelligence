from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    FinancialMetricQuarterly,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_ci_rollout import (
    build_ci_rollout_plan,
    parse_financial_bundle_variant,
    run_ci_filing_ingestion_batch,
    select_ci_acceptance_sample,
)


def _bundle(*, income: list[dict], balance: list[dict]) -> str:
    return json.dumps(
        {
            "income_ci": {"raw_text": json.dumps(income, ensure_ascii=False)},
            "balance_ci": {"raw_text": json.dumps(balance, ensure_ascii=False)},
        },
        ensure_ascii=False,
    )


class FinancialCiBundleTests(unittest.TestCase):
    def test_extracts_union_and_surfaces_statement_mismatch(self) -> None:
        parsed = parse_financial_bundle_variant(
            _bundle(
                income=[
                    {"公司代號": "2330", "公司名稱": "台積電"},
                    {"公司代號": "2303", "公司名稱": "聯電"},
                    {"公司代號": "", "公司名稱": "空白列"},
                ],
                balance=[
                    {"公司代號": "2330", "公司名稱": "台積電"},
                    {"公司代號": "2454", "公司名稱": "聯發科"},
                ],
            )
        )

        self.assertEqual(parsed["symbols"], ["2303", "2330", "2454"])
        self.assertEqual(parsed["income_only"], ["2303"])
        self.assertEqual(parsed["balance_only"], ["2454"])
        self.assertIn(
            "bundle_statement_coverage_mismatch",
            {item["code"] for item in parsed["issues"]},
        )
        self.assertIn(
            "bundle_rows_without_valid_stock_id",
            {item["code"] for item in parsed["issues"]},
        )

    def test_accepts_tpex_english_identity_fields(self) -> None:
        parsed = parse_financial_bundle_variant(
            _bundle(
                income=[
                    {
                        "SecuritiesCompanyCode": "1240",
                        "CompanyName": "茂生農經",
                    }
                ],
                balance=[
                    {
                        "SecuritiesCompanyCode": "1240",
                        "CompanyName": "茂生農經",
                    }
                ],
            )
        )

        self.assertEqual(parsed["symbols"], ["1240"])
        self.assertEqual(parsed["stock_names"], {"1240": "茂生農經"})


class FinancialCiRolloutPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.source = SourceRegistry(
            source_name="TWSE Financial Metrics official",
            source_type="official_api",
            category="fundamentals",
            priority=10,
            reliability_level="official",
        )
        self.db.add(self.source)
        self.db.flush()
        self.raw = RawFetchResult(
            source_id=self.source.id,
            fetched_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            raw_text=_bundle(
                income=[
                    {"公司代號": "2303", "公司名稱": "聯電"},
                    {"公司代號": "2330", "公司名稱": "台積電"},
                ],
                balance=[
                    {"公司代號": "2303", "公司名稱": "聯電"},
                    {"公司代號": "2330", "公司名稱": "台積電"},
                ],
            ),
        )
        self.db.add(self.raw)
        self.db.flush()
        for stock_id, stock_name in (("2303", "聯電"), ("2330", "台積電")):
            self.db.add(
                FinancialMetricQuarterly(
                    source_id=self.source.id,
                    raw_result_id=self.raw.id,
                    fiscal_year=2026,
                    quarter=1,
                    period="2026Q1",
                    stock_id=stock_id,
                    stock_name=stock_name,
                    market="TWSE",
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_ready_2330_period(self, year: int, quarter: int) -> None:
        scope = {1: "ytd_3m", 2: "ytd_6m", 3: "ytd_9m", 4: "annual_12m"}[quarter]
        filing = TaiwanFinancialFiling(
            source_id=self.source.id,
            raw_result_id=self.raw.id,
            stock_id="2330",
            source_document_id=f"{year}{quarter:02d}_2330_AI1.pdf",
            source_document_url="https://example.test/2330",
            content_hash=f"{year}{quarter}".ljust(64, "0"),
            filing_kind="mops_ixbrl_financial_report",
            fiscal_year=year,
            fiscal_quarter=quarter,
            period_end=date(year, quarter * 3, 31 if quarter in {1, 4} else 30),
            filed_at=datetime(year, min(quarter * 3 + 2, 12), 15, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            known_at=datetime(year, min(quarter * 3 + 2, 12), 15, tzinfo=timezone.utc),
            parser_version="mops-ixbrl-v3",
        )
        self.db.add(filing)
        self.db.flush()
        run = TaiwanFinancialParseRun(
            filing_id=filing.id,
            raw_result_id=self.raw.id,
            parser_version="mops-ixbrl-v3",
            parsed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            parse_status="succeeded",
            review_status="approved",
            output_hash=str(filing.content_hash),
            fact_count=1,
            diagnostics_json="{}",
            reviewed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
            reviewed_by="test-reviewer",
        )
        self.db.add(run)
        self.db.flush()
        fact = TaiwanFinancialStatementFact(
            filing_id=filing.id,
            parse_run_id=run.id,
            stock_id="2330",
            fact_key=f"basic-eps-{year}Q{quarter}",
            metric_code="basic_eps",
            source_label="BasicEarningsLossPerShare",
            source_value=Decimal("1.00"),
            source_value_text="1.00",
            source_unit="TWD_per_share",
            currency="TWD",
            statement_type="per_share",
            period_kind="duration",
            period_scope=scope,
            period_start=date(year, 1, 1),
            period_end=filing.period_end,
            months_covered=quarter * 3,
            fiscal_year=year,
            fiscal_quarter=quarter,
            consolidation_scope="consolidated",
            attribution_scope="parent",
            eps_kind="basic",
            presentation_role="current_period",
            source_share_basis_id=f"2330:{year}Q{quarter}:basis",
            source_restated=False,
            source_restated_status="not_restated",
        )
        self.db.add(fact)
        self.db.flush()
        self.db.add(
            TaiwanFinancialNormalizedFact(
                source_fact_id=fact.id,
                comparison_basis_id="2330-test-basis",
                normalization_mode="current_comparable",
                normalized_value=Decimal("1.00"),
                normalized_unit="TWD_per_share",
                adjustment_factor=Decimal("1"),
                normalization_status="unchanged",
                normalization_version="test-v1",
                derived_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
                decision_usable=True,
                issue_codes_json="[]",
                lineage_json="{}",
            )
        )

    def _add_issued_capital(
        self,
        *,
        parse_run_id: int,
        filing_id: int,
        year: int,
        quarter: int,
        value: str,
    ) -> None:
        self.db.add(
            TaiwanFinancialStatementFact(
                filing_id=filing_id,
                parse_run_id=parse_run_id,
                stock_id="2330",
                fact_key=f"issued-capital-{year}Q{quarter}",
                metric_code="issued_capital",
                source_label="IssuedCapital",
                source_value=Decimal(value),
                source_value_text=value,
                source_unit="TWD_thousand",
                currency="TWD",
                statement_type="balance",
                period_kind="instant",
                period_scope="instant_period_end",
                period_start=None,
                period_end=date(year, quarter * 3, 31 if quarter in {1, 4} else 30),
                months_covered=None,
                fiscal_year=year,
                fiscal_quarter=quarter,
                consolidation_scope="consolidated",
                attribution_scope="company",
                eps_kind="not_applicable",
                presentation_role="current_period",
                source_share_basis_id=f"2330:{year}Q{quarter}:basis",
                source_restated=False,
                source_restated_status="not_restated",
            )
        )

    def test_planner_separates_ready_and_missing_without_writes(self) -> None:
        target_periods = [(2025, 4), (2026, 1)]
        for year, quarter in target_periods:
            self._add_ready_2330_period(year, quarter)
        self.db.commit()
        counts_before = (
            self.db.query(TaiwanFinancialFiling).count(),
            self.db.query(TaiwanFinancialNormalizedFact).count(),
        )

        result = build_ci_rollout_plan(
            self.db,
            periods=target_periods,
            limit=10,
        )

        by_symbol = {item["stock_id"]: item for item in result["candidates"]}
        self.assertEqual(result["universe_symbol_count"], 2)
        self.assertEqual(by_symbol["2330"]["stage"], "normalized_ready")
        self.assertEqual(by_symbol["2303"]["stage"], "missing_official_filings")
        self.assertEqual(
            by_symbol["2303"]["missing_official_periods"],
            ["2025Q4", "2026Q1"],
        )
        self.assertEqual(
            counts_before,
            (
                self.db.query(TaiwanFinancialFiling).count(),
                self.db.query(TaiwanFinancialNormalizedFact).count(),
            ),
        )

    def test_batch_isolates_symbol_failure_and_enforces_ci_universe(self) -> None:
        sleep_calls: list[float] = []

        def ingester(db: Session, **kwargs):
            stock_id = kwargs["stock_id"]
            db.add(
                SourceRegistry(
                    source_name=f"batch-test-{stock_id}",
                    source_type="test",
                    category="test",
                )
            )
            db.flush()
            if stock_id == "2303":
                raise ValueError("simulated provider schema drift")
            return {
                "request_count": 2,
                "request_limit": 2,
                "filings_created": 1,
            }

        result = run_ci_filing_ingestion_batch(
            self.db,
            stock_ids=["2303", "2330"],
            periods=[(2026, 1)],
            max_provider_requests=4,
            inter_symbol_delay_seconds=1.5,
            apply=True,
            ingester=ingester,
            sleeper=sleep_calls.append,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["succeeded_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertIsNone(result["actual_request_count"])
        self.assertEqual(result["accounted_request_count"], 2)
        self.assertFalse(result["request_count_complete"])
        self.assertEqual(result["unknown_request_count_failure_count"], 1)
        self.assertEqual(result["inter_symbol_delay_seconds"], 1.5)
        self.assertEqual(sleep_calls, [1.5])
        self.assertEqual(
            result["results"][0]["request_count_status"],
            "unknown_after_failure",
        )
        self.assertIsNone(
            self.db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == "batch-test-2303")
            .one_or_none()
        )
        self.assertIsNotNone(
            self.db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == "batch-test-2330")
            .one_or_none()
        )
        with self.assertRaisesRegex(ValueError, "not in the current ci universe"):
            run_ci_filing_ingestion_batch(
                self.db,
                stock_ids=["2881"],
                periods=[(2026, 1)],
                max_provider_requests=2,
                ingester=ingester,
            )

    def test_batch_rejects_request_plan_above_explicit_ceiling(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds explicit ceiling"):
            run_ci_filing_ingestion_batch(
                self.db,
                stock_ids=["2303", "2330"],
                periods=[(2025, 4), (2026, 1)],
                max_provider_requests=5,
                ingester=lambda *_args, **_kwargs: {},
            )

    def test_acceptance_sample_is_deterministic_and_honors_exclusions(
        self,
    ) -> None:
        first = select_ci_acceptance_sample(
            self.db,
            sample_size=1,
            seed="acceptance-test-v1",
            exclude_stock_ids=["2303"],
        )
        second = select_ci_acceptance_sample(
            self.db,
            sample_size=1,
            seed="acceptance-test-v1",
            exclude_stock_ids=["2303"],
        )

        self.assertEqual(first, second)
        self.assertEqual(first["selected"][0]["stock_id"], "2330")
        self.assertEqual(first["stratum_sample_size"], {"TWSE": 1})
        self.assertIn(
            "sample_validates_pipeline_behavior_not_every_symbol_value",
            first["boundaries"],
        )

    def test_planner_routes_issued_capital_change_to_action_reconciliation(
        self,
    ) -> None:
        target_periods = [(2025, 4), (2026, 1)]
        for year, quarter in target_periods:
            self._add_ready_2330_period(year, quarter)
        self.db.flush()
        self.db.query(TaiwanFinancialNormalizedFact).delete()
        filings = {
            (filing.fiscal_year, filing.fiscal_quarter): filing
            for filing in self.db.query(TaiwanFinancialFiling)
            .filter(TaiwanFinancialFiling.stock_id == "2330")
            .all()
        }
        for period, capital in (
            ((2025, 4), "100000"),
            ((2026, 1), "120000"),
        ):
            filing = filings[period]
            run = (
                self.db.query(TaiwanFinancialParseRun)
                .filter(TaiwanFinancialParseRun.filing_id == filing.id)
                .one()
            )
            run.fact_count += 1
            self._add_issued_capital(
                parse_run_id=run.id,
                filing_id=filing.id,
                year=period[0],
                quarter=period[1],
                value=capital,
            )
        self.db.commit()

        result = build_ci_rollout_plan(
            self.db,
            periods=target_periods,
            limit=10,
        )

        candidate = next(
            item for item in result["candidates"] if item["stock_id"] == "2330"
        )
        self.assertTrue(candidate["capital_change_detected"])
        self.assertEqual(candidate["stage"], "needs_action_reconciliation")


if __name__ == "__main__":
    unittest.main()
