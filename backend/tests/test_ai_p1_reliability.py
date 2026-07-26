from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Event
from time import perf_counter
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_execution, agentic_tools
from app.ai import ask as ai_ask
from app.ai import tools as ai_tools
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context import us_context
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    MonthlyRevenue,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    USDailyPrice,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_monthly_revenue(db: Session, *, stock_id: str, period: date) -> None:
    source = SourceRegistry(
        source_name="test-monthly-revenue",
        source_type="test",
        category="monthly_revenue",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(source_id=source.id, method="GET")
    db.add(raw)
    db.flush()
    db.add(
        MonthlyRevenue(
            source_id=source.id,
            raw_result_id=raw.id,
            period=period,
            stock_id=stock_id,
            stock_name="台積電",
            monthly_revenue=100_000,
        )
    )
    db.commit()


class AiP1FreshnessContractTests(unittest.TestCase):
    def test_available_monthly_revenue_can_be_stale_and_user_visible(self) -> None:
        db = make_session()
        try:
            db.add(
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
            )
            db.commit()
            add_monthly_revenue(db, stock_id="2330", period=date(2026, 4, 1))
            fixed_now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

            with patch.object(ai_tools, "_now", return_value=fixed_now):
                response = ai_ask.ask(
                    db=db,
                    payload=AiAskRequest(
                        question="台積電資料新鮮度",
                        target={"type": "data_freshness", "id": "2330", "market": "TW"},
                        mode="data_only",
                    ),
                )

            monthly = response["result"]["data"]["tables"]["monthly_revenue"]
            self.assertEqual(monthly["availability"], "available")
            self.assertEqual(monthly["freshness"], "stale")
            self.assertEqual(monthly["expected"], "2026-06-01")
            self.assertEqual(
                response["result"]["data"]["compact"]["slots"]["monthly_revenue"]["status"],
                "stale",
            )
            self.assertEqual(
                response["result"]["data"]["status"],
                response["result"]["data"]["compact"]["status"],
            )
            self.assertNotIn("human_answer", response["analysis"])
            self.assertNotIn("monthly_revenue", response["missing"])
            self.assertTrue(
                any("monthly_revenue" in warning for warning in response["warnings"])
            )
        finally:
            db.close()

    def test_explicit_data_freshness_market_is_preserved(self) -> None:
        db = make_session()
        try:
            response = ai_ask.ask(
                db=db,
                payload=AiAskRequest(
                    question="美股資料新鮮度",
                    target={"type": "data_freshness", "market": "US"},
                    mode="data_only",
                ),
            )

            self.assertEqual(response["target"]["market"], "US")
            self.assertEqual(response["result"]["scope"]["market"], "US")
            self.assertIn("us_daily_price", response["result"]["data"]["tables"])
            self.assertNotIn("market_daily_price", response["result"]["data"]["tables"])
        finally:
            db.close()

    def test_jp_kr_and_all_freshness_routes_do_not_fall_back_to_tw(self) -> None:
        db = make_session()
        try:
            jp = ai_tools.read_data_freshness(db, market="JP")
            kr = ai_tools.read_data_freshness(db, market="KR")
            all_markets = ai_tools.read_data_freshness(db, market="ALL")

            self.assertEqual(jp["scope"]["market"], "JP")
            self.assertIn("jp_daily_price", jp["data"]["tables"])
            self.assertEqual(kr["scope"]["market"], "KR")
            self.assertIn("kr_daily_price", kr["data"]["tables"])
            self.assertEqual(all_markets["scope"]["market"], "ALL")
            self.assertEqual(
                set(all_markets["data"]["markets"]),
                {"TW", "US", "JP", "KR", "CRYPTO"},
            )
            self.assertEqual(all_markets["data"]["status"], "missing")
            self.assertEqual(
                all_markets["data"]["compact"]["slots"]["us"]["status"],
                "missing",
            )
        finally:
            db.close()

    def test_unsupported_freshness_market_returns_structured_error(self) -> None:
        db = make_session()
        try:
            response = ai_ask.ask(
                db=db,
                payload=AiAskRequest(
                    question="加拿大市場資料新鮮度",
                    target={"type": "data_freshness", "market": "CA"},
                ),
            )

            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "UNSUPPORTED_MARKET")
            self.assertFalse(response["answer_ready"])
        finally:
            db.close()

    def test_explicit_unknown_freshness_is_not_promoted_by_as_of(self) -> None:
        passport = build_evidence_passport(
            kind="data_freshness",
            as_of="2026-07-19T08:00:00+00:00",
            freshness={"status": "unknown", "is_current": None},
        )

        self.assertEqual(passport["data_freshness"], "unknown")


