from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    MarketDailyPriceReconciliation,
    MarketIndexDailyStat,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.jobs.schemas import TaiwanIndexDailyBootstrapJobRequest
from app.market.official_index_contract import TPEX_INDEX_SOURCE_NAME
from app.market.providers.tw_index_daily_bars import (
    TaiwanIndexDailyBarAcquisitionExecutor,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_aggregation import aggregate_daily_1d, observed_trade_coverage
from app.market.tw_bar_contracts import (
    TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
    TPEX_OFFICIAL_5S_PARSER_VERSION,
    TaiwanReconciliationStatus,
    TaiwanReleaseStatus,
)
from app.market.tw_bar_materialization_transaction import (
    TaiwanBarMaterializationTransaction,
)
from app.market.tw_bar_materializer import materialize_tpex_completed_daily_candidate
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_daily_reconciliation import TaiwanDailyReconciliationTransaction
from app.market.tw_index_daily_platform import (
    bootstrap_taiex_official_daily_history,
    bootstrap_tpex_completed_derived_daily_history,
    plan_tpex_completed_derived_daily_history,
    refresh_taiex_official_daily_bar,
    refresh_tpex_completed_derived_daily_bar,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    SourceLineage,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@dataclass(frozen=True)
class _Response:
    text: str
    status_code: int = 200
    headers: dict[str, str] | None = None
    url: str = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(self, "headers", {"content-type": "application/json"})


def _tpex_components(
    db: Session,
    *,
    trade_date: date,
) -> tuple[
    tuple[BarObservation, ...],
    BarObservation,
    tuple[int, ...],
    tuple[str, ...],
]:
    source = SourceRegistry(
        source_name=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
        source_type="api",
        category="market_data",
        enabled=True,
        priority=5,
        parser_type=TPEX_OFFICIAL_5S_PARSER_VERSION,
        auth_type="none",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    content_hash = "a" * 64
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime.combine(
            trade_date,
            time(6, 0),
            tzinfo=timezone.utc,
        ),
        content_hash=content_hash,
        parser_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
        raw_text="qualified-tpex-5s-payload",
    )
    db.add(raw)
    db.flush()
    instrument = resolve_taiwan_instrument(db, "TPEX")
    start = datetime.combine(trade_date, time(9), tzinfo=TAIWAN_TZ)
    components: list[BarObservation] = []
    for offset in range(0, 4 * 60 * 60 + 30 * 60, 5):
        component_start = start + timedelta(seconds=offset)
        value = Decimal("250.00") + Decimal(offset) / Decimal("100000")
        components.append(
            BarObservation(
                instrument=instrument,
                lineage=SourceLineage(
                    provider="tpex_index_5s",
                    source=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
                    authority=AuthorityClass.EXCHANGE,
                    raw_contract_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
                    event_at=component_start,
                    fetched_at=raw.fetched_at.replace(tzinfo=timezone.utc),
                    content_hash=content_hash,
                ),
                interval="5s",
                start_at=component_start,
                end_at=component_start + timedelta(seconds=5),
                open_price=value,
                high_price=value,
                low_price=value,
                close_price=value,
                volume=None,
                volume_status="not_applicable",
                price_basis="raw",
                finalization=BarFinalization.FINAL,
            )
        )
    formal_close_at = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
    formal_close = BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider="tpex_index_5s",
            source=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
            authority=AuthorityClass.EXCHANGE,
            raw_contract_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
            event_at=formal_close_at,
            fetched_at=raw.fetched_at.replace(tzinfo=timezone.utc),
            content_hash=content_hash,
        ),
        interval="closing_match",
        start_at=formal_close_at - timedelta(seconds=5),
        end_at=formal_close_at,
        open_price=Decimal("250.75"),
        high_price=Decimal("250.75"),
        low_price=Decimal("250.75"),
        close_price=Decimal("250.75"),
        volume=None,
        volume_status="not_applicable",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )
    db.commit()
    return tuple(components), formal_close, (raw.id,), (content_hash,)


