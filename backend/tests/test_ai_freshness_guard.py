from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_tools
from app.ai import ask as ai_ask
from app.ai import freshness
from app.ai import reports as ai_reports
from app.ai import tools as ai_tools
from app.ai.market_context import taiwan_market
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    JPStockMaster,
    RawFetchResult,
    ShareholdingDistributionWeekly,
    SourceRegistry,
    StockMaster,
    USStockMaster,
)


SOURCE_COUNTER = count()


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_stock(db: Session, stock_id: str = "2330") -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()


def add_us_stock(db: Session, symbol: str = "TSM") -> None:
    db.add(
        USStockMaster(
            symbol=symbol,
            security_name="Taiwan Semiconductor Manufacturing ADR",
            exchange="NYSE",
            asset_type="stock",
            listing_source="test",
            cik="0001046179",
            sec_company_name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD",
            is_test_issue=False,
            is_active=True,
        )
    )
    db.commit()


def add_jp_stock(db: Session, symbol: str = "7203.T") -> None:
    db.add(
        JPStockMaster(
            symbol=symbol,
            local_code=symbol.split(".", maxsplit=1)[0],
            security_name="Toyota Motor Corporation",
            exchange="Tokyo Stock Exchange",
            market_segment="Prime Market (Domestic)",
            sector_33_name="Transportation Equipment",
            asset_type="stock",
            listing_source="test",
            currency="JPY",
            is_active=True,
        )
    )
    db.commit()


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    index = next(SOURCE_COUNTER)
    source = SourceRegistry(
        source_name=f"test-{category}-{index}",
        source_type="test",
        category=category,
    )
    db.add(source)
    db.flush()

    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
    )
    db.add(raw)
    db.flush()
    return source.id, raw.id


def add_daily_price(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "market_daily_price")
    db.add(
        MarketDailyPrice(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            close_price=100.0,
        )
    )
    db.commit()


def add_institutional_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "institutional_trade")
    db.add(
        InstitutionalTradeDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            total_institutional_net=1000,
        )
    )
    db.commit()


def add_margin_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "margin_trading")
    db.add(
        MarginTradingDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            margin_today_balance=100,
        )
    )
    db.commit()


def add_broker_branch_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "broker_branch_trade")
    db.add(
        BrokerBranchTradeDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            branch_code="0010",
            branch_name="Test Branch",
            net_lots=10,
        )
    )
    db.commit()


def add_shareholding_distribution(db: Session, stock_id: str, data_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "shareholding_distribution")
    db.add(
        ShareholdingDistributionWeekly(
            source_id=source_id,
            raw_result_id=raw_result_id,
            data_date=data_date,
            stock_id=stock_id,
            stock_name="TSMC",
            holding_level="1",
            holding_level_order=1,
            holder_count=100,
        )
    )
    db.commit()


def add_monthly_revenue(db: Session, stock_id: str, period: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "monthly_revenue")
    db.add(
        MonthlyRevenue(
            source_id=source_id,
            raw_result_id=raw_result_id,
            period=period,
            stock_id=stock_id,
            stock_name="TSMC",
            monthly_revenue=100000,
        )
    )
    db.commit()


def add_financial_metric(db: Session, stock_id: str) -> None:
    source_id, raw_result_id = add_raw_source(db, "financial_metric_quarterly")
    db.add(
        FinancialMetricQuarterly(
            source_id=source_id,
            raw_result_id=raw_result_id,
            fiscal_year=2026,
            quarter=1,
            period="2026Q1",
            stock_id=stock_id,
            stock_name="TSMC",
            eps=1.23,
            roe=10.0,
        )
    )
    db.commit()


def add_complete_stock_evidence(
    db: Session,
    stock_id: str,
    expected_trade_date: date,
) -> None:
    add_daily_price(db, stock_id, expected_trade_date)
    add_institutional_trade(db, stock_id, expected_trade_date)
    add_margin_trade(db, stock_id, expected_trade_date)
    add_broker_branch_trade(db, stock_id, expected_trade_date)
    add_shareholding_distribution(db, stock_id, date(2026, 5, 22))
    add_monthly_revenue(db, stock_id, date(2026, 4, 1))
    add_financial_metric(db, stock_id)


