"""Bounded legacy/canonical comparison for already-acquired US payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping

from app.market_data.contracts import InstrumentKey, MarketSession
from app.us_market.market_data_projection import (
    US_BARS_SCHEMA_VERSION,
    US_QUOTE_SCHEMA_VERSION,
)
from app.us_market.providers.canonical import canonical_yahoo_chart_payload
from app.us_market.providers.canonical import us_session_for_timestamp


ShadowMode = Literal["off", "shadow", "compare", "canary", "on"]
MAX_US_SHADOW_MISMATCHES = 12


@dataclass(frozen=True, slots=True)
class USCanonicalShadowResult:
    contract_version: str
    mode: ShadowMode
    status: str
    provider: str
    compared_fields: int
    mismatches: tuple[str, ...]
    mismatch_truncated: bool
    quote_schema_version: str
    bars_schema_version: str
    canonical_bar_count: int
    skipped_bar_count: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class USCanonicalDailyComparison:
    contract_version: str
    status: str
    compared_fields: int
    mismatches: tuple[str, ...]
    mismatch_truncated: bool
    legacy_bar_count: int
    canonical_bar_count: int


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _legacy_session(value: Any, latest_point: Mapping[str, Any]) -> MarketSession:
    mapped = {
        "pre_market": MarketSession.PRE_OPEN,
        "regular": MarketSession.CONTINUOUS,
        "after_hours": MarketSession.POST_CLOSE,
        "off_session": MarketSession.CLOSED,
    }.get(str(value or "").strip().lower(), MarketSession.UNKNOWN)
    if mapped is not MarketSession.CONTINUOUS:
        return mapped
    try:
        observed_at = datetime.fromisoformat(str(latest_point.get("time") or ""))
        if us_session_for_timestamp(observed_at) is MarketSession.CLOSING_AUCTION:
            return MarketSession.CLOSING_AUCTION
    except (TypeError, ValueError):
        pass
    return mapped


def compare_yahoo_legacy_to_canonical(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    legacy: Mapping[str, Any],
    fetched_at: datetime,
    session_scope: str,
    mode: ShadowMode,
) -> USCanonicalShadowResult | None:
    """Compare bounded summaries without retaining raw provider payloads."""

    if mode == "off":
        return None
    if mode not in {"shadow", "compare", "canary", "on"}:
        raise ValueError("mode must be one of: off, shadow, compare, canary, on")
    batch = canonical_yahoo_chart_payload(
        instrument=instrument,
        payload=payload,
        fetched_at=fetched_at,
        interval="1m",
        session_scope=session_scope,
    )
    if mode == "shadow":
        return USCanonicalShadowResult(
            contract_version="omi.market.us_shadow_comparison.v1",
            mode=mode,
            status="validated",
            provider=batch.provider,
            compared_fields=0,
            mismatches=(),
            mismatch_truncated=False,
            quote_schema_version=US_QUOTE_SCHEMA_VERSION,
            bars_schema_version=US_BARS_SCHEMA_VERSION,
            canonical_bar_count=len(batch.bars),
            skipped_bar_count=batch.skipped_bar_count,
            limitations=batch.limitations,
        )

    mismatches: list[str] = []
    compared = 0
    truncated = False

    def compare(field: str, legacy_value: Any, canonical_value: Any) -> None:
        nonlocal compared, truncated
        compared += 1
        if legacy_value == canonical_value:
            return
        if len(mismatches) >= MAX_US_SHADOW_MISMATCHES:
            truncated = True
            return
        mismatches.append(field)

    latest_legacy = (legacy.get("points") or [None])[-1]
    latest_legacy = latest_legacy if isinstance(latest_legacy, Mapping) else {}
    latest_bar = batch.bars[-1] if batch.bars else None
    quote = batch.snapshot.quote if batch.snapshot else None
    compare("symbol", str(legacy.get("symbol") or "").upper(), instrument.symbol)
    compare("point_count", int(legacy.get("point_count") or 0), len(batch.bars))
    compare(
        "latest_price",
        _decimal(latest_legacy.get("price")),
        quote.last_trade_price if quote else None,
    )
    compare(
        "latest_volume",
        _decimal(latest_legacy.get("volume")),
        latest_bar.volume.value if latest_bar and latest_bar.volume else None,
    )
    compare(
        "session_phase",
        _legacy_session(legacy.get("session_phase"), latest_legacy),
        batch.snapshot.session.session
        if batch.snapshot and batch.snapshot.session
        else MarketSession.UNKNOWN,
    )
    compare("provider", "yahoo_chart", quote.lineage.provider if quote else None)
    return USCanonicalShadowResult(
        contract_version="omi.market.us_shadow_comparison.v1",
        mode=mode,
        status="matched" if not mismatches else "mismatched",
        provider=batch.provider,
        compared_fields=compared,
        mismatches=tuple(mismatches),
        mismatch_truncated=truncated,
        quote_schema_version=US_QUOTE_SCHEMA_VERSION,
        bars_schema_version=US_BARS_SCHEMA_VERSION,
        canonical_bar_count=len(batch.bars),
        skipped_bar_count=batch.skipped_bar_count,
        limitations=batch.limitations,
    )


def compare_cached_daily_legacy_to_resolved(
    *,
    legacy: Mapping[str, Any],
    resolved: Mapping[str, Any],
) -> USCanonicalDailyComparison:
    """Compare bounded daily values before exposing the resolved canary."""

    legacy_rows = legacy.get("points")
    canonical_rows = resolved.get("bars")
    legacy_rows = legacy_rows if isinstance(legacy_rows, list) else []
    canonical_rows = canonical_rows if isinstance(canonical_rows, list) else []
    mismatches: list[str] = []
    compared = 0
    truncated = False

    def mismatch(field: str) -> None:
        nonlocal truncated
        if len(mismatches) >= MAX_US_SHADOW_MISMATCHES:
            truncated = True
            return
        mismatches.append(field)

    compared += 1
    if len(legacy_rows) != len(canonical_rows):
        mismatch("bar_count")

    for index, (legacy_bar, canonical_bar) in enumerate(
        zip(legacy_rows, canonical_rows)
    ):
        if not isinstance(legacy_bar, Mapping) or not isinstance(
            canonical_bar, Mapping
        ):
            compared += 1
            mismatch(f"bars[{index}].shape")
            continue
        legacy_date = str(legacy_bar.get("time") or "")[:10]
        canonical_date = str(canonical_bar.get("start_at") or "")[:10]
        compared += 1
        if legacy_date != canonical_date:
            mismatch(f"bars[{index}].trade_date")
        for legacy_field, canonical_field in (
            ("open", "open_price"),
            ("high", "high_price"),
            ("low", "low_price"),
            ("close", "close_price"),
            ("volume", "volume"),
        ):
            compared += 1
            if _decimal(legacy_bar.get(legacy_field)) != _decimal(
                canonical_bar.get(canonical_field)
            ):
                mismatch(f"bars[{index}].{legacy_field}")

    return USCanonicalDailyComparison(
        contract_version="omi.market.us_daily_shadow_comparison.v1",
        status="matched" if not mismatches else "mismatched",
        compared_fields=compared,
        mismatches=tuple(mismatches),
        mismatch_truncated=truncated,
        legacy_bar_count=len(legacy_rows),
        canonical_bar_count=len(canonical_rows),
    )


__all__ = [
    "MAX_US_SHADOW_MISMATCHES",
    "USCanonicalDailyComparison",
    "USCanonicalShadowResult",
    "compare_cached_daily_legacy_to_resolved",
    "compare_yahoo_legacy_to_canonical",
]
