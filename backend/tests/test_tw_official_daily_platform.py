from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DataQualityCheck,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import (
    TaiwanOfficialDailyPlatform,
    build_taiwan_daily_cache_requirement,
    read_taiwan_latest_daily_evidence,
    read_taiwan_official_daily,
    refresh_taiwan_official_daily,
    refresh_taiwan_official_daily_venue,
)
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.portfolio_valuation import read_taiwan_valuation_price
from app.market.service import list_stock_ohlc_chart_data
from app.market.schemas import MarketOhlcChartRead
from app.routers.market import refresh_stock_official_daily_price
from app.market.providers.tw_official_daily import (
    TPEX_DAILY_RESOURCE_ID,
    TWSE_DAILY_RESOURCE_ID,
    TWSE_RWD_DAILY_RESOURCE_ID,
    TW_OFFICIAL_DAILY_DESCRIPTORS,
    parse_tpex_official_daily_payload,
    parse_twse_rwd_official_daily_payload,
    parse_twse_official_daily_payload,
)
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import (
    DatasetTarget,
    InstrumentTarget,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose
from app.market_data.registry import DATASET_REGISTRY
from app.sources.defaults import (
    TWSE_DAILY_TRADING_SOURCE_NAME,
    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tw_market_data"


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int = 200
    headers: dict[str, str] | None = None
    url: str = "https://official.example.test/daily"

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


def _refresh(
    *,
    symbol: str,
    venue: str,
    trade_date: date,
) -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol=symbol,
                instrument_type=InstrumentType.STOCK,
                venue=venue,
            )
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition="Persisted official daily bar reaches the requested trade date.",
    )


