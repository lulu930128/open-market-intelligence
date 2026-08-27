from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    TaiwanCurrentBreadthSnapshot,
    TaiwanCurrentIndexSnapshot,
)
from app.market.providers.tw_current_market import (
    CurrentBreadthAdapter,
    CurrentIndexAdapter,
    CurrentMarketProviderPayload,
)
from app.market.tw_current_market_acquisition import (
    TaiwanCurrentBreadthAcquisitionExecutor,
    TaiwanCurrentIndexAcquisitionExecutor,
)
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_BREADTH_CAPABILITY_ID,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,
    TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,
    YAHOO_CURRENT_INDEX_DESCRIPTOR,
    current_source_binding,
)
from app.market.tw_current_market_platform import (
    project_taiwan_current_breadth,
    project_taiwan_current_index,
    read_taiwan_current_breadth,
    read_taiwan_current_index,
    refresh_taiwan_current_breadth,
    refresh_taiwan_current_index,
)
from app.market_data.contracts import (
    DatasetHealthStatus,
    MarketSession,
    ResolvedEvidenceStatus,
)
from app.market_data.policies import RealtimePolicy


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 15, tzinfo=TAIPEI)


def test_current_market_session_uses_authoritative_close_lifecycle() -> None:
    from app.market.tw_current_market_platform import current_taiwan_market_session

    assert current_taiwan_market_session(
        datetime(2026, 8, 26, 13, 30, tzinfo=TAIPEI)
    ) is MarketSession.CLOSING_AUCTION
    assert current_taiwan_market_session(
        datetime(2026, 8, 26, 13, 31, tzinfo=TAIPEI)
    ) is MarketSession.CLOSE_RESOLUTION
    assert current_taiwan_market_session(
        datetime(2026, 8, 26, 13, 33, tzinfo=TAIPEI)
    ) is MarketSession.POST_CLOSE


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def _binding(provider: str, source: str, capability: str):
    binding = current_source_binding(
        provider=provider,
        source=source,
        capability_id=capability,
    )
    assert binding is not None
    return binding


def _payload_reader(payload: dict | None, calls: list[str], label: str):
    def read(scope: str, _timeout: int) -> CurrentMarketProviderPayload:
        calls.append(f"{label}:{scope}")
        if payload is None:
            return CurrentMarketProviderPayload(
                payload=None,
                status="failed",
                url=f"https://example.test/{label}",
                error=f"{label} unavailable",
            )
        return CurrentMarketProviderPayload(
            payload=payload,
            status="available",
            url=f"https://example.test/{label}",
        )

    return read


def test_current_index_shared_plan_falls_back_persists_and_rereads() -> None:
    calls: list[str] = []
    mis = CurrentIndexAdapter(
        _binding("twse_mis", "twse_mis_index_snapshot", TW_CURRENT_INDEX_CAPABILITY_ID),
        _payload_reader(None, calls, "mis"),
        clock=lambda: NOW,
    )
    yahoo = CurrentIndexAdapter(
        _binding(
            "yahoo_finance_chart",
            "yahoo_finance_chart",
            TW_CURRENT_INDEX_CAPABILITY_ID,
        ),
        _payload_reader(
            {
                "as_of": NOW.isoformat(),
                "trade_date": NOW.date().isoformat(),
                "close": 24_100.0,
                "previous_close": 24_000.0,
                "volume": 123,
            },
            calls,
            "yahoo",
        ),
        clock=lambda: NOW,
    )
    acquisition = TaiwanCurrentIndexAcquisitionExecutor((mis, yahoo))
    db, engine = _db()
    try:
        result = refresh_taiwan_current_index(
            db,
            index_id="TAIEX",
            requested_at=NOW,
            descriptors=(
                TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,
                YAHOO_CURRENT_INDEX_DESCRIPTOR,
            ),
            acquisition=acquisition,
        )
        projected = project_taiwan_current_index(result)

        assert calls == ["mis:TAIEX", "yahoo:TAIEX"]
        assert result.persistence.committed is True
        assert result.persistence.receipts_written == 2
        assert db.query(RawFetchResult).count() == 2
        assert db.query(TaiwanCurrentIndexSnapshot).count() == 1
        assert result.resolved.market_index is not None
        assert result.resolved.market_index.lineage.provider == "yahoo_finance_chart"
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
        assert projected["close"] == 24_100.0
        assert projected["raw_result_id"]
    finally:
        db.close()
        engine.dispose()


