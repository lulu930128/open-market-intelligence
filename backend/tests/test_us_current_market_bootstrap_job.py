from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.jobs import service as job_service
from app.jobs.job_types import US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE
from app.jobs.us_current_market_bootstrap import (
    enqueue_us_current_market_bootstrap,
    normalize_us_current_market_bootstrap_targets,
    run_us_current_market_bootstrap_job,
)
from app.jobs.schemas import USCurrentMarketBootstrapJobRequest
from app.routers.jobs import enqueue_us_current_market_bootstrap_operator
from app.us_market.intraday_profiles import (
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM,
    US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS,
)


def test_bootstrap_job_default_budget_reserves_two_fallback_calls() -> None:
    request = USCurrentMarketBootstrapJobRequest()

    assert request.max_external_calls == (
        US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS
        + US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM
    )
    assert (
        request.max_external_calls
        == US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS
        == 12
    )


def test_enqueue_bootstrap_normalizes_bounded_target_and_tracks_job() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    queued = SimpleNamespace(id=7)
    try:
        with (
            patch(
                "app.jobs.us_current_market_bootstrap.job_service.find_active_job_by_target",
                return_value=None,
            ),
            patch(
                "app.jobs.us_current_market_bootstrap.job_service.enqueue_job",
                return_value=(queued, True),
            ) as enqueue,
        ):
            result = enqueue_us_current_market_bootstrap(
                db,
                equity_symbols="aapl,TSM,MSFT",
                index_symbols="^GSPC,AAPL,^DJI",
                max_external_calls=8,
            )

        assert result == (queued, True)
        kwargs = enqueue.call_args.kwargs
        assert kwargs["job_type"] == US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE
        assert kwargs["request"] == {
            "equity_symbols": ["AAPL", "TSM"],
            "index_symbols": ["^GSPC", "^DJI"],
            "max_external_calls": 8,
        }
        assert kwargs["task_args"] == ("AAPL,TSM", "^GSPC,^DJI", 8)
        assert kwargs["progress_total"] == 3
    finally:
        db.close()
        engine.dispose()


def test_enqueue_bootstrap_reuses_active_target() -> None:
    active = SimpleNamespace(id=9)
    with patch(
        "app.jobs.us_current_market_bootstrap.job_service.find_active_job_by_target",
        return_value=active,
    ):
        result = enqueue_us_current_market_bootstrap(
            SimpleNamespace(),
            equity_symbols="AAPL,TSM",
            index_symbols="^GSPC,^DJI",
            max_external_calls=8,
        )

    assert result == (active, False)


def test_bootstrap_target_normalization_never_expands_symbol_scope() -> None:
    equity, indexes = normalize_us_current_market_bootstrap_targets(
        equity_symbols=["AAPL", "TSM", "MSFT"],
        index_symbols=["^GSPC", "AAPL", "^DJI"],
    )

    assert equity == ["AAPL", "TSM"]
    assert indexes == ["^GSPC", "^DJI"]


def test_jobs_operator_dispatches_only_the_typed_bounded_request() -> None:
    request = USCurrentMarketBootstrapJobRequest(
        equity_symbols=["aapl", "TSM"],
        index_symbols=["^GSPC", "^SOX"],
        max_external_calls=6,
    )
    queued = SimpleNamespace(id=13)
    with (
        patch(
            "app.routers.jobs.enqueue_us_current_market_bootstrap_job",
            return_value=(queued, True),
        ) as enqueue,
        patch(
            "app.routers.jobs.service.serialize_job",
            return_value={"id": 13, "status": "queued"},
        ),
    ):
        result = enqueue_us_current_market_bootstrap_operator(
            request,
            db=SimpleNamespace(),
        )

    assert result == {"id": 13, "status": "queued"}
    assert enqueue.call_args.kwargs == {
        "equity_symbols": "aapl,TSM",
        "index_symbols": "^GSPC,^SOX",
        "max_external_calls": 6,
    }


def test_tracked_bootstrap_job_preserves_success_result() -> None:
    captured: dict = {}

    def run_immediately(job_id, worker):
        captured["job_id"] = job_id
        captured["result"] = worker(None, lambda *_args: None)

    expected = {
        "status": "success",
        "runs": [{}, {}, {}],
        "external_call_count": 2,
    }
    with (
        patch(
            "app.jobs.us_current_market_bootstrap.bootstrap_us_current_market",
            return_value=expected,
        ),
        patch(
            "app.jobs.us_current_market_bootstrap.job_service.run_tracked_job",
            side_effect=run_immediately,
        ),
    ):
        run_us_current_market_bootstrap_job(11, "AAPL", "^GSPC", 4)

    assert captured == {"job_id": 11, "result": expected}


def test_tracked_bootstrap_job_fails_closed_on_partial_outcome() -> None:
    def run_immediately(_job_id, worker):
        worker(None, lambda *_args: None)

    partial = {"status": "partial", "runs": [{"status": "failed"}]}
    with (
        patch(
            "app.jobs.us_current_market_bootstrap.bootstrap_us_current_market",
            return_value=partial,
        ),
        patch(
            "app.jobs.us_current_market_bootstrap.job_service.run_tracked_job",
            side_effect=run_immediately,
        ),
        pytest.raises(job_service.JobExecutionError) as exc_info,
    ):
        run_us_current_market_bootstrap_job(12, "AAPL", "^GSPC", 4)

    assert exc_info.value.result == partial
