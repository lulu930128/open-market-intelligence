from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    RawFetchReceiptV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.us_market.intraday_maintenance import (
    repair_us_index_intraday_volume_semantics,
    rollback_us_index_intraday_volume_repair,
)
from app.us_market.intraday_repository import USIntradayBarRepository
from app.us_market.intraday_transaction import USIntradayBarTransaction
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_RESOURCE_ID
from app.us_market.providers.canonical import canonical_yahoo_chart_payload


UTC = timezone.utc


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _instrument(
    symbol: str = "^GSPC",
    *,
    instrument_type: InstrumentType = InstrumentType.INDEX,
    venue: str = "SP_INDEX",
) -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol=symbol,
        instrument_type=instrument_type,
        venue=venue,
    )


def _requirement(
    *,
    instrument: InstrumentKey,
    start_at: datetime,
    requested_at: datetime,
) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=BarCapabilityRequest(
            capability_id="intraday.bars",
            interval="1m",
            start_at=start_at,
            end_at=start_at + timedelta(minutes=2),
            max_bars=2,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=180),
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=1,
            max_rows=100,
            max_candidates=8,
        ),
    )


def _yahoo_payload(symbol: str, start_at: datetime, volume: int) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol, "currency": "USD"},
                    "timestamp": [int(start_at.timestamp())],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [101.0],
                                "low": [99.0],
                                "close": [100.5],
                                "volume": [volume],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _persisted_row(
    db: Session,
    *,
    symbol: str,
    market: str,
    start_at: datetime,
    trade_volume: int | None,
    volume_status: str | None,
    with_lineage: bool = False,
) -> MarketIntradayBar:
    source = None
    raw = None
    if with_lineage:
        source = SourceRegistry(
            source_name="yahoo.chart.1m",
            source_type="fixture",
            category="market_data",
            enabled=True,
        )
        db.add(source)
        db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=start_at + timedelta(minutes=1),
            content_hash=hashlib.sha256(symbol.encode("utf-8")).hexdigest(),
            raw_text="fixture",
            parser_version="yahoo.chart.v8",
        )
        db.add(raw)
        db.flush()
    row = MarketIntradayBar(
        source_id=source.id if source is not None else None,
        provider="yahoo_chart",
        stock_id=symbol,
        market=market,
        symbol=symbol,
        interval="1m",
        bar_time=start_at,
        open_price=100.0,
        high_price=101.0,
        low_price=99.0,
        close_price=100.5,
        trade_volume=trade_volume,
        volume_status=volume_status,
        source="yahoo.chart.1m",
    )
    db.add(row)
    db.flush()
    if source is not None and raw is not None:
        db.add(
            MarketIntradayBarLineage(
                bar_id=row.id,
                source_id=source.id,
                raw_result_id=raw.id,
                provider="yahoo_chart",
                source="yahoo.chart.1m",
                authority="vendor",
                raw_contract_version="yahoo.chart.v8",
                event_at=start_at,
                received_at=start_at + timedelta(minutes=1),
                fetched_at=start_at + timedelta(minutes=1),
                finalization="final",
                source_interval="1m",
            )
        )
    db.commit()
    return row


def test_canonical_provider_module_imports_in_fresh_process() -> None:
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", "import app.us_market.providers.canonical"],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_yahoo_index_volume_is_not_applicable_without_changing_stock_volume() -> None:
    start_at = datetime(2026, 9, 1, 14, 30, tzinfo=UTC)
    fetched_at = start_at + timedelta(minutes=2)
    index = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=_yahoo_payload("^GSPC", start_at, 68_569_000),
        fetched_at=fetched_at,
        interval="1m",
        session_scope="all",
    )
    stock = canonical_yahoo_chart_payload(
        instrument=_instrument(
            "AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        payload=_yahoo_payload("AAPL", start_at, 12_345),
        fetched_at=fetched_at,
        interval="1m",
        session_scope="all",
    )

    assert index.bars[0].volume is None
    assert index.bars[0].volume_status == "not_applicable"
    assert "US_INDEX_VOLUME_NOT_APPLICABLE" in index.limitations
    assert stock.bars[0].volume == Quantity(
        value=Decimal("12345"),
        unit=QuantityUnit.SHARE,
    )
    assert stock.bars[0].volume_status == "observed"


def test_index_transaction_rejects_non_null_volume() -> None:
    db = _db()
    start_at = datetime(2026, 9, 1, 14, 30, tzinfo=UTC)
    fetched_at = start_at + timedelta(minutes=2)
    instrument = _instrument()
    raw_text = "index-volume-must-fail"
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    receipt = RawFetchReceiptV1(
        provider="yahoo_chart",
        source="yahoo.chart.1m",
        resource_id=YAHOO_INTRADAY_RESOURCE_ID,
        fetched_at=fetched_at,
        method="GET",
        content_hash=content_hash,
        raw_text=raw_text,
        parser_version="yahoo.chart.v8",
    )
    bar = BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider="yahoo_chart",
            source="yahoo.chart.1m",
            authority=AuthorityClass.VENDOR,
            raw_contract_version="yahoo.chart.v8",
            event_at=start_at,
            fetched_at=fetched_at,
            content_hash=content_hash,
        ),
        interval="1m",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100.5"),
        volume=Quantity(value=Decimal("1000"), unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )
    acquisition = BarAcquisitionResult(
        summary=AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=("yahoo_chart",),
            resource_attempts=(
                AcquisitionResourceAttempt(
                    provider="yahoo_chart",
                    resource_id=YAHOO_INTRADAY_RESOURCE_ID,
                ),
            ),
            external_calls=1,
        ),
        observations=(bar,),
        receipts=(receipt,),
    )

    with pytest.raises(ValueError, match="volume must be null"):
        USIntradayBarTransaction(db).persist_bar_acquisition(
            _requirement(
                instrument=instrument,
                start_at=start_at,
                requested_at=fetched_at,
            ),
            acquisition,
        )
    assert db.query(MarketIntradayBar).count() == 0