def _platform(
    db: Session,
    *,
    resource_id: str,
    response: FakeResponse,
) -> TaiwanOfficialDailyPlatform:
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={resource_id: lambda _route: response},
        clock=lambda: datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc),
        monotonic=lambda: 10.0,
    )
    return TaiwanOfficialDailyPlatform(
        reader=TaiwanCompletedDailyCandidateReader(
            TaiwanOfficialDailyBarRepository(db)
        ),
        transaction=TaiwanOfficialDailyTransaction(db),
        acquisition=executor,
        descriptors=tuple(
            descriptor
            for descriptor in TW_OFFICIAL_DAILY_DESCRIPTORS
            if descriptor.resource_id == resource_id
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


def test_recorded_twse_excerpt_parses_without_losing_market_fields() -> None:
    fixture = _fixture("twse_stock_day_all_excerpt_20260825.json")
    parsed = parse_twse_official_daily_payload(
        _raw_payload("twse_stock_day_all_excerpt_20260825.json"),
        target_symbols=frozenset({"2330"}),
    )

    assert fixture["source_receipt"]["original_row_count"] == 1378
    assert parsed.input_row_count == 2
    assert parsed.matched_row_count == 1
    assert parsed.issues == ()
    record = parsed.records[0]
    assert record.trade_date == date(2026, 8, 24)
    assert record.symbol == "2330"
    assert str(record.close_price) == "2375.00"
    assert record.trade_volume == 13_073_210
    assert record.trade_value == 31_234_578_255
    assert record.transaction_count == 84_694
    assert str(record.price_change) == "-35.0000"


def test_recorded_twse_rwd_same_day_excerpt_parses_official_3711_ohlcv() -> None:
    fixture_name = "twse_mi_index_allbut0999_excerpt_20260827.json"
    fixture = _fixture(fixture_name)
    parsed = parse_twse_rwd_official_daily_payload(
        _raw_payload(fixture_name),
        target_symbols=frozenset({"3711"}),
    )

    assert fixture["source_receipt"]["original_row_count"] == 1377
    assert parsed.input_row_count == 1
    assert parsed.matched_row_count == 1
    assert parsed.issues == ()
    record = parsed.records[0]
    assert record.trade_date == date(2026, 8, 27)
    assert record.symbol == "3711"
    assert record.instrument_name == "日月光投控"
    assert record.open_price == 608
    assert record.high_price == 608
    assert record.low_price == 593
    assert record.close_price == 605
    assert record.trade_volume == 11_658_860
    assert record.trade_value == 7_011_817_192
    assert record.transaction_count == 18_048
    assert record.price_change == 13


def test_twse_rwd_venue_refresh_uses_existing_transaction_and_resolver(
    db: Session,
) -> None:
    db.add(
        StockMaster(
            stock_id="3711",
            stock_name="日月光投控",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={
            TWSE_RWD_DAILY_RESOURCE_ID: lambda _route: FakeResponse(
                text=_raw_payload(
                    "twse_mi_index_allbut0999_excerpt_20260827.json"
                )
            )
        },
        clock=lambda: datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        monotonic=lambda: 10.0,
    )

    result = refresh_taiwan_official_daily_venue(
        db,
        venue="TWSE",
        trade_date=date(2026, 8, 27),
        requested_at=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        acquisition=executor,
    )

    assert result["fetch_status"] == "success"
    assert result["parse_status"] == "success"
    assert result["source_name"] == TWSE_RWD_DAILY_TRADING_SOURCE_NAME
    assert result["parsed_count"] == 1
    assert result["replaced_trade_dates"] == [date(2026, 8, 27)]
    assert result["resource_attempts"] == [
        {"provider": "twse_rwd", "resource_id": TWSE_RWD_DAILY_RESOURCE_ID}
    ]
    row = db.query(MarketDailyPrice).one()
    assert row.stock_id == "3711"
    assert row.trade_date == date(2026, 8, 27)
    assert row.close_price == 605
    assert row.trade_volume == 11_658_860
    assert row.trade_value == 7_011_817_192
    assert row.transaction_count == 18_048
    outward = read_taiwan_official_daily(
        db,
        stock_id="3711",
        from_date=date(2026, 8, 27),
        to_date=date(2026, 8, 27),
        requested_at=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
    )
    assert outward.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert outward.resolved.bars[-1].lineage.provider == "twse_rwd"
    assert outward.resolved.bars[-1].close_price == 605
    assert outward.resolved.bars[-1].volume is not None
    assert outward.resolved.bars[-1].volume.value == 11_658_860


def test_twse_rwd_venue_refresh_accepts_runtime_scale_universe(
    db: Session,
) -> None:
    db.add_all(
        [
            StockMaster(
                stock_id="3711",
                stock_name="日月光投控",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            ),
            *(
                StockMaster(
                    stock_id=f"X{index:04d}",
                    stock_name=f"測試股票 {index}",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
                for index in range(1_085)
            ),
        ]
    )
    db.commit()
    route_symbol_bounds: list[int] = []

    def fetch(route):
        route_symbol_bounds.append(route.max_symbols)
        return FakeResponse(
            text=_raw_payload("twse_mi_index_allbut0999_excerpt_20260827.json")
        )

    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_RWD_DAILY_RESOURCE_ID: fetch},
        clock=lambda: datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        monotonic=lambda: 10.0,
    )

    result = refresh_taiwan_official_daily_venue(
        db,
        venue="TWSE",
        trade_date=date(2026, 8, 27),
        requested_at=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        acquisition=executor,
    )

    assert route_symbol_bounds == [1_086]
    assert result["fetch_status"] == "success"
    assert result["parsed_count"] == 1
    assert db.query(MarketDailyPrice).one().stock_id == "3711"


def test_cache_requirement_rejects_unbounded_calendar_range() -> None:
    with pytest.raises(ValueError, match="36,600 days"):
        build_taiwan_daily_cache_requirement(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="2330",
                instrument_type=InstrumentType.STOCK,
                venue="TWSE",
            ),
            from_date=date(1900, 1, 1),
            to_date=date(2026, 8, 25),
            requested_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
            max_rows=250,
        )


def test_cache_read_defaults_to_latest_released_trading_day(db: Session) -> None:
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()

    result = read_taiwan_official_daily(
        db,
        stock_id="2330",
        requested_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
    )

    assert result.requirement.request.end_at.date() == date(2026, 8, 24)
    assert result.requirement.bounds.max_external_calls == 0


def test_cache_read_without_dates_uses_exact_latest_candidate_window(
    db: Session,
) -> None:
    source = SourceRegistry(
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        source_type="api",
        category="market_data",
        priority=10,
        parser_type="twse_daily_trading",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 25, 1, 0, tzinfo=timezone.utc),
        content_hash="latest-window",
        parser_version="twse.stock_day_all.v1",
        raw_text="[]",
    )
    db.add(raw)
    db.flush()
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.add_all(
        [
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="2330",
                trade_date=trade_date,
                open_price=100.0,
                high_price=110.0,
                low_price=95.0,
                close_price=close_price,
                trade_volume=1_000_000,
            )
            for trade_date, close_price in (
                (date(2026, 8, 20), 101.0),
                (date(2026, 8, 21), 102.0),
                (date(2026, 8, 24), 103.0),
            )
        ]
    )
    db.commit()

    result = read_taiwan_official_daily(
        db,
        stock_id="2330",
        limit=2,
        requested_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
    )

    assert result.requirement.request.start_at.date() == date(2026, 8, 21)
    assert [bar.end_at.date() for bar in result.resolved.bars] == [
        date(2026, 8, 21),
        date(2026, 8, 24),
    ]
    latest = read_taiwan_latest_daily_evidence(
        db,
        "2330",
        requested_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
    )
    assert latest.daily is not None
    assert latest.daily.trade_date == date(2026, 8, 24)
    assert latest.daily.close_price == 103
    assert latest.daily.provider == "twse_openapi"
    assert latest.daily.raw_result_id == f"raw_fetch_result:{raw.id}"
    assert latest.dataset_health is not None
    valuation = read_taiwan_valuation_price(
        db,
        symbol="2330",
        requested_at=datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
    )
    assert valuation.price == 103
    assert valuation.currency == "TWD"
    assert valuation.provider == "twse_openapi"
    assert valuation.source_kind == "resolved_completed_daily_close"
    assert valuation.facts_usable is True


