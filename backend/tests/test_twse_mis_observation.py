from __future__ import annotations

from datetime import datetime
import unittest

from app.market.trading_calendar import TAIWAN_TZ, taiwan_presentation_session
from app.market.twse_mis_observation import (
    resolve_twse_mis_actual_trade,
    resolve_twse_mis_observation,
)


class TaiwanPresentationSessionTests(unittest.TestCase):
    def test_trading_day_rolls_to_today_at_0800(self) -> None:
        before = taiwan_presentation_session(
            datetime(2026, 8, 5, 7, 59, 59, tzinfo=TAIWAN_TZ)
        )
        rollover = taiwan_presentation_session(
            datetime(2026, 8, 5, 8, 0, 0, tzinfo=TAIWAN_TZ)
        )
        pending = taiwan_presentation_session(
            datetime(2026, 8, 5, 8, 29, 59, tzinfo=TAIWAN_TZ)
        )
        observing = taiwan_presentation_session(
            datetime(2026, 8, 5, 8, 30, 0, tzinfo=TAIWAN_TZ)
        )

        self.assertEqual(before["trade_date"].isoformat(), "2026-08-04")
        self.assertEqual(before["state"], "previous_session")
        self.assertEqual(
            before["next_transition_at"].isoformat(),
            "2026-08-05T08:00:00+08:00",
        )
        self.assertEqual(rollover["trade_date"].isoformat(), "2026-08-05")
        self.assertEqual(rollover["state"], "today_pending")
        self.assertEqual(pending["trade_date"].isoformat(), "2026-08-05")
        self.assertEqual(pending["state"], "today_pending")
        self.assertEqual(observing["state"], "observing")

    def test_non_trading_day_does_not_roll_to_false_today_session(self) -> None:
        result = taiwan_presentation_session(
            datetime(2026, 8, 8, 8, 0, 0, tzinfo=TAIWAN_TZ)
        )

        self.assertEqual(result["trade_date"].isoformat(), "2026-08-07")
        self.assertEqual(result["state"], "previous_session")
        self.assertFalse(result["is_current_trading_day"])
        self.assertEqual(
            result["next_transition_at"].isoformat(),
            "2026-08-10T08:00:00+08:00",
        )


