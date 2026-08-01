from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MonthlyRevenue,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.monthly_revenue_history_backfill import (
    _history_url,
    backfill_monthly_revenue_period_from_cached_raw,
    ensure_stock_monthly_revenue_history,
)


def _html_row(
    stock_id: str,
    stock_name: str,
    monthly_revenue: int,
    cumulative_revenue: int,
) -> str:
    cells = [
        stock_id,
        stock_name,
        f"{monthly_revenue:,}",
        "14,000,000",
        "10,000,000",
        "7.25",
        "47.46",
        f"{cumulative_revenue:,}",
        "52,000,000",
        "27.34",
        "-",
    ]
    return "<tr>" + "".join(f"<td>{value}</td>" for value in cells) + "</tr>"


class MonthlyRevenueCachedPeriodBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        source = SourceRegistry(
            source_name="TWSE Monthly Revenue",
            source_type="official",
            category="monthly_revenue",
            parser_type="monthly_revenue",
            enabled=True,
            priority=10,
            auth_type="none",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        self.source_id = source.id
        self.db.add_all(
            [
                StockMaster(
                    stock_id="2327",
                    stock_name="國巨*",
                    market="TWSE",
                    industry="28",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    industry="24",
                    is_active=True,
                ),
            ]
        )
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            url=_history_url("TWSE", date(2026, 5, 1)),
            method="GET",
            status_code=200,
            content_type="text/html",
            raw_text=(
                "<table>"
                + _html_row("2327", "國巨*", 15_058_220, 67_262_966)
                + _html_row("2330", "台積電", 93_000_000, 430_000_000)
                + "</table>"
            ),
            parser_version="mops-monthly-revenue-history-v1",
        )
        self.db.add(raw)
        self.db.flush()
        self.raw_result_id = raw.id
        self.db.add(
            MonthlyRevenue(
                source_id=source.id,
                raw_result_id=raw.id,
                report_date=date(2026, 5, 1),
                period=date(2026, 5, 1),
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                industry="24",
                monthly_revenue=93_000_000,
                cumulative_revenue=430_000_000,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_dry_run_is_cache_only_and_does_not_write(self) -> None:
        summary = backfill_monthly_revenue_period_from_cached_raw(
            self.db,
            period=date(2026, 5, 1),
            markets=("TWSE",),
            company_types=(0,),
            apply=False,
        )

        self.assertEqual(summary["status"], "dry_run_ready")
        self.assertTrue(summary["cache_only"])
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["inserted_count"], 0)
        self.assertEqual(self.db.query(MonthlyRevenue).count(), 1)
        self.assertEqual(summary["market_results"][0]["existing_count"], 1)

    def test_apply_is_single_transaction_and_idempotent(self) -> None:
        first = backfill_monthly_revenue_period_from_cached_raw(
            self.db,
            period=date(2026, 5, 1),
            markets=("TWSE",),
            company_types=(0,),
            apply=True,
        )
        self.db.commit()
        second = backfill_monthly_revenue_period_from_cached_raw(
            self.db,
            period=date(2026, 5, 1),
            markets=("TWSE",),
            company_types=(0,),
            apply=True,
        )
        self.db.commit()

        self.assertEqual(first["candidate_count"], 1)
        self.assertEqual(first["inserted_count"], 1)
        self.assertEqual(second["candidate_count"], 0)
        self.assertEqual(second["inserted_count"], 0)

        yageo = (
            self.db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.stock_id == "2327")
            .one()
        )
        self.assertEqual(yageo.monthly_revenue, 15_058_220)
        self.assertEqual(yageo.cumulative_revenue, 67_262_966)
        self.assertEqual(yageo.raw_result_id, self.raw_result_id)

    def test_missing_cache_blocks_without_fetching(self) -> None:
        summary = backfill_monthly_revenue_period_from_cached_raw(
            self.db,
            period=date(2026, 4, 1),
            markets=("TWSE",),
            company_types=(0,),
            apply=True,
        )

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["cache_missing_markets"], ["TWSE"])
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(self.db.query(RawFetchResult).count(), 1)

    def test_foreign_company_document_is_a_separate_source_version(self) -> None:
        source = self.db.get(SourceRegistry, self.source_id)
        self.db.add(
            StockMaster(
                stock_id="6415",
                stock_name="矽力*-KY",
                market="TWSE",
                industry="24",
                is_active=True,
            )
        )
        foreign_raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            url=_history_url("TWSE", date(2026, 5, 1), company_type=1),
            method="GET",
            status_code=200,
            content_type="text/html",
            raw_text=(
                "<table>"
                + _html_row("6415", "矽力*-KY", 1_200_000, 5_500_000)
                + "</table>"
            ),
            parser_version="mops-monthly-revenue-history-v1",
        )
        self.db.add(foreign_raw)
        self.db.commit()

        summary = backfill_monthly_revenue_period_from_cached_raw(
            self.db,
            period=date(2026, 5, 1),
            markets=("TWSE",),
            company_types=(1,),
            apply=True,
        )
        self.db.commit()

        self.assertEqual(summary["status"], "applied")
        self.assertEqual(summary["candidate_count"], 1)
        foreign = (
            self.db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.stock_id == "6415")
            .one()
        )
        self.assertEqual(foreign.raw_result_id, foreign_raw.id)

    def test_single_stock_history_falls_back_to_foreign_company_document(
        self,
    ) -> None:
        source = self.db.get(SourceRegistry, self.source_id)
        self.db.add(
            StockMaster(
                stock_id="6415",
                stock_name="矽力*-KY",
                market="TWSE",
                industry="24",
                is_active=True,
            )
        )
        foreign_raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            url=_history_url("TWSE", date(2026, 5, 1), company_type=1),
            method="GET",
            status_code=200,
            content_type="text/html",
            raw_text=(
                "<table>"
                + _html_row("6415", "矽力*-KY", 1_200_000, 5_500_000)
                + "</table>"
            ),
            parser_version="mops-monthly-revenue-history-v1",
        )
        self.db.add(foreign_raw)
        self.db.commit()

        summary = ensure_stock_monthly_revenue_history(
            self.db,
            stock_id="6415",
            from_period=date(2026, 5, 1),
            to_period=date(2026, 5, 1),
            lookback_months=1,
            sleep_seconds=0,
            skip_existing=True,
        )

        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["cached_count"], 2)
        self.assertEqual(summary["fetched_count"], 0)
        self.assertEqual(summary["inserted_count"], 1)
        foreign = (
            self.db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.stock_id == "6415")
            .one()
        )
        self.assertEqual(foreign.raw_result_id, foreign_raw.id)

    def test_explicit_refresh_versions_source_and_updates_changed_business_value(
        self,
    ) -> None:
        refreshed_html = (
            "<table>"
            + _html_row("2327", "國巨*", 15_058_220, 67_262_966)
            + _html_row("2330", "台積電", 94_000_000, 431_000_000)
            + "</table>"
        )
        with patch(
            "app.market.monthly_revenue_history_backfill._fetch_month_html",
            return_value=(refreshed_html, 200, "text/html"),
        ):
            dry_run = backfill_monthly_revenue_period_from_cached_raw(
                self.db,
                period=date(2026, 5, 1),
                markets=("TWSE",),
                company_types=(0,),
                apply=False,
                refresh_documents=True,
                max_fetches=1,
            )

        self.assertEqual(dry_run["insert_candidate_count"], 1)
        self.assertEqual(dry_run["update_candidate_count"], 1)
        self.assertEqual(self.db.query(RawFetchResult).count(), 1)
        existing = (
            self.db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.stock_id == "2330")
            .one()
        )
        self.assertEqual(existing.monthly_revenue, 93_000_000)

        with patch(
            "app.market.monthly_revenue_history_backfill._fetch_month_html",
            return_value=(refreshed_html, 200, "text/html"),
        ):
            applied = backfill_monthly_revenue_period_from_cached_raw(
                self.db,
                period=date(2026, 5, 1),
                markets=("TWSE",),
                company_types=(0,),
                apply=True,
                refresh_documents=True,
                max_fetches=1,
            )
        self.db.commit()

        self.assertEqual(applied["inserted_count"], 1)
        self.assertEqual(applied["updated_count"], 1)
        self.assertEqual(self.db.query(RawFetchResult).count(), 2)
        self.assertEqual(existing.monthly_revenue, 94_000_000)
        self.assertEqual(existing.cumulative_revenue, 431_000_000)


if __name__ == "__main__":
    unittest.main()
