from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanMarketIndexDirectorySnapshot,
)
from app.market import indices
from app.market.schemas import MarketIndexListRead
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_index_directory import (
    TaiwanIndexDirectoryRepository,
    TaiwanIndexDirectoryTransaction,
)


FETCHED_AT = datetime(2026, 9, 1, 9, 5, tzinfo=TAIWAN_TZ)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _items() -> list[dict]:
    return [
        {
            "market": "TWSE",
            "name": "加權指數",
            "close": 45_979.67,
            "change": -351.78,
            "change_pct": -0.76,
            "trade_date": "2026-08-31",
        },
        {
            "market": "TWSE",
            "name": "電子類",
            "close": 2_100.0,
            "change": 5.0,
            "change_pct": 0.24,
            "trade_date": "2026-08-31",
        },
    ]


def test_directory_missing_contract_is_typed_when_schema_is_unavailable() -> None:
    engine = _engine()
    db = Session(engine)
    try:
        payload = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=FETCHED_AT,
        )
        public = MarketIndexListRead.model_validate(payload)

        assert public.status == "missing"
        assert public.as_of is None
        assert public.items == []
        assert public.warnings == ["TW_INDEX_DIRECTORY_SCHEMA_UNAVAILABLE"]
    finally:
        db.close()
        engine.dispose()


def test_directory_persists_atomically_and_survives_new_session() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        refreshed = TaiwanIndexDirectoryTransaction(db).persist(
            market="TWSE",
            items=_items(),
            fetched_at=FETCHED_AT,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        assert refreshed["status"] == "available"
        assert refreshed["count"] == 2
        assert refreshed["items"][0]["name"] == "加權指數"
        raw = db.query(RawFetchResult).one()
        assert raw.raw_text == '[{"指數":"發行量加權股價指數"}]'
        assert db.query(SourceRegistry).one().last_success_at is not None
        assert raw.content_hash != db.query(
            TaiwanMarketIndexDirectorySnapshot.content_hash
        ).scalar()
    finally:
        db.close()

    restarted = Session(engine)
    try:
        cached = TaiwanIndexDirectoryRepository(restarted).read(
            market="TWSE",
            limit=1,
            requested_at=FETCHED_AT + timedelta(minutes=1),
        )
        assert cached["status"] == "available"
        assert cached["source"] == "twse_openapi_mi_index"
        assert cached["count"] == 1
        assert cached["items"][0]["rank"] == 1
    finally:
        restarted.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_failed_empty_refresh_preserves_last_successful_snapshot() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        transaction = TaiwanIndexDirectoryTransaction(db)
        transaction.persist(
            market="TWSE",
            items=_items(),
            fetched_at=FETCHED_AT,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        with pytest.raises(ValueError, match="produced no items"):
            transaction.persist(
                market="TWSE",
                items=[],
                fetched_at=FETCHED_AT + timedelta(minutes=5),
                raw_payload=[],
            )

        cached = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=FETCHED_AT + timedelta(minutes=5),
        )
        assert cached["status"] == "available"
        assert cached["count"] == 2
        assert db.query(TaiwanMarketIndexDirectorySnapshot).count() == 1
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_all_unavailable_refresh_does_not_replace_last_successful_snapshot() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        transaction = TaiwanIndexDirectoryTransaction(db)
        transaction.persist(
            market="TWSE",
            items=_items(),
            fetched_at=FETCHED_AT,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        with pytest.raises(ValueError, match="no authoritative observations"):
            transaction.persist(
                market="TWSE",
                items=[
                    {
                        "market": "TWSE",
                        "name": "加權指數",
                        "close": None,
                        "change": None,
                        "change_pct": None,
                        "trade_date": None,
                    }
                ],
                fetched_at=FETCHED_AT + timedelta(minutes=5),
                raw_payload=[],
            )

        assert db.query(TaiwanMarketIndexDirectorySnapshot).count() == 1
        cached = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=FETCHED_AT + timedelta(minutes=5),
        )
        assert cached["items"][0]["close"] == 45_979.67
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_duplicate_refresh_rolls_back_and_preserves_last_successful_snapshot() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        transaction = TaiwanIndexDirectoryTransaction(db)
        transaction.persist(
            market="TWSE",
            items=_items(),
            fetched_at=FETCHED_AT,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        duplicated = [*_items(), {**_items()[0], "close": 46_000.0}]

        with pytest.raises(ValueError, match="duplicate names"):
            transaction.persist(
                market="TWSE",
                items=duplicated,
                fetched_at=FETCHED_AT + timedelta(minutes=5),
                raw_payload=[{"duplicate": True}],
            )

        cached = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=FETCHED_AT + timedelta(minutes=5),
        )
        assert cached["count"] == 2
        assert cached["items"][0]["close"] == 45_979.67
        assert db.query(TaiwanMarketIndexDirectorySnapshot).count() == 1
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_directory_staleness_is_visible_without_dropping_items() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        TaiwanIndexDirectoryTransaction(db).persist(
            market="TWSE",
            items=_items(),
            fetched_at=FETCHED_AT,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        payload = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=FETCHED_AT + timedelta(minutes=16),
        )

        assert payload["status"] == "stale"
        assert payload["freshness_status"] == "stale"
        assert payload["count"] == 2
        assert "TW_INDEX_DIRECTORY_STALE" in payload["warnings"]
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_recent_fetch_with_old_observation_date_is_stale_after_release() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    post_release = datetime(2026, 9, 1, 13, 45, tzinfo=TAIWAN_TZ)
    try:
        TaiwanIndexDirectoryTransaction(db).persist(
            market="TWSE",
            items=_items(),
            fetched_at=post_release,
            raw_payload=[{"指數": "發行量加權股價指數"}],
        )
        payload = TaiwanIndexDirectoryRepository(db).read(
            market="TWSE",
            limit=80,
            requested_at=post_release + timedelta(minutes=1),
        )

        assert payload["transport_fresh"] is True
        assert payload["observation_current"] is False
        assert payload["latest_trade_date"].isoformat() == "2026-08-31"
        assert payload["expected_trade_date"].isoformat() == "2026-09-01"
        assert payload["status"] == "stale"
        assert payload["freshness_status"] == "stale"
        assert "TW_INDEX_DIRECTORY_OBSERVATION_DATE_STALE" in payload["warnings"]
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_get_directory_is_cache_only_and_never_calls_provider() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        with patch.object(
            indices,
            "_fetch_twse_index_list",
            side_effect=AssertionError("GET must not call provider"),
        ) as provider:
            payload = indices.get_market_index_list("TWSE", db=db)

        provider.assert_not_called()
        assert payload["status"] == "missing"
        assert MarketIndexListRead.model_validate(payload).as_of is None
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
