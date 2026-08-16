from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CrossMarketRelation,
    CrossMarketRelationEvidence,
    MarketDailyPrice,
    RawFetchResult,
    ResourceOhlcvBar,
    ResourceQuoteSnapshot,
    SourceRegistry,
    StockMaster,
    USDailyPrice,
)
from app.market.adr_parity import (
    ADR_MAPPINGS,
    build_adr_parity_report,
    calculate_implied_tw_price,
)
from app.market.overnight_impact import (
    build_us_overnight_impact_report,
    scan_us_overnight_impact_gaps,
)
from app.market.schemas import AdrParityRead, OvernightImpactRead


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_tw_daily(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
    close_price: float,
) -> None:
    source = SourceRegistry(
        source_name=f"test-tw-{stock_id}-{trade_date.isoformat()}",
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
        content_hash=f"{stock_id}-{trade_date.isoformat()}",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="台積電",
            close_price=close_price,
        )
    )
    db.commit()


def add_fx(
    db: Session,
    *,
    symbol: str = "USD-TWD",
    last_price: float = 32.5,
    event_time: datetime = datetime(2026, 6, 5, 20, tzinfo=timezone.utc),
) -> None:
    db.add(
        ResourceQuoteSnapshot(
            provider="yahoo_chart",
            exchange="CCY",
            symbol=symbol,
            provider_symbol="USDTWD=X" if symbol == "USD-TWD" else "TWDUSD=X",
            name=symbol,
            root_folder="currency",
            group="fx",
            asset_class="currency",
            base_asset="USD" if symbol == "USD-TWD" else "TWD",
            quote_asset="TWD" if symbol == "USD-TWD" else "USD",
            instrument_type="currency_pair",
            contract_key="spot",
            last_price=last_price,
            event_time=event_time,
            fetched_at=event_time,
        )
    )
    db.commit()


