from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, TaiwanQuoteContractSnapshot
from app.jobs.taiwan_quote_contract_scheduler import (
    add_taiwan_quote_contract_snapshot_jobs,
)
from app.market.quote_contract_capture import (
    TAIWAN_QUOTE_CONTRACT_SLOTS,
    capture_taiwan_quote_contract_snapshot,
    get_taiwan_quote_contract_replay,
)
from app.market.quote_depth import resolve_taiwan_stock_quote_phase
from app.market.trading_calendar import TAIWAN_TZ


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()
    return db, engine


def _captured_payload() -> dict[str, object]:
    return {
        "stock_id": "2330",
        "provider": "twse_mis",
        "market": "TWSE",
        "source": "twse_mis_quote_depth",
        "quote_time": datetime(2026, 6, 30, 8, 50, tzinfo=TAIWAN_TZ),
        "snapshot_time": datetime(2026, 6, 30, 8, 50, 1, tzinfo=TAIWAN_TZ),
        "session_phase": "preopen_auction",
        "refresh_outcome": "inserted",
        "depth_available": True,
        "best_bid_price": 2410.0,
        "best_ask_price": 2415.0,
        "auction_indicative_available": True,
        "indicative_match_available": True,
        "indicative_match_price": 2412.5,
        "indicative_match_volume_lots": 2_046,
        "freshness": {
            "status": "live",
            "is_live": True,
            "is_stale": False,
        },
    }


def test_fixed_slot_capture_serializes_decimal_values() -> None:
    db, engine = _db()
    captured_at = datetime(2026, 6, 30, 8, 50, 1, tzinfo=TAIWAN_TZ)
    payload = _captured_payload()
    payload["best_bid_price"] = Decimal("2410.00")
    payload["indicative_match_price"] = Decimal("2412.50")
    try:
        with (
            patch(
                "app.market.quote_contract_capture.refresh_taiwan_realtime_snapshot"
            ),
            patch(
                "app.market.quote_contract_capture.get_taiwan_stock_quote_depth",
                return_value=payload,
            ),
        ):
            result = capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id="2330",
                capture_slot="08:50",
                now=captured_at,
            )

        assert result["capture_status"] == "captured"
        replay = get_taiwan_quote_contract_replay(
            db=db,
            stock_id="2330",
            trade_date=captured_at.date(),
        )
        quote = next(
            item["quote"]
            for item in replay["snapshots"]
            if item["capture_slot"] == "08:50"
        )
        assert quote["best_bid_price"] == 2410
        assert quote["indicative_match_price"] == 2412.5
    finally:
        db.close()
        engine.dispose()


def test_fixed_slot_capture_persists_serialization_failure() -> None:
    db, engine = _db()
    captured_at = datetime(2026, 6, 30, 8, 50, 1, tzinfo=TAIWAN_TZ)
    payload = _captured_payload()
    payload["unsupported"] = object()
    try:
        with (
            patch(
                "app.market.quote_contract_capture.refresh_taiwan_realtime_snapshot"
            ),
            patch(
                "app.market.quote_contract_capture.get_taiwan_stock_quote_depth",
                return_value=payload,
            ),
        ):
            result = capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id="2330",
                capture_slot="08:50",
                now=captured_at,
            )

        assert result["capture_status"] == "failed"
        assert "SNAPSHOT_SERIALIZATION_FAILED" in str(result["error"])
        row = db.query(TaiwanQuoteContractSnapshot).one()
        assert row.capture_status == "failed"
        assert row.payload_json is None
        assert "SNAPSHOT_SERIALIZATION_FAILED" in str(row.error)

        replay = get_taiwan_quote_contract_replay(
            db=db,
            stock_id="2330",
            trade_date=captured_at.date(),
        )
        failed = next(
            item
            for item in replay["snapshots"]
            if item["capture_slot"] == "08:50"
        )
        assert failed["status"] == "failed"
        assert "08:50" in replay["missing_slots"]
    finally:
        db.close()
        engine.dispose()


def test_session_phase_boundaries_follow_taiwan_stock_depth_rules() -> None:
    cases = {
        "2026-06-30T04:59:00+08:00": "post_close_snapshot",
        "2026-06-30T05:00:00+08:00": "closed_waiting_preopen",
        "2026-06-30T08:29:00+08:00": "closed_waiting_preopen",
        "2026-06-30T08:30:00+08:00": "preopen_auction",
        "2026-06-30T09:00:00+08:00": "regular_live",
        "2026-06-30T13:24:00+08:00": "regular_live",
        "2026-06-30T13:25:00+08:00": "closing_auction",
        "2026-06-30T13:30:00+08:00": "closing_auction",
        "2026-06-30T13:31:00+08:00": "close_resolution",
        "2026-06-30T13:32:59+08:00": "close_resolution",
        "2026-06-30T13:33:00+08:00": "post_close_snapshot",
        "2026-06-28T09:00:00+08:00": "market_closed",
    }
    for value, expected in cases.items():
        assert resolve_taiwan_stock_quote_phase(datetime.fromisoformat(value)) == expected


def test_fixed_slot_capture_is_idempotent_and_replay_is_read_only() -> None:
    db, engine = _db()
    first_now = datetime(2026, 6, 30, 8, 50, 1, tzinfo=TAIWAN_TZ)
    second_now = datetime(2026, 6, 30, 8, 55, 1, tzinfo=TAIWAN_TZ)
    try:
        with (
            patch(
                "app.market.quote_contract_capture.refresh_taiwan_realtime_snapshot"
            ),
            patch(
                "app.market.quote_contract_capture.get_taiwan_stock_quote_depth",
                side_effect=lambda **_kwargs: _captured_payload(),
            ),
        ):
            first = capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id="2330",
                capture_slot="08:50",
                now=first_now,
            )
            repeated = capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id="2330",
                capture_slot="08:50",
                now=first_now,
            )
            second = capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id="2330",
                capture_slot="08:55",
                now=second_now,
            )

        assert first["capture_status"] == "captured"
        assert repeated["capture_status"] == "captured"
        assert second["capture_status"] == "captured"
        assert db.query(TaiwanQuoteContractSnapshot).count() == 2

        with patch.object(
            db,
            "commit",
            side_effect=AssertionError("replay GET must not commit"),
        ):
            replay = get_taiwan_quote_contract_replay(
                db=db,
                stock_id="2330",
                trade_date=first_now.date(),
            )

        assert replay["captured_count"] == 2
        assert replay["complete"] is False
        assert "08:30" in replay["missing_slots"]
        projected = next(
            item["quote"]
            for item in replay["snapshots"]
            if item["capture_slot"] == "08:50"
        )
        assert projected["indicative_match_price"] == 2412.5
        assert projected["replay_projection"] == "captured_public_contract_preserved"
        assert replay["read_path_side_effects"] is False
    finally:
        db.close()
        engine.dispose()


def test_fixed_slot_scheduler_registers_every_acceptance_slot() -> None:
    class FakeScheduler:
        def __init__(self) -> None:
            self.jobs: list[dict] = []

        def add_job(self, function, **kwargs) -> None:
            self.jobs.append({"function": function, **kwargs})

    scheduler = FakeScheduler()
    enabled = add_taiwan_quote_contract_snapshot_jobs(scheduler)

    assert enabled is True
    assert len(scheduler.jobs) == len(TAIWAN_QUOTE_CONTRACT_SLOTS)
    assert [job["kwargs"]["capture_slot"] for job in scheduler.jobs] == list(
        TAIWAN_QUOTE_CONTRACT_SLOTS
    )
    assert all(job["max_instances"] == 1 for job in scheduler.jobs)
