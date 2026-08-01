from __future__ import annotations

from datetime import date
import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RadarFeatureSnapshot,
    RadarOutcomePath,
    RadarRuleEvaluation,
    RadarUniverseObservation,
    WatchlistGroup,
)
from app.watchlists.radar_active_v2_service import (
    build_radar_v2_active_projection,
    persist_radar_v2_active,
)
from app.market.trading_calendar import next_taiwan_trading_day
from app.watchlists.radar_rule_contract import (
    RADAR_V2_ACTIVE_FEATURE_VERSION,
    RADAR_V2_ACTIVE_RULE_VERSION,
)
from app.watchlists.radar_v2_service import (
    _outcome_limitation_objects,
    get_latest_radar_v2_projection,
    get_radar_v2_outcome_summary,
    get_radar_v2_validation_readiness,
    list_radar_v2_projection_history,
)
from app.watchlists.schemas import (
    WatchlistGroupRadarRead,
    WatchlistRadarV2OutcomeSummaryRead,
)
from app.routers.watchlists import (
    create_watchlist_group_radar_snapshot,
    evaluate_watchlist_group_radar_outcome,
    get_watchlist_group_radar,
    router as watchlists_router,
)
from app.watchlists.radar_shadow_v2_service import (
    evaluate_pending_radar_v2_outcomes,
)

def _source_item(
    stock_id: str,
    *,
    signal_keys: list[str],
    source_rank: int,
    urgency: str = "low",
) -> dict:
    return {
        "rank": source_rank,
        "source_rank": source_rank,
        "stock_id": stock_id,
        "stock_name": stock_id,
        "bucket": "breakout_high",
        "bucket_label": "v1 bucket",
        "direction": "bullish",
        "urgency": urgency,
        "priority_score": 99.0 - source_rank,
        "technical_evidence_score": 8.0,
        "technical_score": 50.0,
        "technical_grade": "strong",
        "technical_grade_label": "v1",
        "technical_grade_description": "v1",
        "direction_label": "v1",
        "setup_label": "v1",
        "timing_label": "v1",
        "risk_label": "v1",
        "factor_scores": {},
        "price_levels": {},
        "technical_notes": [],
        "action_label": "v1 action",
        "reason": "v1 reason",
        "trade_date": date(2026, 7, 30),
        "time": "2026-07-30",
        "close": 100.0,
        "previous_close": 101.0,
        "volume": 1_000_000,
        "change": -1.0,
        "change_pct": -0.99,
        "limit_status": None,
        "score": 5,
        "status": "bearish" if signal_keys else "neutral",
        "signal_count": len(signal_keys),
        "signal_keys": signal_keys,
        "matched_signal_keys": signal_keys,
        "matched_signal_labels": signal_keys,
        "signal_labels": signal_keys,
        "primary_signal_key": signal_keys[0] if signal_keys else None,
        "primary_signal_label": signal_keys[0] if signal_keys else None,
        "indicator_snapshot": {
            "ma": {"ma20": 105.0, "ma60": 110.0},
            "atr": {"atr14": 3.0},
            "adx": {
                "adx14": 32.0,
                "plus_di14": 10.0,
                "minus_di14": 28.0,
            },
            "donchian": {"upper20": 115.0, "lower20": 102.0},
            "bollinger": {
                "upper20": 113.0,
                "lower20": 103.0,
                "bandwidth20_pct": 10.0,
            },
            "macd": {"histogram": -2.0},
            "roc": {"roc12": -6.0},
            "rsi": {"rsi14": 34.0},
            "mfi": {"mfi14": 32.0},
            "volume_ma": {"volume_ma5": 700_000.0},
        },
        "context_snapshot": {},
        "context_signals": [],
        "context_summary": "",
        "context_score": 0.0,
        "stale": False,
        "error_message": None,
    }


def _base_radar(v1_item: dict) -> dict:
    return {
        "group_id": 7,
        "include_children": True,
        "mode": "action",
        "max_results": 1,
        "requested_stock_count": 2,
        "ranked_count": 2,
        "matched_count": 1,
        "radar_count": 1,
        "no_data_count": 0,
        "error_count": 0,
        "trade_date": date(2026, 7, 30),
        "target_trade_date": date(2026, 7, 30),
        "is_current": True,
        "current_stock_count": 2,
        "stale_stock_count": 0,
        "buckets": [],
        "results": [v1_item],
    }


