from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from app.market import indices
from app.market.index_resolution import resolve_taiwan_index_quote_state
from app.market.trading_calendar import TAIWAN_TZ


def _calendar(*, phase: str, checked_at: datetime) -> dict:
    presentation_trade_date = (
        "2026-08-14"
        if phase
        in {"regular", "regular_live", "closing_auction", "close_resolution", "post_close"}
        else "2026-08-13"
    )
    return {
        "timezone": "Asia/Taipei",
        "checked_at": checked_at.isoformat(),
        "date": checked_at.date().isoformat(),
        "previous_trading_day": "2026-08-13",
        "is_trading_day": True,
        "phase": phase,
        "presentation_session": {
            "trade_date": presentation_trade_date,
            "state": "today" if presentation_trade_date == "2026-08-14" else "previous_session",
        },
    }


class TaiwanIndexResolutionTests(unittest.TestCase):
    def test_preopen_uses_presentation_session_and_prefers_completed_daily(self) -> None:
        checked_at = datetime(2026, 8, 14, 8, 10, tzinfo=TAIWAN_TZ)
        calendar = _calendar(phase="preopen_pending", checked_at=checked_at)
        calendar["previous_trading_day"] = "2026-08-14"
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "trade_date": "2026-08-13",
                "as_of": "2026-08-13T13:30:00+08:00",
                "close": 46_752.93,
                "source": "fugle_indices_stream",
                "provider": "fugle",
                "completed_daily_close": 46_948.72,
                "completed_daily_trade_date": "2026-08-13",
                "completed_daily_event_time": "2026-08-13T13:30:00+08:00",
                "completed_daily_source": "twse_mi_5mins_hist",
                "completed_daily_provider": "twse",
                "completed_daily_authority": "exchange",
                "completed_daily_finalization": "final",
                "completed_daily_official": True,
                "completed_daily_release_status": "released",
                "completed_daily_reconciliation_status": "not_applicable",
                "completed_daily_qualified": True,
            },
            calendar_status=calendar,
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["expected_trade_date"], "2026-08-13")
        self.assertEqual(result["selected_candidate"], "completed_daily_bar")
        self.assertEqual(result["selected_value"], 46_948.72)
        self.assertEqual(result["selection_reason"], "qualified_completed_daily_bar")
        self.assertEqual(result["freshness_status"], "latest_completed_session")
        self.assertTrue(result["decision_usable"])

    def test_preopen_unconfirmed_summary_is_visible_but_not_decision_usable(self) -> None:
        checked_at = datetime(2026, 8, 14, 8, 10, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "trade_date": "2026-08-13",
                "as_of": "2026-08-13T13:30:00+08:00",
                "close": 46_752.93,
                "source": "fugle_indices_stream",
                "provider": "fugle",
            },
            calendar_status=_calendar(
                phase="preopen_pending",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "index_summary")
        self.assertEqual(result["selection_reason"], "same_trade_date_summary_fallback")
        self.assertFalse(result["decision_usable"])
        self.assertEqual(result["freshness_status"], "latest_completed_session")

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
        self.assertEqual(first["freshness_status"], "current")
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
        self.assertEqual(result["freshness_status"], "stale")

    def test_active_session_rejects_stale_same_day_summary_fallback(self) -> None:
        checked_at = datetime(2026, 8, 14, 11, 0, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "trade_date": "2026-08-14",
                "as_of": "2026-08-14T09:05:00+08:00",
                "close": 24_100.0,
                "source": "twse_mis_index_snapshot",
            },
            calendar_status=_calendar(
                phase="regular",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        summary_candidate = result["candidates"][1]
        self.assertFalse(summary_candidate["eligible"])
        self.assertGreater(summary_candidate["age_seconds"], 240)
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
        self.assertFalse(result["decision_usable"])
        self.assertEqual(
            result["freshness_status"],
            "latest_completed_session",
        )

    def test_post_close_prefers_qualified_canonical_daily_bar(self) -> None:
        checked_at = datetime(2026, 8, 14, 15, 20, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:00+08:00",
                "close": 24_450.0,
                "source": "fugle_indices_stream",
                "completed_daily_close": 24_456.78,
                "completed_daily_trade_date": "2026-08-14",
                "completed_daily_event_time": "2026-08-14T13:30:00+08:00",
                "completed_daily_source": "twse_mi_5mins_hist",
                "completed_daily_provider": "twse",
                "completed_daily_authority": "exchange",
                "completed_daily_finalization": "final",
                "completed_daily_official": True,
                "completed_daily_release_status": "released",
                "completed_daily_reconciliation_status": "not_applicable",
                "completed_daily_qualified": True,
            },
            calendar_status=_calendar(
                phase="post_close",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "completed_daily_bar")
        self.assertEqual(result["selected_value"], 24_456.78)
        self.assertEqual(result["selected_finalization"], "final")
        self.assertTrue(result["decision_usable"])

    def test_completed_daily_trade_date_mismatch_does_not_handoff(self) -> None:
        checked_at = datetime(2026, 8, 14, 15, 20, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:00+08:00",
                "close": 24_450.0,
                "source": "fugle_indices_stream",
                "completed_daily_close": 24_000.0,
                "completed_daily_trade_date": "2026-08-13",
                "completed_daily_event_time": "2026-08-13T13:30:00+08:00",
                "completed_daily_source": "twse_mi_5mins_hist",
                "completed_daily_provider": "twse",
                "completed_daily_authority": "exchange",
                "completed_daily_finalization": "final",
                "completed_daily_official": True,
                "completed_daily_release_status": "released",
                "completed_daily_reconciliation_status": "not_applicable",
                "completed_daily_qualified": True,
            },
            calendar_status=_calendar(
                phase="post_close",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["selected_candidate"], "index_summary")
        self.assertEqual(result["selected_value"], 24_450.0)
        self.assertFalse(result["decision_usable"])

    def test_post_close_exchange_shaped_source_is_not_confirmed_by_clock(self) -> None:
        checked_at = datetime(2026, 8, 14, 13, 34, tzinfo=TAIWAN_TZ)
        result = resolve_taiwan_index_quote_state(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:05+08:00",
                "close": 46_307.67,
                "source": "twse_index_5s_snapshot",
                "provider": "twse",
            },
            calendar_status=_calendar(
                phase="post_close",
                checked_at=checked_at,
            ),
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )

        self.assertEqual(result["official_close_status"], "pending")
        self.assertEqual(result["selected_candidate"], "index_summary")
        self.assertEqual(result["selected_finalization"], "provisional")
        self.assertFalse(result["official_close_confirmed"])
        self.assertFalse(result["decision_usable"])

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
            patch(
                "app.market.tw_current_market_operations."
                "build_current_market_executors",
            ) as live_reader,
        ):
            result = indices.get_market_index_intraday(
                "TAIEX",
                acquisition_policy="cache_only",
            )

        live_reader.assert_not_called()
        self.assertEqual(result["acquisition_policy"], "cache_only")
        self.assertEqual(result["acquisition_status"], "not_attempted")
        self.assertFalse(result["read_path_side_effects"])

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
        with patch(
            "app.market.tw_current_market_operations."
            "build_current_market_executors",
        ) as live_reader:
            result = indices.get_market_index_intraday(
                "TAIEX",
                acquisition_policy="require_live",
            )

        live_reader.assert_not_called()
        self.assertEqual(result["acquisition_policy"], "cache_only")
        self.assertEqual(result["requested_acquisition_policy"], "require_live")
        self.assertIn(
            "GET_ACQUISITION_POLICY_OVERRIDDEN_TO_CACHE_ONLY",
            result["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
