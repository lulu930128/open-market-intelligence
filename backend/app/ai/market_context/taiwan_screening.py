from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.market_context.taiwan_projection import _with_evidence_passport
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.tw_screening import build_tw_screening_snapshot
from app.market.tw_intraday_state import (
    build_tw_intraday_group_snapshots,
    build_tw_intraday_screening_snapshot,
)


SCREENING_CAPABILITIES = frozenset(
    {
        "screening.ranking",
        "screening.coverage",
        "screening.intraday",
        "market.hot_groups",
        "market.sectors",
    }
)


def _unique_strings(*values: Any) -> list[str]:
    return list(
        dict.fromkeys(
            str(item)
            for value in values
            for item in (value if isinstance(value, list) else [])
            if str(item).strip()
        )
    )


def _unique_source_refs(*values: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        for row in value if isinstance(value, list) else []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("type") or ""),
                str(row.get("name") or row.get("url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(deepcopy(row))
    return output


def _slot(
    *,
    capability: str,
    payload_ref: str,
    freshness: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "status": freshness.get("status") or "missing",
        "capability": capability,
        "payload_ref": payload_ref,
        "payload_level": "compact",
        "priority": "core",
        "as_of": freshness.get("as_of"),
        "freshness": deepcopy(freshness),
        "missing": list(missing),
        "warnings": list(warnings),
    }


def read_tw_screening_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    params = dict(market_data_params or {})
    requested_capabilities = {
        str(value).strip()
        for value in params.get("requested_capabilities") or []
        if str(value).strip()
    }
    if not requested_capabilities:
        requested_capabilities = {
            "screening.ranking",
            "screening.coverage",
        }
    capability_parameters = (
        params.get("capability_parameters")
        if isinstance(params.get("capability_parameters"), dict)
        else {}
    )
    generated_at = now()
    daily_requested = bool(
        requested_capabilities
        & {"screening.ranking", "screening.coverage"}
    )
    intraday_requested = "screening.intraday" in requested_capabilities
    hot_groups_requested = "market.hot_groups" in requested_capabilities
    sectors_requested = "market.sectors" in requested_capabilities
    calendar_status = build_taiwan_calendar_status(now=generated_at)
    intraday_sector_session = str(
        calendar_status.get("phase") or ""
    ) in {"regular", "closing_auction"}

    daily_snapshot = (
        build_tw_screening_snapshot(
            db,
            parameters=(
                capability_parameters.get("screening.ranking")
                if isinstance(
                    capability_parameters.get("screening.ranking"),
                    dict,
                )
                else None
            ),
            generated_at=generated_at,
        )
        if daily_requested
        else None
    )
    intraday_snapshot = (
        build_tw_intraday_screening_snapshot(
            db,
            parameters=(
                capability_parameters.get("screening.intraday")
                if isinstance(
                    capability_parameters.get("screening.intraday"),
                    dict,
                )
                else None
            ),
            generated_at=generated_at,
        )
        if intraday_requested
        else None
    )
    group_snapshots = (
        build_tw_intraday_group_snapshots(
            db,
            hot_group_limit=int(
                (
                    capability_parameters.get("market.hot_groups")
                    or {}
                ).get("limit", 20)
            )
            if isinstance(
                capability_parameters.get("market.hot_groups"),
                dict,
            )
            else 20,
            generated_at=generated_at,
            include_watchlist_groups=hot_groups_requested,
        )
        if hot_groups_requested
        or sectors_requested and intraday_sector_session
        else None
    )
    hot_groups_snapshot = (
        group_snapshots.get("hot_groups")
        if hot_groups_requested and group_snapshots is not None
        else None
    )
    sector_snapshot = (
        group_snapshots.get("sectors")
        if sectors_requested
        and intraday_sector_session
        and group_snapshots is not None
        else None
    )

    freshness_by_capability: dict[str, dict[str, Any]] = {}
    screening: dict[str, Any] = {}
    market: dict[str, Any] = {}
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    as_of_values: list[Any] = []
    if daily_snapshot is not None:
        freshness_by_capability.update(
            deepcopy(daily_snapshot["freshness_by_capability"])
        )
        screening["ranking"] = deepcopy(daily_snapshot["ranking"])
        screening["coverage"] = deepcopy(daily_snapshot["coverage"])
        missing.extend(daily_snapshot["missing"])
        warnings.extend(daily_snapshot["warnings"])
        source_refs.extend(deepcopy(daily_snapshot["source_refs"]))
        as_of_values.append(daily_snapshot.get("as_of"))
    if intraday_snapshot is not None:
        screening["intraday"] = deepcopy(intraday_snapshot)
        freshness_by_capability["screening.intraday"] = {
            "status": intraday_snapshot["status"],
            "is_current": intraday_snapshot["status"] == "ready",
            "facts_usable": intraday_snapshot["status"]
            in {"ready", "partial"},
            "intraday_research_usable": intraday_snapshot["status"]
            in {"ready", "partial"},
            "execution_grade_usable": False,
            "dataset": "taiwan_intraday_stock_state",
            "as_of": intraday_snapshot.get("event_time"),
            "observed_trade_date": intraday_snapshot.get(
                "observed_trade_date"
            ),
            "computed_at": intraday_snapshot.get("computed_at"),
            "data_mode": intraday_snapshot.get("data_mode"),
        }
        missing.extend(intraday_snapshot["missing"])
        warnings.extend(intraday_snapshot["warnings"])
        source_refs.extend(deepcopy(intraday_snapshot["source_refs"]))
        as_of_values.append(intraday_snapshot.get("event_time"))
    if hot_groups_snapshot is not None:
        screening["hot_groups"] = deepcopy(hot_groups_snapshot)
        freshness_by_capability["market.hot_groups"] = {
            "status": hot_groups_snapshot["status"],
            "is_current": hot_groups_snapshot["status"] == "ready",
            "facts_usable": hot_groups_snapshot["status"]
            in {"ready", "partial"},
            "intraday_research_usable": hot_groups_snapshot["status"]
            in {"ready", "partial"},
            "execution_grade_usable": False,
            "dataset": "taiwan_intraday_stock_state",
            "as_of": hot_groups_snapshot.get("event_time"),
            "observed_trade_date": hot_groups_snapshot.get(
                "observed_trade_date"
            ),
            "computed_at": hot_groups_snapshot.get("computed_at"),
            "data_mode": hot_groups_snapshot.get("data_mode"),
        }
        missing.extend(hot_groups_snapshot["missing"])
        warnings.extend(hot_groups_snapshot["warnings"])
        source_refs.extend(deepcopy(hot_groups_snapshot["source_refs"]))
        as_of_values.append(hot_groups_snapshot.get("event_time"))
    if sector_snapshot is not None and sector_snapshot.get("items"):
        market["sectors"] = deepcopy(sector_snapshot)
        freshness_by_capability["market.sectors"] = {
            "status": sector_snapshot["status"],
            "is_current": sector_snapshot["status"] == "ready",
            "facts_usable": sector_snapshot["status"]
            in {"ready", "partial"},
            "intraday_research_usable": sector_snapshot["status"]
            in {"ready", "partial"},
            "execution_grade_usable": False,
            "dataset": "taiwan_intraday_stock_state",
            "as_of": sector_snapshot.get("event_time")
            or sector_snapshot.get("as_of"),
            "observed_trade_date": sector_snapshot.get(
                "observed_trade_date"
            ),
            "computed_at": sector_snapshot.get("computed_at"),
            "data_mode": sector_snapshot.get("data_mode"),
            "snapshot_id": sector_snapshot.get("snapshot_id"),
        }
        warnings.extend(sector_snapshot["warnings"])
        source_refs.extend(deepcopy(sector_snapshot["source_refs"]))
        as_of_values.append(
            sector_snapshot.get("event_time")
            or sector_snapshot.get("as_of")
        )
    elif sectors_requested and intraday_sector_session:
        warnings.append(
            "Intraday sector state is unavailable; the market context daily "
            "sample fallback remains authoritative for this response."
        )
    missing = _unique_strings(missing)
    warnings = _unique_strings(warnings)
    source_refs = _unique_source_refs(source_refs)
    as_of = max(
        (str(value) for value in as_of_values if value is not None),
        default=None,
    )

    slots: dict[str, dict[str, Any]] = {
        "identity": {
            "status": "ready",
            "capability": "target_identity",
            "payload_ref": "scope",
            "priority": "core",
            "as_of": as_of,
        },
    }
    if "screening.ranking" in freshness_by_capability:
        slots["screening_ranking"] = _slot(
            capability="tw_screening_ranking",
            payload_ref="screening.ranking",
            freshness=freshness_by_capability["screening.ranking"],
            missing=missing,
            warnings=warnings,
        )
    if "screening.coverage" in freshness_by_capability:
        slots["screening_coverage"] = _slot(
            capability="tw_screening_coverage",
            payload_ref="screening.coverage",
            freshness=freshness_by_capability["screening.coverage"],
            missing=missing,
            warnings=warnings,
        )
    if "screening.intraday" in freshness_by_capability:
        slots["screening_intraday"] = _slot(
            capability="tw_screening_intraday",
            payload_ref="screening.intraday",
            freshness=freshness_by_capability["screening.intraday"],
            missing=intraday_snapshot["missing"] if intraday_snapshot else [],
            warnings=(
                intraday_snapshot["warnings"]
                if intraday_snapshot
                else []
            ),
        )
    if "market.hot_groups" in freshness_by_capability:
        slots["market_hot_groups"] = _slot(
            capability="tw_market_hot_groups",
            payload_ref="screening.hot_groups",
            freshness=freshness_by_capability["market.hot_groups"],
            missing=(
                hot_groups_snapshot["missing"]
                if hot_groups_snapshot
                else []
            ),
            warnings=(
                hot_groups_snapshot["warnings"]
                if hot_groups_snapshot
                else []
            ),
        )
    if "market.sectors" in freshness_by_capability:
        slots["market_sectors"] = _slot(
            capability="tw_market_sectors",
            payload_ref="market.sectors",
            freshness=freshness_by_capability["market.sectors"],
            missing=(sector_snapshot or {}).get("missing") or [],
            warnings=(sector_snapshot or {}).get("warnings") or [],
        )
    slots["data_quality"] = {
        "status": "ready" if not missing and not warnings else "partial",
        "capability": "data_quality_and_freshness",
        "payload_ref": "missing,warnings,source_refs,evidence_passport",
        "payload_level": "compact",
        "priority": "core",
        "as_of": as_of,
        "missing": missing,
        "warnings": warnings,
    }
    compact = {
        "kind": "tw_market_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": str(params.get("payload_level") or "compact"),
        "target": {
            "type": "market",
            "id": "TW",
            "label": "台灣市場",
            "market": "TW",
        },
        "as_of": as_of,
        "screening": screening,
        "market": market,
        "freshness_by_domain": {
            "screening": (
                "ready"
                if freshness_by_capability
                and all(
                    item.get("status") == "ready"
                    for item in freshness_by_capability.values()
                )
                else "partial"
                if freshness_by_capability
                else "missing"
            ),
            "sectors": (
                freshness_by_capability.get("market.sectors", {}).get(
                    "status"
                )
                or "not_requested"
            ),
        },
        "freshness_by_capability": freshness_by_capability,
        "slots": slots,
    }
    envelope = {
        "kind": "market_overview",
        "generated_at": generated_at,
        "as_of": as_of,
        "scope": {"type": "market", "market": "TW"},
        "data": {
            "screening": screening,
            "market": market,
            "freshness_by_domain": compact["freshness_by_domain"],
            "freshness_by_capability": freshness_by_capability,
            "slots": slots,
            "compact": compact,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "status": compact["freshness_by_domain"]["screening"],
            "is_current": compact["freshness_by_domain"]["screening"]
            == "ready",
            "as_of": as_of,
            "datasets": list(
                dict.fromkeys(
                    str(item.get("dataset"))
                    for item in freshness_by_capability.values()
                    if item.get("dataset")
                )
            ),
            "missing": missing,
            "warnings": warnings,
        },
    )


def merge_tw_screening_context(
    market_context: dict[str, Any],
    screening_context: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(market_context)
    merged_data = (
        merged.get("data")
        if isinstance(merged.get("data"), dict)
        else {}
    )
    screening_data = (
        screening_context.get("data")
        if isinstance(screening_context.get("data"), dict)
        else {}
    )
    screening = deepcopy(screening_data.get("screening") or {})
    merged_data["screening"] = screening

    merged_compact = (
        merged_data.get("compact")
        if isinstance(merged_data.get("compact"), dict)
        else {}
    )
    screening_compact = (
        screening_data.get("compact")
        if isinstance(screening_data.get("compact"), dict)
        else {}
    )
    merged_compact["screening"] = deepcopy(screening)

    screening_market = (
        screening_data.get("market")
        if isinstance(screening_data.get("market"), dict)
        else {}
    )
    intraday_sectors = screening_market.get("sectors")
    if (
        isinstance(intraday_sectors, dict)
        and intraday_sectors.get("items")
        and intraday_sectors.get("data_mode") == "intraday_rolling_state"
    ):
        merged_market = (
            deepcopy(merged_data.get("market"))
            if isinstance(merged_data.get("market"), dict)
            else {}
        )
        merged_market["sectors"] = deepcopy(intraday_sectors)
        merged_data["market"] = merged_market
        compact_market = (
            deepcopy(merged_compact.get("market"))
            if isinstance(merged_compact.get("market"), dict)
            else {}
        )
        compact_market["sectors"] = deepcopy(intraday_sectors)
        merged_compact["market"] = compact_market

    for key in ("freshness_by_domain", "freshness_by_capability", "slots"):
        combined = (
            deepcopy(merged_data.get(key))
            if isinstance(merged_data.get(key), dict)
            else {}
        )
        from_screening = (
            screening_data.get(key)
            if isinstance(screening_data.get(key), dict)
            else {}
        )
        combined.update(deepcopy(from_screening))
        merged_data[key] = combined

        compact_combined = (
            deepcopy(merged_compact.get(key))
            if isinstance(merged_compact.get(key), dict)
            else {}
        )
        compact_from_screening = (
            screening_compact.get(key)
            if isinstance(screening_compact.get(key), dict)
            else from_screening
        )
        compact_combined.update(deepcopy(compact_from_screening))
        merged_compact[key] = compact_combined

    merged_data["compact"] = merged_compact
    merged["data"] = merged_data
    merged["missing"] = _unique_strings(
        merged.get("missing"),
        screening_context.get("missing"),
    )
    merged["warnings"] = _unique_strings(
        merged.get("warnings"),
        screening_context.get("warnings"),
    )
    merged["source_refs"] = _unique_source_refs(
        merged.get("source_refs"),
        screening_context.get("source_refs"),
    )
    return _with_evidence_passport(
        merged,
        freshness={
            "is_current": not merged["missing"],
            "missing": merged["missing"],
            "warnings": merged["warnings"],
        },
    )
