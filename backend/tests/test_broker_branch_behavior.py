from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs import scheduler
from app.routers import jobs as jobs_router
from app.db.models import (
    Base,
    BrokerBranchBehaviorFeatureSnapshot,
    BrokerBranchTradeDaily,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.broker_branch import NSTOCK_BRANCH_SOURCE_NAME
from app.market.broker_branch_behavior import (
    BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
    BrokerBranchBehaviorObservation,
    calculate_branch_behavior_feature,
    history_status_for_sessions,
    materialize_broker_branch_behavior_shadow,
    wilson_interval,
)
from app.market import broker_branch_behavior


class BrokerBranchBehaviorPureTests(unittest.TestCase):
    def test_right_censoring_is_conditioned_on_next_snapshot_availability(self) -> None:
        first = date(2026, 8, 20)
        second = date(2026, 8, 21)
        observations = [
            BrokerBranchBehaviorObservation(
                source_id=1,
                stock_id="2330",
                trade_date=first,
                branch_code="A001",
                buy_lots=10,
                sell_lots=0,
                net_lots=10,
            )
        ]

        unavailable = calculate_branch_behavior_feature(
            observations,
            eligible_session_pairs={first: second},
            usable_quality_keys={(1, "2330", first)},
        )
        censored = calculate_branch_behavior_feature(
            observations,
            eligible_session_pairs={first: second},
            usable_quality_keys={
                (1, "2330", first),
                (1, "2330", second),
            },
        )

        self.assertEqual(unavailable["eligible_initial_count"], 0)
        self.assertEqual(unavailable["censored_count"], 0)
        self.assertEqual(censored["eligible_initial_count"], 1)
        self.assertEqual(censored["censored_count"], 1)
        self.assertEqual(censored["censored_rate"], 1.0)

    def test_wilson_interval_and_history_gates_are_deterministic(self) -> None:
        low, high = wilson_interval(5, 10)
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)
        self.assertEqual(wilson_interval(0, 0), (None, None))
        self.assertEqual(history_status_for_sessions(19), "insufficient_history")
        self.assertEqual(history_status_for_sessions(20), "exploratory_only")
        self.assertEqual(history_status_for_sessions(60), "calibration_candidate")
        self.assertEqual(history_status_for_sessions(120), "production_candidate")


class BrokerBranchBehaviorMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.first_date = date(2026, 8, 20)
        self.second_date = date(2026, 8, 21)
        self.source = SourceRegistry(
            source_name=NSTOCK_BRANCH_SOURCE_NAME,
            source_type="http_api",
            category="broker_branch_trade",
        )
        self.raw = RawFetchResult(
            source=self.source,
            url="https://example.test/branch",
            method="GET",
        )
        self.db.add_all(
            [
                self.source,
                self.raw,
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="環球晶",
                    market="TPEx",
                    instrument_type="stock",
                    is_active=True,
                ),
            ]
        )
        self.db.flush()
        self._add_trade(
            stock_id="2330",
            trade_date=self.first_date,
            branch_code="A001",
            net_lots=10,
        )
        self._add_trade(
            stock_id="2330",
            trade_date=self.second_date,
            branch_code="A001",
            net_lots=-5,
        )
        self._add_trade(
            stock_id="6488",
            trade_date=self.first_date,
            branch_code="A001",
            net_lots=8,
        )
        self._add_trade(
            stock_id="6488",
            trade_date=self.second_date,
            branch_code="B002",
            net_lots=3,
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_trade(
        self,
        *,
        stock_id: str,
        trade_date: date,
        branch_code: str,
        net_lots: int,
    ) -> None:
        self.db.add(
            BrokerBranchTradeDaily(
                source_id=self.source.id,
                raw_result_id=self.raw.id,
                trade_date=trade_date,
                stock_id=stock_id,
                stock_name=stock_id,
                branch_code=branch_code,
                branch_name=branch_code,
                buy_lots=max(net_lots, 0),
                sell_lots=abs(min(net_lots, 0)),
                net_lots=net_lots,
            )
        )

    def test_materialization_is_shadow_only_censored_and_idempotent(self) -> None:
        first = materialize_broker_branch_behavior_shadow(
            self.db,
            as_of_trade_date=self.second_date,
            lookback_sessions=2,
        )
        second = materialize_broker_branch_behavior_shadow(
            self.db,
            as_of_trade_date=self.second_date,
            lookback_sessions=2,
        )

        self.assertEqual(first["status"], "completed")
        self.assertFalse(first["advertised"])
        self.assertFalse(first["decision_usable"])
        self.assertEqual(second["profiles_written"], first["profiles_written"])
        self.assertEqual(
            self.db.query(BrokerBranchBehaviorFeatureSnapshot).count(),
            2,
        )

        feature = (
            self.db.query(BrokerBranchBehaviorFeatureSnapshot)
            .filter(BrokerBranchBehaviorFeatureSnapshot.branch_code == "A001")
            .one()
        )
        self.assertEqual(
            feature.methodology_version,
            BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
        )
        self.assertEqual(feature.eligible_initial_count, 2)
        self.assertEqual(feature.reobserved_count, 1)
        self.assertEqual(feature.opposite_observed_count, 1)
        self.assertEqual(feature.same_direction_observed_count, 0)
        self.assertEqual(feature.censored_count, 1)
        self.assertEqual(feature.reappearance_rate, 0.5)
        self.assertEqual(feature.reverse_given_reappearance_rate, 1.0)
        self.assertEqual(feature.censored_rate, 0.5)
        self.assertEqual(feature.high_coverage_session_count, 2)
        self.assertEqual(feature.history_status, "insufficient_history")
        self.assertEqual(feature.calibration_status, "uncalibrated")
        self.assertFalse(feature.decision_usable)
        warnings = json.loads(feature.warnings_json)
        self.assertIn("ranked_top_n_absence_is_censored", warnings)
        self.assertIn("shadow_only_not_advertised", warnings)

    def test_materialization_rejects_unbounded_lookback(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 2 and 120"):
            materialize_broker_branch_behavior_shadow(
                self.db,
                as_of_trade_date=self.second_date,
                lookback_sessions=121,
            )

    def test_materialization_exhausts_stream_before_feature_writes(self) -> None:
        original_stream = broker_branch_behavior._observation_stream
        original_upsert = broker_branch_behavior._upsert_feature_snapshot
        stream_exhausted = False

        def observed_stream(*args, **kwargs):
            nonlocal stream_exhausted
            yield from original_stream(*args, **kwargs)
            stream_exhausted = True

        def checked_upsert(*args, **kwargs):
            self.assertTrue(stream_exhausted)
            return original_upsert(*args, **kwargs)

        with (
            patch.object(
                broker_branch_behavior,
                "_observation_stream",
                side_effect=observed_stream,
            ),
            patch.object(
                broker_branch_behavior,
                "_upsert_feature_snapshot",
                side_effect=checked_upsert,
            ),
        ):
            result = materialize_broker_branch_behavior_shadow(
                self.db,
                as_of_trade_date=self.second_date,
                lookback_sessions=2,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(stream_exhausted)


class BrokerBranchBehaviorSchedulerTests(unittest.TestCase):
    def test_scheduler_enqueues_only_shadow_job_after_raw_coverage_gate(self) -> None:
        target_date = date(2026, 8, 21)
        fake_db = SimpleNamespace(close=Mock())
        with (
            patch.object(
                scheduler,
                "expected_broker_branch_trade_date",
                return_value=target_date,
            ),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "get_taiwan_broker_branch_market_coverage",
                return_value={
                    "expected_count": 2000,
                    "covered_count": 1900,
                    "missing_count": 100,
                    "complete": False,
                },
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_behavior_lookback_sessions",
                120,
            ),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=91), True),
            ) as enqueue,
        ):
            scheduler.enqueue_taiwan_broker_branch_behavior_shadow()

        kwargs = enqueue.call_args.kwargs
        self.assertEqual(
            kwargs["job_type"],
            "research.tw_broker_branch_behavior_shadow",
        )
        self.assertEqual(
            kwargs["target"],
            "2026-08-21|broker_branch.behavior.shadow.v0",
        )
        self.assertEqual(kwargs["task_args"][0], target_date)
        self.assertEqual(kwargs["task_args"][1], 120)
        self.assertFalse(kwargs["request"]["advertised"])
        self.assertEqual(kwargs["request"]["external_fetches"], 0)
        fake_db.close.assert_called_once()

    def test_scheduler_skips_below_high_coverage_gate(self) -> None:
        target_date = date(2026, 8, 21)
        fake_db = SimpleNamespace(close=Mock())
        with (
            patch.object(
                scheduler,
                "expected_broker_branch_trade_date",
                return_value=target_date,
            ),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "get_taiwan_broker_branch_market_coverage",
                return_value={
                    "expected_count": 2000,
                    "covered_count": 1899,
                    "missing_count": 101,
                    "complete": False,
                },
            ),
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            scheduler.enqueue_taiwan_broker_branch_behavior_shadow()

        enqueue.assert_not_called()
        fake_db.close.assert_called_once()

    def test_shadow_scheduler_registration_is_explicitly_flagged(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(
                scheduler.settings,
                "enable_tw_broker_branch_behavior_shadow_scheduler",
                True,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_behavior_shadow_time",
                "20:15",
            ),
        ):
            added = scheduler._add_taiwan_broker_branch_behavior_shadow_job(
                fake_scheduler
            )

        self.assertTrue(added)
        call = fake_scheduler.add_job.call_args
        self.assertIs(
            call.args[0],
            scheduler.enqueue_taiwan_broker_branch_behavior_shadow,
        )
        self.assertEqual(call.kwargs["hour"], 20)
        self.assertEqual(call.kwargs["minute"], 15)
        self.assertEqual(call.kwargs["id"], "tw_broker_branch_behavior_shadow")

    def test_update_center_retry_preserves_methodology_and_bounds(self) -> None:
        request_payload = {
            "as_of_trade_date": "2026-08-21",
            "lookback_sessions": 120,
            "methodology_version": "broker_branch.behavior.shadow.v0",
        }
        job = SimpleNamespace(
            job_type="research.tw_broker_branch_behavior_shadow",
            target="2026-08-21|broker_branch.behavior.shadow.v0",
            request_json=json.dumps(request_payload),
        )

        with patch.object(
            jobs_router.service,
            "serialize_job",
            return_value={"request": request_payload},
        ):
            task, task_args, request = jobs_router._retry_config(job)

        self.assertIs(
            task,
            scheduler.backfill_tasks.run_taiwan_broker_branch_behavior_shadow_job,
        )
        self.assertEqual(
            task_args,
            (
                date(2026, 8, 21),
                120,
                "broker_branch.behavior.shadow.v0",
            ),
        )
        self.assertEqual(request["lookback_sessions"], 120)


if __name__ == "__main__":
    unittest.main()