def test_future_of_release_row_requires_post_release_receipt(
    db: Session,
) -> None:
    source = SourceRegistry(
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        source_type="api",
        category="market_data",
        priority=10,
        parser_type="twse_daily_trading",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    previous_receipt = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc),
        content_hash="previous-released",
        parser_version="twse.stock_day_all.v1",
        raw_text="[]",
    )
    premature_receipt = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 28, 6, 1, tzinfo=timezone.utc),
        content_hash="today-premature",
        parser_version="twse.stock_day_all.v1",
        raw_text="[]",
    )
    db.add_all([previous_receipt, premature_receipt])
    db.flush()
    db.add(
        StockMaster(
            stock_id="3711",
            stock_name="ASE Technology",
            market="TWSE",
            instrument_type="stock",
        )
    )
    previous_row = MarketDailyPrice(
        source_id=source.id,
        raw_result_id=previous_receipt.id,
        stock_id="3711",
        trade_date=date(2026, 8, 27),
        open_price=600,
        high_price=610,
        low_price=590,
        close_price=605,
        trade_volume=11_000_000,
    )
    premature_row = MarketDailyPrice(
        source_id=source.id,
        raw_result_id=premature_receipt.id,
        stock_id="3711",
        trade_date=date(2026, 8, 28),
        open_price=608,
        high_price=630,
        low_price=606,
        close_price=621,
        trade_volume=17_504_000,
    )
    db.add_all([previous_row, premature_row])
    db.commit()

    before_release = read_taiwan_official_daily(
        db,
        stock_id="3711",
        to_date=date(2026, 8, 28),
        limit=20,
        requested_at=datetime(2026, 8, 28, 6, 18, tzinfo=timezone.utc),
    )
    assert before_release.requirement.request.end_at.date() == date(2026, 8, 27)
    assert [bar.end_at.date() for bar in before_release.resolved.bars] == [
        date(2026, 8, 27)
    ]
    assert (
        "REQUESTED_TO_DATE_EXCEEDS_LATEST_RELEASED_DAILY_DATE"
        in before_release.limitations
    )

    after_clock_only = read_taiwan_official_daily(
        db,
        stock_id="3711",
        to_date=date(2026, 8, 28),
        limit=20,
        requested_at=datetime(2026, 8, 28, 7, 20, tzinfo=timezone.utc),
    )
    assert [bar.end_at.date() for bar in after_clock_only.resolved.bars] == [
        date(2026, 8, 27)
    ]
    assert any(
        item.reason_code == "DAILY_RECEIPT_PREDATES_RELEASE"
        for item in after_clock_only.candidate_rejections
    )

    post_release_receipt = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 28, 7, 18, tzinfo=timezone.utc),
        content_hash="today-released",
        parser_version="twse.stock_day_all.v1",
        raw_text="[]",
    )
    db.add(post_release_receipt)
    db.flush()
    premature_row.raw_result_id = post_release_receipt.id
    db.commit()

    after_refresh = read_taiwan_official_daily(
        db,
        stock_id="3711",
        to_date=date(2026, 8, 28),
        limit=20,
        requested_at=datetime(2026, 8, 28, 7, 20, tzinfo=timezone.utc),
    )
    assert [bar.end_at.date() for bar in after_refresh.resolved.bars] == [
        date(2026, 8, 27),
        date(2026, 8, 28),
    ]

    chart = list_stock_ohlc_chart_data(
        db,
        stock_id="3711",
        timeframe="daily",
        bars=20,
        to_date=date(2026, 8, 31),
    )
    assert (
        "REQUESTED_TO_DATE_EXCEEDS_LATEST_RELEASED_DAILY_DATE"
        in chart["warnings"]
    )
    assert chart["trade_value_unit"] == "TWD"
    assert chart["currency"] == "TWD"