def test_taiex_official_daily_acquisition_persists_and_reads_same_owner(
    db: Session,
) -> None:
    payload = json.dumps(
        {
            "stat": "OK",
            "data": [["115/09/01", "24100", "24300", "24000", "24250"]],
        },
        ensure_ascii=False,
    )
    acquisition = TaiwanIndexDailyBarAcquisitionExecutor(
        fetcher=lambda _route: _Response(text=payload),
        clock=lambda: datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
    )
    result = refresh_taiex_official_daily_bar(
        db,
        trade_date=date(2026, 9, 1),
        requested_at=datetime(2026, 9, 1, 23, 59, tzinfo=TAIWAN_TZ),
        acquisition=acquisition,
    )

    assert result.postcondition_satisfied is True
    read = TaiwanBarService(db).read_bars(
        instrument_id="TAIEX",
        interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 1, 23, 59, tzinfo=TAIWAN_TZ),
        requested_at=datetime(2026, 9, 1, 16, 5, tzinfo=TAIWAN_TZ),
    )
    assert [bar.close_price for bar in read.bars] == [Decimal("24250")]
    assert read.bar_states[0].authority is AuthorityClass.EXCHANGE
    assert read.bar_states[0].official is True
    assert read.bar_states[0].release_status is TaiwanReleaseStatus.RELEASED
    assert read.bar_states[0].persisted is True


def test_taiex_history_bootstrap_persists_month_receipt_idempotently(
    db: Session,
) -> None:
    payload = json.dumps(
        {
            "stat": "OK",
            "data": [
                ["115/08/31", "24000", "24200", "23900", "24100"],
                ["115/09/01", "24100", "24300", "24000", "24250"],
            ],
        },
        ensure_ascii=False,
    )
    def fetcher(_month: date) -> _Response:
        return _Response(text=payload)

    first = bootstrap_taiex_official_daily_history(
        db,
        date_from=date(2026, 8, 31),
        date_to=date(2026, 9, 1),
        max_sessions=2,
        requested_at=datetime(2026, 9, 1, 16, 0, tzinfo=TAIWAN_TZ),
        fetcher=fetcher,
    )
    second = bootstrap_taiex_official_daily_history(
        db,
        date_from=date(2026, 8, 31),
        date_to=date(2026, 9, 1),
        max_sessions=2,
        requested_at=datetime(2026, 9, 1, 16, 0, tzinfo=TAIWAN_TZ),
        fetcher=fetcher,
    )

    assert first["observed_sessions"] == 2
    assert first["bars_written"] == 2
    assert first["postcondition_satisfied"] is True
    assert first["qualified_bar_count"] == 2
    assert second["bars_written"] == 0
    assert second["bars_unchanged"] == 2


def test_tpex_completed_session_can_materialize_before_official_release(
    db: Session,
) -> None:
    trade_date = date(2026, 9, 1)
    rows: list[list[str]] = []
    event_at = datetime.combine(trade_date, time(9, 0, 5), tzinfo=TAIWAN_TZ)
    session_end = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
    while event_at <= session_end:
        rows.append([event_at.strftime("%H:%M:%S"), "410.60"])
        event_at += timedelta(seconds=5)
    rows.append(["99:99:99", "410.77"])
    payload = json.dumps(
        {
            "stat": "ok",
            "date": "2026/09/01",
            "tables": [{"fields": ["時間", "櫃買指數"], "data": rows}],
        },
        ensure_ascii=False,
    )
    result = refresh_tpex_completed_derived_daily_bar(
        db,
        trade_date=trade_date,
        requested_at=datetime(2026, 9, 1, 14, tzinfo=TAIWAN_TZ),
        fetcher=lambda _trade_date: _Response(
            text=payload,
            url="https://www.tpex.org.tw/www/zh-tw/indexInfo/miIndex",
        ),
    )
    assert result.receipts_written == 1
    assert result.observations_written == 1
    row = db.query(MarketDailyPrice).filter_by(stock_id="TPEX").one()
    assert Decimal(str(row.close_price)) == Decimal("410.77")
    assert db.query(RawFetchResult).count() == 1
    assert row.raw_result_id is None
    assert row.authority == "derived"
    assert row.official is False
    assert row.aggregation_version == "tw.tpex.daily.materialize.v2"


