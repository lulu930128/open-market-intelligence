from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
import math
import time
import logging
from typing import Any, AsyncIterator, Protocol

from fastapi import FastAPI

from app.crypto_market.auto_refresh import start_crypto_auto_refresh, stop_crypto_auto_refresh
from app.crypto_market.ws_runtime import (
    start_crypto_realtime_collectors,
    stop_crypto_realtime_collectors,
)
from app.db.migrations import run_database_migrations
from app.db.session import SessionLocal
from app.db import session as session_owner
from app.market.providers.fugle_realtime_runtime import (
    start_fugle_realtime,
    stop_fugle_realtime,
)
from app.jobs import scheduler as job_scheduler, service as job_service
from app.jobs import us_intraday_materializer_scheduler as intraday_publisher
from app.config import settings
from app.runtime_lock import ProcessFileLock
from app.stocks.bootstrap import enqueue_stock_master_bootstrap_if_needed


logger = logging.getLogger(__name__)


class RuntimeLock(Protocol):
    def acquire(
        self,
        *,
        timeout_seconds: float = 0,
        poll_interval_seconds: float = 0.05,
    ) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class RuntimeDrainResult:
    state: str
    background_leader: bool
    scheduler_admission_stopped: bool | None
    scheduler_state: str
    jobs: job_service.JobDrainResult
    collectors: dict[str, str]
    background_ownership_retained: bool
    publisher: intraday_publisher.PublisherDrainResult
    job_executor_state: str = "drained"
    sessions: session_owner.SessionDrainResult | None = None
    collector_data_completeness: str = "NOT_ATTESTED"
    all_writers_drained: bool = False
    unknown_writers: tuple[str, ...] = (
        "API/direct transactions", "other processes/checkout/scripts", "external provider runtimes",
    )


