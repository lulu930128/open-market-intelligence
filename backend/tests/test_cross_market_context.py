from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CrossMarketSignalSnapshot,
    MarketDailyPrice,
    RawFetchResult,
    ResourceQuoteSnapshot,
    SourceRegistry,
    USDailyPrice,
)
from app.main import app
from app.market.cross_market.context import build_cross_market_target_context
from app.market.cross_market.maintenance import (
    approve_relation,
    create_relation_candidate,
)
from app.market.cross_market.schemas import (
    CrossMarketRelationCandidate,
    CrossMarketRelationEvidenceCandidate,
    CrossMarketTargetContextRead,
    InstrumentRefRead,
)
from app.market.cross_market.snapshot_store import (
    load_latest_cross_market_context_snapshots,
    materialize_cross_market_context_batch,
    materialize_cross_market_context_snapshot,
)
from app.routers.cross_market import get_cross_market_context


DECISION_AT = datetime(2026, 8, 9, 1, 0, tzinfo=timezone.utc)
ADR_TRADE_DATE = date(2026, 8, 7)
VERIFIED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_verified_tsm_relation(db: Session) -> int:
    candidate = CrossMarketRelationCandidate(
        source=InstrumentRefRead(
            market="US",
            instrument_type="adr",
            canonical_symbol="US:TSM",
            provider_symbol="TSM",
            exchange="NYSE",
            currency="USD",
        ),
        target=InstrumentRefRead(
            market="TW",
            instrument_type="stock",
            canonical_symbol="TW:2330",
            provider_symbol="2330",
            exchange="TWSE",
            currency="TWD",
        ),
        relation_type="same_equity_dr",
        relation_subtype="verified_adr",
        bucket="direct_equivalent",
        directionality="equivalent",
        base_weight=1.0,
        confidence_tier="A",
        evidence_grade="official_primary",
        ratio_numerator=1,
        ratio_denominator=5,
        listing_tier="primary",
        valid_from=date(2026, 7, 22),
        verified_at=VERIFIED_AT,
        evidence=[
            CrossMarketRelationEvidenceCandidate(
                source_type="sec_filing",
                source_grade="A",
                source_label="TSMC 2025 Form 20-F",
                source_url="https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm",
                statement="One ADR represents five common shares.",
                verified_at=VERIFIED_AT,
                is_primary=True,
            )
        ],
    )
    row = create_relation_candidate(
        db,
        candidate,
        actor="candidate-author",
        reason="test candidate",
    )
    approved = approve_relation(
        db,
        row.id,
        actor="approver",
        reason="test verified relation",
    )
    return approved.id


def add_tw_daily(db: Session, *, close_price: float = 1000.0) -> None:
    source = SourceRegistry(
        source_name="test-cross-market-context-tw",
        source_type="test",
        category="market_daily_price",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url="https://example.test/tw",
        status_code=200,
        content_hash="cross-market-context-tw",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            trade_date=ADR_TRADE_DATE,
            stock_id="2330",
            stock_name="台積電",
            close_price=close_price,
            created_at=DECISION_AT,
            updated_at=DECISION_AT,
        )
    )
    db.commit()


def add_adr_close(
    db: Session,
    *,
    close_price: float = 200.0,
    fetched_at: datetime = DECISION_AT,
) -> None:
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol="TSM",
            trade_date=ADR_TRADE_DATE,
            close_price=close_price,
            fetched_at=fetched_at,
        )
    )
    db.commit()


def add_fx(
    db: Session,
    *,
    last_price: float = 32.5,
    fetched_at: datetime = DECISION_AT,
) -> None:
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
            last_price=last_price,
            event_time=fetched_at,
            fetched_at=fetched_at,
        )
    )
    db.commit()


class CrossMarketContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_direct_parity_context_is_registry_backed_and_deterministic(self) -> None:
        relation_id = add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)

        first = build_cross_market_target_context(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )
        second = build_cross_market_target_context(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        parsed = CrossMarketTargetContextRead.model_validate(first)
        self.assertEqual(parsed.schema_version, "cross_market.context.v1")
        self.assertEqual(parsed.status, "ready")
        self.assertTrue(parsed.decision_usable)
        self.assertEqual(parsed.relation_snapshot_version, f"relation_registry:{relation_id}:v1")
        self.assertEqual(parsed.snapshot_id, second.snapshot_id)
        self.assertEqual(parsed.summary.stance, "supportive")
        self.assertEqual(parsed.direct_equivalents[0].implied_gap_pct, 30.0)
        self.assertEqual(parsed.signals[0].relation_id, relation_id)
        self.assertEqual(parsed.signals[0].bucket, "direct_equivalent")
        self.assertEqual(parsed.coverage.coverage_ratio, 1.0)
        self.assertFalse(parsed.freshness["read_path_provider_refresh"])

    def test_point_in_time_snapshot_is_idempotent_and_batch_readable(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)

        first = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
        )
        second = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
        )
        batch = materialize_cross_market_context_batch(
            self.db,
            ["2330", "1101", "2330"],
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test-batch",
        )
        loaded = load_latest_cross_market_context_snapshots(
            self.db,
            ["2330", "1101"],
            as_of_at=DECISION_AT,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(
            self.db.query(CrossMarketSignalSnapshot).count(),
            1,
        )
        self.assertEqual(batch["eligible_count"], 1)
        self.assertEqual(batch["reused_count"], 1)
        self.assertFalse(batch["provider_refresh_attempted"])
        self.assertEqual(set(loaded), {"2330"})
        self.assertEqual(loaded["2330"].snapshot_id, first.snapshot_id)
        self.assertTrue(loaded["2330"].decision_usable)

    def test_point_in_time_snapshot_excludes_future_ingestion(self) -> None:
        add_verified_tsm_relation(self.db)
        add_tw_daily(self.db)
        future = DECISION_AT + timedelta(minutes=1)
        add_adr_close(self.db, fetched_at=future)
        add_fx(self.db, fetched_at=future)

        snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
        )
        context = CrossMarketTargetContextRead.model_validate_json(
            snapshot.payload_json
        )

        self.assertEqual(context.status, "partial")
        self.assertFalse(context.decision_usable)
        self.assertIn("us_daily_price.TSM", context.missing)
        self.assertIn("resource_quote_snapshot.USD-TWD", context.missing)

    def test_missing_market_input_is_partial_and_not_decision_usable(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)

        result = build_cross_market_target_context(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(result.status, "partial")
        self.assertFalse(result.decision_usable)
        self.assertIsNone(result.bucket_scores["direct_equivalent"])
        self.assertIn("resource_quote_snapshot.USD-TWD", result.missing)
        self.assertEqual(result.signals[0].quality_multiplier, 0.0)

    def test_legacy_fallback_is_visible_but_limited(self) -> None:
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)

        result = build_cross_market_target_context(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(result.status, "limited")
        self.assertFalse(result.decision_usable)
        self.assertEqual(
            result.direct_equivalents[0].mapping_resolution.selected_source,
            "legacy",
        )
        self.assertIn("legacy_mapping_fallback", result.limitations)

    def test_unmapped_stock_is_not_applicable_without_false_missing(self) -> None:
        result = build_cross_market_target_context(
            self.db,
            "1101",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(result.status, "not_applicable")
        self.assertFalse(result.decision_usable)
        self.assertEqual(result.signals, [])
        self.assertEqual(result.missing, [])

    def test_read_path_executes_no_provider_refresh_or_database_write(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)
        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(statement.strip().upper())

        engine = self.db.get_bind()
        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            with patch(
                "app.us_market.service.refresh_us_daily_prices"
            ) as refresh_provider:
                build_cross_market_target_context(
                    self.db,
                    "2330",
                    decision_at=DECISION_AT,
                    expected_adr_trade_date=ADR_TRADE_DATE,
                )
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)

        refresh_provider.assert_not_called()
        self.assertTrue(statements)
        self.assertFalse(
            any(
                statement.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
                for statement in statements
            )
        )

    def test_context_route_and_openapi_are_read_only(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)

        with (
            patch(
                "app.market.cross_market.context._now",
                return_value=DECISION_AT,
            ),
            patch(
                "app.market.cross_market.context.expected_us_trade_date",
                return_value=ADR_TRADE_DATE,
            ),
        ):
            payload = get_cross_market_context("2330", db=self.db)

        self.assertEqual(payload.status, "ready")
        path_item = app.openapi()["paths"][
            "/api/market/cross-market/context/{stock_id}"
        ]
        self.assertIn("get", path_item)
        self.assertNotIn("post", path_item)
        response_schema = path_item["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            response_schema["$ref"],
            "#/components/schemas/CrossMarketTargetContextRead",
        )

    def test_context_route_rejects_malformed_stock_id(self) -> None:
        with self.assertRaises(HTTPException) as context:
            get_cross_market_context("bad!", db=self.db)

        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
