from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.market.tw_bar_contracts import TaiwanBarSessionScope
from app.routers import tw_market_bars


def test_unified_bar_route_delegates_to_cache_only_service(monkeypatch) -> None:
    expected = SimpleNamespace(contract_version="tw.bar.series.v1")
    calls: list[dict[str, object]] = []

    class _FakeService:
        def __init__(self, db) -> None:
            calls.append({"db": db})

        def read_scoped_bars(self, **kwargs):
            calls[-1].update(kwargs)
            return expected

    monkeypatch.setattr(tw_market_bars, "TaiwanBarService", _FakeService)
    start = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    db = object()

    result = tw_market_bars.get_taiwan_bars(
        instrument_id="2330",
        interval="15m",
        from_time=start,
        to_time=end,
        limit=300,
        include_partial=False,
        session_scope=TaiwanBarSessionScope.HISTORY,
        db=db,
    )

    assert result is expected
    assert calls == [
        {
            "db": db,
            "instrument_id": "2330",
            "interval": "15m",
            "from_time": start,
            "to_time": end,
            "limit": 300,
            "include_partial": False,
            "session_scope": TaiwanBarSessionScope.HISTORY,
        }
    ]


def test_current_session_bar_route_rejects_consumer_owned_range(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, _db) -> None:
            pass

        def read_scoped_bars(self, **_kwargs):
            raise ValueError(
                "current_session bar scope cannot be combined with from/to"
            )

    monkeypatch.setattr(tw_market_bars, "TaiwanBarService", _FakeService)

    with pytest.raises(HTTPException) as exc_info:
        tw_market_bars.get_taiwan_bars(
            instrument_id="2330",
            interval="1m",
            from_time=datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc),
            to_time=None,
            limit=5000,
            include_partial=True,
            session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
            db=object(),
        )

    assert exc_info.value.status_code == 400
    assert "cannot be combined" in str(exc_info.value.detail)


def test_current_session_exact_snapshot_route_uses_revision_cache(monkeypatch) -> None:
    revision = "a" * 64
    expected = SimpleNamespace(
        current_session_coverage=SimpleNamespace(snapshot_revision=revision)
    )
    calls: list[dict[str, object]] = []

    class _FakeService:
        def __init__(self, _db) -> None:
            pass

        def read_current_session_snapshot_by_revision(self, **kwargs):
            calls.append(kwargs)
            return expected

    monkeypatch.setattr(tw_market_bars, "TaiwanBarService", _FakeService)

    result = tw_market_bars.get_taiwan_bars(
        instrument_id="2330",
        interval="1m",
        from_time=None,
        to_time=None,
        limit=5000,
        include_partial=True,
        session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
        expected_snapshot_revision=revision,
        db=object(),
    )

    assert result is expected
    assert calls == [
        {
            "instrument_id": "2330",
            "interval": "1m",
            "expected_snapshot_revision": revision,
            "limit": 5000,
            "include_partial": True,
        }
    ]


def test_current_session_exact_snapshot_conflict_is_typed(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, _db) -> None:
            pass

        def read_current_session_snapshot_by_revision(self, **_kwargs):
            return SimpleNamespace(
                current_session_coverage=SimpleNamespace(
                    snapshot_revision="b" * 64
                )
            )

    monkeypatch.setattr(tw_market_bars, "TaiwanBarService", _FakeService)

    with pytest.raises(HTTPException) as exc_info:
        tw_market_bars.get_taiwan_bars(
            instrument_id="2330",
            interval="1m",
            from_time=None,
            to_time=None,
            limit=5000,
            include_partial=True,
            session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
            expected_snapshot_revision="a" * 64,
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BAR_SNAPSHOT_REVISION_CONFLICT"


def test_chart_bar_route_projects_resolved_series_without_second_read(monkeypatch) -> None:
    resolved = SimpleNamespace(contract_version="tw.bar.series_read.v1")
    projected = SimpleNamespace(contract_version="tw.bar.chart_series_read.v1")
    reads: list[dict[str, object]] = []

    class _FakeService:
        def __init__(self, _db) -> None:
            pass

        def read_scoped_bars(self, **kwargs):
            reads.append(kwargs)
            return resolved

    monkeypatch.setattr(tw_market_bars, "TaiwanBarService", _FakeService)
    monkeypatch.setattr(
        tw_market_bars,
        "project_taiwan_chart_bar_series",
        lambda series: projected if series is resolved else None,
    )

    result = tw_market_bars.get_taiwan_chart_bars(
        instrument_id="2330",
        interval="1m",
        from_time=None,
        to_time=None,
        limit=5000,
        include_partial=True,
        session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
        expected_snapshot_revision=None,
        db=object(),
    )

    assert result is projected
    assert len(reads) == 1
    assert reads[0]["session_scope"] is TaiwanBarSessionScope.CURRENT_SESSION


def test_unified_bar_route_is_registered_at_one_transport_path() -> None:
    paths = [route.path for route in tw_market_bars.router.routes]

    assert paths.count("/bars/{instrument_id}") == 1
    assert paths.count("/bars/{instrument_id}/chart") == 1
