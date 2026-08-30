from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import JobRun
from app.jobs import scheduler
from app.jobs import service as job_service
from app.jobs import us_index_data_repair_gate as gate
from app.jobs.job_types import US_INDEX_DATA_REPAIR_JOB_TYPE
from app.routers import jobs as jobs_router
from app.routers.system import health_check
from app.us_market.ohlc_priority import PRIORITY_US_INDEX_SYMBOLS


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _audit(*, daily_missing=(), quote_missing=()) -> dict:
    daily_missing_set = set(daily_missing)
    quote_missing_set = set(quote_missing)
    return {
        "contract_version": "omi.us.index_data_repair_gate.audit.v1",
        "checked_at": NOW,
        "expected_trade_date": "2026-08-28",
        "missing_daily_symbols": list(daily_missing),
        "missing_quote_symbols": list(quote_missing),
        "missing_count": len(daily_missing_set) + len(quote_missing_set),
        "postcondition_satisfied": not daily_missing_set and not quote_missing_set,
        "daily": [
            {"symbol": symbol, "satisfied": symbol not in daily_missing_set}
            for symbol in PRIORITY_US_INDEX_SYMBOLS
        ],
        "quotes": [
            {"symbol": symbol, "satisfied": symbol not in quote_missing_set}
            for symbol in PRIORITY_US_INDEX_SYMBOLS
        ],
    }


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    JobRun.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)(), engine


def _daily_result(symbol: str, *, satisfied: bool):
    return SimpleNamespace(
        temporal_postcondition_satisfied=satisfied,
        coverage_postcondition_satisfied=satisfied,
        projection={
            "expected_trade_date": "2026-08-28",
            "latest_trade_date": "2026-08-28" if satisfied else None,
            "coverage_status": "complete" if satisfied else "missing",
        },
    )


def _quote_result(*, satisfied: bool):
    health = SimpleNamespace(
        status=SimpleNamespace(value="usable" if satisfied else "missing"),
        selected_provider="fixture" if satisfied else None,
    )
    return SimpleNamespace(
        postcondition_satisfied=satisfied,
        postcondition_reasons=() if satisfied else ("no_candidate",),
        result=SimpleNamespace(resolved=SimpleNamespace(health=health)),
        projection={"observed_at": NOW.isoformat() if satisfied else None},
    )


def test_cache_only_audit_never_calls_acquisition_methods() -> None:
    daily = Mock()
    quote = Mock()
    daily.read.side_effect = lambda **kwargs: _daily_result(
        kwargs["symbol"], satisfied=kwargs["symbol"] != "^VIX"
    )
    quote.read_quote.return_value = _quote_result(satisfied=True)

    result = gate.audit_us_index_data(
        Mock(),
        now=NOW,
        daily_platform_factory=lambda _db: daily,
        quote_platform_factory=lambda _db: quote,
    )

    assert result["missing_daily_symbols"] == ["^VIX"]
    assert result["missing_quote_symbols"] == []
    assert daily.read.call_count == 6
    assert quote.read_quote.call_count == 6
    assert not daily.ensure_history_coverage.called
    assert not quote.refresh_quote.called


def test_resolved_audit_does_not_enqueue(monkeypatch) -> None:
    db, engine = _db()
    enqueue = Mock()
    monkeypatch.setattr(gate, "audit_us_index_data", lambda *_args, **_kwargs: _audit())
    monkeypatch.setattr(gate.job_service, "enqueue_job", enqueue)
    try:
        result = gate.reconcile_us_index_data_repair_gate(db, now=NOW)
        assert result["status"] == "resolved"
        enqueue.assert_not_called()
    finally:
        db.close()
        engine.dispose()


def test_missing_data_enqueues_one_exact_bounded_job(monkeypatch) -> None:
    db, engine = _db()
    job = SimpleNamespace(id=42)
    enqueue = Mock(return_value=(job, True))
    missing = _audit(
        daily_missing=PRIORITY_US_INDEX_SYMBOLS,
        quote_missing=PRIORITY_US_INDEX_SYMBOLS,
    )
    monkeypatch.setattr(gate, "audit_us_index_data", lambda *_args, **_kwargs: missing)
    monkeypatch.setattr(gate.job_service, "enqueue_job", enqueue)
    try:
        result = gate.reconcile_us_index_data_repair_gate(db, now=NOW)
        kwargs = enqueue.call_args.kwargs
        assert result["status"] == "queued"
        assert kwargs["job_type"] == US_INDEX_DATA_REPAIR_JOB_TYPE
        assert kwargs["target"] == "index-gate:2026-08-28"
        assert kwargs["request"]["symbols"] == list(PRIORITY_US_INDEX_SYMBOLS)
        assert kwargs["request"]["daily_max_external_calls"] <= 12
        assert kwargs["request"]["quote_max_external_calls"] <= 12
        assert kwargs["progress_total"] == 3
    finally:
        db.close()
        engine.dispose()


