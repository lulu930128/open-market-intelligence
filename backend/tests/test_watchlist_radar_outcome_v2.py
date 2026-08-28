from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    RadarFeatureSnapshot,
    RadarOutcomePath,
    RadarRuleConfig,
    RadarRuleEvaluation,
    SourceRegistry,
    StockMaster,
)
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from app.watchlists.radar_outcome_v2_service import (
    OutcomePathBar,
    _corporate_action_context,
    calculate_outcome_path,
    evaluate_radar_outcome_v2,
    trading_dates_after,
)
from app.watchlists.radar_rule_contract import (
    RADAR_V2_FEATURE_VERSION,
    RADAR_V2_OUTCOME_CONFIG_HASH,
    RADAR_V2_OUTCOME_CONTRACT_VERSION,
    RADAR_V2_RULE_VERSION,
)


UTC = timezone.utc


class WatchlistRadarOutcomeV2CalculationTests(unittest.TestCase):
    @patch(
        "app.market.tw_corporate_events.list_taiwan_corporate_events",
        return_value={"results": [], "sources": ["official"]},
    )
    def test_ex_dividend_only_provider_is_not_reported_as_fully_clear(
        self,
        _list_taiwan_corporate_events,
    ) -> None:
        status, events, limitations = _corporate_action_context(
            stock_id="2330",
            date_from=date(2026, 7, 29),
            date_to=date(2026, 7, 30),
        )

        self.assertEqual(status, "partial_coverage")
        self.assertEqual(events, [])
        self.assertTrue(
            any(
                limitation.startswith("corporate_action_types_unavailable:")
                for limitation in limitations
            )
        )

    def test_directional_reversal_is_not_reported_as_confirmation(self) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 30),
                    open_price=100,
                    high_price=112,
                    low_price=92,
                    close_price=94,
                )
            ],
            reference_price=100,
            signal_atr=10,
            direction=1,
        )

        self.assertEqual(result["summary_state"], "reversed")
        self.assertTrue(result["intraday_triggered"])
        self.assertTrue(result["reversed"])
        self.assertFalse(result["close_confirmed"])
        self.assertFalse(result["whipsaw"])
        self.assertAlmostEqual(result["close_r"], -0.6)

    def test_whipsaw_has_precedence_over_close_confirmation(self) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 30),
                    open_price=100,
                    high_price=112,
                    low_price=88,
                    close_price=105,
                )
            ],
            reference_price=100,
            signal_atr=10,
            direction=1,
        )

        self.assertEqual(result["summary_state"], "whipsaw")
        self.assertTrue(result["intraday_triggered"])
        self.assertTrue(result["adverse_triggered"])
        self.assertTrue(result["close_confirmed"])

    def test_bearish_direction_uses_down_move_as_favorable(self) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 30),
                    open_price=100,
                    high_price=102,
                    low_price=88,
                    close_price=90,
                )
            ],
            reference_price=100,
            signal_atr=10,
            direction=-1,
        )

        self.assertEqual(result["summary_state"], "close_confirmed")
        self.assertAlmostEqual(result["mfe_r"], 1.2)
        self.assertAlmostEqual(result["mae_r"], 0.2)
        self.assertAlmostEqual(result["close_r"], 1.0)

    def test_compression_keeps_non_directional_two_way_state(self) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 30),
                    open_price=100,
                    high_price=112,
                    low_price=88,
                    close_price=101,
                )
            ],
            reference_price=100,
            signal_atr=10,
            direction=0,
            outcome_kind="compression",
        )

        self.assertEqual(result["summary_state"], "two_way_expansion")
        self.assertEqual(result["reference_direction"], 0)
        self.assertIsNone(result["mfe_r"])
        self.assertIsNone(result["mae_r"])

    def test_overheat_uses_symmetric_close_direction_instead_of_zero_direction(
        self,
    ) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 30),
                    open_price=100,
                    high_price=112,
                    low_price=98,
                    close_price=108,
                )
            ],
            reference_price=100,
            signal_atr=10,
            direction=0,
            outcome_kind="overheat",
        )

        self.assertEqual(result["summary_state"], "expanded_up")
        self.assertEqual(result["reference_direction"], 0)
        self.assertIsNone(result["close_r"])

    def test_3260_style_path_is_adverse_only_instead_of_generic_hit(self) -> None:
        result = calculate_outcome_path(
            bars=[
                OutcomePathBar(
                    trade_date=date(2026, 7, 29),
                    open_price=367,
                    high_price=405,
                    low_price=350,
                    close_price=394,
                )
            ],
            reference_price=369,
            signal_atr=20,
            direction=-1,
        )

        self.assertEqual(result["summary_state"], "adverse_only")
        self.assertTrue(result["adverse_triggered"])
        self.assertFalse(result["intraday_triggered"])
        self.assertFalse(result["close_confirmed"])
        self.assertAlmostEqual(result["close_r"], -1.35)