def test_tpex_history_plan_is_pure_bounded_and_supports_default_daily_window() -> None:
    sessions = plan_tpex_completed_derived_daily_history(
        date_from=date(2025, 6, 1),
        date_to=date(2026, 9, 1),
    )

    assert len(sessions) == 300
    assert sessions == tuple(sorted(sessions))
    assert all(item.weekday() < 5 for item in sessions)
    with pytest.raises(ValueError, match="between 1 and 300"):
        plan_tpex_completed_derived_daily_history(
            date_from=date(2025, 6, 1),
            date_to=date(2026, 9, 1),
            max_sessions=301,
        )


def test_tpex_history_bootstrap_rereads_qualified_formal_close_rows(
    db: Session,
) -> None:
    official_closes = {
        date(2026, 8, 31): "410.77",
        date(2026, 9, 1): "406.96",
    }
    official_source = SourceRegistry(
        source_name=TPEX_INDEX_SOURCE_NAME,
        source_type="api",
        category="market_data",
        enabled=True,
        priority=5,
        parser_type="tpex.official_index.v1",
        auth_type="none",
        reliability_level="official",
    )
    db.add(official_source)
    db.flush()
    official_raw = RawFetchResult(
        source_id=official_source.id,
        fetched_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        content_hash="c" * 64,
        parser_version="tpex.official_index.v1",
        raw_text="official-close-stat",
    )
    db.add(official_raw)
    db.flush()
    db.add(
        MarketIndexDailyStat(
            index_id="TPEX",
            market="TPEX",
            trade_date=date(2026, 9, 1),
            source_id=official_source.id,
            raw_result_id=official_raw.id,
            close_value=406.96,
            price_change=-3.81,
            source="tpex_openapi",
        )
    )
    db.commit()

    def fetcher(trade_date: date) -> _Response:
        rows: list[list[str]] = []
        event_at = datetime.combine(trade_date, time(9, 0, 5), tzinfo=TAIWAN_TZ)
        session_end = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
        while event_at <= session_end:
            rows.append([event_at.strftime("%H:%M:%S"), "400.00"])
            event_at += timedelta(seconds=5)
        rows.append(["99:99:99", official_closes[trade_date]])
        return _Response(
            text=json.dumps(
                {
                    "stat": "ok",
                    "date": trade_date.strftime("%Y/%m/%d"),
                    "tables": [{"fields": ["時間", "櫃買指數"], "data": rows}],
                },
                ensure_ascii=False,
            ),
            url="https://www.tpex.org.tw/www/zh-tw/indexInfo/miIndex",
        )

    result = bootstrap_tpex_completed_derived_daily_history(
        db,
        date_from=date(2026, 8, 31),
        date_to=date(2026, 9, 1),
        max_sessions=2,
        requested_at=datetime(2026, 9, 1, 16, tzinfo=TAIWAN_TZ),
        fetcher=fetcher,
        sleeper=lambda _seconds: None,
    )

    assert result["status"] == "success"
    assert result["postcondition_satisfied"] is True
    assert result["qualified_bar_count"] == 2
    read = TaiwanBarService(db).read_bars(
        instrument_id="TPEX",
        interval="1d",
        limit=2,
        include_partial=False,
        requested_at=datetime.now(TAIWAN_TZ),
    )
    assert [bar.close_price for bar in read.bars] == [
        Decimal("410.77"),
        Decimal("406.96"),
    ]
    assert all(state.technical_eligible for state in read.bar_states)
    assert read.bar_states[-1].reconciliation_status is TaiwanReconciliationStatus.MATCHED
    assert db.query(MarketDailyPriceReconciliation).count() == 1


