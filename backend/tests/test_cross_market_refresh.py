from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CrossMarketRelation,
    CrossMarketRelationEvidence,
    ResourceQuoteSnapshot,
    USDailyPrice,
)
from app.jobs import backfill_tasks
from app.jobs.job_types import CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE
from app.market.cross_market.refresh import (
    build_cross_market_refresh_plan,
    normalize_refresh_stock_ids,
    refresh_cross_market_context_sources,
)
from app.market.cross_market.maintenance import approve_relation, create_relation_candidate
from app.market.cross_market.schemas import (
    CrossMarketRelationCandidate,
    CrossMarketRelationEvidenceCandidate,
    InstrumentRefRead,
)
from app.routers import jobs as jobs_router
from app.routers.cross_market import refresh_cross_market_context


NOW = datetime(2026, 8, 9, 1, tzinfo=timezone.utc)
EXPECTED_DATE = date(2026, 8, 7)
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_relation(db: Session) -> None:
    relation = CrossMarketRelation(
        source_market="US",
        source_instrument_type="adr",
        source_canonical_symbol="US:TSM",
        source_provider_symbol="TSM",
        source_exchange="NYSE",
        source_currency="USD",
        target_market="TW",
        target_instrument_type="stock",
        target_canonical_symbol="TW:2330",
        target_provider_symbol="2330",
        target_exchange="TWSE",
        target_currency="TWD",
        relation_type="same_equity_dr",
        relation_subtype="verified_adr",
        bucket="direct_equivalent",
        directionality="equivalent",
        base_weight=Decimal("1"),
        confidence_tier="A",
        evidence_grade="official_primary",
        ratio_numerator=Decimal("1"),
        ratio_denominator=Decimal("5"),
        listing_tier="primary",
        valid_from=date(2026, 7, 22),
        verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        review_status="approved",
        is_active=True,
        version=1,
        created_by="test",
        reviewed_by="test",
        reviewed_at=NOW,
        change_reason="test relation",
    )
    relation.evidence = [
        CrossMarketRelationEvidence(
            source_type="sec_filing",
            source_grade="A",
            source_label="TSMC 2025 Form 20-F",
            source_url=SOURCE_URL,
            statement="One ADR represents five common shares.",
            verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            content_hash="d" * 64,
            is_primary=True,
            review_status="approved",
            created_by="test",
            reviewed_by="test",
            reviewed_at=NOW,
        )
    ]
    db.add(relation)
    db.commit()


def add_current_sources(db: Session) -> None:
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol="TSM",
            trade_date=EXPECTED_DATE,
            close_price=200,
            fetched_at=NOW,
        )
    )
    db.add(
        ResourceQuoteSnapshot(
            provider="yahoo_chart",
            exchange="CCY",
            symbol="USD-TWD",
            provider_symbol="USDTWD=X",
            name="USD/TWD",
            root_folder="currency",
            group="fx",
            asset_class="currency",
            base_asset="USD",
            quote_asset="TWD",
            instrument_type="currency_pair",
            contract_key="spot",
            last_price=32.5,
            event_time=NOW,
            fetched_at=NOW,
        )
    )
    db.commit()


def add_proxy_relation(db: Session) -> None:
    candidate = CrossMarketRelationCandidate(
        source=InstrumentRefRead(
            market="US",
            instrument_type="stock",
            canonical_symbol="US:MU",
            provider_symbol="MU",
            exchange="NASDAQ",
            currency="USD",
        ),
        target=InstrumentRefRead(
            market="TW",
            instrument_type="stock",
            canonical_symbol="TW:2408",
            provider_symbol="2408",
            exchange="TWSE",
            currency="TWD",
        ),
        relation_type="industry_peer",
        relation_subtype="dram_memory_cycle_proxy",
        bucket="industry_peer",
        directionality="positive",
        base_weight=0.4,
        confidence_tier="C",
        evidence_grade="industry_mechanism",
        valid_from=date(2026, 8, 8),
        verified_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        evidence=[
            CrossMarketRelationEvidenceCandidate(
                source_type="company_profile",
                source_grade="C",
                source_label="Official DRAM company profiles",
                source_url="https://www.nanya.com/en/About",
                statement=(
                    "MU and 2408 are only an industry-cycle proxy, not a "
                    "company-specific causal relation."
                ),
                verified_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            )
        ],
    )
    created = create_relation_candidate(
        db,
        candidate,
        actor="refresh-test-author",
        reason="proxy refresh fixture",
    )
    approve_relation(
        db,
        created.id,
        actor="refresh-test-reviewer",
        reason="reviewed proxy refresh fixture",
    )


class CrossMarketRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_relation(self.db)

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_normalization_deduplicates_and_validates_stock_ids(self) -> None:
        self.assertEqual(normalize_refresh_stock_ids("2330, 2330"), ["2330"])
        with self.assertRaisesRegex(ValueError, "stock_id"):
            normalize_refresh_stock_ids("bad!")

    @patch(
        "app.market.cross_market.refresh.expected_us_trade_date",
        return_value=EXPECTED_DATE,
    )
    def test_plan_caps_sources_and_reports_deferred_work(self, _expected) -> None:
        plan = build_cross_market_refresh_plan(
            self.db,
            ["2330", "2330"],
            max_symbols=1,
            now=NOW,
        )

        self.assertEqual(plan["requested_stock_ids"], ["2330"])
        self.assertEqual(plan["requested_source_count"], 2)
        self.assertEqual(plan["planned_source_count"], 1)
        self.assertEqual(plan["deferred_source_count"], 1)
        self.assertEqual(plan["planned_sources"][0]["symbol"], "USD-TWD")
        self.assertEqual(plan["deferred_sources"][0]["symbol"], "TSM")

    @patch(
        "app.market.cross_market.refresh.expected_us_trade_date",
        return_value=EXPECTED_DATE,
    )
    def test_current_sources_produce_no_refresh_plan(self, _expected) -> None:
        add_current_sources(self.db)

        plan = build_cross_market_refresh_plan(
            self.db,
            "2330",
            now=NOW,
        )
        self.assertEqual(plan["planned_sources"], [])
        self.assertEqual(plan["requested_source_count"], 0)

    @patch(
        "app.market.cross_market.refresh.expected_us_trade_date",
        return_value=EXPECTED_DATE,
    )
    def test_plan_includes_proxy_source_and_benchmark_without_fx(self, _expected) -> None:
        add_proxy_relation(self.db)

        plan = build_cross_market_refresh_plan(
            self.db,
            "2408",
            now=NOW,
        )

        planned_by_symbol = {
            item["symbol"]: item for item in plan["planned_sources"]
        }
        self.assertEqual(set(planned_by_symbol), {"MU", "^SOX"})
        self.assertEqual(planned_by_symbol["MU"]["roles"], ["proxy_source"])
        self.assertEqual(
            planned_by_symbol["^SOX"]["roles"],
            ["proxy_benchmark"],
        )
        self.assertEqual(plan["missing_relations"], [])

    @patch(
        "app.market.cross_market.refresh.expected_us_trade_date",
        return_value=EXPECTED_DATE,
    )
    @patch("app.market.cross_market.refresh.resource_market_service.refresh_resource_quotes")
    @patch("app.market.cross_market.refresh.us_market_service.refresh_us_daily_prices")
    def test_worker_is_bounded_and_isolates_provider_results(
        self,
        refresh_us,
        refresh_resource,
        _expected,
    ) -> None:
        refresh_resource.return_value = {
            "status": "success",
            "refreshed_count": 1,
            "error_count": 0,
        }
        refresh_us.return_value = {
            "status": "success",
            "symbol": "TSM",
        }
        progress: list[tuple[int | None, int | None, str | None]] = []

        result = refresh_cross_market_context_sources(
            self.db,
            "2330",
            max_symbols=2,
            max_runtime_seconds=30,
            progress_callback=lambda current, total, message: progress.append(
                (current, total, message)
            ),
            now=NOW,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        refresh_resource.assert_called_once_with(self.db, symbols="USD-TWD")
        refresh_us.assert_called_once_with(
            db=self.db,
            symbol="TSM",
            outputsize="compact",
            adjusted=False,
            provider="auto",
        )
        self.assertEqual(progress[-1][0], 2)

    @patch(
        "app.market.cross_market.refresh.expected_us_trade_date",
        return_value=EXPECTED_DATE,
    )
    @patch("app.market.cross_market.refresh.resource_market_service.refresh_resource_quotes")
    @patch(
        "app.market.cross_market.refresh.us_market_service.refresh_us_daily_prices",
        side_effect=RuntimeError("provider timeout"),
    )
    def test_worker_keeps_partial_failure_visible(
        self,
        _refresh_us,
        refresh_resource,
        _expected,
    ) -> None:
        refresh_resource.return_value = {
            "status": "success",
            "refreshed_count": 1,
            "error_count": 0,
        }

        result = refresh_cross_market_context_sources(
            self.db,
            "2330",
            max_symbols=2,
            max_runtime_seconds=30,
            now=NOW,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("provider timeout", result["results"][1]["error"])

    def test_refresh_route_enqueues_deduplicable_job_contract(self) -> None:
        fake_job = {
            "id": 1,
            "job_type": CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE,
            "status": "queued",
        }
        with patch(
            "app.routers.cross_market.enqueue_serialized_job",
            return_value=fake_job,
        ) as enqueue:
            result = refresh_cross_market_context(
                stock_ids="2330,2330",
                max_symbols=8,
                provider="auto",
                outputsize="compact",
                max_runtime_seconds=120,
                db=self.db,
            )

        self.assertEqual(result, fake_job)
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["job_type"], CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE)
        self.assertEqual(kwargs["target"], "2330")
        self.assertEqual(kwargs["request"]["stock_ids"], ["2330"])
        self.assertIs(
            kwargs["task"],
            backfill_tasks.run_cross_market_context_refresh_job,
        )

    def test_job_retry_reconstructs_bounded_refresh_request(self) -> None:
        request = {
            "stock_ids": ["2330"],
            "max_symbols": 4,
            "provider": "yahoo_chart",
            "outputsize": "compact",
            "max_runtime_seconds": 60,
        }
        job = SimpleNamespace(
            job_type=CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE,
            target="2330",
        )
        with patch.object(
            jobs_router.service,
            "serialize_job",
            return_value={"request": request},
        ):
            task, task_args, parsed_request = jobs_router._retry_config(job)

        self.assertIs(task, backfill_tasks.run_cross_market_context_refresh_job)
        self.assertEqual(
            task_args,
            (["2330"], 4, "yahoo_chart", "compact", 60),
        )
        self.assertEqual(parsed_request, request)


if __name__ == "__main__":
    unittest.main()