class RuntimeDrainError(RuntimeError):
    def __init__(self, result: RuntimeDrainResult) -> None:
        super().__init__("Runtime registered-owner drain incomplete; ownership retained")
        self.result = result


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        schema_lock: RuntimeLock | None = None,
        background_lock: RuntimeLock | None = None,
        drain_owned_sessions: bool = False,
    ) -> None:
        lock_dir = settings.runtime_lock_dir
        self.schema_lock = schema_lock or ProcessFileLock(lock_dir / "schema.lock")
        self.background_lock = background_lock or ProcessFileLock(lock_dir / "background.lock")
        self.scheduler: Any | None = None
        self.started = False
        self.background_leader = False
        self._stop_task: asyncio.Task | None = None
        self._collector_stops: dict[str, asyncio.Task] = {}
        self._scheduler_drain: job_scheduler.SchedulerDrain | None = None
        self.drain_result: RuntimeDrainResult | None = None
        # Private opt-in seam, paired with get_draining_db in disposable fixtures.
        # Default lifespan does not enable it or replace the API dependency.
        self._drain_owned_sessions = drain_owned_sessions

    async def start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError("Runtime drain is terminal; new process lifecycle required")
        job_service.require_job_admission()
        intraday_publisher.require_intraday_publisher_admission()
        if self._drain_owned_sessions:
            session_owner.require_session_scope_admission()
        if self.started:
            return

        logger.info(
            "Market Data Foundation runtime mode=%s.",
            settings.canonical_market_data_mode,
        )
        try:
            if not self.schema_lock.acquire(
                timeout_seconds=settings.runtime_schema_lock_timeout_seconds,
            ):
                raise RuntimeError(
                    "Timed out waiting for the database schema migration lock."
                )
            try:
                run_database_migrations()
            finally:
                self.schema_lock.release()

            self.background_leader = self.background_lock.acquire(timeout_seconds=0)
            if not self.background_leader:
                self.started = True
                logger.info(
                    "Runtime started as an API worker; background ownership is held by another process."
                )
                return

            self._mark_interrupted_jobs()
            self._reconcile_dispatch_runs()

            self.scheduler = job_scheduler.start_scheduler()
            await start_crypto_auto_refresh()
            await start_crypto_realtime_collectors()
            await start_fugle_realtime()
            self._enqueue_stock_master_bootstrap()
            self.started = True
        except Exception:
            logger.exception("Runtime startup failed; cleaning up started components.")
            try:
                await self.stop()
            except Exception:
                logger.exception("Runtime cleanup after startup failure also failed.")
            raise

    async def stop(self, *, timeout_seconds: float = 30.0) -> RuntimeDrainResult:
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("Drain timeout must be finite and non-negative")
        if self._stop_task is None:
            # Close admission synchronously, before any await or collector stop.
            job_service.begin_job_drain()
            intraday_publisher.begin_intraday_publisher_drain()
            if self._drain_owned_sessions:
                session_owner.begin_session_scope_drain()
            self._stop_task = asyncio.create_task(
                self._drain(time.monotonic() + timeout_seconds), name="omi-runtime-drain",
            )
        # Caller cancellation must not cancel the actual owner shutdown.
        result = await asyncio.shield(self._stop_task)
        self.drain_result = result
        if result.state != "REGISTERED_DRAINED":
            raise RuntimeDrainError(result)
        return result

    async def _drain(self, deadline: float) -> RuntimeDrainResult:
        scheduler_state = "not_owned"
        scheduler_admission = None
        if self.background_leader:
            try:
                self._scheduler_drain = job_scheduler.stop_scheduler(self.scheduler)
                while (
                    not self._scheduler_drain.admission_stopped.is_set()
                    and not self._scheduler_drain.completion.done()
                    and time.monotonic() < deadline
                ):
                    await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            except Exception:
                scheduler_state = "error"
                logger.exception("Failed to initiate scheduler drain.")
            for name, stop_step in (
                ("Fugle realtime", stop_fugle_realtime),
                ("crypto realtime collectors", stop_crypto_realtime_collectors),
                ("crypto auto refresh", stop_crypto_auto_refresh),
            ):
                try:
                    self._collector_stops[name] = asyncio.create_task(stop_step(drain=True))
                except Exception as exc:
                    async def failed_stop(error=exc):
                        raise error
                    self._collector_stops[name] = asyncio.create_task(failed_stop())

        job_state = "drained"
        try:
            jobs = await job_service.drain_job_executor(deadline=deadline)
            if not jobs.drained:
                job_state = "incomplete"
        except Exception:
            job_state = "error"
            jobs = job_service.job_drain_status()
            logger.exception("Job executor drain failed.")
        pending = {task for task in self._collector_stops.values() if not task.done()}
        if pending:
            await asyncio.wait(pending, timeout=max(0.0, deadline - time.monotonic()))
        if self._scheduler_drain is not None:
            while not self._scheduler_drain.completion.done() and time.monotonic() < deadline:
                await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            scheduler_admission = self._scheduler_drain.admission_stopped.is_set()
            if not self._scheduler_drain.completion.done():
                scheduler_state = "timeout"
            elif self._scheduler_drain.completion.exception() is not None:
                scheduler_state = "error"
            else:
                scheduler_state = "drained"
        collectors = {}
        for name, task in self._collector_stops.items():
            if not task.done():
                collectors[name] = "timeout"
                # Retrieve later exceptions without discarding the owner reference.
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            elif task.cancelled() or task.exception() is not None:
                collectors[name] = "error"
            else:
                collectors[name] = "drained"
        try:
            publisher = await intraday_publisher.drain_intraday_publishers(deadline=deadline)
        except Exception:
            logger.exception("US intraday publisher drain failed.")
            publisher = intraday_publisher.PublisherDrainResult(
                "unknown", True, (), (), (), 0, 0, 0,
            )
        sessions = None
        if self._drain_owned_sessions:
            try:
                sessions = await session_owner.drain_session_scopes(deadline=deadline)
            except Exception:
                logger.exception("Explicit Session owner drain failed.")
                sessions = session_owner.SessionDrainResult("unknown", True, (), 0, 0)
        complete = (
            job_state == "drained" and jobs.drained and scheduler_state in {"not_owned", "drained"}
            and all(value == "drained" for value in collectors.values())
            and publisher.drained
            and (not self._drain_owned_sessions or sessions.drained)
        )
        self.started = False
        # Even a registered-owner success is not process exit or API quiescence.
        # Keep the OS-backed background lock until process exit. No same-process rearm.
        result = RuntimeDrainResult(
            "REGISTERED_DRAINED" if complete else "INCOMPLETE",
            self.background_leader, scheduler_admission, scheduler_state, jobs,
            collectors, self.background_leader, publisher, job_state, sessions,
        )
        self.drain_result = result
        return result

    def _mark_interrupted_jobs(self) -> None:
        with self._startup_session() as db:
            interrupted_count = job_service.mark_interrupted_jobs(db)

        if interrupted_count:
            logger.warning(
                "Marked %s interrupted queued/running jobs as error.",
                interrupted_count,
            )

    def _reconcile_dispatch_runs(self) -> None:
        if not (
            settings.enable_dispatch_scheduler
            and settings.dispatch_scheduler_v2_enabled
        ):
            return

        from app.dispatch import schedule_runs, service as dispatch_service

        with self._startup_session() as db:
            initialized_count = schedule_runs.initialize_next_runs(db)
            result = dispatch_service.reconcile_schedule_runs(db=db)

        if initialized_count or any(
            result.get(key)
            for key in (
                "processed_count",
                "recovered_count",
                "unknown_count",
                "error_count",
            )
        ):
            logger.info(
                "Dispatch startup reconciliation initialized=%s processed=%s "
                "recovered=%s unknown=%s errors=%s.",
                initialized_count,
                result.get("processed_count", 0),
                result.get("recovered_count", 0),
                result.get("unknown_count", 0),
                result.get("error_count", 0),
            )

    def _startup_session(self):
        if self._drain_owned_sessions:
            return session_owner.owned_session("runtime_startup", session_factory=SessionLocal)
        return closing(SessionLocal())

    def _enqueue_stock_master_bootstrap(self) -> None:
        try:
            job_id, created = enqueue_stock_master_bootstrap_if_needed()
        except Exception:
            logger.exception(
                "Failed to inspect or enqueue the first-run stock master bootstrap."
            )
            return

        if job_id is not None:
            logger.info(
                "First-run stock master bootstrap %s. job_id=%s",
                "queued" if created else "deduped",
                job_id,
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = RuntimeCoordinator()
    app.state.runtime = runtime
    await runtime.start()

    try:
        yield
    finally:
        await runtime.stop()
