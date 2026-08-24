from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    BrokerBranchBehaviorFeatureSnapshot,
    BrokerBranchSnapshotQuality,
    SourceRegistry,
)
from app.market.broker_branch_behavior import (
    BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
)
from app.market.broker_branch_calibration import (
    DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY,
    build_broker_branch_readiness_report,
    build_broker_branch_walk_forward_splits,
    render_broker_branch_readiness_markdown,
)
from app.market.broker_branch_quality import (
    BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
    BROKER_BRANCH_COVERAGE_CENSORED,
    BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
    BROKER_BRANCH_FETCH_SUCCESS,
    NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
)
from app.market.trading_calendar import previous_taiwan_trading_day


UTC = timezone.utc


def _trading_sessions(as_of: date, count: int) -> list[date]:
    result: list[date] = []
    current = previous_taiwan_trading_day(as_of, include_value=True)
    for _ in range(count):
        result.append(current)
        current = previous_taiwan_trading_day(current, include_value=False)
    return sorted(result)


class BrokerBranchCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.as_of = date(2026, 8, 21)
        self.source = SourceRegistry(
            source_name="nstock_broker_branch",
            source_type="http_api",
            category="broker_branch_trade",
        )
        self.db.add(self.source)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_snapshot(self, *, high_coverage_sessions: int = 25) -> None:
        sessions = _trading_sessions(self.as_of, high_coverage_sessions)
        for trade_date in sessions:
            self.db.add(
                BrokerBranchSnapshotQuality(
                    source_id=self.source.id,
                    stock_id="2330",
                    expected_trade_date=trade_date,
                    provider_trade_date=trade_date,
                    fetched_at=datetime(2026, 8, 21, 10, tzinfo=UTC),
                    coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
                    buy_rank_limit=15,
                    sell_rank_limit=15,
                    observed_branch_count=4,
                    absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
                    coverage_status=BROKER_BRANCH_COVERAGE_CENSORED,
                    fetch_status=BROKER_BRANCH_FETCH_SUCCESS,
                    source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
                    warnings_json='["ranked_top_n_absence_is_censored"]',
                )
            )
        self.db.add(
            BrokerBranchBehaviorFeatureSnapshot(
                source_id=self.source.id,
                branch_identity_key=f"{self.source.id}:SECRET001",
                branch_code="SECRET001",
                scope_type="global",
                scope_id="TW",
                as_of_trade_date=self.as_of,
                lookback_sessions=120,
                methodology_version=BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
                observation_count=300,
                eligible_initial_count=200,
                reobserved_count=100,
                opposite_observed_count=40,
                same_direction_observed_count=60,
                censored_count=100,
                session_count=high_coverage_sessions,
                stock_count=40,
                gross_visible_lots=500,
                net_visible_lots=100,
                reappearance_rate=0.5,
                reverse_given_reappearance_rate=0.4,
                same_direction_given_reappearance_rate=0.6,
                censored_rate=0.5,
                gross_netting_ratio=0.8,
                observed_sequence_persistence=0.6,
                max_stock_observation_share=0.05,
                candidate_session_count=120,
                high_coverage_session_count=high_coverage_sessions,
                universe_count=1,
                min_session_coverage_ratio=0.0,
                coverage_status="partial_window",
                history_status="exploratory_only",
                calibration_status="uncalibrated",
                decision_usable=False,
                source_as_of=max(sessions),
                derived_as_of=self.as_of,
                computed_at=datetime(2026, 8, 21, 11, tzinfo=UTC),
                input_fingerprint="a" * 64,
                warnings_json=json.dumps(
                    [
                        "shadow_only_not_advertised",
                        "ranked_top_n_absence_is_censored",
                    ]
                ),
            )
        )
        self.db.commit()

    def test_exploratory_report_is_deterministic_aggregate_only_and_read_only(
        self,
    ) -> None:
        self._add_snapshot()
        statements: list[str] = []

        def capture_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(str(statement).strip())

        event.listen(self.engine, "before_cursor_execute", capture_statement)
        try:
            pending = SourceRegistry(
                source_name="must_not_autoflush",
                source_type="test",
                category="test",
            )
            self.db.add(pending)
            first = build_broker_branch_readiness_report(self.db)
            second = build_broker_branch_readiness_report(self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture_statement)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "exploratory_only")
        self.assertEqual(first["evidence"]["high_coverage_session_count"], 25)
        self.assertEqual(first["evidence"]["profile_gate_eligible_count"], 1)
        self.assertEqual(first["walk_forward"]["split_count"], 0)
        self.assertEqual(first["promotion"]["decision"], "shadow_only")
        self.assertFalse(first["promotion"]["production_ready"])
        self.assertFalse(first["promotion"]["advertise_behavior"])
        self.assertEqual(first["boundaries"]["database_writes"], 0)
        self.assertIsNone(pending.id)
        self.assertNotIn("SECRET001", json.dumps(first, ensure_ascii=False))
        self.assertTrue(statements)
        self.assertTrue(
            all(statement.upper().startswith("SELECT") for statement in statements),
            statements,
        )

    def test_report_fingerprint_excludes_operational_compute_time(self) -> None:
        self._add_snapshot()
        first = build_broker_branch_readiness_report(self.db)
        feature = self.db.query(BrokerBranchBehaviorFeatureSnapshot).one()
        feature.computed_at = datetime(2026, 8, 21, 12, tzinfo=UTC)
        self.db.commit()

        second = build_broker_branch_readiness_report(self.db)

        self.assertNotEqual(
            first["evidence"]["sources"][0]["computed_at_max"],
            second["evidence"]["sources"][0]["computed_at_max"],
        )
        self.assertEqual(
            first["evidence_fingerprint"],
            second["evidence_fingerprint"],
        )

    def test_requested_as_of_requires_exact_materialized_snapshot(self) -> None:
        self._add_snapshot()

        report = build_broker_branch_readiness_report(
            self.db,
            as_of_trade_date=self.as_of - timedelta(days=1),
        )

        self.assertEqual(report["status"], "snapshot_missing")
        self.assertEqual(report["evidence"]["profile_count"], 0)
        self.assertIn(
            "materialized_feature_snapshot_missing",
            report["promotion"]["blocked_by"],
        )

    def test_walk_forward_plan_has_purge_embargo_and_never_claims_validation(
        self,
    ) -> None:
        dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(125)]

        splits = build_broker_branch_walk_forward_splits(dates)

        self.assertGreaterEqual(
            len(splits),
            DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY.minimum_walk_forward_splits,
        )
        first = splits[0]
        self.assertLess(first.train_end, first.validation_start)
        self.assertLess(first.validation_end, first.test_start)
        self.assertEqual(
            (first.validation_start - first.train_end).days,
            DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY.purge_sessions + 1,
        )
        self.assertEqual(
            (first.test_start - first.validation_end).days,
            DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY.purge_sessions
            + DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY.embargo_sessions
            + 1,
        )

    def test_markdown_keeps_no_go_and_boundaries_visible(self) -> None:
        self._add_snapshot()
        report = build_broker_branch_readiness_report(self.db)

        rendered = render_broker_branch_readiness_markdown(report)

        self.assertIn("Promotion：`shadow_only`", rendered)
        self.assertIn("Provider fetch：`0`", rendered)
        self.assertIn("Database write：`0`", rendered)
        self.assertIn("unknown_not_ranked", rendered)


if __name__ == "__main__":
    unittest.main()
