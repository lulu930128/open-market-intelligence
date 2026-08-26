from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.official_breadth_platform import (
    TW_BREADTH_DATASET_ID,
    build_taiwan_official_breadth_requirement,
    read_taiwan_official_breadth,
)
from app.market.official_breadth_repository import TaiwanOfficialBreadthRepository
from app.market.providers.tw_official_daily import (
    TPEX_DAILY_RESOURCE_ID,
    TWSE_DAILY_RESOURCE_ID,
    TW_BREADTH_DATASET_ID as PROVIDER_BREADTH_DATASET_ID,
    TW_OFFICIAL_BREADTH_DESCRIPTORS,
    official_daily_record_to_bar,
    parse_tpex_official_daily_payload,
    parse_twse_official_daily_payload,
    parser_version_for_resource,
    source_name_for_resource,
)
from app.market_data.contracts import (
    DatasetHealthStatus,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketBreadthObservation,
    ObservationState,
    ResolvedEvidenceStatus,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    DatasetTarget,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose
from app.market_data.provider_catalog import plan_refresh_acquisition_v1
from app.routers.market import get_taiwan_official_market_breadth


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tw_market_data"
REQUESTED_AT = datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _raw_payload(name: str) -> str:
    return json.dumps(
        _fixture(name)["payload"],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _refresh_requirement(*, venue: str, trade_date: date) -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv.full_market",
        target=DatasetTarget(
            market=Market.TW,
            dataset_id="tw.daily.ohlcv.full_market",
            scope_key=venue,
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=REQUESTED_AT,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=2,
        max_range_days=1,
        postcondition="Official receipt and all accepted daily rows commit atomically.",
    )


def _persist_actual_excerpt(
    db: Session,
    *,
    venue: str,
    fixture_name: str,
    resource_id: str,
) -> tuple[date, tuple[str, ...], int]:
    raw_text = _raw_payload(fixture_name)
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    parser = (
        parse_twse_official_daily_payload
        if venue == "TWSE"
        else parse_tpex_official_daily_payload
    )
    parsed = parser(raw_text)
    assert parsed.records
    trade_dates = {record.trade_date for record in parsed.records}
    assert len(trade_dates) == 1
    trade_date = next(iter(trade_dates))
    provider = next(
        descriptor.provider_key
        for descriptor in TW_OFFICIAL_BREADTH_DESCRIPTORS
        if descriptor.dataset_scope_keys == (venue,)
    )
    source = source_name_for_resource(resource_id)
    parser_version = parser_version_for_resource(resource_id)
    receipt = RawFetchReceiptV1(
        provider=provider,
        source=source,
        resource_id=resource_id,
        fetched_at=datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc),
        method="GET",
        url=f"https://official.example.test/{resource_id}",
        status_code=200,
        content_type="application/json",
        content_hash=content_hash,
        raw_text=raw_text,
        parser_version=parser_version,
    )
    observations = tuple(
        official_daily_record_to_bar(
            record,
            instrument=InstrumentKey(
                market=Market.TW,
                symbol=record.symbol,
                instrument_type=InstrumentType.STOCK,
                venue=venue,
            ),
            provider=provider,
            source=source,
            parser_version=parser_version,
            fetched_at=receipt.fetched_at,
            content_hash=content_hash,
        )
        for record in parsed.records
    )
    persistence = TaiwanOfficialDailyTransaction(db).persist_bar_acquisition(
        _refresh_requirement(venue=venue, trade_date=trade_date),
        BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(provider,),
                resource_attempts=(
                    AcquisitionResourceAttempt(
                        provider=provider,
                        resource_id=resource_id,
                    ),
                ),
                external_calls=1,
                elapsed_ms=10,
            ),
            observations=observations,
            receipts=(receipt,),
        ),
    )
    db.add_all(
        [
            StockMaster(
                stock_id=record.symbol,
                stock_name=record.instrument_name,
                market=venue,
                instrument_type="stock",
                is_active=True,
            )
            for record in parsed.records
        ]
    )
    db.commit()
    return trade_date, tuple(record.symbol for record in parsed.records), persistence.raw_result_ids[0]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("venue", "fixture_name", "resource_id", "expected_counts"),
    [
        (
            "TWSE",
            "twse_stock_day_all_excerpt_20260825.json",
            TWSE_DAILY_RESOURCE_ID,
            (0, 2, 0),
        ),
        (
            "TPEX",
            "tpex_mainboard_quotes_excerpt_20260825.json",
            TPEX_DAILY_RESOURCE_ID,
            (0, 1, 1),
        ),
    ],
)
def test_actual_official_receipt_replays_through_storage_gateway_and_contract(
    db: Session,
    venue: str,
    fixture_name: str,
    resource_id: str,
    expected_counts: tuple[int, int, int],
) -> None:
    trade_date, symbols, raw_id = _persist_actual_excerpt(
        db,
        venue=venue,
        fixture_name=fixture_name,
        resource_id=resource_id,
    )

    result = read_taiwan_official_breadth(
        db,
        venue=venue,
        trade_date=trade_date,
        requested_at=REQUESTED_AT,
    )

    breadth = result.resolved.breadth
    assert result.result_kind == "market_breadth"
    assert result.acquisition.attempted is False
    assert result.acquisition.external_calls == 0
    assert result.persistence.attempted is False
    assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
    assert breadth is not None
    assert breadth.universe_count == len(symbols) == 2
    assert (
        breadth.advance_count,
        breadth.decline_count,
        breadth.unchanged_count,
    ) == expected_counts
    assert breadth.unknown_count == 0
    assert breadth.missing_count == 0
    assert breadth.official is True
    assert breadth.provisional is False
    assert breadth.lineage.cache_hit is True
    assert breadth.lineage.raw_receipt_id == f"raw_fetch_result:{raw_id}"
    assert breadth.lineage.content_hash
    assert breadth.trade_value is not None
    assert breadth.currency == "TWD"
    assert result.model_dump(mode="json")["resolved"]["breadth"]["venue"] == venue


