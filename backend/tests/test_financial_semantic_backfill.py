from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    FinancialMetricQuarterly,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialStatementFact,
)
from app.market.financial_semantic_backfill import (
    backfill_legacy_financial_semantics,
)


class FinancialSemanticBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        source = SourceRegistry(
            source_name="legacy-financial-test",
            source_type="official",
            category="financial",
            enabled=True,
            priority=100,
            auth_type="none",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            url="https://openapi.twse.com.tw/v1/opendata/test",
            method="GET",
            content_hash="legacy-2327-q2",
            parser_version="financial-metrics-v2",
        )
        self.db.add(raw)
        self.db.flush()
        self.db.add(
            FinancialMetricQuarterly(
                source_id=source.id,
                raw_result_id=raw.id,
                report_date=None,
                released_at=None,
                filed_at=None,
                fiscal_year=2025,
                quarter=2,
                period="2025Q2",
                stock_id="2327",
                stock_name="國巨",
                market="TWSE",
                revenue=63_875_083,
                gross_profit=20_000_000,
                operating_income=12_000_000,
                net_income=10_527_349,
                net_income_attributable_parent=10_527_349,
                eps=20.51,
                total_assets=300_000_000,
                total_equity=150_000_000,
                parent_equity=145_000_000,
                book_value_per_share=285.78,
                roe=7.26,
                roa=3.51,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_dry_run_is_bounded_and_does_not_write(self) -> None:
        summary = backfill_legacy_financial_semantics(
            self.db,
            stock_ids=("2327",),
            limit=10,
            apply=False,
        )

        self.assertEqual(summary["legacy_rows_selected"], 1)
        self.assertEqual(summary["filings_created"], 1)
        self.assertEqual(summary["facts_created"], 10)
        self.assertEqual(summary["normalization_ready_rows"], 0)
        self.assertEqual(summary["normalization_blocked_rows"], 1)
        self.assertEqual(self.db.query(TaiwanFinancialFiling).count(), 0)
        self.assertEqual(self.db.query(TaiwanFinancialStatementFact).count(), 0)

    def test_apply_preserves_raw_semantics_and_is_idempotent(self) -> None:
        first = backfill_legacy_financial_semantics(
            self.db,
            stock_ids=("2327",),
            limit=10,
            apply=True,
        )
        self.db.commit()
        second = backfill_legacy_financial_semantics(
            self.db,
            stock_ids=("2327",),
            limit=10,
            apply=True,
        )
        self.db.commit()

        self.assertEqual(first["filings_created"], 1)
        self.assertEqual(first["facts_created"], 10)
        self.assertEqual(second["filings_created"], 0)
        self.assertEqual(second["filings_existing"], 1)
        self.assertEqual(second["facts_created"], 0)
        self.assertEqual(second["facts_existing"], 10)

        filing = self.db.query(TaiwanFinancialFiling).one()
        self.assertIsNone(filing.announced_at)
        self.assertIsNone(filing.filed_at)
        self.assertIsNone(filing.known_at)
        self.assertEqual(filing.period_end.isoformat(), "2025-06-30")

        eps = (
            self.db.query(TaiwanFinancialStatementFact)
            .filter(TaiwanFinancialStatementFact.metric_code == "basic_eps")
            .one()
        )
        self.assertEqual(eps.period_kind, "duration")
        self.assertEqual(eps.period_scope, "ytd_6m")
        self.assertEqual(eps.source_unit, "TWD_per_share")
        self.assertEqual(eps.source_restated_status, "unknown")
        self.assertIsNone(eps.source_share_basis_id)

        assets = (
            self.db.query(TaiwanFinancialStatementFact)
            .filter(TaiwanFinancialStatementFact.metric_code == "total_assets")
            .one()
        )
        self.assertEqual(assets.period_kind, "instant")
        self.assertEqual(assets.period_scope, "instant_period_end")
        self.assertIsNone(assets.months_covered)
        self.assertEqual(
            self.db.query(TaiwanFinancialStatementFact)
            .filter(TaiwanFinancialStatementFact.metric_code.in_(("roe", "roa")))
            .count(),
            0,
        )

    def test_limit_guard_rejects_unbounded_request(self) -> None:
        with self.assertRaises(ValueError):
            backfill_legacy_financial_semantics(
                self.db,
                limit=10_001,
                apply=False,
            )


if __name__ == "__main__":
    unittest.main()
