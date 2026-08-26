from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import shutil
import uuid
from zoneinfo import ZoneInfo

from alembic import command
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.migrations import create_alembic_config
from app.db.models import Base, TaiwanIntradayStockState, TaiwanMarketMinuteState
from app.market.taiwan_market_state import persist_taiwan_market_minute_state
from app.market.tw_intraday_state import (
    attach_current_market_lineage_to_stock_rows,
    persist_taiwan_intraday_stock_states,
)


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)
LINEAGE_COLUMNS = {
    "component_raw_result_ids_json",
    "component_sources_json",
    "component_event_times_json",
    "component_time_skew_seconds",
    "calculation_version",
    "lineage_complete",
}


@contextmanager
def _migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_tw_derived_lineage"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_derived_state_lineage_migration_is_additive_and_scoped() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'derived.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            for table_name in (
                "taiwan_market_minute_state",
                "taiwan_intraday_stock_state",
            ):
                columns = {
                    item["name"] for item in inspector.get_columns(table_name)
                }
                assert LINEAGE_COLUMNS <= columns
        finally:
            engine.dispose()

        command.downgrade(config, "20260826_0071")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            for table_name in (
                "taiwan_market_minute_state",
                "taiwan_intraday_stock_state",
            ):
                columns = {
                    item["name"] for item in inspector.get_columns(table_name)
                }
                assert not (LINEAGE_COLUMNS & columns)
            assert "taiwan_current_index_snapshot" in inspector.get_table_names()
        finally:
            engine.dispose()

        command.upgrade(config, "head")


def test_market_minute_state_persists_each_component_and_time_skew() -> None:
    db, engine = _db()
    try:
        breadth_at = NOW + timedelta(seconds=7)
        payload = {
            "as_of": breadth_at.isoformat(),
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "close": 24_000,
                    "change": 100,
                    "change_pct": 0.42,
                    "time": NOW.date().isoformat(),
                    "breadth_status": {"status": "ready"},
                    "breadth": {
                        "market": "TWSE",
                        "scope": "full_market",
                        "trade_date": NOW.date().isoformat(),
                        "snapshot_as_of": breadth_at.isoformat(),
                        "advance_count": 500,
                        "decline_count": 400,
                        "unchanged_count": 100,
                        "total_count": 1000,
                        "trade_value": 100_000,
                        "decision_usable": True,
                    },
                    "current_data_core": {
                        "index": {
                            "provider": "twse_mis",
                            "source": "twse_mis_index_snapshot",
                            "raw_result_id": "raw_fetch_result:11",
                            "as_of": NOW.isoformat(),
                        },
                        "breadth": {
                            "provider": "twse_mis",
                            "source": "twse_mis_live_breadth",
                            "raw_result_id": "raw_fetch_result:12",
                            "as_of": breadth_at.isoformat(),
                        },
                    },
                }
            ],
        }
        result = persist_taiwan_market_minute_state(db, payload=payload, now=breadth_at)
        row = db.query(TaiwanMarketMinuteState).one()

        assert result["rows"][0]["lineage_complete"] is True
        assert row.lineage_complete is True
        assert json.loads(row.component_raw_result_ids_json or "[]") == [
            "raw_fetch_result:11",
            "raw_fetch_result:12",
        ]
        assert row.component_time_skew_seconds == 7
        assert row.calculation_version == "tw.market.minute_state.derived.v2"
    finally:
        db.close()
        engine.dispose()


def test_stock_state_lineage_is_attached_and_missing_lineage_fails_closed() -> None:
    source_row = {
        "provider": "twse_mis",
        "market": "TWSE",
        "code": "2330",
        "trade_date": NOW.date(),
        "as_of": NOW,
        "current_price": 100.0,
        "previous_close": 99.0,
        "has_actual_trade": True,
        "market_session": "regular",
        "source": "twse_mis_twse_registered_universe",
    }
    summary = {
        "indices": [
            {
                "market": "TWSE",
                "current_data_core": {
                    "breadth": {
                        "provider": "twse_mis",
                        "source": "twse_mis_live_breadth",
                        "raw_result_id": "raw_fetch_result:21",
                        "as_of": NOW.isoformat(),
                    }
                },
            }
        ]
    }
    db, engine = _db()
    try:
        enriched = attach_current_market_lineage_to_stock_rows(
            [source_row],
            summary=summary,
        )
        persist_taiwan_intraday_stock_states(db, rows=enriched, now=NOW)
        row = db.query(TaiwanIntradayStockState).one()
        assert row.lineage_complete is True
        assert row.decision_usable is True
        assert json.loads(row.component_raw_result_ids_json or "[]") == [
            "raw_fetch_result:21"
        ]

        missing = {
            **source_row,
            "provider": "legacy_provider",
            "code": "2317",
        }
        persist_taiwan_intraday_stock_states(db, rows=[missing], now=NOW)
        legacy = (
            db.query(TaiwanIntradayStockState)
            .filter(TaiwanIntradayStockState.stock_id == "2317")
            .one()
        )
        assert legacy.lineage_complete is False
        assert legacy.decision_usable is False
        assert legacy.quality_status == "partial"
    finally:
        db.close()
        engine.dispose()