def test_tpex_history_bootstrap_postcondition_rereads_the_requested_old_range(
    db: Session,
) -> None:
    trade_date = date(2025, 8, 8)

    def fetcher(requested_date: date) -> _Response:
        rows: list[list[str]] = []
        event_at = datetime.combine(requested_date, time(9, 0, 5), tzinfo=TAIWAN_TZ)
        session_end = datetime.combine(requested_date, time(13, 30), tzinfo=TAIWAN_TZ)
        while event_at <= session_end:
            rows.append([event_at.strftime("%H:%M:%S"), "300.00"])
            event_at += timedelta(seconds=5)
        rows.append(["99:99:99", "301.25"])
        return _Response(
            text=json.dumps(
                {
                    "stat": "ok",
                    "date": requested_date.strftime("%Y/%m/%d"),
                    "tables": [{"fields": ["時間", "櫃買指數"], "data": rows}],
                },
                ensure_ascii=False,
            ),
            url="https://www.tpex.org.tw/www/zh-tw/indexInfo/miIndex",
        )

    result = bootstrap_tpex_completed_derived_daily_history(
        db,
        date_from=trade_date,
        date_to=trade_date,
        max_sessions=1,
        requested_at=datetime(2026, 9, 2, 16, tzinfo=TAIWAN_TZ),
        fetcher=fetcher,
        sleeper=lambda _seconds: None,
    )

    assert result["status"] == "success"
    assert result["postcondition_satisfied"] is True
    assert result["qualified_bar_count"] == 1
    assert result["postcondition_latest_trade_date"] == trade_date


def test_tpex_completed_daily_retries_transient_http_failure(
    db: Session,
) -> None:
    trade_date = date(2026, 9, 1)
    rows: list[list[str]] = []
    event_at = datetime.combine(trade_date, time(9, 0, 5), tzinfo=TAIWAN_TZ)
    session_end = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
    while event_at <= session_end:
        rows.append([event_at.strftime("%H:%M:%S"), "250.25"])
        event_at += timedelta(seconds=5)
    rows.append(["99:99:99", "250.25"])
    payload = json.dumps(
        {
            "stat": "ok",
            "date": "2026/09/01",
            "tables": [{"fields": ["時間", "櫃買指數"], "data": rows}],
        },
        ensure_ascii=False,
    )
    responses = iter(
        [
            _Response(text="temporary", status_code=520),
            _Response(text=payload),
        ]
    )
    sleeps: list[float] = []

    result = refresh_tpex_completed_derived_daily_bar(
        db,
        trade_date=trade_date,
        requested_at=datetime(2026, 9, 1, 14, tzinfo=TAIWAN_TZ),
        fetcher=lambda _trade_date: next(responses),
        max_attempts=3,
        retry_backoff_seconds=0.5,
        sleeper=sleeps.append,
    )

    assert result.observations_written == 1
    assert sleeps == [0.5]


