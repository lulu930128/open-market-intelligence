"""Explicit AI projection registrations backed by canonical dataset IDs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.market_data.registry import DATASET_REGISTRY


Projector = Callable[[Mapping[str, Any]], Any]


def _capability_contract_projector(capability_id: str) -> Projector:
    """Use CapabilitySpec.paths as the single executable projection vocabulary."""

    def project(payload: Mapping[str, Any]) -> Any:
        # Import lazily so the production capability registry remains the owner
        # without creating an import cycle during module initialization.
        from app.ai.capability_contract import CAPABILITIES

        spec = CAPABILITIES[capability_id]
        result = payload.get("result")
        result = result if isinstance(result, Mapping) else {}
        data = result.get("data") if isinstance(result.get("data"), Mapping) else None
        if data is None:
            data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
        compact = (
            data.get("compact")
            if isinstance(data.get("compact"), Mapping)
            else payload.get("compact")
            if isinstance(payload.get("compact"), Mapping)
            else {}
        )
        source: Mapping[str, Any] = {
            "target": payload.get("target") or {},
            "result": result,
            "data": data,
            "compact": compact,
            "freshness": payload.get("freshness") or result.get("freshness") or {},
        }
        for raw_path in spec.paths:
            current: Any = source
            for segment in raw_path.split("."):
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
        capability_id="quote.session_close",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.quote.snapshot",),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("quote.session_close"),
        fixture_context={
            "data": {
                "compact": {
                    "quote": {
                        "components": {
                            "session_close": {
                                "status": "session_final",
                                "available": True,
                                "price": 605,
                                "official_daily": False,
                            }
                        }
                    }
                }
            }
        },
        canonical_schema_version="omi.market.tw_session_close.v1",
    ),
    CapabilityProjectionSpec(
        capability_id="quote.snapshot",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.quote.snapshot",),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("quote.snapshot"),
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
        dataset_ids=("us.quote.snapshot", "us.daily.ohlcv"),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("quote.snapshot"),
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
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("intraday.bars"),
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
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("intraday.bars"),
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
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("daily.ohlcv"),
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
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.technical.daily",),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("technical.indicators"),
        fixture_context={
            "data": {
                "technical_indicators": {
                    "schema_version": "tw.technical.indicators.v3",
                    "algorithm_version": "tw.technical.indicators.v3",
                    "price_basis": "raw_unadjusted",
                    "status": "partial",
                }
            }
        },
        canonical_schema_version="omi.research.technical.indicators.v1",
        compatibility_schema_versions=("tw.technical.indicators.v3",),
    ),
    CapabilityProjectionSpec(
        capability_id="technical.structure",
        scope_type="stock",
        market="TW",
        dataset_ids=("tw.technical.daily",),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("technical.structure"),
        fixture_context={
            "data": {
                "compact": {
                    "technical": {
                        "schema_version": "omi.research.technical.structure.v1",
                        "status": "partial",
                        "trend_state": "neutral",
                    }
                }
            }
        },
        canonical_schema_version="omi.research.technical.structure.v1",
    ),
    CapabilityProjectionSpec(
        capability_id="technical.indicators",
        scope_type="us_stock",
        market="US",
        dataset_ids=("us.daily.ohlcv",),
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("technical.indicators"),
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
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("technical.structure"),
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
        projector_name="capability_contract.paths",
        projector=_capability_contract_projector("daily.ohlcv"),
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
    from app.ai.capability_contract import CAPABILITIES

    errors: list[str] = []
    if len(CAPABILITY_PROJECTION_REGISTRY) != len(CAPABILITY_PROJECTION_SPECS):
        errors.append("projection registration keys must be unique")
    dataset_ids = {spec.dataset_id for spec in DATASET_REGISTRY.all()}
    for spec in CAPABILITY_PROJECTION_SPECS:
        if spec.advertised and spec.capability_id not in CAPABILITIES:
            errors.append(f"{spec.key} references unknown capability")
        if spec.advertised and spec.projector_name != "capability_contract.paths":
            errors.append(
                f"{spec.key} advertised projection bypasses CapabilitySpec.paths"
            )
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
