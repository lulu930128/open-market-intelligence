from __future__ import annotations

from datetime import date
from itertools import count
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import freshness
from app.ai import reports as ai_reports
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
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
            ):
                result = freshness.check_stock_data_freshness(db=db, stock_id="2330")

            self.assertTrue(result["is_current"])
            self.assertEqual(result["stale_stock_count"], 0)
            self.assertFalse(result["missing"])
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
                },
                "missing": [],
                "warnings": [],
                "source_refs": [],
            }

            with patch.object(ai_reports.tools, "read_watchlist_context", return_value=context):
                result = ai_reports.build_watchlist_brief(db=db, group_id=1, rank_by="score", sort_order="desc")

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
                ["結論", "追蹤", "等回測", "保守", "資料"],
            )
            self.assertIn("追蹤：", overview["human_answer"]["text"])
            self.assertIn("等回測：2303 聯電", overview["human_answer"]["text"])
            self.assertIn("2330 台積電", overview["strong_rows"][0]["label"])
            self.assertIn("2330 台積電", overview["follow_rows"][0]["label"])
            self.assertIn("2454 聯發科", overview["defensive_rows"][0]["label"])
            self.assertIn("display", result["summary"]["top_rows"][0])
        finally:
            db.close()

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
            intraday.assert_called_once_with(symbol="TSM")
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


if __name__ == "__main__":
    unittest.main()
