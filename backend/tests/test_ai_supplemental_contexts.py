from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import scope_resolution
from app.ai.market_context import (
    capability_context,
    kr_context,
    macro_context,
    portfolio_context,
    regional_watchlist_context,
    resource_context,
    source_health_context,
    tw_cross_market,
    tw_market_chips,
)
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    MacroSeriesObservation,
    MarginTradingDaily,
    MarketChipDaily,
    ResourceOhlcvBar,
    ResourceQuoteSnapshot,
    SourceHealthSnapshot,
    StockMaster,
    USDailyPrice,
    USStockMaster,
)
from app.portfolio import service as portfolio_service
from app.portfolio.schemas import PortfolioHoldingCreate
from app.resource_market import service as resource_service
from app.us_market import service as us_market_service


NOW = datetime(2026, 7, 18, 4, 0, tzinfo=timezone.utc)


class AiSupplementalContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_scope_resolution_supports_supplemental_targets(self) -> None:
        cases = (
            ("resource_asset", "twd/usd", "TWD-USD"),
            ("us_macro", "dgs10", "DGS10"),
            ("us_watchlist", "3", "3"),
            ("jp_watchlist", "4", "4"),
            ("kr_watchlist", "5", "5"),
        )
        for target_type, target_id, expected_id in cases:
            with self.subTest(target_type=target_type):
                resolution = scope_resolution._resolve_scope(
                    db=None,
                    payload=AiAskRequest(
                        question="context",
                        target={"type": target_type, "id": target_id},
                    ),
                )
                self.assertEqual(resolution.selected_scope_type, target_type)
                self.assertEqual(resolution.selected_scope_id, expected_id)

        for target_type in ("portfolio", "source_health", "capability_status"):
            resolution = scope_resolution._resolve_scope(
                db=None,
                payload=AiAskRequest(question="context", target={"type": target_type}),
            )
            self.assertEqual(resolution.selected_scope_type, target_type)

    def test_scope_resolution_infers_supplemental_targets_from_clear_questions(self) -> None:
        cases = (
            ("請給我全部持倉總覽", "portfolio", None),
            ("目前資料來源健康狀態", "source_health", None),
            ("黃金現在的市場資料", "resource_asset", "GC"),
            ("美國10年債殖利率資料", "us_macro", "DGS10"),
            ("美股自選群組 3 排名", "us_watchlist", "3"),
            ("日股自選群組 4 雷達", "jp_watchlist", "4"),
            ("韓股 watchlist 5", "kr_watchlist", "5"),
            ("目前哪些資料還沒接", "capability_status", None),
        )
        for question, expected_scope, expected_id in cases:
            with self.subTest(question=question):
                resolution = scope_resolution._resolve_scope(
                    db=self.db,
                    payload=AiAskRequest(question=question),
                )
                self.assertEqual(resolution.selected_scope_type, expected_scope)
                self.assertEqual(resolution.selected_scope_id, expected_id)

    def test_resource_context_exposes_watch_only_quote_and_chart(self) -> None:
        self.db.add_all(
            [
                ResourceQuoteSnapshot(
                    provider="yahoo_chart",
                    exchange="FX",
                    symbol="TWD-USD",
                    provider_symbol="TWDUSD=X",
                    name="TWD/USD Foreign Exchange",
                    root_folder="currency",
                    group="twd_to_foreign",
                    asset_class="foreign_exchange",
                    base_asset="TWD",
                    quote_asset="USD",
                    instrument_type="spot",
                    contract_key="spot",
                    last_price=0.0311,
                    event_time=NOW,
                    fetched_at=NOW,
                ),
                ResourceOhlcvBar(
                    provider="yahoo_chart",
                    exchange="FX",
                    symbol="TWD-USD",
                    provider_symbol="TWDUSD=X",
                    name="TWD/USD Foreign Exchange",
                    root_folder="currency",
                    group="twd_to_foreign",
                    asset_class="foreign_exchange",
                    base_asset="TWD",
                    quote_asset="USD",
                    instrument_type="spot",
                    contract_key="spot",
                    interval="1d",
                    bar_time=NOW,
                    close_price=0.0311,
                    fetched_at=NOW,
                ),
            ]
        )
        self.db.commit()

        result = resource_context.read_resource_asset_context(
            self.db,
            symbol="twd/usd",
            market_data_params={"interval": "1d", "bars": 10},
            dependencies=resource_context.ResourceContextDependencies(
                resource_service=resource_service,
                build_resource_source_health=lambda *args, **kwargs: {
                    "summary": {"current_count": 2},
                    "entries": [
                        {"resource": "quote", "status": "current"},
                        {"resource": "ohlcv", "status": "current"},
                    ],
                },
                now=lambda: NOW,
            ),
        )

        self.assertEqual(result["scope"]["target"]["type"], "resource_asset")
        self.assertEqual(result["data"]["quote"]["last_price"], 0.0311)
        self.assertEqual(result["data"]["slots"]["quote"]["status"], "ready")
        self.assertEqual(result["data"]["slots"]["trade_execution"]["status"], "not_applicable")

    def test_capability_status_exposes_connected_and_blocked_provider_contracts(self) -> None:
        result = capability_context.read_capability_status(
            market_data_params={"market": "tw"},
            now=NOW,
        )

        self.assertGreater(result["summary"]["connected_count"], 0)
        self.assertEqual(result["summary"]["blocked_count"], 0)
        connected_ids = {row["id"] for row in result["data"]["connected"]}
        self.assertIn("tw_options_chain_iv_greeks", connected_ids)
        self.assertIn("tw_large_trader_positions", connected_ids)
        self.assertIn("tw_futures_basis_term_structure", connected_ids)
        self.assertEqual(result["data"]["slots"]["blocked"]["status"], "not_applicable")

        all_markets = capability_context.read_capability_status(now=NOW)
        blocked_ids = {row["id"] for row in all_markets["data"]["blocked"]}
        self.assertIn("news_events", blocked_ids)
        self.assertIn("hk_market", blocked_ids)

    def test_omi_ask_exposes_capability_status_through_public_contract(self) -> None:
        response = ai_ask.ask(
            db=self.db,
            payload=AiAskRequest(
                question="目前哪些資料還沒接",
            ),
            server_policy=ai_ask.AiAskServerPolicy(),
        )

        self.assertEqual(response["target"]["type"], "capability_status")
        self.assertEqual(response["mode"]["effective"], "data_only")
        self.assertEqual(response["action"], "omi.read_capability_status")
        self.assertEqual(response["result"]["kind"], "capability_status")
        self.assertGreater(response["result"]["summary"]["blocked_count"], 0)
        self.assertEqual(
            response["result"]["data"]["compact"]["kind"],
            "capability_status_compact",
        )
        self.assertTrue(response["result"]["data"]["compact"]["capabilities"])

    def test_macro_context_exposes_cached_observations_and_release_limit(self) -> None:
        self.db.add(
            MacroSeriesObservation(
                provider="fred",
                series_id="DGS10",
                series_name="Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
                observation_date=date(2026, 7, 17),
                value=4.25,
                unit="Percent",
                frequency="Daily",
                fetched_at=NOW,
            )
        )
        self.db.commit()

        result = macro_context.read_us_macro_context(
            self.db,
            series_id="dgs10",
            market_data_params={"limit": 10},
            dependencies=macro_context.MacroContextDependencies(
                us_market_service=us_market_service,
                now=lambda: NOW,
            ),
        )

        self.assertEqual(result["scope"]["target"]["id"], "DGS10")
        self.assertEqual(result["data"]["observations"][-1]["value"], 4.25)
        self.assertEqual(result["data"]["slots"]["observations"]["status"], "ready")
        self.assertEqual(result["data"]["slots"]["release_calendar"]["status"], "partial")

    def test_portfolio_context_requires_trust_and_values_native_currency(self) -> None:
        self.db.add(USStockMaster(symbol="AAPL", security_name="Apple Inc."))
        self.db.commit()
        portfolio_service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="us",
                symbol="AAPL",
                quantity=2,
                cost_amount=300,
            ),
        )
        self.db.add(
            USDailyPrice(
                provider="alphavantage",
                symbol="AAPL",
                trade_date=date(2026, 7, 17),
                currency="USD",
                adjusted_close=200,
                fetched_at=NOW,
            )
        )
        self.db.commit()
        dependencies = portfolio_context.PortfolioContextDependencies(
            portfolio_service=portfolio_service,
            now=lambda: NOW,
        )

        blocked = portfolio_context.read_portfolio_context(
            self.db,
            market_data_params={},
            trusted=False,
            dependencies=dependencies,
        )
        ready = portfolio_context.read_portfolio_context(
            self.db,
            market_data_params={},
            trusted=True,
            dependencies=dependencies,
        )

        self.assertEqual(blocked["data"]["slots"]["holdings"]["status"], "blocked")
        self.assertEqual(ready["data"]["valuation"]["market_value_by_currency"]["USD"], 400)
        self.assertEqual(ready["data"]["valuation"]["unrealized_pnl_by_currency"]["USD"], 100)
        self.assertIsNone(ready["data"]["valuation"]["cross_currency_total"])

    def test_unified_source_health_reads_latest_persisted_snapshots_without_refresh(self) -> None:
        self.db.add_all(
            [
                SourceHealthSnapshot(
                    market="tw",
                    resource="market_daily_price",
                    target="all",
                    provider="twse",
                    status="current",
                    ok=True,
                    checked_at=NOW,
                ),
                SourceHealthSnapshot(
                    market="resource",
                    resource="quote",
                    target="GC",
                    provider="yahoo_chart",
                    status="stale",
                    ok=False,
                    checked_at=NOW,
                ),
            ]
        )
        self.db.commit()

        result = source_health_context.read_unified_source_health_context(
            self.db,
            market_data_params={"limit": 20},
            now=lambda: NOW,
        )

        self.assertEqual(result["data"]["summary"]["entry_count"], 2)
        self.assertEqual(result["data"]["summary"]["problem_count"], 1)
        self.assertEqual(result["data"]["slots"]["health_entries"]["status"], "partial")

    def test_regional_watchlist_context_uses_existing_ranking_and_radar_services(self) -> None:
        fake_us = SimpleNamespace(
            get_us_watchlist_group=lambda db, group_id: SimpleNamespace(name="US Core"),
            get_us_watchlist_ranking=lambda *args, **kwargs: {
                "requested_symbol_count": 1,
                "ranked_count": 1,
                "no_data_count": 0,
                "error_count": 0,
                "is_current": True,
                "trade_date": date(2026, 7, 17),
                "results": [{"symbol": "AAPL", "close": 200}],
            },
            get_us_watchlist_technical_radar=lambda *args, **kwargs: {
                "results": [{"symbol": "AAPL", "score": 80}]
            },
        )
        result = regional_watchlist_context.read_regional_watchlist_context(
            self.db,
            market="us",
            group_id=1,
            include_children=True,
            enabled_only=True,
            rank_by="change_pct",
            sort_order="desc",
            radar_mode="action",
            market_data_params={},
            context_limit=20,
            dependencies=regional_watchlist_context.RegionalWatchlistDependencies(
                us_market_service=fake_us,
                jp_market_service=SimpleNamespace(),
                kr_market_service=SimpleNamespace(),
                now=lambda: NOW,
            ),
        )

        self.assertEqual(result["scope"]["target"]["type"], "us_watchlist")
        self.assertEqual(result["data"]["slots"]["ranking"]["status"], "ready")
        self.assertEqual(result["data"]["slots"]["radar"]["status"], "ready")

    def test_kr_index_context_projects_bounded_intraday_evidence(self) -> None:
        fake_kr = SimpleNamespace(
            list_kr_index_ohlc_chart_data=lambda *args, **kwargs: {
                "points": [
                    {
                        "time": "2026-07-17",
                        "close": 3200.0,
                        "volume": 1000,
                    }
                ]
            },
            get_kr_index_intraday_trend=lambda *args, **kwargs: {
                "source": "naver_index_intraday",
                "session_scope": "regular",
                "session_phase": "regular",
                "previous_close": 3200.0,
                "previous_close_source": "kr_index_daily_price",
                "point_count": 2,
                "points": [
                    {"time": "2026-07-17T09:00:00+09:00", "price": 3201.0, "cumulative_volume": 10},
                    {"time": "2026-07-17T15:30:00+09:00", "price": 3210.0, "cumulative_volume": 500},
                ],
                "source_url": "https://example.test/kr-index",
                "is_partial": False,
                "warnings": [],
            },
        )

        result = kr_context.read_kr_stock_context(
            self.db,
            symbol="KOSPI",
            is_index=True,
            market_data_params={"include_intraday": True, "intraday_limit": 1},
            dependencies=kr_context.KRContextDependencies(
                kr_market_service=fake_kr,
                now=lambda: NOW,
            ),
        )

        self.assertEqual(result["summary"]["latest_close"], 3210.0)
        self.assertTrue(result["summary"]["intraday"]["available"])
        self.assertTrue(result["summary"]["intraday"]["is_current"])
        one_minute = result["data"]["compact"]["intraday_bars"]["series"]["1m"]
        self.assertEqual(one_minute["returned_point_count"], 1)
        self.assertEqual(one_minute["latest"]["price"], 3210.0)

    def test_tw_cross_market_context_reads_bounded_local_cache(self) -> None:
        self.db.add_all(
            [
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="^GSPC",
                    trade_date=date(2026, 7, 16),
                    adjusted_close=6300.0,
                    fetched_at=NOW,
                ),
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="^GSPC",
                    trade_date=date(2026, 7, 17),
                    adjusted_close=6363.0,
                    fetched_at=NOW,
                ),
                ResourceQuoteSnapshot(
                    provider="yahoo_chart",
                    exchange="FX",
                    symbol="USD-TWD",
                    provider_symbol="USDTWD=X",
                    name="USD/TWD Foreign Exchange",
                    root_folder="currency",
                    group="foreign_to_twd",
                    asset_class="foreign_exchange",
                    base_asset="USD",
                    quote_asset="TWD",
                    instrument_type="spot",
                    contract_key="spot",
                    last_price=32.1,
                    event_time=NOW,
                    fetched_at=NOW,
                ),
            ]
        )
        self.db.commit()

        result = tw_cross_market.read_tw_cross_market_context(self.db, now=NOW)

        self.assertEqual(result["status"], "partial")
        sp500 = result["markets"]["us"]["assets"][0]
        self.assertEqual(sp500["id"], "^GSPC")
        self.assertAlmostEqual(sp500["change_pct"], 1.0)
        self.assertEqual(result["markets"]["resource"]["assets"][0]["id"], "USD-TWD")
        self.assertIn("jp.^N225", result["missing"])

    def test_txf_market_chip_trend_exposes_multi_day_positioning(self) -> None:
        from app.ai.market_context.taiwan_futures import _market_chip_trend

        rows = [
            MarketChipDaily(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 7, 15),
                close_value=23000,
                foreign_futures_net_oi=-80000,
                put_call_volume_ratio_pct=85,
                put_call_open_interest_ratio_pct=90,
            ),
            MarketChipDaily(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 7, 16),
                close_value=23100,
                foreign_futures_net_oi=-83000,
                put_call_volume_ratio_pct=88,
                put_call_open_interest_ratio_pct=95,
            ),
            MarketChipDaily(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 7, 17),
                close_value=23230,
                foreign_futures_net_oi=-86000,
                put_call_volume_ratio_pct=92,
                put_call_open_interest_ratio_pct=101,
            ),
        ]

        result = _market_chip_trend(rows)

        three_day = result["windows"]["3d"]
        self.assertEqual(three_day["foreign_futures_net_oi_change"], -6000)
        self.assertEqual(three_day["foreign_positioning"], "net_short_increasing")
        self.assertEqual(three_day["put_call_open_interest_ratio_change_pct_points"], 11)
        self.assertTrue(three_day["short_price_divergence"])
        self.assertTrue(result["coverage"]["is_partial"])

    def test_tw_market_chips_separates_official_aggregate_from_rank_coverage(self) -> None:
        self.db.add_all(
            [
                StockMaster(stock_id="2330", stock_name="TSMC", is_active=True),
                StockMaster(stock_id="2317", stock_name="Hon Hai", is_active=True),
                MarketChipDaily(
                    index_id="TAIEX",
                    market="TWSE",
                    trade_date=date(2026, 7, 17),
                    foreign_investor_net_value=-10_000,
                ),
                MarketChipDaily(
                    index_id="TPEX",
                    market="TPEX",
                    trade_date=date(2026, 7, 17),
                    foreign_investor_net_value=1_000,
                ),
                InstitutionalTradeDaily(
                    source_id=1,
                    raw_result_id=1,
                    trade_date=date(2026, 7, 17),
                    stock_id="2330",
                    stock_name="TSMC",
                    foreign_investor_net=-100,
                    total_institutional_net=-80,
                ),
                InstitutionalTradeDaily(
                    source_id=1,
                    raw_result_id=1,
                    trade_date=date(2026, 7, 17),
                    stock_id="2317",
                    stock_name="Hon Hai",
                    foreign_investor_net=200,
                    total_institutional_net=180,
                ),
                MarginTradingDaily(
                    source_id=1,
                    raw_result_id=1,
                    trade_date=date(2026, 7, 17),
                    stock_id="2330",
                    stock_name="TSMC",
                    margin_previous_balance=1000,
                    margin_today_balance=1100,
                    short_previous_balance=100,
                    short_today_balance=120,
                ),
                MarginTradingDaily(
                    source_id=1,
                    raw_result_id=1,
                    trade_date=date(2026, 7, 17),
                    stock_id="2317",
                    stock_name="Hon Hai",
                    margin_previous_balance=900,
                    margin_today_balance=850,
                    short_previous_balance=80,
                    short_today_balance=70,
                ),
            ]
        )
        self.db.commit()

        result = tw_market_chips.read_tw_market_chips_context(self.db, limit=10)

        self.assertEqual(result["official_market_aggregate"]["status"], "ready")
        coverage = result["institutional_per_stock"]["coverage"]
        self.assertEqual(coverage["scope"], "omi_database_coverage")
        self.assertTrue(coverage["is_full_database_coverage"])
        self.assertEqual(coverage["full_market_verification"], "not_asserted")
        self.assertEqual(result["institutional_per_stock"]["top_net_buy"][0]["stock_id"], "2317")
        self.assertEqual(result["margin_per_stock"]["aggregate"]["margin_balance_change"], 50)


if __name__ == "__main__":
    unittest.main()
