from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, DispatchSchedule
from app.dispatch import readiness, schedule_runs, service
from app.dispatch.schemas import DispatchRecipientGroupCreate, DispatchScheduleCreate


UTC = timezone.utc


def _schedule(db: Session, *, policy: str = "wait_until_ready") -> DispatchSchedule:
    group = service.create_recipient_group(
        db,
        DispatchRecipientGroupCreate(name="readiness recipients", emails=["ready@example.com"]),
    )
    created = service.create_schedule(
        db,
        DispatchScheduleCreate(
            name="readiness schedule",
            recipient_group_id=group["id"],
            template_key="market_overview",
            scope_type="market",
            scope_id="tw",
            readiness_profile="tw_post_close",
            readiness_policy=policy,
            readiness_deadline_minutes=30,
        ),
    )
    schedule = db.get(DispatchSchedule, created["id"])
    assert schedule is not None
    return schedule


def _readiness_result(*, ready: bool, retryable: bool) -> dict:
    return {
        "contract_version": readiness.READINESS_CONTRACT_VERSION,
        "profile": "tw_post_close",
        "policy": "wait_until_ready",
        "checked_at": datetime(2026, 7, 1, 5, 0, tzinfo=UTC),
        "scheduled_for": datetime(2026, 7, 1, 5, 0, tzinfo=UTC),
        "deadline_at": datetime(2026, 7, 1, 5, 30, tzinfo=UTC),
        "retry_at": datetime(2026, 7, 1, 5, 5, tzinfo=UTC),
        "ready": ready,
        "status": "ready" if ready else "incomplete",
        "retryable": retryable,
        "reason_code": "TW_DATA_READY" if ready else "TW_REQUIRED_DATA_INCOMPLETE",
        "reason_message": "ready" if ready else "incomplete",
        "required_capabilities": ["tw.market_breadth"],
        "optional_capabilities": [],
        "warnings": [] if ready else ["market_breadth: stale"],
        "missing": [],
        "provider_failures": [],
        "source_refs": ["tw.source_health.market_breadth"],
        "metadata": {},
    }


def test_generic_readiness_is_ready_without_external_refresh() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = readiness.evaluate_dispatch_readiness(
            db,
            profile="generic",
            policy="immediate",
            scheduled_for=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
            deadline_minutes=0,
            retry_interval_seconds=300,
            now=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    engine.dispose()

    assert result["ready"] is True
    assert result["reason_code"] == "READY_GENERIC"
    assert result["contract_version"] == "omi.dispatch.readiness.v1"


def test_wait_policy_records_incomplete_evidence_then_becomes_actionable() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    scheduled_at = datetime(2026, 7, 1, 5, 0, tzinfo=UTC)
    with Session(engine) as db:
        schedule = _schedule(db)
        run = schedule_runs.create_manual_run(db, schedule=schedule, now=scheduled_at)

        with patch.object(
            schedule_runs,
            "evaluate_dispatch_readiness",
            return_value=_readiness_result(ready=False, retryable=True),
        ):
            waiting = schedule_runs.evaluate_run_readiness(
                db,
                run_id=run.id,
                now=scheduled_at,
            )

        with patch.object(
            schedule_runs,
            "evaluate_dispatch_readiness",
            return_value=_readiness_result(ready=True, retryable=False),
        ):
            actionable = schedule_runs.evaluate_run_readiness(
                db,
                run_id=run.id,
                now=datetime(2026, 7, 1, 5, 5, tzinfo=UTC),
            )

        assert waiting["action"] == "wait"
        assert waiting["run"]["status"] == "waiting_data"
        assert waiting["run"]["readiness"]["warnings"] == ["market_breadth: stale"]
        assert actionable["action"] == "queue"
        assert actionable["run"]["readiness_check_count"] == 2
    engine.dispose()


def test_skip_policy_exposes_non_trading_day_reason() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db, patch.object(
        readiness,
        "build_taiwan_calendar_status",
        return_value={
            "date": "2026-07-04",
            "phase": "closed",
            "is_trading_day": False,
            "reason": "weekend",
        },
    ):
        result = readiness.evaluate_dispatch_readiness(
            db,
            profile="tw_preopen",
            policy="skip_if_incomplete",
            scheduled_for=datetime(2026, 7, 4, 0, 55, tzinfo=UTC),
            deadline_minutes=30,
            retry_interval_seconds=300,
            now=datetime(2026, 7, 4, 0, 55, tzinfo=UTC),
        )
    engine.dispose()

    assert result["ready"] is False
    assert result["retryable"] is False
    assert result["reason_code"] == "TW_NON_TRADING_DAY"