def test_repository_neutralizes_legacy_index_volume() -> None:
    db = _db()
    start_at = datetime(2026, 9, 1, 14, 30, tzinfo=UTC)
    _persisted_row(
        db,
        symbol="^GSPC",
        market="SP_INDEX",
        start_at=start_at,
        trade_volume=68_569_000,
        volume_status=None,
        with_lineage=True,
    )
    requirement = _requirement(
        instrument=_instrument(),
        start_at=start_at,
        requested_at=start_at + timedelta(minutes=2),
    )

    batch = USIntradayBarRepository(db).read_bar_candidates(requirement)

    assert len(batch.candidates) == 1
    bar = batch.candidates[0].bars[0]
    assert bar.volume is None
    assert bar.volume_status == "not_applicable"
    assert USIntradayBarRepository(db).read_volume_sessions(
        instrument=_instrument(),
        provider="yahoo_chart",
        source="yahoo.chart.1m",
        current_trade_date=start_at.date(),
        comparison_time=start_at.time(),
    ) == ()


def test_index_volume_repair_is_bounded_idempotent_and_reversible() -> None:
    db = _db()
    start_at = datetime(2026, 9, 1, 14, 30, tzinfo=UTC)
    bad_index = _persisted_row(
        db,
        symbol="^GSPC",
        market="SP_INDEX",
        start_at=start_at,
        trade_volume=68_569_000,
        volume_status=None,
    )
    good_index = _persisted_row(
        db,
        symbol="^VIX",
        market="CBOE_INDEX",
        start_at=start_at,
        trade_volume=None,
        volume_status="not_applicable",
    )
    stock = _persisted_row(
        db,
        symbol="AAPL",
        market="NASDAQ",
        start_at=start_at,
        trade_volume=12_345,
        volume_status="observed",
    )
    manifest = Path(__file__).with_name(".tmp-index-volume-repair.json")
    manifest.unlink(missing_ok=True)

    dry_run = repair_us_index_intraday_volume_semantics(db)
    assert dry_run["planned_row_count"] == 1
    assert dry_run["affected_symbols"] == ["^GSPC"]
    assert dry_run["writes_performed"] == 0

    try:
        applied = repair_us_index_intraday_volume_semantics(
            db,
            apply=True,
            audit_manifest_path=manifest,
        )
        db.refresh(bad_index)
        db.refresh(good_index)
        db.refresh(stock)
        assert applied["repaired_row_count"] == 1
        assert bad_index.trade_volume is None
        assert bad_index.volume_status == "not_applicable"
        assert good_index.volume_status == "not_applicable"
        assert stock.trade_volume == 12_345
        assert stock.volume_status == "observed"

        second = repair_us_index_intraday_volume_semantics(db)
        assert second["planned_row_count"] == 0
        assert second["writes_performed"] == 0

        rollback_ready = rollback_us_index_intraday_volume_repair(
            db,
            audit_manifest_path=manifest,
        )
        assert rollback_ready["status"] == "ready"
        rolled_back = rollback_us_index_intraday_volume_repair(
            db,
            audit_manifest_path=manifest,
            apply=True,
        )
        db.refresh(bad_index)
        assert rolled_back["restored_row_count"] == 1
        assert bad_index.trade_volume == 68_569_000
        assert bad_index.volume_status is None
    finally:
        manifest.unlink(missing_ok=True)
