"""Candidate commands and fixed MCP desk routes over the existing Native owner."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.research.candidate_service import CandidateService
from app.research.candidate_control import ControlRejected, ControlUnavailable
from app.research.manual_desk_service import ManualDeskService
from app.research.conditional_candidate import ManualStageOrder


router = APIRouter()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Create(Input):
    raw: dict
    owner_id: str = Field(min_length=1, max_length=128)


class Revision(Input):
    expected_revision: int = Field(gt=0, strict=True)


class Revise(Revision):
    raw: dict


class PendingRevise(Revision):
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    quantity: int = Field(gt=0, strict=True)


class Approve(Revision):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeskDraft(ManualStageOrder):
    pass


class DeskCancel(Input):
    trade_date: date
    broker_order_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_:.-]+$")


def desk_call(method, *args, db=None, **kwargs):
    try:
        return getattr(ManualDeskService(db), method)(*args, **kwargs)
    except ControlRejected as exc:
        raise HTTPException(409, detail={"code": str(exc), "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}) from exc
    except ControlUnavailable as exc:
        raise HTTPException(503, detail={"code": str(exc), "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}) from exc
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    except (IntegrityError, OperationalError) as exc:
        raise HTTPException(503, detail={"code": "CANDIDATE_DATABASE_UNAVAILABLE"}) from exc


def call(db, method, *args, **kwargs):
    try:
        return getattr(CandidateService(db), method)(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    except IntegrityError as exc:
        raise HTTPException(409, detail={"code": "CANDIDATE_REVISION_CONFLICT"}) from exc
    except OperationalError as exc:
        raise HTTPException(503, detail={"code": "CANDIDATE_DATABASE_UNAVAILABLE"}) from exc


@router.post("", status_code=201)
def create(request: Create, db: Session = Depends(get_db)):
    return call(db, "create", request.raw, owner_id=request.owner_id)


@router.get("")
def listing(after: str = "", limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db)):
    return call(db, "list", after=after, limit=limit)


@router.get("/monitor-status")
def status():
    from app.jobs.candidate_monitor import monitor_status
    return monitor_status()


# Fixed desk routes precede the existing dynamic Candidate routes. No main.py
# change and no Research Pending masquerading as a real broker order/fill.
@router.post("/desk/draft", status_code=201)
def desk_draft(request: DeskDraft, db: Session = Depends(get_db)):
    return desk_call("draft", request.model_dump(mode="json"), db=db)


@router.get("/desk/staged")
def desk_staged(after: str = "", limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db)):
    return desk_call("staged", after=after, limit=limit, db=db)


@router.get("/desk/staged/{identity}")
def desk_stage(identity: str, db: Session = Depends(get_db)):
    return desk_call("staged", identity, db=db)


@router.post("/desk/staged/{identity}/confirm")
def desk_stage_confirm(identity: str, request: Approve, db: Session = Depends(get_db)):
    return desk_call("send_staged", identity, expected_revision=request.expected_revision,
                     expected_digest=request.expected_digest, db=db)


@router.get("/desk/order-reports")
def desk_orders():
    return desk_call("readback")


@router.get("/desk/fills")
def desk_fills():
    return desk_call("fills")


@router.get("/desk/inventory")
def desk_inventory():
    return desk_call("inventory")


@router.get("/desk/status")
def desk_status():
    return desk_call("status")


@router.post("/desk/reviews/{identity}/confirm")
def desk_confirm(identity: str, request: Approve):
    return desk_call("confirm", identity, expected_revision=request.expected_revision,
                     expected_digest=request.expected_digest)


@router.post("/desk/executions/{identity}/cancel")
def desk_cancel(identity: str, request: DeskCancel):
    return desk_call("cancel", identity, trade_date=request.trade_date.isoformat(),
                     broker_order_id=request.broker_order_id)


@router.get("/{identity}")
def get(identity: str, db: Session = Depends(get_db)):
    return call(db, "get", identity)


@router.get("/{identity}/revisions")
def history(identity: str, db: Session = Depends(get_db)):
    return call(db, "history", identity)


@router.post("/{identity}/revisions")
def revise(identity: str, request: Revise, db: Session = Depends(get_db)):
    return call(db, "change", identity, expected_revision=request.expected_revision, operation="revise", raw=request.raw)


@router.post("/{identity}/pause")
def pause(identity: str, request: Revision, db: Session = Depends(get_db)):
    return call(db, "change", identity, expected_revision=request.expected_revision, operation="pause")


@router.post("/{identity}/resume")
def resume(identity: str, request: Revision, db: Session = Depends(get_db)):
    return call(db, "change", identity, expected_revision=request.expected_revision, operation="resume")


@router.post("/{identity}/cancel")
def cancel(identity: str, request: Revision, db: Session = Depends(get_db)):
    return call(db, "change", identity, expected_revision=request.expected_revision, operation="cancel")


@router.get("/{identity}/pending")
def pending(identity: str, db: Session = Depends(get_db)):
    return call(db, "pending", identity)


@router.post("/pending/{identity}/revise")
def revise_pending(identity: str, request: PendingRevise, db: Session = Depends(get_db)):
    return call(db, "revise_pending", identity, expected_revision=request.expected_revision,
                price=str(request.price), quantity=request.quantity)


@router.post("/pending/{identity}/cancel")
def cancel_pending(identity: str, request: Revision, db: Session = Depends(get_db)):
    return call(db, "cancel_pending", identity, expected_revision=request.expected_revision)


@router.post("/pending/{identity}/prepare")
def prepare(identity: str, db: Session = Depends(get_db)):
    return call(db, "prepare", identity)


@router.post("/pending/{identity}/approve")
def approve(identity: str, request: Approve, db: Session = Depends(get_db)):
    return call(db, "approve", identity, expected_revision=request.expected_revision, expected_digest=request.expected_digest)
