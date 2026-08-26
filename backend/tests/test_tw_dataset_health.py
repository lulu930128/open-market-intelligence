from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    RawFetchResult,
    SourceRegistry,
    TaiwanStockQuoteSnapshot,
)
from app.market.tw_dataset_catalog import TW_DATASET_CATALOG
from app.market.tw_dataset_health import (
    TW_DATASET_STORAGE_PROBES,
    TaiwanDatasetStorageStatus,
    read_taiwan_dataset_health,
)
from app.routers import tw_data_core


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source_and_receipt(db: Session) -> tuple[SourceRegistry, RawFetchResult]:
    source = SourceRegistry(
        source_name="twse_mis_public_quote",
        source_type="api",
        category="market_data",
        endpoint_url="https://example.invalid/quote",
        enabled=True,
        priority=10,
        parser_type="test.v1",
        auth_type="none",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    receipt = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 25, 5, 30, tzinfo=timezone.utc),
        url=source.endpoint_url,
        method="GET",
        status_code=200,
        content_type="application/json",
        content_hash="a" * 64,
        raw_text="{}",
        parser_version="test.v1",
    )
    db.add(receipt)
    db.flush()
    return source, receipt


def test_every_dataset_has_one_bounded_storage_probe() -> None:
    assert set(TW_DATASET_STORAGE_PROBES) == {
        dataset.dataset_id for dataset in TW_DATASET_CATALOG.all()
    }
    for dataset in TW_DATASET_CATALOG.all():
        probe = TW_DATASET_STORAGE_PROBES[dataset.dataset_id]
        assert probe.table_name in dataset.storage_tables


def test_empty_storage_is_truthful_missing_without_freshness_claim(db: Session) -> None:
    result = read_taiwan_dataset_health(db, "tw.chips.institutional.daily")

    assert result.contract_scope == "storage_lineage_only"
    assert result.lifecycle_health is None
    assert "FRESHNESS_REQUIRES_DATASET_POLICY" in result.limitations
    assert result.storage_evidence.status is TaiwanDatasetStorageStatus.MISSING
    assert result.storage_evidence.has_observation is False
    assert result.storage_evidence.freshness_status == "not_evaluated"
    assert "NO_PERSISTED_OBSERVATION" in result.storage_evidence.detail_codes


def test_canonical_latest_row_requires_source_and_raw_receipt(db: Session) -> None:
    source, receipt = _source_and_receipt(db)
    observed_at = datetime(2026, 8, 25, 5, 30, tzinfo=timezone.utc)
    db.add(
        TaiwanStockQuoteSnapshot(
            source_id=source.id,
            raw_result_id=receipt.id,
            provider="twse_mis",
            market="TWSE",
            stock_id="2330",
            session_phase="post_close",
            quote_time=observed_at,
            source=source.source_name,
            source_url=source.endpoint_url,
            fetched_at=observed_at,
        )
    )
    db.commit()

    result = read_taiwan_dataset_health(
        db,
        "tw.quote.snapshot",
        scope_value="2330",
        checked_at=datetime(2026, 8, 25, 6, tzinfo=timezone.utc),
    )

    evidence = result.storage_evidence
    assert evidence.status is TaiwanDatasetStorageStatus.OBSERVED
    assert evidence.lineage_observed is True
    assert evidence.latest_observed_value == "2026-08-25T05:30:00"


def test_intraday_health_defers_component_lineage_to_dataset_projection(
    db: Session,
) -> None:
    observed_at = datetime(2026, 8, 25, 1, 5, tzinfo=timezone.utc)
    db.add(
        MarketIntradayBar(
            provider="yahoo_finance",
            stock_id="2330",
            market="TWSE",
            symbol="2330.TW",
            interval="5m",
            bar_time=observed_at,
            source="Yahoo Finance",
        )
    )
    db.commit()

    result = read_taiwan_dataset_health(
        db,
        "tw.intraday.bars",
        scope_value="2330",
    )

    evidence = result.storage_evidence
    assert evidence.has_observation is True
    assert evidence.status is TaiwanDatasetStorageStatus.OBSERVED
    assert evidence.lineage_observed is None
    assert (
        "DERIVED_COMPONENT_LINEAGE_REQUIRES_DATASET_PROJECTION"
        in evidence.detail_codes
    )


def test_data_core_router_is_provider_neutral_and_unknown_dataset_is_404(
    db: Session,
) -> None:
    datasets = tw_data_core.list_taiwan_data_core_datasets()
    operations = tw_data_core.list_taiwan_data_core_operations()
    assert len(datasets) == 32
    assert len(operations) == 22
    assert all("provider" not in item.dataset_id for item in datasets)

    with pytest.raises(HTTPException) as raised:
        tw_data_core.get_taiwan_data_core_dataset_health(
            "tw.unknown",
            target=None,
            db=db,
        )
    assert raised.value.status_code == 404


def test_platform_evidence_endpoint_is_the_non_deprecated_storage_contract(
    db: Session,
) -> None:
    result = tw_data_core.get_taiwan_data_core_dataset_platform_evidence(
        "tw.chips.institutional.daily",
        target=None,
        db=db,
    )

    assert result.contract_scope == "storage_lineage_only"
    assert result.lifecycle_health is None
    assert result.storage_evidence.freshness_status == "not_evaluated"