def add_approved_adr_relation(
    db: Session,
    *,
    ratio_denominator: int = 5,
    source_url: str = "https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm",
) -> CrossMarketRelation:
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
        ratio_denominator=Decimal(str(ratio_denominator)),
        listing_tier="primary",
        valid_from=date(2026, 7, 22),
        verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        review_status="approved",
        is_active=True,
        version=1,
        created_by="test",
        reviewed_by="test",
        reviewed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        change_reason="test registry relation",
    )
    relation.evidence = [
        CrossMarketRelationEvidence(
            source_type="sec_filing",
            source_grade="A",
            source_label="TSMC 2025 Form 20-F",
            source_url=source_url,
            statement="One ADR represents common shares.",
            verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            content_hash="c" * 64,
            is_primary=True,
            review_status="approved",
            created_by="test",
            reviewed_by="test",
            reviewed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    ]
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


class AdrParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_registry_contains_verified_direct_technology_adr_pairs(self) -> None:
        self.assertEqual(
            {
                stock_id: (mapping.adr_symbol, mapping.local_shares_per_adr)
                for stock_id, mapping in ADR_MAPPINGS.items()
            },
            {
                "2330": ("TSM", 5),
                "2303": ("UMC", 5),
                "3711": ("ASX", 2),
                "8150": ("IMOS", 20),
            },
        )
        self.assertTrue(all(mapping.source_url for mapping in ADR_MAPPINGS.values()))

    def test_formula_rejects_invalid_inputs(self) -> None:
        self.assertEqual(
            calculate_implied_tw_price(
                adr_close_usd=200.0,
                usd_twd=32.5,
                local_shares_per_adr=5,
            ),
            1300.0,
        )
        with self.assertRaises(ValueError):
            calculate_implied_tw_price(
                adr_close_usd=0,
                usd_twd=32.5,
                local_shares_per_adr=5,
            )

    def test_report_uses_raw_adr_close_and_aligned_tw_reference(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="TSM",
                trade_date=date(2026, 6, 5),
                close_price=200.0,
                adjusted_close=150.0,
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="2330",
            trade_date=date(2026, 6, 5),
            close_price=1000.0,
        )
        add_tw_daily(
            self.db,
            stock_id="2330",
            trade_date=date(2026, 6, 8),
            close_price=1250.0,
        )
        add_fx(self.db)

        report = build_adr_parity_report(
            self.db,
            "2330",
            expected_adr_trade_date=date(2026, 6, 5),
            generated_at=datetime(2026, 6, 8, 12, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["adr_close_usd"], 200.0)
        self.assertEqual(report["tw_reference_trade_date"], "2026-06-05")
        self.assertIn(
            "aligned_gap_baseline",
            report["tw_reference_semantics"],
        )
        self.assertEqual(report["target_tw_trade_date"], "2026-06-08")
        self.assertEqual(report["implied_tw_price_twd"], 1300.0)
        self.assertEqual(report["implied_gap_pct"], 30.0)
        self.assertEqual(report["tw_comparison_price_twd"], 1250.0)
        self.assertIn(
            "remaining_gap",
            report["tw_comparison_semantics"],
        )
        self.assertEqual(report["remaining_gap_pct"], 4.0)
        self.assertEqual(report["comparison_mode"], "target_session_review")
        self.assertEqual(AdrParityRead.model_validate(report).mapping.adr_symbol, "TSM")

    def test_exact_trade_date_fx_remains_usable_after_wall_clock_exceeds_72h(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="ASX",
                trade_date=date(2026, 8, 7),
                close_price=12.0,
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="3711",
            trade_date=date(2026, 8, 7),
            close_price=180.0,
        )
        add_fx(
            self.db,
            event_time=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
        )

        report = build_adr_parity_report(
            self.db,
            "3711",
            expected_adr_trade_date=date(2026, 8, 7),
            generated_at=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        )

        assert report is not None
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["freshness"]["fx_is_current"])
        self.assertEqual(report["freshness"]["fx"]["status"], "current")
        self.assertGreater(report["fx_age_seconds"], 72 * 60 * 60)

    def test_adr_parity_prefers_trade_date_daily_fx_over_later_spot(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="ASX",
                trade_date=date(2026, 8, 7),
                close_price=12.0,
            )
        )
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="FX",
                symbol="USD-TWD",
                provider_symbol="USDTWD=X",
                name="USD/TWD",
                root_folder="currency",
                group="foreign_to_twd",
                asset_class="foreign_exchange",
                base_asset="USD",
                quote_asset="TWD",
                instrument_type="spot",
                contract_key="spot",
                interval="1d",
                bar_time=datetime(2026, 8, 6, 23, tzinfo=timezone.utc),
                close_price=32.5,
                raw_payload_json=json.dumps(
                    {"exchange_timezone_name": "Europe/London"}
                ),
                fetched_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="3711",
            trade_date=date(2026, 8, 7),
            close_price=180.0,
        )
        add_fx(
            self.db,
            last_price=40.0,
            event_time=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        )

        report = build_adr_parity_report(
            self.db,
            "3711",
            expected_adr_trade_date=date(2026, 8, 7),
            generated_at=datetime(2026, 8, 10, 13, tzinfo=timezone.utc),
        )

        assert report is not None
        self.assertEqual(report["usd_twd"], 32.5)
        self.assertEqual(
            report["freshness"]["input_lineage"]["fx_quote"]["source_resource"],
            "resource_ohlcv_bar.1d",
        )
        self.assertEqual(report["status"], "ready")

    def test_matching_registry_mapping_becomes_primary_with_relation_lineage(self) -> None:
        relation = add_approved_adr_relation(self.db)
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="TSM",
                trade_date=date(2026, 8, 7),
                close_price=200.0,
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="2330",
            trade_date=date(2026, 8, 7),
            close_price=1000.0,
        )
        add_fx(
            self.db,
            event_time=datetime(2026, 8, 9, 0, tzinfo=timezone.utc),
        )

        report = build_adr_parity_report(
            self.db,
            "2330",
            expected_adr_trade_date=date(2026, 8, 7),
            generated_at=datetime(2026, 8, 9, 1, tzinfo=timezone.utc),
        )

        assert report is not None
        resolution = report["mapping_resolution"]
        self.assertEqual(resolution["selected_source"], "registry")
        self.assertEqual(resolution["shadow_status"], "match")
        self.assertEqual(resolution["relation_id"], relation.id)
        self.assertEqual(resolution["relation_version"], 1)
        self.assertEqual(resolution["evidence_ids"], [relation.evidence[0].id])
        self.assertEqual(report["mapping"]["local_shares_per_adr"], 5)

    def test_registry_shadow_mismatch_keeps_legacy_mapping_and_warns(self) -> None:
        relation = add_approved_adr_relation(self.db, ratio_denominator=4)

        report = build_adr_parity_report(
            self.db,
            "2330",
            generated_at=datetime(2026, 8, 9, 1, tzinfo=timezone.utc),
        )

        assert report is not None
        resolution = report["mapping_resolution"]
        self.assertEqual(resolution["selected_source"], "legacy")
        self.assertEqual(resolution["shadow_status"], "mismatch")
        self.assertIn("local_shares_per_adr", resolution["shadow_differences"])
        self.assertEqual(resolution["relation_id"], relation.id)
        self.assertEqual(report["mapping"]["local_shares_per_adr"], 5)
        self.assertIn("adr_mapping_registry_shadow_mismatch", report["warnings"])

    def test_mapping_dual_read_respects_intraday_availability_cutoff(self) -> None:
        relation = add_approved_adr_relation(self.db)
        verified_at = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
        relation.evidence[0].verified_at = verified_at
        self.db.commit()

        before_verification = build_adr_parity_report(
            self.db,
            "2330",
            generated_at=datetime(2026, 8, 9, 13, tzinfo=timezone.utc),
            mapping_as_of=date(2026, 8, 9),
            data_available_at=datetime(2026, 8, 9, 11, tzinfo=timezone.utc),
        )
        after_verification = build_adr_parity_report(
            self.db,
            "2330",
            generated_at=datetime(2026, 8, 9, 13, tzinfo=timezone.utc),
            mapping_as_of=date(2026, 8, 9),
            data_available_at=datetime(2026, 8, 9, 13, tzinfo=timezone.utc),
        )

        assert before_verification is not None
        assert after_verification is not None
        self.assertEqual(
            before_verification["mapping_resolution"]["selected_source"],
            "legacy",
        )
        self.assertEqual(
            before_verification["mapping_resolution"]["shadow_status"],
            "legacy_only",
        )
        self.assertEqual(
            after_verification["mapping_resolution"]["selected_source"],
            "registry",
        )
        self.assertEqual(
            after_verification["mapping_resolution"]["relation_id"],
            relation.id,
        )

    def test_report_can_invert_twd_usd_but_keeps_warning(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="UMC",
                trade_date=date(2026, 6, 5),
                close_price=10.0,
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="2303",
            trade_date=date(2026, 6, 5),
            close_price=64.0,
        )
        add_fx(self.db, symbol="TWD-USD", last_price=1 / 32.0)

        report = build_adr_parity_report(
            self.db,
            "2303",
            expected_adr_trade_date=date(2026, 6, 5),
            generated_at=datetime(2026, 6, 8, 12, tzinfo=timezone.utc),
        )

        assert report is not None
        self.assertEqual(report["fx_source_symbol"], "TWD-USD")
        self.assertEqual(report["usd_twd"], 32.0)
        self.assertEqual(report["implied_tw_price_twd"], 64.0)
        self.assertEqual(report["implied_gap_pct"], 0.0)
        self.assertTrue(any("反向換算" in item for item in report["warnings"]))

    def test_missing_fx_is_partial_and_does_not_emit_implied_price(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="ASX",
                trade_date=date(2026, 6, 5),
                close_price=12.0,
            )
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="3711",
            trade_date=date(2026, 6, 5),
            close_price=180.0,
        )

        report = build_adr_parity_report(
            self.db,
            "3711",
            expected_adr_trade_date=date(2026, 6, 5),
            generated_at=datetime(2026, 6, 8, 12, tzinfo=timezone.utc),
        )

        assert report is not None
        self.assertEqual(report["status"], "partial")
        self.assertIsNone(report["implied_tw_price_twd"])
        self.assertIn("resource_quote_snapshot.USD-TWD", report["missing"])

    def test_unmapped_stock_is_not_applicable(self) -> None:
        self.assertIsNone(build_adr_parity_report(self.db, "1101"))

    def test_overnight_contract_exposes_optional_adr_parity(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
                industry="24",
            )
        )
        self.db.add_all(
            [
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="TSM",
                    trade_date=date(2026, 6, 4),
                    close_price=195.0,
                ),
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="TSM",
                    trade_date=date(2026, 6, 5),
                    close_price=200.0,
                ),
            ]
        )
        self.db.commit()
        add_tw_daily(
            self.db,
            stock_id="2330",
            trade_date=date(2026, 6, 5),
            close_price=1000.0,
        )
        add_fx(self.db)

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            report = build_us_overnight_impact_report(self.db, "2330")

        parsed = OvernightImpactRead.model_validate(report)
        self.assertIsNotNone(parsed.adr_parity)
        assert parsed.adr_parity is not None
        self.assertEqual(parsed.adr_parity.mapping.adr_symbol, "TSM")
        self.assertEqual(parsed.adr_parity.implied_tw_price_twd, 1300.0)

    def test_gap_scanner_prioritizes_direct_adr_for_bounded_refresh(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="8150",
                stock_name="南茂",
                market="TWSE",
                instrument_type="stock",
                industry="24",
            )
        )
        self.db.commit()

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            gaps = scan_us_overnight_impact_gaps(
                self.db,
                "8150",
                max_symbols=2,
            )

        self.assertEqual(gaps["refresh_symbols"][0], "IMOS")
        self.assertEqual(gaps["symbol_status"][0]["role"], "direct_adr")


if __name__ == "__main__":
    unittest.main()