class WatchlistRadarOutcomeV2PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _evaluation(self, db: Session, *, signal_atr: float | None = 10) -> int:
        effective_at = datetime(2026, 7, 28, 5, 45, tzinfo=UTC)
        feature = RadarFeatureSnapshot(
            market="TW",
            stock_id="2330",
            stock_name="台積電",
            signal_trade_date=date(2026, 7, 28),
            effective_at=effective_at,
            available_at=effective_at,
            source_available_at=effective_at,
            observed_at=effective_at,
            feature_basis="daily_final",
            source_timeframe="daily",
            feature_version=RADAR_V2_FEATURE_VERSION,
            feature_config_hash="feature-hash",
            input_manifest_hash="input-hash",
            data_status="current",
            freshness_status="current",
            close_price=100,
            signal_atr=signal_atr,
            features_json="{}",
            signals_json="[]",
            input_manifest_json="{}",
            data_limitations_json="[]",
        )
        db.add(feature)
        db.flush()
        evaluation = RadarRuleEvaluation(
            feature_snapshot_id=feature.id,
            rule_version=RADAR_V2_RULE_VERSION,
            rule_config_hash="rule-hash",
            stock_id=feature.stock_id,
            signal_trade_date=feature.signal_trade_date,
            direction=1,
            primary_bucket="momentum",
            decision_at=effective_at,
        )
        db.add(evaluation)
        db.flush()
        return evaluation.id

    def _add_daily_bars(self, db: Session, *, count: int) -> None:
        source = SourceRegistry(
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
            source_type="official",
            category="market_daily_price",
            reliability_level="official",
        )
        db.add(source)
        db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            )
        )
        db.flush()
        dates = trading_dates_after(date(2026, 7, 28), count)
        for index, trade_date in enumerate(dates, start=1):
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=datetime.combine(
                    trade_date,
                    datetime.min.time(),
                    tzinfo=UTC,
                ).replace(hour=8),
                method="GET",
                content_hash=f"radar-outcome-{trade_date.isoformat()}",
                parser_version="radar-outcome-test-v1",
            )
            db.add(raw)
            db.flush()
            db.add(
                MarketDailyPrice(
                    source_id=source.id,
                    raw_result_id=raw.id,
                    trade_date=trade_date,
                    stock_id="2330",
                    stock_name="台積電",
                    open_price=100 + index - 1,
                    high_price=104 + index,
                    low_price=98,
                    close_price=101 + index,
                    trade_volume=1000 * index,
                )
            )
        db.flush()

    @patch(
        "app.watchlists.radar_outcome_v2_service._corporate_action_context",
        return_value=("checked_clear", [], []),
    )
    def test_evaluation_persists_three_idempotent_horizons(
        self,
        _corporate_action_context,
    ) -> None:
        with Session(self.engine) as db:
            evaluation_id = self._evaluation(db)
            self._add_daily_bars(db, count=5)
            db.commit()

            first = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
            )
            second = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
            )

            outcome_count = db.query(RadarOutcomePath).count()
            config = db.query(RadarRuleConfig).one()

        self.assertEqual([row["horizon_trading_days"] for row in first], [1, 3, 5])
        self.assertEqual([row["id"] for row in first], [row["id"] for row in second])
        self.assertEqual(outcome_count, 3)
        self.assertEqual(config.version, RADAR_V2_OUTCOME_CONTRACT_VERSION)
        self.assertEqual(config.config_hash, RADAR_V2_OUTCOME_CONFIG_HASH)
        self.assertTrue(all(row["outcome_quality"] == "final" for row in first))
        self.assertTrue(
            all(row["path_order_quality"] == "unordered_daily_ohlc" for row in first)
        )

    @patch(
        "app.watchlists.radar_outcome_v2_service._corporate_action_context",
        return_value=("checked_clear", [], []),
    )
    def test_missing_future_bar_keeps_horizon_pending(
        self,
        _corporate_action_context,
    ) -> None:
        with Session(self.engine) as db:
            evaluation_id = self._evaluation(db)
            self._add_daily_bars(db, count=1)
            db.commit()

            result = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
                horizons=[3],
            )[0]

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["summary_state"], "pending")
        self.assertTrue(
            any(
                limitation.startswith("missing_daily_bars:")
                for limitation in result["limitations"]
            )
        )

    @patch(
        "app.watchlists.radar_outcome_v2_service._corporate_action_context",
        return_value=("checked_clear", [], []),
    )
    def test_missing_signal_atr_preserves_raw_path_as_partial(
        self,
        _corporate_action_context,
    ) -> None:
        with Session(self.engine) as db:
            evaluation_id = self._evaluation(db, signal_atr=None)
            self._add_daily_bars(db, count=1)
            db.commit()

            result = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
                horizons=[1],
            )[0]

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary_state"], "unevaluable")
        self.assertIsNotNone(result["signal_close_return_pct"])
        self.assertIsNone(result["close_r"])
        self.assertIn("missing_signal_atr", result["limitations"])


if __name__ == "__main__":
    unittest.main()
