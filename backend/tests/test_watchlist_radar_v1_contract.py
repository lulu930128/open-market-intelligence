from __future__ import annotations

import unittest

from app.watchlists import radar_outcome_service, radar_service
from app.watchlists.radar_rule_contract import (
    RADAR_V1_CONFIG_HASH,
    RADAR_V1_FROZEN_AT,
    RADAR_V1_LIFECYCLE,
    RADAR_V1_RULE_VERSION,
    RADAR_V1_WRITE_ENABLED,
    V1_BUCKET_PRIORITY_BASES,
    V1_HIGH_MOVE_PCT_THRESHOLD,
    V1_TECHNICAL_SIGNAL_WEIGHTS,
    config_hash,
)


class WatchlistRadarV1ContractTests(unittest.TestCase):
    def test_v1_contract_hash_is_frozen(self) -> None:
        self.assertEqual(RADAR_V1_RULE_VERSION, "radar_v1.0")
        self.assertEqual(
            RADAR_V1_CONFIG_HASH,
            "57527dc8ece6383e70646687f29a8752c93b4a1e1c4c46ccc7bc85905a95b57c",
        )
        self.assertEqual(
            config_hash({"b": 2, "a": 1}),
            config_hash({"a": 1, "b": 2}),
        )
        self.assertEqual(RADAR_V1_LIFECYCLE["status"], "frozen")
        self.assertEqual(RADAR_V1_FROZEN_AT, "2026-08-01")
        self.assertFalse(RADAR_V1_WRITE_ENABLED)

    def test_v1_runtime_uses_frozen_weight_and_priority_contract(self) -> None:
        self.assertIs(radar_service.TECHNICAL_SIGNAL_WEIGHTS, V1_TECHNICAL_SIGNAL_WEIGHTS)
        self.assertEqual(
            radar_service.HIGH_MOVE_PCT_THRESHOLD,
            V1_HIGH_MOVE_PCT_THRESHOLD,
        )
        self.assertEqual(V1_BUCKET_PRIORITY_BASES["selloff_risk"], 102)
        self.assertEqual(V1_TECHNICAL_SIGNAL_WEIGHTS["cross_below_ma60"], 4.2)
        self.assertEqual(V1_TECHNICAL_SIGNAL_WEIGHTS["cross_above_ma60"], 3.8)

    def test_v1_bucket_precedence_keeps_large_selloff_above_support_break(self) -> None:
        bucket, matched = radar_service._bucket_for_row(
            {
                "status": "ok",
                "change_pct": -7.2,
                "limit_status": None,
                "score": -5,
                "signal_keys": [
                    "structure_support_break",
                    "atr_expanding",
                ],
            }
        )

        self.assertEqual(bucket, "selloff_risk")
        self.assertIn("structure_support_break", matched)

    def test_v1_bucket_precedence_keeps_support_break_above_overheat(self) -> None:
        bucket, matched = radar_service._bucket_for_row(
            {
                "status": "ok",
                "change_pct": -1.0,
                "limit_status": None,
                "score": -3,
                "signal_keys": [
                    "rsi_overheated",
                    "structure_support_break",
                ],
            }
        )

        self.assertEqual(bucket, "support_break")
        self.assertEqual(matched, ["structure_support_break"])

    def test_v1_priority_formula_is_frozen_for_known_risk_row(self) -> None:
        priority = radar_service._priority_score(
            row={
                "change_pct": -7.2,
                "score": -5,
                "signal_count": 4,
            },
            bucket="selloff_risk",
            urgency="high",
            stale=False,
            technical_evidence_score=10.0,
            context_score=1.0,
        )

        self.assertAlmostEqual(priority, 175.4)

    def test_v1_risk_hit_preserves_intraday_trigger_even_after_strong_close(self) -> None:
        status, _reason = radar_outcome_service._outcome_status(
            bucket="selloff_risk",
            close_return_pct=6.78,
            max_favorable_pct=9.76,
            max_adverse_pct=-5.15,
            intraday_range_pct=14.91,
        )

        self.assertEqual(status, "hit")

    def test_v1_momentum_hit_is_evaluated_before_adverse_miss(self) -> None:
        status, _reason = radar_outcome_service._outcome_status(
            bucket="breakout_high",
            close_return_pct=-3.0,
            max_favorable_pct=2.2,
            max_adverse_pct=-5.0,
            intraday_range_pct=7.2,
        )

        self.assertEqual(status, "hit")

    def test_v1_structure_watch_uses_absolute_move_or_range(self) -> None:
        status, _reason = radar_outcome_service._outcome_status(
            bucket="compression_watch",
            close_return_pct=0.5,
            max_favorable_pct=1.8,
            max_adverse_pct=-1.5,
            intraday_range_pct=3.3,
        )

        self.assertEqual(status, "hit")

    def test_v2_bundle_keeps_rows_beyond_v1_top_n_projection(self) -> None:
        ranking = {
            "group_id": 7,
            "target_trade_date": "2026-07-29",
            "results": [
                {
                    "rank": index,
                    "stock_id": stock_id,
                    "stock_name": stock_id,
                    "time": "2026-07-29",
                    "status": "ok",
                    "score": 3,
                    "change_pct": 1.0,
                    "close": 100.0 + index,
                    "previous_close": 100.0,
                    "signal_count": 1,
                    "signal_keys": ["donchian_breakout"],
                }
                for index, stock_id in enumerate(
                    ("2330", "2317", "2454"),
                    start=1,
                )
            ],
        }

        radar, universe = radar_service.build_watchlist_radar_bundle_from_ranking(
            ranking=ranking,
            mode="action",
            max_results=1,
        )

        self.assertEqual(len(radar["results"]), 1)
        self.assertEqual(len(universe), 3)
        self.assertEqual(
            {row["stock_id"] for row in universe},
            {"2330", "2317", "2454"},
        )


if __name__ == "__main__":
    unittest.main()
