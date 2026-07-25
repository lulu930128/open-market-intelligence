from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from app.ai import (
    capability_contract,
    data_quality_contract,
    decision_envelope,
    realtime_contract,
)


CONTRACT_VERSION = "omi.decision.v4"
KIND = "omi_decision"

TARGET_SCOPE_ALIASES = {
    "tw_stock": "stock",
    "tw_watchlist": "watchlist",
    "tw_index": "tw_index",
    "tw_futures": "tw_futures",
    "us_stock": "us_stock",
    "jp_stock": "jp_stock",
    "jp_index": "jp_index",
    "kr_stock": "kr_stock",
    "kr_index": "kr_index",
    "crypto_market": "crypto_market",
    "crypto_asset": "crypto_asset",
    "resource_asset": "resource_asset",
    "portfolio": "portfolio",
    "us_macro": "us_macro",
    "us_watchlist": "us_watchlist",
    "jp_watchlist": "jp_watchlist",
    "kr_watchlist": "kr_watchlist",
    "source_health": "source_health",
    "capability_status": "capability_status",
    "data_freshness": "data_freshness",
    "market": "market",
}

SUPPLEMENTAL_GAP_PATTERNS = {
    "intraday": (
        "intraday",
        "intraday_bars",
        "intraday points",
    ),
    "ownership": (
        "ownership",
        "shareholding",
        "shareholding_distribution_weekly",
    ),
    "fundamentals": (
        "fundamental",
        "financial",
        "monthly_revenue",
        "quarterly_revenue",
        "revenue",
        "eps",
    ),
    "cross_market": (
        "cross_market",
        "overnight",
        "us_overnight",
        "adr",
        "nvda",
    ),
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _scope_type(response: dict[str, Any], canonical: dict[str, Any]) -> str:
    query_plan = _dict(response.get("query_plan"))
    target_type = str(query_plan.get("target_type") or "").strip()
    if target_type:
        return TARGET_SCOPE_ALIASES.get(target_type, target_type)
    target = _dict(canonical.get("target"))
    outward_type = str(target.get("type") or "market").strip()
    return TARGET_SCOPE_ALIASES.get(outward_type, outward_type)


def _selection(
    response: dict[str, Any],
    canonical: dict[str, Any],
    *,
    scope_type: str,
) -> dict[str, Any]:
    query_plan = _dict(response.get("query_plan"))
    existing = query_plan.get("selection")
    if isinstance(existing, dict) and existing.get("version"):
        return deepcopy(existing)
    mode = _dict(canonical.get("mode"))
    intent = str(_dict(canonical.get("decision")).get("intent") or "general")
    return capability_contract.normalize_selection(
        selection=(
            response.get("selection")
            if isinstance(response.get("selection"), dict)
            else None
        ),
        output=(
            str(response.get("output") or "").strip()
            or ("evidence_only" if mode.get("response") == "data_only" else None)
        ),
        realtime_policy=(
            str(response.get("realtime_policy") or "").strip() or None
        ),
        payload_level=str(mode.get("payload_level") or "compact"),
        scope_type=scope_type,
        question_intent=intent,
        requested_domains=tuple(query_plan.get("requested_domains") or ()),
        excluded_domains=tuple(query_plan.get("excluded_domains") or ()),
    )


def _selected_slot_names(selection: dict[str, Any]) -> set[str]:
    output = {"data_quality"}
    for capability_id in list(selection.get("required") or []) + list(
        selection.get("optional") or []
    ):
        spec = capability_contract.CAPABILITIES.get(str(capability_id))
        if spec and spec.slot:
            output.add(spec.slot)
    return output


def _selected_domains(selection: dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    for capability_id in [
        *list(selection.get("required") or []),
        *list(selection.get("optional") or []),
    ]:
        spec = capability_contract.CAPABILITIES.get(str(capability_id))
        if spec and spec.domain and spec.domain != "freshness":
            domains.add(spec.domain)
    return domains


def _freshness_dataset_name(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("key", "dataset", "resource", "name"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return None
    text = str(value or "").strip()
    return text or None


def _project_selected_freshness(
    canonical: dict[str, Any],
    *,
    selection: dict[str, Any],
    projected_data: dict[str, Any],
) -> None:
    freshness = projected_data.get("data.freshness")
    if not isinstance(freshness, dict):
        return

    evidence = _dict(canonical.get("evidence"))
    freshness_by_capability = _dict(
        evidence.get("freshness_by_capability")
    )
    selected_capabilities = [
        str(capability_id)
        for capability_id in [
            *list(selection.get("required") or []),
            *list(selection.get("optional") or []),
        ]
        if capability_id
        not in {
            "target.identity",
            "data.freshness",
        }
        and not str(capability_id).startswith("diagnostics.")
    ]
    if not selected_capabilities or any(
        not isinstance(freshness_by_capability.get(capability_id), dict)
        for capability_id in selected_capabilities
    ):
        return

    selected_rows = [
        (
            capability_id,
            _dict(freshness_by_capability.get(capability_id)),
        )
        for capability_id in selected_capabilities
    ]
    dependency_datasets = list(
        dict.fromkeys(
            dataset
            for _, row in selected_rows
            if (dataset := _freshness_dataset_name(row.get("dataset")))
        )
    )
    dependency_keys = {
        dataset.casefold() for dataset in dependency_datasets
    }

    def matches_selected_dependency(value: Any) -> bool:
        if not dependency_keys:
            return False
        if isinstance(value, dict):
            dataset = _freshness_dataset_name(value)
            if dataset and dataset.casefold() in dependency_keys:
                return True
            text = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).casefold()
        else:
            text = str(value or "").casefold()
        return any(dataset in text for dataset in dependency_keys)

    readiness = [
        capability_contract.status_class(row)
        for _, row in selected_rows
    ]
    is_current = all(
        status_class == "ready" and row.get("is_current") is not False
        for status_class, (_, row) in zip(readiness, selected_rows)
    )
    status = (
        "current"
        if is_current
        else "partial"
        if any(status_class in {"ready", "limited"} for status_class in readiness)
        else "missing"
    )

    global_datasets = _list(freshness.get("datasets"))
    selected_datasets = [
        deepcopy(item)
        for item in global_datasets
        if matches_selected_dependency(item)
    ]
    returned_dataset_keys = {
        name.casefold()
        for item in selected_datasets
        if (name := _freshness_dataset_name(item))
    }
    use_object_shape = any(
        isinstance(item, dict) for item in global_datasets
    )
    for capability_id, row in selected_rows:
        dataset = _freshness_dataset_name(row.get("dataset"))
        if not dataset or dataset.casefold() in returned_dataset_keys:
            continue
        selected_datasets.append(
            {
                "key": dataset,
                "latest": row.get("latest"),
                "expected": row.get("expected"),
                "is_current": (
                    capability_contract.status_class(row) == "ready"
                    and row.get("is_current") is not False
                ),
                "capability": capability_id,
            }
            if use_object_shape or not global_datasets
            else dataset
        )
        returned_dataset_keys.add(dataset.casefold())

    selected_missing = [
        deepcopy(value)
        for value in _list(freshness.get("missing"))
        if matches_selected_dependency(value)
    ]
    selected_warnings = [
        deepcopy(value)
        for value in _list(freshness.get("warnings"))
        if matches_selected_dependency(value)
    ]
    for status_class, (_, row) in zip(readiness, selected_rows):
        if status_class == "ready":
            continue
        dataset = _freshness_dataset_name(row.get("dataset"))
        if dataset and dataset not in selected_missing:
            selected_missing.append(dataset)
        reason = str(row.get("reason") or "").strip()
        if reason and reason not in selected_warnings:
            selected_warnings.append(reason)

    selected_view = deepcopy(freshness)
    selected_view.update(
        {
            "scope": "selected_capabilities",
            "status": status,
            "is_current": is_current,
            "selected_capabilities": selected_capabilities,
            "dependency_datasets": dependency_datasets,
            "datasets": selected_datasets,
            "missing": selected_missing,
            "warnings": selected_warnings,
        }
    )
    expected_dates = freshness.get("expected_dates")
    if isinstance(expected_dates, dict):
        selected_view["expected_dates"] = {
            key: deepcopy(value)
            for key, value in expected_dates.items()
            if str(key).casefold() in dependency_keys
        }
    latest_values = [
        str(row.get("latest"))
        for _, row in selected_rows
        if row.get("latest") is not None
    ]
    if latest_values:
        selected_view["as_of"] = max(latest_values)

    projected_data["data.freshness"] = selected_view
    freshness_by_capability["data.freshness"] = {
        "status": status,
        "is_current": is_current,
        "scope": "selected_capabilities",
        "datasets": dependency_datasets,
        "missing": selected_missing,
        "warnings": selected_warnings,
        "refresh_recommended": not is_current,
    }
    evidence["freshness_by_capability"] = freshness_by_capability
    canonical["evidence"] = evidence


def _supplemental_gap_domain(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    for domain, patterns in SUPPLEMENTAL_GAP_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return domain
    return None


def _separate_supplemental_context_gaps(
    canonical: dict[str, Any],
    *,
    selection: dict[str, Any],
) -> None:
    selected_domains = _selected_domains(selection)
    limitations = _dict(canonical.get("limitations"))
    supplemental = _dict(limitations.get("supplemental_context_gaps"))
    selected_missing: list[str] = []
    supplemental_missing = [
        str(value)
        for value in _list(supplemental.get("missing"))
        if str(value).strip()
    ]
    for value in _list(limitations.get("missing")):
        text = str(value).strip()
        if not text:
            continue
        domain = _supplemental_gap_domain(text)
        if domain and domain not in selected_domains:
            if text not in supplemental_missing:
                supplemental_missing.append(text)
            continue
        selected_missing.append(text)

    selected_warnings: list[str] = []
    supplemental_warnings = [
        str(value)
        for value in _list(supplemental.get("warnings"))
        if str(value).strip()
    ]
    for value in _list(limitations.get("warnings")):
        text = str(value).strip()
        if not text:
            continue
        domain = _supplemental_gap_domain(text)
        if domain and domain not in selected_domains:
            if text not in supplemental_warnings:
                supplemental_warnings.append(text)
            continue
        selected_warnings.append(text)

    limitations["missing"] = list(dict.fromkeys(selected_missing))
    limitations["warnings"] = list(dict.fromkeys(selected_warnings))
    if supplemental_missing or supplemental_warnings:
        limitations["supplemental_context_gaps"] = {
            "scope": "unselected_capabilities",
            "affects_selected_quality": False,
            "missing": supplemental_missing,
            "warnings": supplemental_warnings,
        }
    else:
        limitations.pop("supplemental_context_gaps", None)
    canonical["limitations"] = limitations


def _compact_execution(execution: dict[str, Any]) -> None:
    runs = []
    for run in _list(execution.get("tool_runs"))[:12]:
        if not isinstance(run, dict):
            continue
        runs.append(
            {
                key: deepcopy(run[key])
                for key in (
                    "tool",
                    "provider",
                    "status",
                    "duration_ms",
                    "error_code",
                    "retryable",
                    "fallback_used",
                )
                if key in run
            }
        )
    execution["tool_runs"] = runs
    execution["reasoning_steps"] = []
    execution["diagnostics"] = {}
    tool_plan = _dict(execution.get("tool_plan"))
    if tool_plan:
        raw_steps = tool_plan.get("tool_plan")
        execution["tool_plan"] = {
            "provider": tool_plan.get("provider"),
            "reason": tool_plan.get("reason"),
            "budget": deepcopy(_dict(tool_plan.get("budget"))),
            "step_count": len(raw_steps) if isinstance(raw_steps, list) else 0,
        }


def _compact_quality(quality: dict[str, Any]) -> None:
    capabilities = _dict(quality.get("capabilities"))
    quality["capabilities"] = {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "capability",
                "domain",
                "slot",
                "required",
                "status",
                "status_class",
                "availability",
                "freshness",
                "completeness",
                "release_phase",
                "facts_usable",
                "decision_usable",
                "payload_included",
                "issues",
            )
            if key in item
        }
        for capability_id, item in capabilities.items()
        if isinstance(item, dict)
    }
    quality["issues"] = [
        {
            key: deepcopy(item[key])
            for key in ("code", "severity", "capabilities")
            if key in item
        }
        for item in _list(quality.get("issues"))[:12]
        if isinstance(item, dict)
    ]
    fusion = _dict(quality.get("fusion"))
    quality["fusion"] = {
        "status": fusion.get("status"),
        "issues": [
            {
                key: deepcopy(item[key])
                for key in ("code", "severity", "capabilities")
                if key in item
            }
            for item in _list(fusion.get("issues"))[:8]
            if isinstance(item, dict)
        ],
    }
    upstream = _dict(quality.get("upstream_readiness"))
    quality["upstream_readiness"] = {
        key: deepcopy(upstream[key])
        for key in (
            "facts_ready",
            "analysis_ready",
            "answer_ready",
            "response_ready",
            "decision_ready",
            "decision_required",
            "answer_kind",
            "decision_blocked",
        )
        if key in upstream
    }


def _compact_continuation(continuation: dict[str, Any]) -> None:
    fill_plan = _dict(continuation.get("fill_plan"))
    actions = [
        {
            key: deepcopy(action[key])
            for key in (
                "action_id",
                "capability",
                "operation",
                "status",
                "executable",
                "required",
                "limit",
                "reason",
                "estimated_calls",
                "estimated_timeout_seconds",
                "writes_cache",
                "requires_external_fetch",
            )
            if key in action
        }
        for action in _list(fill_plan.get("actions"))[:8]
        if isinstance(action, dict)
    ]
    deferred_actions = [
        {
            key: deepcopy(action[key])
            for key in (
                "capability",
                "status",
                "reason",
                "release_status",
                "next_eligible_refresh_at",
            )
            if key in action
        }
        for action in _list(fill_plan.get("deferred_actions"))[:8]
        if isinstance(action, dict)
    ]
    continuation["fill_plan"] = {
        "version": fill_plan.get("version"),
        "plan_id": fill_plan.get("plan_id"),
        "actions": actions,
        "deferred_actions": deferred_actions,
        "action_count": fill_plan.get("action_count", len(actions)),
        "auto_executed": fill_plan.get("auto_executed", False),
        "projection_truncated": len(_list(fill_plan.get("actions"))) > len(actions)
        or any(
            isinstance(action, dict) and isinstance(action.get("invoke"), dict)
            for action in _list(fill_plan.get("actions"))
        ),
    }


def _compact_manifest(manifest: dict[str, Any]) -> None:
    manifest["capabilities"] = [
        {
            key: deepcopy(item[key])
            for key in (
                "capability",
                "required",
                "status",
                "status_class",
                "decision_usable",
                "facts_usable",
                "payload_included",
                "limit",
                "omission_reason",
                "quality_ref",
            )
            if key in item
        }
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict)
    ]


def _emergency_compact_envelope(envelope: dict[str, Any]) -> None:
    status = _dict(envelope.get("status"))
    readiness = _dict(status.get("readiness"))
    status["readiness"] = {
        key: deepcopy(readiness[key])
        for key in (
            "facts_ready",
            "analysis_ready",
            "answer_ready",
            "decision_ready",
            "decision_required",
            "evidence_status",
            "trust_level",
            "blocked_sections",
        )
        if key in readiness
    }

    answer = _dict(envelope.get("answer"))
    envelope["answer"] = {
        key: deepcopy(answer[key])
        for key in (
            "kind",
            "headline",
            "text",
            "stance",
            "confidence",
            "source",
        )
        if key in answer
    }
    decision = _dict(envelope.get("decision"))
    envelope["decision"] = {
        key: deepcopy(decision[key])
        for key in ("intent", "action_plan", "blocked_sections")
        if key in decision
    }

    evidence = _dict(envelope.get("evidence"))
    passport = _dict(evidence.get("passport"))
    passport_readiness = _dict(passport.get("decision_readiness"))
    evidence["passport"] = {
        "kind": passport.get("kind"),
        "version": passport.get("version"),
        "trust_level": passport.get("trust_level"),
        "decision_readiness": {
            key: deepcopy(passport_readiness[key])
            for key in (
                "status",
                "decision_ready",
                "blocked_capabilities",
                "limited_capabilities",
                "quality_ref",
            )
            if key in passport_readiness
        },
    }
    evidence["freshness"] = {}
    evidence["freshness_by_domain"] = {}
    evidence["freshness_by_capability"] = {}
    evidence["slots"] = {}
    evidence["source_refs"] = []
    evidence["realtime"] = {}
    evidence["data"] = {}

    manifest = _dict(evidence.get("manifest"))
    manifest["capabilities"] = [
        {
            key: deepcopy(item[key])
            for key in (
                "capability",
                "required",
                "status",
                "status_class",
                "decision_usable",
                "payload_included",
                "omission_reason",
            )
            if key in item
        }
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict)
    ]
    quality = _dict(evidence.get("quality"))
    quality["capabilities"] = {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "required",
                "status",
                "status_class",
                "facts_usable",
                "decision_usable",
            )
            if key in item
        }
        for capability_id, item in _dict(quality.get("capabilities")).items()
        if isinstance(item, dict)
    }
    quality["issues"] = [
        {
            key: deepcopy(item[key])
            for key in ("code", "severity", "capabilities")
            if key in item
        }
        for item in _list(quality.get("issues"))[:4]
        if isinstance(item, dict)
    ]
    quality["fusion"] = {
        "status": _dict(quality.get("fusion")).get("status"),
        "issues": [],
    }
    quality.pop("upstream_readiness", None)
    quality.pop("trust_scope", None)

    execution = _dict(envelope.get("execution"))
    selection = _dict(execution.get("selection"))
    envelope["execution"] = {
        "selection": {
            key: deepcopy(selection[key])
            for key in (
                "version",
                "required",
                "output",
                "max_response_bytes",
            )
            if key in selection
        },
    }
    continuation = _dict(envelope.get("continuation"))
    fill_plan = _dict(continuation.get("fill_plan"))
    continuation.pop("resolution", None)
    continuation.pop("next_context", None)
    continuation.pop("clarification", None)
    continuation.pop("next_actions", None)
    continuation["fill_plan"] = {
        "version": fill_plan.get("version"),
        "plan_id": fill_plan.get("plan_id"),
        "actions": [
            {
                key: deepcopy(action[key])
                for key in (
                    "action_id",
                    "capability",
                    "operation",
                    "status",
                    "executable",
                    "required",
                    "estimated_calls",
                )
                if key in action
            }
            for action in _list(fill_plan.get("actions"))[:4]
            if isinstance(action, dict)
        ],
        "deferred_actions": [
            {
                key: deepcopy(action[key])
                for key in (
                    "capability",
                    "reason",
                    "release_status",
                    "next_eligible_refresh_at",
                )
                if key in action
            }
            for action in _list(fill_plan.get("deferred_actions"))[:4]
            if isinstance(action, dict)
        ],
        "action_count": fill_plan.get("action_count", 0),
        "auto_executed": fill_plan.get("auto_executed", False),
        "projection_truncated": True,
    }
    limitations = _dict(envelope.get("limitations"))
    limitations["missing"] = _list(limitations.get("missing"))[:4]
    limitations["warnings"] = _list(limitations.get("warnings"))[:3]
    compatibility = _dict(envelope.get("compatibility"))
    envelope["compatibility"] = {
        key: deepcopy(compatibility[key])
        for key in ("public_contract", "legacy_contracts_accepted")
        if key in compatibility
    }
    projection = _dict(envelope.get("projection"))
    projection["trimmed_fields"] = _list(
        projection.get("trimmed_fields")
    )[:1]
    projection["trimmed_lists"] = (
        {}
        if projection["trimmed_fields"]
        else {
            key: value
            for key, value in list(
                _dict(projection.get("trimmed_lists")).items()
            )[:1]
        }
    )
    projection.pop("pre_projection_bytes", None)


