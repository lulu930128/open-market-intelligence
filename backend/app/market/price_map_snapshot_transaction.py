"""Explicit claim/publication boundary. The caller owns commit/rollback."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import TaiwanPriceMapSnapshot, TaiwanTechnicalInputRevision
from app.market.stock_price_map_schemas import METHODOLOGY_VERSION, PRICE_MAP_VERSION
from app.market.technical_parameters import TechnicalAnalysisParameters
from app.market.price_map_snapshot_repository import read_input_revisions, snapshot_matches


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def claim_price_map_snapshot(db: Session, *, stock_id: str, timeframe: str, parameters: TechnicalAnalysisParameters, corporate_revision: str, basis_date: date, now: datetime) -> str | None:
    if now.tzinfo is None:
        raise ValueError("Snapshot claim requires an aware timestamp")
    now = now.astimezone(timezone.utc)
    revision = read_input_revisions(db, [stock_id]).get(stock_id, 0)
    row = db.get(TaiwanPriceMapSnapshot, (stock_id, timeframe))
    same = row is not None and snapshot_matches(row, input_revision=revision, parameter_revision=parameters.revision, corporate_revision=corporate_revision, basis_date=basis_date)
    if same and row.status in {"ready", "empty", "partial"}:
        return None
    if row is not None and row.status == "building" and _aware(row.claimed_at) + timedelta(minutes=5) > now:
        return None
    if same and row.retry_after is not None and _aware(row.retry_after) > now:
        return None
    token = uuid4().hex
    values = dict(
        claim_token=token, input_revision=revision, parameter_revision=parameters.revision,
        corporate_revision=corporate_revision, methodology_version=METHODOLOGY_VERSION,
        status="building", basis_date=basis_date, claimed_at=now,
        published_at=None, retry_after=None, error_code=None, payload_json=None,
        attempts=(row.attempts + 1 if same else 1),
    )
    if row is None:
        db.add(TaiwanPriceMapSnapshot(stock_id=stock_id, timeframe=timeframe, **values))
        db.flush()  # Concurrent first claims are resolved by the composite primary key.
    else:
        changed = db.execute(update(TaiwanPriceMapSnapshot).where(
            TaiwanPriceMapSnapshot.stock_id == stock_id, TaiwanPriceMapSnapshot.timeframe == timeframe,
            TaiwanPriceMapSnapshot.claim_token == row.claim_token,
        ).values(**values), execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            return None
    return token


def publish_price_map_snapshot(db: Session, *, stock_id: str, timeframe: str, token: str, payload: dict, parameters: TechnicalAnalysisParameters, corporate_revision: str, now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("Snapshot publication requires an aware timestamp")
    now = now.astimezone(timezone.utc)
    row = db.get(TaiwanPriceMapSnapshot, (stock_id, timeframe), populate_existing=True)
    if row is None or row.claim_token != token or row.status != "building":
        return False
    if row.parameter_revision != parameters.revision or row.corporate_revision != corporate_revision:
        return False
    reference_value = (payload.get("reference") or {}).get("trade_date")
    reference_date = date.fromisoformat(str(reference_value)[:10]) if reference_value is not None else None
    if (payload.get("stock_id") != stock_id
            or payload.get("structure_timeframe") != timeframe
            or payload.get("version") != PRICE_MAP_VERSION
            or (reference_date is not None and reference_date > row.basis_date)
            or (payload.get("parameter_contract") or {}).get("parameter_revision") != row.parameter_revision
            or (payload.get("methodology") or {}).get("version") != METHODOLOGY_VERSION):
        raise ValueError("SNAPSHOT_PAYLOAD_IDENTITY_MISMATCH")
    input_revision = select(TaiwanTechnicalInputRevision.generation).where(TaiwanTechnicalInputRevision.stock_id == stock_id).scalar_subquery()
    # Lock the revision on PostgreSQL so a concurrent trigger cannot change it between
    # the comparison and commit. SQLite serializes the conditional publication write.
    if db.bind.dialect.name == "postgresql":
        db.execute(select(TaiwanTechnicalInputRevision).where(TaiwanTechnicalInputRevision.stock_id == stock_id).with_for_update())
    status = "ready" if payload.get("structure_input_usable", payload.get("decision_usable")) is True else "partial"
    if reference_date != row.basis_date:
        status = "partial"
    if status == "ready" and not any(zone.get("scanner_eligible") is True for zone in payload.get("zones", [])):
        status = "empty"
    changed = db.execute(update(TaiwanPriceMapSnapshot).where(
        TaiwanPriceMapSnapshot.stock_id == stock_id, TaiwanPriceMapSnapshot.timeframe == timeframe,
        TaiwanPriceMapSnapshot.claim_token == token, TaiwanPriceMapSnapshot.status == "building",
        TaiwanPriceMapSnapshot.input_revision == func.coalesce(input_revision, 0),
    ).values(status=status, payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
             published_at=now, error_code=None), execution_options={"synchronize_session": False})
    return changed.rowcount == 1


def fail_price_map_snapshot(db: Session, *, stock_id: str, timeframe: str, token: str, now: datetime, error_code: str) -> None:
    if now.tzinfo is None:
        raise ValueError("Snapshot retry requires an aware timestamp")
    now = now.astimezone(timezone.utc)
    row = db.get(TaiwanPriceMapSnapshot, (stock_id, timeframe), populate_existing=True)
    if row is None or row.claim_token != token:
        return
    db.execute(update(TaiwanPriceMapSnapshot).where(
        TaiwanPriceMapSnapshot.stock_id == stock_id, TaiwanPriceMapSnapshot.timeframe == timeframe,
        TaiwanPriceMapSnapshot.claim_token == token, TaiwanPriceMapSnapshot.status == "building",
    ).values(status="failed", error_code=error_code[:120], payload_json=None,
             retry_after=now + timedelta(seconds=min(3600, 30 * 2 ** min(row.attempts, 7)))),
        execution_options={"synchronize_session": False})