def test_active_lease_cooldown_and_attempt_ceiling_suppress_repairs(monkeypatch) -> None:
    db, engine = _db()
    missing = _audit(daily_missing=["^GSPC"])
    monkeypatch.setattr(gate, "audit_us_index_data", lambda *_args, **_kwargs: missing)
    monkeypatch.setattr(settings, "scheduler_us_index_data_repair_max_attempts", 2)
    monkeypatch.setattr(settings, "scheduler_us_index_data_repair_cooldown_seconds", 1800)
    try:
        db.add(
            JobRun(
                job_type=US_INDEX_DATA_REPAIR_JOB_TYPE,
                target="index-gate:2026-08-28",
                status="running",
            )
        )
        db.commit()
        assert gate.plan_us_index_data_repair(db, now=NOW)["status"] == "leased"

        db.query(JobRun).delete()
        db.add(
            JobRun(
                job_type=US_INDEX_DATA_REPAIR_JOB_TYPE,
                target="index-gate:2026-08-28",
                status="error",
                ended_at=(NOW - timedelta(minutes=10)).replace(tzinfo=None),
            )
        )
        db.commit()
        assert gate.plan_us_index_data_repair(db, now=NOW)["status"] == "suppressed"

        db.add(
            JobRun(
                job_type=US_INDEX_DATA_REPAIR_JOB_TYPE,
                target="index-gate:2026-08-28",
                status="error",
                ended_at=(NOW - timedelta(hours=2)).replace(tzinfo=None),
            )
        )
        db.commit()
        assert gate.plan_us_index_data_repair(db, now=NOW)["status"] == "exhausted"
    finally:
        db.close()
        engine.dispose()


def test_worker_delegates_to_existing_owners_and_rereads_persistence(monkeypatch) -> None:
    initial = _audit(daily_missing=["^GSPC"], quote_missing=["^GSPC"])
    final = _audit()
    audit = Mock(side_effect=[initial, final])
    daily = Mock(return_value={"status": "completed", "external_call_count": 1})
    quote = Mock(return_value={"status": "success", "external_call_count": 1})
    progress = Mock()
    db = Mock()
    monkeypatch.setattr(gate, "audit_us_index_data", audit)

    result = gate.repair_us_index_data(
        db,
        progress,
        requested_at=NOW,
        missing_daily_symbols=["^GSPC"],
        missing_quote_symbols=["^GSPC"],
        daily_max_external_calls=4,
        quote_max_external_calls=2,
        max_runtime_seconds=120,
        daily_reconciler=daily,
        quote_materializer=quote,
    )

    assert result["status"] == "completed"
    assert audit.call_count == 2
    assert daily.call_args.kwargs["max_symbols"] == 6
    assert daily.call_args.kwargs["max_external_calls"] == 4
    assert quote.call_args.args == ("quote.snapshot",)
    assert quote.call_args.kwargs["configured_symbols"] == "^GSPC"
    assert quote.call_args.kwargs["lane_id"] == "index_repair_gate"
    db.rollback.assert_called_once()
    db.expire_all.assert_called_once()


def test_worker_fails_tracked_job_when_persisted_reread_is_still_missing(monkeypatch) -> None:
    missing = _audit(daily_missing=["^GSPC"])
    monkeypatch.setattr(gate, "audit_us_index_data", Mock(side_effect=[missing, missing]))

    with pytest.raises(job_service.JobExecutionError) as exc_info:
        gate.repair_us_index_data(
            Mock(),
            Mock(),
            requested_at=NOW,
            missing_daily_symbols=["^GSPC"],
            missing_quote_symbols=[],
            daily_max_external_calls=2,
            quote_max_external_calls=2,
            max_runtime_seconds=120,
            daily_reconciler=Mock(return_value={"status": "partial"}),
        )

    assert exc_info.value.result["status"] == "partial"
    assert exc_info.value.result["final_audit"]["missing_count"] == 1


def test_scheduler_registration_is_independent_and_bounded(monkeypatch) -> None:
    fake_scheduler = Mock()
    monkeypatch.setattr(settings, "enable_us_index_data_repair_gate", True)
    monkeypatch.setattr(settings, "scheduler_us_index_data_repair_interval_minutes", 30)
    monkeypatch.setattr(settings, "scheduler_us_index_data_repair_startup_delay_seconds", 30)

    assert scheduler._add_us_index_data_repair_gate(fake_scheduler) is True
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "us_index_data_repair_gate"
    assert kwargs["minutes"] == 30
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True
    assert kwargs["next_run_time"] is not None


def test_scheduler_registration_can_be_disabled(monkeypatch) -> None:
    fake_scheduler = Mock()
    monkeypatch.setattr(settings, "enable_us_index_data_repair_gate", False)

    assert scheduler._add_us_index_data_repair_gate(fake_scheduler) is False
    fake_scheduler.add_job.assert_not_called()


def test_health_discloses_gate_owner_and_hard_budgets(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_us_index_data_repair_gate", True)

    payload = health_check()["runtime"]["us_index_data_repair_gate"]

    assert payload["enabled"] is True
    assert payload["owner"] == "scheduler_control_plane"
    assert payload["symbols"] == list(PRIORITY_US_INDEX_SYMBOLS)
    assert payload["daily_max_external_calls"] <= 12
    assert payload["quote_max_external_calls"] <= 12
    assert payload["max_attempts"] <= 5


def test_job_retry_preserves_the_exact_repair_budget_and_scope() -> None:
    request = {
        "requested_at": NOW.isoformat(),
        "missing_daily_symbols": ["^GSPC"],
        "missing_quote_symbols": ["^VIX"],
        "daily_max_external_calls": 4,
        "quote_max_external_calls": 2,
        "max_runtime_seconds": 120,
    }
    job = JobRun(
        id=99,
        job_type=US_INDEX_DATA_REPAIR_JOB_TYPE,
        target="index-gate:2026-08-28",
        status="error",
        progress_current=0,
        progress_total=3,
        request_json=json.dumps(request),
    )

    task, args, parsed = jobs_router._retry_config(job)

    assert task is gate.run_us_index_data_repair_job
    assert args == (
        NOW.isoformat(),
        ["^GSPC"],
        ["^VIX"],
        4,
        2,
        120,
    )
    assert parsed == request
