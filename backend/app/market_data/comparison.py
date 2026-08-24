"""Bounded legacy-versus-canonical comparison and in-memory telemetry."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
from threading import RLock
from typing import Any, Mapping

from pydantic import Field

from app.market_data.contracts import (
    CanonicalMarketSnapshot,
    CanonicalModel,
    InstrumentTradability,
    MarketSession,
    Quantity,
    QuantityUnit,
    TradeObservationState,
)


MAX_MISMATCHES = 16
MAX_DEPTH_LEVELS = 5
MAX_METRIC_SERIES = 128


class MismatchCategory(str, Enum):
    IDENTITY = "identity"
    TIME = "time"
    SESSION = "session"
    PRICE = "price"
    VOLUME_UNIT = "volume_unit"
    DEPTH = "depth"
    AUCTION = "auction"
    TRADE_EVIDENCE = "trade_evidence"
    TRADING_STATUS = "trading_status"
    FRESHNESS = "freshness"
    LINEAGE = "lineage"
    SERIALIZATION = "serialization"


class CanonicalMismatch(CanonicalModel):
    category: MismatchCategory
    field: str = Field(min_length=1, max_length=64)
    reason_code: str = Field(min_length=1, max_length=64)
    legacy_value: Any = None
    canonical_value: Any = None


class CanonicalComparisonResult(CanonicalModel):
    contract_version: str = "omi.market.shadow_comparison.v1"
    provider: str = Field(min_length=1, max_length=64)
    compared_fields: int = Field(ge=0, le=128)
    mismatches: tuple[CanonicalMismatch, ...] = ()
    truncated: bool = False

    @property
    def matched(self) -> bool:
        return not self.mismatches


class ComparisonTelemetryEvent(CanonicalModel):
    contract_version: str = "omi.market.shadow_telemetry.v1"
    mode: str = Field(pattern="^(shadow|compare)$")
    provider: str = Field(min_length=1, max_length=64)
    resource: str = "quote_depth"
    market_phase: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern="^(matched|mismatched|validated|error)$")
    mismatch_count: int = Field(ge=0, le=MAX_MISMATCHES)
    categories: tuple[MismatchCategory, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_safe_value(item) for item in value[:MAX_DEPTH_LEVELS])
    return str(type(value).__name__)


def _quantity_lots(quantity: Quantity | None) -> Decimal | None:
    if quantity is None:
        return None
    if quantity.original_unit is QuantityUnit.BOARD_LOT:
        return quantity.original_value
    if quantity.unit is QuantityUnit.SHARE:
        return quantity.value / Decimal("1000")
    return None


def _legacy_depth(value: Any) -> tuple[tuple[Decimal | None, Decimal | None], ...]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return ()
    levels: list[tuple[Decimal | None, Decimal | None]] = []
    for item in parsed[:MAX_DEPTH_LEVELS]:
        if not isinstance(item, Mapping):
            continue
        levels.append((_decimal(item.get("price")), _decimal(item.get("size_lots"))))
    return tuple(levels)


def _canonical_depth(snapshot: CanonicalMarketSnapshot, side: str) -> tuple[
    tuple[Decimal | None, Decimal | None], ...
]:
    if snapshot.depth is None:
        return ()
    levels = snapshot.depth.bids if side == "bid" else snapshot.depth.asks
    return tuple(
        (level.price, _quantity_lots(level.quantity))
        for level in levels[:MAX_DEPTH_LEVELS]
    )


def _legacy_session(value: Any) -> MarketSession:
    normalized = str(value or "").strip().lower()
    return {
        "closed_waiting_preopen": MarketSession.PRE_OPEN,
        "preopen_auction": MarketSession.OPENING_AUCTION,
        "regular_live": MarketSession.CONTINUOUS,
        "closing_auction": MarketSession.CLOSING_AUCTION,
        "post_close_snapshot": MarketSession.POST_CLOSE,
        "market_closed": MarketSession.CLOSED,
    }.get(normalized, MarketSession.UNKNOWN)


def compare_legacy_to_canonical(
    *,
    legacy: Mapping[str, Any],
    canonical: CanonicalMarketSnapshot,
    semantics: Mapping[str, Any] | None = None,
) -> CanonicalComparisonResult:
    """Compare bounded semantic summaries; raw provider payloads are never retained."""

    semantic_values = semantics or {}
    mismatches: list[CanonicalMismatch] = []
    compared_fields = 0
    truncated = False

    def compare(
        category: MismatchCategory,
        field: str,
        legacy_value: Any,
        canonical_value: Any,
        reason_code: str,
    ) -> None:
        nonlocal compared_fields, truncated
        compared_fields += 1
        if legacy_value == canonical_value:
            return
        if len(mismatches) >= MAX_MISMATCHES:
            truncated = True
            return
        mismatches.append(
            CanonicalMismatch(
                category=category,
                field=field,
                reason_code=reason_code,
                legacy_value=_safe_value(legacy_value),
                canonical_value=_safe_value(canonical_value),
            )
        )

    quote = canonical.quote
    compare(
        MismatchCategory.IDENTITY,
        "instrument.symbol",
        str(legacy.get("stock_id") or "").upper(),
        canonical.instrument.symbol,
        "SYMBOL_MISMATCH",
    )
    compare(
        MismatchCategory.TIME,
        "trade_date",
        legacy.get("trade_date"),
        quote.trade_date if quote else None,
        "TRADE_DATE_MISMATCH",
    )
    compare(
        MismatchCategory.TIME,
        "event_at",
        legacy.get("quote_time"),
        quote.lineage.event_at if quote else None,
        "EVENT_TIME_MISMATCH",
    )
    compare(
        MismatchCategory.SESSION,
        "session",
        _legacy_session(legacy.get("session_phase")),
        canonical.session.session if canonical.session else MarketSession.UNKNOWN,
        "SESSION_MISMATCH",
    )
    for legacy_field, canonical_field in (
        ("last_price", "last_trade_price"),
        ("previous_close", "previous_close"),
        ("open_price", "open_price"),
        ("high_price", "high_price"),
        ("low_price", "low_price"),
    ):
        legacy_price = _decimal(legacy.get(legacy_field))
        canonical_price = getattr(quote, canonical_field) if quote else None
        compare(
            MismatchCategory.PRICE,
            canonical_field,
            legacy_price,
            canonical_price,
            (
                "LEGACY_ZERO_NORMALIZED_TO_MISSING"
                if legacy_price == 0 and canonical_price is None
                else "PRICE_MISMATCH"
            ),
        )
    compare(
        MismatchCategory.VOLUME_UNIT,
        "cumulative_volume_lots",
        _decimal(legacy.get("total_volume_lots")),
        _quantity_lots(quote.cumulative_quantity) if quote else None,
        "VOLUME_OR_UNIT_MISMATCH",
    )
    compare(
        MismatchCategory.VOLUME_UNIT,
        "last_trade_volume_lots",
        _decimal(legacy.get("last_trade_volume_lots")),
        _quantity_lots(quote.last_trade_quantity) if quote else None,
        "VOLUME_OR_UNIT_MISMATCH",
    )
    compare(
        MismatchCategory.DEPTH,
        "bid_levels",
        _legacy_depth(legacy.get("bid_levels_json")),
        _canonical_depth(canonical, "bid"),
        "DEPTH_MISMATCH",
    )
    compare(
        MismatchCategory.DEPTH,
        "ask_levels",
        _legacy_depth(legacy.get("ask_levels_json")),
        _canonical_depth(canonical, "ask"),
        "DEPTH_MISMATCH",
    )

    trial = bool(semantic_values.get("trial"))
    expected_trade_state = (
        TradeObservationState.INDICATIVE_OBSERVED
        if trial
        else TradeObservationState.TRADE_OBSERVED
        if _decimal(legacy.get("last_price")) is not None
        else TradeObservationState.AWAITING_FIRST_TRADE
    )
    compare(
        MismatchCategory.TRADE_EVIDENCE,
        "trade_state",
        expected_trade_state,
        quote.trade_state if quote else TradeObservationState.UNKNOWN,
        "TRADE_EVIDENCE_MISMATCH",
    )
    if trial:
        compare(
            MismatchCategory.AUCTION,
            "indicative_price",
            _decimal(semantic_values.get("indicative_price")),
            canonical.auction.indicative_price if canonical.auction else None,
            "AUCTION_PRICE_MISMATCH",
        )
        compare(
            MismatchCategory.AUCTION,
            "indicative_volume_lots",
            _decimal(semantic_values.get("indicative_volume_lots")),
            _quantity_lots(canonical.auction.indicative_quantity)
            if canonical.auction
            else None,
            "AUCTION_VOLUME_OR_UNIT_MISMATCH",
        )
    if "suspend_hint" in semantic_values:
        expected_status = (
            InstrumentTradability.SUSPENDED
            if bool(semantic_values.get("suspend_hint"))
            else InstrumentTradability.UNKNOWN
        )
        compare(
            MismatchCategory.TRADING_STATUS,
            "trading_status",
            expected_status,
            canonical.trading_status.status if canonical.trading_status else None,
            "TRADING_STATUS_MISMATCH",
        )
    compare(
        MismatchCategory.LINEAGE,
        "provider",
        legacy.get("provider"),
        quote.lineage.provider if quote else None,
        "PROVIDER_LINEAGE_MISMATCH",
    )
    compare(
        MismatchCategory.LINEAGE,
        "source",
        legacy.get("source"),
        quote.lineage.source if quote else None,
        "SOURCE_LINEAGE_MISMATCH",
    )
    try:
        canonical.model_dump_json()
    except Exception as exc:
        compare(
            MismatchCategory.SERIALIZATION,
            "canonical_json",
            "serializable",
            type(exc).__name__,
            "SERIALIZATION_FAILED",
        )
    return CanonicalComparisonResult(
        provider=(quote.lineage.provider if quote else "unknown"),
        compared_fields=compared_fields,
        mismatches=tuple(mismatches),
        truncated=truncated,
    )


def build_telemetry_event(
    *,
    mode: str,
    provider: str,
    market_phase: str,
    result: CanonicalComparisonResult | None = None,
    error_code: str | None = None,
) -> ComparisonTelemetryEvent:
    if error_code:
        return ComparisonTelemetryEvent(
            mode=mode,
            provider=provider,
            market_phase=market_phase,
            status="error",
            mismatch_count=0,
            reason_codes=(error_code[:64],),
        )
    if result is None:
        return ComparisonTelemetryEvent(
            mode=mode,
            provider=provider,
            market_phase=market_phase,
            status="validated",
            mismatch_count=0,
        )
    categories = tuple(dict.fromkeys(item.category for item in result.mismatches))
    reason_codes = tuple(dict.fromkeys(item.reason_code for item in result.mismatches))
    return ComparisonTelemetryEvent(
        mode=mode,
        provider=provider,
        market_phase=market_phase,
        status="matched" if result.matched else "mismatched",
        mismatch_count=len(result.mismatches),
        categories=categories,
        reason_codes=reason_codes,
    )


class BoundedComparisonMetrics:
    def __init__(self, *, max_series: int = MAX_METRIC_SERIES) -> None:
        if max_series < 1:
            raise ValueError("max_series must be positive")
        self._max_series = max_series
        self._counts: Counter[tuple[str, str, str, str]] = Counter()
        self._lock = RLock()

    def record(self, event: ComparisonTelemetryEvent) -> None:
        categories = event.categories or ("none",)
        with self._lock:
            for category in categories:
                category_value = category.value if isinstance(category, Enum) else str(category)
                key = (event.mode, event.provider, event.status, category_value)
                overflow_key = (event.mode, "overflow", event.status, "overflow")
                if (
                    key not in self._counts
                    and key != overflow_key
                    and len(self._counts) >= max(0, self._max_series - 1)
                ):
                    key = overflow_key
                self._counts[key] += 1

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                {
                    "mode": key[0],
                    "provider": key[1],
                    "status": key[2],
                    "category": key[3],
                    "count": count,
                }
                for key, count in sorted(self._counts.items())
            )

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


CANONICAL_COMPARISON_METRICS = BoundedComparisonMetrics()


__all__ = [
    "CANONICAL_COMPARISON_METRICS",
    "MAX_METRIC_SERIES",
    "MAX_MISMATCHES",
    "BoundedComparisonMetrics",
    "CanonicalComparisonResult",
    "CanonicalMismatch",
    "ComparisonTelemetryEvent",
    "MismatchCategory",
    "build_telemetry_event",
    "compare_legacy_to_canonical",
]
