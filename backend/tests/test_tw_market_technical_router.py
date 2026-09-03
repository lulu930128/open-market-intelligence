from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.market import tw_chart_service
from app.market.tw_bar_contracts import TaiwanBarSessionScope
from app.routers import tw_market_technical


def _bars(revision: str = "a" * 64):
    return SimpleNamespace(
        identity=SimpleNamespace(
            series_fingerprint="b" * 64,
            lineage_digest="c" * 64,
            state_digest="d" * 64,
            series_revision=revision,
        ),
        current_session_coverage=None,
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


def test_current_session_chart_uses_backend_owned_session_window(
    monkeypatch,
) -> None:
    bars = _bars()
    calls: list[tuple[str, object]] = []

    class _FakeBarService:
        def __init__(self, db) -> None:
            pass

        def read_current_session_bars(self, **kwargs):
            calls.append(("current_session_read", kwargs))
            return bars

    class _FakeTechnicalService:
        def calculate(self, received, **_kwargs):
            return _technical(received)

    monkeypatch.setattr(tw_chart_service, "TaiwanBarService", _FakeBarService)
    monkeypatch.setattr(
        tw_chart_service,
        "taiwan_current_session_bar_window",
        lambda _requested_at: (
            "now",
            date(2026, 9, 3),
            "from",
            "to",
        ),
    )
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

    result = tw_chart_service.TaiwanChartService(object()).read(
        instrument_id="TAIEX",
        interval="1m",
        session_scope=tw_chart_service.TaiwanChartSessionScope.CURRENT_SESSION,
    )

    assert calls == [
        (
            "current_session_read",
            {
                "instrument_id": "TAIEX",
                "interval": "1m",
                "limit": 500,
                "include_partial": True,
                "requested_at": "now",
            },
        )
    ]
    assert result.session_scope == "current_session"
    assert result.presentation_trade_date.isoformat() == "2026-09-03"


def test_index_chart_uses_resolved_index_quote_side(
    monkeypatch,
) -> None:
    bars = _bars()
    bars.instrument = SimpleNamespace(
        symbol="TAIEX",
        instrument_type=SimpleNamespace(value="index"),
    )
    expected_quote_side = {
        "current_observation": {"value": 46_200.0},
        "previous_close": 46_000.0,
    }
    summary_item = {
        "index_id": "TAIEX",
        "resolution": {"resolution_version": "tw.index.resolution.v3"},
    }
    summary_calls: list[tuple[object, bool, object]] = []

    class _FakeBarService:
        def __init__(self, _db) -> None:
            pass

        def read_current_session_bars(self, **_kwargs):
            return bars

    class _FakeTechnicalService:
        def calculate(self, received, **_kwargs):
            return _technical(received)

    monkeypatch.setattr(tw_chart_service, "TaiwanBarService", _FakeBarService)
    monkeypatch.setattr(
        tw_chart_service,
        "taiwan_current_session_bar_window",
        lambda _requested_at: (
            "now",
            date(2026, 9, 3),
            "from",
            "to",
        ),
    )
    monkeypatch.setattr(
        tw_chart_service,
        "TaiwanTechnicalService",
        _FakeTechnicalService,
    )
    monkeypatch.setattr(
        tw_chart_service,
        "get_market_index_summary",
        lambda db, force_refresh=False, requested_at=None: (
            summary_calls.append((db, force_refresh, requested_at)),
            {"indices": [summary_item]},
        )[1],
    )
    monkeypatch.setattr(
        tw_chart_service,
        "project_taiwan_index_quote_side",
        lambda item: expected_quote_side if item is summary_item else None,
    )
    monkeypatch.setattr(
        tw_chart_service,
        "read_taiwan_public_quote_projection",
        lambda *_args, **_kwargs: pytest.fail(
            "Taiwan index chart must not use the stock quote owner"
        ),
    )
    monkeypatch.setattr(
        tw_chart_service,
        "TaiwanChartBundleRead",
        lambda **values: SimpleNamespace(**values),
    )

    db = object()
    result = tw_chart_service.TaiwanChartService(db).read(
        instrument_id="TAIEX",
        interval="1m",
        session_scope=tw_chart_service.TaiwanChartSessionScope.CURRENT_SESSION,
    )

    assert summary_calls == [(db, False, "now")]
    assert result.quote_side is expected_quote_side


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

        def read_scoped_bars(self, **kwargs):
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
            session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BAR_SERIES_REVISION_CONFLICT"
    assert exc_info.value.detail["current_series_revision"] == "f" * 64


def test_separate_technical_route_forwards_same_session_scope(monkeypatch) -> None:
    bars = _bars()
    calls: list[dict[str, object]] = []

    class _FakeBarService:
        def __init__(self, _db) -> None:
            pass

        def read_scoped_bars(self, **kwargs):
            calls.append(kwargs)
            return bars

    class _FakeTechnicalService:
        def calculate(self, received, **_kwargs):
            return _technical(received)

    monkeypatch.setattr(tw_market_technical, "TaiwanBarService", _FakeBarService)
    monkeypatch.setattr(
        tw_market_technical,
        "TaiwanTechnicalService",
        _FakeTechnicalService,
    )

    result = tw_market_technical.get_taiwan_technical_series(
        instrument_id="2330",
        interval="1m",
        from_time=None,
        to_time=None,
        limit=5000,
        include_partial=True,
        expected_series_revision=bars.identity.series_revision,
        ma_windows=None,
        volume_ma_windows=None,
        session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
        db=object(),
    )

    assert result.bar_series_revision == bars.identity.series_revision
    assert calls[0]["session_scope"] is TaiwanBarSessionScope.CURRENT_SESSION


def test_current_session_snapshot_pin_uses_full_calculation_window(
    monkeypatch,
) -> None:
    bars = _bars(revision="e" * 64)
    bars.current_session_coverage = SimpleNamespace(snapshot_revision="f" * 64)
    bar_calls: list[dict[str, object]] = []
    technical_calls: list[dict[str, object]] = []

    class _FakeBarService:
        def __init__(self, _db) -> None:
            pass

        def read_current_session_snapshot_by_revision(self, **kwargs):
            bar_calls.append(kwargs)
            return bars

    class _FakeTechnicalService:
        def calculate(self, received, **kwargs):
            assert received is bars
            technical_calls.append(kwargs)
            return SimpleNamespace(
                bar_series_revision=received.identity.series_revision,
                bar_snapshot_revision=received.current_session_coverage.snapshot_revision,
            )

    monkeypatch.setattr(tw_market_technical, "TaiwanBarService", _FakeBarService)
    monkeypatch.setattr(
        tw_market_technical,
        "TaiwanTechnicalService",
        _FakeTechnicalService,
    )

    result = tw_market_technical.get_taiwan_technical_series(
        instrument_id="2330",
        interval="1m",
        from_time=None,
        to_time=None,
        limit=8,
        include_partial=True,
        expected_snapshot_revision="f" * 64,
        ma_windows="5,20,60",
        volume_ma_windows="5,20",
        session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
        db=object(),
    )

    assert result.bar_snapshot_revision == "f" * 64
    assert bar_calls[0]["expected_snapshot_revision"] == "f" * 64
    assert "limit" not in bar_calls[0]
    assert technical_calls[0]["expected_series_revision"] is None
    assert technical_calls[0]["expected_snapshot_revision"] == "f" * 64
    assert technical_calls[0]["response_limit"] == 8


def test_current_session_snapshot_revision_conflict_is_typed(
    monkeypatch,
) -> None:
    bars = _bars(revision="e" * 64)
    bars.current_session_coverage = SimpleNamespace(snapshot_revision="f" * 64)

    class _FakeBarService:
        def __init__(self, _db) -> None:
            pass

        def read_current_session_snapshot_by_revision(self, **_kwargs):
            return bars

    monkeypatch.setattr(tw_market_technical, "TaiwanBarService", _FakeBarService)

    with pytest.raises(HTTPException) as exc_info:
        tw_market_technical.get_taiwan_technical_series(
            instrument_id="2330",
            interval="1m",
            from_time=None,
            to_time=None,
            limit=8,
            include_partial=True,
            expected_snapshot_revision="0" * 64,
            ma_windows=None,
            volume_ma_windows=None,
            session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "BAR_SNAPSHOT_REVISION_CONFLICT",
        "expected_snapshot_revision": "0" * 64,
        "current_snapshot_revision": "f" * 64,
    }


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
