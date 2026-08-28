from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    RadarBacktestRun,
    RadarFeatureSnapshot,
    RadarOutcomePath,
    RadarRuleEvaluation,
    RadarUniverseObservation,
    SourceRegistry,
    StockMaster,
    WatchlistGroup,
)
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from app.watchlists.radar_backtest_v2 import (
    RadarBacktestRequest,
    build_purged_walk_forward_splits,
    point_in_time_daily_coverage,
    run_radar_backtest_v2,
)


UTC = timezone.utc


class WatchlistRadarBacktestV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        with Session(self.engine) as db:
            group = WatchlistGroup(group_name="回測 universe")
            db.add(group)
            db.commit()
            self.group_id = int(group.id)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_walk_forward_keeps_label_purge_and_embargo_gaps(self) -> None:
        trade_dates = [
            date(2026, 1, 1) + timedelta(days=index)
            for index in range(40)
        ]

        splits = build_purged_walk_forward_splits(
            trade_dates,
            train_trading_days=10,
            validation_trading_days=4,
            test_trading_days=4,
            purge_trading_days=2,
            embargo_trading_days=1,
            step_trading_days=4,
        )

        self.assertGreaterEqual(len(splits), 1)
        first = splits[0]
        self.assertEqual(first.train_end, trade_dates[9])
        self.assertEqual(first.validation_start, trade_dates[12])
        self.assertEqual(first.validation_end, trade_dates[15])
        self.assertEqual(first.test_start, trade_dates[19])
        self.assertLess(first.train_end, first.validation_start)
        self.assertLess(first.validation_end, first.test_start)

    def test_point_in_time_coverage_keeps_missing_and_short_history_visible(
        self,
    ) -> None:
        with Session(self.engine) as db:
            source = SourceRegistry(
                source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
                source_type="official",
                category="market_daily_price",
                reliability_level="official",
            )
            db.add(source)
            db.add_all(
                [
                    StockMaster(
                        stock_id=stock_id,
                        stock_name=stock_id,
                        market="TWSE",
                        instrument_type="stock",
                        is_active=True,
                    )
                    for stock_id in ("2330", "2317", "2454")
                ]
            )
            db.flush()
            trade_dates = [
                date(2026, 7, 27),
                date(2026, 7, 28),
                date(2026, 7, 29),
            ]
            raw_result_id = 1
            for stock_id, observed_dates in (
                ("2330", trade_dates),
                ("2317", trade_dates[:2]),
            ):
                for trade_date in observed_dates:
                    raw = RawFetchResult(
                        source_id=source.id,
                        fetched_at=datetime.combine(
                            trade_date,
                            datetime.min.time(),
                            tzinfo=UTC,
                        ).replace(hour=8),
                        method="GET",
                        content_hash=(
                            f"radar-backtest-{stock_id}-{trade_date.isoformat()}"
                        ),
                        parser_version="radar-backtest-test-v1",
                    )
                    db.add(raw)
                    db.flush()
                    db.add(
                        MarketDailyPrice(
                            source_id=source.id,
                            raw_result_id=raw.id,
                            trade_date=trade_date,
                            stock_id=stock_id,
                            open_price=99,
                            high_price=101,
                            low_price=98,
                            close_price=100,
                        )
                    )
                    raw_result_id += 1
            db.commit()

            result = point_in_time_daily_coverage(
                db=db,
                as_of_date=date(2026, 7, 29),
                required_history_days=3,
                stock_ids=["2330", "2317", "2454"],
            )

        self.assertEqual(result["requested_count"], 3)
        self.assertEqual(result["eligible_count"], 1)
        self.assertAlmostEqual(result["coverage_ratio"], 1 / 3)
        self.assertEqual(result["eligible_stock_ids"], ["2330"])
        self.assertEqual(result["missing_stock_ids"], ["2454"])
        self.assertIn(
            "point_in_time_listing_membership_unavailable",
            result["limitations"],
        )

    def _add_sample(
        self,
        db: Session,
        *,
        index: int,
        signal_trade_date: date,
        close_r: float,
        corporate_action_status: str = "checked_clear",
        available_after_evaluation: bool = False,
    ) -> None:
        effective_at = datetime(
            signal_trade_date.year,
            signal_trade_date.month,
            signal_trade_date.day,
            6,
            tzinfo=UTC,
        )
        available_at = effective_at + (
            timedelta(hours=1)
            if available_after_evaluation
            else timedelta(0)
        )
        decision_at = effective_at
        feature = RadarFeatureSnapshot(
            market="TW",
            stock_id=f"23{index:02d}",
            signal_trade_date=signal_trade_date,
            effective_at=effective_at,
            available_at=available_at,
            source_available_at=available_at,
            observed_at=decision_at,
            feature_basis="daily_final",
            source_timeframe="daily",
            feature_version="technical_v2.0-shadow",
            feature_config_hash="feature-hash",
            input_manifest_hash=f"input-{index}",
            data_status="current",
            freshness_status="current",
            data_quality_score=1.0,
            close_price=100,
            signal_atr=10,
            features_json="{}",
            signals_json="[]",
            input_manifest_json="{}",
            data_limitations_json="[]",
        )
        db.add(feature)
        db.flush()
        evaluation = RadarRuleEvaluation(
            feature_snapshot_id=feature.id,
            rule_version="radar_v2.0-shadow",
            rule_config_hash="rule-hash",
            stock_id=feature.stock_id,
            signal_trade_date=signal_trade_date,
            direction=1,
            primary_bucket="momentum",
            decision_at=decision_at,
        )
        db.add(evaluation)
        db.flush()
        db.add(
            RadarOutcomePath(
                evaluation_id=evaluation.id,
                stock_id=feature.stock_id,
                signal_trade_date=signal_trade_date,
                horizon_trading_days=1,
                horizon_end_trade_date=signal_trade_date + timedelta(days=1),
                outcome_contract_version="outcome_v2.0-shadow",
                outcome_config_hash="outcome-hash",
                status="evaluated",
                summary_state=(
                    "close_confirmed" if close_r > 0 else "invalidated"
                ),
                direction=1,
                reference_direction=1,
                close_r=close_r,
                mfe_r=max(0.1, close_r + 0.5),
                mae_r=max(0.1, -close_r),
                signal_close_return_pct=close_r * 2,
                corporate_action_status=corporate_action_status,
                outcome_quality="final",
                path_order_quality="unordered_daily_ohlc",
                tradability_status="entry_proxy_only",
                return_basis="raw_price",
                corporate_actions_json="[]",
                limitations_json="[]",
                raw_path_json="{}",
            )
        )
        db.flush()
        db.add(
            RadarUniverseObservation(
                group_id=self.group_id,
                mode="action",
                snapshot_date=signal_trade_date,
                market="TW",
                stock_id=feature.stock_id,
                observation_status="evaluated",
                selected=index <= 3,
                evaluation_id=evaluation.id,
                source_rank=index,
                universe_scope="complete_calculation_universe",
                rule_version="radar_v2.0-shadow",
                rule_config_hash="rule-hash",
                observed_at=decision_at,
            )
        )

    def test_backtest_gate_is_idempotent_and_reports_exclusions(self) -> None:
        with Session(self.engine) as db:
            close_r_values = (0.4, 0.4, 0.4, 0.8, 1.0, -0.5, 0.2)
            for index, close_r in enumerate(close_r_values, start=1):
                self._add_sample(
                    db,
                    index=index,
                    signal_trade_date=date(2026, 7, 20)
                    + timedelta(days=index),
                    close_r=close_r,
                    corporate_action_status=(
                        "detected_unadjusted" if index == 4 else "checked_clear"
                    ),
                )
            db.commit()
            request = RadarBacktestRequest(
                rule_version="radar_v2.0-shadow",
                rule_config_hash="rule-hash",
                feature_version="technical_v2.0-shadow",
                feature_config_hash="feature-hash",
                outcome_contract_version="outcome_v2.0-shadow",
                outcome_config_hash="outcome-hash",
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                horizon_trading_days=1,
                minimum_samples=3,
                minimum_coverage_ratio=1.0,
                train_trading_days=1,
                validation_trading_days=1,
                test_trading_days=1,
                embargo_trading_days=0,
                require_baseline=False,
            )

            first = run_radar_backtest_v2(db=db, request=request)
            second = run_radar_backtest_v2(db=db, request=request)
            run_count = db.query(RadarBacktestRun).count()
            baseline_blocked = run_radar_backtest_v2(
                db=db,
                request=replace(request, require_baseline=True),
            )

        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(run_count, 1)
        self.assertEqual(baseline_blocked["status"], "blocked")
        self.assertIn(
            "baseline_available",
            baseline_blocked["coverage"]["failed_gates"],
        )
        self.assertEqual(first["requested_sample_count"], 7)
        self.assertEqual(first["eligible_sample_count"], 6)
        self.assertAlmostEqual(first["coverage_ratio"], 1.0)
        self.assertEqual(
            first["coverage"]["excluded_reason_counts"],
            {"corporate_action_status:detected_unadjusted": 1},
        )
        self.assertEqual(
            first["metrics"]["promotion_basis"],
            "walk_forward_test_only",
        )
        self.assertAlmostEqual(
            first["metrics"]["oos"]["direction_accuracy"],
            2 / 3,
        )
        self.assertEqual(first["metrics"]["oos"]["sample_count"], 3)
        self.assertEqual(
            first["metrics"]["diagnostic_full_sample"]["sample_count"],
            6,
        )
        self.assertEqual(
            first["coverage"]["oos_universe_coverage_ratio"],
            1.0,
        )
        self.assertIn(
            "market_sector_matched_baseline_unavailable",
            first["limitations"],
        )

    def test_feature_available_after_evaluation_is_excluded_as_lookahead(
        self,
    ) -> None:
        with Session(self.engine) as db:
            self._add_sample(
                db,
                index=1,
                signal_trade_date=date(2026, 7, 21),
                close_r=1.0,
                available_after_evaluation=True,
            )
            db.commit()
            request = RadarBacktestRequest(
                rule_version="radar_v2.0-shadow",
                rule_config_hash="rule-hash",
                feature_version="technical_v2.0-shadow",
                feature_config_hash="feature-hash",
                outcome_contract_version="outcome_v2.0-shadow",
                outcome_config_hash="outcome-hash",
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                horizon_trading_days=1,
                minimum_samples=1,
                minimum_coverage_ratio=1.0,
                train_trading_days=1,
                validation_trading_days=1,
                test_trading_days=1,
                embargo_trading_days=0,
                require_baseline=False,
            )

            result = run_radar_backtest_v2(db=db, request=request)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["eligible_sample_count"], 0)
        self.assertEqual(
            result["coverage"]["excluded_reason_counts"],
            {"feature_source_available_after_decision": 1},
        )

    def test_after_the_fact_evaluation_is_not_a_point_in_time_sample(self) -> None:
        with Session(self.engine) as db:
            self._add_sample(
                db,
                index=1,
                signal_trade_date=date(2026, 7, 21),
                close_r=1.0,
            )
            next_day = datetime(2026, 7, 22, 6, tzinfo=UTC)
            feature = db.query(RadarFeatureSnapshot).one()
            evaluation = db.query(RadarRuleEvaluation).one()
            feature.source_available_at = next_day
            feature.available_at = next_day
            feature.observed_at = next_day
            evaluation.decision_at = next_day
            db.commit()
            request = RadarBacktestRequest(
                rule_version="radar_v2.0-shadow",
                rule_config_hash="rule-hash",
                feature_version="technical_v2.0-shadow",
                feature_config_hash="feature-hash",
                outcome_contract_version="outcome_v2.0-shadow",
                outcome_config_hash="outcome-hash",
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                horizon_trading_days=1,
                minimum_samples=1,
                minimum_coverage_ratio=1.0,
                train_trading_days=1,
                validation_trading_days=1,
                test_trading_days=1,
                embargo_trading_days=0,
                require_baseline=False,
            )

            result = run_radar_backtest_v2(db=db, request=request)

        self.assertEqual(result["eligible_sample_count"], 0)
        self.assertEqual(
            result["coverage"]["excluded_reason_counts"],
            {"decision_outside_signal_trade_date": 1},
        )


if __name__ == "__main__":
    unittest.main()
