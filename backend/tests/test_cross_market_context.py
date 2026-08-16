from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
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
    read_cross_market_target_context,
)
from app.routers.cross_market import get_cross_market_context


DECISION_AT = datetime(2026, 8, 9, 1, 0, tzinfo=timezone.utc)
ADR_TRADE_DATE = date(2026, 8, 7)
VERIFIED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)
MATERIALIZED_AT = DECISION_AT + timedelta(minutes=5)


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


def add_tw_daily(
    db: Session,
    *,
    close_price: float = 1000.0,
    trade_date: date = ADR_TRADE_DATE,
    available_at: datetime = DECISION_AT,
) -> None:
    source = SourceRegistry(
        source_name=f"test-cross-market-context-tw-{trade_date.isoformat()}",
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
        content_hash=f"cross-market-context-tw-{trade_date.isoformat()}",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            trade_date=trade_date,
            stock_id="2330",
            stock_name="台積電",
            close_price=close_price,
            created_at=available_at,
            updated_at=available_at,
        )
    )
    db.commit()


def add_adr_close(
    db: Session,
    *,
    close_price: float = 200.0,
    trade_date: date = ADR_TRADE_DATE,
    fetched_at: datetime = DECISION_AT,
) -> None:
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol="TSM",
            trade_date=trade_date,
            close_price=close_price,
            fetched_at=fetched_at,
        )
    )
    db.commit()


