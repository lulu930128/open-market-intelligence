from __future__ import annotations

from datetime import date, timedelta
import unittest
from unittest.mock import patch

from app.ai import evidence_builder, technical_analysis
from app.market.technical_evidence import (
    INDICATOR_ALGORITHM_VERSION,
    build_anchored_vwap,
    build_breakout_evidence,
    build_corporate_action_contract,
    build_divergence_evidence,
    build_fibonacci_evidence,
    build_relative_strength,
    build_swing_evidence,
    build_technical_structure_v2,
    build_volume_profile,
    calculate_canonical_indicator_points,
    classify_latest_period,
    indicator_method_catalog,
    _corporate_contract_for_points,
)
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market import technical_report


def _points(
    closes: list[float],
    *,
    start: date = date(2026, 1, 1),
    volumes: list[float] | None = None,
) -> list[dict[str, object]]:
    resolved_volumes = volumes or [1_000 + index * 10 for index in range(len(closes))]
    return [
        {
            "time": start + timedelta(days=index),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": resolved_volumes[index],
        }
        for index, close in enumerate(closes)
    ]


class TechnicalEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parameters = get_technical_analysis_parameters(persisted_settings={})

    def test_price_evidence_preserves_fractional_values_above_one_hundred(self) -> None:
        for value in (99.95, 100.5, 482.5, 505.5, 1_000.25):
            with self.subTest(value=value):
                self.assertEqual(technical_analysis._round_price(value), value)
                self.assertEqual(evidence_builder.round_price(value), value)

    def test_wilder_rsi_and_sma_seeded_ema_have_explicit_warmup(self) -> None:
        closes = [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
            46.03,
        ]
        calculated = calculate_canonical_indicator_points(
            _points(closes),
            parameters=self.parameters,
        )

        self.assertIsNone(calculated[13]["rsi"]["rsi14"])
        self.assertAlmostEqual(calculated[14]["rsi"]["rsi14"], 70.4641, places=4)
        self.assertIsNone(calculated[10]["ema"]["ema12"])
        self.assertIsNotNone(calculated[11]["ema"]["ema12"])
        self.assertEqual(calculated[-1]["algorithm_version"], INDICATOR_ALGORITHM_VERSION)
        self.assertEqual(calculated[-1]["price_basis"], "raw_unadjusted")
        self.assertEqual(calculated[-1]["calculation_role"], "backend_authoritative")
        self.assertEqual(calculated[-1]["parameter_contract"]["rsi_period"], 14)
        self.assertEqual(
            calculated[-1]["parameter_contract"]["ma_windows"],
            [5, 20, 60],
        )

    def test_indicator_catalog_discloses_method_parameters_and_warmup(self) -> None:
        methods = indicator_method_catalog(self.parameters)

        self.assertEqual(methods["rsi"]["method"], "wilder_smoothed_gain_loss")
        self.assertEqual(methods["ema_macd"]["method"], "ema_sma_seed")
        self.assertEqual(methods["kd"]["parameters"]["seed"], 50)
        self.assertEqual(methods["kd"]["parameters"]["smooth_period"], 3)
        self.assertEqual(methods["pvo"]["warmup_bars"], 34)

    def test_kdj_j_formula_is_unclamped_and_smoothing_is_configurable(self) -> None:
        points = _points([100, 101, 102, 103, 104, 105, 106, 107, 120, 130, 90, 80])
        smooth3 = calculate_canonical_indicator_points(
            points,
            parameters=get_technical_analysis_parameters(
                persisted_settings={"kd_smooth_period": 3},
            ),
        )[-1]["kd"]
        smooth5_parameters = get_technical_analysis_parameters(
            persisted_settings={"kd_smooth_period": 5},
        )
        smooth5 = calculate_canonical_indicator_points(
            points,
            parameters=smooth5_parameters,
        )[-1]["kd"]

        self.assertNotEqual(smooth3["k9"], smooth5["k9"])
        self.assertNotEqual(smooth3["d9"], smooth5["d9"])
        self.assertAlmostEqual(smooth5["j9"], 3 * smooth5["k9"] - 2 * smooth5["d9"], places=3)
        self.assertEqual(
            indicator_method_catalog(smooth5_parameters)["kd"]["parameters"]["smooth_period"],
            5,
        )

    def test_reference_vector_covers_macd_atr_adx_roc_mfi_bollinger_pvo_and_levels(self) -> None:
        parameters = get_technical_analysis_parameters(
            persisted_settings={
                "macd_fast_period": 2,
                "macd_slow_period": 3,
                "macd_signal_period": 2,
                "pvo_fast_period": 2,
                "pvo_slow_period": 3,
                "pvo_signal_period": 2,
                "atr_period": 3,
                "adx_period": 3,
                "roc_period": 3,
                "mfi_period": 3,
                "donchian_period": 3,
                "bollinger_period": 3,
                "bollinger_std_dev": 2,
                "support_resistance_period": 3,
            },
        )
        points = _points(
            [10, 11, 12, 13, 14, 15],
            volumes=[100, 200, 300, 400, 500, 600],
        )
        calculated = calculate_canonical_indicator_points(
            points,
            parameters=parameters,
        )
        latest = calculated[-1]

        self.assertEqual(latest["ema"], {"ema2": 14.5, "ema3": 14.0})
        self.assertEqual(latest["macd"], {"macd": 0.5, "signal": 0.5, "histogram": 0.0})
        self.assertEqual(latest["atr"]["atr3"], 2.0)
        self.assertEqual(latest["adx"]["plus_di3"], 50.0)
        self.assertEqual(latest["adx"]["minus_di3"], 0.0)
        self.assertEqual(latest["adx"]["adx3"], 100.0)
        self.assertEqual(latest["roc"]["roc3"], 25.0)
        self.assertEqual(latest["mfi"]["mfi3"], 100.0)
        self.assertEqual(latest["donchian"]["upper3"], 16.0)
        self.assertEqual(latest["donchian"]["lower3"], 12.0)
        self.assertAlmostEqual(latest["bollinger"]["middle3"], 14.0, places=4)
        self.assertAlmostEqual(latest["bollinger"]["upper3"], 15.633, places=3)
        self.assertAlmostEqual(latest["bollinger"]["lower3"], 12.367, places=3)
        self.assertEqual(latest["support_resistance"]["support3"], 11.0)
        self.assertEqual(latest["support_resistance"]["resistance3"], 15.0)
        self.assertEqual(latest["pvo"]["pvo"], 10.0)
        self.assertAlmostEqual(latest["pvo"]["signal"], 11.7593, places=4)
        self.assertAlmostEqual(latest["pvo"]["histogram"], -1.7593, places=4)

    def test_divergence_uses_configured_rsi_key(self) -> None:
        parameters = get_technical_analysis_parameters(
            persisted_settings={"rsi_period": 10},
        )
        swings = {
            "pivots": [
                {"type": "low", "price": 100, "pivot_index": 0, "evidence_id": "low-1"},
                {"type": "low", "price": 90, "pivot_index": 1, "evidence_id": "low-2"},
            ]
        }
        result = build_divergence_evidence(
            swings,
            [{"rsi": {"rsi10": 30}}, {"rsi": {"rsi10": 40}}],
            parameters=parameters,
        )

        self.assertEqual(result["divergences"][0]["indicator"], "rsi10")

    def test_recent_capability_coverage_is_not_downgraded_by_old_history(self) -> None:
        points = _points([100 + index for index in range(100)])
        history = {
            "cache_status": "current",
            "coverage_start": points[-40]["time"],
            "coverage_end": points[-1]["time"],
            "results": [],
        }

        full = _corporate_contract_for_points(history, points)
        recent = _corporate_contract_for_points(history, points, lookback_bars=34)

        self.assertEqual(full["coverage_status"], "partial")
        self.assertEqual(recent["coverage_status"], "complete")
        self.assertEqual(recent["relevant_analysis_start"], points[-34]["time"].isoformat())

    def test_current_week_and_month_are_not_mislabeled_completed(self) -> None:
        points = _points([100, 101, 102], start=date(2026, 8, 10))

        weekly = classify_latest_period(points, timeframe="weekly")
        monthly = classify_latest_period(points, timeframe="monthly")
        daily = classify_latest_period(points, timeframe="daily")

        self.assertEqual(weekly["status"], "current_partial")
        self.assertEqual(monthly["status"], "current_partial")
        self.assertEqual(daily["status"], "completed")

    def test_aggregated_report_selects_previous_completed_indicator(self) -> None:
        weekly_points = _points(
            [100 + index for index in range(70)],
            start=date(2025, 4, 14),
        )
        for index, point in enumerate(weekly_points):
            point["time"] = date(2025, 4, 14) + timedelta(weeks=index)
        chart = {
            "points": weekly_points,
            "point_count": len(weekly_points),
            "latest_data_date": date(2026, 8, 12),
        }

        with patch.object(
            technical_report.market_service,
            "list_stock_ohlc_chart_data",
            return_value=chart,
        ):
            completed, resolved_chart = technical_report._aggregated_indicator(
                db=object(),
                stock_id="2408",
                timeframe="weekly",
                parameters=self.parameters,
            )

        self.assertEqual(resolved_chart["period"]["status"], "current_partial")
        self.assertEqual(completed["time"], weekly_points[-2]["time"])
        self.assertEqual(
            resolved_chart["current_partial_indicator"]["time"],
            weekly_points[-1]["time"],
        )

    def test_corporate_action_contract_never_claims_unknown_adjustment(self) -> None:
        history = {
            "cache_status": "current",
            "coverage_start": "2026-01-01",
            "coverage_end": "2026-12-31",
            "results": [
                {
                    "event_id": "exd-1",
                    "event_type": "ex_dividend",
                    "start_date": "2026-08-12",
                    "cash_dividend": 3.0,
                    "source_name": "TWSE",
                }
            ],
        }

        contract = build_corporate_action_contract(
            history,
            analysis_start=date(2026, 1, 2),
            analysis_end=date(2026, 8, 12),
        )

        self.assertEqual(contract["coverage_status"], "complete")
        self.assertEqual(contract["price_basis"], "raw_unadjusted")
        self.assertFalse(contract["adjustment_applied"])
        self.assertEqual(contract["affected_dates"], ["2026-08-12"])

    def test_swing_confirmation_requires_right_hand_observations(self) -> None:
        points = _points([10, 11, 15, 11, 10, 12, 9])

        before_confirmation = build_swing_evidence(points[:4])
        after_confirmation = build_swing_evidence(points[:5])

        self.assertFalse(any(item["pivot_time"] == "2026-01-03" for item in before_confirmation["pivots"]))
        confirmed = next(item for item in after_confirmation["pivots"] if item["pivot_time"] == "2026-01-03")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["confirmed_at"], "2026-01-05")

    def test_fibonacci_levels_trace_to_confirmed_swing_ids(self) -> None:
        swings = {
            "pivots": [
                {"evidence_id": "low-1", "type": "low", "price": 100.0, "status": "confirmed"},
                {"evidence_id": "high-1", "type": "high", "price": 200.0, "status": "confirmed"},
            ]
        }

        evidence = build_fibonacci_evidence(swings)

        self.assertEqual(evidence["status"], "ready")
        self.assertEqual(evidence["anchor_ids"], ["low-1", "high-1"])
        self.assertEqual(evidence["levels"][0]["price_basis"], "raw_unadjusted")
        self.assertAlmostEqual(
            next(item["price"] for item in evidence["levels"] if item["ratio"] == 0.5),
            150.0,
        )

    def test_same_bar_pierce_and_close_below_is_rejected_attempt(self) -> None:
        points = _points([490, 495, 482.5])
        points[-1].update({"high": 511.0, "low": 480.5, "volume": 1_500})
        canonical = [{}, {}, {"support_resistance": {}, "volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": 8.0}}]

        evidence = build_breakout_evidence(
            points,
            canonical,
            corporate_action_contract={"affected_dates": []},
            level=505.0,
        )

        self.assertEqual(evidence["state"], "rejected_attempt")
        self.assertTrue(evidence["wick_rejected"])
        self.assertEqual(evidence["close"], 482.5)

    def test_breakout_confirmation_states_use_declared_thresholds(self) -> None:
        points = _points([490, 510], volumes=[900, 1_300])
        canonical = [
            {},
            {"volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": 2.0}},
        ]

        confirmed = build_breakout_evidence(
            points,
            canonical,
            corporate_action_contract={"coverage_status": "complete", "affected_dates": []},
            level=505.0,
            parameters=self.parameters,
        )
        weak = build_breakout_evidence(
            points,
            [canonical[0], {"volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": -1.0}}],
            corporate_action_contract={"coverage_status": "complete", "affected_dates": []},
            level=505.0,
            parameters=self.parameters,
        )

        self.assertEqual(confirmed["state"], "confirmed")
        self.assertEqual(weak["state"], "weak_confirmation")
        self.assertEqual(confirmed["parameters"]["volume_ratio_threshold"], 1.2)
        self.assertIsNotNone(confirmed["breakout_event_id"])

    def test_breakout_frozen_level_reaches_retest_failed_and_continuation(self) -> None:
        base_canonical = [
            {},
            {"volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": 2.0}},
            {"volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": 2.0}},
        ]
        cases = [
            (506.0, 504.0, "retest_held"),
            (500.0, 498.0, "failed"),
            (515.0, 508.0, "continuation"),
        ]

        for close, low, expected in cases:
            with self.subTest(expected=expected):
                points = _points([490, 510, close], volumes=[900, 1_300, 1_100])
                points[-1]["low"] = low
                evidence = build_breakout_evidence(
                    points,
                    base_canonical,
                    corporate_action_contract={"coverage_status": "complete", "affected_dates": []},
                    level=505.0,
                    parameters=self.parameters,
                )

                self.assertEqual(evidence["state"], expected)
                self.assertEqual(evidence["breakout_level"], 505.0)
                self.assertEqual(evidence["breakout_confirmed_at"], "2026-01-02")

    def test_breakout_inside_range_is_reachable(self) -> None:
        evidence = build_breakout_evidence(
            _points([490, 500]),
            [{}, {}],
            corporate_action_contract={"coverage_status": "complete", "affected_dates": []},
            level=505.0,
            parameters=self.parameters,
        )

        self.assertEqual(evidence["state"], "inside_range")

    def test_known_corporate_action_window_suppresses_breakout(self) -> None:
        points = _points([490, 495, 510])
        canonical = [{}, {}, {"support_resistance": {}, "volume_ma": {"volume_ma20": 1_000}, "pvo": {"pvo": 8.0}}]

        evidence = build_breakout_evidence(
            points,
            canonical,
            corporate_action_contract={"affected_dates": ["2026-01-03"]},
            level=505.0,
        )

        self.assertEqual(evidence["state"], "suppressed_corporate_action_window")
        self.assertFalse(evidence["decision_usable"])

    def test_volume_profile_has_ordered_value_area(self) -> None:
        evidence = build_volume_profile(_points([100 + index * 0.5 for index in range(60)]))

        self.assertEqual(evidence["status"], "partial")
        self.assertLessEqual(evidence["val"], evidence["poc"])
        self.assertLessEqual(evidence["poc"], evidence["vah"])
        self.assertEqual(evidence["source_granularity"], "daily_ohlcv")

    def test_anchored_vwap_uses_confirmed_swing_anchor(self) -> None:
        points = _points([100, 105, 110], volumes=[1, 2, 3])
        swings = {
            "pivots": [
                {
                    "evidence_id": "swing:low:1",
                    "type": "low",
                    "price": 99.0,
                    "pivot_time": "2026-01-01",
                    "pivot_index": 0,
                    "status": "confirmed",
                }
            ]
        }

        evidence = build_anchored_vwap(points, swings)

        self.assertEqual(evidence["anchor_evidence_id"], "swing:low:1")
        self.assertAlmostEqual(evidence["value"], (100 * 1 + 105 * 2 + 110 * 3) / 6, places=4)
        self.assertIn("not an official intraday VWAP", evidence["limitations"][0])

    def test_relative_strength_is_excess_price_return_not_rsi(self) -> None:
        stock = _points([100 + index for index in range(70)])
        benchmark = [
            {"time": point["time"], "close": 100 + index * 0.5}
            for index, point in enumerate(stock)
        ]

        evidence = build_relative_strength(stock, benchmark)

        self.assertEqual(evidence["status"], "ready")
        self.assertEqual(evidence["benchmark"], "TAIEX")
        self.assertGreater(evidence["horizons"]["60d"]["excess_return_pct"], 0)
        self.assertIn("not RSI", evidence["limitations"][0])

    def test_structure_v2_is_shadow_only_and_exposes_counter_evidence(self) -> None:
        indicators = {
            "status": "ready",
            "as_of": "2026-08-12",
            "price_basis": "raw_unadjusted",
            "corporate_action": {"coverage_status": "complete"},
            "warnings": [],
            "timeframes": {
                "daily": {
                    "decision_snapshot": "completed",
                    "period": {"status": "completed"},
                    "completed": {
                        "close": 482.5,
                        "rsi": {"rsi14": 82.0},
                        "macd": {"histogram": -2.0},
                        "pvo": {"pvo": -4.0},
                        "atr": {"atr14": 12.0},
                        "bollinger": {},
                        "support_resistance": {"support20": 470.5, "resistance20": 505.0},
                    },
                }
            },
        }

        result = build_technical_structure_v2(
            indicators=indicators,
            swings={"confirmed_count": 0, "pivots": [], "provisional": []},
            fibonacci={"status": "missing", "levels": []},
            divergence={"divergences": []},
            breakout={"state": "rejected_attempt", "level": 505.0},
            volume_profile={"poc": 490.0, "val": 475.0, "vah": 500.0, "confidence": "low", "source_granularity": "daily_ohlcv"},
            anchored_vwap={"value": None},
            relative_strength={"benchmark": "TAIEX", "horizons": {}, "sector": {"status": "not_available"}},
            parameters=self.parameters,
        )

        self.assertEqual(result["version"], "tw_technical_current_state_v2")
        self.assertEqual(result["mode"], "shadow")
        self.assertFalse(result["active_score_impact"])
        self.assertTrue(result["decision_usable"])
        self.assertEqual(result["levels"]["support"], 470.5)
        self.assertEqual(
            {item["evidence"] for item in result["counter_evidence"]},
            {"negative_macd_histogram", "rsi_overheated", "rejected_attempt"},
        )

    def test_structure_v2_downgrades_incomplete_corporate_action_coverage(self) -> None:
        result = build_technical_structure_v2(
            indicators={
                "status": "partial",
                "as_of": "2026-08-12",
                "price_basis": "raw_unadjusted",
                "corporate_action": {"coverage_status": "partial"},
                "warnings": ["Corporate-action coverage is incomplete."],
                "timeframes": {
                    "daily": {
                        "decision_snapshot": "completed",
                        "period": {"status": "completed"},
                        "completed": {"close": 482.5},
                    }
                },
            },
            swings={"confirmed_count": 0, "pivots": [], "provisional": []},
            fibonacci={"status": "missing", "levels": []},
            divergence={"divergences": []},
            breakout={"state": "rejected_attempt", "level": 502.0},
            volume_profile={},
            anchored_vwap={},
            relative_strength={},
            parameters=self.parameters,
        )

        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["decision_usable"])


if __name__ == "__main__":
    unittest.main()
