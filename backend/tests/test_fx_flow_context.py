from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    MarketChipDaily,
    RawFetchResult,
    ResourceOhlcvBar,
    SourceRegistry,
    StockMaster,
)
from app.market.fx_flow_context import build_fx_flow_context
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.schemas import FxFlowContextRead, OvernightImpactRead


FIXED_NOW = datetime(2026, 6, 8, 12, tzinfo=timezone.utc)
LATEST_DATE = date(2026, 6, 8)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_fx_history(
    db: Session,
    *,
    weakening: bool = True,
    days: int = 21,
) -> None:
    start = LATEST_DATE - timedelta(days=days - 1)
    for index in range(days):
        close = 31.0 + index * 0.05 if weakening else 32.0 - index * 0.05
        bar_time = datetime.combine(
            start + timedelta(days=index),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ) + timedelta(hours=8)
        db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="FX",
                symbol="USD-TWD",
                provider_symbol="USDTWD=X",
                name="USD/TWD",
                root_folder="currency",
                group="foreign_to_twd",
                asset_class="currency",
                base_asset="USD",
                quote_asset="TWD",
                instrument_type="currency_pair",
                contract_key="spot",
                interval="1d",
                bar_time=bar_time,
                close_price=close,
                fetched_at=bar_time,
            )
        )
    db.commit()


def add_market_flow(db: Session, *, inflow: bool = False, days: int = 20) -> None:
    start = LATEST_DATE - timedelta(days=days - 1)
    direction = 1 if inflow else -1
    for index in range(days):
        db.add(
            MarketChipDaily(
                index_id="TAIEX",
                market="TWSE",
                trade_date=start + timedelta(days=index),
                foreign_investor_net_value=direction * 10_000_000_000,
                trade_value=1_000_000_000_000,
                source_grade="official",
            )
        )
    db.commit()