def test_tpex_derived_daily_is_persisted_without_fake_receipt_and_reconciled(
    db: Session,
) -> None:
    trade_date = date(2026, 9, 1)
    components, formal_close, raw_ids, hashes = _tpex_components(
        db, trade_date=trade_date
    )
    raw_count_before = db.query(RawFetchResult).count()
    candidate = materialize_tpex_completed_daily_candidate(
        components,
        formal_close_component=formal_close,
        component_raw_result_ids=raw_ids,
        component_content_hashes=hashes,
        coverage_complete=True,
        as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIWAN_TZ),
    )
    persisted = TaiwanBarMaterializationTransaction(db).persist_materialized_daily_bar(
        candidate
    )
    assert persisted.receipts_written == 0
    assert db.query(RawFetchResult).count() == raw_count_before

    before = TaiwanBarService(db).read_bars(
        instrument_id="TPEX",
        interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 1, 23, 59, tzinfo=TAIWAN_TZ),
        requested_at=datetime.now(TAIWAN_TZ),
    )
    assert before.bars, before.model_dump(mode="json")
    assert before.bars[0].finalization is BarFinalization.FINAL
    assert before.bar_states[0].authority is AuthorityClass.DERIVED
    assert before.bar_states[0].official is False
    assert before.bar_states[0].release_status is TaiwanReleaseStatus.PENDING_RELEASE
    assert before.bar_states[0].reconciliation_status is TaiwanReconciliationStatus.PENDING
    numeric_before = (
        before.bars[0].open_price,
        before.bars[0].high_price,
        before.bars[0].low_price,
        before.bars[0].close_price,
    )

    official_source = SourceRegistry(
        source_name=TPEX_INDEX_SOURCE_NAME,
        source_type="api",
        category="market_data",
        enabled=True,
        priority=5,
        parser_type="tpex.official_index.v1",
        auth_type="none",
        reliability_level="official",
    )
    db.add(official_source)
    db.flush()
    official_raw = RawFetchResult(
        source_id=official_source.id,
        fetched_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        content_hash="b" * 64,
        parser_version="tpex.official_index.v1",
        raw_text="official-close-stat",
    )
    db.add(official_raw)
    db.flush()
    db.add(
        MarketIndexDailyStat(
            index_id="TPEX",
            market="TPEX",
            trade_date=trade_date,
            source_id=official_source.id,
            raw_result_id=official_raw.id,
            close_value=float(numeric_before[-1]),
            price_change=1.0,
            source="tpex_openapi",
        )
    )
    db.commit()

    result = TaiwanDailyReconciliationTransaction(db).reconcile_tpex_daily_stat(
        trade_date=trade_date
    )
    assert result.status is TaiwanReconciliationStatus.MATCHED
    after = TaiwanBarService(db).read_bars(
        instrument_id="TPEX",
        interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 1, 23, 59, tzinfo=TAIWAN_TZ),
        requested_at=datetime.now(TAIWAN_TZ),
    )
    numeric_after = (
        after.bars[0].open_price,
        after.bars[0].high_price,
        after.bars[0].low_price,
        after.bars[0].close_price,
    )
    assert numeric_after == numeric_before
    assert after.identity.series_fingerprint == before.identity.series_fingerprint
    assert after.identity.lineage_digest == before.identity.lineage_digest
    assert after.identity.state_digest != before.identity.state_digest
    assert after.identity.series_revision != before.identity.series_revision
    assert after.bar_states[0].reconciliation_status is TaiwanReconciliationStatus.MATCHED
    assert db.query(MarketDailyPriceReconciliation).count() == 1


def test_tpex_daily_materialization_rejects_continuous_bar_as_formal_close(
    db: Session,
) -> None:
    components, _formal_close, raw_ids, hashes = _tpex_components(
        db, trade_date=date(2026, 9, 1)
    )

    with pytest.raises(ValueError, match="explicit exchange closing match"):
        materialize_tpex_completed_daily_candidate(
            components,
            formal_close_component=components[-1],
            component_raw_result_ids=raw_ids,
            component_content_hashes=hashes,
            coverage_complete=True,
            as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIWAN_TZ),
        )


