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

    assert seen_max_symbols == [32]
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
    assert len(scheduler.jobs) == 1
    from apscheduler.triggers.cron import CronTrigger
    trigger = CronTrigger(**{k:v for k,v in scheduler.jobs[0].items()
        if k in {"day_of_week", "hour", "minute", "second"}}, timezone=TAIWAN_TZ)
    clock = datetime(2026, 8, 28, 13, 29, tzinfo=TAIWAN_TZ)
    observed = []
    previous = None
    for _ in TAIWAN_SESSION_CLOSE_RETRY_MINUTES:
        previous = trigger.get_next_fire_time(previous, previous or clock)
        observed.append(previous.minute)
    assert observed == list(TAIWAN_SESSION_CLOSE_RETRY_MINUTES)
    assert {job["second"] for job in scheduler.jobs} == {
        TAIWAN_SESSION_CLOSE_TRIGGER_SECOND
    }
    assert all(job["hour"] == 13 for job in scheduler.jobs)
    assert all(job["coalesce"] is True for job in scheduler.jobs)
    assert all(job["max_instances"] == 1 for job in scheduler.jobs)


def test_closeout_depth_receipt_uses_completed_transport_clock(monkeypatch):
    from datetime import timedelta, timezone
    from app.jobs import taiwan_session_close_scheduler as owner
    from app.db.models import RawFetchResult, TaiwanStockDepthSnapshot
    from app.market.providers.twse_mis_realtime_acquisition import TwseMisRealtimeAcquisitionAdapter, TwseMisProviderSnapshot
    from app.market.taiwan_realtime_platform import acquire_taiwan_depth
    from app.market.tw_realtime_capabilities import MIS_ORDER_BOOK_DESCRIPTOR
    from app.market_data.contracts import MarketSession
    from app.market_data.policies import RealtimePolicy
    from test_twse_mis_realtime_acquisition import _db, _payload
    started = datetime(2026, 8, 26, 13, 30, 1, tzinfo=TAIWAN_TZ)
    completed = started + timedelta(seconds=7)
    tick = [started]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return tick[0].astimezone(tz) if tz else tick[0].replace(tzinfo=None)
    def delayed_response(*args):
        tick[0] = completed
        return TwseMisProviderSnapshot(raw_text=_payload(event_time="13:30:00"),
            status="available", status_code=200)
    monkeypatch.setattr(owner, "datetime", Clock)
    monkeypatch.setattr(owner, "TwseMisRealtimeAcquisitionAdapter",
        lambda **kwargs: TwseMisRealtimeAcquisitionAdapter(delayed_response, **kwargs))
    db, engine = _db()
    try:
        acquire_taiwan_depth(db, stock_id="2330", requested_at=started,
            policy=RealtimePolicy.PREFER_LIVE, session=MarketSession.CLOSE_RESOLUTION,
            descriptors=(MIS_ORDER_BOOK_DESCRIPTOR,), acquisition=owner._mis_depth_acquisition(started))
        raw = db.query(RawFetchResult).one()
        depth = db.query(TaiwanStockDepthSnapshot).one()
        expected = completed.astimezone(timezone.utc).replace(tzinfo=None)
        assert raw.fetched_at == depth.fetched_at == depth.received_at == expected
        assert depth.event_at == datetime(2026, 8, 26, 13, 30)
    finally:
        db.close()
        engine.dispose()
