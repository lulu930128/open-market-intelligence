from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RadarEvaluationEventLink,
    RadarFeatureSnapshot,
    RadarOutcomeEventLink,
    RadarOutcomePath,
    RadarRuleEvaluation,
    RadarSignalEvent,
    RadarUniverseObservation,
    RadarWatchlistProjection,
    TaiwanMarketMinuteState,
    WatchlistGroup,
)
from app.watchlists.radar_shadow_v2_service import (
    attach_radar_v2_shadow,
    latest_market_regime_snapshot,
    persist_radar_v2_shadow,
    radar_v2_shadow_enabled,
)
from app.watchlists.radar_outcome_v2_service import evaluate_radar_outcome_v2
from app.routers.watchlists import (
    persist_watchlist_group_radar_v2_shadow,
    router as watchlists_router,
)


UTC = timezone.utc


def _radar_payload() -> dict:
    return {
        "group_id": 7,
        "include_children": True,
        "mode": "action",
        "max_results": 30,
        "trade_date": date(2026, 7, 29),
        "target_trade_date": date(2026, 7, 29),
        "results": [
            {
                "rank": 1,
                "source_rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "bucket": "breakout_high",
                "direction": "bullish",
                "urgency": "high",
                "priority_score": 90.0,
                "trade_date": date(2026, 7, 29),
                "time": "2026-07-29",
                "close": 1100.0,
                "previous_close": 1080.0,
                "volume": 50_000_000,
                "status": "bullish",
                "stale": False,
                "signal_keys": [
                    "donchian_breakout",
                    "structure_resistance_breakout",
                    "above_ma20",
                    "above_ma60",
                    "macd_positive",
                    "volume_price_up",
                ],
                "indicator_snapshot": {
                    "ma": {"ma20": 1040.0, "ma60": 990.0},
                    "volume_ma": {"volume_ma5": 40_000_000.0},
                    "ema": {"ema12": 1070.0, "ema26": 1030.0},
                    "macd": {"histogram": 5.0},
                    "rsi": {"rsi14": 62.0},
                    "atr": {"atr14": 25.0},
                    "adx": {
                        "adx14": 31.0,
                        "plus_di14": 29.0,
                        "minus_di14": 14.0,
                    },
                    "roc": {"roc12": 8.0},
                    "mfi": {"mfi14": 68.0},
                    "donchian": {"upper20": 1090.0, "lower20": 950.0},
                    "bollinger": {
                        "upper20": 1085.0,
                        "lower20": 980.0,
                        "bandwidth20_pct": 12.0,
                    },
                },
                "context_snapshot": {},
                "context_signals": [],
                "context_score": 0.0,
            },
            {
                "rank": 2,
                "source_rank": 2,
                "stock_id": "2317",
                "stock_name": "鴻海",
                "bucket": "bearish_momentum",
                "direction": "bearish",
                "urgency": "medium",
                "priority_score": 70.0,
                "trade_date": date(2026, 7, 29),
                "time": "2026-07-29",
                "close": 150.0,
                "previous_close": 153.0,
                "volume": 20_000_000,
                "status": "bearish",
                "stale": False,
                "signal_keys": [
                    "above_ma20",
                    "above_ma60",
                    "macd_negative",
                    "roc_negative",
                    "rsi_weak",
                ],
                "indicator_snapshot": {
                    "ma": {"ma20": 148.0, "ma60": 142.0},
                    "volume_ma": {"volume_ma5": 18_000_000.0},
                    "ema": {"ema12": 149.0, "ema26": 150.0},
                    "macd": {"histogram": -1.0},
                    "rsi": {"rsi14": 38.0},
                    "atr": {"atr14": 4.0},
                    "adx": {
                        "adx14": 23.0,
                        "plus_di14": 18.0,
                        "minus_di14": 20.0,
                    },
                    "roc": {"roc12": -3.0},
                    "mfi": {"mfi14": 45.0},
                    "donchian": {"upper20": 158.0, "lower20": 140.0},
                    "bollinger": {
                        "upper20": 159.0,
                        "lower20": 141.0,
                        "bandwidth20_pct": 12.0,
                    },
                },
                "context_snapshot": {},
                "context_signals": [],
                "context_score": 0.0,
            },
        ],
    }


