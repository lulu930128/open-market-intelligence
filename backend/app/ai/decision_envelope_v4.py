from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any

from app.ai import (
    capability_contract,
    contract_manifest,
    data_quality_contract,
    decision_envelope,
    public_contract,
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
    target = _dict(canonical.get("target"))
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
        target_market=str(target.get("market") or "").strip() or None,
        requested_domains=tuple(query_plan.get("requested_domains") or ()),
        excluded_domains=tuple(query_plan.get("excluded_domains") or ()),
    )


def _apply_selection_trace(
    canonical: dict[str, Any],
    *,
    selection: dict[str, Any],
) -> None:
    mode = _dict(canonical.get("mode"))
    mode["requested_output"] = selection.get("requested_output")
    mode["effective_output"] = selection.get("effective_output")
    mode["output_override_reason"] = selection.get(
        "output_override_reason"
    )
    canonical["mode"] = mode

    execution = _dict(canonical.get("execution"))
    query_plan = _dict(execution.get("query_plan"))
    query_plan["capability_origins"] = deepcopy(
        _dict(selection.get("capability_origins"))
    )
    query_plan["inference_policy"] = selection.get("inference_policy")
    execution["query_plan"] = query_plan
    canonical["execution"] = execution


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


def _selected_internal_tool_runs(
    *,
    response: dict[str, Any],
    selection: dict[str, Any],
) -> list[dict[str, Any]]:
    capability_ids = [
        capability_id
        for capability_id in (
            *selection.get("required", []),
            *selection.get("optional", []),
        )
        if capability_id in capability_contract.CAPABILITIES
        and "tool_runs"
        in capability_contract.CAPABILITIES[capability_id].fields
    ]
    if not capability_ids:
        return []
    audit_selection = deepcopy(selection)
    audit_selection["required"] = capability_ids
    audit_selection["optional"] = []
    audit_selection["fields"] = {
        capability_id: ["tool_runs"]
        for capability_id in capability_ids
    }
    audit_data, _ = capability_contract.project_selected_data(
        response=response,
        selection=audit_selection,
    )
    runs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for capability_id, payload in audit_data.items():
        if not isinstance(payload, dict):
            continue
        for run in _list(payload.get("tool_runs")):
            if not isinstance(run, dict):
                continue
            normalized = deepcopy(run)
            normalized.setdefault(
                "requested_capabilities",
                [capability_id],
            )
            arguments = _dict(normalized.get("arguments"))
            arguments.setdefault(
                "requested_capabilities",
                [capability_id],
            )
            normalized["arguments"] = arguments
            identity = json.dumps(
                {
                    "tool": normalized.get("tool"),
                    "provider": normalized.get("provider"),
                    "arguments": arguments,
                    "status": normalized.get("status"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if identity in seen:
                continue
            seen.add(identity)
            runs.append(normalized)
    return runs


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
    evidence = _dict(canonical.get("evidence"))
    if not isinstance(freshness, dict) or not freshness:
        evidence_freshness = evidence.get("freshness")
        freshness = (
            deepcopy(evidence_freshness)
            if isinstance(evidence_freshness, dict)
            else {}
        )
    freshness_by_capability = _dict(
        evidence.get("freshness_by_capability")
    )
    freshness_by_domain = _dict(evidence.get("freshness_by_domain"))
    slots = _dict(evidence.get("slots"))
    selected_capabilities = [
        str(capability_id)
        for capability_id in list(selection.get("required") or [])
        if capability_id
        not in {
            "target.identity",
            "data.freshness",
        }
        and not str(capability_id).startswith("diagnostics.")
    ]
    selected_rows: list[tuple[str, dict[str, Any]]] = []
    for capability_id in selected_capabilities:
        spec = capability_contract.CAPABILITIES.get(capability_id)
        row = freshness_by_capability.get(capability_id)
        if not isinstance(row, dict):
            domain_row = freshness_by_domain.get(spec.domain) if spec and spec.domain else None
            slot_row = slots.get(spec.slot) if spec and spec.slot else None
            payload = _dict(projected_data.get(capability_id))
            payload_freshness = _dict(payload.get("freshness"))
            explicit_is_current = payload.get("is_current")
            payload_status = capability_contract.normalize_status(
                payload_freshness.get("status")
                or payload.get("freshness_status")
                or payload.get("status")
                or (
                    "current"
                    if explicit_is_current is True
                    else "stale"
                    if explicit_is_current is False
                    else None
                )
            )
            payload_row = (
                {
                    "status": payload_status,
                    "is_current": (
                        explicit_is_current
                        if isinstance(explicit_is_current, bool)
                        else capability_contract.status_class(
                            {"status": payload_status}
                        )
                        == "ready"
                    ),
                    "latest": (
                        payload.get("trade_date")
                        or payload.get("as_of")
                        or payload.get("calculated_at")
                    ),
                    "source": "selected_payload",
                }
                if payload and payload_status not in {"unknown", "missing"}
                else None
            )
            if isinstance(domain_row, dict):
                row = deepcopy(domain_row)
            elif domain_row is not None:
                row = {"status": capability_contract.normalize_status(domain_row)}
            elif payload_row is not None:
                row = payload_row
            elif isinstance(slot_row, dict):
                slot_freshness = slot_row.get("freshness")
                row = (
                    deepcopy(slot_freshness)
                    if isinstance(slot_freshness, dict)
                    else {"status": capability_contract.normalize_status(slot_row.get("status"))}
                )
            else:
                row = {
                    "status": "missing",
                    "reason": (
                        "No canonical freshness row is available for "
                        f"{capability_id}."
                    ),
                }
            row.setdefault("dataset", capability_id)
            row.setdefault("capability", capability_id)
            freshness_by_capability[capability_id] = deepcopy(row)
        selected_rows.append((capability_id, _dict(row)))
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
            "version": freshness.get("version") or "omi.freshness.selection.v1",
            "scope": "selected_capabilities",
            "status": status,
            "is_current": is_current,
            "selected_capabilities": selected_capabilities,
            "supplemental_capabilities": [
                str(capability_id)
                for capability_id in list(selection.get("optional") or [])
                if capability_id
                not in {
                    "target.identity",
                    "data.freshness",
                }
                and not str(capability_id).startswith("diagnostics.")
            ],
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
                    "transport_status",
                    "operation_status",
                    "evidence_status",
                    "duration_ms",
                    "error",
                    "error_message",
                    "error_code",
                    "retryable",
                    "fallback_used",
                    "external_fetch",
                    "writes_cache",
                    "requested_capabilities",
                    "result_status",
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
                "intraday_research_usable",
                "execution_grade_usable",
                "policy_satisfied",
                "decision_usable",
                "payload_included",
                "status_authority",
                "refresh_recommended",
                "refresh_possible_now",
                "refresh_allowed",
                "refresh_requested",
                "selected_provider",
                "selected_source",
                "selection_reason",
                "fallback_used",
                "upstream_status_authority",
                "trade_date",
                "event_time",
                "release_at",
                "fetched_at",
                "computed_at",
                "served_at",
                "units",
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


def _compact_capability_status(
    capability_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "required",
                "applicability_status",
                "availability_status",
                "freshness_status",
                "release_status",
                "coverage_status",
                "usability_status",
                "facts_usable",
                "decision_usable",
                "trade_date",
                "event_time",
                "release_at",
                "fetched_at",
                "computed_at",
                "served_at",
                "reason_codes",
                "status_authority",
            )
            if key in item
        }
        for capability_id, item in capability_status.items()
        if isinstance(item, dict)
    }


def _compact_fill_partition(fill_plan: dict[str, Any]) -> dict[str, Any]:
    partition = _dict(fill_plan.get("partition"))
    if not partition:
        return {}
    compact = {
        "version": partition.get("version"),
        "selected_capabilities": [
            str(capability)
            for capability in _list(partition.get("selected_capabilities"))
            if str(capability).strip()
        ],
        **{
            group_name: [
                str(capability)
                for capability in _list(partition.get(group_name))
                if str(capability).strip()
            ]
            for group_name in capability_contract.FILL_PARTITION_GROUPS
        },
        "complete": bool(partition.get("complete")),
    }
    if partition.get("reason") is not None:
        compact["reason"] = partition.get("reason")
    return compact


def _compact_fill_jobs(
    fill_plan: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    return [
        {
            key: deepcopy(job[key])
            for key in (
                "capability",
                "operation",
                "job_id",
                "status",
                "operation_status",
                "evidence_status",
                "deduplicated",
                "status_url",
                "resolution_type",
                "reason",
            )
            if key in job
        }
        for job in _list(fill_plan.get("jobs"))[:limit]
        if isinstance(job, dict)
    ]


def _compact_already_attempted_actions(
    fill_plan: dict[str, Any],
    *,
    limit: int,
    required: set[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            key: deepcopy(action[key])
            for key in (
                "capability",
                "status",
                "status_class",
                "payload_included",
                "resolution_type",
                "reason",
                "refresh_strategy",
                "refresh_possible_now",
                "refresh_requires_market_open",
                "writes_market_cache",
                "operation",
                "provider",
                "target",
                "error_message",
                "retryable",
            )
            if key in action
        }
        for action in _list(fill_plan.get("already_attempted_actions"))
        if isinstance(action, dict)
        and (
            required is None
            or str(action.get("capability") or "") in required
        )
    ][:limit]


def _compact_continuation(continuation: dict[str, Any]) -> None:
    fill_plan = _dict(continuation.get("fill_plan"))
    actions = [
        {
            key: deepcopy(action[key])
            for key in (
                "action_id",
                "capability",
                "operation",
                "refresh_strategy",
                "status",
                "executable",
                "required",
                "limit",
                "reason",
                "estimated_calls",
                "estimated_timeout_seconds",
                "refresh_possible_now",
                "refresh_requires_market_open",
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
                "refresh_strategy",
                "refresh_possible_now",
                "refresh_requires_market_open",
                "writes_market_cache",
                "estimated_calls",
                "expected_timeout_seconds",
                "operation",
                "provider",
                "target",
                "error_message",
                "retryable",
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
        "jobs": _compact_fill_jobs(fill_plan, limit=8),
        "deferred_actions": deferred_actions,
        "already_attempted_actions": _compact_already_attempted_actions(
            fill_plan,
            limit=8,
        ),
        "partition": _compact_fill_partition(fill_plan),
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
                "refresh_recommended",
                "refresh_allowed",
                "refresh_requested",
                "refresh_strategy",
                "fill_operation",
                "refresh_possible_now",
                "refresh_requires_market_open",
                "writes_market_cache",
                "estimated_calls",
                "expected_timeout_seconds",
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
                "refresh_recommended",
                "refresh_allowed",
                "refresh_requested",
                "refresh_strategy",
                "fill_operation",
                "refresh_possible_now",
                "refresh_requires_market_open",
                "writes_market_cache",
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
                "unsupported_capabilities",
                "output",
                "max_response_bytes",
                "requested_max_response_bytes",
                "default_max_response_bytes",
                "effective_max_response_bytes",
                "max_response_ceiling_bytes",
                "response_budget_source",
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
                    "refresh_strategy",
                    "status",
                    "executable",
                    "required",
                    "estimated_calls",
                    "refresh_possible_now",
                    "refresh_requires_market_open",
                    "writes_cache",
                )
                if key in action
            }
            for action in _list(fill_plan.get("actions"))[:4]
            if isinstance(action, dict)
        ],
        "jobs": _compact_fill_jobs(fill_plan, limit=4),
        "deferred_actions": [
            {
                key: deepcopy(action[key])
                for key in (
                    "capability",
                    "reason",
                    "release_status",
                    "next_eligible_refresh_at",
                    "refresh_strategy",
                    "refresh_possible_now",
                    "refresh_requires_market_open",
                    "writes_market_cache",
                )
                if key in action
            }
            for action in _list(fill_plan.get("deferred_actions"))[:4]
            if isinstance(action, dict)
        ],
        "already_attempted_actions": _compact_already_attempted_actions(
            fill_plan,
            limit=4,
        ),
        "partition": _compact_fill_partition(fill_plan),
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
            "status_dimensions": deepcopy(
                _dict(passport.get("status_dimensions"))
            ),
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
            "unsupported_capabilities": deepcopy(
                _list(manifest.get("unsupported_capabilities"))[:8]
            ),
            "unsupported_count": manifest.get("unsupported_count", 0),
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
        "status_dimensions": deepcopy(
            _dict(evidence.get("status_dimensions"))
        ),
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
                "unsupported_capabilities",
                "output",
                "requested_output",
                "effective_output",
                "output_override_reason",
                "realtime_policy",
                "max_response_bytes",
                "requested_max_response_bytes",
                "default_max_response_bytes",
                "effective_max_response_bytes",
                "max_response_ceiling_bytes",
                "response_budget_source",
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
            "jobs": _compact_fill_jobs(fill_plan, limit=4),
            "deferred_actions": [],
            "already_attempted_actions": _compact_already_attempted_actions(
                fill_plan,
                limit=4,
            ),
            "partition": _compact_fill_partition(fill_plan),
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
            "current_request_failures": deepcopy(
                _list(limitations.get("current_request_failures"))[:8]
            ),
            "background_source_health": deepcopy(
                _list(limitations.get("background_source_health"))[:8]
            ),
            "historical_provider_events": deepcopy(
                _list(limitations.get("historical_provider_events"))[:8]
            ),
            "unsupported_capabilities": deepcopy(
                _list(limitations.get("unsupported_capabilities"))[:8]
            ),
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


def _brief_technical_indicator_point(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _summary_dict(
        value,
        fields=(
            "time",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "algorithm_version",
            "price_basis",
            "ma",
            "volume_ma",
            "ema",
            "macd",
            "rsi",
            "atr",
            "adx",
            "roc",
            "mfi",
            "bollinger",
            "kd",
            "pvo",
            "support_resistance",
        ),
    )


def _brief_technical_advanced_summary(
    capability_id: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    common = _summary_dict(
        value,
        fields=(
            "kind",
            "algorithm_version",
            "method",
            "status",
            "decision_usable",
            "as_of",
            "price_basis",
            "source_granularity",
            "confidence",
            "corporate_action",
            "missing",
            "warnings",
            "limitations",
            "source_refs",
        ),
    )
    if capability_id == "technical.swings":
        common.update(
            {
                **_summary_dict(value, fields=("parameters", "confirmed_count")),
                "pivots": _summary_rows(
                    list(value.get("pivots") or [])[-4:],
                    fields=(
                        "evidence_id",
                        "type",
                        "price",
                        "pivot_time",
                        "confirmed_at",
                        "status",
                        "price_basis",
                    ),
                    limit=4,
                ),
                "provisional": _summary_rows(
                    list(value.get("provisional") or [])[-2:],
                    fields=(
                        "evidence_id",
                        "type",
                        "price",
                        "pivot_time",
                        "status",
                        "price_basis",
                    ),
                    limit=2,
                ),
            }
        )
    elif capability_id == "technical.fibonacci":
        common.update(
            {
                **_summary_dict(
                    value,
                    fields=(
                        "direction",
                        "anchor_ids",
                        "anchor_start_id",
                        "anchor_end_id",
                        "confluence_method",
                    ),
                ),
                "anchor_start": _summary_dict(
                    value.get("anchor_start"),
                    fields=("evidence_id", "type", "price", "pivot_time", "confirmed_at"),
                ),
                "anchor_end": _summary_dict(
                    value.get("anchor_end"),
                    fields=("evidence_id", "type", "price", "pivot_time", "confirmed_at"),
                ),
                "levels": _summary_rows(
                    value.get("levels"),
                    fields=("kind", "ratio", "price", "price_basis"),
                    limit=8,
                ),
            }
        )
    elif capability_id == "technical.divergence":
        common.update(
            {
                **_summary_dict(value, fields=("hidden_divergence_enabled",)),
                "divergences": _summary_rows(
                    value.get("divergences"),
                    fields=(
                        "type",
                        "direction",
                        "first_pivot_id",
                        "second_pivot_id",
                        "price_change_pct",
                        "indicator",
                        "indicator_change",
                        "bars_apart",
                        "status",
                    ),
                    limit=4,
                ),
            }
        )
    elif capability_id == "technical.breakout":
        common.update(
            _summary_dict(
                value,
                fields=(
                    "state",
                    "quality",
                    "level",
                    "level_evidence",
                    "bar_time",
                    "high",
                    "low",
                    "close",
                    "close_distance_pct",
                    "wick_rejected",
                    "volume_ratio",
                    "pvo",
                    "previously_confirmed",
                    "suppressed",
                ),
            )
        )
    elif capability_id == "technical.volume_profile":
        common.update(
            {
                **_summary_dict(
                    value,
                    fields=(
                        "lookback_bars",
                        "source_row_count",
                        "poc",
                        "val",
                        "vah",
                        "value_area_pct",
                    ),
                ),
                "high_volume_nodes": _summary_rows(
                    value.get("high_volume_nodes"),
                    fields=("index", "low", "high", "mid", "volume", "volume_pct", "in_value_area"),
                    limit=3,
                ),
                "bins_included": 0,
            }
        )
    elif capability_id == "technical.anchored_vwap":
        common.update(
            _summary_dict(
                value,
                fields=(
                    "anchor_evidence_id",
                    "anchor_time",
                    "anchor_price",
                    "value",
                    "cumulative_volume",
                    "used_bars",
                ),
            )
        )
    elif capability_id == "technical.relative_strength":
        common.update(
            _summary_dict(
                value,
                fields=(
                    "benchmark",
                    "aligned_trade_date_count",
                    "stock_latest_date",
                    "benchmark_latest_date",
                    "horizons",
                    "sector",
                    "freshness",
                ),
            )
        )
    return {**common, "projection_level": "summary"}


def _brief_capability_summary(
    capability_id: str,
    value: Any,
    *,
    minimum_rows: int | None = None,
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
        neutral_quote = _dict(value.get("quote"))
        return {
            **_summary_dict(
                value,
                fields=(
                    "kind",
                    "schema_version",
                    "compatibility_schema_versions",
                    "status",
                    "selected_provider",
                    "selected_source",
                    "selected_event_at",
                    "fallback_used",
                    "selection_reason",
                    "facts_usable",
                    "research_usable",
                    "limitations",
                    "price",
                    "latest_price",
                    "last_price",
                    "price_available",
                    "last_trade_available",
                    "last_trade_price",
                    "last_trade_time",
                    "last_trade_is_current_session",
                    "last_trade_before_auction",
                    "facts_usable_for_current_session",
                    "fallback_quote",
                    "fallback_used",
                    "previous_close",
                    "market_phase",
                    "capability_expectation",
                    "source_status",
                    "provider_snapshot_freshness",
                    "trade_recency",
                    "trade_state",
                    "change_reference_price",
                    "change_reference_type",
                    "change_reference_trade_date",
                    "change_reference_source",
                    "open_price",
                    "high_price",
                    "low_price",
                    "change",
                    "change_pct",
                    "currency",
                    "volume",
                    "volume_unit",
                    "volume_semantics",
                    "volume_status",
                    "canonical_volume_unit",
                    "provider_volume_unit",
                    "total_volume_lots",
                    "total_volume_contracts",
                    "cumulative_volume_lots",
                    "cumulative_volume_shares",
                    "lot_size",
                    "volume_scope",
                    "volume_source",
                    "official_daily_volume_scope",
                    "volume_reconciliation",
                    "volume_decision_usable",
                    "price_decision_usable",
                    "trade_value",
                    "trade_value_unit",
                    "trade_value_status",
                    "trade_value_source",
                    "trade_date",
                    "quote_time",
                    "quote_time_basis",
                    "snapshot_time",
                    "snapshot_time_basis",
                    "provider_event_time",
                    "event_time",
                    "release_at",
                    "fetched_at",
                    "computed_at",
                    "received_at",
                    "served_at",
                    "event_age_seconds",
                    "provider_delay_ms",
                    "network_latency_ms",
                    "provider",
                    "source",
                    "market_status",
                    "session_phase",
                    "quote_semantics",
                    "is_historical",
                    "requested_trade_date",
                    "regular_session_close",
                    "regular_session_close_time",
                    "regular_session_close_trade_date",
                    "timezone",
                    "is_live",
                    "is_realtime",
                    "depth_available",
                    "depth_status",
                    "auction_book_available",
                    "auction_book_status",
                    "auction_book_time",
                    "auction_best_bid",
                    "auction_best_ask",
                    "top5_bid_volume_lots",
                    "top5_ask_volume_lots",
                    "top5_imbalance",
                    "depth_volume_unit",
                    "depth_order_count_status",
                    "auction_indicative_available",
                    "indicative_match_available",
                    "indicative_match_price",
                    "indicative_match_volume_lots",
                    "indicative_unmatched_buy_volume_lots",
                    "indicative_unmatched_sell_volume_lots",
                    "indicative_unmatched_status",
                    "indicative_price_available",
                    "indicative_price",
                    "indicative_bid",
                    "indicative_ask",
                    "official_close_available",
                    "official_close_status",
                    "official_close_price",
                    "official_close_trade_date",
                    "official_close_source",
                    "official_close_raw",
                    "official_close_display",
                    "official_close_precision",
                    "official_vwap",
                    "approx_vwap",
                    "vwap_method",
                    "vwap_confidence",
                    "selected_candidate",
                    "selection_reason",
                ),
            ),
            **(
                {
                    "quote": _summary_dict(
                        neutral_quote,
                        fields=(
                            "market",
                            "symbol",
                            "venue",
                            "instrument_type",
                            "trade_date",
                            "currency",
                            "state",
                            "trade_state",
                            "last_trade_price",
                            "open_price",
                            "high_price",
                            "low_price",
                            "previous_close",
                            "event_at",
                            "received_at",
                            "fetched_at",
                        ),
                    )
                }
                if neutral_quote
                else {}
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
        def point_time(point: dict[str, Any]) -> datetime:
            for key in ("bar_time", "event_time", "time", "date", "trade_date"):
                raw_value = point.get(key)
                if isinstance(raw_value, datetime):
                    parsed = raw_value
                else:
                    text = str(raw_value or "").strip()
                    if not text:
                        continue
                    try:
                        parsed = datetime.fromisoformat(
                            text.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            return datetime.min.replace(tzinfo=timezone.utc)

        latest_point = (
            max(
                (row for row in rows if isinstance(row, dict)),
                key=point_time,
                default={},
            )
            if rows
            else value.get("latest_point")
            if isinstance(value.get("latest_point"), dict)
            else {}
        )
        latest_event_time = next(
            (
                latest_point.get(key)
                for key in ("bar_time", "event_time", "time", "date", "trade_date")
                if latest_point.get(key) is not None
            ),
            None,
        )
        return {
            **_summary_dict(
                value,
                fields=(
                    "kind",
                    "schema_version",
                    "compatibility_schema_versions",
                    "selected_provider",
                    "selected_source",
                    "selected_event_at",
                    "selection_reason",
                    "facts_usable",
                    "research_usable",
                    "limitations",
                    "available_bar_count",
                    "as_of",
                    "latest_data_date",
                    "expected_data_date",
                    "interval",
                    "requested_interval",
                    "source_interval",
                    "effective_interval",
                    "interval_status",
                    "sampling_mode",
                    "original_point_count",
                    "session",
                    "session_phase",
                    "market_phase",
                    "capability_expectation",
                    "current_source_status",
                    "bar_source_status",
                    "source_status",
                    "current_session_expected",
                    "current_session_satisfied",
                    "expected_trade_date",
                    "event_trade_date",
                    "provider_snapshot_freshness",
                    "trade_recency",
                    "trade_state",
                    "change_reference_price",
                    "change_reference_type",
                    "change_reference_trade_date",
                    "change_reference_source",
                    "market_status",
                    "official_close_status",
                    "delivery_status",
                    "point_count",
                    "returned_point_count",
                    "truncated",
                    "bar_limit",
                    "volume_unit",
                    "volume_contracts",
                    "volume_event_time",
                    "volume_semantics",
                    "volume_status",
                    "trade_value_unit",
                    "currency",
                    "event_time",
                    "provider",
                    "source",
                    "continuity",
                    "aggregation_method",
                    "source_point_count",
                    "aggregated_point_count",
                    "partial_bar_count",
                    "cache_status",
                    "cache_hit",
                    "cache_trade_date",
                    "cache_latest_time",
                    "fallback_used",
                ),
            ),
            "latest_point": _summary_dict(
                latest_point,
                fields=(
                    "date",
                    "trade_date",
                    "time",
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
                    "volume_contracts",
                    "base_volume",
                    "quote_volume",
                    "volume_unit",
                    "base_volume_unit",
                    "quote_volume_unit",
                    "volume_semantics",
                ),
            ),
            "event_time": latest_event_time or value.get("event_time"),
            "points_included": 0,
            "projection_level": "summary",
        }
    if capability_id == "technical.structure":
        analysis = _dict(value.get("analysis"))
        levels = _dict(value.get("levels"))
        advanced = _dict(value.get("advanced_shadow"))
        return {
            **_summary_dict(
                value,
                fields=(
                    "kind",
                    "schema_version",
                    "algorithm_version",
                    "market",
                    "symbol",
                    "timeframe",
                    "status",
                    "contract_version",
                    "as_of",
                    "trade_date",
                    "latest_price",
                    "current_price",
                    "trend",
                    "momentum",
                    "provider",
                    "source",
                    "selected_title",
                    "trend_state",
                    "breakout_state",
                    "current_state",
                    "metrics",
                    "invalidation",
                    "counter_evidence",
                    "limitations",
                    "quality",
                    "input_quality",
                    "lineage",
                ),
            ),
            "analysis": _summary_dict(
                analysis,
                fields=(
                    "requested_horizon",
                    "effective_horizon",
                    "selected_horizon",
                    "selected_timeframe",
                    "selected_score",
                    "selected_title",
                    "composite_score_title",
                    "selected_summary",
                    "selected_confidence",
                    "today_state",
                    "historical_structure",
                    "composite_state",
                    "fallback_reason",
                ),
            ),
            "levels": {
                key: deepcopy(levels[key])
                for key in (
                    "latest_price",
                    "basis_timeframe",
                    "technical_price_basis",
                    "bid_ask_price_used",
                    "entry",
                    "risk",
                )
                if key in levels
            },
            "advanced_shadow": {
                **_summary_dict(
                    advanced,
                    fields=(
                        "version",
                        "algorithm_version",
                        "mode",
                        "active_score_impact",
                        "status",
                        "decision_usable",
                        "as_of",
                        "price_basis",
                        "decision_snapshot",
                        "momentum_confirmation",
                        "volatility_context",
                        "breakout_context",
                        "fibonacci_context",
                        "cost_context",
                        "relative_strength",
                        "levels",
                        "invalidation",
                        "counter_evidence",
                        "corporate_action",
                        "warnings",
                        "limitations",
                    ),
                ),
                "projection_level": "summary",
            }
            if advanced
            else None,
            "projection_level": "summary",
        }
    if capability_id == "technical.indicators":
        timeframes = _dict(value.get("timeframes"))
        summarized_timeframes: dict[str, Any] = {}
        for timeframe in ("daily", "weekly", "monthly"):
            snapshot = _dict(timeframes.get(timeframe))
            if not snapshot:
                continue
            summarized_timeframes[timeframe] = {
                **_summary_dict(
                    snapshot,
                    fields=(
                        "timeframe",
                        "period",
                        "decision_snapshot",
                        "available_bars",
                        "completed_bars",
                        "warmup",
                    ),
                ),
                "completed": _brief_technical_indicator_point(snapshot.get("completed")),
                "current_partial": _brief_technical_indicator_point(
                    snapshot.get("current_partial")
                ),
            }
        return {
            **_summary_dict(
                value,
                fields=(
                    "kind",
                    "schema_version",
                    "algorithm_version",
                    "status",
                    "stock_id",
                    "market",
                    "symbol",
                    "timeframe",
                    "as_of",
                    "bar_count",
                    "price_basis",
                    "currency",
                    "price_unit",
                    "methods",
                    "corporate_action",
                    "missing",
                    "warnings",
                    "source_refs",
                    "freshness",
                    "profile",
                    "warmup",
                    "period_completeness",
                    "current",
                    "quality",
                    "input_quality",
                    "lineage",
                ),
            ),
            "timeframes": summarized_timeframes,
            "projection_level": "summary",
        }
    if capability_id in {
        "technical.swings",
        "technical.fibonacci",
        "technical.divergence",
        "technical.breakout",
        "technical.volume_profile",
        "technical.anchored_vwap",
        "technical.relative_strength",
    }:
        return _brief_technical_advanced_summary(capability_id, value)
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
                    "quantity_unit",
                    "raw_unit",
                    "normalized_unit",
                    "normalized_quantities",
                    "lot_size",
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
    if capability_id == "screening.ranking":
        row_limit = max(5, int(minimum_rows or 0))
        rows = _summary_rows(
            value.get("rows"),
            fields=(
                "rank",
                "position",
                "stock_id",
                "stock_name",
                "market",
                "metric",
                "value",
                "unit",
                "observed_periods",
                "requested_periods",
                "window_complete",
            ),
            limit=row_limit,
        )
        return {
            **_summary_dict(
                value,
                fields=(
                    "snapshot_id",
                    "status",
                    "metric",
                    "unit",
                    "sort_order",
                    "tie_policy",
                    "window",
                    "require_complete_window",
                    "min_observed_periods",
                    "incomplete_window_policy",
                    "pagination",
                    "as_of",
                    "cache_policy",
                ),
            ),
            "rows": rows,
            "returned_count": len(rows),
            "projection_level": "summary",
        }
    if capability_id == "screening.coverage":
        return {
            **_summary_dict(
                value,
                fields=(
                    "snapshot_id",
                    "status",
                    "metric",
                    "dataset",
                    "requested_window_trade_days",
                    "available_window_trade_days",
                    "universe_count",
                    "covered_count",
                    "complete_window_count",
                    "incomplete_window_count",
                    "eligible_rank_count",
                    "excluded_incomplete_count",
                    "missing_count",
                    "coverage_ratio",
                    "coverage_status",
                    "as_of",
                    "cache_policy",
                ),
            ),
            "coverage_gaps": _list(value.get("coverage_gaps"))[:3],
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


def _required_row_requirement(
    capability_id: str,
    value: Any,
    *,
    selection: dict[str, Any],
) -> int:
    if capability_id != "screening.ranking" or not isinstance(value, dict):
        return 0
    rows = value.get("rows")
    if not isinstance(rows, list):
        return 0
    parameters = _dict(selection.get("parameters"))
    ranking_parameters = _dict(parameters.get("screening.ranking"))
    requested_limit = ranking_parameters.get("limit")
    if not isinstance(requested_limit, int) or isinstance(requested_limit, bool):
        pagination = _dict(value.get("pagination"))
        requested_limit = pagination.get("returned_count")
        if not isinstance(requested_limit, int) or isinstance(requested_limit, bool):
            requested_limit = pagination.get("limit")
    if not isinstance(requested_limit, int) or isinstance(requested_limit, bool):
        requested_limit = len(rows)
    return min(len(rows), max(0, requested_limit))


def _apply_response_budget_error(
    envelope: dict[str, Any],
    *,
    projection: dict[str, Any],
    minimum_required_bytes: int,
    max_bytes: int,
) -> None:
    target = _brief_capability_summary(
        "target.identity",
        _dict(envelope.get("target")),
    )
    question = str(envelope.get("question") or "")
    mode = _dict(envelope.get("mode"))
    compatibility = _dict(envelope.get("compatibility"))
    required = [
        str(value)
        for value in _list(
            _dict(_dict(envelope.get("execution")).get("selection")).get(
                "required"
            )
        )
        if str(value).strip()
    ]
    projection.update(
        {
            "truncated": True,
            "required_payload_preserved": False,
            "minimum_required_bytes": minimum_required_bytes,
            "omitted_capabilities": list(
                dict.fromkeys(
                    [
                        *projection.get("omitted_capabilities", []),
                        *required,
                    ]
                )
            ),
        }
    )
    envelope.clear()
    envelope.update(
        {
            "kind": KIND,
            "contract_version": CONTRACT_VERSION,
            "ok": False,
            "transport_ok": True,
            "request_valid": True,
            "execution_completed": False,
            "data_available": False,
            "quality_status": "blocked",
            "request_status": "rejected",
            "question": question,
            "target": target,
            "mode": mode,
            "action": "omi.ask",
            "caller_profile": "unknown",
            "status": {
                "readiness": {
                    "response_ready": True,
                    "facts_ready": False,
                    "analysis_ready": False,
                    "decision_ready": False,
                    "answer_ready": False,
                    "evidence_status": "blocked",
                    "blocked_sections": ["evidence"],
                }
            },
            "answer": {},
            "decision": {},
            "evidence": {
                "data": {},
                "capability_status": {},
                "quality": {
                    "version": data_quality_contract.QUALITY_VERSION,
                    "status": "blocked",
                    "facts_ready": False,
                    "blocked_required_capabilities": required,
                },
            },
            "limitations": {
                "missing": [
                    f"capability:{capability_id}"
                    for capability_id in required
                ],
                "warnings": [
                    "The selected response budget cannot preserve the minimum "
                    "required capability payload."
                ],
            },
            "execution": {
                "selection": {
                    "required": required,
                    "max_response_bytes": max_bytes,
                    "requested_max_response_bytes": projection.get(
                        "requested_max_response_bytes"
                    ),
                    "default_max_response_bytes": projection.get(
                        "default_max_response_bytes"
                    ),
                    "effective_max_response_bytes": projection.get(
                        "effective_max_response_bytes"
                    ),
                    "max_response_ceiling_bytes": projection.get(
                        "max_response_ceiling_bytes"
                    ),
                    "response_budget_source": projection.get(
                        "response_budget_source"
                    ),
                }
            },
            "continuation": {},
            "error": {
                "code": "RESPONSE_BUDGET_TOO_SMALL",
                "message": (
                    "max_response_bytes is too small to preserve the minimum "
                    "required capability payload."
                ),
                "minimum_required_bytes": minimum_required_bytes,
                "max_response_bytes": max_bytes,
                "retryable": True,
            },
            "compatibility": compatibility,
            "projection": projection,
        }
    )


def _compact_to_required_core(
    envelope: dict[str, Any],
    *,
    required_core: dict[str, Any],
    required: list[str],
    max_bytes: int,
) -> None:
    # Per-capability schema versions remain available from the public manifest.
    # Under a tight response budget they are metadata and must yield before any
    # required capability payload.
    envelope.pop("capability_schema_versions", None)
    mode = _dict(envelope.get("mode"))
    if mode.get("output_override_reason") is None:
        mode.pop("output_override_reason", None)
    mode.pop("requested", None)
    envelope["mode"] = mode
    evidence = _dict(envelope.get("evidence"))
    required_set = set(required)
    quality = _dict(evidence.get("quality"))
    quality_capabilities = _dict(quality.get("capabilities"))
    compact_quality = {
        key: deepcopy(quality[key])
        for key in (
            "version",
            "status",
            "trust_level",
            "facts_ready",
            "analysis_ready",
            "decision_ready",
            "blocked_required_capabilities",
            "limited_required_capabilities",
        )
        if key in quality
    }
    compact_quality["capabilities"] = {
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
        for capability_id, item in quality_capabilities.items()
        if capability_id in required_set and isinstance(item, dict)
    }
    manifest = _dict(evidence.get("manifest"))
    compact_manifest = {
        "version": manifest.get("version"),
        "capabilities": [
            {
                **{
                    key: deepcopy(item[key])
                    for key in (
                        "capability",
                        "required",
                        "status",
                        "status_class",
                        "payload_included",
                        "canonical_status_ref",
                    )
                    if key in item
                },
                **(
                    {
                        key: deepcopy(item[key])
                        for key in (
                            "refresh_recommended",
                            "refresh_strategy",
                            "fill_operation",
                            "refresh_possible_now",
                            "refresh_requires_market_open",
                            "writes_market_cache",
                        )
                        if key in item
                    }
                    if item.get("refresh_strategy")
                    in {"reader_fetch", "granular_tool"}
                    else {}
                ),
            }
            for item in _list(manifest.get("capabilities"))
            if isinstance(item, dict)
            and str(item.get("capability") or "") in required_set
        ],
    }
    compact_status = _compact_capability_status(
        {
            capability_id: item
            for capability_id, item in _dict(
                evidence.get("capability_status")
            ).items()
            if capability_id in required_set
        }
    )
    compact_freshness = {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "status",
                "dataset",
                "latest",
                "is_current",
                "current_for_requested_session",
                "is_complete",
                "release_status",
                "coverage_status",
                "oldest_as_of",
                "newest_as_of",
                "mixed_as_of",
                "refresh_recommended",
                "canonical_status_ref",
            )
            if key in item
        }
        for capability_id, item in _dict(
            evidence.get("freshness_by_capability")
        ).items()
        if capability_id in required_set and isinstance(item, dict)
    }
    compact_status_dimensions = deepcopy(
        _dict(evidence.get("status_dimensions"))
    )
    evidence.clear()
    evidence.update(
        {
            "data": deepcopy(required_core),
            "capability_status": compact_status,
            "quality": compact_quality,
            "status_dimensions": compact_status_dimensions,
            "manifest": compact_manifest,
            "freshness_by_capability": compact_freshness,
            "source_refs": [],
            "slots": {},
            "realtime": {},
        }
    )
    execution = _dict(envelope.get("execution"))
    selection_contract = _dict(execution.get("selection"))
    query_plan_contract = _dict(execution.get("query_plan"))
    reconciliation = _dict(execution.get("refresh_reconciliation"))
    reconciliation_capabilities = _dict(
        reconciliation.get("capabilities")
    )
    envelope["execution"] = {
        "selection": {
            key: deepcopy(selection_contract[key])
            for key in (
                "version",
                "required",
                "optional",
                "unsupported_capabilities",
                "output",
                "realtime_policy",
                "max_response_bytes",
                "requested_max_response_bytes",
                "default_max_response_bytes",
                "effective_max_response_bytes",
                "max_response_ceiling_bytes",
                "response_budget_source",
            )
            if key in selection_contract
        },
        "query_plan": {
            key: deepcopy(query_plan_contract[key])
            for key in (
                "reader_profile",
                "target_type",
                "question_intent",
                "question_intents",
                "requested_domains",
                "excluded_domains",
            )
            if key in query_plan_contract
        },
        "capability_catalog_version": execution.get(
            "capability_catalog_version"
        ),
        "public_contract_digest": execution.get("public_contract_digest"),
        "tool_runs": [
            {
                key: deepcopy(run[key])
                for key in (
                    "tool",
                    "provider",
                    "status",
                    "transport_status",
                    "operation_status",
                    "evidence_status",
                    "result_status",
                    "duration_ms",
                    "error",
                    "retryable",
                )
                if key in run
            }
            for run in _list(execution.get("tool_runs"))[:4]
            if isinstance(run, dict)
        ],
        "refresh_reconciliation": {
            key: deepcopy(reconciliation[key])
            for key in (
                "version",
                "attempted",
                "tool_run_attempted",
                "primary_reader_attempted",
                "provider_fetch_requested",
                "provider_fetch_attempted",
                "cache_hit",
                "refresh_requested",
                "refresh_allowed",
                "request_policy_observed",
                "not_attempted_reason",
                "attempt_count",
                "remaining_action_count",
                "remaining_action_ids",
            )
            if key in reconciliation
        },
    }
    envelope["execution"]["refresh_reconciliation"]["capabilities"] = {
        capability_id: {
            key: deepcopy(item[key])
            for key in (
                "attempted",
                "tool_run_attempted",
                "primary_reader_attempted",
                "provider_fetch_requested",
                "provider_fetch_attempted",
                "cache_hit",
                "refresh_requested",
                "refresh_allowed",
                "not_attempted_reason",
                "tool_succeeded",
                "tool_statuses",
                "refresh_outcomes",
                "final_status",
                "final_status_class",
                "payload_included",
                "usable_evidence_available",
                "reconciliation",
                "remaining_fill_action",
                "remaining_fill_action_detail",
            )
            if key in item
        }
        for capability_id, item in reconciliation_capabilities.items()
        if (
            capability_id in required_set
            and isinstance(item, dict)
            and (
                item.get("attempted") is True
                or item.get("primary_reader_attempted") is True
                or item.get("remaining_fill_action")
            )
        )
    }
    if not envelope["execution"]["tool_runs"]:
        envelope["execution"].pop("tool_runs", None)
    compact_reconciliation = envelope["execution"]["refresh_reconciliation"]
    if not (
        compact_reconciliation.get("attempted")
        or compact_reconciliation.get("remaining_action_count")
        or compact_reconciliation.get("capabilities")
    ):
        envelope["execution"].pop("refresh_reconciliation", None)
    continuation = _dict(envelope.get("continuation"))
    fill_plan = _dict(continuation.get("fill_plan"))
    original_actions = [
        action
        for action in _list(fill_plan.get("actions"))
        if isinstance(action, dict)
        and str(action.get("capability") or "") in required_set
    ][:4]
    compact_actions = [
        {
            key: deepcopy(action[key])
            for key in (
                "action_id",
                "capability",
                "operation",
                "refresh_strategy",
                "status",
                "executable",
                "required",
                "reason",
                "estimated_calls",
                "estimated_timeout_seconds",
                "refresh_possible_now",
                "refresh_requires_market_open",
                "writes_cache",
            )
            if key in action
        }
        for action in original_actions
    ]
    compact_fill_plan = {
        "version": fill_plan.get("version"),
        "plan_id": fill_plan.get("plan_id"),
        "actions": compact_actions,
        "jobs": _compact_fill_jobs(fill_plan, limit=4),
        "deferred_actions": [
            {
                key: deepcopy(action[key])
                for key in (
                    "capability",
                    "status",
                    "reason",
                    "refresh_strategy",
                    "refresh_possible_now",
                    "refresh_requires_market_open",
                    "writes_market_cache",
                    "release_status",
                    "next_eligible_refresh_at",
                )
                if key in action
            }
            for action in _list(fill_plan.get("deferred_actions"))[:4]
            if isinstance(action, dict)
            and str(action.get("capability") or "") in required_set
            and action.get("refresh_strategy")
            in {"reader_fetch", "granular_tool"}
        ],
        "already_attempted_actions": _compact_already_attempted_actions(
            fill_plan,
            limit=4,
            required=required_set,
        ),
        "partition": _compact_fill_partition(fill_plan),
        "action_count": fill_plan.get("action_count", len(compact_actions)),
        "auto_executed": fill_plan.get("auto_executed", False),
        "projection_truncated": True,
    }
    envelope["continuation"] = (
        {"fill_plan": compact_fill_plan}
        if (
            compact_actions
            or compact_fill_plan["deferred_actions"]
            or compact_fill_plan["already_attempted_actions"]
        )
        else {}
    )
    limitations = _dict(envelope.get("limitations"))
    envelope["limitations"] = {
        "missing": _list(limitations.get("missing"))[:4],
        "warnings": _list(limitations.get("warnings"))[:4],
        "current_request_failures": deepcopy(
            _list(limitations.get("current_request_failures"))[:4]
        ),
    }
    if not envelope["limitations"]["current_request_failures"]:
        envelope["limitations"].pop("current_request_failures", None)
    for index, action in enumerate(original_actions):
        invoke = action.get("invoke")
        if not isinstance(invoke, dict):
            continue
        compact_actions[index]["invoke"] = deepcopy(invoke)
        if _json_bytes(envelope) > max_bytes:
            compact_actions[index].pop("invoke", None)


def _fit_budget(
    envelope: dict[str, Any],
    *,
    selection: dict[str, Any],
) -> dict[str, Any]:
    budget_source = str(
        selection.get("response_budget_source")
        or (
            "caller_explicit"
            if selection.get("requested_max_response_bytes") is not None
            else "payload_default_adaptive"
        )
    )
    requested_max_bytes = selection.get("requested_max_response_bytes")
    default_max_bytes = int(
        selection.get("default_max_response_bytes")
        or selection.get("max_response_bytes")
        or 32_768
    )
    max_bytes = int(
        selection.get("effective_max_response_bytes")
        or selection.get("max_response_bytes")
        or default_max_bytes
    )
    ceiling_bytes = int(
        selection.get("max_response_ceiling_bytes")
        or max_bytes
    )
    pre_projection_bytes = _json_bytes(envelope)
    projection = {
        "version": "omi.response.projection.v1",
        "max_response_bytes": max_bytes,
        "requested_max_response_bytes": requested_max_bytes,
        "default_max_response_bytes": default_max_bytes,
        "effective_max_response_bytes": max_bytes,
        "max_response_ceiling_bytes": ceiling_bytes,
        "response_budget_source": budget_source,
        "adaptation_reason": None,
        "serialized_size_basis": "final_envelope_utf8_json",
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
    initial_projected_bytes = _json_bytes(envelope)

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
    required_row_requirements = {
        capability_id: _required_row_requirement(
            capability_id,
            data.get(capability_id),
            selection=selection,
        )
        for capability_id in required
    }
    required_core = {
        capability_id: _brief_capability_summary(
            capability_id,
            data[capability_id],
            minimum_rows=required_row_requirements.get(capability_id),
        )
        for capability_id in required
        if capability_id in data
    }
    minimum_candidate = deepcopy(envelope)
    _compact_to_required_core(
        minimum_candidate,
        required_core=required_core,
        required=required,
        max_bytes=ceiling_bytes,
    )
    minimum_required_envelope_bytes = _json_bytes(minimum_candidate)
    if (
        budget_source == "payload_default_adaptive"
        and minimum_required_envelope_bytes > default_max_bytes
    ):
        rounded_required_bytes = (
            (minimum_required_envelope_bytes + 4_095) // 4_096
        ) * 4_096
        max_bytes = min(
            ceiling_bytes,
            max(default_max_bytes, rounded_required_bytes),
        )
        if max_bytes > default_max_bytes:
            projection["adaptation_reason"] = (
                "minimum_required_envelope_exceeds_payload_default"
            )
    elif (
        budget_source == "payload_default_adaptive"
        and initial_projected_bytes > default_max_bytes
    ):
        # Absorb bounded final-envelope/provenance overhead near the payload
        # default.  Large optional payloads still use the existing trimming
        # path instead of silently expanding to the ceiling.
        max_bytes = min(
            ceiling_bytes,
            default_max_bytes + 8_192,
        )
        if max_bytes > default_max_bytes:
            projection["adaptation_reason"] = (
                "bounded_final_envelope_overhead"
            )
    execution = _dict(envelope.get("execution"))
    selection_contract = _dict(execution.get("selection"))
    selection_contract.update(
        {
            "max_response_bytes": max_bytes,
            "requested_max_response_bytes": requested_max_bytes,
            "default_max_response_bytes": default_max_bytes,
            "effective_max_response_bytes": max_bytes,
            "max_response_ceiling_bytes": ceiling_bytes,
            "response_budget_source": budget_source,
        }
    )
    execution["selection"] = selection_contract
    envelope["execution"] = execution
    projection.update(
        {
            "max_response_bytes": max_bytes,
            "effective_max_response_bytes": max_bytes,
            "minimum_required_envelope_bytes": (
                minimum_required_envelope_bytes
            ),
        }
    )
    core_payload_bytes = _json_bytes(
        {
            "target": _brief_capability_summary(
                "target.identity",
                _dict(envelope.get("target")),
            ),
            "data": required_core,
        }
    )
    projection.update(
        {
            "required_payload_preserved": True,
            "minimum_required_bytes": core_payload_bytes,
            "core_payload_bytes": core_payload_bytes,
            "envelope_bytes": pre_projection_bytes,
        }
    )
    optional_removal_order = [
        capability_id
        for capability_id in reversed(optional)
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
                minimum_rows=(
                    required_row_requirements.get(capability_id)
                    if capability_id in required
                    else None
                ),
            )
            if (
                summary_value == value
                or _json_bytes(summary_value) >= _json_bytes(value)
            ):
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
        evidence["capability_status"] = _compact_capability_status(
            _dict(evidence.get("capability_status"))
        )
        allowed_slots = _selected_slot_names(selection)
        slots = _dict(evidence.get("slots"))
        evidence["slots"] = {
            key: value for key, value in slots.items() if key in allowed_slots
        }
        evidence["source_refs"] = _list(evidence.get("source_refs"))[:12]
        mark_field("execution.tool_runs[].result_summary")
        mark_field("execution.diagnostics")
        mark_field("evidence.quality.capabilities.*.detail")
        mark_field("evidence.capability_status.*.detail")
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
        if "summary" in answer:
            answer["summary"] = _list(answer.get("summary"))[:3]
        decision = _dict(envelope.get("decision"))
        for key in (
            "action_plan",
            "scenarios",
            "counter_evidence",
            "risks",
            "data_limits",
        ):
            if key not in decision:
                continue
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
            "snapshot_age_seconds",
            "snapshot_is_stale",
            "snapshot_lifecycle",
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
            source_health["problems_preview"] = [
                {
                    key: (
                        str(entry[key])[:240]
                        if key == "reason" and entry.get(key) is not None
                        else deepcopy(entry[key])
                    )
                    for key in compact_entry_fields
                    if key in entry
                }
                for entry in ordered_entries[:5]
                if str(entry.get("status") or "") in problem_statuses
            ]
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
        query_plan_contract = _dict(execution.get("query_plan"))
        reconciliation = _dict(execution.get("refresh_reconciliation"))
        envelope["execution"] = {
            "selection": {
                key: deepcopy(selection_contract[key])
                for key in (
                    "version",
                    "required",
                    "optional",
                    "unsupported_capabilities",
                    "output",
                    "requested_output",
                    "effective_output",
                    "output_override_reason",
                    "realtime_policy",
                    "limits",
                    "requested_limits",
                    "capability_origins",
                    "inference_policy",
                    "max_response_bytes",
                    "requested_max_response_bytes",
                    "default_max_response_bytes",
                    "effective_max_response_bytes",
                    "max_response_ceiling_bytes",
                    "response_budget_source",
                )
                if key in selection_contract
            },
            "query_plan": {
                key: deepcopy(query_plan_contract[key])
                for key in (
                    "reader_profile",
                    "target_type",
                    "question_intent",
                    "question_intents",
                    "requested_domains",
                    "excluded_domains",
                )
                if key in query_plan_contract
            },
            "capability_catalog_version": execution.get(
                "capability_catalog_version"
            ),
            "refresh_reconciliation": {
                key: deepcopy(reconciliation[key])
                for key in (
                    "version",
                    "attempted",
                    "tool_run_attempted",
                    "primary_reader_attempted",
                    "provider_fetch_requested",
                    "provider_fetch_attempted",
                    "cache_hit",
                    "refresh_requested",
                    "refresh_allowed",
                    "request_policy_observed",
                    "not_attempted_reason",
                    "attempt_count",
                    "remaining_action_count",
                    "remaining_action_ids",
                )
                if key in reconciliation
            },
        }
        mark_field("execution.query_plan.nonessential_fields")
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

    if _json_bytes(envelope) > max_bytes:
        _compact_to_required_core(
            envelope,
            required_core=required_core,
            required=required,
            max_bytes=max_bytes,
        )
        mark_field("response.required_core_projection")
        projection["trimmed_fields"] = list(
            dict.fromkeys(projection["trimmed_fields"])
        )[-4:]
        projection["trimmed_lists"] = {}
        projection["truncated"] = True

    if _json_bytes(envelope) > max_bytes:
        minimum_required_bytes = max(
            int(projection.get("minimum_required_bytes") or 0),
            _json_bytes(envelope),
        )
        _apply_response_budget_error(
            envelope,
            projection=projection,
            minimum_required_bytes=minimum_required_bytes,
            max_bytes=max_bytes,
        )
        if _json_bytes(envelope) > max_bytes:
            _hard_cap_envelope(envelope, max_bytes=max_bytes)
        projection = _dict(envelope.get("projection"))
        _finalize_projection(
            envelope,
            projection=projection,
            max_bytes=max_bytes,
        )
        projection["envelope_bytes"] = projection.get(
            "actual_response_bytes"
        )
        _finalize_projection(
            envelope,
            projection=projection,
            max_bytes=max_bytes,
        )
        return envelope

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
    projected_data = _dict(_dict(envelope.get("evidence")).get("data"))
    projection["required_payload_preserved"] = all(
        capability_id in projected_data
        and (
            required_row_requirements.get(capability_id, 0) <= 0
            or len(
                _list(
                    _dict(projected_data.get(capability_id)).get("rows")
                )
            )
            >= required_row_requirements[capability_id]
        )
        for capability_id in required
        if capability_id not in {"target.identity"}
    )
    projection["envelope_bytes"] = projection.get(
        "actual_response_bytes"
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
    rejected_status_dimensions = (
        data_quality_contract.status_dimensions_from_quality_contract(
            {
                "status": "blocked",
                "decision_ready": False,
                "blocked_required_capabilities": ["target.identity"],
                "issues": [{"code": "canonical_request_not_completed"}],
            }
        )
    )
    evidence["status_dimensions"] = rejected_status_dimensions
    evidence["passport"]["status_dimensions"] = deepcopy(
        rejected_status_dimensions
    )
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
        "query_plan": deepcopy(_dict(execution.get("query_plan"))),
        "capability_catalog_version": (
            public_contract.CAPABILITY_REGISTRY_VERSION
        ),
        "capability_schema_versions": {
            capability_id: capability_contract.CAPABILITIES[
                capability_id
            ].schema_version
            for capability_id in (
                *selection.get("required", []),
                *selection.get("optional", []),
            )
            if capability_id in capability_contract.CAPABILITIES
        },
        "public_contract_digest": (
            contract_manifest.public_contract_manifest()["digest"]
        ),
        "tool_runs": [],
    }
    canonical["transport_ok"] = True
    canonical["request_valid"] = False
    canonical["execution_completed"] = False
    canonical["data_available"] = False
    canonical["quality_status"] = "blocked"
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
            "jobs": [],
            "deferred_actions": [],
            "unfillable_actions": [],
            "already_attempted_actions": [],
            "partition": {
                "version": "omi.fill.partition.v1",
                "selected_capabilities": [],
                "already_satisfied": [],
                "actions": [],
                "jobs": [],
                "deferred": [],
                "unfillable": [],
                "not_applicable": [],
                "complete": False,
                "reason": "canonical_request_not_completed",
            },
            "resolutions": [],
            "action_count": 0,
            "summary": {
                "executable_count": 0,
                "job_count": 0,
                "deferred_count": 0,
                "unfillable_count": 0,
                "already_attempted_count": 0,
                "unresolved_count": 0,
            },
            "auto_executed": False,
        },
    }
    limitations = _dict(canonical.get("limitations"))
    unsupported_capabilities = [
        deepcopy(item)
        for item in _list(selection.get("unsupported_capabilities"))
        if isinstance(item, dict)
    ]
    unmet_required_capabilities = [
        deepcopy(item)
        for item in _list(selection.get("unmet_required_capabilities"))
        if isinstance(item, dict)
    ]
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
        "current_request_failures": [],
        "background_source_health": [],
        "historical_provider_events": [],
        "unsupported_capabilities": unsupported_capabilities,
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
    _apply_selection_trace(canonical, selection=selection)
    unsupported_capabilities = [
        deepcopy(item)
        for item in _list(selection.get("unsupported_capabilities"))
        if isinstance(item, dict)
    ]
    unmet_required_capabilities = [
        deepcopy(item)
        for item in _list(selection.get("unmet_required_capabilities"))
        if isinstance(item, dict)
    ]
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
    if (
        isinstance(projected_data.get("data.freshness"), dict)
        and "data.freshness" in unavailable
    ):
        unavailable.remove("data.freshness")
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
    execution["capability_catalog_version"] = (
        public_contract.CAPABILITY_REGISTRY_VERSION
    )
    capability_schema_versions = {
        capability_id: capability_contract.CAPABILITIES[
            capability_id
        ].schema_version
        for capability_id in (
            *selection.get("required", []),
            *selection.get("optional", []),
        )
        if capability_id in capability_contract.CAPABILITIES
    }
    execution["capability_schema_versions"] = capability_schema_versions
    execution["public_contract_digest"] = (
        contract_manifest.public_contract_manifest()["digest"]
    )
    existing_tool_runs = [
        deepcopy(run)
        for run in _list(execution.get("tool_runs"))
        if isinstance(run, dict)
    ]
    internal_tool_runs = _selected_internal_tool_runs(
        response=projection_response,
        selection=selection,
    )
    execution["tool_runs"] = [
        *existing_tool_runs,
        *internal_tool_runs,
    ]
    canonical["execution"] = execution
    canonical["capability_schema_versions"] = capability_schema_versions
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
        if (
            selection.get("realtime_policy") == "require_live"
            and "live_requirement_not_satisfied" not in missing
        ):
            missing.append("live_requirement_not_satisfied")
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
    limitations["unsupported_capabilities"] = unsupported_capabilities
    limitations["unmet_required_capabilities"] = unmet_required_capabilities
    for item in unmet_required_capabilities:
        capability_id = str(item.get("capability") or "").strip()
        if not capability_id:
            continue
        marker = f"capability:{capability_id}"
        if marker not in limitations["missing"]:
            limitations["missing"].append(marker)
        warning = str(item.get("message") or "").strip()
        if warning and warning not in limitations["warnings"]:
            limitations["warnings"].append(warning)
    canonical["limitations"] = limitations
    _separate_supplemental_context_gaps(
        canonical,
        selection=selection,
    )
    canonical = data_quality_contract.apply_quality_contract(
        canonical,
        quality=quality,
    )
    canonical["transport_ok"] = True
    canonical["request_valid"] = True
    canonical["execution_completed"] = True
    canonical["data_available"] = bool(quality.get("facts_ready"))
    canonical["quality_status"] = str(
        quality.get("status") or "blocked"
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
            request_policy=_dict(execution.get("policy")),
        )
    )
    canonical["execution"] = execution
    continuation = _dict(canonical.get("continuation"))
    continuation["fill_plan"] = fill_plan
    canonical["continuation"] = continuation
    return _fit_budget(canonical, selection=selection)