class AiFreshnessGuardTests(unittest.TestCase):
    def test_stock_freshness_reports_missing_evidence_pack(self) -> None:
        db = make_session()
        try:
            add_stock(db)

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
                patch.object(
                    freshness,
                    "expected_taiwan_dataset_date",
                    side_effect=lambda key: date(2026, 4, 1) if key == "monthly_revenue" else None,
                ),
            ):
                result = freshness.check_stock_data_freshness(db=db, stock_id="2330")

            self.assertFalse(result["is_current"])
            self.assertEqual(result["stale_stock_count"], 1)
            self.assertIn("market_daily_price", result["missing"])
            self.assertIn("institutional_trade_daily", result["missing"])
            self.assertIn("margin_trading_daily", result["missing"])
            self.assertIn("broker_branch_trade_daily", result["missing"])
            self.assertIn("shareholding_distribution_weekly", result["missing"])
            self.assertIn("monthly_revenue", result["missing"])
            self.assertIn("financial_metric_quarterly", result["missing"])
            self.assertEqual(result["stale_stocks"][0]["stock_id"], "2330")
            self.assertEqual(result["datasets"][0]["key"], "stock_master")
        finally:
            db.close()

    def test_stock_freshness_accepts_complete_evidence_pack(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            add_complete_stock_evidence(db, "2330", date(2026, 5, 29))

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
                patch.object(
                    freshness,
                    "expected_taiwan_dataset_date",
                    side_effect=lambda key: date(2026, 4, 1) if key == "monthly_revenue" else None,
                ),
            ):
                result = freshness.check_stock_data_freshness(db=db, stock_id="2330")

            self.assertTrue(result["is_current"])
            self.assertEqual(result["stale_stock_count"], 0)
            self.assertFalse(result["missing"])
        finally:
            db.close()

    def test_ask_exposes_compact_evidence_in_analysis(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            compact = {
                "kind": "stock_compact_evidence",
                "version": "stock_compact_evidence.v1",
                "target": {"type": "tw_stock", "id": "2330"},
                "quote": {"source": "market_daily_price", "last_price": 100.0},
                "intraday_bars": {
                    "enabled": True,
                    "series": {
                        "1m": {
                            "interval": "1m",
                            "source": "test_intraday",
                            "point_count": 1,
                            "returned_point_count": 1,
                            "to_time": "2026-05-29T13:30:00+08:00",
                            "latest": {"time": "2026-05-29T13:30:00+08:00", "close": 101.0},
                            "points": [{"time": "2026-05-29T13:30:00+08:00", "close": 101.0}],
                        }
                    },
                    "warnings": [],
                },
                "freshness_by_domain": {"quote": {"status": "daily_close"}},
            }
            context = {
                "kind": "stock_context",
                "generated_at": "2026-05-29T08:00:00Z",
                "as_of": "2026-05-29",
                "scope": {"stock_id": "2330"},
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "daily",
                        "selected_score": 1,
                        "selected_title": "test",
                        "selected_summary": "test",
                        "selected_confidence": "medium",
                    },
                    "compact": compact,
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
                "evidence_passport": {},
            }
            payload = AiAskRequest(
                question="2330 context",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
            )

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(ai_ask.tools, "read_stock_context", return_value=context),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertNotIn("compact_evidence", response["analysis"])
            self.assertEqual(response["analysis"]["compact_evidence_ref"], "result.data.compact")
            self.assertEqual(response["result"]["data"]["compact"], compact)
            self.assertEqual(response["result"]["result_view"]["mode"], "data_only")
            self.assertNotIn("latest_daily", response["result"]["data"])
            self.assertEqual(response["result"]["data"]["quote"], compact["quote"])
            self.assertEqual(response["result"]["stock"]["id"], "2330")
            self.assertEqual(response["result"]["quote"], compact["quote"])
            self.assertEqual(response["result"]["intraday"]["status"], "ok")
            self.assertEqual(response["result"]["intraday"]["latest_point"]["close"], 101.0)
            self.assertFalse(response["result"]["live_summary"]["is_live"])
            self.assertEqual(response["result"]["live_summary"]["intraday_latest_price"], 101.0)
            self.assertEqual(response["result"]["freshness"], compact["freshness_by_domain"])
        finally:
            db.close()

    def test_us_stock_context_projects_intraday_tool_result_into_compact_quote(self) -> None:
        db = make_session()
        try:
            add_us_stock(db)
            latest_daily = SimpleNamespace(
                provider="alphavantage",
                symbol="TSM",
                trade_date=date(2026, 7, 2),
                currency="USD",
                open_price=430.0,
                high_price=436.0,
                low_price=429.0,
                close_price=434.16,
                adjusted_close=434.16,
                trade_volume=11_000_000,
                fetched_at=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
                source_url="https://example.test/daily",
            )
            profile = SimpleNamespace(
                provider="test",
                symbol="TSM",
                company_name="Taiwan Semiconductor Manufacturing ADR",
                exchange="NYSE",
                sector="Technology",
                industry="Semiconductors",
                market_cap=None,
                pe_ratio=None,
                eps=None,
                revenue_ttm=None,
                profit_margin=None,
                latest_quarter=None,
                fetched_at=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
                source_url="https://example.test/profile",
            )
            intraday_summary = {
                "source": "yahoo_finance_chart",
                "source_url": "https://query1.finance.yahoo.com/v8/finance/chart/TSM",
                "session_scope": "regular",
                "session_phase": "regular",
                "previous_close": 434.16,
                "previous_close_source": "us_daily_price",
                "previous_close_trade_date": "2026-07-02",
                "previous_close_provider": "alphavantage",
                "point_count": 65,
                "points": [
                    {"time": "2026-07-06T13:29:00-04:00", "session": "regular", "price": 435.1, "volume": 900},
                    {"time": "2026-07-06T13:30:00-04:00", "session": "regular", "price": 435.5, "volume": 1200},
                ],
                "latest_point": {
                    "time": "2026-07-06T13:30:00-04:00",
                    "session": "regular",
                    "price": 435.5,
                    "volume": 1200,
                },
                "warnings": [],
            }
            tool_runs = [
                {
                    "tool": "us.read_intraday_trend",
                    "status": "success",
                    "result_summary": intraday_summary,
                }
            ]

            with (
                patch.object(agentic_tools.us_market_service, "list_us_daily_prices", return_value=[latest_daily]),
                patch.object(agentic_tools, "_latest_profile", return_value=profile),
                patch.object(
                    agentic_tools.us_market_service,
                    "get_us_sec_fundamental_summary",
                    return_value={"metric_count": 0},
                ),
                patch.object(agentic_tools.us_market_service, "list_us_corporate_actions", return_value=[]),
                patch.object(agentic_tools.us_market_service, "list_us_short_volumes", return_value=[]),
                patch.object(agentic_tools, "scan_us_stock_gaps", return_value={"missing": [], "warnings": []}),
                patch.object(
                    agentic_tools.us_market_service,
                    "build_us_source_health",
                    return_value={"summary": {"status": "ok"}, "entries": []},
                ),
                patch.object(
                    agentic_tools.us_market_service,
                    "list_us_ohlc_chart_data",
                    return_value={
                        "timeframe": "daily",
                        "bars": 90,
                        "point_count": 2,
                        "points": [],
                    },
                ) as list_chart,
                patch.object(
                    agentic_tools.us_context,
                    "build_us_calendar_status",
                    return_value={
                        "checked_at": "2026-07-06T13:31:00-04:00",
                        "date": "2026-07-06",
                        "is_trading_day": True,
                        "phase": "regular",
                        "previous_trading_day": "2026-07-06",
                    },
                ),
            ):
                context = agentic_tools.read_us_stock_context(
                    db=db,
                    symbol="TSM",
                    tool_runs=tool_runs,
                    market_data_params={"include_intraday": True, "payload_level": "summary"},
                )

            list_chart.assert_called_once()
            self.assertFalse(list_chart.call_args.kwargs["include_intraday"])
            compact = context["data"]["compact"]
            self.assertEqual(compact["quote"]["source"], "yahoo_finance_chart")
            self.assertTrue(compact["quote"]["is_realtime"])
            self.assertEqual(compact["quote"]["previous_close_trade_date"], "2026-07-02")
            self.assertEqual(compact["quote"]["previous_close_provider"], "alphavantage")
            self.assertEqual(compact["quote"]["quote_time"], "2026-07-06T13:30:00-04:00")
            self.assertEqual(compact["quote"]["price"], 435.5)
            self.assertEqual(compact["payload_level"], "summary")
            self.assertEqual(compact["freshness_by_domain"]["intraday"], "current")
            self.assertEqual(compact["intraday_bars"]["series"]["1m"]["point_count"], 65)
            self.assertEqual(compact["intraday_bars"]["series"]["1m"]["returned_point_count"], 1)
            self.assertEqual(len(compact["intraday_bars"]["series"]["1m"]["points"]), 1)
            self.assertEqual(compact["intraday_bars"]["series"]["1m"]["latest"]["price"], 435.5)
            self.assertEqual(compact["slots"]["quote"]["status"], "ready")
            self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
            self.assertEqual(compact["slots"]["intraday"]["payload_level"], "summary")
            self.assertEqual(compact["slots"]["intraday"]["payload_ref"], "intraday_bars")
        finally:
            db.close()

    def test_ask_full_mode_preserves_complete_evidence_pack(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            compact = {
                "kind": "stock_compact_evidence",
                "version": "stock_compact_evidence.v1",
                "quote": {"latest_price": 100.0, "is_realtime": False},
            }
            context = {
                "kind": "stock_context",
                "generated_at": date(2026, 6, 4),
                "as_of": "2026-06-04",
                "scope": {"stock_id": "2330"},
                "data": {
                    "latest_daily": {"trade_date": "2026-06-04", "close_price": 100.0},
                    "technical_reports": {"daily": {"title": "test"}},
                    "compact": compact,
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
                "evidence_passport": {},
            }
            payload = AiAskRequest(
                question="2330 full context",
                target={"type": "tw_stock", "id": "2330"},
                mode="full",
            )

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(ai_ask.tools, "read_stock_context", return_value=context),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["mode"]["effective"], "full")
            self.assertEqual(response["report_level"], "full_evidence")
            self.assertEqual(response["result"]["data"]["latest_daily"]["close_price"], 100.0)
            self.assertEqual(response["result"]["data"]["technical_reports"]["daily"]["title"], "test")
            self.assertNotIn("result_view", response["result"])
        finally:
            db.close()

    def test_data_only_without_compact_returns_bounded_explicit_failure(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            context = {
                "kind": "stock_context",
                "as_of": "2026-06-04",
                "scope": {"stock_id": "2330"},
                "data": {"large_legacy_rows": [{"value": "x" * 1000}] * 100},
                "missing": [],
                "warnings": [],
                "source_refs": [],
            }
            payload = AiAskRequest(
                question="2330 data",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
            )

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(ai_ask.tools, "read_stock_context", return_value=context),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["result"]["data"]["compact"]["status"], "failed")
            self.assertEqual(response["result"]["result_view"]["detail"], "compact_projection_failure")
            self.assertNotIn("large_legacy_rows", response["result"]["data"])
            self.assertLess(len(json.dumps(response, ensure_ascii=False)), 20_000)
        finally:
            db.close()

    def test_ask_brief_result_uses_slim_public_view(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            compact = {
                "kind": "stock_compact_evidence",
                "version": "stock_compact_evidence.v1",
                "target": {"type": "tw_stock", "id": "2330", "label": "TSMC", "market": "TWSE"},
                "quote": {"latest_price": 100.0, "is_realtime": False},
                "intraday_bars": {
                    "enabled": False,
                    "intervals": ["1m", "5m"],
                    "series": {},
                    "warnings": [],
                },
                "technical": {"analysis": {"selected_score": 2}},
            }
            stock_brief = {
                "kind": "stock_brief",
                "generated_at": date(2026, 6, 4),
                "as_of": "2026-06-04",
                "scope": {"stock_id": "2330"},
                "data": {
                    "compact": compact,
                    "technical_reports": {"daily": {"title": "raw report"}},
                },
                "summary": {
                    "highlights": ["Latest close is 100."],
                    "analysis": {"selected_score": 2},
                    "decision_evidence": {"raw": "large"},
                    "next_checks": [],
                },
                "prompt": {"system": "large prompt"},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
                "evidence_passport": {},
            }
            payload = AiAskRequest(
                question="2330 brief",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
            )

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["result"]["result_view"]["mode"], "brief")
            self.assertNotIn("prompt", response["result"])
            self.assertNotIn("technical_reports", response["result"]["data"])
            self.assertNotIn("decision_evidence", response["result"]["summary"])
            self.assertEqual(response["result"]["data"]["compact"], compact)
            self.assertEqual(response["result"]["stock"]["id"], "2330")
            self.assertEqual(response["result"]["stock"]["name"], "TSMC")
            self.assertEqual(response["result"]["quote"], compact["quote"])
            self.assertEqual(response["result"]["intraday"]["status"], "not_requested")
            self.assertEqual(response["result"]["analysis"], compact["technical"]["analysis"])
        finally:
            db.close()

    def test_market_brief_mode_returns_compact_market_brief(self) -> None:
        db = make_session()
        try:
            source_id, raw_result_id = add_raw_source(db, "market_daily_price")
            trade_date = date(2026, 6, 4)
            db.add_all(
                [
                    StockMaster(
                        stock_id="2330",
                        stock_name="TSMC",
                        market="TWSE",
                        instrument_type="stock",
                        industry="Semiconductor",
                    ),
                    StockMaster(
                        stock_id="2303",
                        stock_name="UMC",
                        market="TWSE",
                        instrument_type="stock",
                        industry="Semiconductor",
                    ),
                    StockMaster(
                        stock_id="2603",
                        stock_name="EMC",
                        market="TWSE",
                        instrument_type="stock",
                        industry="Shipping",
                    ),
                    MarketDailyPrice(
                        source_id=source_id,
                        raw_result_id=raw_result_id,
                        trade_date=trade_date,
                        stock_id="2330",
                        stock_name="TSMC",
                        close_price=100.0,
                        price_change=5.0,
                        trade_volume=1_000_000,
                        trade_value=100_000_000,
                    ),
                    MarketDailyPrice(
                        source_id=source_id,
                        raw_result_id=raw_result_id,
                        trade_date=trade_date,
                        stock_id="2303",
                        stock_name="UMC",
                        close_price=50.0,
                        price_change=-2.0,
                        trade_volume=2_000_000,
                        trade_value=80_000_000,
                    ),
                    MarketDailyPrice(
                        source_id=source_id,
                        raw_result_id=raw_result_id,
                        trade_date=trade_date,
                        stock_id="2603",
                        stock_name="EMC",
                        close_price=30.0,
                        price_change=1.0,
                        trade_volume=3_000_000,
                        trade_value=90_000_000,
                    ),
                ]
            )
            db.commit()
            payload = AiAskRequest(
                question="台股市場總覽 brief",
                target={"type": "market"},
                mode="brief",
                market_limit=2,
            )

            with patch.object(
                ai_ask,
                "_check_freshness",
                return_value={"is_current": True, "missing": [], "warnings": []},
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["mode"]["effective"], "brief")
            self.assertEqual(response["action"], "omi.generate_market_brief")
            self.assertEqual(response["result"]["kind"], "market_brief")
            self.assertNotIn("prompt", response["result"])
            self.assertEqual(response["analysis"]["kind"], "market_brief_digest")
            self.assertEqual(response["result"]["latest_trade_date"], "2026-06-04")
            self.assertEqual(len(response["result"]["top_gainers"]), 2)
            self.assertEqual(len(response["result"]["top_losers"]), 1)
            self.assertEqual(len(response["result"]["value_leaders"]), 2)
            self.assertEqual(len(response["result"]["data"]["top_gainers"]), 2)
            self.assertEqual(len(response["result"]["data"]["top_losers"]), 1)
            self.assertTrue(
                all(row["change_pct"] > 0 for row in response["result"]["top_gainers"])
            )
            self.assertTrue(
                all(row["change_pct"] < 0 for row in response["result"]["top_losers"])
            )
            self.assertEqual(
                response["result"]["data"]["compact"]["sample_breadth"]["label"],
                "OMI 樣本股廣度",
            )
            self.assertEqual(
                response["result"]["data"]["compact"]["sample_breadth"]["total_count"],
                3,
            )
            self.assertEqual(
                response["result"]["sample_top_gainers"],
                response["result"]["top_gainers"],
            )
            human_text = response["analysis"]["human_answer"]["text"]
            self.assertIn("OMI 3 檔追蹤樣本上漲股", human_text)
            self.assertNotIn("\n上漲股：", human_text)
            self.assertTrue(response["analysis"]["human_answer"]["summary"])
            self.assertFalse(
                any("does not have a brief" in warning for warning in response["warnings"])
            )
        finally:
            db.close()

    def test_negative_leading_industry_is_labeled_relative_resilience(self) -> None:
        self.assertEqual(
            taiwan_market._industry_strength_label(
                [{"industry": "Semiconductor", "average_change_pct": -6.28}]
            ),
            "相對抗跌產業",
        )

    def test_market_brief_can_include_bounded_index_intraday(self) -> None:
        db = make_session()
        try:
            source_id, raw_result_id = add_raw_source(db, "market_daily_price")
            trade_date = date(2026, 6, 4)
            db.add_all(
                [
                    MarketDailyPrice(
                        source_id=source_id,
                        raw_result_id=raw_result_id,
                        trade_date=trade_date,
                        stock_id="2330",
                        stock_name="TSMC",
                        close_price=100.0,
                        price_change=5.0,
                        trade_volume=1_000_000,
                        trade_value=100_000_000,
                    ),
                    MarketDailyPrice(
                        source_id=source_id,
                        raw_result_id=raw_result_id,
                        trade_date=trade_date,
                        stock_id="2303",
                        stock_name="UMC",
                        close_price=50.0,
                        price_change=-2.0,
                        trade_volume=2_000_000,
                        trade_value=80_000_000,
                    ),
                ]
            )
            db.commit()
            payload = AiAskRequest(
                question="台股大盤盤中怎麼看?",
                target={"type": "market"},
                mode="brief",
                allow_external_fetch=True,
                market_limit=2,
                market_data_params={"include_intraday": True, "payload_level": "summary"},
            )

            def intraday_result(index_id):
                return {
                    "stock_id": index_id,
                    "symbol": "^TWII" if index_id == "TAIEX" else "TWOII",
                    "source": "twse_index_5s",
                    "previous_close": 18000.0,
                    "point_count": 3,
                    "points": [
                        {
                            "time": f"2026-06-04T09:0{index}+00:00",
                            "price": 18000.0 + index,
                            "open": 18000.0,
                            "high": 18000.0 + index,
                            "low": 17990.0,
                        }
                        for index in range(3)
                    ],
                }

            with (
                patch.object(
                    ai_ask,
                    "_check_freshness",
                    return_value={"is_current": True, "missing": [], "warnings": []},
                ),
                patch.object(ai_ask.tools, "get_market_index_intraday", side_effect=intraday_result) as intraday,
            ):
                response = ai_ask.ask(
                    db=db,
                    payload=payload,
                    server_policy=ai_ask.AiAskServerPolicy(
                        can_external_fetch=True,
                        trust_source="test",
                    ),
                )

            self.assertEqual(intraday.call_count, 2)
            index_intraday = response["result"]["index_intraday"]
            self.assertTrue(index_intraday["enabled"])
            self.assertEqual(index_intraday["payload_level"], "summary")
            self.assertEqual(len(index_intraday["indices"]), 2)
            first_series = index_intraday["indices"][0]["intraday_bars"]["series"]["1m"]
            self.assertEqual(first_series["returned_point_count"], 1)
            self.assertEqual(response["result"]["data"]["slots"]["index_intraday"]["status"], "ready")
            self.assertEqual(response["result"]["data"]["slots"]["index_intraday"]["payload_ref"], "index_intraday")
            self.assertIn("指數盤中", response["analysis"]["display"])
        finally:
            db.close()

    def test_untrusted_market_intraday_request_does_not_fetch_external_data(self) -> None:
        db = make_session()
        try:
            source_id, raw_result_id = add_raw_source(db, "market_daily_price")
            db.add(
                MarketDailyPrice(
                    source_id=source_id,
                    raw_result_id=raw_result_id,
                    trade_date=date(2026, 6, 4),
                    stock_id="2330",
                    stock_name="TSMC",
                    close_price=100.0,
                    price_change=5.0,
                )
            )
            db.commit()
            payload = AiAskRequest(
                question="台股大盤盤中",
                target={"type": "market"},
                mode="data_only",
                allow_external_fetch=True,
                market_data_params={"include_intraday": True},
            )

            with (
                patch.object(
                    ai_ask,
                    "_check_freshness",
                    return_value={"is_current": True, "missing": [], "warnings": []},
                ),
                patch.object(ai_ask.tools, "get_market_index_intraday") as intraday,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            intraday.assert_not_called()
            self.assertFalse(response["policy"]["can_external_fetch"])
            self.assertFalse(response["result"]["data"]["index_intraday"]["enabled"])
            self.assertEqual(response["result"]["data"]["slots"]["index_intraday"]["status"], "not_requested")
        finally:
            db.close()

    def test_ask_downgrades_incomplete_report_without_calling_llm(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="generate report for 2330",
                target={"type": "tw_stock", "id": "2330"},
                mode="report",
                allow_llm=True,
                allow_write=True,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=True,
                trust_source="token",
            )

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
                patch.object(ai_ask.orchestrator, "generate_stock_llm_report") as generate_report,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_report.assert_not_called()
            self.assertEqual(response["contract_version"], "omi.ai.ask.v2")
            self.assertEqual(response["target"]["type"], "tw_stock")
            self.assertEqual(response["target"]["id"], "2330")
            self.assertEqual(response["mode"]["requested"], "report")
            self.assertEqual(response["mode"]["effective"], "brief")
            self.assertNotIn("scope_type", response)
            self.assertNotIn("scope_id", response)
            self.assertFalse(response["freshness"]["is_current"])
            self.assertIn("market_daily_price", response["missing"])
            self.assertIn("monthly_revenue", response["missing"])
            self.assertIn(response["evidence_passport"]["trust_level"], {"low", "blocked"})
            self.assertIn("market_daily_price", response["evidence_passport"]["missing"])
            self.assertTrue(
                any("Report mode skipped" in warning for warning in response["warnings"])
            )
        finally:
            db.close()

    def test_tw_stock_refreshes_stale_evidence_before_answer_when_allowed(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="2330 今天最新怎麼看",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
                allow_external_fetch=True,
                tool_budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 25},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=False,
                can_write=False,
                can_external_fetch=True,
                trust_source="local_allowlist",
            )

            with patch.object(
                ai_ask.agentic_tools.stock_selection_refresh,
                "refresh_selected_stock_data",
                return_value={
                    "status": "success",
                    "message": "Selected stock data refresh completed.",
                    "stock_id": "2330",
                    "daily_price_date": date(2026, 6, 4),
                    "institutional_trade_date": date(2026, 6, 4),
                    "margin_trade_date": date(2026, 6, 4),
                    "requested_count": 7,
                    "refreshed_count": 7,
                    "skipped_count": 0,
                    "error_count": 0,
                },
            ) as refresh_selected:
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            refresh_selected.assert_called_once()
            self.assertEqual(refresh_selected.call_args.kwargs["stock_id"], "2330")
            self.assertEqual(response["tool_plan"]["provider"], "fallback")
            self.assertEqual(response["tool_runs"][0]["tool"], "tw.refresh_stock_evidence")
            self.assertEqual(response["tool_runs"][0]["status"], "success")
            self.assertTrue(response["policy"]["refresh_policy"]["before_answer"])
        finally:
            db.close()

    def test_tw_stock_refresh_is_blocked_without_external_fetch_trust(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="2330 今天最新怎麼看",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
                allow_external_fetch=True,
                tool_budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 25},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=False,
                can_write=False,
                can_external_fetch=False,
                trust_source="untrusted",
            )

            with patch.object(
                ai_ask.agentic_tools.stock_selection_refresh,
                "refresh_selected_stock_data",
            ) as refresh_selected:
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            refresh_selected.assert_not_called()
            self.assertEqual(response["tool_runs"][0]["tool"], "tw.refresh_stock_evidence")
            self.assertEqual(response["tool_runs"][0]["status"], "blocked")
            self.assertIn("External fetch is not allowed", response["tool_runs"][0]["error"])
            self.assertFalse(response["policy"]["can_external_fetch"])
        finally:
            db.close()

    def test_tw_watchlist_refreshes_stale_daily_prices_before_answer_when_allowed(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="科技股狀況",
                target={"type": "tw_watchlist", "id": "1"},
                mode="brief",
                allow_external_fetch=True,
                tool_budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 25},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=False,
                can_write=False,
                can_external_fetch=True,
                trust_source="local_allowlist",
            )
            stale_freshness = {
                "kind": "ai_scope_freshness",
                "scope_type": "watchlist",
                "scope_id": "1",
                "is_current": False,
                "stale_stock_count": 2,
                "missing": ["market_daily_price"],
                "expected_dates": {"market_daily_price": "2026-06-08"},
                "warnings": ["Local OMI data is incomplete for 2 stock(s)."],
                "refresh_recommended": True,
                "refresh_params": {
                    "lookback_days": 14,
                    "include_today": False,
                    "include_children": True,
                    "enabled_only": True,
                    "sleep_seconds": 0.3,
                    "skip_existing_months": True,
                },
            }
            current_freshness = {
                **stale_freshness,
                "is_current": True,
                "stale_stock_count": 0,
                "missing": [],
                "warnings": [],
                "refresh_recommended": False,
            }

            with (
                patch.object(
                    ai_ask.freshness,
                    "check_watchlist_data_freshness",
                    side_effect=[stale_freshness, current_freshness],
                ) as check_freshness,
                patch.object(
                    ai_ask.agentic_tools.watchlist_backfill_service,
                    "refresh_watchlist_group_daily_prices",
                    return_value={
                        "group_id": 1,
                        "requested_stock_count": 2,
                        "current_count": 0,
                        "success_count": 2,
                        "warning_count": 0,
                        "error_count": 0,
                        "skipped_count": 0,
                        "target_date": date(2026, 6, 8),
                    },
                ) as refresh_group,
                patch.object(
                    ai_ask.reports,
                    "build_watchlist_brief",
                    return_value={
                        "kind": "watchlist_brief",
                        "warnings": [],
                        "strategy_profile": "short_term_momentum",
                    },
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            self.assertEqual(check_freshness.call_count, 2)
            refresh_group.assert_called_once()
            self.assertEqual(refresh_group.call_args.kwargs["group_id"], 1)
            self.assertTrue(refresh_group.call_args.kwargs["include_children"])
            self.assertTrue(refresh_group.call_args.kwargs["enabled_only"])
            self.assertEqual(response["tool_plan"]["provider"], "fallback")
            self.assertEqual(response["tool_runs"][0]["tool"], "tw.refresh_watchlist_evidence")
            self.assertEqual(response["tool_runs"][0]["status"], "success")
            self.assertTrue(response["freshness"]["is_current"])
            self.assertFalse(any(action["type"] == "refresh_data" for action in response["next_actions"]))
        finally:
            db.close()

    def test_watchlist_brief_summary_exposes_sector_overview(self) -> None:
        db = make_session()
        try:
            context = {
                "kind": "watchlist_context",
                "generated_at": "2026-06-08T09:05:00+08:00",
                "as_of": "2026-06-08",
                "scope": {
                    "group_id": 1,
                    "group_name": "科技股",
                    "include_children": True,
                    "enabled_only": True,
                },
                "data": {
                    "ranking": {
                        "group_id": 1,
                        "rank_by": "score",
                        "sort_order": "desc",
                        "requested_stock_count": 3,
                        "ranked_count": 3,
                        "no_data_count": 0,
                        "error_count": 0,
                        "trade_date": date(2026, 6, 8),
                        "target_trade_date": date(2026, 6, 8),
                        "is_current": True,
                        "current_stock_count": 3,
                        "stale_stock_count": 0,
                        "results": [
                            {
                                "rank": 1,
                                "stock_id": "2330",
                                "stock_name": "台積電",
                                "time": "2026-06-08",
                                "close": 2365,
                                "volume": 38924,
                                "change": 35,
                                "change_pct": 1.50,
                                "limit_status": None,
                                "score": 72,
                                "status": "bullish",
                                "signal_count": 2,
                                "signal_keys": ["macd_bullish"],
                                "primary_signal_key": "macd_bullish",
                                "primary_signal_label": "MACD偏多",
                                "error_message": None,
                            },
                            {
                                "rank": 2,
                                "stock_id": "2303",
                                "stock_name": "聯電",
                                "time": "2026-06-08",
                                "close": 131.5,
                                "volume": 377472,
                                "change": 6.5,
                                "change_pct": 5.20,
                                "limit_status": None,
                                "score": 48,
                                "status": "bullish",
                                "signal_count": 1,
                                "signal_keys": ["volume_price_up"],
                                "primary_signal_key": "volume_price_up",
                                "primary_signal_label": "量價上攻",
                                "error_message": None,
                            },
                            {
                                "rank": 3,
                                "stock_id": "2454",
                                "stock_name": "聯發科",
                                "time": "2026-06-08",
                                "close": 4300,
                                "volume": 11889,
                                "change": -130,
                                "change_pct": -2.93,
                                "limit_status": None,
                                "score": -22,
                                "status": "bearish",
                                "signal_count": 1,
                                "signal_keys": ["roc_negative"],
                                "primary_signal_key": "roc_negative",
                                "primary_signal_label": "動能轉弱",
                                "error_message": None,
                            },
                        ],
                    },
                    "radar": {
                        "group_id": 1,
                        "include_children": True,
                        "mode": "action",
                        "requested_stock_count": 3,
                        "matched_count": 2,
                        "radar_count": 2,
                        "trade_date": date(2026, 6, 8),
                        "target_trade_date": date(2026, 6, 8),
                        "is_current": True,
                        "stale_stock_count": 0,
                        "buckets": [
                            {"key": "breakout", "label": "突破動能", "count": 1},
                            {"key": "risk", "label": "風險優先", "count": 1},
                        ],
                        "results": [
                            {
                                "rank": 1,
                                "stock_id": "2330",
                                "stock_name": "台積電",
                                "bucket": "breakout",
                                "bucket_label": "突破動能",
                                "urgency": "high",
                                "action_label": "追蹤突破延續",
                                "reason": "主要訊號：MACD偏多",
                                "trade_date": date(2026, 6, 8),
                                "time": "2026-06-08",
                                "close": 2365,
                                "change_pct": 1.50,
                                "score": 72,
                                "status": "bullish",
                                "signal_labels": ["MACD偏多"],
                                "matched_signal_keys": ["macd_bullish"],
                                "primary_signal_label": "MACD偏多",
                                "stale": False,
                            },
                            {
                                "rank": 2,
                                "stock_id": "2454",
                                "stock_name": "聯發科",
                                "bucket": "risk",
                                "bucket_label": "風險優先",
                                "urgency": "medium",
                                "action_label": "優先檢查風控",
                                "reason": "主要訊號：動能轉弱",
                                "trade_date": date(2026, 6, 8),
                                "time": "2026-06-08",
                                "close": 4300,
                                "change_pct": -2.93,
                                "score": -22,
                                "status": "bearish",
                                "signal_labels": ["動能轉弱"],
                                "matched_signal_keys": ["roc_negative"],
                                "primary_signal_label": "動能轉弱",
                                "stale": False,
                            },
                        ],
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [],
            }

            with patch.object(ai_reports.tools, "read_watchlist_context", return_value=context) as read_context:
                result = ai_reports.build_watchlist_brief(
                    db=db,
                    group_id=1,
                    rank_by="score",
                    sort_order="desc",
                    radar_mode="risk",
                )

            self.assertEqual(read_context.call_args.kwargs["radar_mode"], "risk")
            overview = result["summary"]["overview"]
            self.assertEqual(result["data"]["overview"], overview)
            self.assertEqual(overview["kind"], "watchlist_sector_overview")
            self.assertEqual(overview["group_name"], "科技股")
            self.assertEqual(overview["breadth"]["up_count"], 2)
            self.assertEqual(overview["breadth"]["down_count"], 1)
            self.assertEqual(overview["data_status"]["is_complete"], True)
            self.assertIn("結論", overview["answer_outline"][0])
            self.assertEqual(overview["human_answer"]["kind"], "watchlist_sector_human_answer")
            self.assertEqual(
                [section["label"] for section in overview["human_answer"]["sections"]],
                ["結論", "雷達", "追蹤", "等回測", "保守", "資料"],
            )
            self.assertEqual(result["summary"]["radar"]["matched_count"], 2)
            self.assertEqual(result["data"]["radar"]["results"][0]["label"], "2330 台積電")
            self.assertEqual(overview["radar_rows"][0]["label"], "2330 台積電")
            self.assertIn("雷達：2 檔命中", overview["human_answer"]["text"])
            self.assertIn("2330 台積電（高，追蹤突破延續）", overview["human_answer"]["text"])
            self.assertIn("追蹤：", overview["human_answer"]["text"])
            self.assertIn("等回測：2303 聯電", overview["human_answer"]["text"])
            self.assertIn("2330 台積電", overview["strong_rows"][0]["label"])
            self.assertIn("2330 台積電", overview["follow_rows"][0]["label"])
            self.assertIn("2454 聯發科", overview["defensive_rows"][0]["label"])
            self.assertIn("display", result["summary"]["top_rows"][0])
        finally:
            db.close()

    def test_read_watchlist_context_attaches_radar_from_single_ranking_read(self) -> None:
        ranking = {
            "group_id": 1,
            "rank_by": "score",
            "sort_order": "desc",
            "requested_stock_count": 1,
            "ranked_count": 1,
            "no_data_count": 0,
            "error_count": 0,
            "trade_date": date(2026, 6, 8),
            "target_trade_date": date(2026, 6, 8),
            "is_current": True,
            "current_stock_count": 1,
            "stale_stock_count": 0,
            "results": [
                {
                    "rank": 1,
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "time": "2026-06-08",
                    "close": 2365,
                    "volume": 38924,
                    "change": 35,
                    "change_pct": 1.50,
                    "limit_status": None,
                    "score": 72,
                    "status": "bullish",
                    "signal_count": 2,
                    "signal_keys": ["donchian_breakout", "volume_price_up"],
                    "primary_signal_key": "donchian_breakout",
                    "primary_signal_label": "突破 20 日高",
                    "error_message": None,
                }
            ],
        }

        with (
            patch.object(
                ai_tools.watchlist_service,
                "get_group",
                return_value=SimpleNamespace(group_name="科技股"),
            ),
            patch.object(
                ai_tools.ranking_service,
                "get_watchlist_group_latest_ranking",
                return_value=ranking,
            ) as read_ranking,
        ):
            context = ai_tools.read_watchlist_context(
                db=object(),
                group_id=1,
                include_children=False,
                enabled_only=True,
                rank_by="score",
                sort_order="desc",
                limit=20,
                radar_mode="momentum",
            )

        read_ranking.assert_called_once()
        self.assertEqual(read_ranking.call_args.kwargs["group_id"], 1)
        self.assertFalse(read_ranking.call_args.kwargs["include_children"])
        self.assertEqual(read_ranking.call_args.kwargs["limit"], 20)
        self.assertEqual(context["as_of"], "2026-06-08")
        self.assertEqual(context["scope"]["group_name"], "科技股")
        self.assertIn("watchlist_radar", [source["name"] for source in context["source_refs"]])
        self.assertIn("radar", context["warnings"][0].lower())

        radar = context["data"]["radar"]
        self.assertEqual(radar["group_id"], 1)
        self.assertEqual(radar["mode"], "momentum")
        self.assertEqual(context["scope"]["radar_mode"], "momentum")
        self.assertEqual(radar["matched_count"], 1)
        self.assertEqual(radar["radar_count"], 1)
        self.assertEqual(radar["results"][0]["stock_id"], "2330")
        self.assertEqual(radar["results"][0]["bucket"], "breakout_high")
        compact = context["data"]["compact"]
        self.assertEqual(compact["kind"], "tw_watchlist_compact_evidence")
        self.assertEqual(compact["ranking"]["returned_count"], 1)
        self.assertEqual(compact["slots"]["ranking"]["status"], "ready")
        self.assertEqual(compact["slots"]["institutional"]["status"], "missing")
        self.assertEqual(compact["slots"]["broker_branch"]["status"], "missing")
        self.assertEqual(compact["slots"]["data_quality"]["status"], "partial")

    def test_watchlist_human_answer_masks_raw_dataset_keys(self) -> None:
        db = make_session()
        try:
            context = {
                "kind": "watchlist_context",
                "generated_at": "2026-06-08T09:05:00+08:00",
                "as_of": "2026-06-05",
                "scope": {
                    "group_id": 1,
                    "group_name": "科技股",
                    "include_children": True,
                    "enabled_only": True,
                },
                "data": {
                    "ranking": {
                        "group_id": 1,
                        "rank_by": "score",
                        "sort_order": "desc",
                        "requested_stock_count": 2,
                        "ranked_count": 1,
                        "no_data_count": 1,
                        "error_count": 0,
                        "trade_date": date(2026, 6, 5),
                        "target_trade_date": date(2026, 6, 8),
                        "is_current": False,
                        "current_stock_count": 1,
                        "stale_stock_count": 1,
                        "results": [
                            {
                                "rank": 1,
                                "stock_id": "5289",
                                "stock_name": "宜鼎",
                                "time": "2026-06-05",
                                "close": 100,
                                "volume": 1000,
                                "change": 1,
                                "change_pct": 1.0,
                                "limit_status": None,
                                "score": 38,
                                "status": "bullish",
                                "signal_count": 1,
                                "signal_keys": ["macd_bullish"],
                                "primary_signal_key": "macd_bullish",
                                "primary_signal_label": "MACD偏多",
                                "error_message": None,
                            }
                        ],
                    },
                },
                "missing": ["margin_trading_daily", "broker_branch_trade_daily"],
                "warnings": [],
                "source_refs": [],
            }

            with patch.object(ai_reports.tools, "read_watchlist_context", return_value=context):
                result = ai_reports.build_watchlist_brief(db=db, group_id=1, rank_by="score", sort_order="desc")

            human_text = result["summary"]["overview"]["human_answer"]["text"]
            self.assertIn("融資券", human_text)
            self.assertIn("分點", human_text)
            self.assertNotIn("margin_trading_daily", human_text)
            self.assertNotIn("broker_branch_trade_daily", human_text)
            self.assertEqual(result["summary"]["overview"]["data_status"]["human_missing"], ["融資券", "分點"])
        finally:
            db.close()

    def test_ask_allows_non_persistent_analysis_without_write(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                target={"type": "tw_stock", "id": "2330"},
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )

            with patch.object(
                ai_ask.orchestrator,
                "generate_stock_llm_analysis",
                return_value={"kind": "stock_llm_analysis", "warnings": []},
            ) as generate_analysis:
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_analysis.assert_called_once()
            self.assertEqual(response["mode"]["requested"], "analysis")
            self.assertEqual(response["mode"]["effective"], "analysis")
            self.assertEqual(response["action"], "omi.generate_stock_llm_analysis")
            self.assertTrue(response["policy"]["can_call_llm"])
            self.assertFalse(response["policy"]["can_write"])
            self.assertFalse(response["policy"]["can_generate_report"])
        finally:
            db.close()

    def test_ask_attaches_consumer_human_answer_from_llm_report(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                target={"type": "tw_stock", "id": "2330"},
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )
            analysis_result = {
                "kind": "stock_llm_analysis",
                "strategy_profile": "short_term_momentum",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "daily",
                        "selected_score": 26,
                        "selected_title": "短線偏多",
                        "selected_summary": "站上 MA20，量能普通",
                        "selected_confidence": "medium",
                    }
                },
                "llm": {
                    "report": {
                        "headline": "短線偏多但不適合追高",
                        "stance": "bullish",
                        "confidence": "medium",
                        "as_of": "2026-06-12",
                        "key_observations": ["價格站上 MA20", "MACD 偏多"],
                        "interpretation": ["短線結構仍偏多，但量能沒有明顯放大。"],
                        "risks": ["缺少盤中即時資料，無法確認今日跟進力度。", "若跌回 MA20，短線結論需要降級。"],
                        "missing_data": ["盤中即時資料不足。"],
                        "next_checks": ["觀察下一根 K 是否守住 MA20。"],
                        "disclaimer": "僅根據 OMI 證據包。",
                    }
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(
                    ai_ask.orchestrator,
                    "generate_stock_llm_analysis",
                    return_value=analysis_result,
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(human_answer["kind"], "consumer_market_answer")
            self.assertEqual(human_answer["source"], "llm_report")
            self.assertEqual(human_answer["stance_label"], "偏多")
            self.assertEqual(human_answer["confidence_label"], "中")
            self.assertIn("短線偏多", human_answer["headline"])
            self.assertEqual(len(human_answer["summary"]), 3)
            self.assertEqual([item["label"] for item in human_answer["action_plan"]], ["已持有", "想進場", "失效"])
            self.assertIn("跌回 MA20", human_answer["action_plan"][2]["text"])
            self.assertFalse(any("缺少" in item for item in human_answer["risks"]))
            self.assertEqual(human_answer["data_limits"], [])
            self.assertNotIn("盤中即時資料不足", human_answer["text"])
            self.assertNotIn("盤中即時資料不足", human_answer["detail"])
            self.assertIn("怎麼做", human_answer["text"])
        finally:
            db.close()

    def test_analysis_mode_trend_view_prefers_structured_answer_over_llm_wording(self) -> None:
        db = make_session()
        try:
            add_stock(db, stock_id="2303")
            payload = AiAskRequest(
                question=(
                    "用中線波段角度分析目前標的。請使用日K/週K、均線、動能、量能、籌碼、營收與相對市場資料；"
                    "先給結論，再列出趨勢、支撐壓力、觀察條件與主要風險。"
                ),
                target={"type": "tw_stock", "id": "2303", "label": "2303 聯電"},
                mode="analysis",
                allow_llm=True,
                allow_write=False,
                strategy_profile="technical_swing",
                analysis_horizon="swing",
                conversation_context={"ui_context": {"ask_intent": "swing"}},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )
            analysis_result = {
                "kind": "stock_llm_analysis",
                "strategy_profile": "technical_swing",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 3,
                        "selected_title": "波段偏多",
                        "selected_summary": "中線結構偏多，但短線偏熱。",
                        "selected_confidence": "high",
                    },
                    "technical_levels": {
                        "kind": "technical_price_levels",
                        "latest_price": 141.0,
                        "entry": {
                            "preferred_zone": {"low": 129.0, "high": 134.0},
                            "breakout_confirm_above": {"price": 156.0},
                            "do_not_chase_above": {"price": 143.0},
                        },
                        "risk": {
                            "short_stop": {"price": 124.0},
                            "technical_invalidation": {"price": 130.0},
                        },
                    },
                },
                "llm": {
                    "report": {
                        "headline": "2303 聯電：波段偏多但短線偏熱，141 元靠近追價上限",
                        "interpretation": ["請觀察是否站穩 141 附近。"],
                        "confidence": "high",
                        "stance": "bullish",
                    }
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(
                    ai_ask.orchestrator,
                    "generate_stock_llm_analysis",
                    return_value=analysis_result,
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(response["analysis"]["question_intent"], "trend_view")
            self.assertEqual(human_answer["source"], "question_intent")
            self.assertIn("129-134", human_answer["headline"])
            self.assertIn("129-134", human_answer["text"])
            self.assertIn("143", human_answer["text"])
            self.assertIn("156", human_answer["text"])
            self.assertIn("130", human_answer["text"])
            self.assertNotIn("站穩 141", human_answer["text"])
        finally:
            db.close()

    def test_ask_keeps_llm_missing_data_as_data_limit_when_backend_missing(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                target={"type": "tw_stock", "id": "2330"},
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )
            analysis_result = {
                "kind": "stock_llm_analysis",
                "strategy_profile": "short_term_momentum",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "daily",
                        "selected_score": None,
                        "selected_title": "資料不足",
                        "selected_summary": "缺少日線，無法確認方向。",
                        "selected_confidence": "low",
                    }
                },
                "llm": {
                    "report": {
                        "headline": "資料不足，先不要下結論",
                        "stance": "insufficient_data",
                        "confidence": "low",
                        "as_of": "2026-06-12",
                        "key_observations": [],
                        "interpretation": ["缺少日線時，不應判斷多空。"],
                        "risks": ["資料缺口會讓方向判斷失真。"],
                        "missing_data": ["market_daily_price 缺少最新日線。"],
                        "next_checks": ["先補日線資料。"],
                        "disclaimer": "僅根據 OMI 證據包。",
                    }
                },
                "missing": ["market_daily_price"],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(
                    ai_ask.orchestrator,
                    "generate_stock_llm_analysis",
                    return_value=analysis_result,
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            human_answer = response["analysis"]["human_answer"]
            self.assertIn("market_daily_price 缺少最新日線", human_answer["data_limits"][0])
            self.assertTrue(any("資料缺口" in item for item in human_answer["data_limits"]))
        finally:
            db.close()

    def test_ask_downgrades_analysis_without_trust(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                target={"type": "tw_stock", "id": "2330"},
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )

            with patch.object(ai_ask.orchestrator, "generate_stock_llm_analysis") as generate_analysis:
                response = ai_ask.ask(db=db, payload=payload)

            generate_analysis.assert_not_called()
            self.assertEqual(response["mode"]["requested"], "analysis")
            self.assertEqual(response["mode"]["effective"], "brief")
            self.assertFalse(response["policy"]["can_call_llm"])
            self.assertTrue(
                any("Analysis mode requires" in warning for warning in response["warnings"])
            )
        finally:
            db.close()

    def test_ask_resolves_stock_id_from_question_text(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="analyze 2330 risk",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["contract_version"], "omi.ai.ask.v2")
            self.assertEqual(response["target"]["type"], "tw_stock")
            self.assertEqual(response["target"]["id"], "2330")
            self.assertEqual(response["action"], "omi.generate_stock_brief")
            self.assertEqual(response["resolution"]["target"]["id"], "2330")
            self.assertFalse(response["clarification"]["required"])
            self.assertTrue(response["answer_ready"])
            self.assertIn(response["report_level"], {"brief", "brief_with_gaps"})
        finally:
            db.close()

    def test_ask_defaults_auto_horizon_to_swing_for_tw_stock(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請看 2330 目前怎麼樣",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["policy"]["analysis_horizon"]["requested"], "auto")
            self.assertEqual(response["policy"]["analysis_horizon"]["effective"], "swing")
            self.assertTrue(response["policy"]["analysis_horizon"]["defaulted"])
            self.assertEqual(response["result"]["data"]["analysis"]["selected_horizon"], "swing")
            self.assertEqual(response["analysis"]["selected_horizon"], "swing")
            self.assertEqual(response["analysis"]["horizon_label"], "中短線")
            self.assertEqual(response["analysis"]["source"], "result.data.analysis")
            self.assertIn("中短線評分", response["analysis"]["display"])
        finally:
            db.close()

    def test_direct_entry_question_returns_question_aware_answer(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="可以幫我看看如果想抄底要抄哪裡嗎",
                target={"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 4,
                        "selected_title": "波段偏多",
                        "selected_summary": "週線站上 MA20，動能偏多。",
                        "selected_confidence": "high",
                        "scores": {"short": 1, "swing": 4, "long": 5},
                        "components": [],
                    },
                    "technical_levels": {
                        "kind": "technical_price_levels",
                        "version": "price_levels_v1",
                        "latest_price": 855.0,
                        "entry": {
                            "preferred_zone": {"low": 803.0, "high": 834.0},
                            "breakout_confirm_above": {"price": 919.0},
                            "do_not_chase_above": {"price": 871.0},
                        },
                        "risk": {
                            "short_stop": {"price": 771.0},
                            "technical_invalidation": {"price": 716.0},
                        },
                        "context": {"extended": True},
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(response["action"], "omi.generate_stock_brief")
            self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
            self.assertEqual(human_answer["source"], "question_intent")
            self.assertEqual(human_answer["intent"], "entry_decision")
            self.assertEqual(
                [item["label"] for item in human_answer["action_plan"]],
                ["現在", "進場條件", "風控"],
            )
            self.assertIn("不建議直接追價", human_answer["headline"])
            self.assertIn("803-834", human_answer["text"])
            self.assertIn("919", human_answer["text"])
            self.assertIn("771", human_answer["text"])
            self.assertIn("716", human_answer["text"])
            reasoning_stages = [step["stage"] for step in response["reasoning_steps"]]
            self.assertIn("question_understanding", reasoning_stages)
            self.assertIn("price_levels", reasoning_stages)
            self.assertIn("decision_synthesis", reasoning_stages)
        finally:
            db.close()

    def test_entry_question_inside_pullback_zone_uses_price_position(self) -> None:
        db = make_session()
        try:
            add_stock(db, stock_id="3661")
            payload = AiAskRequest(
                question="你覺得目前價位是好買點嗎",
                target={"type": "tw_stock", "id": "3661", "label": "3661 世芯-KY"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": -3,
                        "selected_title": "波段偏多",
                        "selected_summary": "波段：站上 MA20，MACD 偏多，量能一般。",
                        "selected_confidence": "high",
                        "scores": {"intraday": -7, "short": -7, "swing": -3, "long": 0},
                        "components": [],
                    },
                    "technical_levels": {
                        "kind": "technical_price_levels",
                        "version": "price_levels_v1",
                        "latest_price": 4105.0,
                        "entry": {
                            "preferred_zone": {"low": 4055.0, "high": 4195.0},
                            "conservative_zone": {"low": 4403.0, "high": 4542.0},
                            "breakout_confirm_above": {"price": 5050.0},
                            "do_not_chase_above": {"price": 4175.0},
                        },
                        "risk": {
                            "short_stop": {"price": 3915.0},
                            "technical_invalidation": {"price": 3850.0},
                        },
                        "context": {"extended": True},
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            human_answer = response["analysis"]["human_answer"]
            text = human_answer["text"]
            self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
            self.assertEqual(human_answer["source"], "question_intent")
            self.assertIn("回檔觀察區", human_answer["headline"])
            self.assertIn("不是好買點", human_answer["headline"])
            self.assertNotIn("重新站回關鍵區", human_answer["headline"])
            self.assertIn("現價 4,105 已落在 4,055-4,195", text)
            self.assertIn("不是自動買點", text)
            self.assertIn("4,403-4,542 視為重新轉強確認區", text)
            self.assertIn("跌破 3,915", text)
            self.assertIn("跌破 3,850", text)
            self.assertNotIn("保守買點", text)
        finally:
            db.close()

    def test_entry_question_uses_decision_evidence_context(self) -> None:
        db = make_session()
        try:
            add_stock(db, stock_id="2303")
            payload = AiAskRequest(
                question="如果我現在還想進場可以嗎，還是價格太高?",
                target={"type": "tw_stock", "id": "2303", "label": "2303 聯電"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 3,
                        "selected_title": "波段偏多",
                        "selected_summary": "週線站上 MA20，MACD 偏多，量能一般。",
                        "selected_confidence": "high",
                        "scores": {"intraday": 1, "short": 2, "swing": 3, "long": 2},
                        "components": [],
                    },
                    "technical_levels": {
                        "kind": "technical_price_levels",
                        "version": "price_levels_v1",
                        "latest_price": 136.0,
                        "entry": {
                            "preferred_zone": {"low": 132.5, "high": 133.5},
                            "breakout_confirm_above": {"price": 137.5},
                            "do_not_chase_above": {"price": 136.5},
                        },
                        "risk": {
                            "short_stop": {"price": 130.0},
                            "technical_invalidation": {"price": 127.4},
                        },
                    },
                    "decision_evidence": {
                        "kind": "stock_decision_evidence_v1",
                        "data_quality": {
                            "price": {
                                "source": "market_daily_price.close_price",
                                "as_of": "2026-06-12",
                            },
                            "volume": {
                                "source": "market_daily_price.trade_volume",
                                "display_value": "393.6 張",
                            },
                        },
                        "recent_volatility": {
                            "label": "high",
                            "summary": "近 5 日高波動，最大單日漲跌約 +6.80%，區間振幅約 +13.20%。",
                        },
                        "indicator_quality": {
                            "warnings": [
                                "MACD histogram 與 MACD-signal 不一致，需確認欄位口徑或正負號。"
                            ],
                        },
                        "fundamentals": {
                            "monthly_revenue": {
                                "summary": "2026-05-01 營收，年增 +12.50%，月增 +3.20%。"
                            },
                        },
                        "confidence_factors": {
                            "negative": [
                                "近 5 日高波動，追價需要降低部位。",
                                "MACD histogram 口徑需校驗。",
                            ],
                            "data_limits": ["institutional_trade_daily 尚缺或不完整。"],
                        },
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            human_answer = response["analysis"]["human_answer"]
            text = human_answer["text"]
            self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
            self.assertEqual(human_answer["source"], "question_intent")
            self.assertIn("近 5 日高波動", text)
            self.assertIn("2026-05-01 營收", text)
            self.assertIn("MACD histogram 口徑需校驗", text)
            data_limit_text = "\n".join(human_answer["data_limits"])
            self.assertIn("價格來源 market_daily_price.close_price，截至 2026-06-12", data_limit_text)
            self.assertIn("成交量來源 market_daily_price.trade_volume，折算約 393.6 張", data_limit_text)
            self.assertIn("institutional_trade_daily 尚缺或不完整", data_limit_text)
            self.assertEqual(
                human_answer["decision_evidence"]["kind"],
                "stock_decision_evidence_v1",
            )
        finally:
            db.close()

    def test_entry_question_marks_non_trading_day_context(self) -> None:
        db = make_session()
        try:
            add_stock(db, stock_id="2327")
            payload = AiAskRequest(
                question="你怎麼看這檔股票呢，以現在來說你覺得適合買入嗎",
                target={"type": "tw_stock", "id": "2327", "label": "2327 國巨*"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 1,
                        "selected_title": "多空分歧",
                        "selected_summary": "週線偏多但短線偏熱。",
                        "selected_confidence": "medium",
                        "scores": {"intraday": None, "short": 1, "swing": 1, "long": 2},
                        "components": [],
                    },
                    "technical_levels": {
                        "kind": "technical_price_levels",
                        "version": "price_levels_v1",
                        "latest_price": 855.0,
                        "entry": {
                            "preferred_zone": {"low": 839.0, "high": 855.0},
                            "breakout_confirm_above": {"price": 903.0},
                            "do_not_chase_above": {"price": 875.0},
                        },
                        "risk": {
                            "short_stop": {"price": 803.0},
                            "technical_invalidation": {"price": 774.0},
                        },
                    },
                    "decision_evidence": {
                        "kind": "stock_decision_evidence_v1",
                        "data_quality": {
                            "price": {
                                "source": "market_daily_price.close_price",
                                "as_of": "2026-06-12",
                            },
                            "volume": {
                                "source": "market_daily_price.trade_volume",
                                "display_value": "26.3 張",
                            },
                        },
                        "market_session": {
                            "phase": "market_closed",
                            "is_trading_day": False,
                            "date": "2026-06-14",
                            "previous_trading_day": "2026-06-12",
                            "next_trading_day": "2026-06-15",
                            "latest_daily_date": "2026-06-12",
                            "summary": (
                                "2026-06-14 台股休市，最新日線截至 2026-06-12；"
                                "下一交易日 2026-06-15 再確認盤中價量。"
                            ),
                        },
                        "recent_volatility": {"label": "normal", "summary": "近 5 日波動正常。"},
                        "indicator_quality": {"warnings": []},
                        "fundamentals": {},
                        "confidence_factors": {
                            "negative": [],
                            "data_limits": [],
                        },
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            human_answer = response["analysis"]["human_answer"]
            text = human_answer["text"]
            data_limit_text = "\n".join(human_answer["data_limits"])
            self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
            self.assertIn("台股休市", text)
            self.assertIn("下一交易日 2026-06-15", text)
            self.assertIn("2026-06-14 非台股交易日", data_limit_text)
            self.assertIn("最新日線截至 2026-06-12", data_limit_text)
            self.assertFalse(human_answer["decision_evidence"]["market_session"]["is_trading_day"])
        finally:
            db.close()

    def test_position_stop_loss_question_uses_entry_price_and_latest_price(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="那如果我買在2440了，我該止損嗎",
                target={"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "latest_daily": {
                        "trade_date": "2026-06-12",
                        "stock_id": "2330",
                        "close_price": 2310.0,
                    },
                    "chart": {
                        "points": [
                            {"time": "2026-05-18", "low": 2260.0, "high": 2450.0, "close": 2320.0},
                            {"time": "2026-05-19", "low": 2250.0, "high": 2420.0, "close": 2310.0},
                        ],
                    },
                    "technical_reports": {
                        "daily": {
                            "timeframe": "daily",
                            "latest_close": 2310.0,
                            "ma20": 2298.5,
                            "ma60": 2128.42,
                            "score": 3,
                            "confidence": "high",
                        }
                    },
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 4,
                        "selected_title": "波段偏多",
                        "selected_summary": "週線站上 MA20，MACD 偏多，量能一般。",
                        "selected_confidence": "high",
                        "scores": {"short": 1, "swing": 4, "long": 5},
                        "components": [],
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            decision = response["analysis"]["position_decision"]
            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(response["analysis"]["question_intent"], "position_risk_decision")
            self.assertEqual(decision["entry_price"], 2440.0)
            self.assertEqual(decision["latest_price"], 2310.0)
            self.assertAlmostEqual(decision["unrealized_return_pct"], -5.3279, places=3)
            self.assertEqual(decision["llm_status"], "skipped_policy")
            self.assertEqual(human_answer["source"], "position_decision")
            self.assertIn("2440", human_answer["text"].replace(",", ""))
            self.assertIn("-5.33%", human_answer["text"])
            self.assertIn("停損", human_answer["text"])
            self.assertTrue(
                any(step["stage"] == "position_math" for step in response["reasoning_steps"])
            )
        finally:
            db.close()

    def test_position_cost_question_without_stop_words_uses_position_decision(self) -> None:
        db = make_session()
        try:
            add_stock(db, stock_id="6449")
            payload = AiAskRequest(
                question="我今天這檔買在444，你怎麼看",
                target={"type": "tw_stock", "id": "6449", "label": "6449 鈺邦"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "latest_daily": {
                        "trade_date": "2026-06-16",
                        "stock_id": "6449",
                        "close_price": 445.0,
                    },
                    "technical_reports": {
                        "daily": {
                            "timeframe": "daily",
                            "latest_close": 445.0,
                            "ma20": 435.0,
                            "score": 3,
                            "confidence": "high",
                        }
                    },
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 3,
                        "selected_title": "波段偏多",
                        "selected_summary": "價格仍在支撐區上方。",
                        "selected_confidence": "high",
                        "scores": {"short": 2, "swing": 3, "long": 2},
                        "components": [],
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief):
                response = ai_ask.ask(db=db, payload=payload)

            decision = response["analysis"]["position_decision"]
            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(response["analysis"]["question_intent"], "position_risk_decision")
            self.assertEqual(decision["entry_price"], 444.0)
            self.assertEqual(decision["latest_price"], 445.0)
            self.assertEqual(human_answer["source"], "position_decision")
            self.assertIn("成本 444", human_answer["text"].replace(",", ""))
            self.assertIn("最新 445", human_answer["text"].replace(",", ""))
            self.assertIn("部位", human_answer["text"])
        finally:
            db.close()

    def test_position_stop_loss_question_uses_llm_synthesis_when_trusted(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="那如果我買在2440了，我該止損嗎",
                target={"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                mode="auto",
                allow_llm=True,
                allow_write=False,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )
            stock_brief = {
                "kind": "stock_brief",
                "data": {
                    "latest_daily": {"trade_date": "2026-06-12", "close_price": 2310.0},
                    "technical_reports": {
                        "daily": {"latest_close": 2310.0, "ma20": 2298.5, "score": 3, "confidence": "high"}
                    },
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 4,
                        "selected_title": "波段偏多",
                        "selected_summary": "週線站上 MA20，MACD 偏多，量能一般。",
                        "selected_confidence": "high",
                        "scores": {"short": 1, "swing": 4, "long": 5},
                        "components": [],
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
            }
            llm_decision = {
                "decision": {
                    "headline": "2440 成本已觸及固定停損檢查線",
                    "direct_answer": "若你的原始停損線是 -5%，現在應執行或至少減碼；若採技術停損，先守 MA20。",
                    "confidence": "high",
                    "position_math": ["成本 2440，最新 2310，浮動約 -5.33%。"],
                    "evidence_used": ["OMI 最新日線收盤 2310。"],
                    "decision_conditions": ["固定 -5% 停損已觸發。", "技術停損看 MA20 是否失守。"],
                    "risk_notes": ["缺少部位大小與原始停損規則。"],
                    "missing_context": ["持股比例與可承受虧損未知。"],
                    "next_steps": ["先把停損規則寫成價格或百分比。"],
                },
                "response_id": "resp_test",
                "model": "test-model",
                "usage": {},
            }

            with (
                patch.object(ai_ask.reports, "build_stock_brief", return_value=stock_brief),
                patch.object(ai_ask.llm, "generate_decision_answer", return_value=llm_decision) as generate_decision,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_decision.assert_called_once()
            decision = response["analysis"]["position_decision"]
            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(decision["llm_status"], "completed")
            self.assertEqual(human_answer["source"], "position_decision_llm")
            self.assertIn("觸及固定停損", human_answer["headline"])
            self.assertIn("固定 -5% 停損已觸發", human_answer["text"])
        finally:
            db.close()

    def test_tw_index_target_uses_index_context_reader(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="你怎麼看現在走勢?",
                target={"type": "tw_index", "id": "TAIEX", "label": "TAIEX 加權指數"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            context = {
                "kind": "tw_index_context",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "weekly",
                        "selected_score": 2,
                        "selected_title": "偏多觀察",
                        "selected_summary": "指數站上短均，仍需量能確認。",
                        "selected_confidence": "medium",
                        "scores": {"short": 1, "swing": 2},
                        "components": [],
                    }
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_index_daily_stat"}],
            }

            with patch.object(ai_ask.tools, "read_tw_index_context", return_value=context) as reader:
                response = ai_ask.ask(db=db, payload=payload)

            reader.assert_called_once()
            self.assertEqual(response["target"]["type"], "tw_index")
            self.assertEqual(response["target"]["id"], "TAIEX")
            self.assertEqual(response["action"], "omi.read_tw_index_context")
            self.assertEqual(response["analysis"]["question_intent"], "trend_view")
            self.assertEqual(response["analysis"]["human_answer"]["source"], "question_intent")
            self.assertNotIn("stock_master", response["missing"])
        finally:
            db.close()

    def test_tw_index_data_only_projects_compact_public_result(self) -> None:
        db = make_session()
        try:
            compact = {
                "kind": "tw_index_compact_evidence",
                "version": "tw_index_compact_evidence.v1",
                "payload_level": "summary",
                "target": {"type": "tw_index", "id": "TAIEX", "label": "加權指數", "market": "TWSE"},
                "quote": {"source": "twse_index_5s", "price": 18111.0, "is_realtime": True},
                "intraday_bars": {
                    "enabled": True,
                    "payload_level": "summary",
                    "series": {
                        "1m": {
                            "interval": "1m",
                            "source": "twse_index_5s",
                            "point_count": 120,
                            "returned_point_count": 1,
                            "latest": {"time": "2026-06-04T13:30:00+08:00", "price": 18111.0},
                            "points": [{"time": "2026-06-04T13:30:00+08:00", "price": 18111.0}],
                        }
                    },
                    "warnings": [],
                },
                "technical": {"analysis": {"selected_score": 2}},
                "freshness_by_domain": {"quote": {"status": "live"}},
            }
            context = {
                "kind": "tw_index_context",
                "generated_at": "2026-06-04T05:30:00Z",
                "as_of": "2026-06-04T13:30:00+08:00",
                "scope": {"index_id": "TAIEX"},
                "data": {
                    "analysis": {
                        "requested_horizon": "intraday",
                        "selected_horizon": "intraday",
                        "selected_timeframe": "today",
                        "selected_score": 2,
                        "selected_title": "偏多觀察",
                        "selected_summary": "盤中站穩短線均價。",
                        "selected_confidence": "medium",
                    },
                    "compact": compact,
                    "intraday": {"points": [{"price": value} for value in range(120)]},
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "external_or_cache", "name": "market_index_intraday"}],
                "evidence_passport": {},
            }
            payload = AiAskRequest(
                question="加權指數盤中",
                target={"type": "tw_index", "id": "TAIEX"},
                mode="data_only",
            )

            with (
                patch.object(ai_ask, "_check_freshness", return_value={"is_current": True, "missing": [], "warnings": []}),
                patch.object(ai_ask.tools, "read_tw_index_context", return_value=context),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["result"]["data"]["compact"], compact)
            self.assertEqual(response["result"]["data"]["payload_level"], "summary")
            self.assertEqual(response["result"]["target"]["type"], "tw_index")
            self.assertEqual(response["result"]["quote"], compact["quote"])
            self.assertEqual(response["result"]["intraday"]["returned_point_count"], 1)
            self.assertNotIn("intraday", response["result"]["data"])
        finally:
            db.close()

    def test_tw_futures_target_uses_futures_context_reader(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="台指期現在走勢怎麼看?",
                target={"type": "tw_futures", "id": "TXF", "label": "TXF 台指期"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            context = {
                "kind": "tw_futures_context",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "daily",
                        "selected_score": -2,
                        "selected_title": "偏弱觀察",
                        "selected_summary": "日線跌破短均，先看反彈是否失敗。",
                        "selected_confidence": "medium",
                        "scores": {"short": -2, "swing": -2},
                        "components": [],
                    },
                    "compact": {
                        "kind": "tw_futures_compact_evidence",
                        "version": "market_compact_evidence.v1",
                        "target": {"type": "tw_futures", "id": "TXF", "label": "TXF 台指期", "market": "TW"},
                        "quote": {
                            "session": "after_hours",
                            "quote_time": "2026-07-18T04:59:58+08:00",
                            "last_price": 43_481,
                            "freshness": {
                                "status": "closed",
                                "is_live": False,
                                "market_status": {
                                    "is_open": False,
                                    "last_session": "after_hours",
                                },
                            },
                        },
                        "intraday_chart": {
                            "timeframe": "today",
                            "point_count": 390,
                            "to_date": "2026-07-18T05:00:00+08:00",
                            "points": [
                                {"time": "2026-07-18T04:59:00+08:00", "close": 43_481}
                            ],
                        },
                        "daily_close": {"trade_date": "2026-07-17", "close_price": 42_725},
                        "institutional_position": {
                            "trade_date": "2026-07-17",
                            "foreign_futures_net_oi": -86_189,
                            "foreign_futures_net_oi_change": -1_736,
                        },
                        "options_sentiment": {
                            "trade_date": "2026-07-17",
                            "put_call_volume_ratio_pct": 83.63,
                            "put_call_open_interest_ratio_pct": 92.94,
                        },
                        "slots": {},
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "taiwan_futures_daily_bar"}],
            }

            with patch.object(ai_ask.tools, "read_tw_futures_context", return_value=context) as reader:
                response = ai_ask.ask(db=db, payload=payload)

            reader.assert_called_once()
            self.assertEqual(response["target"]["type"], "tw_futures")
            self.assertEqual(response["target"]["id"], "TXF")
            self.assertEqual(response["action"], "omi.read_tw_futures_context")
            self.assertEqual(response["analysis"]["question_intent"], "trend_view")
            self.assertEqual(response["analysis"]["human_answer"]["source"], "tw_futures_contract")
            human_text = response["analysis"]["human_answer"]["text"]
            self.assertIn("夜盤最後成交：43,481", human_text)
            self.assertIn("日 K 收盤：42,725", human_text)
            self.assertIn("外資期貨淨未平倉 -86,189", human_text)
            self.assertIn("PCR 成交量 83.63%", human_text)
            self.assertIn("不代表目前夜盤的即時加空或回補", "\n".join(response["analysis"]["human_answer"]["data_limits"]))
            self.assertNotIn("stock_master", response["missing"])
            self.assertEqual(response["result"]["live_summary"]["quote_price"], 43_481)
            self.assertFalse(response["result"]["live_summary"]["is_live"])
            self.assertTrue(response["result"]["live_summary"]["intraday_available"])
            self.assertEqual(response["result"]["live_summary"]["intraday_point_count"], 390)
        finally:
            db.close()

    def test_ask_resolves_tsmc_alias_to_tw_stock_with_adr_candidate(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="TSMC risk",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "tw_stock")
            self.assertEqual(response["target"]["id"], "2330")
            self.assertEqual(response["resolution"]["target"]["id"], "2330")
            self.assertEqual(response["resolution"]["confidence"], "high")
            self.assertTrue(
                any(
                    candidate["target"]["type"] == "us_stock" and candidate["target"]["id"] == "TSM"
                    for candidate in response["resolution"]["candidates"]
                )
            )
            self.assertTrue(
                any(action["type"] == "connect_us_stock_context" for action in response["next_actions"])
            )
        finally:
            db.close()

    def test_ask_resolves_adr_followup_to_us_stock_from_last_resolution(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            add_us_stock(db)
            payload = AiAskRequest(
                question="那 ADR 呢？",
                mode="auto",
                allow_llm=False,
                allow_write=False,
                conversation_context={
                    "last_resolution": {
                        "target": {"type": "tw_stock", "id": "2330", "label": "台積電"},
                        "candidates": [
                            {"target": {"type": "tw_stock", "id": "2330", "label": "台積電"}},
                            {"target": {"type": "us_stock", "id": "TSM", "label": "TSM ADR"}},
                        ],
                    }
                },
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["target"]["id"], "TSM")
            self.assertEqual(response["action"], "omi.generate_us_stock_brief")
            self.assertEqual(response["resolution"]["source"], "conversation_resolution")
            self.assertFalse(
                any(action["type"] == "connect_us_stock_context" for action in response["next_actions"])
            )
        finally:
            db.close()

    def test_ask_resolves_known_us_symbol_from_question_text(self) -> None:
        db = make_session()
        try:
            add_us_stock(db, symbol="MU")
            payload = AiAskRequest(
                question="MU 怎麼看？",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["target"]["id"], "MU")
            self.assertEqual(response["action"], "omi.generate_us_stock_brief")
            self.assertEqual(response["resolution"]["source"], "question_us_symbol")
            self.assertFalse(response["clarification"]["required"])
        finally:
            db.close()

    def test_ask_resolves_known_us_symbol_from_auto_target_id(self) -> None:
        db = make_session()
        try:
            add_us_stock(db, symbol="SPCX")
            payload = AiAskRequest(
                question="幫我分析這檔",
                target={"type": "auto", "id": "SPCX"},
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["target"]["id"], "SPCX")
            self.assertEqual(response["action"], "omi.generate_us_stock_brief")
            self.assertEqual(response["resolution"]["source"], "explicit_scope_id")
        finally:
            db.close()

    def test_ask_uses_jp_stock_context_reader_for_explicit_target(self) -> None:
        db = make_session()
        try:
            add_jp_stock(db)
            payload = AiAskRequest(
                question="Toyota Japan context",
                target={"type": "jp_stock", "id": "7203", "label": "Toyota"},
                mode="data_only",
                allow_llm=False,
                allow_write=False,
            )
            context = {
                "kind": "jp_stock_context",
                "as_of": "2026-06-18",
                "summary": {"latest_close": 3080.0},
                "data": {"stock": {"symbol": "7203.T"}},
                "missing": ["jp_company_fundamental"],
                "warnings": ["local-cache only"],
                "source_refs": [{"type": "table", "name": "jp_daily_price"}],
            }

            with patch.object(ai_ask.agentic_tools, "read_jp_stock_context", return_value=context) as reader:
                response = ai_ask.ask(db=db, payload=payload)

            reader.assert_called_once()
            self.assertEqual(reader.call_args.kwargs["symbol"], "7203.T")
            self.assertFalse(reader.call_args.kwargs["is_index"])
            self.assertEqual(response["target"]["type"], "jp_stock")
            self.assertEqual(response["target"]["id"], "7203.T")
            self.assertEqual(response["action"], "omi.read_jp_stock_context")
            self.assertEqual(response["result"]["kind"], "jp_stock_context")
        finally:
            db.close()

    def test_ask_gates_jp_intraday_provider_read_by_external_fetch_policy(self) -> None:
        db = make_session()
        try:
            add_jp_stock(db)
            context = {
                "kind": "jp_stock_context",
                "as_of": "2026-07-15T10:00:00+09:00",
                "summary": {"latest_close": 3080.0},
                "data": {"compact": {}},
                "missing": [],
                "warnings": [],
                "source_refs": [],
            }

            for allow_external_fetch, expected_include_intraday in (
                (False, False),
                (True, True),
            ):
                payload = AiAskRequest(
                    question="Toyota Japan intraday context",
                    target={"type": "jp_stock", "id": "7203", "label": "Toyota"},
                    mode="data_only",
                    analysis_horizon="intraday",
                    allow_external_fetch=allow_external_fetch,
                    allow_llm=False,
                    allow_write=False,
                )
                with patch.object(
                    ai_ask.agentic_tools,
                    "read_jp_stock_context",
                    return_value=context,
                ) as reader:
                    ai_ask.ask(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(
                            can_external_fetch=allow_external_fetch,
                            trust_source="test",
                        ),
                    )

                self.assertEqual(
                    reader.call_args.kwargs["market_data_params"]["include_intraday"],
                    expected_include_intraday,
                )
        finally:
            db.close()

    def test_ask_uses_jp_index_context_reader_for_explicit_target(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="Nikkei context",
                target={"type": "jp_index", "id": "^N225", "label": "Nikkei 225"},
                mode="data_only",
                allow_llm=False,
                allow_write=False,
            )
            context = {
                "kind": "jp_index_context",
                "as_of": "2026-06-18",
                "summary": {"latest_close": 38500.0},
                "data": {"chart": {"point_count": 2}},
                "missing": [],
                "warnings": ["OHLC-only"],
                "source_refs": [{"type": "table", "name": "jp_daily_price"}],
            }

            with patch.object(ai_ask.agentic_tools, "read_jp_stock_context", return_value=context) as reader:
                response = ai_ask.ask(db=db, payload=payload)

            reader.assert_called_once()
            self.assertEqual(reader.call_args.kwargs["symbol"], "^N225")
            self.assertTrue(reader.call_args.kwargs["is_index"])
            self.assertEqual(response["target"]["type"], "jp_index")
            self.assertEqual(response["target"]["id"], "^N225")
            self.assertEqual(response["action"], "omi.read_jp_index_context")
            self.assertEqual(response["result"]["kind"], "jp_index_context")
        finally:
            db.close()

    def test_ask_uses_jp_stock_brief_for_explicit_brief_target(self) -> None:
        db = make_session()
        try:
            add_jp_stock(db)
            payload = AiAskRequest(
                question="Toyota Japan brief",
                target={"type": "jp_stock", "id": "7203", "label": "Toyota"},
                mode="brief",
                allow_llm=False,
                allow_write=False,
                market_data_params={"timeframe": "weekly", "bars": 26},
            )
            context = {
                "kind": "jp_stock_brief",
                "as_of": "2026-06-18",
                "scope": {"target": {"type": "jp_stock", "id": "7203.T", "market": "JP"}},
                "summary": {"kind": "cross_market_brief_summary", "human_answer": {"lines": ["Toyota"]}},
                "data": {"compact": {"target": {"type": "jp_stock", "id": "7203.T", "market": "JP"}}},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "jp_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_jp_stock_brief", return_value=context) as builder:
                response = ai_ask.ask(db=db, payload=payload)

            builder.assert_called_once()
            self.assertEqual(builder.call_args.kwargs["symbol"], "7203.T")
            self.assertFalse(builder.call_args.kwargs["is_index"])
            self.assertEqual(builder.call_args.kwargs["market_data_params"]["timeframe"], "weekly")
            self.assertEqual(response["action"], "omi.generate_jp_stock_brief")
            self.assertEqual(response["mode"]["effective"], "brief")
        finally:
            db.close()

    def test_ask_uses_kr_stock_brief_for_explicit_brief_target(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="Samsung Korea brief",
                target={"type": "kr_stock", "id": "005930", "label": "Samsung Electronics"},
                mode="brief",
                allow_llm=False,
                allow_write=False,
                market_data_params={"timeframe": "daily", "bars": 60},
            )
            context = {
                "kind": "kr_stock_brief",
                "as_of": "2026-06-18",
                "scope": {"target": {"type": "kr_stock", "id": "005930", "market": "KR"}},
                "summary": {"kind": "cross_market_brief_summary", "human_answer": {"lines": ["Samsung"]}},
                "data": {"compact": {"target": {"type": "kr_stock", "id": "005930", "market": "KR"}}},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "kr_daily_price"}],
            }

            with patch.object(ai_ask.reports, "build_kr_stock_brief", return_value=context) as builder:
                response = ai_ask.ask(db=db, payload=payload)

            builder.assert_called_once()
            self.assertEqual(builder.call_args.kwargs["symbol"], "005930.KS")
            self.assertFalse(builder.call_args.kwargs["is_index"])
            self.assertEqual(builder.call_args.kwargs["market_data_params"]["bars"], 60)
            self.assertEqual(response["target"]["type"], "kr_stock")
            self.assertEqual(response["action"], "omi.generate_kr_stock_brief")
        finally:
            db.close()

    def test_ask_uses_crypto_asset_brief_for_explicit_brief_target(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="BTC crypto brief",
                target={"type": "crypto_asset", "id": "BTC", "label": "Bitcoin"},
                mode="brief",
                allow_llm=False,
                allow_write=False,
                market_data_params={"symbol": "BTCUSDT", "instrument_type": "perpetual", "interval": "1m", "limit": 80},
            )
            context = {
                "kind": "crypto_asset_brief",
                "as_of": "2026-06-18T12:00:00+00:00",
                "scope": {"target": {"type": "crypto_asset", "id": "BTC", "market": "crypto"}},
                "summary": {"kind": "cross_market_brief_summary", "human_answer": {"lines": ["BTC"]}},
                "data": {"compact": {"target": {"type": "crypto_asset", "id": "BTC", "market": "crypto"}}},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "crypto_ticker_snapshot"}],
            }

            with patch.object(ai_ask.reports, "build_crypto_brief", return_value=context) as builder:
                response = ai_ask.ask(db=db, payload=payload)

            builder.assert_called_once()
            self.assertEqual(builder.call_args.kwargs["asset"], "BTC")
            self.assertEqual(builder.call_args.kwargs["market_data_params"]["instrument_type"], "perpetual")
            self.assertEqual(response["target"]["type"], "crypto_asset")
            self.assertEqual(response["action"], "omi.generate_crypto_asset_brief")
        finally:
            db.close()

    def test_ask_does_not_treat_ambiguous_ai_word_as_us_stock_without_us_context(self) -> None:
        db = make_session()
        try:
            add_us_stock(db, symbol="AI")
            payload = AiAskRequest(
                question="AI 技術趨勢怎麼看？",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertNotEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["action"], "omi.ask.clarify")
            self.assertTrue(response["clarification"]["required"])
        finally:
            db.close()

    def test_ask_resolves_ambiguous_symbol_when_us_context_is_explicit(self) -> None:
        db = make_session()
        try:
            add_us_stock(db, symbol="AI")
            payload = AiAskRequest(
                question="AI 這檔美股怎麼看？",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["target"]["id"], "AI")
            self.assertEqual(response["action"], "omi.generate_us_stock_brief")
        finally:
            db.close()

    def test_us_stock_analysis_uses_us_llm_analysis_path_when_trusted(self) -> None:
        db = make_session()
        try:
            add_us_stock(db)
            payload = AiAskRequest(
                question="TSM ADR 怎麼看？",
                target={"type": "us_stock", "id": "TSM"},
                mode="analysis",
                allow_llm=True,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                can_external_fetch=False,
                trust_source="token",
            )
            tool_session = {
                "tool_plan": {"provider": "fallback", "tool_plan": []},
                "tool_runs": [],
                "warnings": [],
                "freshness": {
                    "kind": "us_stock_freshness",
                    "is_current": True,
                    "missing": [],
                    "warnings": [],
                },
            }
            analysis_result = {
                "kind": "us_stock_llm_analysis",
                "strategy_profile": "short_term_momentum",
                "as_of": "2026-06-12",
                "data": {
                    "analysis": {
                        "requested_horizon": "swing",
                        "selected_horizon": "swing",
                        "selected_timeframe": "us_daily",
                        "selected_score": 18,
                        "selected_title": "美股短線偏強",
                        "selected_summary": "TSM ADR evidence ready",
                        "selected_confidence": "medium",
                    }
                },
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "us_daily_price"}],
            }

            with (
                patch.object(ai_ask.agentic_tools, "run_us_stock_tool_session", return_value=tool_session),
                patch.object(
                    ai_ask.orchestrator,
                    "generate_us_stock_llm_analysis",
                    return_value=analysis_result,
                ) as generate_analysis,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_analysis.assert_called_once()
            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["action"], "omi.generate_us_stock_llm_analysis")
            self.assertEqual(response["mode"]["effective"], "analysis")
            self.assertEqual(response["analysis"]["selected_timeframe"], "us_daily")
        finally:
            db.close()

    def test_us_stock_report_uses_us_llm_report_path_when_trusted_and_current(self) -> None:
        db = make_session()
        try:
            add_us_stock(db)
            payload = AiAskRequest(
                question="TSM ADR 產生正式報告",
                target={"type": "us_stock", "id": "TSM"},
                mode="report",
                allow_llm=True,
                allow_write=True,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=True,
                can_external_fetch=False,
                trust_source="token",
            )
            tool_session = {
                "tool_plan": {"provider": "fallback", "tool_plan": []},
                "tool_runs": [],
                "warnings": [],
                "freshness": {
                    "kind": "us_stock_freshness",
                    "is_current": True,
                    "missing": [],
                    "warnings": [],
                },
            }
            report_result = {
                "kind": "stored_ai_report",
                "report_type": "us_stock_llm_brief",
                "scope_type": "us_stock",
                "scope_id": "TSM",
                "strategy_profile": "short_term_momentum",
                "as_of": "2026-06-12",
                "summary": {},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "us_daily_price"}],
            }

            with (
                patch.object(ai_ask.agentic_tools, "run_us_stock_tool_session", return_value=tool_session),
                patch.object(
                    ai_ask.orchestrator,
                    "generate_us_stock_llm_report",
                    return_value=report_result,
                ) as generate_report,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_report.assert_called_once()
            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["action"], "omi.generate_us_stock_llm_report")
            self.assertEqual(response["mode"]["effective"], "report")
            self.assertEqual(response["report_level"], "full_report")
        finally:
            db.close()

    def test_us_stock_llm_tool_plan_executes_allowed_tools(self) -> None:
        db = make_session()
        try:
            add_us_stock(db)
            payload = AiAskRequest(
                question="TSM ADR 最新走勢和資料缺口",
                target={"type": "us_stock", "id": "TSM"},
                mode="brief",
                allow_llm=True,
                allow_external_fetch=True,
                tool_budget={"max_calls": 2, "max_external_fetches": 2, "max_total_seconds": 25},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                can_external_fetch=True,
                trust_source="token",
            )
            planner_result = {
                "provider": "openai",
                "reason": "ADR question needs US intraday and daily evidence.",
                "tool_plan": [
                    {"tool": "us.read_intraday_trend", "args": {"symbol": "TSM"}, "reason": "latest ADR trading"},
                    {
                        "tool": "us.refresh_daily_price",
                        "args": {"symbol": "TSM", "provider": "auto", "outputsize": "compact", "adjusted": False},
                        "reason": "daily cache gap",
                    },
                ],
            }

            with (
                patch.object(ai_ask.agentic_tools.llm, "generate_tool_plan", return_value=planner_result) as planner,
                patch.object(
                    ai_ask.agentic_tools.us_market_service,
                    "get_us_intraday_trend",
                    return_value={
                        "symbol": "TSM",
                        "source": "yahoo_chart",
                        "previous_close": 180.0,
                        "point_count": 3,
                        "points": [],
                    },
                ) as intraday,
                patch.object(
                    ai_ask.agentic_tools.us_market_service,
                    "refresh_us_daily_prices",
                    return_value={
                        "status": "success",
                        "provider": "yahoo_chart",
                        "symbol": "TSM",
                        "fetched_count": 5,
                        "inserted_count": 5,
                        "updated_count": 0,
                    },
                ) as refresh_daily,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            planner.assert_called_once()
            intraday.assert_called_once_with(symbol="TSM", db=db)
            refresh_daily.assert_called_once()
            self.assertEqual(response["target"]["type"], "us_stock")
            self.assertEqual(response["tool_plan"]["provider"], "openai")
            self.assertEqual([run["status"] for run in response["tool_runs"]], ["success", "success"])
            self.assertEqual(response["tool_runs"][0]["tool"], "us.read_intraday_trend")
            self.assertEqual(response["result"]["summary"]["intraday"]["point_count"], 3)
        finally:
            db.close()

    def test_us_stock_external_tool_is_blocked_without_fetch_trust(self) -> None:
        db = make_session()
        try:
            add_us_stock(db)
            payload = AiAskRequest(
                question="TSM ADR 最新走勢",
                target={"type": "us_stock", "id": "TSM"},
                mode="brief",
                allow_llm=True,
                allow_external_fetch=True,
                tool_budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 25},
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                can_external_fetch=False,
                trust_source="token_without_fetch",
            )
            planner_result = {
                "provider": "openai",
                "reason": "latest ADR context",
                "tool_plan": [
                    {"tool": "us.read_intraday_trend", "args": {"symbol": "TSM"}, "reason": "latest ADR trading"},
                ],
            }

            with (
                patch.object(ai_ask.agentic_tools.llm, "generate_tool_plan", return_value=planner_result),
                patch.object(ai_ask.agentic_tools.us_market_service, "get_us_intraday_trend") as intraday,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            intraday.assert_not_called()
            self.assertEqual(response["tool_runs"][0]["status"], "blocked")
            self.assertIn("External fetch is not allowed", response["tool_runs"][0]["error"])
            self.assertFalse(response["policy"]["can_external_fetch"])
        finally:
            db.close()

    def test_ask_resolves_watchlist_group_id_from_question_text(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="watchlist group 1 ranking",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            with (
                patch.object(ai_ask.freshness, "check_watchlist_data_freshness", return_value={}),
                patch.object(
                    ai_ask.reports,
                    "build_watchlist_brief",
                    return_value={
                        "kind": "watchlist_brief",
                        "warnings": [],
                        "strategy_profile": "short_term_momentum",
                        "data": {
                            "overview": {
                            "kind": "watchlist_sector_overview",
                            "group_id": 1,
                            "group_name": "科技股",
                            "stance": "結構偏多",
                            "confidence": "high",
                            "display": "科技股 結構偏多；上漲 2、下跌 1。",
                            "answer_outline": ["結論：科技股 結構偏多。"],
                            "human_answer": {
                                "kind": "watchlist_sector_human_answer",
                                "lines": [
                                    "結論：科技股 結構偏多；上漲 2、下跌 1。",
                                    "追蹤：2330 台積電",
                                ],
                                "text": "結論：科技股 結構偏多；上漲 2、下跌 1。\n追蹤：2330 台積電",
                            },
                            "breadth": {"up_count": 2, "down_count": 1},
                        }
                    },
                    },
                ) as build_watchlist_brief,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            build_watchlist_brief.assert_called_once()
            self.assertEqual(build_watchlist_brief.call_args.kwargs["group_id"], 1)
            self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_mode"], "action")
            self.assertEqual(response["target"]["type"], "tw_watchlist")
            self.assertEqual(response["target"]["id"], "1")
            self.assertEqual(response["action"], "omi.generate_watchlist_brief")
            self.assertEqual(response["analysis"]["kind"], "watchlist_sector_digest")
            self.assertEqual(response["analysis"]["stance"], "結構偏多")
            self.assertEqual(response["analysis"]["source"], "result.data.overview")
            self.assertEqual(response["analysis"]["answer_outline"][1], "追蹤：2330 台積電")
            self.assertIn("human_answer", response["analysis"])
            self.assertFalse(response["clarification"]["required"])
        finally:
            db.close()

    def test_ask_watchlist_risk_question_uses_radar_rows(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="watchlist group 1 哪些有風險",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            report_result = {
                "kind": "watchlist_brief",
                "warnings": [],
                "missing": [],
                "strategy_profile": "short_term_momentum",
                "data": {
                    "overview": {
                        "kind": "watchlist_sector_overview",
                        "group_id": 1,
                        "group_name": "科技股",
                        "stance": "結構偏多",
                        "confidence": "high",
                        "display": "科技股 結構偏多；上漲 2、下跌 1。",
                        "answer_outline": [
                            "結論：科技股 結構偏多；上漲 2、下跌 1。",
                            "雷達：2 檔命中。",
                        ],
                        "human_answer": {
                            "kind": "watchlist_sector_human_answer",
                            "lines": [
                                "結論：科技股 結構偏多；上漲 2、下跌 1。",
                                "雷達：2 檔命中。",
                            ],
                            "text": "結論：科技股 結構偏多；上漲 2、下跌 1。\n雷達：2 檔命中。",
                        },
                        "breadth": {"up_count": 2, "down_count": 1},
                        "radar": {
                            "mode": "action",
                            "matched_count": 2,
                            "radar_count": 2,
                            "is_current": True,
                            "buckets": [
                                {"key": "breakout", "label": "突破動能", "count": 1},
                                {"key": "risk", "label": "風險優先", "count": 1},
                            ],
                        },
                        "radar_rows": [
                            {
                                "stock_id": "2330",
                                "label": "2330 台積電",
                                "bucket": "breakout",
                                "bucket_label": "突破動能",
                                "urgency": "high",
                                "action_label": "追蹤突破延續",
                                "change_pct_text": "+1.50%",
                                "primary_signal_label": "突破 20 日高",
                            },
                            {
                                "stock_id": "2454",
                                "label": "2454 聯發科",
                                "bucket": "risk",
                                "bucket_label": "風險優先",
                                "urgency": "medium",
                                "action_label": "優先檢查風控",
                                "change_pct_text": "-2.93%",
                                "primary_signal_label": "動能轉弱",
                            },
                        ],
                    }
                },
            }

            with (
                patch.object(ai_ask.freshness, "check_watchlist_data_freshness", return_value={}),
                patch.object(ai_ask.reports, "build_watchlist_brief", return_value=report_result) as build_watchlist_brief,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            build_watchlist_brief.assert_called_once()
            self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_mode"], "risk")
            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(response["analysis"]["question_intent"], "risk_check")
            self.assertEqual(human_answer["source"], "watchlist_radar")
            self.assertEqual(human_answer["radar_rows"][0]["stock_id"], "2454")
            self.assertIn("2454 聯發科", human_answer["text"])
            self.assertNotIn("目前標的", human_answer["text"])
        finally:
            db.close()

    def test_ask_watchlist_entry_question_uses_momentum_radar_mode(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="watchlist group 1 可以買嗎",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )
            report_result = {
                "kind": "watchlist_brief",
                "warnings": [],
                "missing": [],
                "strategy_profile": "short_term_momentum",
                "data": {
                    "overview": {
                        "kind": "watchlist_sector_overview",
                        "group_id": 1,
                        "group_name": "科技股",
                        "stance": "結構偏多",
                        "confidence": "high",
                        "display": "科技股 結構偏多；上漲 2、下跌 1。",
                        "human_answer": {
                            "kind": "watchlist_sector_human_answer",
                            "lines": ["結論：科技股 結構偏多。"],
                            "text": "結論：科技股 結構偏多。",
                        },
                        "breadth": {"up_count": 2, "down_count": 1},
                        "radar": {
                            "mode": "momentum",
                            "matched_count": 1,
                            "radar_count": 1,
                            "is_current": True,
                            "buckets": [{"key": "breakout", "label": "突破動能", "count": 1}],
                        },
                        "radar_rows": [
                            {
                                "stock_id": "2330",
                                "label": "2330 台積電",
                                "bucket": "breakout",
                                "bucket_label": "突破動能",
                                "urgency": "high",
                                "action_label": "追蹤突破延續",
                                "change_pct_text": "+1.50%",
                                "primary_signal_label": "突破 20 日高",
                            },
                        ],
                    }
                },
            }

            with (
                patch.object(ai_ask.freshness, "check_watchlist_data_freshness", return_value={}),
                patch.object(ai_ask.reports, "build_watchlist_brief", return_value=report_result) as build_watchlist_brief,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            build_watchlist_brief.assert_called_once()
            self.assertEqual(build_watchlist_brief.call_args.kwargs["radar_mode"], "momentum")
            self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
            self.assertEqual(response["analysis"]["human_answer"]["source"], "watchlist_radar")
            self.assertIn("2330 台積電", response["analysis"]["human_answer"]["text"])
        finally:
            db.close()

    def test_ask_resolves_stock_specific_freshness_from_question_text(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="freshness coverage for 2330",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "data_freshness")
            self.assertEqual(response["target"]["id"], "2330")
            self.assertEqual(response["action"], "omi.read_data_freshness")
            self.assertEqual(response["result"]["scope"]["stock_id"], "2330")
            self.assertFalse(response["clarification"]["required"])
        finally:
            db.close()

    def test_ask_returns_clarification_for_watchlist_without_group_id(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="watchlist ranking",
                mode="auto",
                allow_llm=False,
                allow_write=False,
            )

            response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["target"]["type"], "tw_watchlist")
            self.assertIsNone(response["target"]["id"])
            self.assertEqual(response["mode"]["effective"], "clarification")
            self.assertEqual(response["action"], "omi.ask.clarify")
            self.assertTrue(response["clarification"]["required"])
            self.assertFalse(response["answer_ready"])
            self.assertEqual(response["evidence_passport"]["trust_level"], "blocked")
            self.assertIn("target_scope", response["evidence_passport"]["missing"])
            self.assertTrue(any(action["type"] == "ask_clarification" for action in response["next_actions"]))
        finally:
            db.close()

    def test_auto_target_symbol_precedes_generic_freshness_wording(self) -> None:
        payload = AiAskRequest(
            question="SOX 最新資料 freshness",
            target={"type": "auto", "id": "SOX"},
            mode="data_only",
        )

        resolution = ai_ask._resolve_scope(db=None, payload=payload)

        self.assertEqual(resolution.selected_scope_type, "us_stock")
        self.assertEqual(resolution.selected_scope_id, "^SOX")

    def test_auto_target_resolves_known_us_index_alias_from_question_without_context_hint(self) -> None:
        payload = AiAskRequest(
            question="SOX 半導體指數最新行情與資料時間",
            target={"type": "auto"},
            mode="data_only",
        )

        resolution = ai_ask._resolve_scope(db=None, payload=payload)

        self.assertEqual(resolution.selected_scope_type, "us_stock")
        self.assertEqual(resolution.selected_scope_id, "^SOX")
        self.assertEqual(resolution.confidence, "high")
        self.assertIsNone(resolution.assumption)

    def test_sox_latest_only_requires_index_price_capabilities(self) -> None:
        db = make_session()
        try:
            gaps = agentic_tools.scan_us_stock_gaps(
                db,
                "SOX",
                question="SOX 最新行情是否還在即時交易？",
            )

            self.assertEqual(gaps["scope"]["target"]["id"], "^SOX")
            self.assertEqual(gaps["instrument_type"], "index")
            self.assertEqual(
                gaps["required_capabilities"],
                ["us_daily_price", "us_intraday_trend"],
            )
            self.assertNotIn("us_company_profile", gaps["missing"])
            self.assertNotIn("us_sec_company_fact", gaps["missing"])
            self.assertIn("us_company_profile", gaps["not_applicable"])
        finally:
            db.close()

    def test_successful_intraday_tool_satisfies_rescan_capability(self) -> None:
        db = make_session()
        try:
            gaps = agentic_tools.scan_us_stock_gaps(
                db,
                "SOX",
                question="SOX 最新行情",
                satisfied_capabilities={"us_intraday_trend"},
            )

            self.assertNotIn("us_intraday_trend", gaps["missing"])
            self.assertIn("us_daily_price", gaps["missing"])
        finally:
            db.close()

    def test_us_index_context_skips_company_resources_and_projects_source_health(self) -> None:
        db = make_session()
        try:
            with (
                patch.object(agentic_tools.us_market_service, "list_us_daily_prices", return_value=[]),
                patch.object(agentic_tools, "_latest_profile", return_value=None) as latest_profile,
                patch.object(
                    agentic_tools.us_market_service,
                    "get_us_sec_fundamental_summary",
                    return_value=None,
                ) as get_sec,
                patch.object(
                    agentic_tools.us_market_service,
                    "list_us_corporate_actions",
                    return_value=[],
                ) as list_actions,
                patch.object(
                    agentic_tools.us_market_service,
                    "list_us_short_volumes",
                    return_value=[],
                ) as list_short,
                patch.object(
                    agentic_tools,
                    "scan_us_stock_gaps",
                    return_value={"missing": ["us_daily_price"], "warnings": []},
                ),
                patch.object(
                    agentic_tools.us_market_service,
                    "build_us_source_health",
                    return_value={
                        "summary": {"entry_count": 4, "stale_count": 2},
                        "entries": [
                            {"resource": "symbol_master", "status": "current", "ok": True},
                            {"resource": "daily_price", "status": "stale", "ok": False},
                            {"resource": "profile", "status": "stale", "ok": False},
                            {"resource": "sec_facts", "status": "stale", "ok": False},
                        ],
                    },
                ),
                patch.object(
                    agentic_tools.us_market_service,
                    "list_us_ohlc_chart_data",
                    return_value={"point_count": 1, "points": []},
                ),
            ):
                context = agentic_tools.read_us_stock_context(db=db, symbol="SOX")

            latest_profile.assert_not_called()
            get_sec.assert_not_called()
            list_actions.assert_not_called()
            list_short.assert_not_called()
            self.assertEqual(context["scope"]["target"]["instrument_type"], "index")
            self.assertEqual(context["summary"]["latest_volume_status"], "provider_unavailable")
            self.assertEqual(
                {entry["resource"] for entry in context["data"]["source_health"]["entries"]},
                {"symbol_master", "daily_price"},
            )
            self.assertIn(
                "profile",
                context["data"]["source_health"]["not_applicable_resources"],
            )
            self.assertEqual(context["data"]["compact"]["slots"]["fundamentals"]["status"], "not_applicable")
            self.assertEqual(context["data"]["compact"]["slots"]["flows_liquidity"]["status"], "not_applicable")
        finally:
            db.close()

    def test_explicit_us_target_normalizes_known_index_alias(self) -> None:
        payload = AiAskRequest(
            question="SOX latest",
            target={"type": "us_stock", "id": "SOX"},
            mode="data_only",
        )

        resolution = ai_ask._resolve_scope(db=None, payload=payload)

        self.assertEqual(resolution.selected_scope_type, "us_stock")
        self.assertEqual(resolution.selected_scope_id, "^SOX")

    def test_unknown_contract_version_is_rejected(self) -> None:
        payload = AiAskRequest(
            question="market",
            contract_version="made.up.v99",
            target={"type": "market"},
        )

        with self.assertRaisesRegex(ValueError, "contract_version must be one of"):
            ai_ask._validate_request(payload)

    def test_context_only_brief_returns_human_status_summary(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="黃金資料狀態",
                target={"type": "resource_asset", "id": "GC", "label": "黃金"},
                mode="brief",
            )
            context = {
                "kind": "resource_asset_context",
                "as_of": "2026-07-17",
                "scope": {"target": {"type": "resource_asset", "id": "GC"}},
                "data": {
                    "compact": {
                        "kind": "resource_asset_compact_evidence",
                        "version": "market_compact_evidence.v1",
                        "target": {"type": "resource_asset", "id": "GC", "label": "黃金"},
                        "resources": {"ohlcv_rows": 20, "watch_only": True},
                        "freshness_by_domain": {"quote": "stale", "chart": "missing"},
                        "slots": {
                            "quote": {"status": "stale", "capability": "quote_snapshot"},
                            "daily_chart": {"status": "missing", "capability": "daily_chart"},
                            "trade_execution": {"status": "not_applicable", "capability": "trade_execution"},
                        },
                    }
                },
                "missing": ["resource_ohlcv"],
                "warnings": ["Resource quote is stale."],
                "source_refs": [],
            }

            with patch.object(
                ai_ask.agentic_tools,
                "read_resource_asset_context",
                return_value=context,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            self.assertEqual(response["mode"]["effective"], "brief")
            self.assertEqual(response["analysis"]["kind"], "compact_context_status_digest")
            self.assertEqual(response["analysis"]["human_answer"]["source"], "compact_context_contract")
            self.assertIn("quote=stale", response["analysis"]["human_answer"]["text"])
            self.assertIn("daily_chart=missing", response["analysis"]["human_answer"]["text"])
            self.assertEqual(response["result"]["human_answer"]["source"], "compact_context_contract")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
