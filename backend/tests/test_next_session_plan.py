from __future__ import annotations

from datetime import date, datetime, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.main import app
from app.market.next_session_plan import (
    build_known_range,
    build_transition_level,
    build_tw_stock_next_session_plan,
    normalize_daily_history,
)
from app.market.next_session_plan_schemas import TaiwanNextSessionPlanRead
from app.market.trading_calendar import (
    TAIWAN_TZ,
    previous_taiwan_trading_day,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def trading_dates_ending(end: date, count: int) -> list[date]:
    values = [end]
    while len(values) < count:
        values.append(
            previous_taiwan_trading_day(values[-1], include_value=False)
        )
    values.reverse()
    return values


def add_stock(
    db: Session,
    *,
    stock_id: str = "2330",
    instrument_type: str = "stock",
    market: str = "TWSE",
) -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name="TSMC",
            market=market,
            instrument_type=instrument_type,
        )
    )
    db.commit()


def add_daily_history(
    db: Session,
    *,
    stock_id: str = "2330",
    end: date = date(2026, 8, 7),
    count: int = 80,
) -> None:
    source = SourceRegistry(
        source_name=f"test-daily-{stock_id}",
        source_type="test",
        category="market_daily_price",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url=f"https://example.test/{stock_id}/daily",
        status_code=200,
        content_hash=f"daily-{stock_id}",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()

    for index, trade_date in enumerate(trading_dates_ending(end, count)):
        close = 100.0 + index
        db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=trade_date,
                stock_id=stock_id,
                stock_name="TSMC",
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=close,
                trade_volume=1_000_000 + index,
            )
        )
    db.commit()


def pure_history(count: int = 60) -> list[dict]:
    dates = trading_dates_ending(date(2026, 8, 7), count)
    return [
        {
            "trade_date": trade_date,
            "open": float(index),
            "high": float(index + 2),
            "low": float(index - 2),
            "close": float(index),
        }
        for index, trade_date in enumerate(dates, start=1)
    ]


class NextSessionPlanPureTests(unittest.TestCase):
    def test_ma20_transition_is_self_consistent_candidate_threshold(self) -> None:
        history = pure_history()
        level = build_transition_level(
            history,
            period=20,
            as_of_close=60.0,
        )

        self.assertIsNotNone(level)
        assert level is not None
        self.assertEqual(level["transition_price"], 51.0)
        self.assertEqual(level["current_ma"], 50.5)
        self.assertEqual(level["projected_ma_if_flat"], 51.45)
        self.assertEqual(level["drift_if_flat"], 0.95)
        self.assertEqual(level["dropped_close"], 41.0)
        self.assertEqual(level["role_at_as_of_close"], "support")

        transition_sum = sum(row["close"] for row in history[-19:])
        for candidate in (50.0, 51.0, 52.0):
            projected_ma = (transition_sum + candidate) / 20
            self.assertEqual(
                candidate >= projected_ma,
                candidate >= level["transition_price"],
            )

    def test_ma60_transition_uses_latest_59_completed_closes(self) -> None:
        level = build_transition_level(
            pure_history(),
            period=60,
            as_of_close=60.0,
        )

        self.assertIsNotNone(level)
        assert level is not None
        self.assertEqual(level["transition_price"], 31.0)
        self.assertEqual(level["current_ma"], 30.5)
        self.assertEqual(level["dropped_close"], 1.0)

    def test_known_range_uses_latest_20_completed_sessions_including_as_of(self) -> None:
        result = build_known_range(pure_history())

        self.assertEqual(result["support"], 39.0)
        self.assertEqual(result["resistance"], 62.0)
        self.assertEqual(result["previous_session_low"], 58.0)
        self.assertEqual(result["previous_session_high"], 62.0)
        self.assertEqual(result["previous_session_close"], 60.0)

    def test_long_gap_invalidates_transition_window(self) -> None:
        history = pure_history(count=19)
        history[-1] = {
            **history[-1],
            "trade_date": history[-2]["trade_date"] + timedelta(days=11),
        }

        level = build_transition_level(
            history,
            period=20,
            as_of_close=float(history[-1]["close"]),
        )

        self.assertIsNone(level)

    def test_history_normalization_keeps_newest_row_per_trade_date(self) -> None:
        rows = [
            {
                "id": 1,
                "source_id": 1,
                "trade_date": date(2026, 8, 7),
                "close_price": 100,
                "high_price": 101,
                "low_price": 99,
            },
            {
                "id": 2,
                "source_id": 2,
                "trade_date": date(2026, 8, 7),
                "close_price": 105,
                "high_price": 106,
                "low_price": 104,
            },
        ]

        normalized, raw_count = normalize_daily_history(rows)

        self.assertEqual(raw_count, 2)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["close"], 105.0)
        self.assertEqual(normalized[0]["source_id"], 2)


class NextSessionPlanServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_weekend_plan_is_ready_for_next_taiwan_trading_day(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )

        validated = TaiwanNextSessionPlanRead.model_validate(plan)
        self.assertEqual(validated.status, "ready")
        self.assertTrue(validated.readiness.decision_usable)
        self.assertEqual(validated.as_of_trade_date, date(2026, 8, 7))
        self.assertEqual(validated.target_trade_date, date(2026, 8, 10))
        self.assertEqual(validated.target_session_state, "upcoming")
        self.assertEqual(
            [level.key for level in validated.levels],
            ["ma20_transition", "ma60_transition"],
        )
        self.assertEqual(
            [zone.key for zone in validated.scenario_zones],
            ["below_both", "between_transition_levels", "at_or_above_both"],
        )

    def test_regular_session_keeps_previous_close_plan_active(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 10, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["freshness"]["status"], "current")
        self.assertEqual(plan["target_session_state"], "active")
        self.assertEqual(plan["status"], "ready")
        self.assertTrue(plan["readiness"]["decision_usable"])

    def test_post_close_before_daily_release_is_pending_not_next_plan(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 10, 14, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["freshness"]["expected_trade_date"], date(2026, 8, 7))
        self.assertEqual(plan["target_trade_date"], date(2026, 8, 10))
        self.assertEqual(plan["target_session_state"], "completed_waiting_refresh")
        self.assertEqual(plan["status"], "pending")
        self.assertFalse(plan["readiness"]["decision_usable"])
        self.assertIn(
            "awaiting_latest_completed_daily_bar",
            plan["readiness"]["reason_codes"],
        )

    def test_post_release_missing_current_bar_remains_pending(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 10, 16, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["freshness"]["expected_trade_date"], date(2026, 8, 10))
        self.assertEqual(plan["freshness"]["status"], "stale")
        self.assertEqual(plan["status"], "pending")
        self.assertFalse(plan["readiness"]["decision_usable"])

    def test_older_plan_becomes_stale_after_target_session(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 11, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["target_session_state"], "expired")
        self.assertEqual(plan["status"], "stale")
        self.assertFalse(plan["readiness"]["decision_usable"])

    def test_short_history_returns_partial_ma20_only_plan(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db, count=25)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["status"], "partial")
        self.assertTrue(plan["readiness"]["decision_usable"])
        self.assertEqual(
            plan["readiness"]["available_level_keys"],
            ["ma20_transition"],
        )
        self.assertEqual(
            plan["readiness"]["missing_level_keys"],
            ["ma60_transition"],
        )

    def test_insufficient_ma20_history_returns_missing(self) -> None:
        add_stock(self.db)
        add_daily_history(self.db, count=18)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["status"], "missing")
        self.assertFalse(plan["readiness"]["decision_usable"])
        self.assertIn("ma20_history_insufficient", plan["readiness"]["reason_codes"])

    def test_non_stock_instrument_is_not_applicable(self) -> None:
        add_stock(self.db, instrument_type="etf")
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["status"], "not_applicable")
        self.assertFalse(plan["readiness"]["decision_usable"])
        self.assertEqual(plan["levels"], [])

    def test_missing_stock_master_keeps_math_but_blocks_decision_use(self) -> None:
        add_daily_history(self.db)

        plan = build_tw_stock_next_session_plan(
            db=self.db,
            stock_id="2330",
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(plan["status"], "partial")
        self.assertFalse(plan["readiness"]["decision_usable"])
        self.assertIn("instrument_metadata_partial", plan["readiness"]["reason_codes"])


class NextSessionPlanApiContractTests(unittest.TestCase):
    def test_openapi_exposes_named_next_session_plan_response(self) -> None:
        schema = app.openapi()
        operation = schema["paths"][
            "/api/market/technical/{stock_id}/next-session-plan"
        ]["get"]
        response_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        self.assertEqual(
            response_schema["$ref"],
            "#/components/schemas/TaiwanNextSessionPlanRead",
        )
        self.assertEqual(
            operation["operationId"],
            "get_stock_next_session_plan_api_market_technical__stock_id__next_session_plan_get",
        )


if __name__ == "__main__":
    unittest.main()
