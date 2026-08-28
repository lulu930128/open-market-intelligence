from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import data_quality_contract
from app.ai.market_context.taiwan_stock import _financial_valuation_input
from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanFinancialBasisAssessment,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialParseRunReview,
    TaiwanFinancialStatementFact,
)
from app.market.financial_contract import (
    build_database_financial_contract,
    build_legacy_financial_contract,
    build_normalized_financial_contract,
)
from app.market.financial_metric_normalization import NormalizedPeriodFact
from app.market.schemas import TaiwanFinancialContractRead
from app.routers.market import get_stock_financial_contract_api, router
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


def _financial_row(
    row_id: int,
    fiscal_year: int,
    quarter: int,
    eps: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        source_id=1,
        raw_result_id=100 + row_id,
        stock_id="2327",
        period=f"{fiscal_year}Q{quarter}",
        fiscal_year=fiscal_year,
        quarter=quarter,
        report_date=None,
        released_at=None,
        filed_at=None,
        revenue=1_000_000.0,
        gross_profit=300_000.0,
        operating_income=200_000.0,
        net_income=150_000.0,
        net_income_attributable_parent=150_000.0,
        eps=eps,
        total_assets=5_000_000.0,
        total_equity=2_000_000.0,
        parent_equity=1_900_000.0,
        book_value_per_share=80.0,
        roe=7.5,
        roa=3.0,
    )


class FinancialContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.financial_history = [
            _financial_row(1, 2025, 2, 20.51),
            _financial_row(2, 2025, 3, 8.22),
            _financial_row(3, 2025, 4, 11.51),
            _financial_row(4, 2026, 1, 3.90),
        ]
        self.revenue_history = [
            SimpleNamespace(period=date(2026, month, 1))
            for month in (1, 2, 3, 4, 6)
        ]
        self.as_of = datetime(2026, 7, 30, 13, 30, tzinfo=timezone.utc)

    def test_current_comparable_legacy_contract_is_explicitly_blocked(self) -> None:
        result = build_legacy_financial_contract(
            stock_id="2327",
            financial_history=self.financial_history,
            revenue_history=self.revenue_history,
            mode="current_comparable",
            as_of=self.as_of,
        )
        parsed = TaiwanFinancialContractRead.model_validate(result)

        self.assertEqual(parsed.contract_version, "omi.financial.v1")
        self.assertEqual(parsed.as_reported["latest"]["period"], "2026Q1")
        self.assertEqual(
            parsed.as_reported["history"][0]["period_scope"],
            "ytd",
        )
        self.assertEqual(parsed.normalized["status"], "blocked")
        self.assertEqual(parsed.derived["ttm_eps_status"], "blocked")
        self.assertIsNone(parsed.valuation["pe_ttm"])
        self.assertEqual(parsed.quality.continuity, "interior_gap")
        self.assertFalse(parsed.quality.decision_usable)
        self.assertIn(
            "monthly_revenue_missing_2026_05",
            parsed.quality.issues,
        )
        self.assertIn(
            "normalized_financial_facts_unavailable",
            parsed.quality.issues,
        )

    def test_point_in_time_mode_does_not_reuse_unknown_legacy_dates(self) -> None:
        result = build_legacy_financial_contract(
            stock_id="2327",
            financial_history=self.financial_history,
            revenue_history=self.revenue_history,
            mode="as_reported_as_of",
            as_of=self.as_of,
        )

        self.assertEqual(result["as_reported"]["status"], "blocked")
        self.assertEqual(result["as_reported"]["history"], [])
        self.assertIn(
            "point_in_time_known_at_missing",
            result["quality"]["issues"],
        )

    def test_normalized_contract_projects_yageo_ttm_and_valuation(self) -> None:
        baseline = build_legacy_financial_contract(
            stock_id="2327",
            financial_history=self.financial_history,
            revenue_history=self.revenue_history,
            mode="current_comparable",
            as_of=self.as_of,
        )
        values = (
            (2025, 1, "ytd_3m", "2.69", "1", "0.005"),
            (2025, 2, "discrete_3m", "2.435", "4", "0.00125"),
            (2025, 2, "ytd_6m", "5.1275", "4", "0.00125"),
            (2025, 3, "discrete_3m", "3.10", "1", "0.005"),
            (2025, 3, "ytd_9m", "8.22", "1", "0.005"),
            (2025, 4, "annual_12m", "11.51", "1", "0.005"),
            (2026, 1, "ytd_3m", "3.90", "1", "0.005"),
        )
        normalized = [
            NormalizedPeriodFact(
                source_fact_id=f"2327-{year}Q{quarter}-{scope}",
                stock_id="2327",
                fiscal_year=year,
                fiscal_quarter=quarter,
                metric_code="basic_eps",
                period_scope=scope,
                period_end={
                    1: date(year, 3, 31),
                    2: date(year, 6, 30),
                    3: date(year, 9, 30),
                    4: date(year, 12, 31),
                }[quarter],
                normalized_value=Decimal(value),
                normalized_unit="TWD_per_share",
                adjustment_factor=Decimal(factor),
                comparison_basis_id="2327-current-share-basis-2025-08-22",
                normalization_status=(
                    "normalized" if Decimal(factor) != 1 else "unchanged"
                ),
                normalization_version="tw-financial-normalization-v1",
                normalization_mode="current_comparable",
                decision_usable=True,
                action_ids=(
                    ("2327-split-2025-08-22",)
                    if Decimal(factor) != 1
                    else ()
                ),
                issue_codes=(),
                known_at=self.as_of,
                rounding_tolerance=Decimal(tolerance),
            )
            for year, quarter, scope, value, factor, tolerance in values
        ]
        contract = build_normalized_financial_contract(
            baseline=baseline,
            normalized_facts=normalized,
            revenue_continuity={
                "status": "complete",
                "decision_usable": True,
                "issues": [],
            },
            price=Decimal("456.5"),
            price_as_of=self.as_of,
            price_basis="official_close",
        )

        self.assertEqual(contract["normalized"]["status"], "ready")
        self.assertEqual(contract["derived"]["ttm_eps"], Decimal("12.73"))
        self.assertEqual(contract["derived"]["ttm_eps_exact"], "12.725")
        self.assertEqual(
            contract["derived"]["ttm_periods"],
            ["2025Q2", "2025Q3", "2025Q4", "2026Q1"],
        )
        self.assertEqual(
            contract["derived"]["annual_reconciliations"][0]["status"],
            "ready",
        )
        self.assertEqual(
            contract["derived"]["annual_reconciliations"][0]["difference"],
            Decimal("0.005"),
        )
        self.assertTrue(
            contract["derived"]["annual_reconciliations"][0][
                "within_tolerance"
            ]
        )
        self.assertEqual(contract["valuation"]["pe_ttm"], Decimal("35.87"))
        self.assertEqual(contract["quality"]["semantic_validity"], "valid")
        self.assertTrue(contract["quality"]["decision_usable"])

    def test_disputed_normalization_blocks_derived_and_valuation_contract(self) -> None:
        baseline = build_legacy_financial_contract(
            stock_id="2327",
            financial_history=self.financial_history,
            revenue_history=self.revenue_history,
            mode="current_comparable",
            as_of=self.as_of,
        )
        disputed = NormalizedPeriodFact(
            source_fact_id="2327-2025Q3-disputed",
            stock_id="2327",
            fiscal_year=2025,
            fiscal_quarter=3,
            metric_code="basic_eps",
            period_scope="ytd_9m",
            period_end=date(2025, 9, 30),
            normalized_value=Decimal("8.22"),
            normalized_unit="TWD_per_share",
            adjustment_factor=Decimal("1"),
            comparison_basis_id="2327-current-share-basis-2025-08-22",
            normalization_status="disputed",
            normalization_version="tw-financial-normalization-v1",
            normalization_mode="current_comparable",
            decision_usable=False,
            action_ids=(),
            issue_codes=("official_discrete_eps_conflict",),
            known_at=self.as_of,
        )

        contract = build_normalized_financial_contract(
            baseline=baseline,
            normalized_facts=[disputed],
            revenue_continuity={
                "status": "complete",
                "decision_usable": True,
                "issues": [],
            },
            price=Decimal("456.5"),
            price_as_of=self.as_of,
            price_basis="official_close",
        )

        self.assertEqual(contract["normalized"]["status"], "blocked")
        self.assertEqual(contract["derived"]["ttm_eps_status"], "blocked")
        self.assertEqual(contract["valuation"]["status"], "blocked")
        self.assertEqual(contract["quality"]["semantic_validity"], "disputed")
        self.assertFalse(contract["quality"]["decision_usable"])
        self.assertIn(
            "official_discrete_eps_conflict",
            contract["quality"]["issues"],
        )

    def test_router_exposes_versioned_read_only_contract(self) -> None:
        paths = {route.path for route in router.routes}
        self.assertIn("/financials/{stock_id}/contract", paths)

        with (
            patch(
                "app.routers.market.list_stock_financial_metric_history",
                return_value=self.financial_history,
            ),
            patch(
                "app.routers.market.list_stock_monthly_revenue_history",
                return_value=self.revenue_history,
            ),
        ):
            result = get_stock_financial_contract_api(
                stock_id="2327",
                mode="current_comparable",
                as_of=self.as_of,
                financial_limit=8,
                revenue_limit=24,
                price=None,
                price_as_of=None,
                price_basis="explicit_input",
                db=SimpleNamespace(get_bind=lambda: None),
            )

        self.assertEqual(result["contract_version"], "omi.financial.v1")
        self.assertEqual(result["target"]["stock_id"], "2327")
        self.assertFalse(result["quality"]["decision_usable"])

    def test_resolved_trade_price_is_auditable_valuation_input(self) -> None:
        price, price_as_of, price_basis = _financial_valuation_input(
            {
                "value": 456.5,
                "event_time": "2026-07-30T13:25:00+08:00",
                "source_kind": "quote_last_trade",
                "is_estimate": False,
            }
        )

        self.assertEqual(price, Decimal("456.5"))
        self.assertEqual(
            price_as_of,
            datetime.fromisoformat("2026-07-30T13:25:00+08:00"),
        )
        self.assertEqual(
            price_basis,
            "resolved_current_price:quote_last_trade",
        )

    def test_estimated_price_is_not_used_for_valuation(self) -> None:
        price, price_as_of, price_basis = _financial_valuation_input(
            {
                "value": 456.5,
                "event_time": "2026-07-30T13:25:00+08:00",
                "source_kind": "order_book_midpoint_estimate",
                "is_estimate": True,
            }
        )

        self.assertIsNone(price)
        self.assertIsNone(price_as_of)
        self.assertEqual(price_basis, "unavailable")

    def test_database_contract_surfaces_blocking_accounting_basis_assessment(
        self,
    ) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            db.add(
                TaiwanFinancialBasisAssessment(
                    raw_result_id=None,
                    stock_id="2881",
                    normalization_mode="current_comparable",
                    assessment_type="accounting_basis_transition",
                    outcome="blocked",
                    effective_date=date(2026, 1, 1),
                    issue_code=(
                        "accounting_basis_transition_incomplete_comparatives"
                    ),
                    rationale=(
                        "IFRS 17 restated 2025Q1, while restated Q2-Q4 EPS "
                        "remain unavailable."
                    ),
                    resolution_requirements_json=(
                        '["restated_2025Q2_discrete_eps",'
                        '"restated_2025_annual_eps"]'
                    ),
                    evidence_package_hash="a" * 64,
                    evidence_json="{}",
                    known_at=datetime(
                        2026,
                        5,
                        29,
                        4,
                        1,
                        13,
                        tzinfo=timezone.utc,
                    ),
                    reviewed_at=self.as_of,
                    reviewed_by="test-reviewer",
                )
            )
            db.commit()

            result = build_database_financial_contract(
                db,
                stock_id="2881",
                mode="current_comparable",
                as_of=self.as_of,
                financial_history=[
                    SimpleNamespace(
                        **{
                            **_financial_row(1, 2026, 1, 2.40).__dict__,
                            "stock_id": "2881",
                        }
                    )
                ],
                revenue_history=[
                    SimpleNamespace(period=date(2026, month, 1))
                    for month in range(1, 7)
                ],
                price=Decimal("100"),
                price_as_of=self.as_of,
                price_basis="official_close",
            )

            self.assertEqual(result["normalized"]["status"], "blocked")
            self.assertEqual(result["derived"]["ttm_eps_status"], "blocked")
            self.assertEqual(result["valuation"]["status"], "blocked")
            self.assertEqual(
                result["quality"]["semantic_validity"],
                "accounting_basis_transition",
            )
            self.assertFalse(result["quality"]["decision_usable"])
            self.assertEqual(
                result["basis_assessment"]["issue_code"],
                "accounting_basis_transition_incomplete_comparatives",
            )
            self.assertIn(
                "restated_2025Q2_discrete_eps",
                result["basis_assessment"]["resolution_requirements"],
            )
            self.assertTrue(
                any(
                    ref.get("name") == "tw_financial_basis_assessment"
                    for ref in result["source_refs"]
                )
            )
        finally:
            db.close()
            engine.dispose()

    def test_database_contract_reads_persisted_normalization_lineage(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            source = SourceRegistry(
                source_name="financial-contract-test",
                source_type="official",
                category="financial",
                enabled=True,
                priority=1,
                auth_type="none",
                reliability_level="official",
            )
            db.add(source)
            db.flush()
            values = (
                (2025, 1, "ytd_3m", "2.69", "2.69", "1"),
                (2025, 2, "discrete_3m", "2.435", "9.74", "4"),
                (2025, 2, "ytd_6m", "5.1275", "20.51", "4"),
                (2025, 3, "discrete_3m", "3.10", "3.10", "1"),
                (2025, 3, "ytd_9m", "8.22", "8.22", "1"),
                (2025, 4, "annual_12m", "11.51", "11.51", "1"),
                (2026, 1, "ytd_3m", "3.90", "3.90", "1"),
            )
            for index, (year, quarter, scope, value, raw_value, factor) in enumerate(
                values,
                start=1,
            ):
                raw = RawFetchResult(
                    source_id=source.id,
                    fetched_at=self.as_of,
                    method="GET",
                    content_hash=f"raw-{year}Q{quarter}",
                    parser_version="financial-contract-test-v1",
                )
                db.add(raw)
                db.flush()
                period_end = {
                    1: date(year, 3, 31),
                    2: date(year, 6, 30),
                    3: date(year, 9, 30),
                    4: date(year, 12, 31),
                }[quarter]
                filing = TaiwanFinancialFiling(
                    source_id=source.id,
                    raw_result_id=raw.id,
                    stock_id="2327",
                    source_document_id=f"2327-{year}Q{quarter}-{scope}",
                    content_hash=f"filing-{year}Q{quarter}",
                    filing_kind="quarterly_report",
                    fiscal_year=year,
                    fiscal_quarter=quarter,
                    period_end=period_end,
                    announced_at=self.as_of,
                    filed_at=self.as_of,
                    fetched_at=self.as_of,
                    known_at=self.as_of,
                    parser_version="financial-contract-test-v1",
                )
                db.add(filing)
                db.flush()
                parse_run = TaiwanFinancialParseRun(
                    filing_id=filing.id,
                    raw_result_id=raw.id,
                    parser_version="financial-contract-test-v1",
                    parsed_at=self.as_of,
                    parse_status="succeeded",
                    review_status="approved",
                    output_hash=f"output-{year}Q{quarter}-{scope}",
                    fact_count=1,
                    diagnostics_json="{}",
                    reviewed_at=self.as_of,
                    reviewed_by="test-reviewer",
                )
                db.add(parse_run)
                db.flush()
                fact = TaiwanFinancialStatementFact(
                    filing_id=filing.id,
                    parse_run_id=parse_run.id,
                    stock_id="2327",
                    fact_key=f"basic_eps|current|{year}Q{quarter}",
                    metric_code="basic_eps",
                    source_label="基本每股盈餘",
                    source_value=Decimal(raw_value),
                    source_value_text=raw_value,
                    source_unit="TWD_per_share",
                    currency="TWD",
                    statement_type="per_share",
                    period_kind="duration",
                    period_scope=scope,
                    period_start=date(year, 1, 1),
                    period_end=period_end,
                    months_covered=quarter * 3,
                    fiscal_year=year,
                    fiscal_quarter=quarter,
                    consolidation_scope="consolidated",
                    attribution_scope="parent",
                    eps_kind="basic",
                    presentation_role="current_period",
                    source_share_basis_id=f"2327-source-basis-{index}",
                    source_restated=factor == "1",
                    source_restated_status=(
                        "confirmed" if factor == "1" else "not_restated"
                    ),
                )
                db.add(fact)
                db.flush()
                db.add(
                    TaiwanFinancialNormalizedFact(
                        source_fact_id=fact.id,
                        comparison_basis_id=(
                            "2327-current-share-basis-2025-08-22"
                        ),
                        normalization_mode="current_comparable",
                        normalized_value=Decimal(value),
                        normalized_unit="TWD_per_share",
                        adjustment_factor=Decimal(factor),
                        normalization_status=(
                            "normalized" if factor != "1" else "unchanged"
                        ),
                        normalization_version="tw-financial-normalization-v1",
                        derived_at=self.as_of,
                        decision_usable=True,
                        issue_codes_json="[]",
                        lineage_json=(
                            '{"corporate_action_ids":'
                            '["2327-split-2025-08-22"]}'
                            if factor != "1"
                            else '{"corporate_action_ids":[]}'
                        ),
                    )
                )
            pending_run = TaiwanFinancialParseRun(
                filing_id=filing.id,
                raw_result_id=raw.id,
                parser_version="financial-contract-test-v2",
                parsed_at=self.as_of,
                parse_status="succeeded",
                review_status="pending",
                output_hash="pending-output-2026Q1",
                fact_count=1,
                diagnostics_json="{}",
            )
            db.add(pending_run)
            db.flush()
            pending_fact = TaiwanFinancialStatementFact(
                filing_id=filing.id,
                parse_run_id=pending_run.id,
                stock_id="2327",
                fact_key="basic_eps|pending|2026Q1",
                metric_code="basic_eps",
                source_label="Basic EPS",
                source_value=Decimal("999"),
                source_value_text="999",
                source_unit="TWD_per_share",
                currency="TWD",
                statement_type="per_share",
                period_kind="duration",
                period_scope="ytd_3m",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 3, 31),
                months_covered=3,
                fiscal_year=2026,
                fiscal_quarter=1,
                consolidation_scope="consolidated",
                attribution_scope="parent",
                eps_kind="basic",
                presentation_role="current_period",
                source_share_basis_id="2327-pending-basis",
                source_restated=False,
                source_restated_status="not_restated",
            )
            db.add(pending_fact)
            db.flush()
            db.add(
                TaiwanFinancialNormalizedFact(
                    source_fact_id=pending_fact.id,
                    comparison_basis_id="2327-current-share-basis-2025-08-22",
                    normalization_mode="current_comparable",
                    normalized_value=Decimal("999"),
                    normalized_unit="TWD_per_share",
                    adjustment_factor=Decimal("1"),
                    normalization_status="unchanged",
                    normalization_version="tw-financial-normalization-v1",
                    derived_at=self.as_of,
                    decision_usable=True,
                    issue_codes_json="[]",
                    lineage_json='{"corporate_action_ids":[]}',
                )
            )
            daily_source = SourceRegistry(
                source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
                source_type="official",
                category="daily_price",
                enabled=True,
                priority=5,
                auth_type="none",
                reliability_level="official",
            )
            db.add(daily_source)
            db.flush()
            daily_raw = RawFetchResult(
                source_id=daily_source.id,
                fetched_at=self.as_of,
                method="GET",
                content_hash="daily-close-2026-07-30",
                parser_version="daily-close-test-v1",
            )
            db.add(daily_raw)
            db.flush()
            db.add(
                StockMaster(
                    stock_id="2327",
                    stock_name="國巨",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
            )
            db.add(
                MarketDailyPrice(
                    source_id=daily_source.id,
                    raw_result_id=daily_raw.id,
                    trade_date=date(2026, 7, 30),
                    stock_id="2327",
                    stock_name="國巨",
                    open_price=456.5,
                    high_price=456.5,
                    low_price=456.5,
                    close_price=456.5,
                )
            )
            db.commit()

            result = build_database_financial_contract(
                db,
                stock_id="2327",
                mode="current_comparable",
                as_of=self.as_of,
                financial_history=self.financial_history,
                revenue_history=[
                    SimpleNamespace(period=date(2026, month, 1))
                    for month in range(1, 7)
                ],
            )

            self.assertEqual(result["normalized"]["status"], "ready")
            self.assertEqual(result["derived"]["ttm_eps"], Decimal("12.73"))
            self.assertEqual(
                result["derived"]["ttm_eps_exact"],
                "12.7250000000",
            )
            self.assertEqual(result["valuation"]["pe_ttm"], Decimal("35.87"))
            self.assertEqual(
                result["valuation"]["price_basis"],
                "latest_completed_daily_close:canonical_daily",
            )
            self.assertEqual(
                result["valuation"]["price_trade_date"],
                "2026-07-30",
            )
            self.assertEqual(
                result["valuation"]["price_source"],
                TWSE_DAILY_TRADING_SOURCE_NAME,
            )
            self.assertTrue(result["quality"]["decision_usable"])
            self.assertTrue(
                any(
                    source_ref.get("name") == "tw_financial_normalized_fact"
                    for source_ref in result["source_refs"]
                )
            )

            source.reliability_level = "unknown"
            db.commit()
            blocked = build_database_financial_contract(
                db,
                stock_id="2327",
                mode="current_comparable",
                as_of=self.as_of,
                financial_history=self.financial_history,
                revenue_history=[
                    SimpleNamespace(period=date(2026, month, 1))
                    for month in range(1, 7)
                ],
                price=Decimal("456.5"),
                price_as_of=self.as_of,
                price_basis="official_close",
            )
            self.assertEqual(blocked["normalized"]["status"], "blocked")
            self.assertFalse(blocked["quality"]["decision_usable"])
            self.assertIn(
                "normalized_source_untrusted",
                blocked["quality"]["issues"],
            )
        finally:
            db.close()
            engine.dispose()

    def test_point_in_time_contract_uses_parse_run_approved_by_as_of(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        try:
            source = SourceRegistry(
                source_name="point-in-time-financial-test",
                source_type="official",
                category="financial",
                enabled=True,
                priority=1,
                auth_type="none",
                reliability_level="official",
            )
            db.add(source)
            db.flush()
            filing_known_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=filing_known_at,
                method="GET",
                content_hash="point-in-time-filing",
                parser_version="point-in-time-test-v1",
            )
            db.add(raw)
            db.flush()
            filing = TaiwanFinancialFiling(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="2327",
                source_document_id="2327-2026Q1-point-in-time",
                content_hash="point-in-time-filing",
                filing_kind="quarterly_report",
                fiscal_year=2026,
                fiscal_quarter=1,
                period_end=date(2026, 3, 31),
                announced_at=filing_known_at,
                filed_at=filing_known_at,
                fetched_at=filing_known_at,
                known_at=filing_known_at,
                parser_version="point-in-time-test-v1",
            )
            db.add(filing)
            db.flush()

            parse_runs: list[tuple[TaiwanFinancialParseRun, Decimal, datetime]] = []
            for parser_version, value, reviewed_at in (
                (
                    "point-in-time-test-v1",
                    Decimal("2.69"),
                    datetime(2026, 4, 17, tzinfo=timezone.utc),
                ),
                (
                    "point-in-time-test-v2",
                    Decimal("3.90"),
                    datetime(2026, 8, 2, tzinfo=timezone.utc),
                ),
            ):
                run = TaiwanFinancialParseRun(
                    filing_id=filing.id,
                    raw_result_id=raw.id,
                    parser_version=parser_version,
                    parsed_at=reviewed_at,
                    parse_status="succeeded",
                    review_status="approved",
                    output_hash=f"{parser_version}-output",
                    fact_count=1,
                    diagnostics_json="{}",
                    reviewed_at=reviewed_at,
                    reviewed_by="test-reviewer",
                )
                db.add(run)
                db.flush()
                parse_runs.append((run, value, reviewed_at))
                db.add(
                    TaiwanFinancialParseRunReview(
                        parse_run_id=run.id,
                        decision="approved",
                        decided_at=reviewed_at,
                        decided_by="test-reviewer",
                        output_hash_snapshot=run.output_hash,
                    )
                )
                fact = TaiwanFinancialStatementFact(
                    filing_id=filing.id,
                    parse_run_id=run.id,
                    stock_id="2327",
                    fact_key=f"basic_eps|{parser_version}|2026Q1",
                    metric_code="basic_eps",
                    source_label="Basic EPS",
                    source_value=value,
                    source_value_text=str(value),
                    source_unit="TWD_per_share",
                    currency="TWD",
                    statement_type="per_share",
                    period_kind="duration",
                    period_scope="ytd_3m",
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 3, 31),
                    months_covered=3,
                    fiscal_year=2026,
                    fiscal_quarter=1,
                    consolidation_scope="consolidated",
                    attribution_scope="parent",
                    eps_kind="basic",
                    presentation_role="current_period",
                    source_share_basis_id="2327-point-in-time-basis",
                    source_restated=True,
                    source_restated_status="confirmed",
                )
                db.add(fact)
                db.flush()
                db.add(
                    TaiwanFinancialNormalizedFact(
                        source_fact_id=fact.id,
                        comparison_basis_id="2327-point-in-time-basis",
                        normalization_mode="as_reported_as_of",
                        normalized_value=value,
                        normalized_unit="TWD_per_share",
                        adjustment_factor=Decimal("1"),
                        normalization_status="unchanged",
                        normalization_version=parser_version,
                        derived_at=reviewed_at,
                        decision_usable=True,
                        issue_codes_json="[]",
                        lineage_json='{"corporate_action_ids":[]}',
                    )
                )
            old_run = parse_runs[0][0]
            revoked_at = datetime(2026, 8, 15, tzinfo=timezone.utc)
            db.add(
                TaiwanFinancialParseRunReview(
                    parse_run_id=old_run.id,
                    decision="revoked",
                    decided_at=revoked_at,
                    decided_by="test-reviewer",
                    output_hash_snapshot=old_run.output_hash,
                    reason="superseded after the historical as-of date",
                )
            )
            old_run.review_status = "revoked"
            old_run.reviewed_at = revoked_at
            db.commit()

            historical_as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
            result = build_database_financial_contract(
                db,
                stock_id="2327",
                mode="as_reported_as_of",
                as_of=historical_as_of,
                financial_history=[],
                revenue_history=[],
                price=Decimal("456.5"),
                price_as_of=historical_as_of,
                price_basis="official_close",
            )

            self.assertEqual(result["normalized"]["status"], "ready")
            self.assertEqual(
                result["normalized"]["facts"][0]["normalized_value"],
                Decimal("2.69"),
            )
            normalized_ref = next(
                ref
                for ref in result["source_refs"]
                if ref.get("name") == "tw_financial_normalized_fact"
            )
            self.assertEqual(normalized_ref["parse_run_id"], parse_runs[0][0].id)
            self.assertNotEqual(
                normalized_ref["parse_run_id"],
                parse_runs[1][0].id,
            )
        finally:
            db.close()
            engine.dispose()


