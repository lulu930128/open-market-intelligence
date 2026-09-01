from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.market.tw_bar_aggregation import observed_trade_coverage
from app.market.tw_bar_identity import build_taiwan_bar_series_identity
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


def _bar(*, provider: str, source: str, content_hash: str) -> BarObservation:
    start = datetime(2026, 9, 1, 9, 0, tzinfo=TAIPEI)
    return BarObservation(
        instrument=INSTRUMENT,
        lineage=SourceLineage(
            provider=provider,
            source=source,
            authority=AuthorityClass.VENDOR,
            raw_contract_version="provider.1m.v1",
            event_at=start,
            received_at=start,
            fetched_at=start,
            content_hash=content_hash,
        ),
        interval="1m",
        start_at=start,
        end_at=start + timedelta(minutes=1),
        open_price=Decimal("100.00"),
        high_price=Decimal("101.0"),
        low_price=Decimal("99.000"),
        close_price=Decimal("100.50"),
        volume=Quantity(value=Decimal("10.0"), unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )


def _identity(bar: BarObservation, *, reconciliation: str):
    coverage = observed_trade_coverage(
        (bar,),
        trading_policy_version="tw.trading_policy.v1",
    )
    return build_taiwan_bar_series_identity(
        instrument=INSTRUMENT,
        requested_interval="1m",
        base_interval="1m",
        bars=(bar,),
        coverage=coverage,
        aggregation_version=None,
        state={"reconciliation": reconciliation},
    )


def test_same_numeric_series_with_different_lineage_keeps_numeric_fingerprint() -> None:
    first = _identity(
        _bar(provider="kgi", source="kgi-1m", content_hash="hash-a"),
        reconciliation="pending",
    )
    second = _identity(
        _bar(provider="fugle", source="fugle-1m", content_hash="hash-b"),
        reconciliation="pending",
    )

    assert first.series_fingerprint == second.series_fingerprint
    assert first.lineage_digest != second.lineage_digest
    assert first.series_revision != second.series_revision


def test_state_only_change_updates_state_digest_and_composite_revision() -> None:
    bar = _bar(provider="kgi", source="kgi-1m", content_hash="hash-a")
    pending = _identity(bar, reconciliation="pending")
    matched = _identity(bar, reconciliation="matched")

    assert pending.series_fingerprint == matched.series_fingerprint
    assert pending.lineage_digest == matched.lineage_digest
    assert pending.state_digest != matched.state_digest
    assert pending.series_revision != matched.series_revision