def _hard_cap_envelope(
    envelope: dict[str, Any],
    *,
    max_bytes: int,
) -> None:
    """Keep the public v4 shape when the normal emergency projection is still too large."""

    def bounded_text(value: Any, *, limit: int) -> str | None:
        text = str(value or "").strip()
        return text[:limit] if text else None

    def bounded_strings(
        value: Any,
        *,
        item_limit: int,
        char_limit: int,
    ) -> list[str]:
        return [
            text
            for item in _list(value)[:item_limit]
            if (text := bounded_text(item, limit=char_limit)) is not None
        ]

    projection = _dict(envelope.get("projection"))
    projection.update(
        {
            "version": "omi.response.projection.v1",
            "max_response_bytes": max_bytes,
            "truncated": True,
            "trimmed_fields": ["response.hard_cap"],
            "trimmed_lists": {},
            "omitted_capabilities": list(
                dict.fromkeys(
                    str(value)
                    for value in _list(projection.get("omitted_capabilities"))
                    if str(value).strip()
                )
            )[:12],
            "actual_response_bytes": max_bytes,
            "budget_met": False,
        }
    )
    projection.pop("pre_projection_bytes", None)

    target = _dict(envelope.get("target"))
    compact_target = {
        key: bounded_text(target.get(key), limit=80)
        for key in (
            "type",
            "id",
            "label",
            "market",
            "exchange",
            "instrument_type",
            "identity_status",
        )
        if bounded_text(target.get(key), limit=80) is not None
    }
    mode = _dict(envelope.get("mode"))
    compact_mode = {
        key: bounded_text(mode.get(key), limit=40)
        for key in ("requested", "effective", "response", "payload_level")
        if bounded_text(mode.get(key), limit=40) is not None
    }
    readiness = _dict(_dict(envelope.get("status")).get("readiness"))
    compact_readiness = {
        key: deepcopy(readiness[key])
        for key in (
            "facts_ready",
            "analysis_ready",
            "answer_ready",
            "decision_ready",
            "decision_required",
            "evidence_status",
            "trust_level",
        )
        if key in readiness
    }

    evidence = _dict(envelope.get("evidence"))
    passport = _dict(evidence.get("passport"))
    passport_readiness = _dict(passport.get("decision_readiness"))
    quality = _dict(evidence.get("quality"))
    compact_quality_capabilities = {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "status",
                "status_class",
                "facts_usable",
                "decision_usable",
                "payload_included",
            )
            if key in item
        }
        for capability_id, item in list(
            _dict(quality.get("capabilities")).items()
        )[:4]
        if isinstance(item, dict)
    }
    manifest = _dict(evidence.get("manifest"))
    compact_evidence = {
        "passport": {
            "version": passport.get("version"),
            "trust_level": passport.get("trust_level"),
            "decision_readiness": {
                key: deepcopy(passport_readiness[key])
                for key in ("status", "decision_ready", "quality_ref")
                if key in passport_readiness
            },
        },
        "freshness": {},
        "freshness_by_domain": {},
        "freshness_by_capability": {},
        "slots": {},
        "source_refs": [],
        "manifest": {
            "version": manifest.get("version"),
            "capabilities": [],
            "ready_count": manifest.get("ready_count", 0),
            "limited_count": manifest.get("limited_count", 0),
            "blocked_count": manifest.get("blocked_count", 0),
        },
        "realtime": {},
        "data": {},
        "quality": {
            key: deepcopy(quality[key])
            for key in (
                "version",
                "status",
                "trust_level",
                "trust_scope",
                "response_ready",
                "facts_ready",
                "analysis_ready",
                "decision_ready",
            )
            if key in quality
        },
    }
    compact_evidence["quality"]["capabilities"] = compact_quality_capabilities

    execution = _dict(envelope.get("execution"))
    selection = _dict(execution.get("selection"))
    reconciliation = _dict(execution.get("refresh_reconciliation"))
    compact_execution = {
        "selection": {
            key: deepcopy(selection[key])
            for key in (
                "version",
                "required",
                "optional",
                "output",
                "realtime_policy",
                "max_response_bytes",
            )
            if key in selection
        },
        "refresh_reconciliation": {
            key: deepcopy(reconciliation[key])
            for key in (
                "version",
                "attempted",
                "attempt_count",
                "remaining_action_count",
            )
            if key in reconciliation
        },
    }

    continuation = _dict(envelope.get("continuation"))
    fill_plan = _dict(continuation.get("fill_plan"))
    compact_continuation = {
        "fill_plan": {
            "version": fill_plan.get("version"),
            "plan_id": fill_plan.get("plan_id"),
            "actions": [],
            "deferred_actions": [],
            "action_count": fill_plan.get("action_count", 0),
            "auto_executed": fill_plan.get("auto_executed", False),
            "projection_truncated": True,
        }
    }
    limitations = _dict(envelope.get("limitations"))
    error = _dict(envelope.get("error"))
    compatibility = _dict(envelope.get("compatibility"))
    compact_envelope = {
        "kind": envelope.get("kind"),
        "contract_version": envelope.get("contract_version"),
        "ok": envelope.get("ok"),
        "request_status": envelope.get("request_status"),
        "question": bounded_text(envelope.get("question"), limit=240),
        "target": compact_target,
        "mode": compact_mode,
        "action": bounded_text(envelope.get("action"), limit=80),
        "caller_profile": bounded_text(
            envelope.get("caller_profile"),
            limit=80,
        ),
        "status": {"readiness": compact_readiness},
        "answer": {},
        "decision": {},
        "evidence": compact_evidence,
        "limitations": {
            "missing": bounded_strings(
                limitations.get("missing"),
                item_limit=4,
                char_limit=120,
            ),
            "warnings": bounded_strings(
                limitations.get("warnings"),
                item_limit=2,
                char_limit=180,
            ),
            "provider_failures": [],
        },
        "execution": compact_execution,
        "continuation": compact_continuation,
        "error": {
            key: bounded_text(error.get(key), limit=160)
            for key in ("code", "message")
            if bounded_text(error.get(key), limit=160) is not None
        },
        "compatibility": {
            key: deepcopy(compatibility[key])
            for key in ("public_contract", "legacy_contracts_accepted")
            if key in compatibility
        },
        "projection": projection,
    }
    envelope.clear()
    envelope.update(compact_envelope)

    if _json_bytes(envelope) > max_bytes:
        envelope["question"] = bounded_text(envelope.get("question"), limit=80)
        envelope["target"].pop("label", None)
        envelope["limitations"]["warnings"] = []
        envelope["execution"].pop("refresh_reconciliation", None)
        envelope["evidence"]["quality"]["capabilities"] = {}
        projection["omitted_capabilities"] = projection[
            "omitted_capabilities"
        ][:6]


