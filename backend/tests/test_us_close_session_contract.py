from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import ANY, patch
from zoneinfo import ZoneInfo

from app.ai import agentic_execution, agentic_planning, answer_composer
from app.ai.ask_execution import _us_market_data_params
from app.ai.market_context.us_context import _us_intraday_quote
from app.ai.market_date_request import (
    parse_market_trade_date,
    requested_us_trade_date,
)
from app.ai.schemas import AiAskRequest


class USMarketDateRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(
            2026,
            7,
            26,
            10,
            0,
            tzinfo=ZoneInfo("America/New_York"),
        )

    def test_explicit_trade_date_is_strict_iso(self) -> None:
        self.assertEqual(
            parse_market_trade_date("2026-07-20").isoformat(),
            "2026-07-20",
        )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            parse_market_trade_date("2026/07/20")
        with self.assertRaisesRegex(ValueError, "valid ISO date"):
            parse_market_trade_date("2026-02-30")

    def test_close_question_resolves_day_only_in_us_market_calendar(self) -> None:
        result = requested_us_trade_date(
            "查 20 號的收盤價",
            now=self.now,
        )

        self.assertEqual(result.isoformat(), "2026-07-20")

    def test_close_question_resolves_month_day_to_latest_occurrence(self) -> None:
        result = requested_us_trade_date(
            "AAPL 12/31 closing price",
            now=self.now,
        )

        self.assertEqual(result.isoformat(), "2025-12-31")

    def test_day_only_skips_months_without_that_calendar_day(self) -> None:
        result = requested_us_trade_date(
            "查 31 號的收盤價",
            now=datetime(
                2026,
                5,
                1,
                10,
                0,
                tzinfo=ZoneInfo("America/New_York"),
            ),
        )

        self.assertEqual(result.isoformat(), "2026-03-31")

    def test_non_close_question_does_not_infer_trade_date(self) -> None:
        self.assertIsNone(
            requested_us_trade_date(
                "AAPL 20 日均線怎麼看",
                now=self.now,
            )
        )

    def test_public_us_params_bind_close_date_and_disable_current_intraday(self) -> None:
        payload = AiAskRequest(
            question="AAPL closing price on 2026-07-20",
            target={"type": "us_stock", "id": "AAPL"},
            analysis_horizon="intraday",
            allow_external_fetch=True,
            market_data_params={
                "include_intraday": True,
                "session_scope": "all",
            },
        )

        params = _us_market_data_params(
            payload,
            policy={"can_external_fetch": True},
        )

        self.assertEqual(params["trade_date"], "2026-07-20")
        self.assertFalse(params["include_intraday"])
        self.assertEqual(params["session_scope"], "all")


class USQuoteSessionContractTests(unittest.TestCase):
    def test_after_hours_quote_keeps_regular_close_separate(self) -> None:
        quote = _us_intraday_quote(
            {
                "source": "yahoo_finance_chart",
                "session_scope": "all",
                "session_phase": "after_hours",
                "previous_close": 90.0,
                "regular_session_close": 91.25,
                "regular_session_close_time": "2026-06-02T16:00:00-04:00",
                "latest_point": {
                    "time": "2026-06-02T16:30:00-04:00",
                    "session": "after_hours",
                    "price": 92.0,
                    "volume": 450,
                },
                "point_count": 3,
            },
            calendar_status={
                "checked_at": "2026-06-02T16:31:00-04:00",
                "phase": "after_hours",
                "previous_trading_day": "2026-06-02",
            },
        )

        self.assertEqual(quote["price"], 92.0)
        self.assertEqual(quote["trade_date"], "2026-06-02")
        self.assertEqual(quote["quote_semantics"], "after_hours_last_trade")
        self.assertEqual(quote["regular_session_close"], 91.25)
        self.assertEqual(
            quote["regular_session_close_trade_date"],
            "2026-06-02",
        )
        self.assertEqual(quote["timezone"], "America/New_York")

    def test_historical_close_answer_names_exchange_and_taipei_times(self) -> None:
        answer = answer_composer.build_quote_consumer_answer(
            target={"type": "us_stock", "id": "AAPL", "market": "US"},
            analysis_digest={
                "as_of": "2026-07-20T16:00:00-04:00",
                "compact_evidence": {
                    "target": {"market": "US"},
                    "quote": {
                        "status": "historical",
                        "price": 326.59,
                        "trade_date": "2026-07-20",
                        "quote_time": "2026-07-20T16:00:00-04:00",
                        "quote_time_basis": "scheduled_regular_session_close",
                        "quote_semantics": "historical_regular_session_close",
                        "is_historical": True,
                    },
                },
            },
            missing=[],
            warnings=[],
            summary_limit=3,
            response_preferences={"language": "Traditional Chinese"},
        )

        self.assertIn("正常盤收盤價", answer["headline"])
        self.assertIn("2026-07-20 16:00 EDT", answer["detail"])
        self.assertIn("台北時間 2026-07-21 04:00", answer["detail"])
        self.assertIn("不是盤中或盤後成交價", answer["detail"])
        self.assertIn("特殊提早收盤日", answer["data_limits"][0])

    def test_exact_close_plan_does_not_schedule_current_intraday(self) -> None:
        plan, warnings = agentic_planning.plan_us_stock_tools(
            question="AAPL 2026-07-20 closing price",
            symbol="AAPL",
            target={"type": "us_stock", "id": "AAPL"},
            gaps={"missing": ["us_daily_price", "us_intraday_trend"]},
            budget={
                "max_calls": 3,
                "max_external_fetches": 2,
                "max_total_seconds": 20,
            },
            can_call_llm=False,
            requested_capabilities=("quote.snapshot", "intraday.bars"),
            requested_trade_date="2026-07-20",
            session_scope="all",
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [step["tool"] for step in plan["tool_plan"]],
            ["us.refresh_daily_price"],
        )

    def test_intraday_execution_forwards_session_scope(self) -> None:
        with patch.object(
            agentic_execution.us_market_service,
            "get_us_intraday_trend",
            return_value={"point_count": 1},
        ) as intraday:
            result = agentic_execution._execute_tool(
                db=object(),
                tool_name="us.read_intraday_trend",
                args={"symbol": "AAPL", "session_scope": "all"},
            )

        self.assertEqual(result["point_count"], 1)
        intraday.assert_called_once_with(
            symbol="AAPL",
            session_scope="all",
            db=ANY,
        )


if __name__ == "__main__":
    unittest.main()