class AiP1ProviderAndTimeoutTests(unittest.TestCase):
    def test_latest_daily_uses_existing_canonical_provider_rule(self) -> None:
        trade_date = date(2026, 7, 17)
        fetched_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        alpha = USDailyPrice(
            id=1,
            provider="alphavantage",
            symbol="NVDA",
            trade_date=trade_date,
            open_price=170.0,
            high_price=172.0,
            low_price=169.0,
            close_price=171.0,
            trade_volume=1_000,
            fetched_at=fetched_at,
        )
        yahoo = USDailyPrice(
            id=2,
            provider="yahoo_chart",
            symbol="NVDA",
            trade_date=trade_date,
            open_price=170.0,
            high_price=172.0,
            low_price=169.0,
            close_price=171.0,
            trade_volume=1_000,
            fetched_at=fetched_at,
        )

        selected = us_context._select_latest_daily([alpha, yahoo])

        self.assertIsNotNone(selected)
        self.assertEqual(selected.provider, "yahoo_chart")

    def test_selected_current_provider_is_separate_from_stale_fallback(self) -> None:
        source_health = {
            "summary": {"total": 2, "stale": 1},
            "entries": [
                {
                    "resource": "daily_price",
                    "provider": "yahoo_chart",
                    "status": "current",
                },
                {
                    "resource": "daily_price",
                    "provider": "alphavantage",
                    "status": "stale",
                },
            ],
        }

        annotated = us_context._annotate_daily_provider_roles(
            source_health,
            selected_provider="yahoo_chart",
        )

        entries = {entry["provider"]: entry for entry in annotated["entries"]}
        self.assertEqual(entries["yahoo_chart"]["provider_role"], "selected")
        self.assertEqual(entries["alphavantage"]["provider_role"], "fallback")
        self.assertEqual(annotated["selected_provider_status"], "current")
        self.assertEqual(annotated["selected_evidence_summary"]["stale_count"], 0)
        self.assertEqual(annotated["fallback_provider_summary"]["stale_count"], 1)

    def test_tool_wall_clock_deadline_returns_timeout(self) -> None:
        db = make_session()
        cancelled = Event()

        def wait_for_cancel(
            _db: Session,
            _tool_name: str,
            _args: dict[str, object],
            *,
            cancel_event: Event | None = None,
        ) -> dict[str, object]:
            self.assertIsNotNone(cancel_event)
            cancelled.set()
            cancel_event.wait(5)
            return {"status": "cancelled"}

        try:
            started = perf_counter()
            with patch.object(agentic_execution, "_execute_tool", side_effect=wait_for_cancel):
                runs, warnings = agentic_execution.execute_tool_plan(
                    db=db,
                    plan={
                        "tool_plan": [
                            {
                                "tool": "us.read_intraday_trend",
                                "args": {"symbol": "NVDA"},
                                "reason": "deadline regression",
                            }
                        ]
                    },
                    budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 1},
                    can_external_fetch=True,
                    fallback_to_cached=True,
                )
            elapsed = perf_counter() - started

            self.assertTrue(cancelled.is_set())
            self.assertLess(elapsed, 1.5)
            self.assertEqual(runs[0]["status"], "timeout")
            self.assertTrue(runs[0]["fallback_used"])
            self.assertFalse(runs[0]["cached_data_returned"])
            self.assertTrue(runs[0]["cancellation_requested"])
            self.assertTrue(runs[0]["background_completion_possible"])
            self.assertTrue(any("timed out" in warning for warning in warnings))
        finally:
            db.close()

    def test_timeout_fallback_reports_cached_data(self) -> None:
        runs = [
            {
                "status": "timeout",
                "fallback_used": True,
                "cached_data_returned": False,
                "result_summary": {},
            }
        ]

        agentic_tools._annotate_timeout_fallback(runs, cached_data_available=True)

        self.assertTrue(runs[0]["cached_data_returned"])
        self.assertEqual(runs[0]["result_summary"]["status"], "timeout")
        self.assertTrue(runs[0]["result_summary"]["fallback_used"])

    def test_expected_date_alone_is_not_cached_evidence(self) -> None:
        freshness = {
            "expected_dates": {"market_daily_price": "2026-07-17"},
            "datasets": [{"key": "market_daily_price", "latest": None}],
        }

        self.assertFalse(agentic_tools._freshness_has_cached_data(freshness))
        freshness["datasets"][0]["latest"] = "2026-07-16"
        self.assertTrue(agentic_tools._freshness_has_cached_data(freshness))


if __name__ == "__main__":
    unittest.main()