def _finalize_projection(
    envelope: dict[str, Any],
    *,
    projection: dict[str, Any],
    max_bytes: int,
) -> None:
    for _ in range(6):
        actual_bytes = _json_bytes(envelope)
        budget_met = actual_bytes <= max_bytes
        if (
            projection.get("actual_response_bytes") == actual_bytes
            and projection.get("budget_met") is budget_met
        ):
            break
        projection["actual_response_bytes"] = actual_bytes
        projection["budget_met"] = budget_met


def _summary_rows(
    value: Any,
    *,
    fields: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            key: deepcopy(row[key])
            for key in fields
            if key in row
        }
        for row in value[:limit]
        if isinstance(row, dict)
    ]


def _summary_dict(
    value: Any,
    *,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: deepcopy(value[key])
        for key in fields
        if key in value
    }


def _brief_capability_summary(
    capability_id: str,
    value: Any,
) -> Any:
    if not isinstance(value, dict):
        return value
    if capability_id == "target.identity":
        return {
            **_summary_dict(
                value,
                fields=(
                    "type",
                    "id",
                    "label",
                    "market",
                    "exchange",
                    "instrument_type",
                    "identity_status",
                ),
            ),
            "projection_level": "summary",
        }
    if capability_id == "quote.snapshot":
        return {
            **_summary_dict(
                value,
                fields=(
                    "status",
                    "price",
                    "latest_price",
                    "last_price",
                    "change",
                    "change_pct",
                    "currency",
                    "volume",
                    "volume_unit",
                    "total_volume_lots",
                    "trade_date",
                    "quote_time",
                    "event_time",
                    "provider",
                    "source",
                    "market_status",
                    "session_phase",
                    "quote_semantics",
                    "is_live",
                    "is_realtime",
                ),
            ),
            "projection_level": "summary",
        }
    if capability_id in {"daily.ohlcv", "intraday.bars"}:
        rows = (
            value.get("points")
            if isinstance(value.get("points"), list)
            else value.get("bars")
            if isinstance(value.get("bars"), list)
            else []
        )
        latest_point = (
            rows[-1]
            if rows and isinstance(rows[-1], dict)
            else value.get("latest_point")
            if isinstance(value.get("latest_point"), dict)
            else {}
        )
        return {
            **_summary_dict(
                value,
                fields=(
                    "as_of",
                    "latest_data_date",
                    "expected_data_date",
                    "interval",
                    "source_interval",
                    "effective_interval",
                    "sampling_mode",
                    "original_point_count",
                    "session",
                    "point_count",
                    "returned_point_count",
                    "truncated",
                    "bar_limit",
                    "volume_unit",
                    "trade_value_unit",
                    "currency",
                    "event_time",
                    "provider",
                    "source",
                    "continuity",
                ),
            ),
            "latest_point": _summary_dict(
                latest_point,
                fields=(
                    "date",
                    "trade_date",
                    "bar_time",
                    "event_time",
                    "open",
                    "open_price",
                    "high",
                    "high_price",
                    "low",
                    "low_price",
                    "close",
                    "close_price",
                    "volume",
                    "base_volume",
                ),
            ),
            "points_included": 0,
            "projection_level": "summary",
        }
    if capability_id == "technical.structure":
        analysis = _dict(value.get("analysis"))
        levels = _dict(value.get("levels"))
        return {
            **_summary_dict(
                value,
                fields=(
                    "as_of",
                    "trade_date",
                    "latest_price",
                    "current_price",
                    "trend",
                    "momentum",
                    "provider",
                    "source",
                ),
            ),
            "analysis": _summary_dict(
                analysis,
                fields=(
                    "requested_horizon",
                    "selected_horizon",
                    "selected_timeframe",
                    "selected_score",
                    "selected_title",
                    "selected_summary",
                    "selected_confidence",
                ),
            ),
            "levels": {
                key: deepcopy(levels[key])
                for key in ("latest_price", "basis_timeframe", "entry", "risk")
                if key in levels
            },
            "projection_level": "summary",
        }
    if capability_id == "chips.institutional":
        return {
            **_summary_dict(
                value,
                fields=(
                    "trade_date",
                    "foreign_investor_net",
                    "foreign_net",
                    "investment_trust_net",
                    "dealer_net",
                    "total_institutional_net",
                    "total_net",
                    "source",
                ),
            ),
            "projection_level": "summary",
        }
    if capability_id == "chips.margin":
        return {
            **_summary_dict(
                value,
                fields=(
                    "trade_date",
                    "margin_buy",
                    "margin_sell",
                    "margin_today_balance",
                    "margin_balance",
                    "margin_change",
                    "short_sale",
                    "short_covering",
                    "short_today_balance",
                    "short_balance",
                    "short_change",
                    "source",
                ),
            ),
            "projection_level": "summary",
        }
    if capability_id == "broker_branch.summary":
        return {
            **_summary_dict(
                value,
                fields=(
                    "trade_date",
                    "available_days",
                    "requested_days",
                    "is_partial",
                    "aggregation_window",
                    "source",
                ),
            ),
            "buy_top": _summary_rows(
                value.get("buy_top"),
                fields=(
                    "branch_code",
                    "branch_name",
                    "net_lots",
                    "buy_lots",
                    "sell_lots",
                ),
                limit=3,
            ),
            "sell_top": _summary_rows(
                value.get("sell_top"),
                fields=(
                    "branch_code",
                    "branch_name",
                    "net_lots",
                    "buy_lots",
                    "sell_lots",
                ),
                limit=3,
            ),
            "projection_level": "summary",
        }
    if capability_id == "ownership.distribution":
        return {
            **_summary_dict(
                value,
                fields=("trade_date", "source"),
            ),
            "distribution": _summary_rows(
                value.get("distribution"),
                fields=(
                    "data_date",
                    "holding_level",
                    "holder_count",
                    "share_count",
                    "share_ratio",
                ),
                limit=3,
            ),
            "projection_level": "summary",
        }
    if capability_id == "data.freshness":
        return {
            **_summary_dict(
                value,
                fields=(
                    "status",
                    "as_of",
                    "is_current",
                    "expected_date",
                    "expected_dates",
                ),
            ),
            "missing": _list(value.get("missing"))[:4],
            "warnings": _list(value.get("warnings"))[:3],
            "projection_level": "summary",
        }
    return value


