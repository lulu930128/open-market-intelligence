"""Migration failure never starts background owners; no live runtime involved."""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401

from app.runtime import RuntimeCoordinator


@pytest.mark.parametrize("revision", ["old", "future-or-unknown", None])
def test_owned_schema_mismatch_points_to_maintenance_without_migration(revision):
    import asyncio
    import sys
    from types import SimpleNamespace

    schema, background = Mock(), Mock()
    schema.acquire.return_value = True

    async def scenario():
        runtime = RuntimeCoordinator(schema_lock=schema, background_lock=background)
        with (
            patch.dict(sys.modules, {"_omi_owned_release": SimpleNamespace(verified=True)}),
            patch("app.db.migrations.get_database_revision", return_value=revision) as read,
            patch("app.db.migrations.get_head_revision", return_value="head"),
            patch("app.runtime.run_database_migrations") as migrate,
        ):
            with pytest.raises(RuntimeError, match="omi-schema-maintenance.py Plan"):
                await runtime.start()
            read.assert_called_once_with(existing_only=True)
            migrate.assert_not_called()
            background.acquire.assert_not_called()
            schema.release.assert_called_once()
            with pytest.raises(RuntimeError, match="terminal"):
                await runtime.start()
            assert read.call_count == 1
    asyncio.run(scenario())


def test_migration_failure_releases_schema_lock_without_starting_writers():
    import asyncio
    schema = Mock()
    schema.acquire.return_value = True
    background = Mock()
    async def scenario():
        runtime = RuntimeCoordinator(schema_lock=schema, background_lock=background)
        with (
            patch('app.runtime.run_database_migrations', side_effect=RuntimeError('fixture migration failure')),
            patch('app.runtime.job_scheduler.start_scheduler') as scheduler,
            patch('app.runtime.start_crypto_auto_refresh', new_callable=AsyncMock) as crypto,
            patch('app.runtime.start_fugle_realtime', new_callable=AsyncMock) as fugle,
            patch.object(runtime, '_mark_interrupted_jobs') as interrupted,
            patch.object(runtime, '_reconcile_dispatch_runs') as dispatch,
            patch.object(runtime, '_enqueue_stock_master_bootstrap') as bootstrap,
        ):
            with pytest.raises(RuntimeError, match='fixture migration failure'):
                await runtime.start()
            schema.release.assert_called_once()
            background.acquire.assert_not_called()
            scheduler.assert_not_called()
            crypto.assert_not_awaited()
            fugle.assert_not_awaited()
            interrupted.assert_not_called()
            dispatch.assert_not_called()
            bootstrap.assert_not_called()
            assert not runtime.started and not runtime.background_leader
            assert runtime.drain_result is not None
            # A failed startup cannot silently rearm the same coordinator.
            with pytest.raises(RuntimeError, match='terminal'):
                await runtime.start()
    asyncio.run(scenario())
