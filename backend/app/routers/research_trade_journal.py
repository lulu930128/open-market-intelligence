"""Independent F05 router; G6 registers it in app.main, without market.py edits.

    from app.routers import research_trade_journal
    app.include_router(research_trade_journal.router,
                       prefix="/api/research/trade-proposals", tags=["research"])
"""
from typing import Callable, TypeVar, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.research import trade_journal_http_service as service
from app.research.stock_nomination import StockNomination, create_nominations
from app.research.proposal_monitor import read_proposal_monitor
from app.jobs.us_watchlist_research import ScanRequest, enqueue_scan, read_latest
from app.research.trade_journal_http_schemas import (
    PaperEvaluationRead, PaperEvaluationRequest, ProposalCreate, ProposalRead,
    ProposalListRead, ProposalSummaryListRead, ProposalPromote, ProposalRevise, RevisionListRead, ProposalDelete, ProposalDeleteRead, ProposalMove, ProposalStage,
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


@router.get("", response_model=ProposalListRead | ProposalSummaryListRead)
def get_proposals(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                  market: Literal["TW", "US"] | None = None,
                  origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] | None = None,
                  direction: Literal["long", "short"] | None = None,
                  view: Literal["full", "summary"] = "full",
                  db: Session = Depends(get_db)):
    return _call(service.read_list, db, limit, offset, market=market, origin=origin, direction=direction, view=view)


@router.post("/nominations", status_code=201)
def post_nominations(request: StockNomination, db: Session = Depends(get_db)):
    return _call(create_nominations, db, request)


@router.post("/us-watchlist-scan", status_code=202)
def post_us_scan(request: ScanRequest, db: Session = Depends(get_db)):
    return _call(enqueue_scan, db, request)


@router.get("/us-watchlist-scan")
def get_us_scan(db: Session = Depends(get_db)):
    return _call(read_latest, db)


class AiNomination(StockNomination):
    nomination_origin: Literal["AI_NOMINATION", "OMI_SCREEN"] = "AI_NOMINATION"


class ResearchStageChange(ProposalDelete):
    stage_id: str
    expected_stage_revision: int
    raw: dict | None = None


@router.get("/ai/schema")
def ai_schema():
    return {name: model.model_json_schema() for name, model in {
        "create": ProposalCreate, "revise": ProposalRevise, "nominate": AiNomination,
        "move": ProposalMove, "stage": ProposalStage, "stage_revision": ResearchStageChange,
    }.items()}


@router.post("/ai/{creation_id}/stage-revision")
def ai_stage_revision(creation_id: str, request: ResearchStageChange, db: Session = Depends(get_db)):
    from app.research.candidate_service import CandidateService
    with db.begin():
        proposal = _call(service.read_at, db, creation_id, ai_scope=True)
        if proposal.proposal.revision_id != request.expected_revision_id:
            raise HTTPException(409, detail={"code": "REVISION_CONFLICT"})
    try:
        return CandidateService(db).change(request.stage_id, expected_revision=request.expected_stage_revision,
            operation="revise" if request.raw is not None else "cancel", raw=request.raw, research_id=creation_id)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "RESEARCH_STAGE_CONFLICT", "message": str(exc)}) from exc


@router.get("/ai", response_model=ProposalListRead | ProposalSummaryListRead)
def ai_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
            market: Literal["TW", "US"] | None = None,
            origin: Literal["AI_NOMINATION", "OMI_SCREEN"] | None = None,
            direction: Literal["long", "short"] | None = None,
            view: Literal["full", "summary"] = "summary", db: Session = Depends(get_db)):
    return _call(service.read_list, db, limit, offset, market=market, origin=origin, direction=direction, ai_scope=True, view=view)


@router.post("/ai", response_model=ProposalRead, status_code=201)
def ai_create(request: ProposalCreate, db: Session = Depends(get_db)):
    if request.workflow_origin not in {None, "AI_NOMINATION", "OMI_SCREEN"}:
        raise HTTPException(403, detail={"code": "RESEARCH_OUTSIDE_AI_SCOPE"})
    return _call(service.create, db, request.model_copy(update={"workflow_origin": request.workflow_origin or "AI_NOMINATION"}))


@router.post("/ai/nominations", status_code=201)
def ai_nominate(request: AiNomination, db: Session = Depends(get_db)):
    return _call(create_nominations, db, request)


@router.get("/ai/{creation_id}", response_model=ProposalRead)
def ai_read(creation_id: str, db: Session = Depends(get_db)):
    return _call(service.read_at, db, creation_id, ai_scope=True)


@router.get("/ai/{creation_id}/revisions", response_model=RevisionListRead)
def ai_history(creation_id: str, db: Session = Depends(get_db)):
    _call(service.read_at, db, creation_id, ai_scope=True)
    return _call(service.read_revisions, db, creation_id)


@router.post("/ai/{creation_id}/revisions", response_model=ProposalRead)
def ai_revise(creation_id: str, request: ProposalRevise, db: Session = Depends(get_db)):
    return _call(service.revise, db, creation_id, request, ai_scope=True)


@router.post("/ai/{creation_id}/move", response_model=ProposalRead)
def ai_move(creation_id: str, request: ProposalMove, db: Session = Depends(get_db)):
    return _call(service.move, db, creation_id, request, ai_scope=True)


@router.delete("/ai/{creation_id}", response_model=ProposalDeleteRead)
def ai_delete(creation_id: str, request: ProposalDelete, db: Session = Depends(get_db)):
    return _call(service.delete, db, creation_id, request, ai_scope=True)


@router.post("/{creation_id}/move", response_model=ProposalRead)
def move_proposal(creation_id: str, request: ProposalMove, db: Session = Depends(get_db)):
    return _call(service.move, db, creation_id, request)


@router.post("/ai/{creation_id}/stage", status_code=201)
def ai_stage(creation_id: str, request: ProposalStage, db: Session = Depends(get_db)):
    from app.research.research_order_service import stage
    return _call(stage, db, creation_id, request, ai_scope=True)


@router.post("/{creation_id}/stage", status_code=201)
def stage_order(creation_id: str, request: ProposalStage, db: Session = Depends(get_db)):
    from app.research.research_order_service import stage
    return _call(stage, db, creation_id, request)


@router.delete("/{creation_id}", response_model=ProposalDeleteRead)
def delete_proposal(creation_id: str, request: ProposalDelete, db: Session = Depends(get_db)):
    return _call(service.delete, db, creation_id, request)


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
