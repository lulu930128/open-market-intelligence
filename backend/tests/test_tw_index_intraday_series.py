from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanCurrentIndexSnapshot,
)
from app.market import indices
from app.market.schemas import IntradayTrendRead
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_current_market_capabilities import current_source_binding
from app.market.tw_current_market_platform import (
    project_taiwan_index_intraday_series,
    read_taiwan_index_intraday_series,
)


TRADE_DATE = datetime(2026, 8, 31, 9, 0, tzinfo=TAIWAN_TZ).date()


def _db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine), engine


def _persist_index_event(
    db: Session,
    *,
    provider: str,
    source_name: str,
    event_at: datetime,
    close_value: float,
    price_change: float,
    raw_symbol: str | None = None,
    official: bool = False,
    provisional: bool = True,
    finalization: str = "provisional",
) -> None:
    binding = current_source_binding(
        provider=provider,
        source=source_name,
        capability_id="market.index.snapshot",
    )
    assert binding is not None
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == source_name)
        .first()
    )
    if source is None:
        source = SourceRegistry(
            source_name=source_name,
            source_type=binding.source_type,
            category="market_data",
            enabled=True,
            priority=binding.descriptor.priority,
            parser_type=binding.parser_version,
            auth_type=binding.auth_type,
            reliability_level=binding.descriptor.authority.value,
        )
        db.add(source)
        db.flush()
    raw_text = (
        json.dumps(
            {
                "channel": "indices",
                "data": {"symbol": raw_symbol, "index": close_value},
            }
        )
        if raw_symbol is not None
        else json.dumps({"index_id": "TAIEX", "close": close_value})
    )
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=event_at.astimezone(timezone.utc),
        method="STREAM" if raw_symbol else "GET",
        content_hash=f"{provider}-{event_at.isoformat()}-{close_value}",
        raw_text=raw_text,
        parser_version=binding.parser_version,
    )
    db.add(raw)
    db.flush()
    db.add(
        TaiwanCurrentIndexSnapshot(
            source_id=source.id,
            raw_result_id=raw.id,
            provider=provider,
            source=source_name,
            authority=binding.descriptor.authority.value,
            raw_contract_version=binding.parser_version,
            index_id="TAIEX",
            venue="TWSE",
            trade_date=TRADE_DATE,
            event_at=event_at,
            received_at=event_at.astimezone(timezone.utc),
            fetched_at=event_at.astimezone(timezone.utc),
            session="continuous",
            close_value=close_value,
            price_change=price_change,
            observation_state="available",
            value_semantics="current_index_snapshot",
            finalization=finalization,
            official=official,
            provisional=provisional,
        )
    )
    db.flush()


def test_series_rejects_ir0001_and_aggregates_exchange_events() -> None:
    db, engine = _db()
    try:
        _persist_index_event(
            db,
            provider="fugle_marketdata",
            source_name="fugle_indices_stream",
            event_at=datetime(2026, 8, 31, 9, 0, 15, tzinfo=TAIWAN_TZ),
            close_value=46_000.0,
            price_change=10.0,
            raw_symbol="IR0001",
        )
        _persist_index_event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 8, 31, 9, 0, 5, tzinfo=TAIWAN_TZ),
            close_value=45_900.0,
            price_change=-100.0,
        )
        _persist_index_event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 8, 31, 9, 0, 50, tzinfo=TAIWAN_TZ),
            close_value=45_920.0,
            price_change=-80.0,
        )
        db.commit()

        series = read_taiwan_index_intraday_series(
            db,
            index_id="TAIEX",
            requested_at=datetime(2026, 8, 31, 9, 0, 59, tzinfo=TAIWAN_TZ),
        )

        assert series.status == "available"
        assert len(series.points) == 1
        point = series.points[0]
        assert point.provider == "twse_mis"
        assert point.open_value == 45_900
        assert point.high_value == 45_920
        assert point.low_value == 45_900
        assert point.close_value == 45_920
        assert series.rejected_candidate_count == 1
        assert series.candidate_rejections[0]["reason_code"] == (
            "CURRENT_INDEX_RAW_SCOPE_IDENTITY_MISMATCH"
        )
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_exchange_source_wins_same_minute_over_valid_vendor_stream() -> None:
    db, engine = _db()
    try:
        _persist_index_event(
            db,
            provider="fugle_marketdata",
            source_name="fugle_indices_stream",
            event_at=datetime(2026, 8, 31, 9, 0, 15, tzinfo=TAIWAN_TZ),
            close_value=45_905.0,
            price_change=-95.0,
            raw_symbol="IX0001",
        )
        _persist_index_event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 8, 31, 9, 0, 20, tzinfo=TAIWAN_TZ),
            close_value=45_910.0,
            price_change=-90.0,
        )
        db.commit()

        series = read_taiwan_index_intraday_series(
            db,
            index_id="TAIEX",
            requested_at=datetime(2026, 8, 31, 9, 0, 59, tzinfo=TAIWAN_TZ),
        )

        assert len(series.points) == 1
        assert series.points[0].provider == "twse_mis"
        assert series.points[0].close_value == 45_910
        assert series.rejected_candidate_count == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_series_projection_validates_against_public_intraday_contract() -> None:
    db, engine = _db()
    try:
        _persist_index_event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 8, 31, 9, 0, 5, tzinfo=TAIWAN_TZ),
            close_value=45_900.0,
            price_change=-100.0,
        )
        db.commit()
        series = read_taiwan_index_intraday_series(
            db,
            index_id="TAIEX",
            requested_at=datetime(2026, 8, 31, 9, 0, 59, tzinfo=TAIWAN_TZ),
        )

        payload = indices._finalize_index_intraday_contract(
            {
                **project_taiwan_index_intraday_series(series),
                "symbol": "^TWII",
                "volume_semantics": "not_available_for_index_series",
            }
        )
        public = IntradayTrendRead.model_validate(payload)

        assert public.point_count == 1
        assert public.points[0].provider == "twse_mis"
        assert public.points[0].source == "twse_mis_index_snapshot"
        assert public.series_coverage is not None
        assert public.series_coverage["resolved_minute_count"] == 1
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_current_1330_point_is_session_close_not_official_daily() -> None:
    db, engine = _db()
    try:
        _persist_index_event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 8, 31, 13, 30, tzinfo=TAIWAN_TZ),
            close_value=45_979.67,
            price_change=-351.78,
            official=True,
            provisional=True,
            finalization="provisional",
        )
        db.commit()
        series = read_taiwan_index_intraday_series(
            db,
            index_id="TAIEX",
            requested_at=datetime(2026, 8, 31, 13, 30, tzinfo=TAIWAN_TZ),
        )
        payload = indices._finalize_index_intraday_contract(
            {
                **project_taiwan_index_intraday_series(series),
                "symbol": "^TWII",
                "volume_semantics": "not_available_for_index_series",
            }
        )

        assert payload["points"][0]["bar_type"] == "session_close_marker"
        assert payload["points"][0]["price_semantics"] == (
            "session_close_index_value"
        )
        assert payload["points"][0]["indicator_eligible"] is False
        assert payload["current_observation"]["price_semantics"] == (
            "session_close_index_value"
        )
        assert payload["current_observation"]["freshness_status"] == (
            "session_final"
        )
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
