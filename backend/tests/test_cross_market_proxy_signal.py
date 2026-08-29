from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    USDailyPrice,
    USStockMaster,
)
from app.market.cross_market.context import build_cross_market_target_context
from app.market.cross_market.maintenance import (
    approve_relation,
    create_relation_candidate,
)
from app.market.cross_market.schemas import (
    CrossMarketRelationCandidate,
    CrossMarketRelationEvidenceCandidate,
    InstrumentRefRead,
)
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, us_session_close_time


DECISION_AT = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)
EXPECTED_DATE = date(2026, 8, 7)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_proxy_relation(db: Session) -> int:
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
                    "MU and 2408 are used only as a DRAM industry-cycle proxy; "
                    "this is not a supplier, customer, or ownership relation."
                ),
                verified_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            )
        ],
    )
    created = create_relation_candidate(
        db,
        candidate,
        actor="proxy-test-author",
        reason="proxy fixture",
    )
    approved = approve_relation(
        db,
        created.id,
        actor="proxy-test-reviewer",
        reason="reviewed proxy fixture",
    )
    return approved.id


def add_direct_relation_for_2408(db: Session) -> int:
    candidate = CrossMarketRelationCandidate(
        source=InstrumentRefRead(
            market="US",
            instrument_type="adr",
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
        relation_type="same_equity_dr",
        relation_subtype="test_direct_overlap_guard",
        bucket="direct_equivalent",
        directionality="equivalent",
        base_weight=1.0,
        confidence_tier="A",
        evidence_grade="official_primary",
        ratio_numerator=1,
        ratio_denominator=5,
        valid_from=date(2026, 8, 8),
        verified_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        evidence=[
            CrossMarketRelationEvidenceCandidate(
                source_type="test_filing",
                source_grade="A",
                source_label="Direct overlap guard fixture",
                source_url="https://example.test/direct-overlap",
                statement="One test ADR represents five local shares.",
                verified_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
                is_primary=True,
            )
        ],
    )
    created = create_relation_candidate(
        db,
        candidate,
        actor="direct-test-author",
        reason="double-count guard fixture",
    )
    approved = approve_relation(
        db,
        created.id,
        actor="direct-test-reviewer",
        reason="approve double-count guard fixture",
    )
    return approved.id


def add_price_pair(
    db: Session,
    symbol: str,
    *,
    previous_close: float,
    latest_close: float,
) -> None:
    if db.query(USStockMaster).filter(USStockMaster.symbol == symbol).first() is None:
        db.add(
            USStockMaster(
                symbol=symbol,
                exchange="INDEX" if symbol.startswith("^") else "NASDAQ",
                asset_type="index" if symbol.startswith("^") else "stock",
                is_active=True,
            )
        )
    source = SourceRegistry(
        source_name=f"test.canonical.{symbol}",
        source_type="test",
        category="market_data",
    )
    db.add(source)
    db.flush()
    for trade_date, close in (
        (date(2026, 8, 6), previous_close),
        (EXPECTED_DATE, latest_close),
    ):
        content_hash = f"{symbol}-{trade_date.isoformat()}-{close}"
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=DECISION_AT,
            method="GET",
            url=f"https://example.test/us/{symbol}",
            content_hash=content_hash,
            parser_version="test.canonical.v1",
        )
        db.add(raw)
        db.flush()
        db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol=symbol,
                trade_date=trade_date,
                currency="USD",
                open_price=close,
                high_price=close,
                low_price=close,
                close_price=close,
                adjusted_close=close,
                trade_volume=1_000,
                fetched_at=DECISION_AT,
                created_at=DECISION_AT,
                updated_at=DECISION_AT,
                source_id=source.id,
                raw_result_id=raw.id,
                authority="vendor",
                raw_contract_version="test.canonical.v1",
                event_at=datetime.combine(
                    trade_date,
                    us_session_close_time(trade_date),
                    tzinfo=US_MARKET_TIMEZONE,
                ),
                finalization="final",
                price_basis="raw",
                volume_unit="shares",
                volume_status="observed",
                raw_payload_hash=content_hash,
            )
        )
    db.flush()


class CrossMarketProxySignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    def test_mu_proxy_uses_sox_residual_and_non_causal_weighting(self) -> None:
        relation_id = add_proxy_relation(self.db)
        add_price_pair(self.db, "MU", previous_close=100, latest_close=95)
        add_price_pair(self.db, "^SOX", previous_close=100, latest_close=96)

        context = build_cross_market_target_context(
            self.db,
            "2408",
            decision_at=DECISION_AT,
            expected_adr_trade_date=EXPECTED_DATE,
            data_available_at=DECISION_AT,
        )

        self.assertEqual(context.status, "ready")
        self.assertTrue(context.decision_usable)
        self.assertEqual(context.relation_snapshot_version, f"relation_registry:{relation_id}:v1")
        self.assertEqual(len(context.signals), 1)
        signal = context.signals[0]
        self.assertEqual(signal.bucket, "industry_peer")
        self.assertEqual(signal.relation_subtype, "dram_memory_cycle_proxy")
        self.assertEqual(signal.event_context, "unresolved")
        self.assertEqual(signal.calculation["methodology"], "simple_sector_residual")
        self.assertAlmostEqual(signal.calculation["raw_return_pct"], -5.0)
        self.assertAlmostEqual(signal.calculation["benchmark_return_pct"], -4.0)
        self.assertAlmostEqual(signal.calculation["excess_return_pct"], -1.0)
        self.assertAlmostEqual(signal.effective_weight, 0.24)
        self.assertAlmostEqual(signal.contribution, -0.24)
        self.assertAlmostEqual(context.bucket_scores["industry_peer"], -0.24)
        self.assertAlmostEqual(context.coverage.coverage_ratio, 1.0)
        self.assertIn("industry_proxy_not_company_causality", signal.limitations)
        self.assertIn("event_context_unresolved", signal.warnings)
        self.assertIn("industry_peer_residual_negative", context.summary.reason_codes)

    def test_proxy_without_benchmark_exposes_raw_return_but_blocks_score(self) -> None:
        add_proxy_relation(self.db)
        add_price_pair(self.db, "MU", previous_close=100, latest_close=105)

        context = build_cross_market_target_context(
            self.db,
            "2408",
            decision_at=DECISION_AT,
            expected_adr_trade_date=EXPECTED_DATE,
            data_available_at=DECISION_AT,
        )

        signal = context.signals[0]
        self.assertEqual(context.status, "blocked")
        self.assertFalse(context.decision_usable)
        self.assertAlmostEqual(signal.calculation["raw_return_pct"], 5.0)
        self.assertIsNone(signal.calculation["benchmark_return_pct"])
        self.assertIsNone(signal.calculation["excess_return_pct"])
        self.assertEqual(signal.excluded_reason, "benchmark_or_return_missing")
        self.assertEqual(context.bucket_scores["industry_peer"], None)
        self.assertEqual(context.coverage.coverage_ratio, 0.0)
        self.assertIn("us_daily_price.^SOX", context.missing)

    def test_relation_verified_after_decision_at_is_not_visible(self) -> None:
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
            base_weight=0.4,
            confidence_tier="C",
            evidence_grade="industry_mechanism",
            valid_from=DECISION_AT.date(),
            verified_at=DECISION_AT.replace(hour=14),
            evidence=[
                CrossMarketRelationEvidenceCandidate(
                    source_type="company_profile",
                    source_grade="C",
                    source_label="future review",
                    source_url="https://www.nanya.com/en/About",
                    statement="future-verified industry proxy",
                    verified_at=DECISION_AT.replace(hour=14),
                )
            ],
        )
        created = create_relation_candidate(
            self.db,
            candidate,
            actor="future-author",
            reason="future relation",
        )
        approve_relation(
            self.db,
            created.id,
            actor="future-reviewer",
            reason="future approval",
        )

        context = build_cross_market_target_context(
            self.db,
            "2408",
            decision_at=DECISION_AT,
            expected_adr_trade_date=EXPECTED_DATE,
            data_available_at=DECISION_AT,
        )

        self.assertEqual(context.status, "not_applicable")
        self.assertEqual(context.signals, [])
        self.assertEqual(context.relation_snapshot_version, "relation_registry:none")

    def test_direct_source_cannot_be_counted_again_as_proxy(self) -> None:
        add_direct_relation_for_2408(self.db)
        add_proxy_relation(self.db)
        add_price_pair(self.db, "MU", previous_close=100, latest_close=105)
        add_price_pair(self.db, "^SOX", previous_close=100, latest_close=100)

        context = build_cross_market_target_context(
            self.db,
            "2408",
            decision_at=DECISION_AT,
            expected_adr_trade_date=EXPECTED_DATE,
            data_available_at=DECISION_AT,
        )

        proxy = next(
            signal for signal in context.signals if signal.bucket == "industry_peer"
        )
        self.assertEqual(proxy.status, "blocked")
        self.assertFalse(proxy.decision_usable)
        self.assertIsNone(proxy.contribution)
        self.assertEqual(proxy.excluded_reason, "duplicate_direct_source")
        self.assertIn("duplicate_direct_source", proxy.warnings)
        self.assertEqual(
            context.coverage.excluded_by_reason["duplicate_direct_source"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