def test_recorded_tpex_excerpt_parses_legacy_table_shape() -> None:
    fixture = _fixture("tpex_mainboard_quotes_excerpt_20260825.json")
    parsed = parse_tpex_official_daily_payload(
        _raw_payload("tpex_mainboard_quotes_excerpt_20260825.json"),
        target_symbols=frozenset({"6488"}),
    )

    assert fixture["source_receipt"]["original_row_count"] == 10495
    assert parsed.input_row_count == 2
    assert parsed.matched_row_count == 1
    assert parsed.issues == ()
    record = parsed.records[0]
    assert record.trade_date == date(2026, 8, 25)
    assert record.symbol == "6488"
    assert str(record.close_price) == "980.00"
    assert record.trade_volume == 9_687_718
    assert record.trade_value == 9_403_896_234
    assert record.transaction_count == 26_254
    assert str(record.price_change) == "-30.00"


@pytest.mark.parametrize(
    ("resource_id", "fixture_name", "symbol", "venue", "trade_date", "close"),
    [
        (
            TWSE_DAILY_RESOURCE_ID,
            "twse_stock_day_all_excerpt_20260825.json",
            "2330",
            "TWSE",
            date(2026, 8, 24),
            2375.0,
        ),
        (
            TPEX_DAILY_RESOURCE_ID,
            "tpex_mainboard_quotes_excerpt_20260825.json",
            "6488",
            "TPEX",
            date(2026, 8, 25),
            980.0,
        ),
    ],
)
def test_actual_excerpt_refresh_persists_rereads_resolves_and_is_idempotent(
    db: Session,
    resource_id: str,
    fixture_name: str,
    symbol: str,
    venue: str,
    trade_date: date,
    close: float,
) -> None:
    response = FakeResponse(text=_raw_payload(fixture_name))
    platform = _platform(db, resource_id=resource_id, response=response)
    requirement = _refresh(symbol=symbol, venue=venue, trade_date=trade_date)

    first = platform.refresh_instrument(requirement)

    assert first.postcondition_satisfied is True
    assert first.acquisition.providers_attempted
    assert len(first.acquisition.resource_attempts) == 1
    assert first.persistence.committed is True
    assert first.persistence.receipts_written == 1
    assert first.persistence.observations_written == 1
    assert first.result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert first.result.resolved.bars[0].lineage.cache_hit is True
    assert float(first.result.resolved.bars[0].close_price) == close
    assert db.query(SourceRegistry).count() == 1
    assert db.query(RawFetchResult).count() == 1
    assert db.query(MarketDailyPrice).count() == 1
    assert db.query(DataQualityCheck).count() == 1
    first_raw = db.query(RawFetchResult).one()
    assert first_raw.id == first.persistence.raw_result_ids[0]
    assert first_raw.content_hash == first.result.resolved.bars[0].lineage.content_hash
    assert (
        first.result.resolved.bars[0].lineage.raw_receipt_id
        == f"raw_fetch_result:{first_raw.id}"
    )

    second = platform.refresh_instrument(requirement)

    assert second.postcondition_satisfied is True
    assert second.persistence.observations_written == 0
    assert second.persistence.observations_unchanged == 1
    assert db.query(RawFetchResult).count() == 2
    assert db.query(MarketDailyPrice).count() == 1
    assert db.query(DataQualityCheck).count() == 2
    row = db.query(MarketDailyPrice).one()
    assert row.raw_result_id == second.persistence.raw_result_ids[0]
    assert row.trade_value is not None
    assert row.transaction_count is not None

    db.add(
        StockMaster(
            stock_id=symbol,
            stock_name=row.stock_name,
            market=venue,
            instrument_type="stock",
        )
    )
    db.commit()
    chart = list_stock_ohlc_chart_data(
        db,
        stock_id=symbol,
        timeframe="daily",
        bars=1,
        ensure_history=False,
        include_intraday=False,
        to_date=trade_date,
    )
    assert chart["point_count"] == 1
    assert chart["requested_bar_count"] == 1
    assert chart["available_bar_count"] == 1
    assert chart["returned_point_count"] == 1
    assert chart["bars_legacy_count"] == 1
    assert chart["deprecated_fields"] == ["bars"]
    assert chart["points"][0]["time"] == trade_date
    assert chart["points"][0]["close"] == close
    assert chart["points"][0]["trade_value"] == row.trade_value
    assert chart["points"][0]["transaction_count"] == row.transaction_count
    assert chart["volume_unit"] == "shares"
    assert chart["volume_semantics"] == "finalized_traded_shares"
    assert chart["latest_finalized_data_date"] == trade_date
    assert chart["data_quality"] == "ok"
    outward = MarketOhlcChartRead.model_validate(chart).model_dump(mode="json")
    assert outward["stock_id"] == symbol
    assert outward["requested_bar_count"] == 1
    assert outward["available_bar_count"] == 1
    assert outward["returned_point_count"] == 1
    assert outward["bars_legacy_count"] == 1
    assert outward["deprecated_fields"] == ["bars"]
    assert outward["points"][0]["close"] == close
    assert outward["volume_unit"] == "shares"
    assert outward["latest_finalized_data_date"] == trade_date.isoformat()
    assert outward["data_quality"] == "ok"