def test_current_breadth_preserves_unknown_and_not_received_partition() -> None:
    calls: list[str] = []
    adapter = CurrentBreadthAdapter(
        _binding(
            "twse_mis",
            "twse_mis_live_breadth",
            TW_CURRENT_BREADTH_CAPABILITY_ID,
        ),
        _payload_reader(
            {
                "snapshot_as_of": NOW.isoformat(),
                "trade_date": NOW.date().isoformat(),
                "scope": "full_market",
                "universe_source": "StockMaster active TWSE",
                "universe_count": 1000,
                "advance_count": 500,
                "decline_count": 400,
                "unchanged_count": 95,
                "received_unclassified_count": 3,
                "not_received_count": 2,
                "trade_value": 123_000_000,
            },
            calls,
            "mis-breadth",
        ),
        clock=lambda: NOW,
    )
    db, engine = _db()
    try:
        result = refresh_taiwan_current_breadth(
            db,
            venue="TWSE",
            requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
            acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)),
        )
        projected = project_taiwan_current_breadth(result)

        assert calls == ["mis-breadth:TWSE"]
        assert result.persistence.committed is True
        assert db.query(TaiwanCurrentBreadthSnapshot).count() == 1
        assert projected["classified_count"] == 995
        assert projected["received_unclassified_count"] == 3
        assert projected["not_received_count"] == 2
        assert projected["universe_count"] == 1000
        assert projected["decision_usable"] is False
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.PARTIAL
    finally:
        db.close()
        engine.dispose()


def test_current_breadth_normalizes_legacy_aggregate_unknown_partition() -> None:
    calls: list[str] = []
    adapter = CurrentBreadthAdapter(
        _binding(
            "twse_mis",
            "twse_mis_live_breadth",
            TW_CURRENT_BREADTH_CAPABILITY_ID,
        ),
        _payload_reader(
            {
                "snapshot_as_of": NOW.isoformat(),
                "trade_date": NOW.date().isoformat(),
                "scope": "registered_universe",
                "universe_source": "StockMaster active TWSE",
                "universe_count": 1000,
                "advance_count": 500,
                "decline_count": 300,
                "unchanged_count": 100,
                "unknown_count": 100,
                "missing_count": 50,
                "trade_value": 123_000_000,
            },
            calls,
            "mis-breadth",
        ),
        clock=lambda: NOW,
    )
    db, engine = _db()
    try:
        result = refresh_taiwan_current_breadth(
            db,
            venue="TWSE",
            requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
            acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)),
        )
        projected = project_taiwan_current_breadth(result)

        assert calls == ["mis-breadth:TWSE"]
        assert result.persistence.committed is True
        assert projected["classified_count"] == 900
        assert projected["received_unclassified_count"] == 50
        assert projected["not_received_count"] == 50
        assert projected["universe_count"] == 1000
        assert (
            projected["classified_count"]
            + projected["received_unclassified_count"]
            + projected["not_received_count"]
            == projected["universe_count"]
        )
        assert projected["decision_usable"] is False
    finally:
        db.close()
        engine.dispose()


def test_current_market_gets_are_cache_only_and_never_commit(monkeypatch) -> None:
    db, engine = _db()
    try:
        def forbidden(*_args, **_kwargs):
            raise AssertionError("current-session GET attempted mutation")

        monkeypatch.setattr(db, "commit", forbidden)
        index = read_taiwan_current_index(db, index_id="TAIEX", requested_at=NOW)
        breadth = read_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW)

        assert index.acquisition.attempted is False
        assert breadth.acquisition.attempted is False
        assert index.dataset_health is not None
        assert index.dataset_health.status is DatasetHealthStatus.MISSING
        assert breadth.dataset_health is not None
        assert breadth.dataset_health.status is DatasetHealthStatus.MISSING
        assert (
            index.resolved.health.status
            is ResolvedEvidenceStatus.POLICY_UNSATISFIED
        )
        assert (
            breadth.resolved.health.status
            is ResolvedEvidenceStatus.POLICY_UNSATISFIED
        )
    finally:
        db.close()
        engine.dispose()


def test_require_live_does_not_route_to_non_live_yahoo_descriptor() -> None:
    calls: list[str] = []
    yahoo = CurrentIndexAdapter(
        _binding(
            "yahoo_finance_chart",
            "yahoo_finance_chart",
            TW_CURRENT_INDEX_CAPABILITY_ID,
        ),
        _payload_reader(
            {
                "as_of": NOW.isoformat(),
                "close": 24_100,
                "previous_close": 24_000,
            },
            calls,
            "yahoo",
        ),
        clock=lambda: NOW,
    )
    db, engine = _db()
    try:
        result = refresh_taiwan_current_index(
            db,
            index_id="TAIEX",
            requested_at=NOW,
            policy=RealtimePolicy.REQUIRE_LIVE,
            descriptors=(YAHOO_CURRENT_INDEX_DESCRIPTOR,),
            acquisition=TaiwanCurrentIndexAcquisitionExecutor((yahoo,)),
        )

        assert calls == []
        assert result.acquisition.attempted is False
        assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    finally:
        db.close()
        engine.dispose()
