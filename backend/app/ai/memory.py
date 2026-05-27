from __future__ import annotations

from typing import Any
import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai.schemas import AiMemoryCreate, AiMemoryUpdate
from app.db.models import AiMemory, utc_now


ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


class AiMemoryNotFoundError(Exception):
    pass


def _to_json(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def serialize_memory(memory: AiMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "memory_type": memory.memory_type,
        "scope_type": memory.scope_type,
        "scope_id": memory.scope_id,
        "title": memory.title,
        "content": memory.content,
        "tags": _from_json(memory.tags_json, []),
        "metadata": _from_json(memory.metadata_json, {}),
        "importance": memory.importance,
        "status": memory.status,
        "source": memory.source,
        "created_by": memory.created_by,
        "last_used_at": memory.last_used_at,
        "archived_at": memory.archived_at,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
    }


def get_memory(db: Session, memory_id: int) -> AiMemory:
    memory = db.query(AiMemory).filter(AiMemory.id == memory_id).first()

    if memory is None:
        raise AiMemoryNotFoundError(f"AI memory id={memory_id} not found.")

    return memory


def list_memories(
    db: Session,
    *,
    memory_type: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    status: str | None = ACTIVE_STATUS,
    keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AiMemory]:
    query = db.query(AiMemory)

    if memory_type:
        query = query.filter(AiMemory.memory_type == memory_type)

    if scope_type:
        query = query.filter(AiMemory.scope_type == scope_type)

    if scope_id:
        query = query.filter(AiMemory.scope_id == scope_id)

    if status:
        query = query.filter(AiMemory.status == status)

    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                AiMemory.title.ilike(pattern),
                AiMemory.content.ilike(pattern),
            )
        )

    return (
        query.order_by(
            AiMemory.importance.desc(),
            AiMemory.updated_at.desc(),
            AiMemory.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_relevant_memories(
    db: Session,
    *,
    scope_type: str | None,
    scope_id: str | None,
    strategy_profile: str | None = None,
    limit: int = 20,
) -> list[AiMemory]:
    filters = [AiMemory.scope_type == "global"]

    if strategy_profile:
        filters.append(
            (AiMemory.scope_type == "strategy") & (AiMemory.scope_id == strategy_profile)
        )

    if scope_type and scope_id:
        filters.append(
            (AiMemory.scope_type == scope_type) & (AiMemory.scope_id == str(scope_id))
        )

    return (
        db.query(AiMemory)
        .filter(AiMemory.status == ACTIVE_STATUS)
        .filter(or_(*filters))
        .order_by(
            AiMemory.importance.desc(),
            AiMemory.updated_at.desc(),
            AiMemory.id.desc(),
        )
        .limit(limit)
        .all()
    )


def create_memory(db: Session, payload: AiMemoryCreate) -> AiMemory:
    memory = AiMemory(
        memory_type=payload.memory_type,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        title=payload.title,
        content=payload.content,
        tags_json=_to_json(payload.tags),
        metadata_json=_to_json(payload.metadata),
        importance=payload.importance,
        status=ACTIVE_STATUS,
        source=payload.source,
        created_by=payload.created_by,
    )

    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def update_memory(
    db: Session,
    memory_id: int,
    payload: AiMemoryUpdate,
) -> AiMemory:
    memory = get_memory(db=db, memory_id=memory_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "tags" in update_data:
        memory.tags_json = _to_json(update_data.pop("tags"))

    if "metadata" in update_data:
        memory.metadata_json = _to_json(update_data.pop("metadata"))

    for key, value in update_data.items():
        setattr(memory, key, value)

    if memory.status == ARCHIVED_STATUS and memory.archived_at is None:
        memory.archived_at = utc_now()
    elif memory.status != ARCHIVED_STATUS:
        memory.archived_at = None

    memory.updated_at = utc_now()
    db.commit()
    db.refresh(memory)
    return memory


def archive_memory(db: Session, memory_id: int) -> AiMemory:
    memory = get_memory(db=db, memory_id=memory_id)
    memory.status = ARCHIVED_STATUS
    memory.archived_at = utc_now()
    memory.updated_at = utc_now()
    db.commit()
    db.refresh(memory)
    return memory


def mark_memories_used(db: Session, memory_ids: list[int]) -> None:
    if not memory_ids:
        return

    now = utc_now()
    db.query(AiMemory).filter(AiMemory.id.in_(memory_ids)).update(
        {
            "last_used_at": now,
            "updated_at": now,
        },
        synchronize_session=False,
    )
    db.commit()
