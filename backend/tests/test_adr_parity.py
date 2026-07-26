from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
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
    event_time: datetime = datetime(2026, 6, 8, 8, tzinfo=timezone.utc),
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
