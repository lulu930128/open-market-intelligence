"""Add explicit lifecycle metadata to cross-market signal snapshots.

Revision ID: 20260809_0057
Revises: 20260809_0056
Create Date: 2026-08-09 20:30:00
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0057"
down_revision: str | Sequence[str] | None = "20260809_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "cross_market_signal_snapshot"
PROJECTION_SOURCE = "materialized_snapshot"
LATEST_CACHE_LIMITATION = "latest_local_cache_projection_not_materialized_snapshot"
PROJECTION_CHECK = "ck_cross_market_signal_snapshot_projection_source"
LIFECYCLE_COLUMNS = (
    "projection_source",
    "source_cutoff_at",
    "materialized_at",
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table() -> bool:
    return _inspector().has_table(TABLE_NAME)


def _column_names() -> set[str]:
    return {item["name"] for item in _inspector().get_columns(TABLE_NAME)}


def _index_names() -> set[str]:
    return {item["name"] for item in _inspector().get_indexes(TABLE_NAME)}


def _check_names() -> set[str]:
    return {
        item["name"]
        for item in _inspector().get_check_constraints(TABLE_NAME)
        if item.get("name")
    }


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse_payload(value: Any, *, snapshot_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} has malformed payload_json"
        ) from exc
    if not isinstance(payload, dict) or payload.get("snapshot_id") != snapshot_id:
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} payload identity is invalid"
        )
    return payload


def _iso_datetime(value: Any, *, field: str, snapshot_id: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"cross-market snapshot {snapshot_id} has invalid {field}"
            ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _content_hash(payload: Mapping[str, Any]) -> str:
    hash_payload = json.loads(_canonical_json(payload))
    hash_payload["payload_hash"] = None
    passport = hash_payload.get("evidence_passport")
    if isinstance(passport, dict):
        passport["payload_hash"] = None
    return hashlib.sha256(_canonical_json(hash_payload).encode("utf-8")).hexdigest()


def _without_latest_cache_limitation(values: Any) -> list[Any]:
    return [
        value
        for value in values or []
        if value != LATEST_CACHE_LIMITATION
    ]


def _with_latest_cache_limitation(values: Any) -> list[Any]:
    output = list(values or [])
    if LATEST_CACHE_LIMITATION not in output:
        output.append(LATEST_CACHE_LIMITATION)
    return output


def _upgrade_payload(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    snapshot_id = str(row["snapshot_id"])
    payload = _parse_payload(row["payload_json"], snapshot_id=snapshot_id)
    legacy_serialized = str(row["payload_json"])
    existing_source = payload.get("projection_source")
    if existing_source not in {None, "latest_local_cache", PROJECTION_SOURCE}:
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} has unknown projection_source"
        )
    if existing_source != PROJECTION_SOURCE:
        legacy_hash = hashlib.sha256(legacy_serialized.encode("utf-8")).hexdigest()
        if legacy_hash != str(row["payload_hash"]):
            raise RuntimeError(
                f"cross-market snapshot {snapshot_id} failed legacy hash validation"
            )

    source_cutoff_at = _iso_datetime(
        payload.get("source_cutoff_at") or row["source_cutoff_at"] or row["decision_at"],
        field="source_cutoff_at",
        snapshot_id=snapshot_id,
    )
    materialized_at = _iso_datetime(
        payload.get("materialized_at") or row["materialized_at"] or row["created_at"],
        field="materialized_at",
        snapshot_id=snapshot_id,
    )
    materialized_by = str(
        payload.get("materialized_by") or row["materialized_by"] or ""
    ).strip()
    if not materialized_by:
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} has no materialized_by actor"
        )

    payload.update(
        {
            "projection_source": PROJECTION_SOURCE,
            "source_cutoff_at": source_cutoff_at,
            "materialized_at": materialized_at,
            "materialized_by": materialized_by,
            "payload_hash": None,
            "limitations": _without_latest_cache_limitation(
                payload.get("limitations")
            ),
        }
    )
    freshness = dict(payload.get("freshness") or {})
    freshness.update(
        {
            "projection_source": PROJECTION_SOURCE,
            "source_cutoff_at": source_cutoff_at,
        }
    )
    payload["freshness"] = freshness
    passport = dict(payload.get("evidence_passport") or {})
    passport.update(
        {
            "projection_source": PROJECTION_SOURCE,
            "source_cutoff_at": source_cutoff_at,
            "materialized_at": materialized_at,
            "materialized_by": materialized_by,
            "payload_hash": None,
            "limitations": _without_latest_cache_limitation(
                passport.get("limitations")
            ),
        }
    )
    payload["evidence_passport"] = passport
    payload_hash = _content_hash(payload)
    payload["payload_hash"] = payload_hash
    passport["payload_hash"] = payload_hash
    return (
        _canonical_json(payload),
        payload_hash,
        source_cutoff_at,
        materialized_at,
    )


def _downgrade_payload(row: Mapping[str, Any]) -> tuple[str, str]:
    snapshot_id = str(row["snapshot_id"])
    payload = _parse_payload(row["payload_json"], snapshot_id=snapshot_id)
    if payload.get("projection_source") != PROJECTION_SOURCE:
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} is not materialized"
        )
    if _content_hash(payload) != str(row["payload_hash"]):
        raise RuntimeError(
            f"cross-market snapshot {snapshot_id} failed content hash validation"
        )

    for field in (
        "projection_source",
        "source_cutoff_at",
        "materialized_at",
        "materialized_by",
        "payload_hash",
    ):
        payload.pop(field, None)
    payload["limitations"] = _with_latest_cache_limitation(
        payload.get("limitations")
    )
    freshness = dict(payload.get("freshness") or {})
    freshness.pop("projection_source", None)
    freshness.pop("source_cutoff_at", None)
    payload["freshness"] = freshness
    passport = dict(payload.get("evidence_passport") or {})
    for field in (
        "projection_source",
        "source_cutoff_at",
        "materialized_at",
        "materialized_by",
        "payload_hash",
    ):
        passport.pop(field, None)
    passport["limitations"] = _with_latest_cache_limitation(
        passport.get("limitations")
    )
    payload["evidence_passport"] = passport
    serialized = _canonical_json(payload)
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def upgrade() -> None:
    if not _has_table():
        return
    columns = _column_names()
    additions = (
        ("projection_source", sa.Column("projection_source", sa.String(40), nullable=True)),
        ("source_cutoff_at", sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=True)),
        ("materialized_at", sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column(TABLE_NAME, column)

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT id, snapshot_id, decision_at, created_at, materialized_by, "
            f"payload_hash, payload_json, projection_source, source_cutoff_at, "
            f"materialized_at FROM {TABLE_NAME}"
        )
    ).mappings()
    for row in rows:
        serialized, payload_hash, source_cutoff_at, materialized_at = _upgrade_payload(row)
        connection.execute(
            sa.text(
                f"UPDATE {TABLE_NAME} SET projection_source = :projection_source, "
                "source_cutoff_at = :source_cutoff_at, materialized_at = :materialized_at, "
                "payload_hash = :payload_hash, payload_json = :payload_json WHERE id = :id"
            ),
            {
                "id": row["id"],
                "projection_source": PROJECTION_SOURCE,
                "source_cutoff_at": source_cutoff_at,
                "materialized_at": materialized_at,
                "payload_hash": payload_hash,
                "payload_json": serialized,
            },
        )

    with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
        for name in LIFECYCLE_COLUMNS:
            batch_op.alter_column(name, existing_nullable=True, nullable=False)
        if PROJECTION_CHECK not in _check_names():
            batch_op.create_check_constraint(
                PROJECTION_CHECK,
                "projection_source = 'materialized_snapshot'",
            )

    indexes = _index_names()
    for name in LIFECYCLE_COLUMNS:
        index_name = f"ix_{TABLE_NAME}_{name}"
        if index_name not in indexes:
            op.create_index(index_name, TABLE_NAME, [name], unique=False)


def downgrade() -> None:
    if not _has_table() or not set(LIFECYCLE_COLUMNS).issubset(_column_names()):
        return
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT id, snapshot_id, payload_hash, payload_json FROM {TABLE_NAME}"
        )
    ).mappings()
    for row in rows:
        serialized, payload_hash = _downgrade_payload(row)
        connection.execute(
            sa.text(
                f"UPDATE {TABLE_NAME} SET payload_hash = :payload_hash, "
                "payload_json = :payload_json WHERE id = :id"
            ),
            {
                "id": row["id"],
                "payload_hash": payload_hash,
                "payload_json": serialized,
            },
        )

    indexes = _index_names()
    checks = _check_names()
    for name in LIFECYCLE_COLUMNS:
        index_name = f"ix_{TABLE_NAME}_{name}"
        if index_name in indexes:
            op.drop_index(index_name, table_name=TABLE_NAME)
    with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
        if PROJECTION_CHECK in checks:
            batch_op.drop_constraint(PROJECTION_CHECK, type_="check")
        for name in reversed(LIFECYCLE_COLUMNS):
            batch_op.drop_column(name)
