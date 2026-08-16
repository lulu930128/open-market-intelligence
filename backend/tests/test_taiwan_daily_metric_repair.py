from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    JobRun,
    MarketDailyPrice,
    SourceRegistry,
)
from app.jobs import backfill_tasks, service as job_service
from app.jobs import taiwan_daily_metric_repair as repair
from app.market.daily_metrics_backfill import ensure_latest_daily_metrics


EXPECTED = date(2026, 8, 13)
STALE = date(2026, 8, 12)


class TaiwanDailyMetricRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.source = SourceRegistry(
            source_name="TWSE institutional fixture",
            source_type="http",
            category="institutional_trade",
            endpoint_url="https://example.invalid",
            enabled=True,
            parser_type="twse_institutional_trade",
        )
        self.db.add(self.source)
        self.db.flush()
        self._add_market_price(STALE)
        self._add_institutional(STALE)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_market_price(self, trade_date: date) -> None:
        self.db.add(
            MarketDailyPrice(
                source_id=self.source.id,
                raw_result_id=1,
                stock_id="2330",
                trade_date=trade_date,
                close_price=100.0,
            )
        )

    def _add_institutional(self, trade_date: date) -> None:
        self.db.add(
            InstitutionalTradeDaily(
                source_id=self.source.id,
                raw_result_id=1,
                stock_id="2330",
                trade_date=trade_date,
            )
        )

    def test_expected_date_is_fetched_even_when_market_price_max_is_stale(self) -> None:
        def refresh_source(*, db: Session, source_id: int, trade_date: date) -> dict:
            self.assertEqual(trade_date, EXPECTED)
            db.add(
                InstitutionalTradeDaily(
                    source_id=source_id,
                    raw_result_id=2,
                    stock_id="2330",
                    trade_date=trade_date,
                )
            )
            db.flush()
            return {
                "fetch_status": "success",
                "parse_status": "success",
                "inserted_count": 1,
                "raw_result_id": 2,
            }

        with patch(
            "app.market.daily_metrics_backfill.refresh_source",
            side_effect=refresh_source,
        ) as refresh:
            result = ensure_latest_daily_metrics(
                self.db,
                categories=["institutional_trade"],
                expected_trade_date=EXPECTED,
                include_today=True,
                sleep_seconds=0,
            )

        refresh.assert_called_once()
        self.assertEqual(result["end_date"], EXPECTED)
        self.assertTrue(result["postcondition_met"])
        self.assertEqual(result["postcondition"]["coverage_ratio"], 1.0)

    def test_missing_expected_date_is_not_reported_as_success(self) -> None:
        with patch(
            "app.market.daily_metrics_backfill.refresh_source",
            return_value={
                "fetch_status": "success",
                "parse_status": "success",
                "inserted_count": 0,
            },
        ):
            result = ensure_latest_daily_metrics(
                self.db,
                categories=["institutional_trade"],
                expected_trade_date=EXPECTED,
                include_today=True,
                sleep_seconds=0,
            )

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["postcondition_met"])
        self.assertEqual(result["observed_max_trade_date"], STALE)
        self.assertEqual(result["postcondition"]["missing_source_ids"], [self.source.id])

    def test_worker_raises_structured_failure_when_postcondition_is_missing(self) -> None:
        captured: list[Exception] = []

        def run_inline(_job_id: int, worker) -> None:
            try:
                worker(self.db, lambda *_args: None)
            except Exception as exc:  # assertion inspects the exact contract below
                captured.append(exc)

        with (
            patch.object(backfill_tasks, "run_tracked_job", side_effect=run_inline),
            patch.object(
                backfill_tasks,
                "ensure_latest_daily_metrics",
                return_value={
                    "status": "error",
                    "postcondition_met": False,
                    "postcondition": {
                        "postcondition_met": False,
                        "observed_max_trade_date": STALE,
                        "coverage_ratio": 0.0,
                    },
                },
            ),
        ):
            backfill_tasks.run_market_daily_metrics_job(
                7,
                None,
                None,
                ["institutional_trade"],
                7,
                True,
                0,
                True,
                EXPECTED,
                None,
            )

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], job_service.JobExecutionError)
        self.assertEqual(captured[0].result["postcondition"]["coverage_ratio"], 0.0)

    def test_repair_plan_honors_active_lease_backoff_and_max_attempts(self) -> None:
        now = datetime(2026, 8, 13, 22, 0, tzinfo=timezone.utc)
        spec = repair.REPAIR_SPECS[0]
        ready = repair.plan_taiwan_daily_metric_repair(
            self.db,
            spec=spec,
            expected_trade_date=EXPECTED,
            now=now,
        )
        self.assertEqual(ready["status"], "ready")

        active = job_service.create_job(
            self.db,
            job_type=spec.job_type,
            target=EXPECTED.isoformat(),
            request={"schedule": spec.schedule},
        )
        leased = repair.plan_taiwan_daily_metric_repair(
            self.db,
            spec=spec,
            expected_trade_date=EXPECTED,
            now=now,
        )
        self.assertEqual(leased["status"], "leased")
        self.assertEqual(leased["active_job_id"], active.id)

        active.status = "error"
        active.ended_at = now
        self.db.commit()
        with patch.object(repair.settings, "scheduler_market_daily_repair_max_attempts", 2):
            for attempt in (1, 2):
                job = job_service.create_job(
                    self.db,
                    job_type=spec.job_type,
                    target=EXPECTED.isoformat(),
                    request={
                        "repair": {
                            "repair_key": ready["repair_key"],
                            "attempt": attempt,
                            "detected_at": now.isoformat(),
                        }
                    },
                )
                job.status = "error"
                job.ended_at = now
                self.db.commit()

            exhausted = repair.plan_taiwan_daily_metric_repair(
                self.db,
                spec=spec,
                expected_trade_date=EXPECTED,
                now=now + timedelta(hours=3),
            )

        self.assertEqual(exhausted["status"], "exhausted")
        self.assertEqual(exhausted["attempt_count"], 2)

    def test_recent_provider_error_suppresses_first_repair_attempt(self) -> None:
        now = datetime(2026, 8, 13, 22, 0, tzinfo=timezone.utc)
        self.source.last_error_at = now - timedelta(minutes=2)
        self.source.last_error_message = "HTTP 429 rate limit"
        self.db.commit()

        decision = repair.plan_taiwan_daily_metric_repair(
            self.db,
            spec=repair.REPAIR_SPECS[0],
            expected_trade_date=EXPECTED,
            now=now,
        )

        self.assertEqual(decision["status"], "suppressed")
        self.assertEqual(decision["reason"], "provider_cooldown")
        self.assertTrue(decision["provider_guard"]["sources"][0]["circuit_open"])

    def test_startup_reconciliation_enqueues_one_exact_bounded_repair(self) -> None:
        now = datetime(2026, 8, 13, 22, 0, tzinfo=timezone.utc)
        spec = repair.REPAIR_SPECS[0]
        with (
            patch.object(repair, "REPAIR_SPECS", (spec,)),
            patch.object(
                repair,
                "build_taiwan_calendar_status",
                return_value={"phase": "post_close"},
            ),
            patch.object(
                repair,
                "expected_trade_date_from_calendar",
                return_value=EXPECTED,
            ),
            patch.object(
                repair,
                "is_release_released_from_calendar",
                return_value=True,
            ),
            patch.object(
                repair,
                "resolve_market_refresh_interval_seconds",
                return_value=0.2,
            ),
            patch.object(
                repair.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=73), True),
            ) as enqueue,
        ):
            result = repair.reconcile_taiwan_daily_metric_repairs(
                self.db,
                now=now,
                trigger="startup",
            )

        self.assertEqual(result["queued_count"], 1)
        request = enqueue.call_args.kwargs["request"]
        task_args = enqueue.call_args.kwargs["task_args"]
        self.assertEqual(enqueue.call_args.kwargs["target"], EXPECTED.isoformat())
        self.assertEqual(request["start_date"], EXPECTED)
        self.assertEqual(request["end_date"], EXPECTED)
        self.assertEqual(request["repair"]["attempt"], 1)
        self.assertEqual(request["repair"]["trigger"], "startup")
        self.assertEqual(task_args[7], EXPECTED)


class StructuredJobFailureTests(unittest.TestCase):
    def test_run_tracked_job_persists_structured_failure_result(self) -> None:
        fake_db = Mock()
        evidence = {"postcondition_met": False, "expected_trade_date": EXPECTED}

        def worker(_db, _progress):
            raise job_service.JobExecutionError("expected date missing", result=evidence)

        with (
            patch.object(job_service, "SessionLocal", return_value=fake_db),
            patch.object(job_service, "start_job"),
            patch.object(job_service, "fail_job") as fail,
        ):
            job_service.run_tracked_job(91, worker)

        fail.assert_called_once_with(
            fake_db,
            91,
            error_message="expected date missing",
            result=evidence,
        )
        fake_db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
