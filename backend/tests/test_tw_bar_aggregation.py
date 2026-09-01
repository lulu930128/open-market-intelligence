from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.market.tw_bar_aggregation import (
    TAIWAN_BAR_AGGREGATION_VERSION,
    aggregate_completed_session_to_1d,
    aggregate_intraday_1m,
    continuous_session_coverage,
)
from app.market.tw_bar_contracts import TaiwanDerivedBucketCoverageStatus
from app.market.tw_instrument_trading_policy import (
    resolve_taiwan_instrument_trading_policy,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)


TAIPEI = timezone(timedelta(hours=8))
INSTRUMENT = InstrumentKey(
    market=Market.TW,
    symbol="2330",
    instrument_type=InstrumentType.STOCK,
    venue="TWSE",
)


def _bar(minute: int, *, trade_date: date = date(2026, 9, 1)) -> BarObservation:
    start = datetime.combine(trade_date, datetime.min.time(), TAIPEI).replace(
        hour=9
    ) + timedelta(minutes=minute)
    price = Decimal("100") + Decimal(minute)
    return BarObservation(
        instrument=INSTRUMENT,
        lineage=SourceLineage(
            provider="kgi_superpy",
            source="kgi_superpy_minute_kbars",
            authority=AuthorityClass.BROKER,
            raw_contract_version="kgi.superpy.minute_kbars.v1",
            event_at=start + timedelta(minutes=1),
            received_at=start + timedelta(minutes=1, seconds=1),
            fetched_at=start + timedelta(minutes=1, seconds=1),
            content_hash=f"hash-{trade_date}-{minute}",
        ),
        interval="1m",
        start_at=start,
        end_at=start + timedelta(minutes=1),
        open_price=price,
        high_price=price + Decimal("1"),
        low_price=price - Decimal("1"),
        close_price=price + Decimal("0.5"),
        volume=Quantity(value=Decimal(10 + minute), unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="provider_default",
        turnover_value=Decimal(1000 + minute),
        turnover_currency="TWD",
        trade_count=minute + 1,
        finalization=BarFinalization.FINAL,
    )


def _coverage(bars: tuple[BarObservation, ...], trade_date: date = date(2026, 9, 1)):
    return continuous_session_coverage(
        bars,
        trade_date=trade_date,
        trading_policy_version="tw.trading_policy.continuous.v1",
    )


def test_five_minute_aggregation_uses_first_max_min_last_and_sums() -> None:
    bars = tuple(_bar(minute) for minute in range(5))

    aggregated, coverage = aggregate_intraday_1m(
        bars,
        target_interval="5m",
        bucket_coverage=_coverage(bars),
        as_of=datetime(2026, 9, 1, 10, 0, tzinfo=TAIPEI),
    )

    first = aggregated[0]
    assert first.open_price == Decimal("100")
    assert first.high_price == Decimal("105")
    assert first.low_price == Decimal("99")
    assert first.close_price == Decimal("104.5")
    assert first.volume is not None
    assert first.volume.value == Decimal("60")
    assert first.turnover_value == Decimal("5010")
    assert first.trade_count == 15
    assert first.finalization is BarFinalization.FINAL
    assert coverage[0].status is TaiwanDerivedBucketCoverageStatus.COMPLETE
    assert first.lineage.raw_contract_version == TAIWAN_BAR_AGGREGATION_VERSION


def test_base_gap_is_partial_and_does_not_fill_or_publish_partial_volume_sum() -> None:
    bars = tuple(_bar(minute) for minute in (0, 1, 3, 4))

    aggregated, coverage = aggregate_intraday_1m(
        bars,
        target_interval="5m",
        bucket_coverage=_coverage(bars),
        as_of=datetime(2026, 9, 1, 10, 0, tzinfo=TAIPEI),
    )

    first = aggregated[0]
    assert first.open_price == Decimal("100")
    assert first.close_price == Decimal("104.5")
    assert first.volume is None
    assert first.volume_status == "missing"
    assert first.turnover_value is None
    assert first.trade_count is None
    assert first.finalization is BarFinalization.FINAL
    assert coverage[0].status is TaiwanDerivedBucketCoverageStatus.PARTIAL
    assert coverage[0].missing_evidence_count == 1


def test_active_bucket_is_provisional_even_when_observed_prefix_is_complete() -> None:
    bars = tuple(_bar(minute) for minute in range(3))

    aggregated, _ = aggregate_intraday_1m(
        bars,
        target_interval="5m",
        bucket_coverage=_coverage(bars),
        as_of=datetime(2026, 9, 1, 9, 3, tzinfo=TAIPEI),
    )

    assert aggregated[0].finalization is BarFinalization.PROVISIONAL


def test_one_hour_tail_is_session_truncated_and_does_not_cross_date() -> None:
    first_date = date(2026, 9, 1)
    next_date = date(2026, 9, 2)
    first_bars = tuple(_bar(minute) for minute in range(240, 265))
    next_bars = tuple(_bar(minute, trade_date=next_date) for minute in range(5))
    coverage = _coverage(first_bars, first_date) + _coverage(next_bars, next_date)

    aggregated, derived_coverage = aggregate_intraday_1m(
        first_bars + next_bars,
        target_interval="1h",
        bucket_coverage=coverage,
        as_of=datetime(2026, 9, 2, 14, 0, tzinfo=TAIPEI),
    )

    first_tail = next(
        item
        for item in aggregated
        if item.start_at.date() == first_date and item.start_at.hour == 13
    )
    first_tail_coverage = next(
        item
        for item in derived_coverage
        if item.bucket_start == first_tail.start_at
    )
    assert first_tail.end_at.time().isoformat() == "13:30:00"
    assert first_tail_coverage.session_truncated is True
    assert first_tail_coverage.status is TaiwanDerivedBucketCoverageStatus.COMPLETE
    assert all(item.start_at.date() == item.end_at.date() for item in aggregated)


def test_coverage_excludes_future_buckets_and_rejects_closing_auction_bar() -> None:
    closing_auction_bar = _bar(267)
    coverage = continuous_session_coverage(
        (_bar(0), closing_auction_bar),
        trade_date=date(2026, 9, 1),
        trading_policy_version="tw.instrument_trading_policy.v2",
        as_of=datetime(2026, 9, 1, 9, 3, 25, tzinfo=TAIPEI),
    )
    assert [item.bucket_start.minute for item in coverage] == [0, 1, 2]

    post_close = continuous_session_coverage(
        (closing_auction_bar,),
        trade_date=date(2026, 9, 1),
        trading_policy_version="tw.instrument_trading_policy.v2",
        as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
    )
    auction = next(item for item in post_close if item.bucket_start.hour == 13 and item.bucket_start.minute == 27)
    assert auction.status.value == "not_applicable"
    assert auction.source_observation_count == 0


def test_all_not_applicable_volume_stays_not_applicable_after_aggregation() -> None:
    bars = tuple(
        _bar(minute).model_copy(
            update={"volume": None, "volume_status": "not_applicable"}
        )
        for minute in range(5)
    )
    aggregated, _ = aggregate_intraday_1m(
        bars,
        target_interval="5m",
        bucket_coverage=_coverage(bars),
        as_of=datetime(2026, 9, 1, 10, 0, tzinfo=TAIPEI),
    )
    assert aggregated[0].volume is None
    assert aggregated[0].volume_status == "not_applicable"


def test_coverage_uses_batch_auction_policy_and_unknown_fails_closed() -> None:
    batch_policy = resolve_taiwan_instrument_trading_policy(
        {"cache_status": "current", "is_active": True}
    )
    batch = continuous_session_coverage(
        (_bar(0),),
        trade_date=date(2026, 9, 1),
        trading_policy_version="tw.instrument_trading_policy.v2",
        trading_policy=batch_policy,
        as_of=datetime(2026, 9, 1, 9, 3, 25, tzinfo=TAIPEI),
    )
    assert batch[0].status.value == "observed_trade"
    assert [item.status.value for item in batch[1:]] == [
        "not_applicable",
        "not_applicable",
    ]

    unknown_policy = resolve_taiwan_instrument_trading_policy(
        {"cache_status": "missing", "is_active": False}
    )
    unknown = continuous_session_coverage(
        (_bar(0),),
        trade_date=date(2026, 9, 1),
        trading_policy_version="tw.instrument_trading_policy.v2",
        trading_policy=unknown_policy,
        as_of=datetime(2026, 9, 1, 9, 3, 25, tzinfo=TAIPEI),
    )
    assert [item.status.value for item in unknown] == [
        "observed_trade",
        "missing_evidence",
        "missing_evidence",
    ]


def test_daily_finalization_requires_qualified_formal_close_component() -> None:
    components = tuple(_bar(minute) for minute in range(265))
    without_close = aggregate_completed_session_to_1d(
        components,
        output_provider="fixture",
        output_source="fixture.daily",
        source_interval="1m",
        coverage_complete=True,
        as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
    )
    formal_close = _bar(264).model_copy(
        update={
            "interval": "5s",
            "start_at": datetime(2026, 9, 1, 13, 29, 55, tzinfo=TAIPEI),
            "end_at": datetime(2026, 9, 1, 13, 30, tzinfo=TAIPEI),
            "high_price": Decimal("999"),
            "close_price": Decimal("999"),
        }
    )
    with_close = aggregate_completed_session_to_1d(
        components,
        output_provider="fixture",
        output_source="fixture.daily",
        source_interval="1m",
        coverage_complete=True,
        as_of=datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
        formal_close_component=formal_close,
    )
    assert without_close.finalization is BarFinalization.PROVISIONAL
    assert with_close.finalization is BarFinalization.FINAL
    assert with_close.close_price == Decimal("999")
