from __future__ import annotations

from typing import Any, Iterable


STATUS_CONTRACT_VERSION = "omi.status-dimensions.v1"

_QUALITY_ALIASES = {
    "available": "current",
    "complete": "current",
    "current": "current",
    "ok": "current",
    "ready": "current",
    "stale": "stale",
    "partial": "partial",
    "degraded": "partial",
    "pending": "pending",
    "pending_release": "pending",
    "empty": "missing",
    "missing": "missing",
    "unavailable": "missing",
    "error": "failed",
    "failed": "failed",
    "disabled": "not_applicable",
    "not_applicable": "not_applicable",
}
_QUALITY_SEVERITY = {
    "not_applicable": 0,
    "current": 1,
    "unknown": 2,
    "pending": 3,
    "partial": 4,
    "stale": 5,
    "missing": 6,
    "failed": 7,
}
_SERVICE_SEVERITY = {"available": 1, "degraded": 2, "unavailable": 3}
_READINESS_SEVERITY = {"not_applicable": 0, "ready": 1, "limited": 2, "blocked": 3}
_PROVIDER_SEVERITY = {
    "not_applicable": 0,
    "available": 1,
    "unknown": 2,
    "degraded": 3,
    "unavailable": 4,
}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _canonical_data_quality(entry: dict[str, Any]) -> str:
    raw = _normalized(entry.get("data_quality"))
    if raw in {"", "unknown"}:
        raw = _normalized(entry.get("status"))
    return _QUALITY_ALIASES.get(raw, "unknown")


def _provider_status(entry: dict[str, Any]) -> str:
    if entry.get("required") is False:
        return "not_applicable"
    dimensions = (
        entry.get("health_dimensions")
        if isinstance(entry.get("health_dimensions"), dict)
        else {}
    )
    provider = (
        dimensions.get("provider_availability")
        if isinstance(dimensions.get("provider_availability"), dict)
        else {}
    )
    raw = _normalized(provider.get("status") or entry.get("provider_status"))
    if raw in {"available", "current", "ok", "ready", "success"}:
        return "available"
    if raw in {"partial", "degraded", "stale", "fallback"}:
        return "degraded"
    if raw in {"unavailable", "failed", "error", "circuit_open", "blocked"}:
        return "unavailable"
    if raw in {"disabled", "not_applicable"}:
        return "not_applicable"
    return "unknown"


