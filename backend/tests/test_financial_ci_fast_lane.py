from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_ci_fast_lane import build_ci_fast_lane_package
from app.market.financial_parse_runs import canonical_fact_output_hash


class FinancialCiFastLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.source = SourceRegistry(
            source_name="MOPS Official Filing iXBRL",
            source_type="official_filing",
            category="financial_filing",
            endpoint_url="https://mops.example.test/t164sb01",
            priority=5,
            reliability_level="official",
        )
        self.db.add(self.source)
        self.db.flush()
        self.raw = RawFetchResult(
            source_id=self.source.id,
            fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            method="GET",
            status_code=200,
            content_hash="raw",
            parser_version="mops-ixbrl-v4",
        )
        self.db.add(self.raw)
        self.db.flush()
        self.runs: dict[tuple[int, int], TaiwanFinancialParseRun] = {}
        self.capital_facts: dict[tuple[int, int], TaiwanFinancialStatementFact] = {}
        for period, values in {
            (2025, 1): {"ytd_3m": "1.00"},
            (2025, 2): {"ytd_6m": "2.10", "discrete_3m": "1.10"},
            (2025, 3): {"ytd_9m": "3.30", "discrete_3m": "1.20"},
            (2025, 4): {"annual_12m": "4.60"},
            (2026, 1): {"ytd_3m": "1.40"},
        }.items():
            self._add_period(period=period, values=values)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _period_end(year: int, quarter: int) -> date:
        return {
            1: date(year, 3, 31),
            2: date(year, 6, 30),
            3: date(year, 9, 30),
            4: date(year, 12, 31),
        }[quarter]

    def _fact(
        self,
        *,
        filing: TaiwanFinancialFiling,
        run: TaiwanFinancialParseRun,
        fiscal_year: int,
        fiscal_quarter: int,
        scope: str,
        value: str,
        role: str = "current_period",
    ) -> TaiwanFinancialStatementFact:
        if scope == "discrete_3m":
            start_month = 4 if fiscal_quarter == 2 else 7
            period_start = date(fiscal_year, start_month, 1)
        else:
            period_start = date(fiscal_year, 1, 1)
        period_end = self._period_end(fiscal_year, fiscal_quarter)
        return TaiwanFinancialStatementFact(
            filing_id=filing.id,
            parse_run_id=run.id,
            stock_id="5902",
            fact_key=(
                f"basic-eps|{fiscal_year}Q{fiscal_quarter}|{scope}|{role}"
            ),
            metric_code="basic_eps",
            source_label="BasicEarningsLossPerShare",
            source_value=Decimal(value),
            source_value_text=value,
            source_unit="TWD_per_share",
            currency="TWD",
            statement_type="per_share",
            period_kind="duration",
            period_scope=scope,
            period_start=period_start,
            period_end=period_end,
            months_covered=3 if scope == "discrete_3m" else fiscal_quarter * 3,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            consolidation_scope="consolidated",
            attribution_scope="parent",
            eps_kind="basic",
            presentation_role=role,
            source_share_basis_id=(
                f"5902:{fiscal_year}Q{fiscal_quarter}:presentation"
            ),
            source_restated=False,
            source_restated_status="not_restated",
        )

    def _add_period(
        self,
        *,
        period: tuple[int, int],
        values: dict[str, str],
    ) -> None:
        year, quarter = period
        filing = TaiwanFinancialFiling(
            source_id=self.source.id,
            raw_result_id=self.raw.id,
            stock_id="5902",
            source_document_id=f"{year}{quarter:02d}_5902_AI1.pdf",
            source_document_url=(
                "https://mops.example.test/t164sb01?"
                f"CO_ID=5902&SYEAR={year}&SSEASON={quarter}&REPORT_ID=C"
            ),
            content_hash=(f"{year}{quarter}" * 20)[:64],
            filing_kind="mops_ixbrl_financial_report",
            fiscal_year=year,
            fiscal_quarter=quarter,
            period_end=self._period_end(year, quarter),
            fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            known_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            parser_version="mops-ixbrl-v4",
        )
        self.db.add(filing)
        self.db.flush()
        run = TaiwanFinancialParseRun(
            filing_id=filing.id,
            raw_result_id=self.raw.id,
            parser_version="mops-ixbrl-v4",
            parsed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            parse_status="succeeded",
            review_status="approved",
            output_hash="0" * 64,
            fact_count=0,
            diagnostics_json="{}",
            reviewed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            reviewed_by="test-reviewer",
        )
        self.db.add(run)
        self.db.flush()
        facts = [
            self._fact(
                filing=filing,
                run=run,
                fiscal_year=year,
                fiscal_quarter=quarter,
                scope=scope,
                value=value,
            )
            for scope, value in values.items()
        ]
        if period == (2026, 1):
            facts.append(
                self._fact(
                    filing=filing,
                    run=run,
                    fiscal_year=2025,
                    fiscal_quarter=1,
                    scope="ytd_3m",
                    value="1.00",
                    role="comparative_period",
                )
            )
        capital = TaiwanFinancialStatementFact(
            filing_id=filing.id,
            parse_run_id=run.id,
            stock_id="5902",
            fact_key=f"issued-capital|{year}Q{quarter}|current",
            metric_code="issued_capital",
            source_label="IssuedCapital",
            source_value=Decimal("945000"),
            source_value_text="945,000",
            source_unit="TWD_thousand",
            currency="TWD",
            statement_type="balance",
            period_kind="instant",
            period_scope="instant_period_end",
            period_start=None,
            period_end=self._period_end(year, quarter),
            months_covered=None,
            fiscal_year=year,
            fiscal_quarter=quarter,
            consolidation_scope="consolidated",
            attribution_scope="company",
            eps_kind="not_applicable",
            presentation_role="current_period",
            source_share_basis_id=f"5902:{year}Q{quarter}:presentation",
            source_restated=False,
            source_restated_status="not_restated",
        )
        facts.append(capital)
        self.db.add_all(facts)
        self.db.flush()
        run.fact_count = len(facts)
        run.output_hash = canonical_fact_output_hash(facts)
        self.runs[period] = run
        self.capital_facts[period] = capital

    def _build(self):
        return build_ci_fast_lane_package(
            self.db,
            stock_id="5902",
            reviewer="test-reviewer",
            reviewed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

    def test_builds_auditable_clone_only_package(self) -> None:
        package, audit = self._build()

        self.assertEqual(package.approval_scope, "clone_only")
        self.assertEqual(package.stock_id, "5902")
        self.assertEqual(len(package.documents), 5)
        self.assertEqual(len(package.facts), 7)
        self.assertEqual(audit["status"], "eligible")
        self.assertEqual(audit["report_id"], "C")
        self.assertEqual(audit["issued_capital_twd_thousand"], "945000")
        self.assertEqual(audit["q1_cross_filing_value"], "1")
        self.assertEqual(len(audit["package_hash"]), 64)

    def test_rejects_capital_change(self) -> None:
        capital = self.capital_facts[(2026, 1)]
        capital.source_value = Decimal("946000")
        run = self.runs[(2026, 1)]
        facts = (
            self.db.query(TaiwanFinancialStatementFact)
            .filter(TaiwanFinancialStatementFact.parse_run_id == run.id)
            .all()
        )
        run.output_hash = canonical_fact_output_hash(facts)
        self.db.flush()

        with self.assertRaisesRegex(ValueError, "issued capital changed"):
            self._build()

    def test_rejects_cross_filing_comparative_mismatch(self) -> None:
        run = self.runs[(2026, 1)]
        comparative = (
            self.db.query(TaiwanFinancialStatementFact)
            .filter(
                TaiwanFinancialStatementFact.parse_run_id == run.id,
                TaiwanFinancialStatementFact.presentation_role
                == "comparative_period",
            )
            .one()
        )
        comparative.source_value = Decimal("0.99")
        facts = (
            self.db.query(TaiwanFinancialStatementFact)
            .filter(TaiwanFinancialStatementFact.parse_run_id == run.id)
            .all()
        )
        run.output_hash = canonical_fact_output_hash(facts)
        self.db.flush()

        with self.assertRaisesRegex(ValueError, "comparative EPS mismatch"):
            self._build()


if __name__ == "__main__":
    unittest.main()
