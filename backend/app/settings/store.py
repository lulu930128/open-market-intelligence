from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import AppSetting
from app.db.session import SessionLocal


TECHNICAL_ANALYSIS_SETTING_KEY = "technical_analysis"


def _load_setting_payload(db: Session, setting_key: str) -> dict[str, Any] | None:
    row = db.query(AppSetting).filter(AppSetting.setting_key == setting_key).first()
    if row is None:
        return None

    payload = json.loads(row.value_json)
    return payload if isinstance(payload, dict) else None


def get_setting_payload(
    setting_key: str,
    *,
    db: Session | None = None,
    fallback_on_error: bool = True,
) -> dict[str, Any] | None:
    try:
        if db is not None:
            return _load_setting_payload(db, setting_key)

        with SessionLocal() as session:
            return _load_setting_payload(session, setting_key)
    except (SQLAlchemyError, json.JSONDecodeError):
        if fallback_on_error:
            return None
        raise


def save_setting_payload(
    db: Session,
    setting_key: str,
    payload: Mapping[str, Any],
    *,
    source: str = "user",
    description: str | None = None,
) -> AppSetting:
    value_json = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
    row = db.query(AppSetting).filter(AppSetting.setting_key == setting_key).first()

    if row is None:
        row = AppSetting(
            setting_key=setting_key,
            value_json=value_json,
            source=source,
            description=description,
        )
        db.add(row)
    else:
        row.value_json = value_json
        row.source = source
        row.description = description

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(row)
    return row


def get_technical_analysis_setting_payload(
    *,
    db: Session | None = None,
    fallback_on_error: bool = True,
) -> dict[str, Any] | None:
    return get_setting_payload(
        TECHNICAL_ANALYSIS_SETTING_KEY,
        db=db,
        fallback_on_error=fallback_on_error,
    )


def save_technical_analysis_setting_payload(
    db: Session,
    payload: Mapping[str, Any],
) -> AppSetting:
    return save_setting_payload(
        db,
        TECHNICAL_ANALYSIS_SETTING_KEY,
        payload,
        source="user",
        description="Global technical analysis parameters.",
    )