class WatchlistRadarActiveV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_persisted_outcome_limitation_codes_normalize_for_public_schema(
        self,
    ) -> None:
        self.assertEqual(
            _outcome_limitation_objects(
                '["entry_proxy_not_execution", "daily_ohlc_path_unordered"]'
            ),
            [
                {"code": "entry_proxy_not_execution"},
                {"code": "daily_ohlc_path_unordered"},
            ],
        )

    def test_public_route_defaults_to_v2_and_keeps_v1_read_only_routes(
        self,
    ) -> None:
        version_default = inspect.signature(
            get_watchlist_group_radar
        ).parameters["version"].default
        self.assertEqual(version_default.default, "v2")
        methods_by_path = {
            getattr(route, "path", ""): getattr(route, "methods", set())
            for route in watchlists_router.routes
        }
        self.assertEqual(
            methods_by_path["/groups/{group_id}/radar/v2/evaluate"],
            {"POST"},
        )
        self.assertEqual(
            methods_by_path[
                "/groups/{group_id}/radar/v2/snapshots/history"
            ],
            {"GET"},
        )

    def test_v1_projection_is_frozen_snapshot_only(self) -> None:
        frozen_snapshot = {
            **_base_radar(
                _source_item("2330", signal_keys=["donchian_breakout"], source_rank=1)
            ),
            "snapshot_id": 7,
            "snapshot_date": "2026-07-31",
        }
        with Session(self.engine) as db, patch(
            "app.routers.watchlists.radar_outcome_service.get_latest_watchlist_radar_snapshot_payload",
            return_value=frozen_snapshot,
        ), patch(
            "app.routers.watchlists.radar_service.get_watchlist_group_radar_bundle"
        ) as compute_v1:
            result = get_watchlist_group_radar(
                group_id=1,
                include_children=True,
                enabled_only=True,
                mode="action",
                max_results=30,
                ma_windows=None,
                volume_ma_windows=None,
                calculation_limit=100,
                volume_ratio_threshold=None,
                use_intraday=False,
                intraday_limit=30,
                prefer_snapshot=False,
                snapshot_only=False,
                include_shadow_v2=True,
                version="v1",
                db=db,
            )

        self.assertEqual(result["cache_status"], "frozen_v1_snapshot")
        self.assertEqual(result["radar_engine"]["mode"], "frozen")
        self.assertEqual(result["radar_engine"]["legacy_status"], "frozen")
        compute_v1.assert_not_called()

    def test_v1_write_routes_return_gone(self) -> None:
        with Session(self.engine) as db:
            for write_call in (
                lambda: create_watchlist_group_radar_snapshot(group_id=1, db=db),
                lambda: evaluate_watchlist_group_radar_outcome(group_id=1, db=db),
            ):
                with self.assertRaises(HTTPException) as raised:
                    write_call()
                self.assertEqual(raised.exception.status_code, 410)
                self.assertEqual(
                    raised.exception.detail["code"],
                    "RADAR_V1_FROZEN",
                )

    def test_active_projection_ranks_complete_universe_not_v1_top_n(self) -> None:
        v1_selected = _source_item(
            "1111",
            signal_keys=[],
            source_rank=1,
            urgency="high",
        )
        v2_candidate = _source_item(
            "2222",
            signal_keys=[
                "cross_below_ma60",
                "donchian_breakdown",
                "structure_support_break",
                "bollinger_breakdown",
                "volume_price_down",
                "adx_bear_trend",
                "macd_negative",
                "roc_negative",
            ],
            source_rank=2,
            urgency="low",
        )

        result = build_radar_v2_active_projection(
            radar=_base_radar(v1_selected),
            universe_items=[v1_selected, v2_candidate],
        )

        self.assertEqual(
            result["radar_engine"]["active_version"],
            RADAR_V2_ACTIVE_RULE_VERSION,
        )
        self.assertEqual(
            result["radar_v2_summary"]["universe_evaluated_count"],
            2,
        )
        self.assertEqual(
            [item["stock_id"] for item in result["results"]],
            ["2222"],
        )
        self.assertNotEqual(
            result["results"][0]["action_label"],
            v2_candidate["action_label"],
        )
        self.assertNotEqual(
            result["results"][0]["reason"],
            v2_candidate["reason"],
        )
        self.assertIn(
            result["results"][0]["urgency"],
            {"medium", "high"},
        )
        validated = WatchlistGroupRadarRead.model_validate(result)
        self.assertEqual(
            validated.radar_engine.active_version,
            RADAR_V2_ACTIVE_RULE_VERSION,
        )

    def test_active_persistence_and_read_model_do_not_require_v1_snapshot(
        self,
    ) -> None:
        quiet = _source_item("1111", signal_keys=[], source_rank=1)
        selected = _source_item(
            "2222",
            signal_keys=[
                "cross_below_ma60",
                "structure_support_break",
                "volume_price_down",
                "macd_negative",
            ],
            source_rank=2,
        )
        active = build_radar_v2_active_projection(
            radar=_base_radar(quiet),
            universe_items=[quiet, selected],
        )

        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar v2"))
            db.commit()
            persisted = persist_radar_v2_active(
                db=db,
                radar=active,
                group_id=7,
                mode="action",
            )
            latest = get_latest_radar_v2_projection(
                db=db,
                group_id=7,
                mode="action",
                max_results=10,
            )
            history = list_radar_v2_projection_history(
                db=db,
                group_id=7,
                mode="action",
            )
            outcome = get_radar_v2_outcome_summary(
                db=db,
                group_id=7,
                mode="action",
            )
            readiness = get_radar_v2_validation_readiness(
                db=db,
                group_id=7,
                mode="action",
            )

            self.assertEqual(
                persisted["rule_version"],
                RADAR_V2_ACTIVE_RULE_VERSION,
            )
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["cache_status"], "v2_snapshot")
            self.assertEqual(latest["results"][0]["stock_id"], "2222")
            WatchlistGroupRadarRead.model_validate(latest)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["selected_count"], 1)
            self.assertEqual(outcome["status"], "not_evaluated")
            self.assertEqual(outcome["total_count"], 1)
            WatchlistRadarV2OutcomeSummaryRead.model_validate(outcome)
            self.assertEqual(readiness["validation_status"], "unverified")
            self.assertEqual(
                {
                    row.stock_id
                    for row in db.query(RadarUniverseObservation)
                    .filter(RadarUniverseObservation.selected.is_(True))
                    .all()
                },
                {"2222"},
            )
            self.assertTrue(
                all(
                    row.feature_version
                    == RADAR_V2_ACTIVE_FEATURE_VERSION
                    for row in db.query(RadarFeatureSnapshot).all()
                )
            )
            self.assertTrue(
                all(
                    row.rule_version == RADAR_V2_ACTIVE_RULE_VERSION
                    for row in db.query(RadarRuleEvaluation).all()
                )
            )

    def test_pending_active_outcomes_are_reconciled_oldest_first(self) -> None:
        quiet = _source_item("1111", signal_keys=[], source_rank=1)
        selected = _source_item(
            "2222",
            signal_keys=[
                "cross_below_ma60",
                "structure_support_break",
                "volume_price_down",
                "macd_negative",
            ],
            source_rank=2,
        )
        active = build_radar_v2_active_projection(
            radar=_base_radar(quiet),
            universe_items=[quiet, selected],
        )

        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar v2"))
            db.commit()
            persisted = persist_radar_v2_active(
                db=db,
                radar=active,
                group_id=7,
                mode="action",
            )
            first = evaluate_pending_radar_v2_outcomes(
                db=db,
                evaluation_ids=persisted["evaluation_ids"],
                group_id=7,
                mode="action",
                rule_version=RADAR_V2_ACTIVE_RULE_VERSION,
            )
            self.assertEqual(first["error_count"], 0)
            self.assertEqual(
                db.query(RadarOutcomePath)
                .filter(RadarOutcomePath.status == "pending")
                .count(),
                6,
            )

            trade_date = date(2026, 7, 30)
            for index in range(1, 6):
                trade_date = next_taiwan_trading_day(trade_date)
                for stock_id in ("1111", "2222"):
                    db.add(
                        MarketDailyPrice(
                            source_id=1,
                            raw_result_id=index,
                            trade_date=trade_date,
                            stock_id=stock_id,
                            stock_name=stock_id,
                            open_price=100.0,
                            high_price=103.0,
                            low_price=97.0,
                            close_price=99.0,
                            trade_volume=1_000_000,
                        )
                    )
            db.commit()

            second = evaluate_pending_radar_v2_outcomes(
                db=db,
                group_id=7,
                mode="action",
                rule_version=RADAR_V2_ACTIVE_RULE_VERSION,
            )

            self.assertEqual(second["error_count"], 0)
            self.assertEqual(
                db.query(RadarOutcomePath)
                .filter(RadarOutcomePath.status == "pending")
                .count(),
                0,
            )

    def test_empty_active_scope_still_has_a_readable_snapshot(self) -> None:
        base = _base_radar(_source_item("1111", signal_keys=[], source_rank=1))
        base.update(
            {
                "requested_stock_count": 0,
                "ranked_count": 0,
                "matched_count": 0,
                "radar_count": 0,
                "results": [],
            }
        )
        active = build_radar_v2_active_projection(
            radar=base,
            universe_items=[],
        )
        with Session(self.engine) as db:
            db.add(WatchlistGroup(id=7, group_name="Radar v2"))
            db.commit()
            persisted = persist_radar_v2_active(
                db=db,
                radar=active,
                group_id=7,
                mode="action",
            )
            latest = get_latest_radar_v2_projection(
                db=db,
                group_id=7,
                mode="action",
            )

        self.assertIsNotNone(persisted["snapshot_run_id"])
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["results"], [])
        self.assertEqual(latest["radar_count"], 0)
        WatchlistGroupRadarRead.model_validate(latest)


if __name__ == "__main__":
    unittest.main()
