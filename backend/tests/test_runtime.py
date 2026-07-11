from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.runtime import RuntimeCoordinator


class RuntimeCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_initializes_database_and_background_components(self) -> None:
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch("app.runtime.run_database_migrations") as run_migrations,
            patch("app.runtime.init_db") as init_db,
            patch("app.runtime.SessionLocal", return_value=fake_db),
            patch("app.runtime.job_service.mark_interrupted_jobs", return_value=2) as mark_interrupted,
            patch("app.runtime.job_scheduler.start_scheduler", return_value="scheduler") as start_scheduler,
            patch("app.runtime.start_crypto_auto_refresh", new=AsyncMock()) as start_auto_refresh,
            patch(
                "app.runtime.start_crypto_realtime_collectors",
                new=AsyncMock(),
            ) as start_collectors,
        ):
            coordinator = RuntimeCoordinator()
            await coordinator.start()

        run_migrations.assert_called_once_with()
        init_db.assert_called_once_with()
        mark_interrupted.assert_called_once_with(fake_db)
        fake_db.close.assert_called_once_with()
        start_scheduler.assert_called_once_with()
        start_auto_refresh.assert_awaited_once_with()
        start_collectors.assert_awaited_once_with()
        self.assertEqual(coordinator.scheduler, "scheduler")
        self.assertTrue(coordinator.started)

    async def test_stop_runs_every_shutdown_step(self) -> None:
        coordinator = RuntimeCoordinator()
        coordinator.scheduler = "scheduler"
        coordinator.started = True

        with (
            patch("app.runtime.stop_crypto_realtime_collectors", new=AsyncMock()) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler") as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            await coordinator.stop()

        stop_collectors.assert_awaited_once_with()
        stop_auto_refresh.assert_awaited_once_with()
        stop_scheduler.assert_called_once_with("scheduler")
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertIsNone(coordinator.scheduler)
        self.assertFalse(coordinator.started)

    async def test_start_cleans_up_started_components_after_late_failure(self) -> None:
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch("app.runtime.run_database_migrations"),
            patch("app.runtime.init_db"),
            patch("app.runtime.SessionLocal", return_value=fake_db),
            patch("app.runtime.job_service.mark_interrupted_jobs", return_value=0),
            patch("app.runtime.job_scheduler.start_scheduler", return_value="scheduler"),
            patch("app.runtime.start_crypto_auto_refresh", new=AsyncMock()),
            patch(
                "app.runtime.start_crypto_realtime_collectors",
                new=AsyncMock(side_effect=RuntimeError("collector startup failed")),
            ),
            patch("app.runtime.stop_crypto_realtime_collectors", new=AsyncMock()) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler") as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            coordinator = RuntimeCoordinator()
            with self.assertRaises(RuntimeError):
                await coordinator.start()

        stop_collectors.assert_awaited_once_with()
        stop_auto_refresh.assert_awaited_once_with()
        stop_scheduler.assert_called_once_with("scheduler")
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertIsNone(coordinator.scheduler)
        self.assertFalse(coordinator.started)

    async def test_stop_attempts_remaining_steps_after_shutdown_error(self) -> None:
        coordinator = RuntimeCoordinator()
        coordinator.scheduler = "scheduler"
        coordinator.started = True

        with (
            patch(
                "app.runtime.stop_crypto_realtime_collectors",
                new=AsyncMock(side_effect=RuntimeError("collector failed")),
            ) as stop_collectors,
            patch("app.runtime.stop_crypto_auto_refresh", new=AsyncMock()) as stop_auto_refresh,
            patch("app.runtime.job_scheduler.stop_scheduler") as stop_scheduler,
            patch("app.runtime.job_service.shutdown_job_executor") as shutdown_executor,
        ):
            with self.assertRaises(RuntimeError):
                await coordinator.stop()

        stop_collectors.assert_awaited_once_with()
        stop_auto_refresh.assert_awaited_once_with()
        stop_scheduler.assert_called_once_with("scheduler")
        shutdown_executor.assert_called_once_with(wait=False)
        self.assertIsNone(coordinator.scheduler)
        self.assertFalse(coordinator.started)


if __name__ == "__main__":
    unittest.main()