def test_unknown_price_change_is_not_zero_and_remains_partial(db: Session) -> None:
    trade_date, symbols, _ = _persist_actual_excerpt(
        db,
        venue="TPEX",
        fixture_name="tpex_mainboard_quotes_excerpt_20260825.json",
        resource_id=TPEX_DAILY_RESOURCE_ID,
    )
    row = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == symbols[1])
        .one()
    )
    row.price_change = None
    db.commit()

    result = read_taiwan_official_breadth(
        db,
        venue="TPEX",
        trade_date=trade_date,
        requested_at=REQUESTED_AT,
    )

    breadth = result.resolved.breadth
    assert breadth is not None
    assert breadth.unchanged_count == 0
    assert breadth.unknown_count == 1
    assert breadth.missing_count == 0
    assert breadth.state is ObservationState.PARTIAL
    assert result.resolved.health.status is ResolvedEvidenceStatus.PARTIAL
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.PARTIAL
    assert "BREADTH_PRICE_CHANGE_UNKNOWN" in result.limitations


def test_universe_member_without_daily_row_is_missing_not_unknown(db: Session) -> None:
    trade_date, _, _ = _persist_actual_excerpt(
        db,
        venue="TWSE",
        fixture_name="twse_stock_day_all_excerpt_20260825.json",
        resource_id=TWSE_DAILY_RESOURCE_ID,
    )
    db.add(
        StockMaster(
            stock_id="9999",
            stock_name="Fixture missing member",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()

    result = read_taiwan_official_breadth(
        db,
        venue="TWSE",
        trade_date=trade_date,
        requested_at=REQUESTED_AT,
    )

    breadth = result.resolved.breadth
    assert breadth is not None
    assert breadth.universe_count == 3
    assert breadth.unknown_count == 0
    assert breadth.missing_count == 1
    assert breadth.state is ObservationState.PARTIAL
    assert "BREADTH_UNIVERSE_ROWS_MISSING" in result.limitations


def test_mixed_raw_receipts_fail_closed_instead_of_publishing_false_aggregate(
    db: Session,
) -> None:
    trade_date, symbols, _ = _persist_actual_excerpt(
        db,
        venue="TWSE",
        fixture_name="twse_stock_day_all_excerpt_20260825.json",
        resource_id=TWSE_DAILY_RESOURCE_ID,
    )
    source = db.query(SourceRegistry).one()
    extra_raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 25, 10, 31, tzinfo=timezone.utc),
        method="GET",
        status_code=200,
        content_hash="f" * 64,
        raw_text="[]",
        parser_version="test.mixed.v1",
    )
    db.add(extra_raw)
    db.flush()
    row = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == symbols[1])
        .one()
    )
    row.raw_result_id = extra_raw.id
    db.commit()

    result = read_taiwan_official_breadth(
        db,
        venue="TWSE",
        trade_date=trade_date,
        requested_at=REQUESTED_AT,
    )

    assert result.resolved.breadth is None
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.MISSING
    assert result.limitations == (
        "BREADTH_COMPONENT_LINEAGE_NOT_COHERENT",
        "READ_POLICY_FORBIDS_ACQUISITION",
    )


