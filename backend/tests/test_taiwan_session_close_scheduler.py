from __future__ import annotations

from datetime import datetime

from app.jobs.taiwan_session_close_scheduler import (
    TAIWAN_SESSION_CLOSE_RETRY_MINUTES,
    TAIWAN_SESSION_CLOSE_TRIGGER_SECOND,
    add_taiwan_session_close_jobs,
    collect_taiwan_session_closes,
)
from app.market.trading_calendar import TAIWAN_TZ


class _FakeDb:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.closed = False

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, function, **kwargs) -> None:
        self.jobs.append({"function": function, **kwargs})


def test_session_closeout_skips_before_exact_boundary_without_opening_db() -> None:
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return _FakeDb()

    result = collect_taiwan_session_closes(
        now=datetime(2026, 8, 28, 13, 30, 0, tzinfo=TAIWAN_TZ),
        session_factory=session_factory,
    )

    assert result["status"] == "skipped"
    assert opened is False


def test_session_closeout_uses_bounded_universe_and_short_circuits_final() -> None:
    db = _FakeDb()
    acquired: list[str] = []
    seen_max_symbols: list[int] = []

    def universe_resolver(_db, *, max_symbols: int):
        seen_max_symbols.append(max_symbols)
        return {
            "symbols": ["2330", "3711"],
            "targets": [
                {"stock_id": "2330", "origins": ["configured"]},
                {"stock_id": "3711", "origins": ["holding"]},
            ],
        }

    def reader(_db, *, stock_id: str, **_kwargs):
        return {"stock_id": stock_id, "cached": stock_id == "2330"}

    def acquirer(_db, *, stock_id: str, **_kwargs):
        acquired.append(stock_id)
        return {"stock_id": stock_id, "cached": False, "acquired": True}

    def projector(value):
        available = bool(value["cached"] or value.get("acquired"))
        return {
            "available": available,
            "status": "session_final" if available else "unavailable",
            "provider": "test",
        }

    result = collect_taiwan_session_closes(
        now=datetime(2026, 8, 28, 13, 30, 1, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=universe_resolver,
        reader=reader,
        acquirer=acquirer,
        projector=projector,
        depth_reader=lambda *_args, **_kwargs: {"available": True},
        depth_projector=lambda value, **_kwargs: value,
    )

    assert seen_max_symbols == [3]
    assert acquired == ["3711"]
    assert result["status"] == "success"
    assert result["confirmed_count"] == 2
    assert [item["status"] for item in result["results"]] == [
        "already_final",
        "confirmed",
    ]
    assert result["universe"]["targets"][1]["origins"] == ["holding"]
    assert db.closed is True


def test_session_closeout_reports_pending_and_per_symbol_failure() -> None:
    db = _FakeDb()

    def acquirer(_db, *, stock_id: str, **_kwargs):
        if stock_id == "3711":
            raise RuntimeError("provider unavailable")
        return {"available": False, "status": "resolving"}

    result = collect_taiwan_session_closes(
        now=datetime(2026, 8, 28, 13, 31, 1, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=lambda _db, **_kwargs: {"symbols": ["2330", "3711"]},
        reader=lambda *_args, **_kwargs: {"available": False},
        acquirer=acquirer,
        projector=lambda value: value,
        depth_reader=lambda *_args, **_kwargs: {"available": True},
        depth_projector=lambda value, **_kwargs: value,
    )

    assert result["status"] == "partial"
    assert result["pending_count"] == 1
    assert result["failed_count"] == 1
    assert result["depth_pending_count"] == 0
    assert db.rollback_count == 1
    assert db.closed is True


def test_closeout_captures_missing_depth_once_during_close_resolution() -> None:
    db = _FakeDb()
    acquired_depth: list[str] = []

    def depth_acquirer(_db, *, stock_id: str, **kwargs):
        acquired_depth.append(stock_id)
        assert kwargs["session"].value == "close_resolution"
        return {"available": True, "status": "available", "provider": "twse_mis"}

    result = collect_taiwan_session_closes(
        now=datetime(2026, 8, 28, 13, 30, 1, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=lambda _db, **_kwargs: {"symbols": ["2330"]},
        reader=lambda *_args, **_kwargs: {"available": True, "status": "session_final"},
        projector=lambda value: value,
        depth_reader=lambda *_args, **_kwargs: {"available": False, "status": "unavailable"},
        depth_acquirer=depth_acquirer,
        depth_projector=lambda value, **_kwargs: value,
        depth_acquisition_factory=lambda _now: object(),
    )

    assert acquired_depth == ["2330"]
    assert result["status"] == "success"
    assert result["depth_snapshot_count"] == 1
    assert result["results"][0]["depth_snapshot_provider"] == "twse_mis"


def test_closeout_post_close_is_cache_only_for_depth_snapshot() -> None:
    db = _FakeDb()

    def forbidden_depth_acquirer(*_args, **_kwargs):
        raise AssertionError("post-close depth acquisition must stay disabled")

    result = collect_taiwan_session_closes(
        now=datetime(2026, 8, 28, 13, 33, 1, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=lambda _db, **_kwargs: {"symbols": ["2330"]},
        reader=lambda *_args, **_kwargs: {"available": True, "status": "session_final"},
        projector=lambda value: value,
        depth_reader=lambda *_args, **_kwargs: {"available": False, "status": "unavailable"},
        depth_acquirer=forbidden_depth_acquirer,
        depth_projector=lambda value, **_kwargs: value,
    )

    assert result["status"] == "partial"
    assert result["depth_pending_count"] == 1
    assert result["depth_failed_count"] == 0


def test_session_closeout_registers_exact_bounded_retry_slots() -> None:
    scheduler = _FakeScheduler()

    assert add_taiwan_session_close_jobs(scheduler) is True
    assert len(scheduler.jobs) == len(TAIWAN_SESSION_CLOSE_RETRY_MINUTES)
    assert [job["minute"] for job in scheduler.jobs] == list(
        TAIWAN_SESSION_CLOSE_RETRY_MINUTES
    )
    assert {job["second"] for job in scheduler.jobs} == {
        TAIWAN_SESSION_CLOSE_TRIGGER_SECOND
    }
    assert all(job["hour"] == 13 for job in scheduler.jobs)
    assert all(job["coalesce"] is True for job in scheduler.jobs)
    assert all(job["max_instances"] == 1 for job in scheduler.jobs)