def test_tpex_official_close_mismatch_never_patches_derived_ohlc(db: Session) -> None:
    trade_date = date(2026, 9, 1)
    components, formal_close, raw_ids, hashes = _tpex_components(
        db, trade_date=trade_date
    )
    candidate = materialize_tpex_completed_daily_candidate(
        components,
        formal_close_component=formal_close,
        component_raw_result_ids=raw_ids,
        component_content_hashes=hashes,
        coverage_complete=True,
        as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIWAN_TZ),
    )
    TaiwanBarMaterializationTransaction(db).persist_materialized_daily_bar(candidate)
    row = db.query(MarketDailyPrice).filter_by(stock_id="TPEX").one()
    numeric_before = (row.open_price, row.high_price, row.low_price, row.close_price)
    source = SourceRegistry(
        source_name=TPEX_INDEX_SOURCE_NAME,
        source_type="api",
        category="market_data",
        enabled=True,
        priority=5,
        parser_type="tpex.official_index.v1",
        auth_type="none",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 9, 1, 8, tzinfo=timezone.utc),
        content_hash="c" * 64,
        parser_version="tpex.official_index.v1",
        raw_text="mismatched-official-close",
    )
    db.add(raw)
    db.flush()
    db.add(
        MarketIndexDailyStat(
            index_id="TPEX",
            market="TPEX",
            trade_date=trade_date,
            source_id=source.id,
            raw_result_id=raw.id,
            close_value=float(Decimal(str(row.close_price)) + Decimal("1")),
            price_change=1.0,
            source="tpex_openapi",
        )
    )
    db.commit()

    result = TaiwanDailyReconciliationTransaction(db).reconcile_tpex_daily_stat(
        trade_date=trade_date
    )
    db.refresh(row)
    assert result.status is TaiwanReconciliationStatus.MISMATCHED
    assert (row.open_price, row.high_price, row.low_price, row.close_price) == numeric_before
    read = TaiwanBarService(db).read_bars(
        instrument_id="TPEX",
        interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 1, 23, 59, tzinfo=TAIWAN_TZ),
        requested_at=datetime.now(TAIWAN_TZ),
    )
    assert read.bar_states[0].technical_eligible is False
    assert read.bar_states[0].reconciliation_status is TaiwanReconciliationStatus.MISMATCHED


def test_weekly_and_monthly_are_derived_only_from_canonical_daily() -> None:
    key = InstrumentKey(
        market=Market.TW,
        symbol="TAIEX",
        instrument_type=InstrumentType.INDEX,
        venue="TWSE",
    )
    daily = tuple(
        BarObservation(
            instrument=key,
            lineage=SourceLineage(
                provider="twse_index_daily_ohlc",
                source="twse_indices_report_mi_5mins_hist",
                authority=AuthorityClass.EXCHANGE,
                raw_contract_version="fixture.v1",
                event_at=datetime.combine(day, time(13, 30), tzinfo=TAIWAN_TZ),
                content_hash=str(index) * 64,
            ),
            interval="1d",
            start_at=datetime.combine(day, time(9), tzinfo=TAIWAN_TZ),
            end_at=datetime.combine(day, time(13, 30), tzinfo=TAIWAN_TZ),
            open_price=Decimal(100 + index),
            high_price=Decimal(110 + index),
            low_price=Decimal(90 + index),
            close_price=Decimal(105 + index),
            volume=None,
            volume_status="not_applicable",
            price_basis="raw",
            finalization=BarFinalization.FINAL,
        )
        for index, day in enumerate(
            (date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2))
        )
    )
    weekly = aggregate_daily_1d(daily, target_interval="1w")
    monthly = aggregate_daily_1d(daily, target_interval="1mo")
    assert len(weekly) == 1
    assert weekly[0].open_price == Decimal("100")
    assert weekly[0].high_price == Decimal("112")
    assert weekly[0].low_price == Decimal("90")
    assert weekly[0].close_price == Decimal("107")
    assert [bar.start_at.month for bar in monthly] == [8, 9]
    assert all(bar.lineage.authority is AuthorityClass.DERIVED for bar in monthly)


def test_taiwan_index_bootstrap_contract_allows_bounded_300_sessions() -> None:
    request = TaiwanIndexDailyBootstrapJobRequest(
        date_from=date(2025, 9, 1),
        date_to=date(2026, 9, 1),
    )
    assert request.taiex_max_sessions == 300
    assert request.tpex_max_sessions == 300

    with pytest.raises(ValidationError):
        TaiwanIndexDailyBootstrapJobRequest(
            date_from=date(2025, 9, 1),
            date_to=date(2026, 9, 1),
            tpex_max_sessions=301,
        )