def test_malformed_payload_persists_raw_failure_without_fake_bar(
    db: Session,
) -> None:
    response = FakeResponse(text="{not-json")
    platform = _platform(db, resource_id=TWSE_DAILY_RESOURCE_ID, response=response)

    result = platform.refresh_instrument(
        _refresh(
            symbol="2330",
            venue="TWSE",
            trade_date=date(2026, 8, 24),
        )
    )

    assert result.postcondition_satisfied is False
    assert result.acquisition.status.value == "failed"
    assert "PAYLOAD_PARSE_FAILED" in result.limitations
    assert result.result.resolved.bars == ()
    assert db.query(RawFetchResult).count() == 1
    assert db.query(MarketDailyPrice).count() == 0
    quality = db.query(DataQualityCheck).one()
    assert quality.status == "error"


def test_http_failure_receipt_is_durable_and_does_not_become_observation(
    db: Session,
) -> None:
    response = FakeResponse(text='{"stat":"520"}', status_code=520)
    platform = _platform(db, resource_id=TPEX_DAILY_RESOURCE_ID, response=response)

    result = platform.refresh_instrument(
        _refresh(
            symbol="6488",
            venue="TPEX",
            trade_date=date(2026, 8, 25),
        )
    )

    assert result.postcondition_satisfied is False
    assert "HTTP_520" in result.limitations
    assert db.query(RawFetchResult).one().status_code == 520
    assert db.query(MarketDailyPrice).count() == 0


def test_empty_success_payload_is_missing_not_a_fake_zero_bar(db: Session) -> None:
    platform = _platform(
        db,
        resource_id=TWSE_DAILY_RESOURCE_ID,
        response=FakeResponse(text="[]"),
    )

    result = platform.refresh_instrument(
        _refresh(
            symbol="2330",
            venue="TWSE",
            trade_date=date(2026, 8, 24),
        )
    )

    assert result.postcondition_satisfied is False
    assert result.acquisition.status.value == "failed"
    assert "TARGET_SYMBOL_NOT_FOUND" in result.limitations
    assert result.result.resolved.bars == ()
    assert db.query(RawFetchResult).count() == 1
    assert db.query(MarketDailyPrice).count() == 0
    assert db.query(DataQualityCheck).one().status == "warning"


def test_partially_invalid_target_rows_remain_explicit(db: Session) -> None:
    fixture = _fixture("twse_stock_day_all_excerpt_20260825.json")
    valid_row = fixture["payload"][1]
    invalid_row = dict(valid_row, ClosingPrice="")
    platform = _platform(
        db,
        resource_id=TWSE_DAILY_RESOURCE_ID,
        response=FakeResponse(
            text=json.dumps([valid_row, invalid_row], ensure_ascii=False)
        ),
    )

    result = platform.refresh_instrument(
        _refresh(
            symbol="2330",
            venue="TWSE",
            trade_date=date(2026, 8, 24),
        )
    )

    assert result.postcondition_satisfied is True
    assert result.acquisition.status.value == "partial"
    assert "REQUIRED_OHLC_MISSING" in result.limitations
    assert db.query(MarketDailyPrice).count() == 1
    assert db.query(DataQualityCheck).one().status == "warning"