def _fit_budget(
    envelope: dict[str, Any],
    *,
    selection: dict[str, Any],
) -> dict[str, Any]:
    max_bytes = int(selection.get("max_response_bytes") or 32_768)
    pre_projection_bytes = _json_bytes(envelope)
    projection = {
        "version": "omi.response.projection.v1",
        "max_response_bytes": max_bytes,
        "truncated": False,
        "trimmed_fields": [],
        "trimmed_lists": {},
        "omitted_capabilities": [],
        "pre_projection_bytes": pre_projection_bytes,
        # Reserve the serialized bookkeeping cost while fitting the envelope so
        # adding these fields at the end cannot push a response over budget.
        "actual_response_bytes": max_bytes,
        "budget_met": False,
    }
    envelope["projection"] = projection

    def mark_field(path: str) -> None:
        fields = projection["trimmed_fields"]
        if path not in fields:
            fields.append(path)

    def mark_list(path: str, *, available: int, returned: int) -> None:
        if available <= returned:
            return
        projection["trimmed_lists"][path] = {
            "available": available,
            "returned": returned,
        }

    evidence = _dict(envelope.get("evidence"))
    data = _dict(evidence.get("data"))
    optional = list(selection.get("optional") or [])
    required = list(selection.get("required") or [])
    optional_removal_order = [
        capability_id
        for capability_id in reversed(optional)
        if capability_id not in {"target.identity", "data.freshness"}
    ]
    required_removal_order = [
        capability_id
        for capability_id in reversed(required)
        if capability_id not in {"target.identity", "data.freshness"}
    ]

    def summarize_capability_data() -> bool:
        changed = False
        for capability_id, value in list(data.items()):
            if capability_id == "diagnostics.source_health":
                continue
            summary_value = _brief_capability_summary(
                capability_id,
                value,
            )
            if summary_value == value:
                continue
            data[capability_id] = summary_value
            changed = True
            mark_field(
                f"evidence.data.{capability_id}.projection_level=summary"
            )
            if capability_id in {"daily.ohlcv", "intraday.bars"}:
                rows = (
                    value.get("points")
                    if isinstance(value, dict)
                    and isinstance(value.get("points"), list)
                    else value.get("bars")
                    if isinstance(value, dict)
                    and isinstance(value.get("bars"), list)
                    else []
                )
                mark_list(
                    f"evidence.data.{capability_id}.points",
                    available=len(rows),
                    returned=0,
                )
            elif capability_id == "broker_branch.summary" and isinstance(
                value,
                dict,
            ):
                for key in ("buy_top", "sell_top"):
                    mark_list(
                        f"evidence.data.{capability_id}.{key}",
                        available=len(_list(value.get(key))),
                        returned=len(
                            _list(_dict(data.get(capability_id)).get(key))
                        ),
                    )
        return changed

    if _json_bytes(envelope) > max_bytes:
        execution = _dict(envelope.get("execution"))
        tool_runs_before = len(_list(execution.get("tool_runs")))
        reasoning_before = len(_list(execution.get("reasoning_steps")))
        source_refs_before = len(_list(evidence.get("source_refs")))
        slots_before = len(_dict(evidence.get("slots")))
        fill_actions = _list(
            _dict(_dict(envelope.get("continuation")).get("fill_plan")).get(
                "actions"
            )
        )
        _compact_execution(_dict(envelope.get("execution")))
        _compact_continuation(_dict(envelope.get("continuation")))
        _compact_quality(_dict(evidence.get("quality")))
        allowed_slots = _selected_slot_names(selection)
        slots = _dict(evidence.get("slots"))
        evidence["slots"] = {
            key: value for key, value in slots.items() if key in allowed_slots
        }
        evidence["source_refs"] = _list(evidence.get("source_refs"))[:12]
        mark_field("execution.tool_runs[].result_summary")
        mark_field("execution.diagnostics")
        mark_field("evidence.quality.capabilities.*.detail")
        if any(
            isinstance(action, dict) and isinstance(action.get("invoke"), dict)
            for action in fill_actions
        ):
            mark_field("continuation.fill_plan.actions[].invoke")
        mark_list(
            "execution.tool_runs",
            available=tool_runs_before,
            returned=len(_list(execution.get("tool_runs"))),
        )
        mark_list(
            "execution.reasoning_steps",
            available=reasoning_before,
            returned=0,
        )
        mark_list(
            "evidence.source_refs",
            available=source_refs_before,
            returned=len(_list(evidence.get("source_refs"))),
        )
        mark_list(
            "evidence.slots",
            available=slots_before,
            returned=len(_dict(evidence.get("slots"))),
        )
        projection["truncated"] = True

    if _json_bytes(envelope) > max_bytes:
        _compact_manifest(_dict(evidence.get("manifest")))
        passport = _dict(evidence.get("passport"))
        evidence["passport"] = {
            key: deepcopy(passport[key])
            for key in (
                "kind",
                "version",
                "trust_level",
                "trust_score",
                "decision_readiness",
                "domains",
            )
            if key in passport
        }
        answer = _dict(envelope.get("answer"))
        if isinstance(answer.get("detail"), str):
            answer["detail"] = answer["detail"][:2_000]
        answer["summary"] = _list(answer.get("summary"))[:3]
        decision = _dict(envelope.get("decision"))
        for key in (
            "action_plan",
            "scenarios",
            "counter_evidence",
            "risks",
            "data_limits",
        ):
            original_count = len(_list(decision.get(key)))
            decision[key] = _list(decision.get(key))[:3]
            mark_list(
                f"decision.{key}",
                available=original_count,
                returned=len(_list(decision.get(key))),
            )
        mark_field("evidence.manifest.capabilities[].detail")
        mark_field("evidence.passport.nonessential_fields")
        mark_field("answer.detail")
        projection["truncated"] = True

    if (
        _json_bytes(envelope) > max_bytes
        and isinstance(data.get("diagnostics.source_health"), dict)
    ):
        source_health = _dict(data.get("diagnostics.source_health"))
        original_entries = [
            entry
            for entry in _list(source_health.get("entries"))
            if isinstance(entry, dict)
        ]
        problem_statuses = {
            "missing",
            "empty",
            "stale",
            "delayed",
            "error",
            "blocked",
            "disabled",
        }
        ordered_entries = [
            *[
                entry
                for entry in original_entries
                if str(entry.get("status") or "") in problem_statuses
            ],
            *[
                entry
                for entry in original_entries
                if str(entry.get("status") or "") not in problem_statuses
            ],
        ]
        original_summary = _dict(source_health.get("summary"))
        total_entry_count = int(
            original_summary.get("total_entry_count")
            or original_summary.get("entry_count")
            or len(original_entries)
        )
        total_problem_count = int(
            original_summary.get("total_problem_count")
            or original_summary.get("problem_count")
            or sum(
                1
                for entry in original_entries
                if str(entry.get("status") or "") in problem_statuses
            )
        )
        compact_entry_fields = (
            "market",
            "resource",
            "target",
            "provider",
            "status",
            "ok",
            "row_count",
            "latest_data_date",
            "expected_data_date",
            "release_status",
            "reason",
            "latest_event_status",
            "latest_event_severity",
            "checked_at",
        )
        for sample_limit in (20, 5, 0):
            sampled_entries = [
                {
                    key: (
                        str(entry[key])[:240]
                        if key == "reason" and entry.get(key) is not None
                        else deepcopy(entry[key])
                    )
                    for key in compact_entry_fields
                    if key in entry
                }
                for entry in ordered_entries[:sample_limit]
            ]
            returned_problem_count = sum(
                1
                for entry in sampled_entries
                if str(entry.get("status") or "") in problem_statuses
            )
            returned_status_counts: dict[str, int] = {}
            returned_market_counts: dict[str, int] = {}
            for entry in sampled_entries:
                status = str(entry.get("status") or "unknown")
                market = str(entry.get("market") or "unknown")
                returned_status_counts[status] = (
                    returned_status_counts.get(status, 0) + 1
                )
                returned_market_counts[market] = (
                    returned_market_counts.get(market, 0) + 1
                )
            source_health["entries"] = sampled_entries
            source_health["summary"] = {
                **original_summary,
                "entry_count": total_entry_count,
                "total_entry_count": total_entry_count,
                "matched_entry_count": int(
                    original_summary.get("matched_entry_count")
                    or total_entry_count
                ),
                "returned_entry_count": len(sampled_entries),
                "problem_count": total_problem_count,
                "total_problem_count": total_problem_count,
                "returned_problem_count": returned_problem_count,
                "returned_status_counts": returned_status_counts,
                "returned_market_counts": returned_market_counts,
            }
            source_health["returned_count"] = len(sampled_entries)
            source_health["truncated"] = (
                total_entry_count > len(sampled_entries)
            )
            source_health["is_partial"] = source_health["truncated"]
            source_health["degradation"] = {
                "level": (
                    f"summary_plus_{sample_limit}_problem_sample"
                    if sample_limit
                    else "summary_only"
                ),
                "sample_priority": "non_current_or_failed_first",
                "available_entry_count": total_entry_count,
                "returned_entry_count": len(sampled_entries),
            }
            mark_list(
                "evidence.data.diagnostics.source_health.entries",
                available=max(total_entry_count, len(original_entries)),
                returned=len(sampled_entries),
            )
            mark_field(
                "evidence.data.diagnostics.source_health.entries[].event_diagnostics"
            )
            projection["truncated"] = True
            if _json_bytes(envelope) <= max_bytes:
                break

    mode = _dict(envelope.get("mode"))
    brief_projection = (
        str(mode.get("effective") or "").strip().lower() == "brief"
        or str(envelope.get("report_level") or "").strip().lower() == "brief"
    )
    if _json_bytes(envelope) > max_bytes and brief_projection:
        execution = _dict(envelope.get("execution"))
        selection_contract = _dict(execution.get("selection"))
        reconciliation = _dict(execution.get("refresh_reconciliation"))
        envelope["execution"] = {
            "selection": {
                key: deepcopy(selection_contract[key])
                for key in (
                    "version",
                    "required",
                    "optional",
                    "output",
                    "realtime_policy",
                    "limits",
                    "max_response_bytes",
                )
                if key in selection_contract
            },
            "capability_catalog_version": execution.get(
                "capability_catalog_version"
            ),
            "refresh_reconciliation": {
                key: deepcopy(reconciliation[key])
                for key in (
                    "version",
                    "attempted",
                    "attempt_count",
                    "remaining_action_count",
                    "remaining_action_ids",
                )
                if key in reconciliation
            },
        }
        mark_field("execution.query_plan")
        mark_field("execution.tool_plan")
        mark_field("execution.tool_runs")
        mark_field("execution.reasoning_steps")
        mark_field("execution.diagnostics")
        summarize_capability_data()
        projection["truncated"] = True

    if (
        _json_bytes(envelope) > max_bytes
        and summarize_capability_data()
    ):
        projection["truncated"] = True

    while data and _json_bytes(envelope) > max_bytes and optional_removal_order:
        capability_id = optional_removal_order.pop(0)
        if capability_id not in data:
            continue
        data.pop(capability_id, None)
        projection["omitted_capabilities"].append(capability_id)
        projection["truncated"] = True

    if _json_bytes(envelope) > max_bytes:
        quality = _dict(evidence.get("quality"))
        capability_rows = _dict(quality.get("capabilities"))
        quality["capabilities"] = {
            capability_id: {
                key: deepcopy(item[key])
                for key in (
                    "required",
                    "status",
                    "status_class",
                    "facts_usable",
                    "decision_usable",
                    "payload_included",
                    "issues",
                )
                if key in item
            }
            for capability_id, item in capability_rows.items()
            if isinstance(item, dict)
        }
        quality["issues"] = _list(quality.get("issues"))[:6]
        quality["fusion"] = {
            "status": _dict(quality.get("fusion")).get("status"),
            "issues": _list(_dict(quality.get("fusion")).get("issues"))[:3],
        }
        quality.pop("upstream_readiness", None)
        evidence["slots"] = {}
        evidence["realtime"] = {}
        evidence["source_refs"] = []
        limitations = _dict(envelope.get("limitations"))
        limitations["missing"] = _list(limitations.get("missing"))[:6]
        limitations["warnings"] = _list(limitations.get("warnings"))[:6]
        mark_field("evidence.quality.capabilities.*.diagnostics")
        mark_field("evidence.realtime")
        mark_field("evidence.slots")
        mark_field("evidence.source_refs")
        projection["truncated"] = True

    while data and _json_bytes(envelope) > max_bytes and required_removal_order:
        capability_id = required_removal_order.pop(0)
        if capability_id not in data:
            continue
        data.pop(capability_id, None)
        projection["omitted_capabilities"].append(capability_id)
        projection["truncated"] = True

    if _json_bytes(envelope) > max_bytes:
        evidence["data"] = {}
        projection["omitted_capabilities"] = list(
            dict.fromkeys(
                projection["omitted_capabilities"]
                + list(selection.get("required") or [])
                + list(selection.get("optional") or [])
            )
        )
        projection["truncated"] = True

    manifest = _dict(evidence.get("manifest"))
    quality_capabilities = _dict(_dict(evidence.get("quality")).get("capabilities"))
    omitted = set(projection["omitted_capabilities"])
    for item in _list(manifest.get("capabilities")):
        if isinstance(item, dict) and item.get("capability") in omitted:
            item["payload_included"] = False
            item["omission_reason"] = "response_budget"
    for capability_id in omitted:
        quality_item = quality_capabilities.get(capability_id)
        if isinstance(quality_item, dict):
            quality_item["payload_included"] = False

    if _json_bytes(envelope) > max_bytes:
        _emergency_compact_envelope(envelope)
        mark_field("response.nonessential_fields")
        projection["truncated"] = True

    if _json_bytes(envelope) > max_bytes:
        _hard_cap_envelope(envelope, max_bytes=max_bytes)

    if projection["truncated"] and not (
        projection["trimmed_fields"]
        or projection["trimmed_lists"]
        or projection["omitted_capabilities"]
    ):
        mark_field("response.nonessential_fields")

    _finalize_projection(
        envelope,
        projection=projection,
        max_bytes=max_bytes,
    )
    if projection["truncated"]:
        limitations = _dict(envelope.get("limitations"))
        warnings = [
            str(value)
            for value in _list(limitations.get("warnings"))
            if str(value).strip()
        ]
        omitted_capabilities = projection["omitted_capabilities"]
        if omitted_capabilities:
            detail = (
                "omitted capabilities: "
                + ", ".join(str(value) for value in omitted_capabilities[:6])
            )
        elif projection["trimmed_fields"]:
            detail = (
                "trimmed fields: "
                + ", ".join(
                    str(value) for value in projection["trimmed_fields"][:4]
                )
            )
        else:
            detail = (
                "trimmed lists: "
                + ", ".join(
                    str(value)
                    for value in list(projection["trimmed_lists"])[:4]
                )
            )
        warning = (
            "Selected response was bounded by max_response_bytes; "
            f"{detail}."
        )
        if warning not in warnings:
            warnings.append(warning)
        limitations["warnings"] = warnings
        warning_bytes = _json_bytes(envelope)
        if warning_bytes > max_bytes:
            limitations["warnings"] = [
                value for value in warnings if value != warning
            ]
        if _json_bytes(envelope) > max_bytes:
            _hard_cap_envelope(envelope, max_bytes=max_bytes)
        _finalize_projection(
            envelope,
            projection=projection,
            max_bytes=max_bytes,
        )
    return envelope


