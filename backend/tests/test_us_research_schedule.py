"""Offline schedule boundaries, default registration and read-only projection."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import JobRun
from app.jobs import us_watchlist_research as scans
from app.us_market.research_schedule import postclose_schedule
from test_research_trade_journal import engine


@pytest.mark.parametrize("stamp,basis,eligible,next_check", [
    ("2026-11-05T20:59:00Z", "2026-11-04", False, "2026-11-05T16:15:00-05:00"),
    ("2026-11-05T21:10:00Z", "2026-11-05", False, "2026-11-05T16:15:00-05:00"),
    ("2026-11-05T21:15:00Z", "2026-11-05", True, "2026-11-05T16:15:00-05:00"),
    ("2026-11-05T21:15:01Z", "2026-11-05", True, "2026-11-05T16:25:00-05:00"),
    ("2026-11-06T08:58:00Z", "2026-11-05", True, "2026-11-06T16:15:00-05:00"),
    ("2026-11-06T09:00:00Z", "2026-11-05", False, "2026-11-06T16:15:00-05:00"),
    # Summer time, holiday, early close and weekend use the exchange owner.
    ("2026-10-30T20:15:00Z", "2026-10-30", True, "2026-10-30T16:15:00-04:00"),
    ("2026-11-26T21:15:00Z", "2026-11-25", False, "2026-11-27T13:15:00-05:00"),
    ("2026-11-27T18:14:00Z", "2026-11-27", False, "2026-11-27T13:15:00-05:00"),
    ("2026-11-27T18:15:00Z", "2026-11-27", True, "2026-11-27T13:15:00-05:00"),
    ("2026-11-28T06:00:00Z", "2026-11-27", True, "2026-11-28T01:05:00-05:00"),
    ("2026-11-28T17:00:00Z", "2026-11-27", False, "2026-11-30T16:15:00-05:00"),
])
def test_postclose_window(stamp, basis, eligible, next_check):
    schedule = postclose_schedule(datetime.fromisoformat(stamp))
    assert schedule["in_window"] is eligible
    assert schedule["basis_trade_date"] == basis
    assert schedule["next_check_at"] == next_check


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        postclose_schedule(datetime(2026, 11, 5))


def test_default_registration_and_disabled_opt_out(monkeypatch):
    from app.jobs.scheduler import _add_us_watchlist_research_job
    assert Settings.model_fields["enable_us_watchlist_research_scheduler"].default is True
    calls = []
    fake = SimpleNamespace(add_job=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", True)
    assert _add_us_watchlist_research_job(fake)
    _, kwargs = calls[0]
    assert kwargs["id"] == scans.JOB_TYPE and kwargs["max_instances"] == 1 and kwargs["coalesce"]
    trigger = kwargs["trigger"]
    now = datetime(2026, 11, 27, 18, 14, tzinfo=timezone.utc)
    assert trigger.get_next_fire_time(None, now).isoformat() == "2026-11-27T13:15:00-05:00"
    monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", False)
    assert not _add_us_watchlist_research_job(fake)
    assert len(calls) == 1


@pytest.mark.parametrize("enabled,stamp", [
    (True, "2026-11-05T15:00:00Z"), (True, "2026-11-26T21:00:00Z"),
    (False, "2026-11-05T22:00:00Z"),
])
def test_closed_window_and_disabled_schedule_never_open_database(monkeypatch, enabled, stamp):
    monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", enabled)
    monkeypatch.setattr(scans, "utc_now", lambda: datetime.fromisoformat(stamp))
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: pytest.fail("Closed schedule opened database"))
    assert scans.run_scheduled_scan() is None


def test_status_read_only_and_schedule_state(engine, monkeypatch):
    JobRun.__table__.create(engine)
    monkeypatch.setattr(scans, "utc_now", lambda: datetime(2026, 11, 5, 22, tzinfo=timezone.utc))
    monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", True)
    monkeypatch.setattr(scans.jobs, "enqueue_job", lambda **kw: pytest.fail("GET enqueued work"))
    with Session(engine) as db:
        db.execute(text("PRAGMA query_only=ON"))
        result = scans.read_latest(db)
        assert result["job"] is None and result["schedule"]["state"] == "ready"
        assert result["schedule"]["enabled"] is True
        monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", False)
        result = scans.read_latest(db)
        assert result["schedule"]["state"] == "disabled" and result["schedule"]["next_check_at"] is None


@pytest.mark.parametrize("status,result,state", [
    ("success", {"next_cursor": None}, "completed_for_session"),
    ("success", {"next_cursor": 25}, "ready"),
    ("error", None, "requires_attention"), ("running", None, "running"),
])
def test_receipt_state_changes_next_automatic_window(engine, monkeypatch, status, result, state):
    JobRun.__table__.create(engine)
    with Session(engine) as db:
        # Serialization is stubbed; only the isolated existence lookup is real.
        db.add(JobRun(job_type=scans.JOB_TYPE, target="fixture", status="success", request_json="{}"))
        db.commit()
        monkeypatch.setattr(scans, "utc_now", lambda: datetime(2026, 11, 5, 22, tzinfo=timezone.utc))
        monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", True)
        monkeypatch.setattr(scans.jobs, "serialize_job", lambda job: {
            "id": job.id, "status": status, "request": {"basis_trade_date": "2026-11-05"}, "result": result})
        db.execute(text("PRAGMA query_only=ON"))
        schedule = scans.read_latest(db)["schedule"]
        assert schedule["state"] == state
        if state in {"completed_for_session", "requires_attention"}:
            assert schedule["next_check_at"] == "2026-11-06T16:15:00-05:00"