def build_status_dimensions(
    entry: dict[str, Any],
    *,
    service_completed: bool = True,
) -> dict[str, Any]:
    """Map independent service/data/decision/provider axes without conflation."""

    required = entry.get("required") is not False
    data_quality = _canonical_data_quality(entry)
    service_status = "available" if service_completed else "unavailable"
    if not required or data_quality == "not_applicable":
        decision_readiness = "not_applicable"
    elif data_quality == "current":
        decision_readiness = "ready"
    elif data_quality in {"unknown", "pending", "partial", "stale"}:
        decision_readiness = "limited"
    else:
        decision_readiness = "blocked"
    provider_status = _provider_status(entry)

    reason_codes: list[str] = []
    if service_status != "available":
        reason_codes.append("service_unavailable")
    if data_quality != "current" and data_quality != "not_applicable":
        reason_codes.append(f"data_{data_quality}")
    if decision_readiness == "limited":
        reason_codes.append("decision_limited")
    elif decision_readiness == "blocked":
        reason_codes.append("decision_blocked")
    if provider_status in {"degraded", "unavailable"}:
        reason_codes.append(f"provider_{provider_status}")

    health_dimensions = (
        entry.get("health_dimensions")
        if isinstance(entry.get("health_dimensions"), dict)
        else {}
    )
    repair = (
        health_dimensions.get("repair")
        if isinstance(health_dimensions.get("repair"), dict)
        else {}
    )
    repair_status = _normalized(repair.get("status"))
    if repair_status in {"repairing", "retry_wait", "detected", "outcome_mismatch"}:
        if decision_readiness == "ready":
            decision_readiness = "limited"
        reason_codes.append(f"repair_{repair_status}")
    elif repair_status == "exhausted":
        decision_readiness = "blocked"
        reason_codes.append("repair_exhausted")

    return {
        "version": STATUS_CONTRACT_VERSION,
        "status_authority": "backend_status_taxonomy",
        "service_status": service_status,
        "data_quality": data_quality,
        "decision_readiness": decision_readiness,
        "provider_status": provider_status,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


def _worst(
    values: Iterable[str],
    *,
    severity: dict[str, int],
    default: str,
) -> str:
    return max(values, key=lambda item: severity.get(item, 999), default=default)


def summarize_status_dimensions(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    contracts = [
        entry.get("status_dimensions")
        if isinstance(entry.get("status_dimensions"), dict)
        else build_status_dimensions(entry)
        for entry in entries
    ]
    if not contracts:
        return {
            "version": STATUS_CONTRACT_VERSION,
            "status_authority": "backend_status_taxonomy",
            "service_status": "unavailable",
            "data_quality": "unknown",
            "decision_readiness": "blocked",
            "provider_status": "unknown",
            "reason_codes": ["no_status_entries"],
        }
    return {
        "version": STATUS_CONTRACT_VERSION,
        "status_authority": "backend_status_taxonomy",
        "service_status": _worst(
            (str(item.get("service_status") or "unavailable") for item in contracts),
            severity=_SERVICE_SEVERITY,
            default="unavailable",
        ),
        "data_quality": _worst(
            (str(item.get("data_quality") or "unknown") for item in contracts),
            severity=_QUALITY_SEVERITY,
            default="unknown",
        ),
        "decision_readiness": _worst(
            (str(item.get("decision_readiness") or "blocked") for item in contracts),
            severity=_READINESS_SEVERITY,
            default="blocked",
        ),
        "provider_status": _worst(
            (str(item.get("provider_status") or "unknown") for item in contracts),
            severity=_PROVIDER_SEVERITY,
            default="unknown",
        ),
        "reason_codes": list(
            dict.fromkeys(
                str(reason)
                for item in contracts
                for reason in item.get("reason_codes") or []
                if str(reason).strip()
            )
        ),
    }


def status_dimensions_from_quality_contract(
    quality: dict[str, Any],
) -> dict[str, Any]:
    """Project AI quality evidence into the shared four-axis vocabulary."""

    quality_status = _normalized(quality.get("status"))
    data_quality = {
        "ready": "current",
        "partial": "partial",
        "blocked": "failed",
        "failed": "failed",
    }.get(quality_status, "unknown")
    if bool(quality.get("decision_ready")):
        decision_readiness = "ready"
    elif quality.get("blocked_required_capabilities"):
        decision_readiness = "blocked"
    else:
        decision_readiness = "limited"

    required_capabilities = [
        item
        for item in (
            quality.get("capabilities", {}).values()
            if isinstance(quality.get("capabilities"), dict)
            else []
        )
        if isinstance(item, dict) and item.get("required") is True
    ]
    provider_states: list[str] = []
    for item in required_capabilities:
        if not item.get("selected_provider"):
            continue
        if item.get("fallback_used"):
            provider_states.append("degraded")
        elif item.get("availability_status") in {"missing", "error", "failed"}:
            provider_states.append("unavailable")
        else:
            provider_states.append("available")
    provider_status = _worst(
        provider_states,
        severity=_PROVIDER_SEVERITY,
        default="unknown",
    )
    reason_codes = list(
        dict.fromkeys(
            str(issue.get("code"))
            for issue in quality.get("issues") or []
            if isinstance(issue, dict) and str(issue.get("code") or "").strip()
        )
    )
    return {
        "version": STATUS_CONTRACT_VERSION,
        "status_authority": "backend_status_taxonomy",
        "service_status": "available",
        "data_quality": data_quality,
        "decision_readiness": decision_readiness,
        "provider_status": provider_status,
        "reason_codes": reason_codes,
    }


__all__ = [
    "STATUS_CONTRACT_VERSION",
    "build_status_dimensions",
    "status_dimensions_from_quality_contract",
    "summarize_status_dimensions",
]
