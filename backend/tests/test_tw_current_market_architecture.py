from __future__ import annotations

import inspect

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.market import indices
from app.market import tw_current_market_platform
from app.market import tw_current_market_operations
from app.market.providers import twse_mis_current_breadth
from app.jobs import scheduler
from app.market_data import gateway


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_current_index_and_summary_gets_are_cache_only(monkeypatch) -> None:
    db, engine = _db()
    try:
        def forbidden(*_args, **_kwargs):
            raise AssertionError("current-session GET attempted IO or mutation")

        monkeypatch.setattr(indices, "provider_fetch_json", forbidden)
        monkeypatch.setattr(indices, "http_get", forbidden)
        monkeypatch.setattr(db, "commit", forbidden)

        summary = indices.get_market_index_summary(db, force_refresh=True)
        intraday = indices.get_market_index_intraday(
            "TAIEX",
            acquisition_policy="require_live",
            db=db,
        )

        assert summary["acquisition_policy"] == "cache_only"
        assert summary["cache_status"] == "canonical_cache"
        assert intraday["acquisition_policy"] == "cache_only"
        assert intraday["requested_acquisition_policy"] == "require_live"
        assert intraday["read_path_side_effects"] is False
        assert "GET_ACQUISITION_POLICY_OVERRIDDEN_TO_CACHE_ONLY" in intraday["warnings"]
    finally:
        db.close()
        engine.dispose()


def test_current_provider_selection_is_not_owned_by_public_indices_functions() -> None:
    summary_source = inspect.getsource(indices.get_market_index_summary)
    intraday_source = inspect.getsource(indices.get_market_index_intraday)
    assert "return _market_index_summary(" not in summary_source
    assert "_fetch_" not in summary_source
    assert "_get_market_index_intraday_prefer_live" not in intraday_source
    assert "_fetch_" not in intraday_source
    assert "read_taiwan_current_index" in intraday_source
    assert "TaiwanBarService" in intraday_source
    assert "read_taiwan_index_intraday_series" not in intraday_source
    assert "taiwan_index_minute" not in intraday_source


def test_shared_gateway_is_provider_neutral_for_current_capabilities() -> None:
    gateway_source = inspect.getsource(gateway)
    assert "twse_mis" not in gateway_source.lower()
    assert "yahoo" not in gateway_source.lower()
    assert "kgi" not in gateway_source.lower()

    platform_source = inspect.getsource(tw_current_market_platform)
    assert "app.market.providers" not in platform_source
    assert "TW_CURRENT_INDEX_CAPABILITY_ID" in platform_source
    assert "TW_CURRENT_BREADTH_CAPABILITY_ID" in platform_source


def test_current_refresh_uses_market_owned_provider_operations() -> None:
    refresh_source = inspect.getsource(indices.refresh_market_index_summary)
    refresh_core_source = inspect.getsource(indices._refresh_current_market_summary)
    indices_source = inspect.getsource(indices)
    operation_source = inspect.getsource(tw_current_market_operations)
    breadth_provider_source = inspect.getsource(twse_mis_current_breadth)

    assert "_refresh_current_market_summary" in refresh_source
    assert "tw_current_market_operations" in refresh_core_source
    assert "tw_current_market_legacy_bridge" not in refresh_core_source
    assert "build_current_market_executors" in refresh_core_source
    assert "app.market import indices" not in operation_source
    assert "app.market.indices" not in operation_source
    assert "def _fetch_mis_index_intraday" not in indices_source
    assert "def _fetch_yahoo_index_intraday" not in indices_source
    assert "def _fetch_twse_mis_live_market_breadth" not in indices_source
    assert "def _fetch_twse_mis_stock_messages" not in indices_source
    assert "from app.db.models import StockMaster" not in breadth_provider_source
    assert "sqlalchemy" not in breadth_provider_source
    assert "Session" not in breadth_provider_source


def test_index_and_breadth_scheduler_lanes_are_independent() -> None:
    index_job_source = inspect.getsource(
        scheduler.collect_taiwan_market_index_summary
    )
    breadth_job_source = inspect.getsource(
        scheduler.collect_taiwan_market_breadth_summary
    )

    assert "refresh_current_market_index_snapshots" in index_job_source
    assert "materialize_index_minute_candidates" in index_job_source
    assert "TaiwanBarMaterializationTransaction" in index_job_source
    assert "refresh_current_market_breadth_snapshots" not in index_job_source
    assert "refresh_current_market_breadth_snapshots" in breadth_job_source
    assert "refresh_current_market_index_snapshots" not in breadth_job_source
    assert "persist_taiwan_index_minute_snapshots" not in index_job_source
