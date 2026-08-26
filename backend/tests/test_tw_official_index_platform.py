from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DataQualityCheck,
    MarketIndexDailyStat,
    RawFetchResult,
    SourceRegistry,
)
from app.market.official_index_acquisition import (
    TaiwanOfficialIndexAcquisitionExecutor,
)
from app.market.official_index_platform import (
    TaiwanOfficialIndexCandidateReader,
    TaiwanOfficialIndexPlatform,
    build_taiwan_official_index_read_requirement,
    read_taiwan_official_index,
)
from app.market.official_index_repository import TaiwanOfficialIndexRepository
from app.market.official_index_transaction import TaiwanOfficialIndexTransaction
from app.market.providers.tw_official_index import (
    TPEX_INDEX_RESOURCE_ID,
    TWSE_INDEX_RESOURCE_ID,
    TW_INDEX_DATASET_ID,
    TW_OFFICIAL_INDEX_DESCRIPTORS,
    parse_tpex_official_index_payload,
    parse_twse_official_index_payload,
)
from app.market_data.contracts import (
    AuthorityClass,
    ConnectionStatus,
    DatasetHealthStatus,
    EvidenceFreshness,
    MarketSession,
    OperationalStatus,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import (
    DatasetTarget,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import plan_refresh_acquisition_v1
from app.market_data.resolution import ResolutionCandidate, resolve_market_index
from app.routers.tw_market_indices import (
    get_official_index_daily,
    refresh_official_index_daily,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tw_market_data"
REQUESTED_AT = datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int = 200
    url: str = "https://official.example.test/index"
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(self, "headers", {"content-type": "application/json"})


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _raw_payload(name: str) -> str:
    return json.dumps(
        _fixture(name)["payload"],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _refresh(*, index_id: str, trade_date: date) -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id=TW_INDEX_DATASET_ID,
        target=DatasetTarget(
            market="TW",
            dataset_id=TW_INDEX_DATASET_ID,
            scope_key=index_id,
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=REQUESTED_AT,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition="Official index row rereads with raw receipt lineage.",
    )


def _platform(
    db: Session,
    *,
    resource_id: str,
    response: FakeResponse | None = None,
    error: Exception | None = None,
) -> TaiwanOfficialIndexPlatform:
    def fetch(_route):
        if error is not None:
            raise error
        assert response is not None
        return response

    return TaiwanOfficialIndexPlatform(
        reader=TaiwanOfficialIndexCandidateReader(
            TaiwanOfficialIndexRepository(db)
        ),
        transaction=TaiwanOfficialIndexTransaction(db),
        acquisition=TaiwanOfficialIndexAcquisitionExecutor(
            fetchers={resource_id: fetch},
            clock=lambda: datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc),
            monotonic=lambda: 10.0,
        ),
    )


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


def test_actual_twse_and_tpex_payloads_preserve_official_index_semantics() -> None:
    twse_fixture = _fixture("twse_fmtqik_20260825.json")
    twse = parse_twse_official_index_payload(
        _raw_payload("twse_fmtqik_20260825.json")
    )
    assert twse_fixture["source_receipt"]["original_content_hash"] == (
        "76e193b9a34c1004d422cc70959d421c7f2926a3f44eb7b718250e01af2c2d72"
    )
    assert twse.input_row_count == 16
    assert twse.records[-1].index_id == "TAIEX"
    assert twse.records[-1].venue == "TWSE"
    assert twse.records[-1].trade_date == date(2026, 8, 24)
    assert str(twse.records[-1].close_value) == "44762.32"
    assert str(twse.records[-1].price_change) == "-461.97"
    assert twse.records[-1].trade_volume == 8_082_548_083
    assert twse.records[-1].trade_value == 656_280_679_689
    assert twse.records[-1].transaction_count == 3_876_321

    tpex_fixture = _fixture("tpex_daily_trading_index_20260825.json")
    tpex = parse_tpex_official_index_payload(
        _raw_payload("tpex_daily_trading_index_20260825.json")
    )
    assert tpex_fixture["source_receipt"]["original_content_hash"] == (
        "93ff27302b023fabd00c8cba4a46539f4c00d91c5e74357762fe9d6068aeffd8"
    )
    assert tpex.input_row_count == 17
    assert tpex.records[-1].index_id == "TPEX"
    assert tpex.records[-1].venue == "TPEX"
    assert tpex.records[-1].trade_date == date(2026, 8, 25)
    assert str(tpex.records[-1].close_value) == "389.41"
    assert str(tpex.records[-1].price_change) == "3.31"
    assert tpex.records[-1].trade_volume == 701_017_083
    assert tpex.records[-1].trade_value == 168_782_272_071
    assert tpex.records[-1].transaction_count == 809_034


@pytest.mark.parametrize(
    ("index_id", "trade_date", "resource_id", "fixture_name", "expected_close"),
    [
        (
            "TAIEX",
            date(2026, 8, 24),
            TWSE_INDEX_RESOURCE_ID,
            "twse_fmtqik_20260825.json",
            44_762.32,
        ),
        (
            "TPEX",
            date(2026, 8, 25),
            TPEX_INDEX_RESOURCE_ID,
            "tpex_daily_trading_index_20260825.json",
            389.41,
        ),
    ],
)
def test_actual_payload_refresh_persists_rereads_resolves_and_is_idempotent(
    db: Session,
    index_id: str,
    trade_date: date,
    resource_id: str,
    fixture_name: str,
    expected_close: float,
) -> None:
    platform = _platform(
        db,
        resource_id=resource_id,
        response=FakeResponse(
            text=_raw_payload(fixture_name),
            url=_fixture(fixture_name)["source_receipt"]["url"],
        ),
    )
    requirement = _refresh(index_id=index_id, trade_date=trade_date)

    first = platform.refresh_index(requirement)

    assert first.postcondition_satisfied is True
    assert first.acquisition.external_calls == 1
    assert first.persistence.committed is True
    assert first.persistence.receipts_written == 1
    assert first.persistence.observations_written == 1
    assert first.result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert first.result.dataset_health is not None
    assert first.result.dataset_health.status is DatasetHealthStatus.HEALTHY
    observation = first.result.resolved.market_index
    assert observation is not None
    assert observation.index_id == index_id
    assert float(observation.close_value) == expected_close
    assert observation.official is True
    assert observation.provisional is False
    assert observation.lineage.cache_hit is True
    assert observation.lineage.raw_receipt_id == (
        f"raw_fetch_result:{first.persistence.raw_result_ids[0]}"
    )
    assert observation.lineage.content_hash
    row = db.query(MarketIndexDailyStat).one()
    assert row.source_id is not None
    assert row.raw_result_id == first.persistence.raw_result_ids[0]
    assert db.query(SourceRegistry).count() == 1
    assert db.query(RawFetchResult).count() == 1
    assert db.query(DataQualityCheck).count() == 1

    second = platform.refresh_index(requirement)

    assert second.postcondition_satisfied is True
    assert second.persistence.observations_written == 0
    assert second.persistence.observations_unchanged == 1
    assert db.query(MarketIndexDailyStat).count() == 1
    assert db.query(RawFetchResult).count() == 2
    assert db.query(DataQualityCheck).count() == 2
    row = db.query(MarketIndexDailyStat).one()
    assert row.raw_result_id == second.persistence.raw_result_ids[0]


def test_legacy_index_row_without_raw_lineage_fails_closed(db: Session) -> None:
    db.add(
        MarketIndexDailyStat(
            index_id="TAIEX",
            market="TWSE",
            trade_date=date(2026, 8, 24),
            close_value=44_762.32,
            price_change=-461.97,
            source="legacy_string_only",
        )
    )
    db.commit()

    result = read_taiwan_official_index(
        db,
        index_id="TAIEX",
        trade_date=date(2026, 8, 24),
        requested_at=REQUESTED_AT,
    )

    assert result.resolved.market_index is None
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.MISSING
    assert result.limitations == ("INDEX_ROW_LINEAGE_MISSING",)


def test_http_failure_receipt_is_durable_but_never_becomes_index_evidence(
    db: Session,
) -> None:
    platform = _platform(
        db,
        resource_id=TPEX_INDEX_RESOURCE_ID,
        response=FakeResponse(
            text='{"error":"upstream"}',
            status_code=503,
        ),
    )

    result = platform.refresh_index(
        _refresh(index_id="TPEX", trade_date=date(2026, 8, 25))
    )

    assert result.postcondition_satisfied is False
    assert result.acquisition.status.value == "failed"
    assert result.persistence.committed is True
    assert result.persistence.receipts_written == 1
    assert result.persistence.observations_written == 0
    assert result.result.resolved.market_index is None
    assert result.result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert db.query(RawFetchResult).count() == 1
    assert db.query(MarketIndexDailyStat).count() == 0
    assert db.query(DataQualityCheck).one().status == "error"


def test_provider_connection_failure_is_truthful_and_performs_no_persistence(
    db: Session,
) -> None:
    platform = _platform(
        db,
        resource_id=TWSE_INDEX_RESOURCE_ID,
        error=TimeoutError("fixture timeout"),
    )

    result = platform.refresh_index(
        _refresh(index_id="TAIEX", trade_date=date(2026, 8, 24))
    )

    assert result.postcondition_satisfied is False
    assert result.acquisition.status.value == "failed"
    assert result.persistence.attempted is False
    assert result.result.resolved.market_index is None
    assert result.result.provider_health[0].connection is ConnectionStatus.DISCONNECTED
    assert result.result.provider_health[0].operational is OperationalStatus.FAILED
    assert db.query(RawFetchResult).count() == 0
    assert db.query(MarketIndexDailyStat).count() == 0


def test_resolver_prefers_official_index_when_vendor_has_lower_numeric_priority(
    db: Session,
) -> None:
    platform = _platform(
        db,
        resource_id=TPEX_INDEX_RESOURCE_ID,
        response=FakeResponse(
            text=_raw_payload("tpex_daily_trading_index_20260825.json")
        ),
    )
    refreshed = platform.refresh_index(
        _refresh(index_id="TPEX", trade_date=date(2026, 8, 25))
    )
    official = refreshed.result.resolved.market_index
    assert official is not None
    vendor = official.model_copy(
        update={
            "official": False,
            "lineage": official.lineage.model_copy(
                update={
                    "provider": "vendor_fixture",
                    "source": "Vendor fixture",
                    "authority": AuthorityClass.VENDOR,
                }
            ),
        }
    )

    resolved = resolve_market_index(
        (
            ResolutionCandidate(
                observation=vendor,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=1,
                session=MarketSession.CLOSED,
            ),
            ResolutionCandidate(
                observation=official,
                freshness=EvidenceFreshness.FRESH,
                provider_priority=100,
                session=MarketSession.CLOSED,
            ),
        ),
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=REQUESTED_AT,
        max_age=timedelta(days=31),
    )

    assert resolved.market_index is official
    assert resolved.health.selected_provider == official.lineage.provider


def test_official_index_descriptors_and_reads_are_scope_bounded() -> None:
    requirement = _refresh(index_id="TAIEX", trade_date=date(2026, 8, 24))
    plan = plan_refresh_acquisition_v1(
        requirement,
        TW_OFFICIAL_INDEX_DESCRIPTORS,
    )
    assert len(plan.routes) == 1
    assert plan.routes[0].resource_id == TWSE_INDEX_RESOURCE_ID
    assert plan.routes[0].max_external_calls == 1
    assert plan.routes[0].max_symbols == 1
    assert plan.routes[0].max_range_days == 1
    assert plan.skipped_resources[0].reason_code == (
        "DATASET_SCOPE_NOT_SUPPORTED_BY_RESOURCE"
    )

    read_requirement = build_taiwan_official_index_read_requirement(
        index_id="TAIEX",
        trade_date=date(2026, 8, 24),
        requested_at=REQUESTED_AT,
    )
    assert read_requirement.bounds.max_provider_attempts == 0
    assert read_requirement.bounds.max_external_calls == 0
    assert read_requirement.bounds.max_subscriptions == 0


def test_official_index_http_routes_do_not_expose_provider_selection() -> None:
    get_parameters = inspect.signature(get_official_index_daily).parameters
    refresh_parameters = inspect.signature(refresh_official_index_daily).parameters
    assert tuple(get_parameters) == ("index_id", "trade_date", "db")
    assert tuple(refresh_parameters) == ("index_id", "trade_date", "db")
    assert "provider" not in get_parameters
    assert "provider" not in refresh_parameters