class TwseMisObservationTests(unittest.TestCase):
    def test_actual_trade_requires_z_and_positive_volume_evidence(self) -> None:
        available = resolve_twse_mis_actual_trade(
            expected_trade_date="2026-08-05",
            observation_trade_date="20260805",
            provider_event_time=datetime(2026, 8, 5, 9, 5, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            last_trade_price=2400.0,
            last_trade_volume_lots=None,
            cumulative_volume_lots=3141,
        )
        missing_price = resolve_twse_mis_actual_trade(
            expected_trade_date="2026-08-05",
            observation_trade_date="20260805",
            provider_event_time=datetime(2026, 8, 5, 9, 5, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            last_trade_price=None,
            last_trade_volume_lots=5,
            cumulative_volume_lots=3141,
        )
        missing_volume = resolve_twse_mis_actual_trade(
            expected_trade_date="2026-08-05",
            observation_trade_date="20260805",
            provider_event_time=datetime(2026, 8, 5, 9, 5, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            last_trade_price=2400.0,
            last_trade_volume_lots=0,
            cumulative_volume_lots=0,
        )

        self.assertTrue(available["actual_trade_price_available"])
        self.assertEqual(available["actual_trade_price_source"], "twse_mis_snapshot_z")
        self.assertEqual(available["volume_evidence_fields"], ["v"])
        self.assertFalse(missing_price["actual_trade_price_available"])
        self.assertEqual(missing_price["reason_code"], "ACTUAL_TRADE_PRICE_MISSING")
        self.assertFalse(missing_volume["actual_trade_occurred"])
        self.assertEqual(missing_volume["reason_code"], "ACTUAL_TRADE_EVIDENCE_MISSING")

    def test_actual_trade_rejects_trial_and_trade_date_mismatch(self) -> None:
        trial = resolve_twse_mis_actual_trade(
            expected_trade_date="2026-08-05",
            observation_trade_date="20260805",
            provider_event_time=datetime(2026, 8, 5, 8, 59, 55, tzinfo=TAIWAN_TZ),
            trial_status="1",
            last_trade_price=2385.0,
            last_trade_volume_lots=5,
            cumulative_volume_lots=3141,
        )
        mismatch = resolve_twse_mis_actual_trade(
            expected_trade_date="2026-08-05",
            observation_trade_date="20260804",
            provider_event_time=datetime(2026, 8, 4, 13, 30, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            last_trade_price=2405.0,
            last_trade_volume_lots=5,
            cumulative_volume_lots=50_000,
        )

        self.assertFalse(trial["actual_trade_price_available"])
        self.assertEqual(trial["reason_code"], "AUCTION_INDICATIVE_ONLY")
        self.assertFalse(mismatch["actual_trade_price_available"])
        self.assertEqual(mismatch["reason_code"], "OBSERVATION_TRADE_DATE_MISMATCH")

    def test_0900_request_keeps_085955_trial_observation_in_auction(self) -> None:
        result = resolve_twse_mis_observation(
            request_now=datetime(2026, 8, 5, 9, 0, 0, tzinfo=TAIWAN_TZ),
            market_calendar_phase="regular",
            legacy_clock_phase="regular_live",
            provider_event_time=datetime(
                2026, 8, 5, 8, 59, 55, tzinfo=TAIWAN_TZ
            ),
            trial_status="1",
            indicative_price=2385.0,
            indicative_volume_lots=2113,
            last_trade_price=None,
            cumulative_volume_lots=0,
        )

        self.assertEqual(result["market_calendar_phase"], "regular")
        self.assertEqual(result["instrument_phase"], "preopen_auction")
        self.assertEqual(result["legacy_session_phase"], "preopen_auction")
        self.assertTrue(result["auction_applicable"])
        self.assertFalse(result["actual_trade_occurred"])

    def test_trial_observation_after_0900_is_delayed_opening_auction(self) -> None:
        result = resolve_twse_mis_observation(
            request_now=datetime(2026, 8, 5, 9, 1, 0, tzinfo=TAIWAN_TZ),
            market_calendar_phase="regular",
            legacy_clock_phase="regular_live",
            provider_event_time=datetime(2026, 8, 5, 9, 1, 0, tzinfo=TAIWAN_TZ),
            trial_status="1",
            indicative_price=2385.0,
            indicative_volume_lots=2500,
            last_trade_price=None,
            cumulative_volume_lots=0,
        )

        self.assertEqual(result["instrument_phase"], "opening_auction_delayed")
        self.assertEqual(result["legacy_session_phase"], "preopen_auction")
        self.assertTrue(result["auction_applicable"])

    def test_positive_volume_without_z_is_trade_occurred_price_missing(self) -> None:
        result = resolve_twse_mis_observation(
            request_now=datetime(2026, 8, 5, 9, 5, 0, tzinfo=TAIWAN_TZ),
            market_calendar_phase="regular",
            legacy_clock_phase="regular_live",
            provider_event_time=datetime(2026, 8, 5, 9, 5, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            indicative_price=None,
            indicative_volume_lots=None,
            last_trade_price=None,
            cumulative_volume_lots=3141,
        )

        self.assertEqual(result["instrument_phase"], "regular_traded")
        self.assertTrue(result["actual_trade_occurred"])
        self.assertFalse(result["actual_trade_price_available"])
        self.assertEqual(result["reason_code"], "ACTUAL_TRADE_PRICE_MISSING")

    def test_trial_observation_is_rejected_during_close_resolution(self) -> None:
        result = resolve_twse_mis_observation(
            request_now=datetime(2026, 8, 5, 13, 31, 0, tzinfo=TAIWAN_TZ),
            market_calendar_phase="close_resolution",
            legacy_clock_phase="close_resolution",
            provider_event_time=datetime(2026, 8, 5, 13, 31, 0, tzinfo=TAIWAN_TZ),
            trial_status="1",
            indicative_price=2410.0,
            indicative_volume_lots=3815,
            last_trade_price=None,
            cumulative_volume_lots=27545,
        )

        self.assertEqual(result["instrument_phase"], "close_resolution")
        self.assertEqual(result["legacy_session_phase"], "close_resolution")
        self.assertFalse(result["auction_applicable"])
        self.assertFalse(result["session_final_candidate"])
        self.assertEqual(result["session_final_reason_code"], "TRIAL_OBSERVATION")

    def test_actual_trade_is_explicit_session_final_candidate(self) -> None:
        result = resolve_twse_mis_observation(
            request_now=datetime(2026, 8, 5, 13, 31, 0, tzinfo=TAIWAN_TZ),
            market_calendar_phase="close_resolution",
            legacy_clock_phase="close_resolution",
            provider_event_time=datetime(2026, 8, 5, 13, 30, 0, tzinfo=TAIWAN_TZ),
            trial_status="0",
            indicative_price=None,
            indicative_volume_lots=None,
            last_trade_price=2410.0,
            cumulative_volume_lots=27545,
        )

        self.assertEqual(result["instrument_phase"], "close_resolution")
        self.assertTrue(result["session_final_candidate"])
        self.assertEqual(
            result["session_final_reason_code"],
            "VALID_CURRENT_SESSION_ACTUAL_TRADE",
        )


if __name__ == "__main__":
    unittest.main()
