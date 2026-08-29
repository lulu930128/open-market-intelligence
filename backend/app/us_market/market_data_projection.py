"""Bounded outward projections for resolved US market evidence."""

from __future__ import annotations

from typing import Any

from app.market_data.contracts import ResolvedBarSeries, ResolvedQuote


US_QUOTE_SCHEMA_VERSION = "omi.market.quote.snapshot.v1"
US_BARS_SCHEMA_VERSION = "omi.market.bars.v1"
LEGACY_QUOTE_SCHEMA_VERSION = "tw.quote.snapshot.v2"
LEGACY_INTRADAY_SCHEMA_VERSION = "tw.intraday.bars.v2"


def _health_payload(value: ResolvedQuote | ResolvedBarSeries) -> dict[str, Any]:
    health = value.health
    return {
        "status": health.status.value,
        "selected_provider": health.selected_provider,
        "selected_source": health.selected_source,
        "selected_session": (
            health.selected_session.value if health.selected_session else None
        ),
        "selected_event_at": (
            health.selected_event_at.isoformat() if health.selected_event_at else None
        ),
        "fallback_used": health.fallback_used,
        "selection_reason": health.selection_reason,
        "facts_usable": health.facts_usable,
        "research_usable": health.research_usable,
        "limitations": list(health.limitations),
        "candidates": [
            candidate.model_dump(mode="json") for candidate in value.candidates
        ],
    }


def project_resolved_us_quote(value: ResolvedQuote) -> dict[str, Any]:
    """Project one resolved quote without provider-specific payload fields."""

    payload = {
        "kind": "us_quote_snapshot",
        "schema_version": US_QUOTE_SCHEMA_VERSION,
        "compatibility_schema_versions": [LEGACY_QUOTE_SCHEMA_VERSION],
        **_health_payload(value),
        "quote": None,
    }
    if value.quote is not None:
        quote = value.quote
        payload["quote"] = {
            "market": quote.instrument.market.value,
            "symbol": quote.instrument.symbol,
            "venue": quote.instrument.venue,
            "instrument_type": quote.instrument.instrument_type.value,
            "trade_date": quote.trade_date.isoformat() if quote.trade_date else None,
            "currency": quote.currency,
            "state": quote.state.value,
            "trade_state": quote.trade_state.value,
            "last_trade_price": (
                str(quote.last_trade_price) if quote.last_trade_price is not None else None
            ),
            "open_price": str(quote.open_price) if quote.open_price is not None else None,
            "high_price": str(quote.high_price) if quote.high_price is not None else None,
            "low_price": str(quote.low_price) if quote.low_price is not None else None,
            "previous_close": (
                str(quote.previous_close) if quote.previous_close is not None else None
            ),
            "event_at": (
                quote.lineage.event_at.isoformat() if quote.lineage.event_at else None
            ),
            "received_at": (
                quote.lineage.received_at.isoformat()
                if quote.lineage.received_at
                else None
            ),
            "fetched_at": (
                quote.lineage.fetched_at.isoformat()
                if quote.lineage.fetched_at
                else None
            ),
        }
    return payload


def project_resolved_us_bars(
    value: ResolvedBarSeries,
    *,
    max_bars: int = 500,
    compatibility_schema_versions: tuple[str, ...] = (
        LEGACY_INTRADAY_SCHEMA_VERSION,
    ),
) -> dict[str, Any]:
    """Project a bounded resolved bar series with explicit omission counts."""

    if max_bars < 1 or max_bars > 5000:
        raise ValueError("max_bars must be between 1 and 5000")
    available = len(value.bars)
    selected = value.bars[-max_bars:]
    interval = selected[0].interval if selected else None
    return {
        "kind": "us_bar_series",
        "schema_version": US_BARS_SCHEMA_VERSION,
        "compatibility_schema_versions": list(compatibility_schema_versions),
        **_health_payload(value),
        "interval": interval,
        "available_bar_count": available,
        "point_count": available,
        "returned_bar_count": len(selected),
        "returned_point_count": len(selected),
        "truncated": available > len(selected),
        "bars": [
            {
                "start_at": bar.start_at.isoformat(),
                "end_at": bar.end_at.isoformat(),
                "open_price": str(bar.open_price),
                "high_price": str(bar.high_price),
                "low_price": str(bar.low_price),
                "close_price": str(bar.close_price),
                "volume": str(bar.volume.value) if bar.volume else None,
                "volume_unit": bar.volume.unit.value if bar.volume else None,
                "volume_status": bar.volume_status,
                "price_basis": bar.price_basis,
                "finalization": bar.finalization.value,
                "provider": bar.lineage.provider,
                "source": bar.lineage.source,
                "event_at": (
                    bar.lineage.event_at.isoformat()
                    if bar.lineage.event_at
                    else None
                ),
                "fetched_at": (
                    bar.lineage.fetched_at.isoformat()
                    if bar.lineage.fetched_at
                    else None
                ),
            }
            for bar in selected
        ],
    }


def project_resolved_us_daily_bars(
    value: ResolvedBarSeries,
    *,
    max_bars: int = 500,
) -> dict[str, Any]:
    """Project daily bars without claiming intraday-schema compatibility."""

    return project_resolved_us_bars(
        value,
        max_bars=max_bars,
        compatibility_schema_versions=(),
    )


__all__ = [
    "LEGACY_INTRADAY_SCHEMA_VERSION",
    "LEGACY_QUOTE_SCHEMA_VERSION",
    "US_BARS_SCHEMA_VERSION",
    "US_QUOTE_SCHEMA_VERSION",
    "project_resolved_us_daily_bars",
    "project_resolved_us_bars",
    "project_resolved_us_quote",
]