def test_continuous_minutes_without_formal_close_remain_provisional(
    db: Session,
) -> None:
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()
    instrument = resolve_taiwan_instrument(db, "2330")
    session_start = datetime(2026, 9, 1, 9, tzinfo=TAIWAN_TZ)
    minute_bars = tuple(
        BarObservation(
            instrument=instrument,
            lineage=SourceLineage(
                provider="fixture",
                source="fixture_1m",
                authority=AuthorityClass.VENDOR,
                raw_contract_version="fixture.1m.v1",
                event_at=session_start + timedelta(minutes=index),
                content_hash=f"{index:064x}",
            ),
            interval="1m",
            start_at=session_start + timedelta(minutes=index),
            end_at=session_start + timedelta(minutes=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100.5"),
            volume=None,
            volume_status="missing",
            price_basis="raw",
            finalization=BarFinalization.FINAL,
        )
        for index in range(270)
    )
    coverage = observed_trade_coverage(
        minute_bars,
        trading_policy_version="fixture.policy.v1",
    )
    service = TaiwanBarService(db)
    service.read_bars = lambda **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        bars=minute_bars,
        bucket_coverage=coverage,
        history=SimpleNamespace(requested_coverage_satisfied=True),
    )

    result = service._read_daily_bars(
        instrument_id="2330",
        requested_interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 2, tzinfo=TAIWAN_TZ),
        limit=10,
        include_partial=True,
        requested_at=datetime(2026, 9, 1, 14, tzinfo=TAIWAN_TZ),
    )

    assert result.bars[0].finalization is BarFinalization.PROVISIONAL
    assert result.bar_states[0].authority is AuthorityClass.DERIVED
    assert result.bar_states[0].official is False
    assert result.bar_states[0].release_status is TaiwanReleaseStatus.PENDING_RELEASE
    assert result.bar_states[0].reconciliation_status is TaiwanReconciliationStatus.PENDING
    assert result.bar_states[0].persisted is False
    assert result.bar_states[0].technical_eligible is False


def test_overlapping_current_minutes_fail_open_without_breaking_daily_read(
    db: Session,
) -> None:
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()
    instrument = resolve_taiwan_instrument(db, "2330")
    first_start = datetime(2026, 9, 1, 9, tzinfo=TAIWAN_TZ)

    def component(start_at: datetime, provider: str) -> BarObservation:
        return BarObservation(
            instrument=instrument,
            lineage=SourceLineage(
                provider=provider,
                source=f"{provider}.fixture",
                authority=AuthorityClass.VENDOR,
                raw_contract_version="fixture.1m.v1",
                event_at=start_at,
                content_hash=("a" if provider == "aligned" else "b") * 64,
            ),
            interval="1m",
            start_at=start_at,
            end_at=start_at + timedelta(minutes=1),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100.5"),
            volume=None,
            volume_status="missing",
            price_basis="raw",
            finalization=BarFinalization.FINAL,
        )

    minute_bars = (
        component(first_start, "aligned"),
        component(first_start + timedelta(seconds=10), "misaligned"),
    )
    coverage = observed_trade_coverage(
        minute_bars,
        trading_policy_version="fixture.policy.v1",
    )
    service = TaiwanBarService(db)
    service.read_bars = lambda **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        bars=minute_bars,
        bucket_coverage=coverage,
        history=SimpleNamespace(requested_coverage_satisfied=False),
    )

    result = service._read_daily_bars(
        instrument_id="2330",
        requested_interval="1d",
        from_time=datetime(2026, 9, 1, tzinfo=TAIWAN_TZ),
        to_time=datetime(2026, 9, 1, 10, tzinfo=TAIWAN_TZ),
        limit=10,
        include_partial=True,
        requested_at=datetime(2026, 9, 1, 10, tzinfo=TAIWAN_TZ),
    )

    assert result.bars == ()
    assert "TW_CURRENT_SESSION_DAILY_PROJECTION_INVALID" in result.limitations
    assert "TW_CURRENT_SESSION_DAILY_COMPONENTS_OVERLAP" in result.limitations
