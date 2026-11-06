"""Explicit Daily entry scope and per-symbol isolation on disposable SQLite."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db.models import JobRun, USDailyPrice, USStockMaster
from app.jobs import backfill_tasks
from app.market_data.gateway import PostAcquisitionError
from app.market_data.integration_contracts import AcquisitionSummary
from app.routers import us_market as router
from app.us_market import daily_ohlcv_platform as platform_module, service, watchlist_workflows as workflows
from app.us_market.daily_rollout import require_us_daily_acquisition_enabled, us_daily_full_market_acquisition_enabled
from app.us_market.errors import USMarketConfigurationError, USMarketDataFetchError
from app.us_market.market_data.descriptors import YAHOO_DAILY_DESCRIPTOR, YAHOO_DAILY_RESOURCE_ID
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor, USProviderPayload
from test_us_daily_rollout import _session
from test_us_daily_ohlcv_acquisition import NOW, _yahoo_payload


@pytest.fixture
def isolated(monkeypatch):
    db = _session()
    db.add_all([USStockMaster(symbol=s, exchange="NYSE", is_etf=True) for s in ("VOO", "QQQ", "DENIED")])
    db.commit()
    calls = []
    monkeypatch.setattr(settings, "us_canonical_market_data_mode", "canary")
    monkeypatch.setattr(settings, "us_canonical_shadow_symbols", "AAPL")
    monkeypatch.setattr(settings, "us_canonical_canary_max_symbols", 1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW

    def fetch(route, requirement):
        symbol = requirement.target.instrument.symbol
        calls.append(symbol)
        return USProviderPayload(payload=_yahoo_payload(symbol), url="https://fixture.invalid/chart")

    class Platform(platform_module.USDailyOhlcvPlatform):
        def __init__(self, chart_db, **kwargs):
            if kwargs.get("rollout_state") is not None:
                chart_db.info.setdefault("operation_scopes", []).append(kwargs["rollout_state"])
            super().__init__(chart_db, **kwargs, descriptors=(YAHOO_DAILY_DESCRIPTOR,),
                acquisition=USDailyOhlcvAcquisitionExecutor(fetchers={YAHOO_DAILY_RESOURCE_ID: fetch}, clock=lambda: NOW))

        def refresh(self, **kwargs):
            if kwargs["symbol"] == "DENIED":
                self._db.add(USStockMaster(symbol="UNCOMMITTED", exchange="NYSE"))
                self._db.flush()
                require_us_daily_acquisition_enabled("DENIED")
            return super().refresh(**kwargs)

    monkeypatch.setattr(platform_module, "datetime", Clock)
    monkeypatch.setattr(platform_module, "USDailyOhlcvPlatform", Platform)
    yield db, calls
    db.close()
    db.get_bind().dispose()


def test_explicit_daily_post_uses_exact_scope_and_generic_helper_stays_gated(isolated):
    db, calls = isolated
    result = router.refresh_us_daily_prices(symbol="VOO", outputsize="compact", adjusted=False, provider="auto", db=db)
    assert calls == ["VOO"] and result["symbol"] == "VOO"
    assert result["external_call_count"] == 1 and result["persistence_committed"]
    assert settings.us_canonical_market_data_mode == "canary" and settings.us_canonical_shadow_symbols == "AAPL"
    assert not us_daily_full_market_acquisition_enabled()
    with pytest.raises(USMarketConfigurationError, match="ROLLOUT_DISABLED"):
        require_us_daily_acquisition_enabled("QQQ", state=db.info["operation_scopes"][0])
    with pytest.raises(USMarketConfigurationError, match="ROLLOUT_DISABLED"):
        platform_module.refresh_us_daily_ohlcv(db, symbol="QQQ")
    platform_module.USDailyOhlcvPlatform(db).read(symbol="QQQ", now=NOW)
    assert calls == ["VOO"]


@pytest.mark.parametrize("job_type,explicit", [("us_market.watchlist_daily_refresh", True),
    ("scheduler.us_market_daily_refresh", False)])
@pytest.mark.parametrize("invalid_symbol", ["MISSING", "??"])
def test_job_owned_watchlist_snapshot_isolates_targets_without_opening_background(isolated, monkeypatch, job_type, explicit, invalid_symbol):
    db, calls = isolated
    monkeypatch.setattr(workflows, "list_us_watchlist_symbols", lambda **_: ("VOO", "DENIED", invalid_symbol, "QQQ"))
    job = JobRun(job_type=job_type, status="running", target="fixture")
    db.add(job)
    db.commit()
    output = []
    monkeypatch.setattr(backfill_tasks, "run_tracked_job", lambda job_id, worker: output.append(worker(db, Mock())))
    backfill_tasks.run_us_watchlist_daily_refresh_job(job.id, 7, True, True, "compact", False, 0)
    result = output[0]
    assert result["status"] == "partial_success" and result["symbol_count"] == 4
    assert calls == (["VOO", "QQQ"] if explicit else [])
    assert len(result["errors"]) == (2 if explicit else 4)
    if explicit:
        assert [e["symbol"] for e in result["errors"]] == ["DENIED", invalid_symbol]
        assert result["fetched_count"] > 0 and result["inserted_count"] > 0
        assert db.query(USDailyPrice).filter_by(symbol="VOO").count() > 0
        assert db.query(USDailyPrice).filter_by(symbol="QQQ").count() > 0
        assert db.query(USStockMaster).filter_by(symbol="UNCOMMITTED").count() == 0
    else:
        assert result["fetched_count"] == result["inserted_count"] == 0
    assert not us_daily_full_market_acquisition_enabled()


@pytest.mark.parametrize("failure", ["global_config", "persistence", "post_acquisition", "provider_unknown", "rollback_unknown"])
def test_watchlist_unknown_or_global_failure_does_not_become_success(isolated, monkeypatch, failure):
    db, calls = isolated
    seen = []
    errors = {
        "global_config": USMarketConfigurationError("ALPHAVANTAGE_API_KEY is not configured."),
        "persistence": OperationalError("fixture write", None, RuntimeError("outcome unknown")),
        "post_acquisition": PostAcquisitionError("unknown", acquisition=AcquisitionSummary(), stage="persistence"),
        "provider_unknown": RuntimeError("provider consumption unknown"),
        "rollback_unknown": USMarketDataFetchError("known target failure"),
    }
    def refresh(**kwargs):
        seen.append(kwargs["symbol"])
        raise errors[failure]
    if failure == "rollback_unknown":
        monkeypatch.setattr(db, "rollback", Mock(side_effect=RuntimeError("rollback unknown")))
    monkeypatch.setattr(workflows, "list_us_watchlist_symbols", lambda **_: ("VOO", "QQQ"))
    dependencies = SimpleNamespace(refresh_daily_prices=refresh)
    with pytest.raises(RuntimeError if failure == "rollback_unknown" else type(errors[failure])):
        workflows.refresh_us_watchlist_daily_prices(db, dependencies=dependencies, sleep_seconds=0)
    assert seen == ["VOO"] and not calls
