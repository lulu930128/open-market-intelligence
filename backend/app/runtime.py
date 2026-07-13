from __future__ import annotations

from contextlib import asynccontextmanager
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
from app.jobs import scheduler as job_scheduler, service as job_service
from app.config import settings
from app.runtime_lock import ProcessFileLock


logger = logging.getLogger(__name__)


class RuntimeLock(Protocol):
    def acquire(
        self,
        *,
        timeout_seconds: float = 0,
        poll_interval_seconds: float = 0.05,
    ) -> bool: ...

    def release(self) -> None: ...


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        schema_lock: RuntimeLock | None = None,
        background_lock: RuntimeLock | None = None,
    ) -> None:
        lock_dir = settings.runtime_lock_dir
        self.schema_lock = schema_lock or ProcessFileLock(lock_dir / "schema.lock")
        self.background_lock = background_lock or ProcessFileLock(lock_dir / "background.lock")
        self.scheduler: Any | None = None
        self.started = False
        self.background_leader = False

    async def start(self) -> None:
        if self.started:
            return

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

            self.scheduler = job_scheduler.start_scheduler()
            await start_crypto_auto_refresh()
            await start_crypto_realtime_collectors()
            self.started = True
        except Exception:
            logger.exception("Runtime startup failed; cleaning up started components.")
            try:
                await self.stop()
            except Exception:
                logger.exception("Runtime cleanup after startup failure also failed.")
            raise

    async def stop(self) -> None:
        errors: list[BaseException] = []

        if self.background_leader:
            for name, stop_step in (
                ("crypto realtime collectors", stop_crypto_realtime_collectors),
                ("crypto auto refresh", stop_crypto_auto_refresh),
            ):
                try:
                    await stop_step()
                except Exception as exc:
                    errors.append(exc)
                    logger.exception("Failed to stop %s.", name)

            try:
                job_scheduler.stop_scheduler(self.scheduler)
            except Exception as exc:
                errors.append(exc)
                logger.exception("Failed to stop job scheduler.")
            finally:
                self.scheduler = None

            try:
                self.background_lock.release()
            except Exception as exc:
                errors.append(exc)
                logger.exception("Failed to release background runtime ownership.")
            finally:
                self.background_leader = False
        else:
            self.scheduler = None

        try:
            job_service.shutdown_job_executor(wait=False)
        except Exception as exc:
            errors.append(exc)
            logger.exception("Failed to shut down job executor.")

        self.started = False

        if errors:
            raise RuntimeError("One or more runtime shutdown steps failed.") from errors[0]

    def _mark_interrupted_jobs(self) -> None:
        db = SessionLocal()

        try:
            interrupted_count = job_service.mark_interrupted_jobs(db)
        finally:
            db.close()

        if interrupted_count:
            logger.warning(
                "Marked %s interrupted queued/running jobs as error.",
                interrupted_count,
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
