from __future__ import annotations

import unittest

from app.watchlists.radar_regime_v2 import (
    classify_instrument_regime,
    classify_market_regime,
    combined_regime_clarity,
    scoring_config_for_instrument_regime,
)
from app.watchlists.radar_rule_contract import (
    RADAR_V2_RULE_CONFIG,
    RADAR_V2_RULE_CONFIG_HASH,
    RADAR_V2_SCORING_CONFIG,
    config_hash,
)


class WatchlistRadarRegimeV2Tests(unittest.TestCase):
    def test_instrument_trend_up_and_down_are_distinct(self) -> None:
        common = {
            "atr": {"atr14": 3.0},
            "bollinger": {"bandwidth20_pct": 18.0},
        }
        up = classify_instrument_regime(
            indicator_snapshot={
                **common,
                "adx": {"adx14": 32.0, "plus_di14": 30.0, "minus_di14": 12.0},
            },
            signal_keys=[
                "above_ma20",
                "above_ma60",
                "ma20_above_ma60",
                "cross_above_ma20",
            ],
            close_price=100.0,
        )
        down = classify_instrument_regime(
            indicator_snapshot={
                **common,
                "adx": {"adx14": 32.0, "plus_di14": 12.0, "minus_di14": 30.0},
            },
            signal_keys=[
                "below_ma20",
                "below_ma60",
                "ma20_below_ma60",
                "cross_below_ma20",
            ],
            close_price=100.0,
        )

        self.assertEqual(up["instrument_regime"], "trend_up")
        self.assertEqual(down["instrument_regime"], "trend_down")
        self.assertGreater(up["instrument_regime_clarity"], 0.5)
        self.assertGreater(down["instrument_regime_clarity"], 0.5)

    def test_compression_precedes_ambiguous_trend(self) -> None:
        result = classify_instrument_regime(
            indicator_snapshot={
                "adx": {"adx14": 26.0, "plus_di14": 22.0, "minus_di14": 18.0},
                "atr": {"atr14": 1.5},
                "bollinger": {"bandwidth20_pct": 6.0},
            },
            signal_keys=["bollinger_squeeze", "above_ma20"],
            close_price=100.0,
        )

        self.assertEqual(result["instrument_regime"], "compression")
        self.assertEqual(result["volatility_state"], "normal")

    def test_high_volatility_is_overlay_not_forced_direction(self) -> None:
        result = classify_instrument_regime(
            indicator_snapshot={
                "adx": {"adx14": 21.0, "plus_di14": 20.0, "minus_di14": 19.0},
                "atr": {"atr14": 6.0},
                "bollinger": {"bandwidth20_pct": 20.0},
            },
            signal_keys=["atr_high_volatility"],
            close_price=100.0,
        )

        self.assertEqual(result["instrument_regime"], "transition")
        self.assertEqual(result["volatility_state"], "high")
        self.assertIn(
            "high_volatility_regime_overlay",
            {item["code"] for item in result["limitations"]},
        )

    def test_empty_instrument_inputs_are_insufficient(self) -> None:
        result = classify_instrument_regime(
            indicator_snapshot={},
            signal_keys=[],
        )

        self.assertEqual(result["instrument_regime"], "insufficient")
        self.assertEqual(result["instrument_regime_clarity"], 0)

    def test_market_regime_requires_ready_full_market_breadth(self) -> None:
        partial = classify_market_regime(
            market_snapshot={
                "quality_status": "partial",
                "breadth_status": "partial",
                "breadth_session_phase": "regular",
                "breadth_contract_version": "tw.market.breadth.v2",
                "breadth_decision_usable": False,
                "breadth_scope": "registered_universe",
                "advance_count": 800,
                "decline_count": 200,
                "total_count": 1000,
                "index_change_pct": 2.0,
            }
        )
        ready = classify_market_regime(
            market_snapshot={
                "quality_status": "ready",
                "breadth_status": "ready",
                "breadth_session_phase": "post_close",
                "breadth_contract_version": "tw.market.breadth.v2",
                "breadth_decision_usable": True,
                "breadth_scope": "full_market",
                "advance_count": 800,
                "decline_count": 200,
                "total_count": 1000,
                "unknown_count": 0,
                "missing_count": 0,
                "index_change_pct": 2.0,
                "index_above_ma20": True,
                "index_above_ma60": True,
            }
        )

        self.assertEqual(partial["market_regime"], "insufficient")
        self.assertEqual(partial["market_regime_clarity"], 0)
        self.assertEqual(ready["market_regime"], "risk_on")
        self.assertGreater(ready["market_regime_clarity"], 0.8)

    def test_market_regime_rejects_preopen_or_legacy_breadth(self) -> None:
        result = classify_market_regime(
            market_snapshot={
                "quality_status": "ready",
                "breadth_status": "pending",
                "breadth_session_phase": "preopen",
                "breadth_contract_version": "legacy_unverified",
                "breadth_decision_usable": False,
                "breadth_scope": "full_market",
                "advance_count": 900,
                "decline_count": 100,
                "total_count": 1000,
                "index_change_pct": 2.0,
            }
        )

        self.assertEqual(result["market_regime"], "insufficient")
        self.assertEqual(result["market_regime_clarity"], 0)
        codes = {item["code"] for item in result["limitations"]}
        self.assertIn("legacy_market_breadth_contract", codes)
        self.assertIn("market_breadth_regular_session_pending", codes)

    def test_instrument_and_market_regimes_remain_separate(self) -> None:
        instrument = classify_instrument_regime(
            indicator_snapshot={
                "adx": {"adx14": 30.0, "plus_di14": 28.0, "minus_di14": 14.0},
                "atr": {"atr14": 2.0},
                "bollinger": {"bandwidth20_pct": 16.0},
            },
            signal_keys=["above_ma20", "cross_above_ma20"],
            close_price=100.0,
        )
        market = classify_market_regime(
            market_snapshot={
                "quality_status": "ready",
                "breadth_status": "ready",
                "breadth_session_phase": "post_close",
                "breadth_contract_version": "tw.market.breadth.v2",
                "breadth_decision_usable": True,
                "breadth_scope": "full_market",
                "advance_count": 200,
                "decline_count": 800,
                "total_count": 1000,
                "index_change_pct": -2.0,
            }
        )

        self.assertEqual(instrument["instrument_regime"], "trend_up")
        self.assertEqual(market["market_regime"], "risk_off")
        combined = combined_regime_clarity(
            instrument_regime_clarity=instrument["instrument_regime_clarity"],
            market_regime_clarity=market["market_regime_clarity"],
        )
        self.assertLessEqual(
            combined,
            instrument["instrument_regime_clarity"],
        )

    def test_regime_weights_are_versioned_without_mutating_base_config(self) -> None:
        base_weight = RADAR_V2_SCORING_CONFIG["family_direction_weights"]["trend"]
        adjusted = scoring_config_for_instrument_regime("range")

        self.assertEqual(
            adjusted["family_direction_weights"]["trend"],
            base_weight * 0.75,
        )
        self.assertEqual(
            RADAR_V2_SCORING_CONFIG["family_direction_weights"]["trend"],
            base_weight,
        )
        self.assertEqual(
            config_hash(RADAR_V2_RULE_CONFIG),
            RADAR_V2_RULE_CONFIG_HASH,
        )


if __name__ == "__main__":
    unittest.main()