class FinancialCapabilityQualityTests(unittest.TestCase):
    @staticmethod
    def _build_quality(financial_payload: dict) -> dict:
        quality = data_quality_contract.build_quality_contract(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": {"type": "tw_stock", "id": "2327", "market": "TW"},
                "status": {"readiness": {"decision_required": False}},
                "evidence": {
                    "freshness_by_domain": {"fundamentals": "current"},
                    "freshness_by_capability": {
                        "fundamentals.financials": {"status": "current"}
                    },
                    "slots": {"fundamentals": {"status": "partial"}},
                },
            },
            selection={
                "output": "evidence_only",
                "unmet_required_capabilities": [],
            },
            manifest={
                "capabilities": [
                    {
                        "capability": "fundamentals.financials",
                        "domain": "fundamentals",
                        "slot": "fundamentals",
                        "required": True,
                        "status": "current",
                    }
                ]
            },
            projected_data={"fundamentals.financials": financial_payload},
            realtime_assessments={},
            scope_type="stock",
        )
        return quality["capabilities"]["fundamentals.financials"]

    def test_legacy_financial_contract_is_factual_but_not_decision_usable(
        self,
    ) -> None:
        quality = self._build_quality(
            {
                "latest_financial": {
                    "period": "2026Q1",
                    "eps": 3.9,
                    "decision_usable": False,
                },
                "financial_history": [
                    {
                        "period": "2025Q4",
                        "eps": 11.51,
                        "decision_usable": False,
                    }
                ],
                "financial_contract": {
                    "contract_version": "omi.financial.v1",
                    "as_reported": {
                        "status": "available_with_legacy_semantics",
                        "latest": {"period": "2026Q1"},
                    },
                    "normalized": {"status": "blocked"},
                    "quality": {
                        "semantic_validity": "unknown_share_basis",
                        "decision_usable": False,
                        "issues": [
                            "share_basis_unverified",
                            "ttm_eps_unavailable",
                        ],
                    },
                },
            }
        )

        self.assertEqual(quality["status"], "partial")
        self.assertEqual(quality["status_class"], "limited")
        self.assertEqual(quality["freshness_status"], "current")
        self.assertTrue(quality["facts_usable"])
        self.assertFalse(quality["decision_usable"])
        self.assertEqual(
            quality["upstream_status_authority"],
            "payload.semantic_quality",
        )
        self.assertIn("share_basis_unverified", quality["reason_codes"])
        self.assertIn(
            "financial_contract_decision_blocked",
            quality["reason_codes"],
        )

    def test_normalized_financial_contract_remains_decision_usable(self) -> None:
        quality = self._build_quality(
            {
                "latest_financial": {
                    "period": "2026Q1",
                    "eps": 3.9,
                    "decision_usable": True,
                },
                "financial_contract": {
                    "contract_version": "omi.financial.v1",
                    "as_reported": {
                        "status": "available_with_legacy_semantics",
                        "latest": {"period": "2026Q1"},
                    },
                    "normalized": {"status": "ready"},
                    "quality": {
                        "semantic_validity": "valid",
                        "decision_usable": True,
                        "issues": [],
                    },
                },
            }
        )

        self.assertEqual(quality["status"], "current")
        self.assertEqual(quality["status_class"], "ready")
        self.assertTrue(quality["facts_usable"])
        self.assertTrue(quality["decision_usable"])
        self.assertEqual(
            quality["upstream_status_authority"],
            "freshness_by_capability",
        )


if __name__ == "__main__":
    unittest.main()
