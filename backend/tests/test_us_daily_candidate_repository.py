from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USDailyPrice
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor, USProviderPayload
from app.us_market.daily_price_repository import USDailyBarRepository
from app.us_market.daily_price_transaction import USDailyPriceTransaction
from app.us_market.price_store import upsert_us_daily_price_records
from app.us_market.sources import USDailyPriceRecord
from app.us_market.market_data.descriptors import (
    US_DAILY_PROVIDER_DESCRIPTORS,
    YAHOO_DAILY_RESOURCE_ID,
)
from app.market_data.provider_catalog import plan_data_acquisition_v2
from test_us_daily_ohlcv_acquisition import _requirement, _yahoo_payload, NOW


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_repository_reconstructs_provider_coherent_canonical_lineage() -> None:
    db = _session()
    try:
        requirement = _requirement()
        plan = plan_data_acquisition_v2(requirement, US_DAILY_PROVIDER_DESCRIPTORS)
        acquisition = USDailyOhlcvAcquisitionExecutor(
            fetchers={
                YAHOO_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                    payload=_yahoo_payload("TSM"),
                    url="https://query.example.invalid/chart/TSM",
                )
            },
            clock=lambda: NOW,
        ).acquire_bar_observations(requirement, plan)
        USDailyPriceTransaction(db).persist_bar_acquisition(requirement, acquisition)

        result = USDailyBarRepository(db).load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 21),
                max_rows=10,
            )
        )

        assert result.rows_examined == 1
        assert result.rows_accepted == 1
        assert result.rejections == ()
        assert len(result.series) == 1
        series = result.series[0]
        assert series.provider == "yahoo_chart"
        assert series.source == "yahoo.chart.1d"
        assert series.raw_result_ids[0] > 0
        assert series.bars[0].lineage.raw_receipt_id == f"raw_fetch_result:{series.raw_result_ids[0]}"
        assert series.bars[0].lineage.content_hash
    finally:
        db.close()


def test_legacy_row_without_lineage_is_rejected_not_guessed() -> None:
    db = _session()
    try:
        requirement = _requirement()
        db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="TSM",
                trade_date=date(2026, 8, 21),
                open_price=240,
                high_price=245,
                low_price=239,
                close_price=244,
                trade_volume=1000,
                raw_payload_hash="legacy",
                fetched_at=NOW,
            )
        )
        db.commit()
        result = USDailyBarRepository(db).load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 21),
                max_rows=10,
            )
        )

        assert result.rows_accepted == 0
        assert result.rejections[0].reason_code == "US_DAILY_LINEAGE_INCOMPLETE"
        assert "raw_result_id" in result.rejections[0].missing_fields
    finally:
        db.close()


def test_legacy_compat_synthetic_lineage_is_rejected_from_canonical_candidates() -> None:
    db = _session()
    try:
        requirement = _requirement()
        upsert_us_daily_price_records(
            db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="TSM",
                    trade_date=date(2026, 8, 21),
                    open_price=240,
                    high_price=245,
                    low_price=239,
                    close_price=244,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query.example.invalid/chart/TSM",
                    raw_payload_hash=None,
                )
            ],
        )
        result = USDailyBarRepository(db).load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 21),
                max_rows=10,
            )
        )

        assert result.rows_accepted == 0
        assert result.rejections[0].reason_code == (
            "US_DAILY_LEGACY_COMPAT_LINEAGE_REJECTED"
        )
    finally:
        db.close()


def test_repository_excludes_receipts_not_available_at_research_cutoff() -> None:
    db = _session()
    try:
        requirement = _requirement()
        plan = plan_data_acquisition_v2(requirement, US_DAILY_PROVIDER_DESCRIPTORS)
        acquisition = USDailyOhlcvAcquisitionExecutor(
            fetchers={
                YAHOO_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                    payload=_yahoo_payload("TSM"),
                    url="https://query.example.invalid/chart/TSM",
                )
            },
            clock=lambda: NOW,
        ).acquire_bar_observations(requirement, plan)
        USDailyPriceTransaction(db).persist_bar_acquisition(requirement, acquisition)

        before_receipt = USDailyBarRepository(db).load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 21),
                available_at=NOW - timedelta(seconds=1),
                max_rows=10,
            )
        )
        after_receipt = USDailyBarRepository(db).load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 21),
                available_at=NOW + timedelta(seconds=1),
                max_rows=10,
            )
        )

        assert before_receipt.rows_examined == 0
        assert after_receipt.rows_accepted == 1
    finally:
        db.close()
