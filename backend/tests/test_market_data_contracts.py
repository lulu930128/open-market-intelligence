from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    DatasetHealth,
    DatasetHealthStatus,
    DepthCapability,
    DepthLevel,
    DepthObservation,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    AuthorityClass,
    TradeObservationState,
)


NOW = datetime(2026, 8, 19, 9, 1, tzinfo=timezone(timedelta(hours=8)))


def _instrument(symbol: str = "2330") -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol=symbol,
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _lineage() -> SourceLineage:
    return SourceLineage(
        provider="kgi",
        source="kgi.superpy.quote",
        authority=AuthorityClass.BROKER,
        event_at=NOW,
        received_at=NOW,
    )


def test_market_session_and_instrument_tradability_are_distinct_domains() -> None:
    assert MarketSession.CLOSED.value == "closed"
    assert InstrumentTradability.SUSPENDED.value == "suspended"
    assert "suspended" not in {item.value for item in MarketSession}
    assert "closed" not in {item.value for item in InstrumentTradability}


def test_instrument_identity_requires_venue_and_prevents_symbol_collision() -> None:
    with pytest.raises(ValidationError, match="venue is required"):
        InstrumentKey(
            market=Market.TW,
            symbol="2330",
            instrument_type=InstrumentType.STOCK,
        )

    twse = _instrument()
    tpex = _instrument().model_copy(update={"venue": "TPEX"})
    assert twse != tpex


def test_lineage_rejects_naive_timestamps_and_requires_temporal_evidence() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceLineage(
            provider="kgi",
            source="quote",
            authority=AuthorityClass.BROKER,
            event_at=datetime(2026, 8, 19, 9, 0),
        )
    with pytest.raises(ValidationError, match="requires event_at"):
        SourceLineage(
            provider="cache",
            source="sqlite",
            authority=AuthorityClass.CACHE,
        )


def test_unknown_price_is_not_coerced_to_zero() -> None:
    quote = QuoteObservation(
        instrument=_instrument(),
        lineage=_lineage(),
        trade_date=date(2026, 8, 19),
        last_trade_price=None,
        cumulative_quantity=Quantity(value=0, unit=QuantityUnit.SHARE),
    )
    assert quote.last_trade_price is None
    assert quote.trade_state is TradeObservationState.UNKNOWN
    assert quote.cumulative_quantity is not None
    assert quote.cumulative_quantity.value == Decimal("0")

    with pytest.raises(ValidationError, match="last_trade_price must be positive"):
        QuoteObservation(
            instrument=_instrument(),
            lineage=_lineage(),
            last_trade_price=0,
        )


def test_trade_observation_state_is_tri_state_not_a_lossy_boolean() -> None:
    assert {item.value for item in TradeObservationState} >= {
        "unknown",
        "awaiting_first_trade",
        "indicative_observed",
        "trade_observed",
    }


def test_quantity_preserves_original_unit_lineage() -> None:
    quantity = Quantity(
        value=Decimal("3000"),
        unit=QuantityUnit.SHARE,
        original_value=Decimal("3"),
        original_unit=QuantityUnit.BOARD_LOT,
        scale=Decimal("1000"),
    )
    assert quantity.value == quantity.original_value * quantity.scale
    with pytest.raises(ValidationError, match="provided together"):
        Quantity(
            value=Decimal("3000"),
            unit=QuantityUnit.SHARE,
            original_value=Decimal("3"),
        )


def test_depth_capability_bounds_and_order_are_enforced() -> None:
    one = DepthLevel(
        level=1,
        price=Decimal("1045"),
        quantity=Quantity(value=1000, unit=QuantityUnit.SHARE),
    )
    two = one.model_copy(update={"level": 2, "price": Decimal("1040")})
    with pytest.raises(ValidationError, match="exceed declared depth capability"):
        DepthObservation(
            instrument=_instrument(),
            lineage=_lineage(),
            capability=DepthCapability.LEVEL_1,
            bids=(one, two),
        )

    with pytest.raises(ValidationError, match="unique and ordered"):
        DepthObservation(
            instrument=_instrument(),
            lineage=_lineage(),
            capability=DepthCapability.LEVEL_5,
            bids=(two, one),
        )


def test_bar_finalization_and_price_consistency_are_explicit() -> None:
    bar = BarObservation(
        instrument=_instrument(),
        lineage=_lineage(),
        interval="1m",
        start_at=NOW,
        end_at=NOW + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("103"),
        low_price=Decimal("99"),
        close_price=Decimal("102"),
        volume=Quantity(value=1000, unit=QuantityUnit.SHARE),
        finalization=BarFinalization.FINAL,
    )
    assert bar.finalization is BarFinalization.FINAL
    with pytest.raises(ValidationError, match="start_at must be before end_at"):
        BarObservation.model_validate({**bar.model_dump(), "end_at": NOW})


def test_provider_health_keeps_independent_dimensions() -> None:
    health = ProviderResourceHealth(
        provider="kgi",
        market=Market.TW,
        capability="quote",
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.PLAN_RESTRICTED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.MISSING,
        checked_at=NOW,
    )
    assert health.connection is ConnectionStatus.CONNECTED
    assert health.entitlement is EntitlementStatus.PLAN_RESTRICTED
    assert health.freshness is EvidenceFreshness.MISSING


def test_dataset_health_cannot_advertise_refresh_without_operation() -> None:
    with pytest.raises(ValidationError, match="require refresh_operation"):
        DatasetHealth(
            dataset_id="tw.quote.snapshot",
            market=Market.TW,
            status=DatasetHealthStatus.STALE,
            checked_at=NOW,
            refreshable=True,
        )


def test_shared_contract_module_has_no_market_service_or_consumer_imports() -> None:
    module_path = Path(__file__).parents[1] / "app" / "market_data" / "contracts.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_prefixes = (
        "app.market",
        "app.us_market",
        "app.ai",
        "app.models",
        "app.database",
    )
    assert not any(
        module.startswith(forbidden_prefixes) for module in imported_modules
    )


def test_us_level_one_depth_keeps_share_units_without_lot_inference() -> None:
    instrument = InstrumentKey(
        market=Market.US,
        symbol="NVDA",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )
    lineage = SourceLineage(
        provider="fixture",
        source="fixture.us_quote",
        authority=AuthorityClass.VENDOR,
        event_at=NOW,
    )
    depth = DepthObservation(
        instrument=instrument,
        lineage=lineage,
        capability=DepthCapability.LEVEL_1,
        bids=(
            DepthLevel(
                level=1,
                price=Decimal("182.50"),
                quantity=Quantity(value=100, unit=QuantityUnit.SHARE),
            ),
        ),
    )
    assert depth.bids[0].quantity is not None
    assert depth.bids[0].quantity.value == Decimal("100")
    assert depth.bids[0].quantity.original_unit is None


def test_canonical_json_round_trip_preserves_decimal_and_timezone_semantics() -> None:
    quote = QuoteObservation(
        instrument=_instrument(),
        lineage=_lineage(),
        last_trade_price=Decimal("1045.50"),
        trade_state=TradeObservationState.TRADE_OBSERVED,
    )
    serialized = quote.model_dump_json()
    restored = QuoteObservation.model_validate_json(serialized)
    assert restored == quote
    assert '"1045.50"' in serialized
    assert "+08:00" in serialized
