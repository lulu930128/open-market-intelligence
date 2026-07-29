from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from app.ai import realtime_contract


class AiRealtimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 24, 2, 0, tzinfo=timezone.utc)

    def test_closed_taiwan_quote_is_latest_session_not_live(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "latest_price": 1_105.0,
                "quote_time": "2026-07-23T13:30:00+08:00",
                "market_status": "latest_session_close",
                "session_phase": "post_close_snapshot",
                "quote_semantics": "latest_completed_session",
                "is_live": False,
            },
            market="TW",
            realtime_policy="require_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertFalse(result["policy_satisfied"])
        self.assertFalse(result["refresh_possible_now"])
        self.assertFalse(result["refresh_recommended"])
        self.assertEqual(result["status_class"], "blocked")

    def test_local_daily_close_is_latest_session_during_preopen_pending(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "status": "delayed_daily_close",
                "latest_price": 2_405.0,
                "trade_date": "2026-07-23",
                "provider": "local_daily_close",
                "market_status": "preopen",
                "session_phase": "preopen_pending",
                "is_realtime": False,
                "freshness": {
                    "status": "daily_close",
                    "is_stale": False,
                },
            },
            market="TW",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertTrue(result["policy_satisfied"])
        self.assertTrue(result["decision_usable"])
        self.assertFalse(result["refresh_recommended"])

    def test_open_us_quote_with_current_event_is_live(self) -> None:
        event_time = self.now - timedelta(seconds=20)
        result = realtime_contract.classify_observation(
            {
                "price": 180.5,
                "quote_time": event_time.isoformat(),
                "market_status": "open",
                "session_phase": "regular",
                "is_live": True,
            },
            market="US",
            realtime_policy="require_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "live")
        self.assertTrue(result["policy_satisfied"])
        self.assertTrue(result["decision_usable"])

    def test_tw_futures_nested_after_hours_market_status_is_live(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "last_price": 23_500.0,
                "quote_time": "2026-07-28T22:33:05+08:00",
                "session": "after_hours",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                    "market_status": {
                        "status": "open",
                        "phase": "after_hours",
                        "is_open": True,
                    },
                },
            },
            market="TW",
            realtime_policy="require_live",
            now=datetime(2026, 7, 28, 14, 33, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "live")
        self.assertEqual(result["market_status"], "open")
        self.assertEqual(result["session_phase"], "after_hours")
        self.assertEqual(result["observation_mode"], "live_quote")
        self.assertTrue(result["policy_satisfied"])
        self.assertTrue(result["decision_usable"])

    def test_open_us_quote_outside_delay_window_is_stale(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 180.5,
                "quote_time": (self.now - timedelta(minutes=20)).isoformat(),
                "market_status": "open",
                "session_phase": "regular",
                "is_live": True,
            },
            market="US",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "stale")
        self.assertFalse(result["decision_usable"])
        self.assertTrue(result["refresh_recommended"])

    def test_jp_delayed_feed_uses_declared_provider_window_before_stale(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 42_000.0,
                "quote_time": (self.now - timedelta(minutes=17)).isoformat(),
                "market_status": "open",
                "session_phase": "regular",
                "is_live": False,
            },
            market="JP",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "delayed")
        self.assertEqual(result["expected_provider_delay_seconds"], 900)
        self.assertEqual(result["excess_delay_seconds"], 120)
        self.assertEqual(
            result["expected_provider_delay_source"],
            "omi_market_provider_policy",
        )
        self.assertTrue(result["decision_usable"])

    def test_jp_delayed_feed_beyond_excess_tolerance_is_stale(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 42_000.0,
                "quote_time": (self.now - timedelta(minutes=19)).isoformat(),
                "market_status": "open",
                "session_phase": "regular",
            },
            market="JP",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "stale")
        self.assertEqual(result["expected_provider_delay_seconds"], 900)
        self.assertEqual(result["excess_delay_seconds"], 240)

    def test_weekend_us_close_matches_latest_completed_trading_session(
        self,
    ) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 213.88,
                "quote_time": "2026-07-24T16:00:00-04:00",
                "market_status": "closed",
                "session_phase": "market_closed",
                "is_live": False,
            },
            market="US",
            realtime_policy="prefer_live",
            now=datetime(2026, 7, 25, 16, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertEqual(result["observation_mode"], "session_close")
        self.assertEqual(result["status_class"], "ready")
        self.assertTrue(result["policy_satisfied"])
        self.assertTrue(result["decision_usable"])
        self.assertFalse(result["refresh_recommended"])

    def test_old_us_close_label_cannot_override_expected_session_date(
        self,
    ) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 213.88,
                "quote_time": "2026-07-24T16:00:00-04:00",
                "market_status": "closed",
                "session_phase": "post_close",
                "quote_semantics": "latest_completed_session",
                "is_latest_session_quote": True,
            },
            market="US",
            realtime_policy="prefer_live",
            now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "stale")
        self.assertFalse(result["decision_usable"])
        self.assertTrue(result["refresh_recommended"])

    def test_tw_post_close_bar_matches_latest_completed_session(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 2_325.0,
                "bar_time": "2026-07-27T13:30:00+08:00",
                "provider": "yahoo_finance_chart",
                "market_status": "closed",
                "session_phase": "post_close",
            },
            market="TW",
            realtime_policy="cache_only",
            now=datetime(2026, 7, 27, 5, 40, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertEqual(result["status_class"], "ready")
        self.assertTrue(result["decision_usable"])

    def test_jp_post_close_bar_matches_latest_completed_session(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 42_100.0,
                "bar_time": "2026-07-27T15:30:00+09:00",
                "provider": "yahoo_finance_chart",
                "market_status": "closed",
                "session_phase": "post_close",
            },
            market="JP",
            realtime_policy="prefer_live",
            now=datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertEqual(result["status_class"], "ready")

    def test_kr_post_close_bar_matches_latest_completed_session(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 92_000.0,
                "bar_time": "2026-07-27T15:30:00+09:00",
                "provider": "naver_finance",
                "market_status": "closed",
                "session_phase": "post_close",
            },
            market="KR",
            realtime_policy="prefer_live",
            now=datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertEqual(result["status_class"], "ready")

    def test_completed_session_does_not_satisfy_require_live(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 2_325.0,
                "bar_time": "2026-07-27T13:30:00+08:00",
                "provider": "yahoo_finance_chart",
                "market_status": "closed",
                "session_phase": "post_close",
            },
            market="TW",
            realtime_policy="require_live",
            now=datetime(2026, 7, 27, 5, 40, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "latest_completed_session")
        self.assertFalse(result["policy_satisfied"])
        self.assertEqual(result["status_class"], "blocked")

    def test_explicit_historical_us_close_is_not_latest_or_live(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "status": "historical",
                "price": 326.59,
                "trade_date": "2026-07-20",
                "quote_time": "2026-07-20T16:00:00-04:00",
                "market_status": "historical",
                "session_phase": "regular_session_close",
                "quote_semantics": "historical_regular_session_close",
                "is_historical": True,
                "is_live": False,
                "is_latest_session_quote": False,
            },
            market="US",
            realtime_policy="prefer_live",
            now=datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "historical")
        self.assertEqual(result["observation_mode"], "historical_close")
        self.assertTrue(result["policy_satisfied"])
        self.assertTrue(result["decision_usable"])
        self.assertFalse(result["refresh_recommended"])

    def test_open_us_latest_session_flag_cannot_be_completed_session(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 180.5,
                "quote_time": (self.now - timedelta(minutes=20)).isoformat(),
                "market_status": "open",
                "session_phase": "regular",
                "is_latest_session_quote": True,
                "quote_semantics": "latest_completed_session",
            },
            market="US",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "stale")
        self.assertNotEqual(
            result["observation_mode"],
            "session_close",
        )
        self.assertNotEqual(
            result["reason"],
            "Market is not live; value represents the latest completed session.",
        )

    def test_open_us_latest_session_flag_is_live_inside_live_window(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "price": 180.5,
                "quote_time": (self.now - timedelta(seconds=20)).isoformat(),
                "market_status": "open",
                "session_phase": "regular",
                "is_latest_session_quote": True,
            },
            market="US",
            realtime_policy="require_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "live")
        self.assertEqual(result["observation_mode"], "live_quote")
        self.assertTrue(result["policy_satisfied"])

    def test_fresh_crypto_pull_can_be_live_without_stream_flag(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "last_price": 118_000.0,
                "event_time": (self.now - timedelta(seconds=12)).isoformat(),
                "fetched_at": (self.now - timedelta(seconds=5)).isoformat(),
                "market_status": "continuous",
                "is_realtime": False,
            },
            market="crypto",
            realtime_policy="require_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "live")
        self.assertEqual(result["observation_mode"], "on_demand_snapshot")
        self.assertTrue(result["policy_satisfied"])

    def test_crypto_current_label_does_not_override_old_timestamps(self) -> None:
        result = realtime_contract.classify_observation(
            {
                "status": "current",
                "last_price": 118_000.0,
                "event_time": (self.now - timedelta(hours=1)).isoformat(),
                "fetched_at": (self.now - timedelta(hours=1)).isoformat(),
                "market_status": "continuous",
            },
            market="crypto",
            realtime_policy="prefer_live",
            now=self.now,
        )

        self.assertEqual(result["state"], "stale")
        self.assertFalse(result["decision_usable"])
        self.assertTrue(result["refresh_recommended"])


if __name__ == "__main__":
    unittest.main()
