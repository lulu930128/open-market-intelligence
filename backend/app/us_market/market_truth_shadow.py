"""Diagnostic-only legacy/canonical US Market Truth comparison."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

from pydantic import Field

from app.market_data.contracts import CanonicalModel
from app.us_market.market_truth_contracts import (
    USComparisonPurpose,
    USMarketTruthSnapshot,
)


MAX_US_TRUTH_SHADOW_DIFFERENCES = 16


class USTruthShadowDifferenceKind(str, Enum):
    VALUE = "value"
    LEGACY_MISSING = "legacy_missing"
    TRUTH_MISSING = "truth_missing"


class USTruthShadowFieldDifference(CanonicalModel):
    field: str = Field(min_length=1, max_length=128)
    kind: USTruthShadowDifferenceKind
    legacy_value: Any = None
    truth_value: Any = None


class USTruthShadowDiff(CanonicalModel):
    contract_version: str = "omi.market.us_truth_shadow_diff.v1"
    status: str
    compared_fields: int = Field(ge=0)
    differences: tuple[USTruthShadowFieldDifference, ...] = ()
    difference_truncated: bool = False
    limitations: tuple[str, ...] = ("DIAGNOSTIC_ONLY_NO_CONSUMER_CUTOVER",)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def compare_legacy_to_us_market_truth(
    *,
    legacy: Mapping[str, Any],
    truth: USMarketTruthSnapshot,
) -> USTruthShadowDiff:
    """Compare bounded outward semantics without mutating either read path."""

    headline = truth.headline_observation
    latest_close = next(
        (
            item
            for item in truth.close_evidence
            if item.evidence_id == truth.close_roles.latest_completed_id
        ),
        None,
    )
    headline_metric = next(
        (
            item
            for item in truth.change_metrics
            if item.purpose is USComparisonPurpose.HEADLINE_CHANGE
        ),
        None,
    )
    fields = (
        ("symbol", str(legacy.get("symbol") or "").strip().upper() or None, truth.instrument.symbol),
        ("market_phase", legacy.get("market_phase"), truth.market_phase),
        ("headline_price", _decimal(legacy.get("price")), headline.price if headline else None),
        (
            "latest_completed_close",
            _decimal(legacy.get("previous_close")),
            latest_close.price if latest_close else None,
        ),
        (
            "headline_absolute_change",
            _decimal(legacy.get("change")),
            headline_metric.absolute_change if headline_metric else None,
        ),
        (
            "headline_percent_change",
            _decimal(legacy.get("change_percent")),
            headline_metric.percent_change if headline_metric else None,
        ),
    )
    differences: list[USTruthShadowFieldDifference] = []
    truncated = False
    for field, legacy_value, truth_value in fields:
        if legacy_value == truth_value:
            continue
        if len(differences) >= MAX_US_TRUTH_SHADOW_DIFFERENCES:
            truncated = True
            continue
        kind = (
            USTruthShadowDifferenceKind.LEGACY_MISSING
            if legacy_value is None and truth_value is not None
            else USTruthShadowDifferenceKind.TRUTH_MISSING
            if legacy_value is not None and truth_value is None
            else USTruthShadowDifferenceKind.VALUE
        )
        differences.append(
            USTruthShadowFieldDifference(
                field=field,
                kind=kind,
                legacy_value=legacy_value,
                truth_value=truth_value,
            )
        )
    return USTruthShadowDiff(
        status="matched" if not differences else "different",
        compared_fields=len(fields),
        differences=tuple(differences),
        difference_truncated=truncated,
    )


__all__ = [
    "MAX_US_TRUTH_SHADOW_DIFFERENCES",
    "USTruthShadowDiff",
    "USTruthShadowDifferenceKind",
    "USTruthShadowFieldDifference",
    "compare_legacy_to_us_market_truth",
]