def test_duplicate_symbol_date_is_explicit_and_not_double_persisted() -> None:
    fixture = _fixture("twse_stock_day_all_excerpt_20260825.json")
    duplicate_payload = [fixture["payload"][1], fixture["payload"][1]]
    parsed = parse_twse_official_daily_payload(
        json.dumps(duplicate_payload, ensure_ascii=False),
        target_symbols=frozenset({"2330"}),
    )

    assert len(parsed.records) == 1
    assert parsed.issues[0].reason_code == "DUPLICATE_SYMBOL_DATE"
    assert parsed.issues[0].count == 1


def test_transaction_failure_rolls_back_receipt_source_and_bar(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = _platform(
        db,
        resource_id=TWSE_DAILY_RESOURCE_ID,
        response=FakeResponse(
            text=_raw_payload("twse_stock_day_all_excerpt_20260825.json")
        ),
    )
    original_commit = db.commit

    def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        platform.refresh_instrument(
            _refresh(
                symbol="2330",
                venue="TWSE",
                trade_date=date(2026, 8, 24),
            )
        )
    monkeypatch.setattr(db, "commit", original_commit)

    assert db.query(SourceRegistry).count() == 0
    assert db.query(RawFetchResult).count() == 0
    assert db.query(MarketDailyPrice).count() == 0
    assert db.query(DataQualityCheck).count() == 0


def test_refresh_dataset_scope_cannot_cross_venue() -> None:
    requirement = RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv",
        target=DatasetTarget(
            market=Market.TW,
            dataset_id="tw.daily.ohlcv",
            scope_key="TWSE",
        ),
        from_date=date(2026, 8, 24),
        to_date=date(2026, 8, 24),
        requested_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition="Venue-scoped refresh remains bounded.",
    )
    from app.market.providers.tw_official_daily import TW_OFFICIAL_DAILY_DESCRIPTORS
    from app.market_data.provider_catalog import plan_refresh_acquisition_v1

    plan = plan_refresh_acquisition_v1(requirement, TW_OFFICIAL_DAILY_DESCRIPTORS)

    assert len(plan.routes) == 1
    assert plan.routes[0].resource_id == TWSE_RWD_DAILY_RESOURCE_ID
    assert any(
        item.reason_code == "DATASET_SCOPE_NOT_SUPPORTED_BY_RESOURCE"
        for item in plan.skipped_resources
    )


def test_production_refresh_entrypoint_is_provider_neutral_and_registry_owned(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_name = "twse_mi_index_allbut0999_excerpt_20260827.json"
    calls: list[str] = []

    def fetch(route) -> FakeResponse:
        calls.append(route.resource_id)
        return FakeResponse(text=_raw_payload(fixture_name))

    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_RWD_DAILY_RESOURCE_ID: fetch},
        clock=lambda: datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        monotonic=lambda: 10.0,
    )
    db.add(
        StockMaster(
            stock_id="3711",
            stock_name="日月光投控",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.market.daily_ohlcv_platform.expected_daily_price_date",
        lambda **_kwargs: date(2026, 8, 27),
    )

    result = refresh_taiwan_official_daily(
        db,
        stock_id="3711",
        trade_date=date(2026, 8, 27),
        requested_at=datetime(2026, 8, 27, 15, 35, tzinfo=timezone.utc),
        acquisition=executor,
    )

    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID]
    assert result.postcondition_satisfied is True
    assert result.plan.routes[0].provider_key == "twse_rwd"
    spec = DATASET_REGISTRY.get("tw.daily.ohlcv")
    assert spec.owner == "app.market.daily_ohlcv_platform"
    assert spec.read_operation == "MarketDataGateway.resolve_bars"
    assert "raw_fetch_result" in str(spec.storage_reference)


def test_production_refresh_rejects_non_expected_date_before_provider_call(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fetch(_route) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(
            text=_raw_payload("twse_stock_day_all_excerpt_20260825.json")
        )

    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.market.daily_ohlcv_platform.expected_daily_price_date",
        lambda **_kwargs: date(2026, 8, 24),
    )
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_DAILY_RESOURCE_ID: fetch}
    )

    with pytest.raises(ValueError, match="latest expected completed"):
        refresh_taiwan_official_daily(
            db,
            stock_id="2330",
            trade_date=date(2026, 8, 23),
            requested_at=datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc),
            acquisition=executor,
        )

    assert calls == 0
    assert db.query(RawFetchResult).count() == 0


def test_official_refresh_http_entrypoint_does_not_expose_provider_selection() -> None:
    parameters = inspect.signature(
        refresh_stock_official_daily_price
    ).parameters

    assert tuple(parameters) == ("stock_id", "trade_date", "db")
    assert "provider" not in parameters
