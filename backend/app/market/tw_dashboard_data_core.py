"""Data Core projection for completed Taiwan dashboard evidence.

The legacy dashboard may still own a current-session compatibility snapshot.
Completed official index and breadth evidence, however, must be projected from
the shared Gateway/Resolver result and must retain its own time and lineage.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.market.official_breadth_platform import read_taiwan_official_breadth
from app.market.official_index_platform import read_taiwan_official_index
from app.market.trading_calendar import TAIWAN_TZ, previous_taiwan_trading_day
from app.market_data.contracts import ResolvedEvidenceStatus
from app.market_data.integration_contracts import MarketDataResultV1


TW_DASHBOARD_DATA_CORE_CONTRACT_VERSION = (
    "omi.market.tw_dashboard_data_core.v1"
)
_INDEX_TO_VENUE = {"TAIEX": "TWSE", "TPEX": "TPEX"}


def _json_model(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _number(value: Decimal | int | float | None) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return float(value)


def _component_base(
    result: MarketDataResultV1,
    *,
    dataset_id: str,
) -> dict[str, Any]:
    health = result.resolved.health
    return {
        "dataset_id": dataset_id,
        "status": health.status.value,
        "selected_provider": health.selected_provider,
        "selection_reason": health.selection_reason,
        "resolved_health": _json_model(health),
        "dataset_health": _json_model(result.dataset_health),
        "provider_health": [_json_model(item) for item in result.provider_health],
        "limitations": list(result.limitations),
    }


def _project_index_component(
    index_result: MarketDataResultV1,
) -> dict[str, Any]:
    index_component = _component_base(
        index_result,
        dataset_id="tw.market_index.daily",
    )
    resolved_index = index_result.resolved.market_index
    if (
        index_result.resolved.health.status
        in {ResolvedEvidenceStatus.SELECTED, ResolvedEvidenceStatus.FALLBACK}
        and resolved_index is not None
    ):
        close_value = _number(resolved_index.close_value)
        change_value = _number(resolved_index.price_change)
        previous_close = (
            float(close_value) - float(change_value)
            if close_value is not None and change_value is not None
            else None
        )
        previous_trade_date = (
            previous_taiwan_trading_day(
                resolved_index.trade_date,
                include_value=False,
            )
            if previous_close is not None
            else None
        )
        index_component["observation"] = {
            "index_id": resolved_index.index_id,
            "venue": resolved_index.venue,
            "trade_date": resolved_index.trade_date,
            "close": close_value,
            "change": change_value,
            "previous_close": previous_close,
            "previous_close_trade_date": previous_trade_date,
            "trade_volume": (
                _number(resolved_index.trade_volume.value)
                if resolved_index.trade_volume is not None
                else None
            ),
            "trade_value": _number(resolved_index.trade_value),
            "transaction_count": resolved_index.transaction_count,
            "session": resolved_index.session.value,
            "state": resolved_index.state.value,
            "finalization": resolved_index.finalization.value,
            "official": resolved_index.official,
            "provisional": resolved_index.provisional,
            "value_semantics": resolved_index.value_semantics,
            "lineage": resolved_index.lineage.model_dump(mode="json"),
        }
    else:
        index_component["observation"] = None
    return index_component


def _project_breadth_component(
    breadth_result: MarketDataResultV1,
) -> dict[str, Any]:
    breadth_component = _component_base(
        breadth_result,
        dataset_id="tw.market_breadth.daily",
    )
    resolved_breadth = breadth_result.resolved.breadth
    if (
        breadth_result.resolved.health.status
        in {ResolvedEvidenceStatus.SELECTED, ResolvedEvidenceStatus.FALLBACK}
        and resolved_breadth is not None
    ):
        classified_count = resolved_breadth.classified_count
        covered_count = resolved_breadth.universe_count - resolved_breadth.missing_count
        coverage_ratio = (
            covered_count / resolved_breadth.universe_count
            if resolved_breadth.universe_count > 0
            else None
        )
        complete_and_available = (
            resolved_breadth.state.value == "available"
            and resolved_breadth.unknown_count == 0
            and resolved_breadth.missing_count == 0
        )
        breadth_component["observation"] = {
            "market": resolved_breadth.venue,
            "venue": resolved_breadth.venue,
            "trade_date": resolved_breadth.trade_date,
            "as_of": resolved_breadth.lineage.event_at
            or resolved_breadth.lineage.fetched_at,
            "snapshot_as_of": resolved_breadth.lineage.event_at
            or resolved_breadth.lineage.fetched_at,
            "advance_count": resolved_breadth.advance_count,
            "decline_count": resolved_breadth.decline_count,
            "unchanged_count": resolved_breadth.unchanged_count,
            "classified_count": classified_count,
            "total_count": resolved_breadth.universe_count,
            "coverage_count": covered_count,
            "coverage_ratio": coverage_ratio,
            "unknown_count": resolved_breadth.unknown_count,
            "missing_count": resolved_breadth.missing_count,
            "trade_value": _number(resolved_breadth.trade_value),
            "scope": resolved_breadth.scope,
            "source": resolved_breadth.lineage.source,
            "market_session": resolved_breadth.session.value,
            "price_semantics": resolved_breadth.price_semantics,
            "is_provisional": resolved_breadth.provisional,
            "official": resolved_breadth.official,
            "state": resolved_breadth.state.value,
            "status": "ready" if complete_and_available else "partial",
            "decision_usable": complete_and_available,
            "universe_definition": {
                "authority": resolved_breadth.universe_source,
                "missing_quote_policy": "unknown_and_missing_remain_explicit",
                "official_full_market": resolved_breadth.official,
            },
            "warnings": list(breadth_result.limitations),
            "lineage": resolved_breadth.lineage.model_dump(mode="json"),
        }
    else:
        breadth_component["observation"] = None
    return breadth_component


def project_taiwan_completed_dashboard_evidence(
    *,
    index_result: MarketDataResultV1,
    breadth_result: MarketDataResultV1,
) -> dict[str, Any]:
    """Project resolved completed-session evidence without re-selection."""

    return {
        "contract_version": TW_DASHBOARD_DATA_CORE_CONTRACT_VERSION,
        "official_index": _project_index_component(index_result),
        "official_breadth": _project_breadth_component(breadth_result),
    }


def _failed_component(dataset_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "status": "unavailable",
        "selected_provider": None,
        "selection_reason": None,
        "resolved_health": None,
        "dataset_health": None,
        "provider_health": [],
        "limitations": [f"DATA_CORE_READ_FAILED:{type(exc).__name__}"],
        "observation": None,
    }


def attach_taiwan_dashboard_data_core(
    db: Session,
    payload: dict[str, Any],
    *,
    requested_at: datetime | None = None,
) -> dict[str, Any]:
    """Attach completed official components; provider IO is never allowed."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    projected_items: list[dict[str, Any]] = []
    for raw_item in payload.get("indices") or []:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        index_id = str(item.get("index_id") or "").strip().upper()
        venue = _INDEX_TO_VENUE.get(index_id)
        if venue is None:
            projected_items.append(item)
            continue
        try:
            index_component = _project_index_component(
                read_taiwan_official_index(
                    db,
                    index_id=index_id,
                    requested_at=effective_requested_at,
                )
            )
        except Exception as exc:
            index_component = _failed_component(
                "tw.market_index.daily",
                exc,
            )
        try:
            breadth_component = _project_breadth_component(
                read_taiwan_official_breadth(
                    db,
                    venue=venue,
                    requested_at=effective_requested_at,
                )
            )
        except Exception as exc:
            breadth_component = _failed_component(
                "tw.market_breadth.daily",
                exc,
            )
        data_core = {
            "contract_version": TW_DASHBOARD_DATA_CORE_CONTRACT_VERSION,
            "official_index": index_component,
            "official_breadth": breadth_component,
        }

        completed_index = data_core["official_index"]["observation"]
        completed_breadth = data_core["official_breadth"]["observation"]
        item["data_core"] = data_core
        item["completed_official_index"] = completed_index
        item["completed_official_breadth"] = completed_breadth
        item["data_core_projection_scope"] = {
            "official_index": (
                "resolved_data_core"
                if completed_index is not None
                else "data_core_missing"
            ),
            "official_breadth": (
                "resolved_data_core"
                if completed_breadth is not None
                else "data_core_missing"
            ),
        }

        # The compatibility resolver may consume these field names, but the
        # values are exclusively owned by the Data Core projection. Missing
        # selected evidence fails closed instead of reviving a legacy row.
        item["official_close_status"] = (
            "confirmed" if completed_index is not None else "not_available"
        )
        item["official_close_price"] = (
            completed_index.get("close") if completed_index is not None else None
        )
        item["official_close_trade_date"] = (
            completed_index.get("trade_date")
            if completed_index is not None
            else None
        )
        item["official_close_time"] = (
            completed_index.get("lineage", {}).get("event_at")
            if completed_index is not None
            else None
        )
        item["official_close_source"] = (
            completed_index.get("lineage", {}).get("source")
            if completed_index is not None
            else None
        )
        item["official_close_provider"] = (
            completed_index.get("lineage", {}).get("provider")
            if completed_index is not None
            else None
        )
        item["official_close_authority"] = (
            completed_index.get("lineage", {}).get("authority")
            if completed_index is not None
            else None
        )
        item["official_close_finalization"] = (
            completed_index.get("finalization")
            if completed_index is not None
            else None
        )
        item["official_close_change"] = (
            completed_index.get("change") if completed_index is not None else None
        )
        item["official_close_previous_close"] = (
            completed_index.get("previous_close")
            if completed_index is not None
            else None
        )
        item["official_close_previous_close_trade_date"] = (
            completed_index.get("previous_close_trade_date")
            if completed_index is not None
            else None
        )
        item["official_close_previous_close_source"] = item[
            "official_close_source"
        ]
        item["official_close_previous_close_provider"] = item[
            "official_close_provider"
        ]
        item["official_close_previous_close_authority"] = item[
            "official_close_authority"
        ]
        item["official_close_previous_close_finalization"] = item[
            "official_close_finalization"
        ]

        legacy_breadth = item.get("breadth")
        if (
            isinstance(legacy_breadth, dict)
            and legacy_breadth.get("scope") == "full_market"
        ):
            item["breadth"] = completed_breadth

        projected_items.append(item)
    return {
        **payload,
        "data_core_contract_version": TW_DASHBOARD_DATA_CORE_CONTRACT_VERSION,
        "indices": projected_items,
    }


__all__ = [
    "TW_DASHBOARD_DATA_CORE_CONTRACT_VERSION",
    "attach_taiwan_dashboard_data_core",
    "project_taiwan_completed_dashboard_evidence",
]