def add_stock_flow(
    db: Session,
    *,
    stock_id: str = "2330",
    inflow: bool = False,
    days: int = 20,
) -> None:
    source = SourceRegistry(
        source_name=f"test-institutional-{stock_id}",
        source_type="test",
        category="institutional_trade",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url="https://example.test/institutional",
        status_code=200,
        content_hash=f"institutional-{stock_id}",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    start = LATEST_DATE - timedelta(days=days - 1)
    direction = 1 if inflow else -1
    for index in range(days):
        db.add(
            InstitutionalTradeDaily(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=start + timedelta(days=index),
                stock_id=stock_id,
                stock_name="台積電",
                foreign_investor_net=direction * 1_000_000,
                foreign_dealer_net=direction * 100_000,
            )
        )
    db.commit()


class FxFlowContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def build(self, stock_id: str = "2330") -> dict:
        return build_fx_flow_context(
            self.db,
            stock_id,
            generated_at=FIXED_NOW,
            expected_market_trade_date=LATEST_DATE,
            expected_stock_trade_date=LATEST_DATE,
        )

    def test_weak_twd_and_foreign_selling_confirms_outflow(self) -> None:
        add_fx_history(self.db, weakening=True)
        add_market_flow(self.db, inflow=False)
        add_stock_flow(self.db, inflow=False)

        report = self.build()

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["signal"], "confirmed_outflow")
        self.assertEqual(report["fx"]["regime"], "twd_weakening")
        self.assertGreater(report["fx"]["usd_twd_change_5d_pct"], 0)
        self.assertLess(report["fx"]["twd_change_5d_pct"], 0)
        self.assertEqual(
            report["market_foreign"]["windows"][1]["net_value_twd"],
            -50_000_000_000,
        )
        self.assertEqual(
            report["stock_foreign"]["windows"][1]["net_shares"],
            -5_500_000,
        )
        self.assertEqual(
            FxFlowContextRead.model_validate(report).signal,
            "confirmed_outflow",
        )

    def test_strong_twd_and_foreign_buying_confirms_inflow(self) -> None:
        add_fx_history(self.db, weakening=False)
        add_market_flow(self.db, inflow=True)
        add_stock_flow(self.db, inflow=True)

        report = self.build()

        self.assertEqual(report["signal"], "confirmed_inflow")
        self.assertEqual(report["fx"]["regime"], "twd_strengthening")
        self.assertEqual(report["market_foreign"]["state"], "inflow")
        self.assertEqual(report["stock_foreign"]["state"], "inflow")

    def test_fx_daily_rows_are_deduplicated_by_data_date(self) -> None:
        add_fx_history(self.db, weakening=True)
        duplicate_time = datetime(2026, 6, 8, 1, tzinfo=timezone.utc)
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="FX",
                symbol="USD-TWD",
                provider_symbol="USDTWD=X",
                name="USD/TWD duplicate",
                root_folder="currency",
                group="foreign_to_twd",
                asset_class="currency",
                base_asset="USD",
                quote_asset="TWD",
                instrument_type="currency_pair",
                contract_key="spot",
                interval="1d",
                bar_time=duplicate_time,
                close_price=99.0,
                fetched_at=duplicate_time,
            )
        )
        self.db.commit()
        add_market_flow(self.db)
        add_stock_flow(self.db)

        report = self.build()

        self.assertEqual(report["fx"]["observed_history_points"], 21)
        self.assertEqual(report["fx"]["history_points"], 18)
        self.assertEqual(report["fx"]["excluded_provisional_points"], 3)
        self.assertEqual(report["fx"]["usd_twd"], 31.85)

    def test_missing_stock_flow_is_partial_but_keeps_market_signal(self) -> None:
        add_fx_history(self.db, weakening=True)
        add_market_flow(self.db, inflow=False)

        report = self.build(stock_id="2303")

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["signal"], "confirmed_outflow")
        self.assertEqual(report["stock_foreign"]["status"], "missing")
        self.assertTrue(
            any("institutional_trade_daily.2303" in item for item in report["missing"])
        )

    def test_stale_flow_dates_are_visible(self) -> None:
        add_fx_history(self.db, weakening=True)
        add_market_flow(self.db, inflow=False)
        add_stock_flow(self.db, inflow=False)

        report = build_fx_flow_context(
            self.db,
            "2330",
            generated_at=FIXED_NOW + timedelta(days=1),
            expected_market_trade_date=LATEST_DATE + timedelta(days=1),
            expected_stock_trade_date=LATEST_DATE + timedelta(days=1),
        )

        self.assertEqual(report["status"], "stale")
        self.assertEqual(
            set(report["freshness"]["stale_reasons"]),
            {"market_foreign", "stock_foreign"},
        )

    def test_friday_daily_bar_is_current_before_monday_fx_session_completes(self) -> None:
        add_fx_history(self.db, weakening=True)
        for row in self.db.query(ResourceOhlcvBar).all():
            if row.bar_time.date() > date(2026, 6, 5):
                self.db.delete(row)
        self.db.commit()
        add_market_flow(self.db, inflow=False)
        add_stock_flow(self.db, inflow=False)

        report = self.build()

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["fx"]["status"], "ready")
        self.assertEqual(
            report["fx"]["freshness"]["status"],
            "latest_completed_session",
        )
        self.assertEqual(
            report["fx"]["freshness"]["expected_data_date"],
            "2026-06-05",
        )
        self.assertGreater(report["fx"]["age_seconds"], 72 * 60 * 60)

    def test_overnight_contract_exposes_fx_flow_context_without_changing_score(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
                industry="24",
            )
        )
        self.db.commit()
        add_fx_history(self.db, weakening=True)
        add_market_flow(self.db, inflow=False)
        add_stock_flow(self.db, inflow=False)

        with patch("app.market.overnight_impact._now", return_value=FIXED_NOW):
            report = build_us_overnight_impact_report(self.db, "2330")

        parsed = OvernightImpactRead.model_validate(report)
        self.assertIsNotNone(parsed.fx_flow_context)
        assert parsed.fx_flow_context is not None
        self.assertEqual(parsed.fx_flow_context.signal, "confirmed_outflow")
        self.assertEqual(report["score"], 0)
        self.assertIn(
            "app.market.fx_flow_context",
            {item["name"] for item in report["source_refs"]},
        )


if __name__ == "__main__":
    unittest.main()
