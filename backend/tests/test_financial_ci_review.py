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
    TaiwanFinancialParseRunReview,
    TaiwanFinancialStatementFact,
)
from app.market.financial_ci_review import review_ci_parse_run_batch
from app.market.financial_parse_runs import canonical_fact_output_hash


class FinancialCiReviewBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.source = SourceRegistry(
            source_name="MOPS Official Filing iXBRL",
            source_type="official_filing",
            category="financial_filing",
            reliability_level="official",
        )
        self.db.add(self.source)
        self.db.flush()
        self.raw = RawFetchResult(
            source_id=self.source.id,
            fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            raw_text="test",
        )
        self.db.add(self.raw)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_run(self, stock_id: str, *, corrupt_hash: bool = False) -> int:
        filing = TaiwanFinancialFiling(
            source_id=self.source.id,
            raw_result_id=self.raw.id,
            stock_id=stock_id,
            source_document_id=f"202601_{stock_id}_AI1.pdf",
            source_document_url=f"https://example.test/{stock_id}",
            content_hash=(stock_id * 64)[:64],
            filing_kind="mops_ixbrl_financial_report",
            fiscal_year=2026,
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
            filed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            known_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
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
            review_status="pending",
            output_hash="0" * 64,
            fact_count=1,
            diagnostics_json="{}",
        )
        self.db.add(run)
        self.db.flush()
        fact = TaiwanFinancialStatementFact(
            filing_id=filing.id,
            parse_run_id=run.id,
            stock_id=stock_id,
            fact_key="basic-eps-2026Q1",
            metric_code="basic_eps",
            source_label="BasicEarningsLossPerShare",
            source_value=Decimal("1.25"),
            source_value_text="1.25",
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
            source_share_basis_id=f"{stock_id}:2026Q1:basis",
            source_restated=False,
            source_restated_status="not_restated",
        )
        self.db.add(fact)
        self.db.flush()
        run.output_hash = (
            "f" * 64 if corrupt_hash else canonical_fact_output_hash([fact])
        )
        self.db.commit()
        return run.id

    def test_apply_is_exact_hash_checked_and_idempotent(self) -> None:
        run_id = self._add_run("2330")
        reviewed_at = datetime(2026, 8, 1, 7, 30, tzinfo=timezone.utc)

        dry_run = review_ci_parse_run_batch(
            self.db,
            stock_ids=["2330"],
            periods=[(2026, 1)],
            reviewer="test:m8-review",
            reviewed_at=reviewed_at,
        )
        self.assertEqual(dry_run["status"], "complete")
        self.assertEqual(
            self.db.query(TaiwanFinancialParseRun).get(run_id).review_status,
            "pending",
        )

        applied = review_ci_parse_run_batch(
            self.db,
            stock_ids=["2330"],
            periods=[(2026, 1)],
            reviewer="test:m8-review",
            reviewed_at=reviewed_at,
            apply=True,
        )
        self.assertEqual(applied["results"][0]["changed_count"], 1)
        self.assertEqual(self.db.query(TaiwanFinancialParseRunReview).count(), 1)

        repeated = review_ci_parse_run_batch(
            self.db,
            stock_ids=["2330"],
            periods=[(2026, 1)],
            reviewer="test:m8-review",
            reviewed_at=reviewed_at,
            apply=True,
        )
        self.assertEqual(repeated["results"][0]["changed_count"], 0)
        self.assertEqual(self.db.query(TaiwanFinancialParseRunReview).count(), 1)

    def test_failure_is_isolated_by_symbol(self) -> None:
        valid_run_id = self._add_run("2303")
        corrupt_run_id = self._add_run("5902", corrupt_hash=True)

        result = review_ci_parse_run_batch(
            self.db,
            stock_ids=["2303", "5902"],
            periods=[(2026, 1)],
            reviewer="test:m8-review",
            reviewed_at=datetime(2026, 8, 1, 7, 30, tzinfo=timezone.utc),
            apply=True,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["succeeded_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(
            self.db.query(TaiwanFinancialParseRun).get(valid_run_id).review_status,
            "approved",
        )
        self.assertEqual(
            self.db.query(TaiwanFinancialParseRun).get(corrupt_run_id).review_status,
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
