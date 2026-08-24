from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from app import http_client
from app.config import settings


LOGGER = logging.getLogger(__name__)

ATLAS_CAPABILITY_ID = "news.events"
ATLAS_CONTEXT_SCHEMA_VERSION = "omi.external.news_events.v1"
ATLAS_CONTRACT_VERSION = "1.1"
ATLAS_PROFILE = "evidence_pack_v1"
SUPPORTED_SCOPES = frozenset({"stock", "us_stock", "market"})
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def shadow_enabled() -> bool:
    return bool(settings.omi_atlas_shadow_enabled)


def selection_with_atlas_shadow(
    selection: dict[str, Any] | None,
    *,
    scope_type: str,
) -> dict[str, Any]:
    """Add Atlas as an optional auto-planned capability without overriding callers."""
    raw = dict(selection) if isinstance(selection, dict) else {}
    if not shadow_enabled() or scope_type not in SUPPORTED_SCOPES:
        return raw

    excluded = _string_values(raw.get("exclude"))
    if ATLAS_CAPABILITY_ID in excluded:
        return raw

    has_explicit_selection = any(
        key in raw for key in ("required", "include", "optional")
    )
    if has_explicit_selection and raw.get("auto_planning") is not True:
        return raw

    selected = {
        *_string_values(raw.get("required") or raw.get("include")),
        *_string_values(raw.get("optional")),
    }
    if ATLAS_CAPABILITY_ID not in selected:
        raw["optional"] = [
            *_string_values(raw.get("optional")),
            ATLAS_CAPABILITY_ID,
        ]
    raw["auto_planning"] = True
    return raw


def atlas_selected(selection: dict[str, Any] | None) -> bool:
    if not isinstance(selection, dict):
        return False
    selected = {
        *_string_values(selection.get("required") or selection.get("include")),
        *_string_values(selection.get("optional")),
    }
    return ATLAS_CAPABILITY_ID in selected


