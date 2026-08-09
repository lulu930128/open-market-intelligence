from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_tools
from app.ai import tools as ai_tools
from app.db.models import (
    Base,
    MarketDailyPrice,
    ProviderEvent,
    RawFetchResult,
    ResourceQuoteSnapshot,
    SourceRegistry,
    StockMaster,
    USDailyPrice,
    USWatchlistGroup,
    USWatchlistItem,
)
from app.market.cross_market.refresh import build_cross_market_refresh_plan
from app.market.overnight_impact import (
    build_us_overnight_impact_report,
    ensure_current_us_overnight_impact_report,
    scan_us_overnight_impact_gaps,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    source = SourceRegistry(
        source_name=f"test-{category}",
        source_type="test",
        category=category,
    )
    db.add(source)
    db.flush()

    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url=f"https://example.test/{category}",
        status_code=200,
        content_hash=f"{category}-hash",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    return source.id, raw.id


def add_stock(
    db: Session,
    *,
    stock_id: str = "2330",
    stock_name: str = "台積電",
    industry: str | None = "24",
) -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name=stock_name,
            market="TWSE",
            instrument_type="stock",
            industry=industry,
        )
    )
    db.commit()


def add_tw_daily_history(db: Session, stock_id: str = "2330", count: int = 90) -> None:
    source_id, raw_result_id = add_raw_source(db, "market_daily_price")
    start = date(2026, 1, 1)
    for index in range(count):
        close = 100.0 + index
        db.add(
            MarketDailyPrice(
                source_id=source_id,
                raw_result_id=raw_result_id,
                trade_date=start + timedelta(days=index),
                stock_id=stock_id,
                stock_name="台積電",
                trade_volume=1_000_000 + index * 1000,
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=close,
                price_change=1.0,
            )
        )
    db.commit()


def add_us_move(
    db: Session,
    symbol: str,
    *,
    previous_close: float = 100.0,
    change_pct: float,
    latest_date: date = date(2026, 6, 5),
) -> None:
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol=symbol,
            trade_date=latest_date - timedelta(days=1),
            open_price=previous_close,
            high_price=previous_close,
            low_price=previous_close,
            close_price=previous_close,
            adjusted_close=previous_close,
            trade_volume=1_000_000,
        )
    )
    latest_close = previous_close * (1 + change_pct / 100)
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol=symbol,
            trade_date=latest_date,
            open_price=latest_close,
            high_price=latest_close,
            low_price=latest_close,
            close_price=latest_close,
            adjusted_close=latest_close,
            trade_volume=1_100_000,
        )
    )
    db.commit()


def add_us_group(db: Session, group_name: str, moves: dict[str, float]) -> None:
    group = USWatchlistGroup(group_name=group_name, is_active=True)
    db.add(group)
    db.flush()
    for index, (symbol, change_pct) in enumerate(moves.items()):
        db.add(
            USWatchlistItem(
                group_id=group.id,
                symbol=symbol,
                priority=index,
                enabled=True,
            )
        )
        add_us_move(db, symbol, change_pct=change_pct)
    db.commit()


def add_core_us_market(db: Session) -> None:
    for symbol, change_pct in {
        "^GSPC": -1.2,
        "^IXIC": -2.4,
        "^DJI": -0.7,
        "^SOX": -4.8,
        "QQQ": -2.6,
        "SMH": -4.1,
        "TSM": -3.2,
        "NVDA": -5.4,
        "MU": -6.5,
    }.items():
        add_us_move(db, symbol, change_pct=change_pct)


class OvernightImpactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_semiconductor_stock_uses_semiconductor_factors(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        add_core_us_market(self.db)
        add_us_group(
            self.db,
            "半導體_GPU_ASIC",
            {"AMD": -4.0, "AVGO": -2.5, "MRVL": -3.0},
        )
        add_us_group(
            self.db,
            "半導體設備_量測",
            {"AMAT": -2.0, "LRCX": -2.2, "KLAC": -1.8},
        )
        add_us_group(
            self.db,
            "晶圓製造_IDM",
            {"INTC": -1.4, "GFS": -1.1, "UMC": -0.8},
        )
        add_us_group(
            self.db,
            "ETF_科技",
            {"XLK": -2.0, "SOXX": -3.5, "IGV": -1.2},
        )

        report = build_us_overnight_impact_report(db=self.db, stock_id="2330")

        self.assertEqual(report["kind"], "us_overnight_tw_impact")
        self.assertIn("semiconductor", report["tw_mapping"]["profiles"])
        self.assertLess(report["weighted_change_pct"], 0)
        self.assertIn(report["stance"], {"risk_off", "strong_risk_off"})
        self.assertIn("^SOX", {factor["symbol"] for factor in report["factors"]})
        self.assertTrue(
            any(basket["group_name"] == "半導體_GPU_ASIC" for basket in report["baskets"])
        )
        self.assertEqual(report["evidence_passport"]["target_kind"], "us_overnight_tw_impact")
        context = report["cross_market_context"]
        self.assertEqual(context["schema_version"], "cross_market.context.v1")
        self.assertEqual(context["target"]["canonical_symbol"], "TW:2330")
        self.assertEqual(
            context["direct_equivalents"][0]["implied_gap_pct"],
            report["adr_parity"]["implied_gap_pct"],
        )
        self.assertIn(
            "latest_local_cache_projection_not_materialized_snapshot",
            context["limitations"],
        )
        self.assertEqual(context["projection_source"], "latest_local_cache")
        self.assertIsNotNone(context["source_cutoff_at"])
        self.assertIsNone(context["materialized_at"])
        self.assertIsNone(context["payload_hash"])
        self.assertEqual(
            report["evidence_passport"]["cross_market_context"]["snapshot_id"],
            context["snapshot_id"],
        )
        self.assertEqual(
            report["evidence_passport"]["cross_market_context"][
                "projection_source"
            ],
            context["projection_source"],
        )
        self.assertEqual(
            report["evidence_passport"]["cross_market_context"]["payload_hash"],
            context["payload_hash"],
        )
        self.assertEqual(report["signals"], context["signals"])
        self.assertEqual(report["bucket_scores"], context["bucket_scores"])
        self.assertEqual(report["coverage"], context["coverage"])
        self.assertEqual(report["methodology_version"], context["methodology_version"])
        self.assertEqual(
            report["relation_snapshot_version"],
            context["relation_snapshot_version"],
        )
        self.assertEqual(report["snapshot_id"], context["snapshot_id"])
        self.assertEqual(report["projection_source"], context["projection_source"])
        self.assertEqual(report["source_cutoff_at"], context["source_cutoff_at"])
        self.assertEqual(report["materialized_at"], context["materialized_at"])
        self.assertEqual(report["payload_hash"], context["payload_hash"])
        self.assertEqual(report["limitations"], context["limitations"])

    def test_general_stock_uses_market_factors(self) -> None:
        add_stock(self.db, stock_id="1101", stock_name="台泥", industry="水泥工業")
        for symbol, change_pct in {
            "^GSPC": 0.8,
            "^DJI": 0.6,
            "^IXIC": 0.4,
            "QQQ": 0.5,
            "^SOX": -5.0,
        }.items():
            add_us_move(self.db, symbol, change_pct=change_pct)

        report = build_us_overnight_impact_report(db=self.db, stock_id="1101")

        self.assertEqual(report["tw_mapping"]["profiles"], ["general"])
        self.assertGreater(report["weighted_change_pct"], 0)
        self.assertIn(report["stance"], {"risk_on", "strong_risk_on"})
        self.assertNotIn("^SOX", {factor["symbol"] for factor in report["factors"]})

    def test_stale_overnight_report_suppresses_directional_signal(self) -> None:
        add_stock(self.db, stock_id="1101", stock_name="台泥", industry="水泥工業")
        for symbol, change_pct in {
            "^GSPC": 0.8,
            "^DJI": 0.6,
            "^IXIC": 0.4,
            "QQQ": 0.5,
        }.items():
            add_us_move(self.db, symbol, change_pct=change_pct, latest_date=date(2026, 6, 5))

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            report = build_us_overnight_impact_report(
                db=self.db,
                stock_id="1101",
                suppress_stale_signal=True,
            )

        self.assertFalse(report["freshness"]["is_current"])
        self.assertEqual(report["stance"], "unknown")
        self.assertEqual(report["score"], 0)
        self.assertIsNone(report["weighted_change_pct"])
        self.assertIn("us_overnight_tw_impact_stale", report["missing"])
        self.assertTrue(any("落後預期 2026-06-08" in item for item in report["warnings"]))

    def test_ensure_current_overnight_report_refreshes_stale_us_factors(self) -> None:
        add_stock(self.db, stock_id="1101", stock_name="台泥", industry="水泥工業")
        expected_date = date(2026, 6, 8)
        for symbol, change_pct in {
            "^GSPC": 0.8,
            "^DJI": 0.6,
            "^IXIC": 0.4,
            "QQQ": 0.5,
        }.items():
            add_us_move(self.db, symbol, change_pct=change_pct, latest_date=date(2026, 6, 5))

        def refresh_daily(*, db: Session, symbol: str, **_: object) -> dict:
            add_us_move(db, symbol, change_pct=1.0, latest_date=expected_date)
            return {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": symbol,
                "fetched_count": 2,
                "inserted_count": 2,
                "updated_count": 0,
            }

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=expected_date,
        ), patch(
            "app.market.overnight_impact.us_market_service.refresh_us_daily_prices",
            side_effect=refresh_daily,
        ) as refresh_mock:
            report = ensure_current_us_overnight_impact_report(
                db=self.db,
                stock_id="1101",
                max_refresh_symbols=4,
                provider="yahoo_chart",
            )

        self.assertEqual(refresh_mock.call_count, 4)
        self.assertTrue(report["freshness"]["is_current"])
        self.assertEqual(report["freshness"]["refresh"]["is_current_after_refresh"], True)
        self.assertNotEqual(report["stance"], "unknown")
        self.assertIsNotNone(report["weighted_change_pct"])

    def test_stock_context_exposes_overnight_impact_for_ai(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        add_tw_daily_history(self.db, stock_id="2330")
        add_core_us_market(self.db)

        context = ai_tools.read_stock_context(
            db=self.db,
            stock_id="2330",
            include_intraday=False,
            analysis_horizon="swing",
        )

        overnight = context["data"]["overnight_impact"]
        self.assertEqual(overnight["kind"], "us_overnight_tw_impact")
        self.assertIn("app.market.overnight_impact", {ref["name"] for ref in context["source_refs"]})

    def test_gap_scanner_marks_missing_core_us_factors(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")

        gaps = scan_us_overnight_impact_gaps(db=self.db, stock_id="2330", max_symbols=4)

        self.assertEqual(gaps["kind"], "us_overnight_tw_impact_freshness")
        self.assertFalse(gaps["is_current"])
        self.assertTrue(gaps["refresh_recommended"])
        self.assertIn("^SOX", gaps["refresh_symbols"])
        self.assertIn("SMH", gaps["refresh_symbols"])
        self.assertIn("us_daily_price.^SOX", gaps["missing"])

    def test_gap_scanner_uses_composite_plan_when_only_fx_is_stale(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        add_core_us_market(self.db)
        now = datetime(2026, 6, 9, 8, tzinfo=timezone.utc)
        stale_fx_at = now - timedelta(days=4)
        self.db.add(
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
                event_time=stale_fx_at,
                fetched_at=stale_fx_at,
            )
        )
        self.db.commit()

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ), patch(
            "app.market.overnight_impact._now",
            return_value=now,
        ), patch(
            "app.market.cross_market.refresh.expected_us_trade_date",
            return_value=date(2026, 6, 5),
        ):
            gaps = scan_us_overnight_impact_gaps(
                db=self.db,
                stock_id="2330",
                max_symbols=8,
            )
            plan = build_cross_market_refresh_plan(
                self.db,
                "2330",
                max_symbols=8,
                now=now,
            )

        self.assertEqual(gaps["refresh_symbols"], [])
        self.assertEqual(plan["planned_source_count"], 1)
        self.assertEqual(plan["planned_sources"][0]["source_kind"], "resource_quote")
        self.assertEqual(plan["planned_sources"][0]["symbol"], "USD-TWD")
        self.assertTrue(gaps["refresh_recommended"])
        self.assertEqual(gaps["refresh_plan"]["planned_source_count"], 1)
        self.assertEqual(
            gaps["refresh_plan"]["planned_sources"][0]["symbol"],
            "USD-TWD",
        )

    def test_gap_scanner_keeps_deferred_source_stale_without_tool_loop(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        add_core_us_market(self.db)
        now = datetime(2026, 6, 9, 8, tzinfo=timezone.utc)
        stale_fx_at = now - timedelta(days=4)
        self.db.add_all(
            [
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
                    event_time=stale_fx_at,
                    fetched_at=stale_fx_at,
                ),
                ProviderEvent(
                    market="cross_market",
                    provider="cross_market_orchestrator",
                    resource="context_source",
                    target="resource_quote:USD-TWD",
                    status="failed",
                    severity="error",
                    event_type="cross_market_refresh",
                    event_time=now - timedelta(seconds=30),
                    observed_at=now - timedelta(seconds=30),
                    error_message="provider timeout",
                ),
            ]
        )
        self.db.commit()

        with patch(
            "app.market.overnight_impact.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ), patch(
            "app.market.overnight_impact._now",
            return_value=now,
        ), patch(
            "app.market.cross_market.refresh.expected_us_trade_date",
            return_value=date(2026, 6, 5),
        ):
            gaps = scan_us_overnight_impact_gaps(
                db=self.db,
                stock_id="2330",
                max_symbols=8,
            )

        with patch(
            "app.ai.agentic_tools.scan_us_overnight_impact_gaps",
            return_value=gaps,
        ):
            merged = agentic_tools.attach_us_overnight_gaps_to_tw_stock_freshness(
                self.db,
                stock_id="2330",
                stock_freshness={
                    "kind": "ai_scope_freshness",
                    "scope_type": "stock",
                    "scope_id": "2330",
                    "is_current": True,
                    "refresh_recommended": False,
                    "missing": [],
                    "warnings": [],
                    "expected_dates": {},
                },
            )
        steps = agentic_tools._overnight_daily_refresh_steps(
            gaps,
            stock_id="2330",
        )

        self.assertFalse(gaps["is_current"])
        self.assertFalse(gaps["refresh_recommended"])
        self.assertEqual(gaps["refresh_decision"]["status"], "deferred")
        self.assertFalse(gaps["refresh_decision"]["should_execute"])
        self.assertEqual(gaps["refresh_plan"]["deferred_source_count"], 1)
        self.assertEqual(steps, [])
        self.assertFalse(merged["is_current"])
        self.assertFalse(merged["refresh_recommended"])
        self.assertIn("us_overnight_tw_impact", merged["missing"])

    def test_tw_stock_tool_session_refreshes_missing_overnight_factors(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        overnight_gaps = scan_us_overnight_impact_gaps(db=self.db, stock_id="2330", max_symbols=2)
        existing_freshness = {
            "kind": "ai_scope_freshness",
            "scope_type": "stock",
            "scope_id": "2330",
            "is_current": False,
            "refresh_recommended": True,
            "missing": ["us_overnight_tw_impact"],
            "warnings": [],
            "expected_dates": {},
            "cross_market": {
                "us_overnight_impact": overnight_gaps,
            },
        }

        with patch(
            "app.ai.agentic_tools.cross_market_refresh.refresh_cross_market_context_sources",
            return_value={
                "status": "success",
                "requested_count": 2,
                "attempted_count": 2,
                "success_count": 2,
                "failed_count": 0,
                "deferred_count": 0,
            },
        ) as refresh_mock, patch(
            "app.ai.agentic_tools.stock_selection_refresh.refresh_selected_stock_data"
        ) as tw_refresh_mock:
            session = agentic_tools.run_tw_stock_tool_session(
                db=self.db,
                question="台積電今天怎麼看",
                stock_id="2330",
                target={"type": "tw_stock", "id": "2330", "market": "TW"},
                policy={
                    "can_external_fetch": True,
                    "can_plan_tools": False,
                },
                raw_budget={
                    "max_calls": 2,
                    "max_external_fetches": 2,
                    "max_total_seconds": 25,
                },
                existing_freshness=existing_freshness,
            )

        self.assertFalse(tw_refresh_mock.called)
        refresh_mock.assert_called_once_with(
            self.db,
            ["2330"],
            max_symbols=8,
            provider="auto",
            outputsize="compact",
            max_runtime_seconds=120,
        )
        self.assertEqual(
            [run["tool"] for run in session["tool_runs"]],
            ["cross_market.refresh_context"],
        )
        self.assertEqual(session["tool_runs"][0]["operation_status"], "succeeded")

    def test_tw_stock_cache_only_policy_blocks_cross_market_provider_refresh(self) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        overnight_gaps = scan_us_overnight_impact_gaps(
            db=self.db,
            stock_id="2330",
            max_symbols=2,
        )
        existing_freshness = {
            "kind": "ai_scope_freshness",
            "scope_type": "stock",
            "scope_id": "2330",
            "is_current": False,
            "refresh_recommended": True,
            "missing": ["us_overnight_tw_impact"],
            "warnings": [],
            "expected_dates": {},
            "cross_market": {"us_overnight_impact": overnight_gaps},
        }

        with patch(
            "app.ai.agentic_tools.cross_market_refresh.refresh_cross_market_context_sources"
        ) as refresh_mock:
            session = agentic_tools.run_tw_stock_tool_session(
                db=self.db,
                question="台積電隔夜影響",
                stock_id="2330",
                target={"type": "tw_stock", "id": "2330", "market": "TW"},
                policy={
                    "can_external_fetch": False,
                    "can_plan_tools": False,
                    "refresh_policy": {"fallback_to_cached": True},
                },
                raw_budget={
                    "max_calls": 1,
                    "max_external_fetches": 1,
                    "max_total_seconds": 25,
                },
                existing_freshness=existing_freshness,
            )

        refresh_mock.assert_not_called()
        self.assertEqual(session["tool_runs"][0]["status"], "blocked")
        self.assertIn(
            "External fetch is not allowed",
            session["tool_runs"][0]["error"],
        )

    def test_tw_stock_partial_cross_market_refresh_keeps_cached_limitations_visible(
        self,
    ) -> None:
        add_stock(self.db, stock_id="2330", stock_name="台積電", industry="24")
        overnight_gaps = scan_us_overnight_impact_gaps(
            db=self.db,
            stock_id="2330",
            max_symbols=2,
        )
        existing_freshness = {
            "kind": "ai_scope_freshness",
            "scope_type": "stock",
            "scope_id": "2330",
            "is_current": False,
            "refresh_recommended": True,
            "missing": ["us_overnight_tw_impact"],
            "warnings": ["cached cross-market context is stale"],
            "expected_dates": {},
            "cross_market": {"us_overnight_impact": overnight_gaps},
        }

        with patch(
            "app.ai.agentic_tools.cross_market_refresh.refresh_cross_market_context_sources",
            return_value={
                "status": "partial",
                "requested_count": 2,
                "attempted_count": 2,
                "success_count": 1,
                "failed_count": 1,
                "deferred_count": 0,
                "results": [
                    {"symbol": "USD-TWD", "status": "success"},
                    {
                        "symbol": "TSM",
                        "status": "failed",
                        "error": "provider timeout",
                    },
                ],
            },
        ):
            session = agentic_tools.run_tw_stock_tool_session(
                db=self.db,
                question="台積電隔夜影響",
                stock_id="2330",
                target={"type": "tw_stock", "id": "2330", "market": "TW"},
                policy={"can_external_fetch": True, "can_plan_tools": False},
                raw_budget={
                    "max_calls": 1,
                    "max_external_fetches": 1,
                    "max_total_seconds": 25,
                },
                existing_freshness=existing_freshness,
            )

        run = session["tool_runs"][0]
        self.assertEqual(run["operation_status"], "partial")
        self.assertEqual(run["evidence_status"], "partial")
        self.assertEqual(run["error"], "provider timeout")
        self.assertTrue(
            any("kept the local cached context" in warning for warning in session["warnings"])
        )
        self.assertIn("us_overnight_tw_impact", session["freshness"]["missing"])


if __name__ == "__main__":
    unittest.main()
