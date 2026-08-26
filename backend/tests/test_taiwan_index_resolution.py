from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from app.market import indices
from app.market.index_resolution import resolve_taiwan_index_quote_state
from app.market.trading_calendar import TAIWAN_TZ


def _calendar(*, phase: str, checked_at: datetime) -> dict:
    return {
        "timezone": "Asia/Taipei",
        "checked_at": checked_at.isoformat(),
        "date": checked_at.date().isoformat(),
        "previous_trading_day": "2026-08-13",
        "is_trading_day": True,
        "phase": phase,
    }


class TaiwanIndexResolutionTests(unittest.TestCase):
    def test_regular_session_prefers_current_intraday_and_is_deterministic(
        self,
    ) -> None:
        checked_at = datetime(2026, 8, 14, 10, 0, tzinfo=TAIWAN_TZ)
        intraday = {
            "source": "twse_index_5s_intraday",
            "provider": "twse",
            "trade_date": "2026-08-14",
            "points": [
                {
                    "time": "2026-08-14T09:59:00+08:00",
                    "price": 24_321.5,
                }
            ],
        }
        snapshot = {
            "index_id": "TAIEX",
            "time": "2026-08-13",
            "as_of": "2026-08-13T13:30:00+08:00",
            "close": 24_000.0,
            "source": "market_index_daily_stat",
        }

        first = resolve_taiwan_index_quote_state(
            intraday=intraday,
            index_snapshot=snapshot,
            calendar_status=_calendar(
                phase="regular",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="prefer_live",
        )
        repeated = resolve_taiwan_index_quote_state(
            intraday=intraday,
            index_snapshot=snapshot,
            calendar_status=_calendar(
                phase="regular",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="prefer_live",
        )

        self.assertEqual(first["selected_candidate"], "intraday_last_trade")
        self.assertEqual(first["selected_trade_date"], "2026-08-14")
        self.assertEqual(first["selected_value"], 24_321.5)
        self.assertTrue(first["decision_usable"])
        self.assertEqual(first["resolution_id"], repeated["resolution_id"])
        self.assertEqual(first["acquisition_policy"], "prefer_live")
        self.assertEqual(first["selected_provider"], "twse")
        self.assertEqual(first["selected_authority"], "official_exchange")
        self.assertEqual(first["selected_finalization"], "intraday")
        self.assertTrue(first["official_source"])
        self.assertFalse(first["official_close_confirmed"])
        self.assertFalse(first["provisional_estimate"])

    def test_stale_same_day_intraday_is_not_current_live_evidence(self) -> None:
        checked_at = datetime(2026, 8, 14, 11, 0, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday={
                "source": "taiwan_index_minute_snapshot",
                "trade_date": "2026-08-14",
                "points": [
                    {
                        "time": "2026-08-14T09:05:00+08:00",
                        "price": 24_100.0,
                    }
                ],
            },
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-13",
                "close": 24_000.0,
                "source": "market_index_daily_stat",
            },
            calendar_status=_calendar(
                phase="regular",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        intraday_candidate = result["candidates"][0]
        self.assertFalse(intraday_candidate["eligible"])
        self.assertGreater(intraday_candidate["age_seconds"], 240)
        self.assertIsNone(result["selected_candidate"])
        self.assertFalse(result["decision_usable"])

    def test_completed_official_component_keeps_its_own_trade_date(self) -> None:
        checked_at = datetime(2026, 8, 14, 10, 0, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday={
                "source": "twse_index_5s_intraday",
                "provider": "twse",
                "trade_date": "2026-08-14",
                "points": [
                    {
                        "time": "2026-08-14T09:59:00+08:00",
                        "price": 24_321.5,
                    }
                ],
            },
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T09:59:00+08:00",
                "close": 24_321.5,
                "source": "twse_index_5s_intraday",
                "official_close_status": "confirmed",
                "official_close_price": 24_000.0,
                "official_close_trade_date": "2026-08-13",
                "official_close_source": "twse_openapi_fmtqik",
            },
            calendar_status=_calendar(
                phase="regular",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "intraday_last_trade")
        self.assertEqual(result["selected_trade_date"], "2026-08-14")
        self.assertFalse(result["official_close_available"])
        self.assertIsNone(result["official_close_trade_date"])

    def test_post_close_uses_confirmed_official_close(self) -> None:
        checked_at = datetime(2026, 8, 14, 13, 34, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:05+08:00",
                "close": 24_456.78,
                "source": "twse_index_5s_snapshot",
                "official_close_status": "confirmed",
            },
            calendar_status=_calendar(
                phase="post_close",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "official_close")
        self.assertEqual(result["official_close_status"], "confirmed")
        self.assertEqual(result["selected_value"], 24_456.78)
        self.assertTrue(result["decision_usable"])
        self.assertEqual(result["selected_authority"], "official_exchange")
        self.assertEqual(result["selected_finalization"], "final")
        self.assertTrue(result["official_source"])
        self.assertTrue(result["official_close_confirmed"])
        self.assertFalse(result["provisional_estimate"])

    def test_post_close_unconfirmed_provider_value_is_explicitly_provisional(self) -> None:
        checked_at = datetime(2026, 8, 14, 13, 31, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:05+08:00",
                "close": 24_450.0,
                "source": "third_party_index_snapshot",
                "provider": "example_provider",
            },
            calendar_status=_calendar(
                phase="post_close",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "index_summary")
        self.assertEqual(result["selected_provider"], "example_provider")
        self.assertEqual(result["selected_authority"], "provider")
        self.assertEqual(result["selected_finalization"], "provisional")
        self.assertFalse(result["official_source"])
        self.assertFalse(result["official_close_confirmed"])
        self.assertTrue(result["provisional_estimate"])

    def test_cache_only_policy_performs_no_live_acquisition(self) -> None:
        cached = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "taiwan_index_minute_snapshot",
            "provider": "scheduler_snapshot_aggregation",
            "trade_date": "2026-08-14",
            "interval": "1m",
            "synthetic": True,
            "coverage_status": "synthetic_partial",
            "is_partial": True,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-14T13:30:00+08:00",
                    "price": 24_456.78,
                    "open": 24_456.78,
                    "high": 24_456.78,
                    "low": 24_456.78,
                    "close": 24_456.78,
                    "volume": None,
                }
            ],
        }
        with (
            patch(
                "app.market.taiwan_index_minute."
                "read_persisted_taiwan_index_minute_series",
                return_value=cached,
            ),
            patch.object(
                indices,
                "_get_market_index_intraday_prefer_live",
            ) as live_reader,
        ):
            result = indices.get_market_index_intraday(
                "TAIEX",
                acquisition_policy="cache_only",
            )

        live_reader.assert_not_called()
        self.assertEqual(result["acquisition_policy"], "cache_only")
        self.assertEqual(result["acquisition_status"], "cached")
        self.assertIn("resolution_id", result)

    def test_require_live_rejects_cached_fallback(self) -> None:
        cached = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "taiwan_index_minute_snapshot",
            "provider": "scheduler_snapshot_aggregation",
            "trade_date": "2026-08-14",
            "synthetic": True,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-14T13:30:00+08:00",
                    "price": 24_456.78,
                }
            ],
        }
        with patch.object(
            indices,
            "_get_market_index_intraday_prefer_live",
            return_value=cached,
        ):
            with self.assertRaisesRegex(RuntimeError, "Live Taiwan index"):
                indices.get_market_index_intraday(
                    "TAIEX",
                    acquisition_policy="require_live",
                )


if __name__ == "__main__":
    unittest.main()