class WatchlistRadarShadowV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_attach_keeps_v1_order_and_exposes_shadow_contract(self) -> None:
        source = _radar_payload()
        result = attach_radar_v2_shadow(
            radar=source,
            market_snapshot={
                "quality_status": "ready",
                "breadth_scope": "full_market",
                "advance_count": 800,
                "decline_count": 200,
                "total_count": 1000,
                "index_change_pct": 1.8,
            },
        )

        self.assertEqual(
            [item["stock_id"] for item in result["results"]],
            ["2330", "2317"],
        )
        self.assertNotIn("radar_v2", source["results"][0])
        self.assertEqual(
            result["radar_engine"]["active_version"],
            "radar_v1.0",
        )
        self.assertEqual(
            result["radar_engine"]["shadow_version"],
            "radar_v2.0-shadow",
        )
        self.assertEqual(
            result["results"][0]["radar_v2"]["market_regime"],
            "risk_on",
        )
        self.assertGreater(
            result["results"][1]["radar_v2"][
                "cross_family_conflict_score"
            ],
            0,
        )
        contributions = result["results"][0]["radar_v2"][
            "signal_contributions"
        ]
        self.assertTrue(
            any(0 < float(row["strength"]) < 1 for row in contributions)
        )
        self.assertNotEqual(
            result["results"][0]["radar_v2"]["feature_config_hash"],
            result["results"][0]["radar_v2"]["rule_config_hash"],
        )

    def test_attach_evaluates_complete_universe_before_public_projection(
        self,
    ) -> None:
        source = _radar_payload()
        third = deepcopy(source["results"][1])
        third.update(
            {
                "rank": 3,
                "source_rank": 3,
                "stock_id": "2454",
                "stock_name": "聯發科",
            }
        )

        result = attach_radar_v2_shadow(
            radar=source,
            universe_items=[*source["results"], third],
        )

        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(len(result["_radar_v2_universe"]), 3)
        self.assertEqual(
            result["radar_v2_summary"]["universe_evaluated_count"],
            3,
        )
        self.assertEqual(
            result["radar_v2_summary"]["universe_scope"],
            "complete_calculation_universe",
        )

    def test_shadow_persist_route_is_explicit_post(self) -> None:
        matching = [
            route
            for route in watchlists_router.routes
            if getattr(route, "path", "")
            == "/groups/{group_id}/radar/v2/shadow-evaluate"
        ]

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].methods, {"POST"})

    def test_shadow_flag_has_explicit_environment_rollback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(radar_v2_shadow_enabled())
        with patch.dict(
            os.environ,
            {"OMI_RADAR_V2_SHADOW_ENABLED": "false"},
            clear=True,
        ):
            self.assertFalse(radar_v2_shadow_enabled())

    def test_shadow_persist_route_respects_environment_rollback(self) -> None:
        with patch.dict(
            os.environ,
            {"OMI_RADAR_V2_SHADOW_ENABLED": "false"},
            clear=True,
        ):
            with self.assertRaises(HTTPException) as raised:
                persist_watchlist_group_radar_v2_shadow(
                    group_id=7,
                    db=Session(self.engine),
                )

        self.assertEqual(raised.exception.status_code, 503)

    def test_market_regime_uses_latest_aligned_market_minute(self) -> None:
        aligned_minute = datetime(2026, 7, 29, 1, 30, tzinfo=UTC)
        later_minute = aligned_minute + timedelta(minutes=1)
        common = {
            "trade_date": date(2026, 7, 29),
            "session_status": "regular",
            "breadth_status": "ready",
            "breadth_scope": "full_market",
            "quality_status": "ready",
            "unchanged_count": 0,
            "unknown_count": 0,
            "missing_count": 0,
            "source": "test",
            "source_category": "official",
        }
        with Session(self.engine) as db:
            db.add_all(
                [
                    TaiwanMarketMinuteState(
                        **common,
                        market="TWSE",
                        index_id="TAIEX",
                        minute_at=aligned_minute,
                        advance_count=500,
                        decline_count=400,
                        total_count=900,
                        index_change_pct=0.5,
                    ),
                    TaiwanMarketMinuteState(
                        **common,
                        market="TPEX",
                        index_id="OTC",
                        minute_at=aligned_minute,
                        advance_count=300,
                        decline_count=200,
                        total_count=500,
                        index_change_pct=0.3,
                    ),
                    TaiwanMarketMinuteState(
                        **common,
                        market="TWSE",
                        index_id="TAIEX",
                        minute_at=later_minute,
                        advance_count=1,
                        decline_count=899,
                        total_count=900,
                        index_change_pct=-9.0,
                    ),
                    TaiwanMarketMinuteState(
                        **common,
                        market="TPEX",
                        index_id="OTC",
                        minute_at=later_minute,
                        advance_count=1,
                        decline_count=499,
                        total_count=500,
                        index_change_pct=-8.0,
                    ),
                ]
            )
            db.commit()

            snapshot = latest_market_regime_snapshot(
                db=db,
                signal_trade_date=date(2026, 7, 29),
                as_of_at=aligned_minute,
            )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["minute_at"], aligned_minute.replace(tzinfo=None).isoformat())
        self.assertEqual(snapshot["advance_count"], 800)
        self.assertEqual(snapshot["decline_count"], 600)
        self.assertEqual(snapshot["quality_status"], "ready")
        self.assertEqual(snapshot["breadth_scope"], "full_market")

    def test_persistence_is_idempotent_and_group_projection_is_separate(self) -> None:
        attached = attach_radar_v2_shadow(radar=_radar_payload())
        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar Test"))
            db.commit()
            first = persist_radar_v2_shadow(
                db=db,
                radar=attached,
                group_id=7,
                mode="action",
                now=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
            )
            second = persist_radar_v2_shadow(
                db=db,
                radar=attached,
                group_id=7,
                mode="action",
                now=datetime(2026, 7, 29, 8, 5, tzinfo=UTC),
            )

            self.assertEqual(first["feature_created_count"], 2)
            self.assertEqual(first["evaluation_created_count"], 2)
            self.assertEqual(first["projection_created_count"], 2)
            self.assertEqual(second["feature_created_count"], 0)
            self.assertEqual(second["evaluation_created_count"], 0)
            self.assertEqual(second["projection_created_count"], 0)
            self.assertEqual(db.query(RadarFeatureSnapshot).count(), 2)
            self.assertEqual(db.query(RadarRuleEvaluation).count(), 2)
            self.assertEqual(db.query(RadarWatchlistProjection).count(), 2)
            self.assertEqual(db.query(RadarSignalEvent).count(), 3)
            self.assertEqual(db.query(RadarUniverseObservation).count(), 2)
            self.assertEqual(db.query(RadarEvaluationEventLink).count(), 3)
            feature = (
                db.query(RadarFeatureSnapshot)
                .filter(RadarFeatureSnapshot.stock_id == "2330")
                .one()
            )
            self.assertEqual(
                feature.source_available_at,
                datetime(2026, 7, 29, 8, 0),
            )
            self.assertGreater(feature.source_available_at, feature.effective_at)

    def test_missing_universe_observation_does_not_false_exit_event(self) -> None:
        first_day = attach_radar_v2_shadow(radar=_radar_payload())
        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar Test"))
            db.commit()
            persist_radar_v2_shadow(
                db=db,
                radar=first_day,
                group_id=7,
                mode="action",
                now=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
            )

            missing_item = {
                "source_rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "trade_date": date(2026, 7, 30),
                "time": "2026-07-30",
                "status": "no_data",
                "error_message": "provider timeout",
            }
            missing_radar = deepcopy(_radar_payload())
            missing_radar.update(
                {
                    "trade_date": date(2026, 7, 30),
                    "target_trade_date": date(2026, 7, 30),
                    "results": [],
                }
            )
            missing_attached = attach_radar_v2_shadow(
                radar=missing_radar,
                universe_items=[missing_item],
            )
            persist_radar_v2_shadow(
                db=db,
                radar=missing_attached,
                group_id=7,
                mode="action",
                now=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
            )

            events = (
                db.query(RadarSignalEvent)
                .filter(RadarSignalEvent.stock_id == "2330")
                .all()
            )
            self.assertTrue(events)
            self.assertTrue(all(event.status == "unobserved" for event in events))
            self.assertTrue(all(event.exit_trade_date is None for event in events))
            observation = (
                db.query(RadarUniverseObservation)
                .filter(RadarUniverseObservation.snapshot_date == date(2026, 7, 30))
                .filter(RadarUniverseObservation.stock_id == "2330")
                .one()
            )
            self.assertEqual(observation.observation_status, "no_data")

            inactive_item = deepcopy(_radar_payload()["results"][0])
            inactive_item.update(
                {
                    "trade_date": date(2026, 7, 31),
                    "time": "2026-07-31",
                    "signal_keys": [],
                }
            )
            inactive_radar = deepcopy(_radar_payload())
            inactive_radar.update(
                {
                    "trade_date": date(2026, 7, 31),
                    "target_trade_date": date(2026, 7, 31),
                    "results": [inactive_item],
                }
            )
            inactive_attached = attach_radar_v2_shadow(
                radar=inactive_radar,
                universe_items=[inactive_item],
            )
            persist_radar_v2_shadow(
                db=db,
                radar=inactive_attached,
                group_id=7,
                mode="action",
                now=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
            )

            db.expire_all()
            events = (
                db.query(RadarSignalEvent)
                .filter(RadarSignalEvent.stock_id == "2330")
                .all()
            )
            self.assertTrue(all(event.status == "exited" for event in events))
            self.assertTrue(
                all(event.exit_trade_date == date(2026, 7, 31) for event in events)
            )

    def test_outcome_keeps_all_active_event_links(self) -> None:
        attached = attach_radar_v2_shadow(radar=_radar_payload())
        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar Test"))
            db.commit()
            persisted = persist_radar_v2_shadow(
                db=db,
                radar=attached,
                group_id=7,
                mode="action",
            )
            evaluation = (
                db.query(RadarRuleEvaluation)
                .filter(RadarRuleEvaluation.stock_id == "2330")
                .one()
            )
            evaluation_event_ids = {
                int(row.signal_event_id)
                for row in db.query(RadarEvaluationEventLink)
                .filter(RadarEvaluationEventLink.evaluation_id == evaluation.id)
                .all()
            }
            self.assertGreater(len(evaluation_event_ids), 1)

            outcome = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=int(evaluation.id),
                horizons=[1],
            )[0]
            outcome_event_ids = {
                int(row.signal_event_id)
                for row in db.query(RadarOutcomeEventLink)
                .filter(
                    RadarOutcomeEventLink.outcome_path_id == int(outcome["id"])
                )
                .all()
            }

            self.assertEqual(outcome_event_ids, evaluation_event_ids)
            self.assertEqual(set(outcome["signal_event_ids"]), evaluation_event_ids)
            self.assertEqual(
                db.query(RadarOutcomePath).filter(
                    RadarOutcomePath.id == int(outcome["id"])
                ).one().signal_event_id,
                None,
            )
            self.assertGreater(persisted["event_link_created_count"], 1)

    def test_same_feature_is_reused_across_watchlist_groups(self) -> None:
        attached = attach_radar_v2_shadow(radar=_radar_payload())
        with Session(self.engine) as db:
            db.add_all(
                [
                    WatchlistGroup(id=7, group_name="Radar A"),
                    WatchlistGroup(id=8, group_name="Radar B"),
                ]
            )
            db.commit()
            persist_radar_v2_shadow(
                db=db,
                radar=attached,
                group_id=7,
                mode="action",
            )
            second = persist_radar_v2_shadow(
                db=db,
                radar=attached,
                group_id=8,
                mode="action",
            )

            self.assertEqual(second["feature_created_count"], 0)
            self.assertEqual(second["evaluation_created_count"], 0)
            self.assertEqual(second["projection_created_count"], 2)
            self.assertEqual(db.query(RadarFeatureSnapshot).count(), 2)
            self.assertEqual(db.query(RadarRuleEvaluation).count(), 2)
            self.assertEqual(db.query(RadarWatchlistProjection).count(), 4)


if __name__ == "__main__":
    unittest.main()
