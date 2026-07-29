from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.market_context.taiwan_projection import _with_evidence_passport
from app.market.tw_screening import build_tw_screening_snapshot


SCREENING_CAPABILITIES = frozenset(
    {"screening.ranking", "screening.coverage"}
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
    capability_parameters = (
        params.get("capability_parameters")
        if isinstance(params.get("capability_parameters"), dict)
        else {}
    )
    ranking_parameters = capability_parameters.get("screening.ranking")
    snapshot = build_tw_screening_snapshot(
        db,
        parameters=(
            ranking_parameters
            if isinstance(ranking_parameters, dict)
            else None
        ),
        generated_at=now(),
    )
    freshness_by_capability = deepcopy(
        snapshot["freshness_by_capability"]
    )
    missing = list(snapshot["missing"])
    warnings = list(snapshot["warnings"])
    screening = {
        "ranking": deepcopy(snapshot["ranking"]),
        "coverage": deepcopy(snapshot["coverage"]),
    }
    slots = {
        "identity": {
            "status": "ready",
            "capability": "target_identity",
            "payload_ref": "scope",
            "priority": "core",
            "as_of": snapshot["as_of"],
        },
        "screening_ranking": _slot(
            capability="tw_screening_ranking",
            payload_ref="screening.ranking",
            freshness=freshness_by_capability["screening.ranking"],
            missing=missing,
            warnings=warnings,
        ),
        "screening_coverage": _slot(
            capability="tw_screening_coverage",
            payload_ref="screening.coverage",
            freshness=freshness_by_capability["screening.coverage"],
            missing=missing,
            warnings=warnings,
        ),
        "data_quality": {
            "status": "ready" if not missing and not warnings else "partial",
            "capability": "data_quality_and_freshness",
            "payload_ref": "missing,warnings,source_refs,evidence_passport",
            "payload_level": "compact",
            "priority": "core",
            "as_of": snapshot["as_of"],
            "missing": missing,
            "warnings": warnings,
        },
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
        "as_of": snapshot["as_of"],
        "screening": screening,
        "freshness_by_domain": {
            "screening": freshness_by_capability[
                "screening.ranking"
            ].get("status")
        },
        "freshness_by_capability": freshness_by_capability,
        "slots": slots,
    }
    envelope = {
        "kind": "market_overview",
        "generated_at": snapshot["generated_at"],
        "as_of": snapshot["as_of"],
        "scope": {"type": "market", "market": "TW"},
        "data": {
            "screening": screening,
            "freshness_by_domain": compact["freshness_by_domain"],
            "freshness_by_capability": freshness_by_capability,
            "slots": slots,
            "compact": compact,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": deepcopy(snapshot["source_refs"]),
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "status": freshness_by_capability["screening.ranking"].get(
                "status"
            ),
            "is_current": freshness_by_capability["screening.ranking"].get(
                "is_current"
            ),
            "as_of": snapshot["as_of"],
            "datasets": [
                freshness_by_capability["screening.ranking"].get("dataset")
            ],
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
