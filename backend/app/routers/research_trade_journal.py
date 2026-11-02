"""Independent F05 router; G6 registers it in app.main, without market.py edits.

    from app.routers import research_trade_journal
    app.include_router(research_trade_journal.router,
                       prefix="/api/research/trade-proposals", tags=["research"])
"""
from typing import Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.research import trade_journal_http_service as service
from app.research.stock_nomination import StockNomination, create_nominations
from app.research.proposal_monitor import read_proposal_monitor
from app.research.trade_journal_http_schemas import (
    PaperEvaluationRead, PaperEvaluationRequest, ProposalCreate, ProposalRead,
    ProposalListRead, ProposalPromote, ProposalRevise, RevisionListRead,
)


router = APIRouter()
T = TypeVar("T")


def _call(operation: Callable[..., T], *args, **kwargs) -> T:
    try:
        return operation(*args, **kwargs)
    except service.JournalHttpError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except OperationalError as exc:
        if "no such table: research_candidate_revision" in str(exc.orig):
            raise HTTPException(503, detail={"code": "RESEARCH_CANDIDATE_SCHEMA_UNAVAILABLE",
                                            "message": "Candidate schema 0095 has not been applied."}) from exc
        if "no such table: research_trade_proposal_version" not in str(exc.orig):
            raise
        raise HTTPException(503, detail={"code": "RESEARCH_JOURNAL_SCHEMA_UNAVAILABLE",
                                        "message": "Research journal schema 0094 has not been applied."}) from exc


@router.post("", response_model=ProposalRead, status_code=201)
def post_proposal(request: ProposalCreate, db: Session = Depends(get_db)):
    return _call(service.create, db, request)


@router.get("", response_model=ProposalListRead)
def get_proposals(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                  db: Session = Depends(get_db)):
    return _call(service.read_list, db, limit, offset)


@router.post("/nominations", status_code=201)
def post_nominations(request: StockNomination, db: Session = Depends(get_db)):
    return _call(create_nominations, db, request)


@router.post("/{creation_id}/revisions", response_model=ProposalRead, status_code=201)
def post_revision(creation_id: str, request: ProposalRevise, db: Session = Depends(get_db)):
    return _call(service.revise, db, creation_id, request)


@router.post("/{creation_id}/promote")
def post_promote(creation_id: str, request: ProposalPromote, db: Session = Depends(get_db)):
    return _call(service.promote, db, creation_id, request)


@router.get("/{creation_id}", response_model=ProposalRead)
def get_proposal(creation_id: str, decision_at: AwareDatetime | None = Query(default=None),
                 db: Session = Depends(get_db)):
    return _call(service.read_at, db, creation_id, decision_at)


@router.get("/{creation_id}/revisions", response_model=RevisionListRead)
def get_revisions(creation_id: str, as_of: AwareDatetime | None = Query(default=None),
                  db: Session = Depends(get_db)):
    return _call(service.read_revisions, db, creation_id, as_of)


@router.get("/{creation_id}/monitor")
def get_monitor(creation_id: str, db: Session = Depends(get_db)):
    return _call(read_proposal_monitor, db, creation_id)


@router.post("/{creation_id}/paper-outcome", response_model=PaperEvaluationRead)
def post_paper_outcome(creation_id: str, request: PaperEvaluationRequest, db: Session = Depends(get_db)):
    return _call(service.evaluate, db, creation_id, request)


@router.get("/{creation_id}/paper-outcome", response_model=PaperEvaluationRead)
def get_paper_outcome(creation_id: str, decision_at: AwareDatetime, outcome_as_of: AwareDatetime,
                      expected_revision_id: str | None = Query(default=None, min_length=1, max_length=36),
                      horizon_sessions: int | None = Query(default=None, ge=7, le=20),
                      db: Session = Depends(get_db)):
    request = PaperEvaluationRequest(decision_at=decision_at, outcome_as_of=outcome_as_of,
                                     expected_revision_id=expected_revision_id, horizon_sessions=horizon_sessions)
    return _call(service.evaluate, db, creation_id, request)
