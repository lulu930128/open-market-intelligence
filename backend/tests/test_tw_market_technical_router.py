from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.market import tw_chart_service
from app.routers import tw_market_technical


def _bars(revision: str = "a" * 64):
    return SimpleNamespace(
        identity=SimpleNamespace(
            series_fingerprint="b" * 64,
            lineage_digest="c" * 64,
            state_digest="d" * 64,
            series_revision=revision,
        )
    )


def _technical(bars):
    return SimpleNamespace(bar_series_revision=bars.identity.series_revision)


def test_chart_bundle_reads_bars_once_and_calculates_from_same_object(
    monkeypatch,
) -> None:
    bars = _bars()
    calls: list[tuple[str, object]] = []

    class _FakeBarService:
        def __init__(self, db) -> None:
            calls.append(("bar_service_db", db))

        def read_bars(self, **kwargs):
            calls.append(("bar_read", kwargs))
            return bars

    class _FakeTechnicalService:
        def calculate(self, received, **kwargs):
            calls.append(("technical_input", received))
            assert received is bars
            assert kwargs["expected_series_revision"] == bars.identity.series_revision
            return _technical(received)

    monkeypatch.setattr(tw_chart_service, "TaiwanBarService", _FakeBarService)
    monkeypatch.setattr(
        tw_chart_service,
        "TaiwanTechnicalService",
        _FakeTechnicalService,
    )
    monkeypatch.setattr(
        tw_chart_service,
        "TaiwanChartBundleRead",
        lambda **values: SimpleNamespace(**values),
    )

    result = tw_market_technical.get_taiwan_chart_bundle(
        instrument_id="2330",
        interval="15m",
        from_time=None,
        to_time=None,
        limit=500,
        include_partial=True,
        ma_windows=None,
        volume_ma_windows=None,
        db=object(),
    )

    assert sum(kind == "bar_read" for kind, _ in calls) == 1
    assert result.bars is bars
    assert result.technical.bar_series_revision == result.series_revision


def test_chart_route_delegates_to_chart_service(monkeypatch) -> None:
    expected = object()
    calls: list[dict[str, object]] = []

    class _FakeChartService:
        def __init__(self, db) -> None:
            assert db == "db"

        def read(self, **kwargs):
            calls.append(kwargs)
            return expected

    monkeypatch.setattr(tw_market_technical, "TaiwanChartService", _FakeChartService)

    result = tw_market_technical.get_taiwan_chart_bundle(
        instrument_id="2330",
        interval="15m",
        from_time=None,
        to_time=None,
        limit=500,
        include_partial=True,
        ma_windows=None,
        volume_ma_windows=None,
        db="db",
    )

    assert result is expected
    assert calls[0]["instrument_id"] == "2330"
    assert calls[0]["interval"] == "15m"


def test_separate_technical_route_returns_typed_revision_conflict(
    monkeypatch,
) -> None:
    bars = _bars(revision="f" * 64)

    class _FakeBarService:
        def __init__(self, db) -> None:
            pass

        def read_bars(self, **kwargs):
            return bars

    monkeypatch.setattr(tw_market_technical, "TaiwanBarService", _FakeBarService)

    with pytest.raises(HTTPException) as exc_info:
        tw_market_technical.get_taiwan_technical_series(
            instrument_id="2330",
            interval="15m",
            from_time=None,
            to_time=None,
            limit=500,
            include_partial=True,
            expected_series_revision="0" * 64,
            ma_windows=None,
            volume_ma_windows=None,
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BAR_SERIES_REVISION_CONFLICT"
    assert exc_info.value.detail["current_series_revision"] == "f" * 64


def test_technical_contract_route_is_pure(monkeypatch) -> None:
    expected = {"contract_version": "tw.technical.capabilities.v1"}
    monkeypatch.setattr(
        tw_market_technical,
        "build_taiwan_technical_capability_contract",
        lambda: expected,
    )

    assert tw_market_technical.get_taiwan_technical_contract() is expected


def test_canonical_routes_are_registered_once() -> None:
    paths = [route.path for route in tw_market_technical.router.routes]

    assert paths.count("/technical/contracts/tw") == 1
    assert paths.count("/technical/{instrument_id}/series") == 1
    assert paths.count("/chart/{instrument_id}") == 1