def read_shadow_context(
    *,
    target: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = _utc_datetime(now)
    normalized_target = _bounded_target(target)
    query = _target_query(normalized_target)
    base = _base_payload(
        status="disabled" if not shadow_enabled() else "unavailable",
        target=normalized_target,
        query=query,
        generated_at=observed_at,
    )
    if not shadow_enabled():
        base.update(
            {
                "reason_code": "atlas_shadow_disabled",
                "missing": ["Atlas shadow context is disabled by server policy."],
            }
        )
        return base

    base_url = _validated_loopback_base_url(settings.omi_atlas_api_base_url)
    if base_url is None:
        base.update(
            {
                "reason_code": "atlas_base_url_not_loopback",
                "missing": [
                    "Atlas shadow context requires an explicit loopback HTTP base URL."
                ],
            }
        )
        return base

    params: dict[str, Any] = {
        "profile": ATLAS_PROFILE,
        "limit": int(settings.omi_atlas_max_events),
        "from": (
            observed_at - timedelta(hours=int(settings.omi_atlas_lookback_hours))
        ).isoformat().replace("+00:00", "Z"),
    }
    if query:
        params["q"] = query

    try:
        response = http_client.get(
            f"{base_url}/api/v1/brief",
            params=params,
            timeout=float(settings.omi_atlas_timeout_seconds),
        )
    except requests.Timeout:
        return _unavailable(base, "atlas_timeout")
    except requests.ConnectionError:
        return _unavailable(base, "atlas_connection_unavailable")
    except requests.RequestException:
        return _unavailable(base, "atlas_request_failed")
    except Exception:
        LOGGER.exception("Unexpected Atlas shadow read failure")
        return _unavailable(base, "atlas_unexpected_error")

    if response.status_code != 200:
        return _unavailable(base, f"atlas_http_{int(response.status_code)}")
    try:
        payload = response.json()
    except ValueError:
        return _incompatible(base, "atlas_invalid_json")
    if not isinstance(payload, dict):
        return _incompatible(base, "atlas_invalid_envelope")
    if str(payload.get("contract_version") or "") != ATLAS_CONTRACT_VERSION:
        return _incompatible(base, "atlas_contract_version_mismatch")
    if str(payload.get("profile") or "") != ATLAS_PROFILE:
        return _incompatible(base, "atlas_profile_mismatch")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_events = data.get("events") if isinstance(data.get("events"), list) else []
    max_events = int(settings.omi_atlas_max_events)
    events = [_project_event(item) for item in raw_events[:max_events] if isinstance(item, dict)]
    events = [event for event in events if event.get("id") or event.get("title")]
    source_refs = _source_refs(events)
    status = "available" if events else "ready_empty"
    base.update(
        {
            "status": status,
            "contract_version": ATLAS_CONTRACT_VERSION,
            "profile": ATLAS_PROFILE,
            "atlas_generated_at": _text(payload.get("generated_at"), 80),
            "event_count": _non_negative_int(data.get("event_count"), len(events)),
            "returned_count": len(events),
            "events": events,
            "freshness": _bounded_mapping(payload.get("freshness"), max_items=32),
            "coverage": _bounded_mapping(payload.get("coverage"), max_items=32),
            "warnings": _bounded_strings(payload.get("warnings"), limit=20, length=300),
            "source_refs": source_refs,
            "facts_usable": bool(events),
        }
    )
    if not events:
        base["missing"] = [
            "No Atlas events matched the bounded query window; absence is not evidence that no event occurred."
        ]
    return base


def attach_to_result(
    result: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Attach bounded Atlas evidence without changing OMI core missing/warning state."""
    data = result.get("data")
    if not isinstance(data, dict):
        data = {}
        result["data"] = data
    compact = data.get("compact")
    if not isinstance(compact, dict):
        compact = {}
        data["compact"] = compact
    slots = compact.get("slots")
    if not isinstance(slots, dict):
        slots = {}
        compact["slots"] = slots

    bounded = dict(context)
    data["atlas_context"] = bounded
    compact["atlas_context"] = bounded
    slots["news_events"] = {
        "capability": ATLAS_CAPABILITY_ID,
        "status": bounded.get("status") or "unavailable",
        "mode": "shadow",
        "payload_ref": "data.atlas_context",
        "payload_level": "compact",
        "as_of": bounded.get("atlas_generated_at") or bounded.get("generated_at"),
        "returned_count": bounded.get("returned_count", 0),
        "missing": list(bounded.get("missing") or []),
        "warnings": list(bounded.get("warnings") or []),
        "next_fill": (
            "Restore the local Atlas runtime or keep this supplemental context omitted."
            if bounded.get("status") in {"unavailable", "incompatible", "disabled"}
            else None
        ),
    }
    return result


def _base_payload(
    *,
    status: str,
    target: dict[str, Any],
    query: str | None,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "kind": "external_news_event_context",
        "schema_version": ATLAS_CONTEXT_SCHEMA_VERSION,
        "status": status,
        "mode": "shadow",
        "provider": "Open Intel Atlas",
        "contract_version": ATLAS_CONTRACT_VERSION,
        "profile": ATLAS_PROFILE,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "target": target,
        "query": query,
        "event_count": 0,
        "returned_count": 0,
        "events": [],
        "freshness": {},
        "coverage": {},
        "warnings": [],
        "missing": [],
        "source_refs": [],
        "facts_usable": False,
        "decision_usable": False,
        "absence_interpretation": "unknown_not_observed",
        "limitations": [
            "Shadow-only supplemental context; it does not alter OMI market facts, decision scores, or recommendations.",
            "Atlas owns event identity, attribution, deduplication, coverage, and freshness semantics.",
            "An empty result or unavailable Atlas runtime must not be interpreted as proof that no event occurred.",
        ],
    }


def _unavailable(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    output = dict(base)
    output.update(
        {
            "status": "unavailable",
            "reason_code": reason_code,
            "missing": [f"Atlas supplemental context is unavailable ({reason_code})."],
        }
    )
    return output


def _incompatible(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    output = dict(base)
    output.update(
        {
            "status": "incompatible",
            "reason_code": reason_code,
            "missing": [f"Atlas supplemental contract is incompatible ({reason_code})."],
        }
    )
    return output


def _validated_loopback_base_url(value: Any) -> str | None:
    text = str(value or "").strip().rstrip("/")
    try:
        parsed = urlparse(text)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOCAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or port is None
    ):
        return None
    return text


def _utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bounded_target(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        key: cleaned
        for key in ("type", "id", "symbol", "name", "label", "market")
        if (cleaned := _text(raw.get(key), 160)) is not None
    }


def _target_query(target: dict[str, Any]) -> str | None:
    if target.get("type") == "market":
        return None
    for key in ("label", "name", "symbol", "id"):
        value = _text(target.get(key), 120)
        if value:
            return value
    return None


def _project_event(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("evidence") if isinstance(event.get("evidence"), list) else []
    max_evidence = int(settings.omi_atlas_max_evidence_per_event)
    projected = {
        "id": _text(event.get("id"), 160),
        "title": _text(event.get("title"), 300),
        "summary": _text(event.get("summary"), 1200),
        "event_type": _text(event.get("event_type"), 120),
        "primary_domain": _text(
            event.get("primary_domain") or event.get("domain"), 120
        ),
        "lifecycle": _text(event.get("lifecycle"), 80),
        "severity": _text(event.get("severity"), 80),
        "confidence": _bounded_scalar(event.get("confidence")),
        "verification_status": _text(event.get("verification_status"), 100),
        "occurred_at": _text(event.get("occurred_at"), 80),
        "last_updated_at": _text(event.get("last_updated_at"), 80),
        "evidence_count": _non_negative_int(event.get("evidence_count"), len(evidence)),
        "independent_source_count": _non_negative_int(
            event.get("independent_source_count"), 0
        ),
        "has_primary_source": event.get("has_primary_source") is True,
        "has_official_source": event.get("has_official_source") is True,
        "representative_url": _safe_public_url(event.get("representative_url")),
        "domains": _bounded_records(
            event.get("domains"),
            fields=("domain", "confidence"),
            limit=12,
        ),
        "stories": _bounded_records(
            event.get("stories"),
            fields=("id", "story_id", "relationship", "confidence"),
            limit=12,
        ),
        "entities": _bounded_records(
            event.get("entities"),
            fields=("id", "entity_id", "name", "canonical_name", "type", "role", "confidence"),
            limit=20,
        ),
        "locations": _bounded_records(
            event.get("locations"),
            fields=("id", "name", "country", "region", "locality", "role", "confidence", "is_primary"),
            limit=12,
        ),
        "evidence": [
            _project_evidence(item)
            for item in evidence[:max_evidence]
            if isinstance(item, dict)
        ],
    }
    return {key: value for key, value in projected.items() if value not in (None, [], {})}


def _project_evidence(document: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "id": _text(document.get("id"), 160),
        "source_id": _text(document.get("source_id"), 160),
        "source_name": _text(document.get("source_name"), 240),
        "source_class": _text(document.get("source_class"), 100),
        "authority_class": _text(document.get("authority_class"), 100),
        "document_type": _text(document.get("document_type"), 100),
        "canonical_url": _safe_public_url(document.get("canonical_url")),
        "title": _text(document.get("title"), 300),
        "summary": _text(document.get("summary"), 800),
        "language": _text(document.get("language"), 40),
        "published_at": _text(document.get("published_at"), 80),
        "observed_at": _text(document.get("observed_at"), 80),
        "publisher": _text(document.get("publisher"), 240),
        "evidence_role": _text(document.get("evidence_role"), 100),
        "supports": _text(document.get("supports"), 160),
        "evidence_confidence": _bounded_scalar(document.get("evidence_confidence")),
    }
    return {key: value for key, value in projected.items() if value is not None}


def _source_refs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        for evidence in event.get("evidence") or []:
            url = _text(evidence.get("canonical_url"), 2048)
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append(
                {
                    "url": url,
                    "title": evidence.get("title") or event.get("title"),
                    "provider": evidence.get("source_name") or "Open Intel Atlas",
                    "document_id": evidence.get("id"),
                }
            )
            if len(rows) >= 20:
                return rows
    return rows


def _bounded_records(
    value: Any,
    *,
    fields: Iterable[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for field in fields:
            raw = item.get(field)
            bounded = _bounded_scalar(raw)
            if bounded is not None:
                row[field] = bounded
        if row:
            output.append(row)
    return output


def _bounded_mapping(value: Any, *, max_items: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for key, raw in list(value.items())[:max_items]:
        bounded = _bounded_scalar(raw)
        if bounded is not None:
            output[str(key)[:120]] = bounded
    return output


def _bounded_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _text(value, 400)
    return None


def _string_values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bounded_strings(value: Any, *, limit: int, length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value[:limit] if (text := _text(item, length))]


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return max(0, default)


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _safe_public_url(value: Any) -> str | None:
    text = _text(value, 2048)
    if text is None:
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return text
