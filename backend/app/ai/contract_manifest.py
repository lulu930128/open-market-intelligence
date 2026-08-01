from __future__ import annotations

import hashlib
import json
from typing import Any

from app.ai import capability_contract, public_contract


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_contract_manifest() -> dict[str, Any]:
    payload = {
        "contract_version": "omi.decision.v4",
        "capability_registry_version": (
            public_contract.CAPABILITY_REGISTRY_VERSION
        ),
        "selection_version": public_contract.CAPABILITY_SELECTION_VERSION,
        "targets": public_contract.target_catalog(),
        "capabilities": capability_contract.capability_catalog(),
        "capability_schema_versions": {
            spec.capability_id: spec.schema_version
            for spec in capability_contract.CAPABILITY_SPECS
        },
    }
    return {
        **payload,
        "digest": _canonical_digest(payload),
    }
