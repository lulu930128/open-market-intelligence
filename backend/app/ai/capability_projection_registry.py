"""Explicit AI projection registrations backed by canonical dataset IDs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.market_data.registry import DATASET_REGISTRY


Projector = Callable[[Mapping[str, Any]], Any]


def _path_projector(*paths: tuple[str, ...]) -> Projector:
    def project(payload: Mapping[str, Any]) -> Any:
        for path in paths:
            current: Any = payload
            for segment in path:
                if not isinstance(current, Mapping) or segment not in current:
                    current = None
                    break
                current = current[segment]
            if current not in (None, {}, []):
                return current
        return None

    return project


def _truthful_unavailable(_: Mapping[str, Any]) -> dict[str, str]:
    return {
        "status": "unavailable",
        "reason_code": "PROJECTION_NOT_ADVERTISED",
    }


@dataclass(frozen=True)
class CapabilityProjectionSpec:
    capability_id: str
    scope_type: str
    market: str
    dataset_ids: tuple[str, ...]
    projector_name: str
    projector: Projector
    fixture_context: Mapping[str, Any]
    advertised: bool = True
    canonical_schema_version: str | None = None
    compatibility_schema_versions: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str, str]:
        return self.capability_id, self.scope_type, self.market


CAPABILITY_PROJECTION_SPECS: tuple[CapabilityProjectionSpec, ...] = (
    CapabilityProjectionSpec(
        capability_id="quote.snapshot",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.quote.snapshot",),
        projector_name="compact.quote",
        projector=_path_projector(
            ("data", "compact", "quote"),
            ("compact", "quote"),
        ),
        fixture_context={
            "data": {
                "compact": {
                    "quote": {
                        "status": "available",
                        "last_trade_price": 1045,
                        "provider": "fixture",
                    }
                }
            }
        },
        canonical_schema_version="omi.market.quote.snapshot.v1",
        compatibility_schema_versions=("tw.quote.snapshot.v2",),
    ),
    CapabilityProjectionSpec(
        capability_id="quote.snapshot",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.intraday.bars", "us.daily.ohlcv"),
        projector_name="compact.quote",
        projector=_path_projector(
            ("data", "resolved_market_data", "quote_snapshot"),
            ("data", "compact", "quote"),
            ("compact", "quote"),
        ),
        fixture_context={
            "data": {
                "compact": {
                    "quote": {
                        "status": "available",
                        "last_trade_price": 182.5,
                        "provider": "fixture",
                    }
                }
            }
        },
        canonical_schema_version="omi.market.quote.snapshot.v1",
        compatibility_schema_versions=("tw.quote.snapshot.v2",),
    ),
    CapabilityProjectionSpec(
        capability_id="intraday.bars",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.intraday.bars",),
        projector_name="compact.intraday_bars",
        projector=_path_projector(
            ("data", "compact", "intraday_bars"),
            ("compact", "intraday_bars"),
        ),
        fixture_context={
            "data": {
                "compact": {
                    "intraday_bars": {
                        "status": "available",
                        "bars": [{"time": "09:01:00", "close": 1045}],
                    }
                }
            }
        },
        canonical_schema_version="omi.market.bars.v1",
        compatibility_schema_versions=("tw.intraday.bars.v2",),
    ),
    CapabilityProjectionSpec(
        capability_id="intraday.bars",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.intraday.bars",),
        projector_name="compact.intraday_bars",
        projector=_path_projector(
            ("data", "resolved_market_data", "intraday_bars"),
            ("data", "compact", "intraday_bars"),
            ("compact", "intraday_bars"),
        ),
        fixture_context={
            "data": {
                "compact": {
                    "intraday_bars": {
                        "status": "available",
                        "bars": [{"time": "09:31:00-04:00", "close": 182.5}],
                    }
                }
            }
        },
        canonical_schema_version="omi.market.bars.v1",
        compatibility_schema_versions=("tw.intraday.bars.v2",),
    ),
    CapabilityProjectionSpec(
        capability_id="daily.ohlcv",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.daily.ohlcv",),
        projector_name="compact.chart",
        projector=_path_projector(
            ("data", "compact", "chart"),
            ("data", "chart"),
            ("compact", "chart"),
        ),
        fixture_context={
            "data": {
                "compact": {
                    "chart": {
                        "status": "available",
                        "bars": [{"date": "2026-08-18", "close": 1040}],
                    }
                }
            }
        },
        canonical_schema_version="omi.market.bars.v1",
    ),
    CapabilityProjectionSpec(
        capability_id="technical.indicators",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.daily.ohlcv",),
        projector_name="data.resolved_research.technical_indicators",
        projector=_path_projector(
            ("data", "resolved_research", "technical_indicators"),
            ("data", "compact", "technical_indicators"),
        ),
        fixture_context={
            "data": {
                "resolved_research": {
                    "technical_indicators": {
                        "schema_version": "omi.research.technical.indicators.v1",
                        "status": "partial",
                        "quality": {"facts_usable": True, "decision_usable": False},
                    }
                }
            }
        },
        canonical_schema_version="omi.research.technical.indicators.v1",
        compatibility_schema_versions=("tw.technical.indicators.v3",),
    ),
    CapabilityProjectionSpec(
        capability_id="technical.structure",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.daily.ohlcv",),
        projector_name="data.resolved_research.technical_structure",
        projector=_path_projector(
            ("data", "resolved_research", "technical_structure"),
            ("data", "compact", "technical"),
        ),
        fixture_context={
            "data": {
                "resolved_research": {
                    "technical_structure": {
                        "schema_version": "omi.research.technical.structure.v1",
                        "status": "partial",
                        "trend_state": "bullish_stack",
                    }
                }
            }
        },
        canonical_schema_version="omi.research.technical.structure.v1",
    ),
    CapabilityProjectionSpec(
        capability_id="daily.ohlcv",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.daily.ohlcv",),
        projector_name="data.chart",
        projector=_path_projector(
            ("data", "resolved_market_data", "daily_ohlcv"),
            ("data", "compact", "chart"),
            ("data", "chart"),
            ("compact", "chart"),
        ),
        fixture_context={
            "data": {
                "chart": {
                    "status": "available",
                    "bars": [{"date": "2026-08-18", "close": 181.9}],
                }
            }
        },
        canonical_schema_version="omi.market.bars.v1",
    ),
    CapabilityProjectionSpec(
        capability_id="instrument.trading_status",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.quote.snapshot",),
        projector_name="truthful_unavailable",
        projector=_truthful_unavailable,
        fixture_context={},
        advertised=False,
    ),
    CapabilityProjectionSpec(
        capability_id="instrument.trading_status",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.intraday.bars",),
        projector_name="truthful_unavailable",
        projector=_truthful_unavailable,
        fixture_context={},
        advertised=False,
    ),
)


CAPABILITY_PROJECTION_REGISTRY = {spec.key: spec for spec in CAPABILITY_PROJECTION_SPECS}


def validate_capability_projection_registry() -> tuple[str, ...]:
    errors: list[str] = []
    if len(CAPABILITY_PROJECTION_REGISTRY) != len(CAPABILITY_PROJECTION_SPECS):
        errors.append("projection registration keys must be unique")
    dataset_ids = {spec.dataset_id for spec in DATASET_REGISTRY.all()}
    for spec in CAPABILITY_PROJECTION_SPECS:
        missing_datasets = sorted(set(spec.dataset_ids) - dataset_ids)
        if missing_datasets:
            errors.append(f"{spec.key} references unknown datasets {missing_datasets}")
        projected = spec.projector(spec.fixture_context)
        if spec.advertised and projected in (None, {}, []):
            errors.append(f"{spec.key} advertised projection has no fixture payload")
        if spec.advertised and isinstance(projected, Mapping):
            if projected.get("status") in {"planned", "unavailable"}:
                errors.append(f"{spec.key} advertised projection is only a placeholder")
        if spec.market == "US" and spec.advertised and not spec.canonical_schema_version:
            errors.append(f"{spec.key} has no neutral canonical schema version")
        if (
            spec.canonical_schema_version
            and spec.canonical_schema_version in spec.compatibility_schema_versions
        ):
            errors.append(f"{spec.key} repeats canonical schema as compatibility")
    return tuple(errors)


__all__ = [
    "CAPABILITY_PROJECTION_REGISTRY",
    "CAPABILITY_PROJECTION_SPECS",
    "CapabilityProjectionSpec",
    "validate_capability_projection_registry",
]
