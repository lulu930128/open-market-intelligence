from __future__ import annotations

from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401

from types import SimpleNamespace
from concurrent.futures import Future
from threading import Event
from app.jobs.scheduler import SchedulerDrain
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.runtime import RuntimeCoordinator


def runtime_lock(*, acquired: bool = True) -> Mock:
    lock = Mock()
    lock.acquire.return_value = acquired
    return lock


def scheduler_receipt():
    done = Future()
    done.set_result(None)
    paused = Event()
    paused.set()
    return SchedulerDrain(done, paused)


class RuntimeCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_migrates_database_and_starts_background_leader(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        schema_lock = runtime_lock()
        background_lock = runtime_lock()

        with (
            patch("app.runtime.run_database_migrations") as run_migrations,
            patch("app.runtime.SessionLocal", return_value=fake_db),
            patch("app.runtime.job_service.mark_interrupted_jobs", return_value=2) as mark_interrupted,
            patch("app.runtime.job_service.read_paused_job_obligations", return_value={}) as read_paused,
            patch("app.runtime.job_service.resume_job_obligations", return_value=0) as resume_paused,
            patch.object(RuntimeCoordinator, "_reconcile_dispatch_runs") as reconcile_dispatch,
            patch("app.runtime.job_scheduler.start_scheduler", return_value="scheduler") as start_scheduler,
            patch("app.runtime.start_crypto_auto_refresh", new=AsyncMock()) as start_auto_refresh,
            patch(
                "app.runtime.start_crypto_realtime_collectors",
                new=AsyncMock(),
            ) as start_collectors,
            patch(
                "app.runtime.enqueue_stock_master_bootstrap_if_needed",
                return_value=(None, False),
            ) as enqueue_stock_master_bootstrap,
            patch("app.runtime.logger.info") as log_info,
        ):
            coordinator = RuntimeCoordinator(
                schema_lock=schema_lock,
                background_lock=background_lock,
            )
            await coordinator.start()

        schema_lock.acquire.assert_called_once_with(
            timeout_seconds=settings.runtime_schema_lock_timeout_seconds,
        )
        schema_lock.release.assert_called_once_with()
        run_migrations.assert_called_once_with()
        background_lock.acquire.assert_called_once_with(timeout_seconds=0)
        mark_interrupted.assert_called_once_with(fake_db)
        read_paused.assert_called_once_with(fake_db)
        resume_paused.assert_called_once_with({})
        reconcile_dispatch.assert_called_once_with()
        self.assertEqual(fake_db.close.call_count, 2)  # interrupted scan + read-only obligations
        start_scheduler.assert_called_once_with()
        start_auto_refresh.assert_awaited_once_with()
        start_collectors.assert_awaited_once_with()
        enqueue_stock_master_bootstrap.assert_called_once_with()
        log_info.assert_any_call(
            "Market Data Foundation runtime mode=%s.",
            settings.canonical_market_data_mode,
        )
        self.assertEqual(coordinator.scheduler, "scheduler")
        self.assertTrue(coordinator.background_leader)
        self.assertTrue(coordinator.started)

    async def test_follower_starts_without_background_components(self) -> None:
        schema_lock = runtime_lock()
        background_lock = runtime_lock(acquired=False)

        with (
            patch("app.runtime.run_database_migrations") as run_migrations,
            patch("app.runtime.SessionLocal") as session_local,
            patch("app.runtime.job_service.mark_interrupted_jobs") as mark_interrupted,
            patch("app.runtime.job_scheduler.start_scheduler") as start_scheduler,
            patch("app.runtime.start_crypto_auto_refresh", new=AsyncMock()) as start_auto_refresh,
            patch(
                "app.runtime.start_crypto_realtime_collectors",
                new=AsyncMock(),
            ) as start_collectors,
            patch(
                "app.runtime.enqueue_stock_master_bootstrap_if_needed",
                return_value=(None, False),
            ) as enqueue_stock_master_bootstrap,
            patch("app.runtime.stop_crypto_realtime_collectors", new=AsyncMock()) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler", return_value=scheduler_receipt()) as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            coordinator = RuntimeCoordinator(
                schema_lock=schema_lock,
                background_lock=background_lock,
            )
            await coordinator.start()
            await coordinator.stop()

        run_migrations.assert_called_once_with()
        session_local.assert_not_called()
        mark_interrupted.assert_not_called()
        start_scheduler.assert_not_called()
        start_auto_refresh.assert_not_awaited()
        start_collectors.assert_not_awaited()
        enqueue_stock_master_bootstrap.assert_not_called()
        stop_collectors.assert_not_awaited()
        stop_auto_refresh.assert_not_awaited()
        stop_scheduler.assert_not_called()
        background_lock.release.assert_not_called()
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertFalse(coordinator.background_leader)
        self.assertFalse(coordinator.started)

    async def test_stop_runs_every_leader_shutdown_step_and_retains_lock_until_exit(self) -> None:
        background_lock = runtime_lock()
        coordinator = RuntimeCoordinator(
            schema_lock=runtime_lock(),
            background_lock=background_lock,
        )
        coordinator.scheduler = "scheduler"
        coordinator.started = True
        coordinator.background_leader = True

        with (
            patch("app.runtime.stop_crypto_realtime_collectors", new=AsyncMock()) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler", return_value=scheduler_receipt()) as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            await coordinator.stop()

        stop_collectors.assert_awaited_once_with(drain=True)
        stop_auto_refresh.assert_awaited_once_with(drain=True)
        stop_scheduler.assert_called_once_with("scheduler")
        background_lock.release.assert_not_called()
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertEqual(coordinator.scheduler, "scheduler")
        self.assertTrue(coordinator.background_leader)
        self.assertFalse(coordinator.started)

    async def test_start_cleans_up_started_components_after_late_failure(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        schema_lock = runtime_lock()
        background_lock = runtime_lock()

        with (
            patch("app.runtime.run_database_migrations"),
            patch("app.runtime.SessionLocal", return_value=fake_db),
            patch("app.runtime.job_service.mark_interrupted_jobs", return_value=0),
            patch("app.runtime.job_service.read_paused_job_obligations", return_value={}),
            patch("app.runtime.job_service.resume_job_obligations") as resume_paused,
            patch.object(RuntimeCoordinator, "_reconcile_dispatch_runs"),
            patch("app.runtime.job_scheduler.start_scheduler", return_value="scheduler"),
            patch("app.runtime.start_crypto_auto_refresh", new=AsyncMock()),
            patch(
                "app.runtime.start_crypto_realtime_collectors",
                new=AsyncMock(side_effect=RuntimeError("collector startup failed")),
            ),
            patch("app.runtime.stop_crypto_realtime_collectors", new=AsyncMock()) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler", return_value=scheduler_receipt()) as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            coordinator = RuntimeCoordinator(
                schema_lock=schema_lock,
                background_lock=background_lock,
            )
            with self.assertRaises(RuntimeError):
                await coordinator.start()

        stop_collectors.assert_awaited_once_with(drain=True)
        resume_paused.assert_not_called()
        stop_auto_refresh.assert_awaited_once_with(drain=True)
        stop_scheduler.assert_called_once_with("scheduler")
        background_lock.release.assert_not_called()
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertEqual(coordinator.scheduler, "scheduler")
        self.assertTrue(coordinator.background_leader)
        self.assertFalse(coordinator.started)

    async def test_stop_attempts_remaining_steps_after_shutdown_error(self) -> None:
        background_lock = runtime_lock()
        coordinator = RuntimeCoordinator(
            schema_lock=runtime_lock(),
            background_lock=background_lock,
        )
        coordinator.scheduler = "scheduler"
        coordinator.started = True
        coordinator.background_leader = True

        with (
            patch(
                "app.runtime.stop_crypto_realtime_collectors",
                new=AsyncMock(side_effect=RuntimeError("collector failed")),
            ) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler", return_value=scheduler_receipt()) as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            with self.assertRaises(RuntimeError):
                await coordinator.stop()

        stop_collectors.assert_awaited_once_with(drain=True)
        stop_auto_refresh.assert_awaited_once_with(drain=True)
        stop_scheduler.assert_called_once_with("scheduler")
        background_lock.release.assert_not_called()
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertEqual(coordinator.scheduler, "scheduler")
        self.assertTrue(coordinator.background_leader)
        self.assertFalse(coordinator.started)


if __name__ == "__main__":
    unittest.main()
