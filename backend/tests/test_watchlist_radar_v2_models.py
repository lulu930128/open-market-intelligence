from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RadarFeatureSnapshot,
    RadarOutcomePath,
    RadarRuleEvaluation,
)


UTC = timezone.utc


class WatchlistRadarV2ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def _feature_snapshot(self) -> RadarFeatureSnapshot:
        effective_at = datetime(2026, 7, 29, 5, 45, tzinfo=UTC)
        return RadarFeatureSnapshot(
            market="TW",
            stock_id="2330",
            stock_name="台積電",
            signal_trade_date=date(2026, 7, 29),
            effective_at=effective_at,
            available_at=effective_at,
            source_available_at=effective_at,
            observed_at=effective_at,
            feature_basis="daily_final",
            source_timeframe="daily",
            feature_version="technical_v2.0-shadow",
            feature_config_hash="feature-hash",
            input_manifest_hash="input-hash",
            data_status="current",
            freshness_status="current",
            features_json="{}",
            signals_json="[]",
            input_manifest_json="{}",
            data_limitations_json="[]",
        )

    def test_feature_snapshot_identity_is_group_independent(self) -> None:
        with Session(self.engine) as db:
            db.add(self._feature_snapshot())
            db.commit()

            db.add(self._feature_snapshot())
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_same_feature_supports_parallel_v1_and_v2_evaluations(self) -> None:
        with Session(self.engine) as db:
            feature = self._feature_snapshot()
            db.add(feature)
            db.flush()
            for rule_version, config_hash in (
                ("radar_v1.0", "v1-hash"),
                ("radar_v2.0-shadow", "v2-hash"),
            ):
                db.add(
                    RadarRuleEvaluation(
                        feature_snapshot_id=feature.id,
                        rule_version=rule_version,
                        rule_config_hash=config_hash,
                        stock_id=feature.stock_id,
                        signal_trade_date=feature.signal_trade_date,
                        primary_bucket="watch",
                        decision_at=feature.source_available_at,
                    )
                )
            db.commit()

            evaluations = db.query(RadarRuleEvaluation).all()

        self.assertEqual(len(evaluations), 2)
        self.assertEqual(
            {evaluation.rule_version for evaluation in evaluations},
            {"radar_v1.0", "radar_v2.0-shadow"},
        )

    def test_outcome_identity_supports_multiple_horizons(self) -> None:
        with Session(self.engine) as db:
            feature = self._feature_snapshot()
            db.add(feature)
            db.flush()
            evaluation = RadarRuleEvaluation(
                feature_snapshot_id=feature.id,
                rule_version="radar_v2.0-shadow",
                rule_config_hash="v2-hash",
                stock_id=feature.stock_id,
                signal_trade_date=feature.signal_trade_date,
                primary_bucket="momentum",
                direction=1,
                decision_at=feature.source_available_at,
            )
            db.add(evaluation)
            db.flush()
            for horizon in (1, 3, 5):
                db.add(
                    RadarOutcomePath(
                        evaluation_id=evaluation.id,
                        stock_id=feature.stock_id,
                        signal_trade_date=feature.signal_trade_date,
                        horizon_trading_days=horizon,
                        outcome_contract_version="outcome_v2.0-shadow",
                        outcome_config_hash="outcome-hash",
                        direction=1,
                        reference_direction=1,
                    )
                )
            db.commit()

            outcomes = db.query(RadarOutcomePath).order_by(
                RadarOutcomePath.horizon_trading_days
            ).all()

        self.assertEqual(
            [outcome.horizon_trading_days for outcome in outcomes],
            [1, 3, 5],
        )


if __name__ == "__main__":
    unittest.main()