def test_breadth_contract_rejects_bad_partition_and_completed_provisional(
    db: Session,
) -> None:
    trade_date, _, _ = _persist_actual_excerpt(
        db,
        venue="TPEX",
        fixture_name="tpex_mainboard_quotes_excerpt_20260825.json",
        resource_id=TPEX_DAILY_RESOURCE_ID,
    )
    observation = TaiwanOfficialBreadthRepository(db).load_market_breadth(
        venue="TPEX",
        trade_date=trade_date,
        max_rows=5000,
    ).observation
    assert observation is not None
    payload = observation.model_dump()
    payload["universe_count"] += 1
    with pytest.raises(ValidationError, match="must equal universe_count"):
        MarketBreadthObservation.model_validate(payload)

    payload = observation.model_dump()
    payload["provisional"] = True
    with pytest.raises(ValidationError, match="cannot be provisional"):
        MarketBreadthObservation.model_validate(payload)


def test_breadth_refresh_descriptors_are_dataset_and_venue_scoped() -> None:
    assert PROVIDER_BREADTH_DATASET_ID == TW_BREADTH_DATASET_ID
    requirement = RefreshRequirementV1(
        dataset_id=TW_BREADTH_DATASET_ID,
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_BREADTH_DATASET_ID,
            scope_key="TWSE",
        ),
        from_date=date(2026, 8, 24),
        to_date=date(2026, 8, 24),
        requested_at=REQUESTED_AT,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=2,
        max_external_calls=2,
        timeout_seconds=60,
        max_symbols=2,
        max_range_days=1,
        postcondition="Both venue breadth projections reread from coherent receipts.",
    )

    plan = plan_refresh_acquisition_v1(
        requirement,
        TW_OFFICIAL_BREADTH_DESCRIPTORS,
    )

    assert len(plan.routes) == 1
    assert plan.routes[0].resource_id == TWSE_DAILY_RESOURCE_ID
    assert plan.routes[0].max_external_calls == 1
    assert plan.routes[0].max_range_days == 1
    assert len(plan.skipped_resources) == 1
    assert plan.skipped_resources[0].reason_code == "DATASET_SCOPE_NOT_SUPPORTED_BY_RESOURCE"


def test_breadth_read_requirement_and_http_route_are_provider_neutral() -> None:
    requirement = build_taiwan_official_breadth_requirement(
        venue="TWSE",
        trade_date=date(2026, 8, 24),
        requested_at=REQUESTED_AT,
    )
    assert requirement.target.dataset_id == TW_BREADTH_DATASET_ID
    assert requirement.bounds.max_provider_attempts == 0
    assert requirement.bounds.max_external_calls == 0
    assert requirement.bounds.max_subscriptions == 0

    parameters = inspect.signature(get_taiwan_official_market_breadth).parameters
    assert tuple(parameters) == ("venue", "trade_date", "db")
    assert "provider" not in parameters
