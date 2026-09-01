from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers import tw_market_bars


def test_unified_bar_route_delegates_to_cache_only_service(monkeypatch) -> None:
    expected = SimpleNamespace(contract_version="tw.bar.series.v1")
    calls: list[dict[str, object]] = []

    class _FakeService:
        def __init__(self, db) -> None:
            calls.append({"db": db})

        def read_bars(self, **kwargs):
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
        }
    ]


def test_unified_bar_route_is_registered_at_one_transport_path() -> None:
    paths = [route.path for route in tw_market_bars.router.routes]

    assert paths.count("/bars/{instrument_id}") == 1