def add_fx(
    db: Session,
    *,
    last_price: float = 32.5,
    event_time: datetime = datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
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
            event_time=event_time,
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
        self.assertEqual(parsed.projection_source, "latest_local_cache")
        self.assertEqual(parsed.source_cutoff_at, DECISION_AT)
        self.assertIsNone(parsed.materialized_at)
        self.assertIsNone(parsed.payload_hash)
        self.assertEqual(
            parsed.freshness["projection_source"],
            "latest_local_cache",
        )
        self.assertTrue(parsed.freshness["input_lineage_hash"])
        self.assertEqual(
            parsed.freshness["input_lineage_hash"],
            parsed.evidence_passport["input_lineage_hash"],
        )
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
            materialized_at=MATERIALIZED_AT,
        )
        second = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
            materialized_at=MATERIALIZED_AT + timedelta(minutes=1),
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
        self.assertEqual(
            loaded["2330"].projection_source,
            "materialized_snapshot",
        )
        self.assertEqual(loaded["2330"].source_cutoff_at, DECISION_AT)
        self.assertEqual(loaded["2330"].materialized_at, MATERIALIZED_AT)
        self.assertEqual(loaded["2330"].materialized_by, "test")
        self.assertEqual(loaded["2330"].payload_hash, first.payload_hash)
        self.assertEqual(
            loaded["2330"].evidence_passport["payload_hash"],
            first.payload_hash,
        )
        self.assertEqual(
            loaded["2330"].freshness["input_lineage_hash"],
            loaded["2330"].evidence_passport["input_lineage_hash"],
        )
        self.assertNotIn(
            "latest_local_cache_projection_not_materialized_snapshot",
            loaded["2330"].limitations,
        )
        self.assertEqual(
            load_latest_cross_market_context_snapshots(
                self.db,
                ["2330"],
                as_of_at=MATERIALIZED_AT,
                exact_decision_at=DECISION_AT + timedelta(seconds=1),
            ),
            {},
        )

    def test_batch_rethrows_sqlite_lock_for_outer_transaction_retry(self) -> None:
        add_verified_tsm_relation(self.db)
        locked = OperationalError(
            "INSERT cross_market_signal_snapshot",
            {},
            Exception("database is locked"),
        )

        with patch(
            "app.market.cross_market.snapshot_store."
            "materialize_cross_market_context_snapshot",
            side_effect=locked,
        ):
            with self.assertRaises(OperationalError) as raised:
                materialize_cross_market_context_batch(
                    self.db,
                    ["2330"],
                    decision_at=DECISION_AT,
                    materialized_by="test-lock",
                )

        self.assertIs(raised.exception, locked)

    def test_snapshot_identity_is_immutable_when_source_data_changes(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)
        snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
            materialized_at=MATERIALIZED_AT,
        )
        original_payload = snapshot.payload_json
        self.db.commit()

        adr = self.db.query(USDailyPrice).filter(USDailyPrice.symbol == "TSM").one()
        adr.close_price = 250.0
        self.db.commit()

        with self.assertRaisesRegex(RuntimeError, "non-deterministic"):
            materialize_cross_market_context_snapshot(
                self.db,
                "2330",
                decision_at=DECISION_AT,
                expected_adr_trade_date=ADR_TRADE_DATE,
                materialized_by="changed-source-retry",
                materialized_at=MATERIALIZED_AT + timedelta(minutes=10),
            )

        stored = self.db.query(CrossMarketSignalSnapshot).one()
        self.assertEqual(stored.payload_json, original_payload)
        self.assertEqual(stored.materialized_at, MATERIALIZED_AT.replace(tzinfo=None))

    def test_snapshot_resolver_rejects_tamper_and_falls_back_to_latest_cache(self) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)
        snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="test",
            materialized_at=MATERIALIZED_AT,
        )
        payload = json.loads(snapshot.payload_json)
        payload["summary"]["title"] = "tampered"
        snapshot.payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.db.commit()

        loaded = load_latest_cross_market_context_snapshots(
            self.db,
            ["2330"],
            as_of_at=MATERIALIZED_AT,
        )
        resolved = read_cross_market_target_context(
            self.db,
            "2330",
            as_of_at=MATERIALIZED_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(loaded, {})
        self.assertEqual(resolved.projection_source, "latest_local_cache")
        self.assertIn(
            "latest_local_cache_projection_not_materialized_snapshot",
            resolved.limitations,
        )

    def test_current_read_uses_newer_local_inputs_without_breaking_replay(self) -> None:
        add_verified_tsm_relation(self.db)
        old_trade_date = date(2026, 8, 4)
        old_decision_at = datetime(2026, 8, 5, 1, tzinfo=timezone.utc)
        add_adr_close(
            self.db,
            trade_date=old_trade_date,
            fetched_at=old_decision_at,
        )
        add_tw_daily(
            self.db,
            trade_date=old_trade_date,
            available_at=old_decision_at,
        )
        add_fx(
            self.db,
            event_time=datetime(2026, 8, 4, 20, tzinfo=timezone.utc),
            fetched_at=old_decision_at,
        )
        old_snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=old_decision_at,
            expected_adr_trade_date=old_trade_date,
            materialized_by="historical-test",
            materialized_at=old_decision_at + timedelta(minutes=5),
        )
        self.db.commit()

        add_adr_close(
            self.db,
            trade_date=ADR_TRADE_DATE,
            fetched_at=DECISION_AT,
        )
        add_tw_daily(
            self.db,
            trade_date=ADR_TRADE_DATE,
            available_at=DECISION_AT,
        )
        fx = self.db.query(ResourceQuoteSnapshot).one()
        fx.event_time = datetime(2026, 8, 7, 20, tzinfo=timezone.utc)
        fx.fetched_at = DECISION_AT
        self.db.commit()

        current = read_cross_market_target_context(
            self.db,
            "2330",
            as_of_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )
        replay = read_cross_market_target_context(
            self.db,
            "2330",
            as_of_at=old_decision_at,
            expected_adr_trade_date=old_trade_date,
            projection_mode="replay",
        )

        self.assertEqual(current.projection_source, "latest_local_cache")
        self.assertEqual(current.as_of, ADR_TRADE_DATE)
        self.assertNotEqual(current.snapshot_id, old_snapshot.snapshot_id)
        self.assertIn(
            "materialized_snapshot_superseded_by_local_inputs",
            current.limitations,
        )
        self.assertEqual(replay.projection_source, "materialized_snapshot")
        self.assertEqual(replay.snapshot_id, old_snapshot.snapshot_id)
        self.assertEqual(replay.as_of, old_trade_date)
        self.assertEqual(self.db.query(CrossMarketSignalSnapshot).count(), 1)

    def test_current_read_reuses_materialized_snapshot_when_lineage_is_unchanged(
        self,
    ) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)
        snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="same-lineage-test",
            materialized_at=MATERIALIZED_AT,
        )
        self.db.commit()

        current = read_cross_market_target_context(
            self.db,
            "2330",
            as_of_at=MATERIALIZED_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(current.projection_source, "latest_local_cache")
        self.assertNotEqual(current.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(
            current.freshness["matching_materialized_snapshot"]["snapshot_id"],
            snapshot.snapshot_id,
        )
        self.assertNotIn(
            "materialized_snapshot_superseded_by_local_inputs",
            current.limitations,
        )
        self.assertEqual(self.db.query(CrossMarketSignalSnapshot).count(), 1)

    def test_current_read_keeps_session_aligned_fx_usable_as_wall_clock_ages(
        self,
    ) -> None:
        add_verified_tsm_relation(self.db)
        add_adr_close(self.db)
        add_tw_daily(self.db)
        add_fx(self.db)
        snapshot = materialize_cross_market_context_snapshot(
            self.db,
            "2330",
            decision_at=DECISION_AT,
            expected_adr_trade_date=ADR_TRADE_DATE,
            materialized_by="freshness-aging-test",
            materialized_at=MATERIALIZED_AT,
        )
        self.db.commit()

        current = read_cross_market_target_context(
            self.db,
            "2330",
            as_of_at=DECISION_AT + timedelta(hours=73),
            expected_adr_trade_date=ADR_TRADE_DATE,
        )

        self.assertEqual(current.projection_source, "latest_local_cache")
        self.assertEqual(current.status, "ready")
        self.assertTrue(current.decision_usable)
        self.assertNotEqual(current.snapshot_id, snapshot.snapshot_id)
        self.assertNotIn(
            "materialized_snapshot_superseded_by_local_inputs",
            current.limitations,
        )
        self.assertIn(
            "latest_local_cache_projection_not_materialized_snapshot",
            current.limitations,
        )
        self.assertEqual(self.db.query(CrossMarketSignalSnapshot).count(), 1)

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
