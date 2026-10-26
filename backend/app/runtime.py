from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, replace
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
from app.db.admission import sqlite_admission
from app.db.quiescence import SQLiteWriterLease
from app.runtime_admission import AsyncAdmission, detached_admission
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
UNATTESTED_WRITERS = (
    "noncanonical Engine/raw DBAPI/escaped borrowers and driver-close completion",
    "other processes/checkout/scripts", "external provider runtimes",
)


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
    unknown_writers: tuple[str, ...] = UNATTESTED_WRITERS
    engine_connections: Any | None = None


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
        drain_engine_connections: bool = False,
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
        # Production lifespan enables both fences. Private fixtures can isolate
        # owner subsets; neither option grants global restart authority.
        self._drain_owned_sessions = drain_owned_sessions
        self._drain_engine_connections = drain_engine_connections
        self.http_admission = AsyncAdmission()
        self.http_ownership_unknown = False
        self._restart_undo = []
        self._restart_gates = []
        self._restart_guard = None
        self._restart_preparing = False
        self._restart_committed = False
        self._restart_deadline = 0.0
        self._restart_expiry = None
        self._restart_owner_commits = []
        self._restart_rearmed = False

    def owned_restart_preflight(self) -> dict[str, object]:
        """Capability observation, never evidence that PREPARE has completed."""
        import sys
        state = ""
        if not getattr(sys.modules.get("_omi_owned_release"), "verified", False):
            state = "OWNED_BOOTSTRAP_REQUIRED"
        elif not (self.started and self._drain_owned_sessions and self._drain_engine_connections):
            state = "WRITER_ADMISSION_NOT_ATTESTED"
        elif self.http_ownership_unknown or self._stop_task is not None:
            state = "ALL_WRITERS_DRAIN_UNAVAILABLE"
        elif self._restart_undo and not self._restart_preparing and self._restart_guard is None:
            state = "REARM_UNKNOWN"
        return {"state": state,
                "sqlite": sqlite_admission.observation(),
                "terminal_drain_started": self._stop_task is not None}

    def _scheduler_inflight_evidence(self, max_jobs: int = 12, *, expected_lease: Any = None) -> dict[str, object]:
        """Failure-only diagnostic of the same executor instances used by quiescence.

        Do not copy job arguments, database contents, or private runtime state.
        This observation NEVER grants restart authority.
        """
        scheduler = self.scheduler
        if scheduler is None:
            return {"state": "UNVERIFIED"}
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
        try:
            with scheduler._omi_admission_lock:
                scheduler_state = scheduler.state
                lease_matches = (expected_lease is scheduler._omi_pause
                                 if expected_lease is not None else None)
                if scheduler._omi_pause is None or scheduler_state != 2:
                    return {"state": "NOT_PAUSED", "scheduler_state": scheduler_state,
                            "lease_matches": lease_matches}
                jobs: list[tuple[str, str, int]] = []
                omitted = 0
                total = 0
                raw_keys = 0
                zero_keys = 0
                invalid_keys = 0
                with scheduler._executors_lock:
                    for alias, executor in scheduler._executors.items():
                        with executor._lock:
                            for job_id, instances in executor._instances.items():
                                raw_keys += 1
                                if type(instances) is not int or instances < 0:
                                    invalid_keys += 1
                                    continue
                                if instances == 0:
                                    zero_keys += 1
                                    continue
                                total += instances
                                if len(jobs) < max_jobs:
                                    label = str(job_id)
                                    safe_id = label if 0 < len(label) <= 80 and all(c in allowed for c in label) else "[redacted]"
                                    safe_executor = str(alias)
                                    safe_executor = (safe_executor if 0 < len(safe_executor) <= 32
                                                     and all(c in allowed for c in safe_executor) else "[redacted]")
                                    jobs.append((safe_executor, safe_id, instances))
                                else:
                                    omitted += 1
                reason = ("LEASE_MISMATCH" if lease_matches is False else
                          "INVALID_INSTANCE_COUNT" if invalid_keys else
                          "ACTIVE_INSTANCES" if total else
                          "ZERO_KEYS_ONLY" if zero_keys else "NO_EXECUTOR_INSTANCES")
                return {"state": "UNVERIFIED" if invalid_keys else "OBSERVED",
                        "reason": reason, "scheduler_state": scheduler_state,
                        "lease_matches": lease_matches, "active_instances": total,
                        "raw_instance_keys": raw_keys, "zero_instance_keys": zero_keys,
                        "invalid_instance_keys": invalid_keys,
                        "jobs": jobs, "omitted_job_ids": omitted}
        except Exception:
            # Diagnostics must never prevent the ordinary reversible rearm.
            return {"state": "UNVERIFIED"}

    async def prepare_owned_restart(self, *, timeout_seconds: float) -> dict[str, object]:
        """Reversible quiescence; never calls stop or cancels admitted DB work."""
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Prepare timeout must be finite and positive")
        capability = self.owned_restart_preflight()
        if capability["state"]:
            return capability
        if self._restart_preparing or self._restart_guard is not None:
            return {"state": "RESTART_ALREADY_PREPARING"}
        self._restart_preparing = True
        self._restart_rearmed = False
        deadline = time.monotonic() + timeout_seconds
        stage = "HTTP_QUIESCENCE"
        scheduler_lease = None
        last_scheduler_false_remaining_ms = None
        last_job_false_remaining_ms = None
        last_job_false_evidence = None
        last_job_sample_at = 0.0

        async def until(probe):
            while time.monotonic() < deadline:
                value = probe()
                if value:
                    return value
                await asyncio.sleep(.02)
            raise TimeoutError(stage)

        def pause(owner, resume=None):
            lease = owner.pause()
            self._restart_undo.append(lambda: (resume or owner.resume)(lease))
            self._restart_gates.append((owner, lease))
            return lease

        async def flush(awaitable):
            task = asyncio.create_task(awaitable)
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            await asyncio.wait_for(asyncio.shield(task), max(.001, deadline - time.monotonic()))

        try:
            http = pause(self.http_admission)
            if self.scheduler is not None:
                scheduler_lease = self.scheduler.pause_for_restart()
                self._restart_undo.append(lambda: self.scheduler.resume_after_restart_refusal(scheduler_lease))
            jobs = job_service.request_job_pause()
            self._restart_undo.append(lambda: job_service.resume_jobs(jobs))
            # Admitted HTTP/scheduler callbacks can finish, but cannot launch
            # new child jobs after this fence. Keep their Session owner open.
            await until(lambda: self.http_admission.idle(http))
            if self.http_ownership_unknown:
                raise RuntimeError("HTTP_WORKER_OWNERSHIP_UNKNOWN")
            if self.scheduler is not None:
                stage = "SCHEDULER_QUIESCENCE"

                def scheduler_idle():
                    nonlocal last_scheduler_false_remaining_ms
                    idle = self.scheduler.restart_quiescent(scheduler_lease)
                    if not idle:
                        last_scheduler_false_remaining_ms = round(
                            (deadline - time.monotonic()) * 1000)
                    return idle

                await until(scheduler_idle)
            stage = "DETACHED_WORKER_QUIESCENCE"
            workers = await until(detached_admission.pause_if_idle)
            self._restart_undo.append(lambda: detached_admission.resume(workers))
            from app.crypto_market.auto_refresh import crypto_auto_refresh_manager as auto
            from app.crypto_market.ws_runtime import crypto_realtime_collector_manager as collectors
            from app.crypto_market.realtime_persistence import crypto_realtime_persistence_manager as persistence
            from app.market.providers.fugle_realtime_runtime import get_fugle_realtime_runtime
            fugle = get_fugle_realtime_runtime()
            for owner in (auto, collectors, persistence):
                lease = pause(owner.restart_admission)
                self._restart_owner_commits.append((owner, lease))
            if fugle is not None:
                fugle_lease = pause(fugle.restart_admission, fugle.resume_after_restart_refusal)
                self._restart_owner_commits.append((fugle, fugle_lease))
            stage = "COLLECTOR_QUIESCENCE"
            await until(lambda: all(gate.idle(lease) for gate, lease in self._restart_gates))
            stage = "COLLECTOR_FINAL_FLUSH"
            if fugle is not None:
                await flush(fugle.flush_for_restart(fugle_lease))
            await flush(persistence.flush_once())
            persisted = persistence.status()
            if persisted["pending_count"] or persisted["flush_in_flight"] or persisted["last_error"]:
                raise RuntimeError("COLLECTOR_UNPERSISTED_WORK")
            stage = "JOB_QUIESCENCE"

            def jobs_quiescent():
                nonlocal last_job_false_remaining_ms, last_job_false_evidence, last_job_sample_at
                idle = job_service.jobs_paused(jobs)
                if not idle:
                    current = time.monotonic()
                    last_job_false_remaining_ms = round((deadline - current) * 1000)
                    # Capture the last refused state at most four times a
                    # second. Final evidence may differ at the deadline edge.
                    if current - last_job_sample_at >= .25:
                        last_job_sample_at = current
                        try:
                            last_job_false_evidence = job_service.observe_job_quiescence()
                        except Exception:
                            last_job_false_evidence = {"reason": "UNVERIFIED"}
                return idle

            await until(jobs_quiescent)
            job_history = job_service.job_drain_status()
            if job_history.unresolved_enqueues:
                # Execution has exited, but its durable result still needs
                # reconciliation. Preserve that evidence through safe shutdown;
                # it does not replace the following Session/SQLite writer gates.
                logger.warning(
                    "OMI_RESTART_JOB_RECONCILIATION_PENDING unresolved_enqueues=%s task_failures=%s",
                    job_history.unresolved_enqueues, job_history.task_failures,
                )
            # Jobs can still open Sessions while persisting a safe checkpoint.
            sessions = session_owner.pause_session_scopes()
            self._restart_undo.append(lambda: session_owner.resume_session_scopes(sessions))
            stage = "SESSION_QUIESCENCE"
            await until(lambda: session_owner.session_scopes_quiescent(sessions))
            stage = "PUBLISHER_QUIESCENCE"
            publisher = await until(intraday_publisher.pause_publishers_if_idle)
            self._restart_undo.append(lambda: intraday_publisher.resume_publishers(publisher))
            stage = "SQLITE_PHYSICAL_CONNECTION_QUIESCENCE"
            sqlite = await until(sqlite_admission.pause_if_idle)
            self._restart_undo.append(lambda: sqlite_admission.resume(sqlite))
            engine = session_owner.engine_admission.status(deadline=deadline)
            if engine.active_connections or engine.unknown_connections:
                raise RuntimeError("ENGINE_DRIVER_OWNERSHIP_UNKNOWN")
            stage = "SQLITE_EXTERNAL_WRITER_EXCLUSION"
            self._restart_guard = SQLiteWriterLease.acquire(session_owner.engine.url)
            if not self._restart_guard.held or time.monotonic() >= deadline:
                raise RuntimeError("SQLITE_RESERVATION_NOT_HELD")
            # A lost owner/STOP message must not leave admission paused forever.
            self._restart_deadline = time.monotonic() + 5
            self._restart_expiry = asyncio.create_task(self._expire_restart_prepare())
            return {"state": "WRITERS_PREPARED", "authority": "SQLITE_IMMEDIATE_TRANSACTION",
                    "terminal_drain_started": False}
        except BaseException as exc:
            if stage == "SCHEDULER_QUIESCENCE":
                # Observe before rearm clears the pause lease. Never infer the
                # blocker from missed-run notices, and never discard active jobs.
                logger.warning("OMI_RESTART_SCHEDULER_QUIESCENCE failure_type=%s "
                               "last_false_remaining_ms=%s deadline_remaining_ms=%s evidence=%s",
                               type(exc).__name__, last_scheduler_false_remaining_ms,
                               round((deadline - time.monotonic()) * 1000),
                               self._scheduler_inflight_evidence(expected_lease=scheduler_lease))
            elif stage == "JOB_QUIESCENCE":
                try:
                    job_evidence = job_service.observe_job_quiescence()
                except Exception:
                    job_evidence = {"reason": "UNVERIFIED"}
                reason = (
                    "DEADLINE" if isinstance(exc, TimeoutError) else "OTHER"
                )
                logger.warning(
                    "OMI_RESTART_JOB_QUIESCENCE failure_type=%s reason=%s "
                    "last_false_remaining_ms=%s last_false_evidence=%s "
                    "deadline_remaining_ms=%s evidence=%s",
                    type(exc).__name__, reason,
                    last_job_false_remaining_ms, last_job_false_evidence,
                    round((deadline - time.monotonic()) * 1000), job_evidence
                )
            elif stage == "DETACHED_WORKER_QUIESCENCE":
                try:
                    worker_evidence = detached_admission.observation()
                except Exception:
                    worker_evidence = {"state": "UNVERIFIED"}
                logger.warning("OMI_RESTART_DETACHED_QUIESCENCE failure_type=%s evidence=%s",
                               type(exc).__name__, worker_evidence)
            rearmed = self.abort_owned_restart()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return {"state": "PREFLIGHT_REARMED" if rearmed else "REARM_UNKNOWN",
                    "stage": stage, "terminal_drain_started": self._stop_task is not None}
        finally:
            self._restart_preparing = False

    async def _expire_restart_prepare(self):
        await asyncio.sleep(max(0, self._restart_deadline - time.monotonic()))
        if not self._restart_committed:
            self.abort_owned_restart()

    def abort_owned_restart(self):
        self._restart_rearmed = False
        if self._restart_committed or self._stop_task is not None:
            return False
        try:
            if self._restart_guard is not None:
                self._restart_guard.release()
                self._restart_guard = None
            while self._restart_undo:
                self._restart_undo[-1]()
                self._restart_undo.pop()
            self._restart_gates.clear()
            self._restart_owner_commits.clear()
            if self._restart_expiry is not None and self._restart_expiry is not asyncio.current_task():
                self._restart_expiry.cancel()
            self._restart_expiry = None
            self._restart_deadline = 0.0
            self._restart_rearmed = self.started and self.http_admission.accepting
            return self._restart_rearmed
        except Exception:
            logger.exception("Restart preflight rearm incomplete")
            return False

    def owned_restart_rearmed(self):
        """Observation of successful undo by this owner, never absence-of-guard proof."""
        return (self._restart_rearmed and self.started and self.http_admission.accepting
                and not self._restart_preparing and not self._restart_committed
                and self._restart_guard is None and not self._restart_undo
                and self._stop_task is None)

    def commit_owned_restart(self):
        """Only inherited STOP can call this, while the native authority is held."""
        if (self._restart_guard is None or not self._restart_guard.held
                or time.monotonic() >= self._restart_deadline or self._restart_committed
                or not all(gate.idle(lease) for gate, lease in self._restart_gates)):
            self.abort_owned_restart()
            raise RuntimeError("PREPARE_AUTHORITY_EXPIRED")
        self._restart_committed = True
        for owner, lease in self._restart_owner_commits:
            owner.commit_restart(lease)
        self.http_admission.commit(self._restart_gates[0][1])
        sqlite_admission.begin_drain()
        # Native transaction intentionally stays open through lifespan and exit.

    def restart_preflight(self) -> dict[str, object]:
        """Memory-only observation, never a drain command or restart permission.

        Registered-owner completion cannot attest global writer admission or
        external writers. Keep this separate from stop(), which is terminal.
        """
        result = self.drain_result
        state = result.state if result else "NOT_REQUESTED"
        if result is None and self._stop_task is not None:
            state = "UNKNOWN" if self._stop_task.done() else "IN_PROGRESS"
        return {
            "schema": "omi.restart-preflight.v1",
            "runtime_started": self.started,
            "registered_drain_state": state,
            "all_writers_drained": result.all_writers_drained if result else False,
            "unknown_writer_count": len(result.unknown_writers if result else UNATTESTED_WRITERS),
        }

    def restart_diagnostics(self) -> dict[str, object]:
        """GET-only memory observations; never part of the five-field pipe wire."""
        result = self.drain_result
        return {
            # This legacy count measures scope categories, not live processes
            # or connections. Keep its value and refusal semantics unchanged.
            "unknown_writer_count_basis": "unattested_scope_categories",
            "unknown_writer_categories": list(result.unknown_writers if result else UNATTESTED_WRITERS),
            "observation_scope": "process_local_non_atomic_not_restart_authority",
            "owned_restart_capability": self.owned_restart_preflight(),
            "owner_observations": {
                "jobs": job_service.observe_job_quiescence(),
                "detached_workers": detached_admission.observation(),
                "http": {"accepting": self.http_admission.accepting,
                         "ownership_unknown": self.http_ownership_unknown},
                "session_fence_enabled": self._drain_owned_sessions,
                "engine_fence_enabled": self._drain_engine_connections,
                "prepare_in_progress": self._restart_preparing,
                "native_writer_lease_retained": self._restart_guard is not None,
                "stop_committed": self._restart_committed,
            },
        }

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
                import sys
                if getattr(sys.modules.get("_omi_owned_release"), "verified", False):
                    from app.db.migrations import get_database_revision, get_head_revision
                    current_revision = get_database_revision(existing_only=True)
                    head_revision = get_head_revision()
                    if current_revision != head_revision:
                        raise RuntimeError(
                            "Owned startup requires existing schema at head; migration is a separate action. "
                            f"current={current_revision!r} head={head_revision!r}. "
                            "Do not repeat Restart or Apply Update. Run .venv\\Scripts\\python.exe "
                            "scripts\\omi-schema-maintenance.py Plan for the maintenance gate; "
                            "preserve the original failed-start receipt."
                        )
                else:
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
            with self._startup_session() as db:
                paused_jobs = job_service.read_paused_job_obligations(db)
            self._reconcile_dispatch_runs()

            self.scheduler = job_scheduler.start_scheduler()
            await start_crypto_auto_refresh()
            await start_crypto_realtime_collectors()
            await start_fugle_realtime()
            self._enqueue_stock_master_bootstrap()
            self.started = True
            # Recovery cannot launch IO until all required runtime components
            # have started. A prior startup failure leaves obligations durable.
            job_service.resume_job_obligations(paused_jobs)
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
        engine_connections = None
        if self._drain_engine_connections and complete:
            # Admitted jobs/collectors/API requests may lazily open connections
            # to finish. Fence the canonical Engine only after those owners exit;
            # retain direct/maintenance/borrowed connections until actual checkin.
            engine_connections = await session_owner.engine_admission.drain(deadline=deadline)
            complete = engine_connections.drained
        self.started = False
        # Even a registered-owner success is not process exit or API quiescence.
        # Keep the OS-backed background lock until process exit. No same-process rearm.
        result = RuntimeDrainResult(
            "REGISTERED_DRAINED" if complete else "INCOMPLETE",
            self.background_leader, scheduler_admission, scheduler_state, jobs,
            collectors, self.background_leader, publisher, job_state, sessions,
            engine_connections=engine_connections,
        )
        if complete and self._restart_committed and self._restart_guard is not None and self._restart_guard.held:
            result = replace(result, all_writers_drained=True, unknown_writers=(),
                             collector_data_completeness="OWNER_FINAL_FLUSH_COMPLETED")
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
    runtime = RuntimeCoordinator(drain_owned_sessions=True, drain_engine_connections=True)
    app.state.runtime = runtime
    await runtime.start()

    try:
        yield
    finally:
        await runtime.stop()
