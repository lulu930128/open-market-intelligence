from __future__ import annotations

from datetime import date, datetime
import unittest
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, TaiwanMarketMinuteState
from app.market.taiwan_market_state import (
    persist_taiwan_market_minute_state,
    read_taiwan_market_volume_state,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def market_summary_payload(
    trade_date: date,
    *,
    hour: int,
    minute: int,
    twse_trade_value: int,
    tpex_trade_value: int,
) -> dict:
    as_of = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        hour,
        minute,
        45,
        tzinfo=TAIWAN_TZ,
    )
    rows = []
    for index_id, market, trade_value, total_count in (
        ("TAIEX", "TWSE", twse_trade_value, 1062),
        ("TPEX", "TPEX", tpex_trade_value, 866),
    ):
        rows.append(
            {
                "index_id": index_id,
                "market": market,
                "source": "official_index_summary",
                "as_of": as_of.isoformat(),
                "time": trade_date.isoformat(),
                "close": 20000.0,
                "change": 100.0,
                "change_pct": 0.5,
                "trade_value": trade_value,
                "estimated_trade_value": trade_value * 2,
                "breadth": {
                    "market": market,
                    "scope": "full_market",
                    "trade_date": trade_date.isoformat(),
                    "advance_count": total_count // 2,
                    "decline_count": total_count // 3,
                    "unchanged_count": total_count - total_count // 2 - total_count // 3,
                    "total_count": total_count,
                    "limit_up_count": 10,
                    "limit_down_count": 1,
                    "trade_value": trade_value,
                    "source": f"{market.lower()}_official_breadth",
                },
                "breadth_status": {
                    "status": "ready",
                    "scope": "full_market",
                },
                "current_data_core": {
                    "index": {
                        "provider": "twse_mis",
                        "source": "twse_mis_index_snapshot",
                        "raw_result_id": f"raw_fetch_result:{market}:index:{trade_date}",
                        "as_of": as_of.isoformat(),
                    },
                    "breadth": {
                        "provider": "twse_mis",
                        "source": "twse_mis_live_breadth",
                        "raw_result_id": f"raw_fetch_result:{market}:breadth:{trade_date}",
                        "as_of": as_of.isoformat(),
                    },
                },
            }
        )
    return {
        "as_of": as_of.isoformat(),
        "source": "official_index_summary",
        "indices": rows,
    }


class TaiwanMarketStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    def test_minute_state_upserts_and_builds_same_time_volume_baselines(self) -> None:
        history_dates = [
            date(2026, 7, 14),
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 17),
            date(2026, 7, 20),
            date(2026, 7, 21),
        ]
        combined_values = [120, 132, 144, 156, 168, 180]
        for trade_date, combined in zip(history_dates, combined_values, strict=True):
            result = persist_taiwan_market_minute_state(
                self.db,
                payload=market_summary_payload(
                    trade_date,
                    hour=10,
                    minute=30,
                    twse_trade_value=combined - 20,
                    tpex_trade_value=20,
                ),
            )
            self.assertEqual(result["inserted_count"], 2)

        current_date = date(2026, 7, 22)
        persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                current_date,
                hour=10,
                minute=29,
                twse_trade_value=160,
                tpex_trade_value=20,
            ),
        )
        first = persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                current_date,
                hour=10,
                minute=30,
                twse_trade_value=210,
                tpex_trade_value=20,
            ),
        )
        updated = persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                current_date,
                hour=10,
                minute=30,
                twse_trade_value=220,
                tpex_trade_value=20,
            ),
        )

        self.assertEqual(first["inserted_count"], 2)
        self.assertEqual(updated["updated_count"], 2)
        self.assertEqual(
            self.db.query(TaiwanMarketMinuteState)
            .filter(TaiwanMarketMinuteState.trade_date == current_date)
            .count(),
            4,
        )

        state = read_taiwan_market_volume_state(self.db)

        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["comparison_minute"], "10:30")
        self.assertEqual(state["current_cumulative_trade_value"], 240)
        self.assertEqual(state["available_cumulative_trade_value"], 240)
        self.assertTrue(state["trade_value_available"])
        self.assertTrue(state["trade_value_complete"])
        self.assertEqual(state["trade_value_coverage_status"], "complete")
        self.assertEqual(state["trade_value_authority_status"], "official")
        self.assertEqual(state["trade_value_status"], "official_complete")
        self.assertEqual(state["included_markets"], ["TWSE", "TPEX"])
        self.assertEqual(state["missing_markets"], [])
        self.assertEqual(state["currency"], "TWD")
        self.assertEqual(state["trade_value_unit"], "TWD")
        self.assertTrue(
            all(
                item["trade_value_unit"] == "TWD"
                for item in state["markets"]
            )
        )
        self.assertEqual(state["previous_minute_cumulative_trade_value"], 180)
        self.assertEqual(state["one_minute_trade_value_change"], 60)
        self.assertEqual(
            state["field_status"]["current_cumulative_trade_value"]["status"],
            "available",
        )
        self.assertEqual(
            state["field_status"]["previous_minute_cumulative_trade_value"]["status"],
            "available",
        )
        self.assertEqual(
            state["same_time_baseline_5d"]["median_cumulative_trade_value"],
            156,
        )
        self.assertAlmostEqual(
            state["same_time_baseline_5d"]["pace_ratio"],
            240 / 156,
        )
        self.assertEqual(state["same_time_baseline_20d"]["sample_days"], 6)
        self.assertEqual(
            state["same_time_baseline_5d"]["sample_status"],
            "complete",
        )
        self.assertEqual(
            len(state["same_time_baseline_5d"]["samples"]),
            5,
        )
        self.assertEqual(
            state["same_time_baseline_5d"]["samples"][-1],
            {
                "trade_date": "2026-07-21",
                "cumulative_trade_value": 180,
                "authority_status": "official",
            },
        )
        self.assertEqual(
            state["same_time_baseline_20d"]["sample_status"],
            "provisional",
        )
        self.assertEqual(
            state["same_time_baseline_20d"]["status"],
            "warming_up",
        )
        self.assertIsNone(state["same_time_baseline_20d"]["pace_ratio"])
        self.assertEqual(
            state["same_time_baseline_20d"]["pace_ratio_status"],
            "insufficient_history",
        )
        self.assertEqual(state["baseline_readiness_status"], "warming_up")
        self.assertEqual(state["available_sample_days"], 6)
        self.assertEqual(state["expected_5d_ready_after_sessions"], 0)
        self.assertEqual(state["expected_20d_ready_after_sessions"], 14)
        self.assertEqual(state["next_fill"], "scheduler_accumulation")

    def test_volume_state_reports_warming_up_when_history_empty(self) -> None:
        trade_date = date(2026, 7, 22)
        persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                trade_date,
                hour=10,
                minute=30,
                twse_trade_value=200,
                tpex_trade_value=40,
            ),
        )

        state = read_taiwan_market_volume_state(self.db)

        baseline_5d = state["same_time_baseline_5d"]
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["baseline_readiness_status"], "warming_up")
        self.assertEqual(state["available_sample_days"], 0)
        self.assertEqual(state["expected_5d_ready_after_sessions"], 5)
        self.assertEqual(state["expected_20d_ready_after_sessions"], 20)
        self.assertEqual(state["next_fill"], "scheduler_accumulation")
        self.assertEqual(baseline_5d["status"], "warming_up")
        self.assertEqual(baseline_5d["sample_status"], "empty")
        self.assertEqual(baseline_5d["available_sample_days"], 0)
        self.assertEqual(baseline_5d["required_sample_days"], 5)
        self.assertEqual(baseline_5d["expected_ready_after_sessions"], 5)
        self.assertEqual(baseline_5d["next_fill"], "scheduler_accumulation")
        self.assertIsNone(baseline_5d["pace_ratio"])
        self.assertEqual(
            baseline_5d["backfill_status"],
            "unavailable_no_trusted_historical_minute_provider",
        )

    def test_final_reconciliation_uses_official_close_minute(self) -> None:
        trade_date = date(2026, 7, 22)
        result = persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                trade_date,
                hour=15,
                minute=5,
                twse_trade_value=1000,
                tpex_trade_value=200,
            ),
            finalized=True,
        )

        rows = self.db.query(TaiwanMarketMinuteState).all()
        self.assertEqual(result["inserted_count"], 2)
        self.assertEqual({row.session_status for row in rows}, {"final"})
        self.assertEqual({row.minute_at.strftime("%H:%M") for row in rows}, {"13:30"})
        self.assertTrue(all(row.official_flag for row in rows))

    def test_cumulative_trade_value_regression_is_visible_as_invalid(self) -> None:
        trade_date = date(2026, 7, 22)
        persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                trade_date,
                hour=10,
                minute=29,
                twse_trade_value=200,
                tpex_trade_value=50,
            ),
        )
        persist_taiwan_market_minute_state(
            self.db,
            payload=market_summary_payload(
                trade_date,
                hour=10,
                minute=30,
                twse_trade_value=190,
                tpex_trade_value=55,
            ),
        )

        rows = (
            self.db.query(TaiwanMarketMinuteState)
            .filter(TaiwanMarketMinuteState.minute_at.like("2026-07-22 10:30%"))
            .all()
        )
        quality_by_market = {row.market: row.quality_status for row in rows}
        state = read_taiwan_market_volume_state(self.db)

        self.assertEqual(quality_by_market["TWSE"], "invalid_value")
        self.assertEqual(quality_by_market["TPEX"], "ready")
        self.assertEqual(state["status"], "partial")
        self.assertIsNone(state["current_cumulative_trade_value"])
        self.assertEqual(state["available_cumulative_trade_value"], 55)
        self.assertTrue(state["trade_value_available"])
        self.assertFalse(state["trade_value_complete"])
        self.assertEqual(state["trade_value_status"], "partial")
        self.assertEqual(state["included_markets"], ["TPEX"])
        self.assertEqual(state["missing_markets"], ["TWSE"])
        self.assertEqual(
            state["field_status"]["current_cumulative_trade_value"]["status"],
            "missing",
        )

    def test_preopen_does_not_reuse_index_daily_trade_value(self) -> None:
        trade_date = date(2026, 8, 4)
        as_of = datetime(2026, 8, 4, 8, 59, tzinfo=TAIWAN_TZ)
        payload = {
            "as_of": as_of.isoformat(),
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "time": trade_date.isoformat(),
                    "close": 23_500.0,
                    "trade_value": 450_000_000_000,
                    "breadth": {
                        "market": "TWSE",
                        "trade_date": trade_date.isoformat(),
                        "market_session": "preopen_auction",
                        "scope": "full_market",
                        "advance_count": 1,
                        "decline_count": 1,
                        "unchanged_count": 1,
                        "total_count": 3,
                    },
                    "breadth_status": {"status": "ready"},
                }
            ],
        }

        persist_taiwan_market_minute_state(self.db, payload=payload, now=as_of)

        row = self.db.query(TaiwanMarketMinuteState).one()
        state = read_taiwan_market_volume_state(self.db)
        self.assertIsNone(row.cumulative_trade_value)
        self.assertEqual(row.trade_value_quality_status, "missing")
        self.assertIsNone(state["current_cumulative_trade_value"])
        self.assertFalse(state["trade_value_available"])


if __name__ == "__main__":
    unittest.main()