def _realtime_observation_data(
    *,
    response: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    selected = list(selection.get("required") or []) + list(
        selection.get("optional") or []
    )
    capability_ids = [
        capability_id
        for capability_id in ("quote.snapshot", "intraday.bars")
        if capability_id in selected
    ]
    if not capability_ids:
        return {}
    observation_selection = deepcopy(selection)
    observation_selection["required"] = capability_ids
    observation_selection["optional"] = []
    observation_selection["fields"] = {
        capability_id: list(
            capability_contract.CAPABILITIES[capability_id].default_fields
        )
        for capability_id in capability_ids
    }
    observation_data, _ = capability_contract.project_selected_data(
        response=response,
        selection=observation_selection,
    )
    return observation_data


def _rejected_envelope(
    canonical: dict[str, Any],
    *,
    selection: dict[str, Any],
) -> dict[str, Any]:
    target = _dict(canonical.get("target"))
    target["identity_status"] = "unresolved"
    canonical["target"] = target
    canonical["contract_version"] = CONTRACT_VERSION
    canonical["kind"] = KIND
    canonical["decision"] = {}

    evidence = _dict(canonical.get("evidence"))
    passport = _dict(evidence.get("passport"))
    evidence["passport"] = {
        key: deepcopy(passport[key])
        for key in (
            "kind",
            "version",
            "trust_level",
            "trust_score",
            "summary",
            "missing",
            "warnings",
        )
        if key in passport
    }
    evidence["manifest"] = {
        "version": "omi.data.manifest.v1",
        "capabilities": [
            {
                "capability": "target.identity",
                "required": True,
                "status": "unresolved",
                "status_class": "blocked",
                "facts_usable": False,
                "decision_usable": False,
                "payload_included": False,
            }
        ],
        "ready_count": 0,
        "limited_count": 0,
        "blocked_count": 1,
    }
    evidence["slots"] = {
        "identity": {
            "status": "unresolved",
            "usability": "unusable",
            "facts_usable": False,
            "decision_usable": False,
        }
    }
    evidence["freshness"] = {}
    evidence["freshness_by_domain"] = {}
    evidence["freshness_by_capability"] = {}
    evidence["realtime"] = {}
    evidence["data"] = {}
    evidence["source_refs"] = []
    evidence.pop("quality", None)
    canonical["evidence"] = evidence

    execution = _dict(canonical.get("execution"))
    canonical["execution"] = {
        "selection": deepcopy(selection),
        "capability_catalog_version": "omi.capability.registry.v1",
        "tool_runs": [],
    }
    continuation = _dict(canonical.get("continuation"))
    canonical["continuation"] = {
        "resolution": deepcopy(_dict(continuation.get("resolution"))),
        "clarification": deepcopy(_dict(continuation.get("clarification"))),
        "fill_plan": {
            "version": "omi.fill.plan.v1",
            "plan_id": capability_contract.fill_plan_id(
                target=target,
                action_ids=[],
            ),
            "actions": [],
            "deferred_actions": [],
            "action_count": 0,
            "auto_executed": False,
        },
    }
    limitations = _dict(canonical.get("limitations"))
    canonical["limitations"] = {
        "missing": [
            str(value)
            for value in _list(limitations.get("missing"))
            if str(value).strip()
        ],
        "warnings": [
            str(value)
            for value in _list(limitations.get("warnings"))
            if str(value).strip()
        ],
        "provider_failures": [],
    }
    canonical["compatibility"] = {
        "public_contract": CONTRACT_VERSION,
        "legacy_contracts_accepted": False,
    }
    return _fit_budget(canonical, selection=selection)


def build(
    response: dict[str, Any],
    *,
    canonical_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_response = deepcopy(response)
    projection_response = deepcopy(source_response)
    if isinstance(canonical_result, dict):
        projection_response["result"] = deepcopy(canonical_result)
    canonical = decision_envelope.build(projection_response)
    scope_type = _scope_type(projection_response, canonical)
    selection = _selection(projection_response, canonical, scope_type=scope_type)
    if canonical.get("ok") is not True or canonical.get("request_status") != "completed":
        return _rejected_envelope(canonical, selection=selection)
    projected_data, unavailable = capability_contract.project_selected_data(
        response=projection_response,
        selection=selection,
    )
    _project_selected_freshness(
        canonical,
        selection=selection,
        projected_data=projected_data,
    )
    realtime_assessments = realtime_contract.annotate_selected_data(
        _realtime_observation_data(
            response=projection_response,
            selection=selection,
        ),
        target=_dict(canonical.get("target")),
        selection=selection,
    )
    manifest = capability_contract.build_manifest(
        canonical=canonical,
        selection=selection,
        projected_data=projected_data,
        realtime_assessments=realtime_assessments,
    )
    quality = data_quality_contract.build_quality_contract(
        canonical=canonical,
        selection=selection,
        manifest=manifest,
        projected_data=projected_data,
        realtime_assessments=realtime_assessments,
        scope_type=scope_type,
    )
    canonical["contract_version"] = CONTRACT_VERSION
    canonical["kind"] = KIND
    evidence = _dict(canonical.get("evidence"))
    evidence.pop("result", None)
    evidence["manifest"] = manifest
    evidence["realtime"] = realtime_assessments
    evidence["data"] = (
        projected_data
        if selection.get("output") in {"evidence_only", "decision_with_evidence"}
        else {}
    )
    canonical["evidence"] = evidence
    execution = _dict(canonical.get("execution"))
    execution["selection"] = deepcopy(selection)
    execution["capability_catalog_version"] = "omi.capability.registry.v1"
    canonical["execution"] = execution
    canonical["compatibility"] = {
        "public_contract": CONTRACT_VERSION,
        "legacy_contracts_accepted": False,
    }

    if selection.get("output") == "evidence_only":
        canonical["answer"] = {}
        canonical["decision"] = {}
    limitations = _dict(canonical.get("limitations"))
    missing = [
        str(value)
        for value in _list(limitations.get("missing"))
        if str(value).strip()
    ]
    for capability_id in unavailable:
        marker = f"capability:{capability_id}"
        if marker not in missing:
            missing.append(marker)
    warnings = [
        str(value)
        for value in _list(limitations.get("warnings"))
        if str(value).strip()
    ]
    for capability_id, assessment in realtime_assessments.items():
        if assessment.get("policy_satisfied") is True:
            continue
        marker = f"realtime:{capability_id}"
        if marker not in missing:
            missing.append(marker)
        warning = (
            f"{capability_id} does not satisfy realtime_policy="
            f"{selection.get('realtime_policy')}: state={assessment.get('state')}; "
            f"{assessment.get('reason')}"
        )
        if warning not in warnings:
            warnings.append(warning)
    limitations["missing"] = missing
    limitations["warnings"] = warnings
    canonical["limitations"] = limitations
    _separate_supplemental_context_gaps(
        canonical,
        selection=selection,
    )
    canonical = data_quality_contract.apply_quality_contract(
        canonical,
        quality=quality,
    )
    reconciled_manifest = _dict(_dict(canonical.get("evidence")).get("manifest"))
    execution = _dict(canonical.get("execution"))
    tool_runs = [
        run
        for run in _list(execution.get("tool_runs"))
        if isinstance(run, dict)
    ]
    fill_plan = capability_contract.build_fill_plan(
        canonical=canonical,
        selection=selection,
        manifest=reconciled_manifest,
        scope_type=scope_type,
        tool_runs=tool_runs,
    )
    execution["refresh_reconciliation"] = (
        capability_contract.build_refresh_reconciliation(
            selection=selection,
            manifest=reconciled_manifest,
            fill_plan=fill_plan,
            tool_runs=tool_runs,
            scope_type=scope_type,
        )
    )
    canonical["execution"] = execution
    continuation = _dict(canonical.get("continuation"))
    continuation["fill_plan"] = fill_plan
    canonical["continuation"] = continuation
    return _fit_budget(canonical, selection=selection)
