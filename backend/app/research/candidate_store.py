"""Research candidate revisions only. The calling service owns transactions."""
from datetime import datetime, timezone
import json

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, func, insert, select

from .conditional_candidate import CandidateBody, PendingBody, digest


metadata = MetaData()


def version_table(name):
    return Table(name, metadata,
        Column("id", String(64), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("candidate_id", String(64), nullable=False, index=True),
        Column("recorded_at", String(40), nullable=False),
        Column("payload", Text, nullable=False),
        Column("digest", String(64), nullable=False),
        UniqueConstraint("id", "revision", name="uq_" + name + "_revision"))


candidates = version_table("research_candidate_revision")
pending = version_table("research_candidate_pending_revision")


def decode(row):
    value = json.loads(row.payload)
    if digest(value) != row.digest:
        raise ValueError("CANDIDATE_INTEGRITY_MISMATCH")
    return {**value, "id": row.id, "revision": row.revision, "digest": row.digest,
            "recorded_at": row.recorded_at}


def get(db, table, identity, revision=None):
    query = select(table).where(table.c.id == identity)
    if revision is not None:
        query = query.where(table.c.revision == revision)
    row = db.execute(query.order_by(table.c.revision.desc()).limit(1)).first()
    if row is None:
        raise LookupError("CANDIDATE_RECORD_NOT_FOUND")
    return decode(row)


def latest(db, table, *, candidate_id=None, after="", limit=100, kind=None):
    heads = select(table.c.id, func.max(table.c.revision).label("revision")).group_by(table.c.id).subquery()
    query = select(table).join(heads, (table.c.id == heads.c.id) & (table.c.revision == heads.c.revision))
    if candidate_id is not None:
        query = query.where(table.c.candidate_id == candidate_id)
    if kind is not None:
        query = query.where(func.coalesce(func.json_extract(table.c.payload, "$.kind"), "conditional") == kind)
    return [decode(row) for row in db.execute(query.where(table.c.id > after).order_by(table.c.id).limit(limit))]


def history(db, table, identity):
    return [decode(row) for row in db.execute(select(table).where(table.c.id == identity).order_by(table.c.revision))]


def append(db, table, identity, candidate_id, revision, value, now=None):
    (CandidateBody if table is candidates else PendingBody).model_validate(value)
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    db.execute(insert(table).values(id=identity, candidate_id=candidate_id, revision=revision,
        recorded_at=timestamp, payload=json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False),
        digest=digest(value)))
    return get(db, table, identity)


def body(record):
    return {k: v for k, v in record.items() if k not in {"id", "revision", "digest", "recorded_at"}}
