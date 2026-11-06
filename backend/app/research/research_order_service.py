"""Research version selection -> existing local Desk staging, without broker IO."""
from app.db.models import utc_now
from app.research import trade_journal
from app.research.candidate_service import CandidateService
from app.research.conditional_candidate import ManualStageOrder
from app.research.trade_journal_http_service import JournalHttpError, require_ai_scope


def stage(db, identity, request, *, ai_scope=False):
    with db.begin():
        versions = trade_journal.list_versions(db, creation_id=identity, as_of=utc_now())
        if not versions:
            raise JournalHttpError(404, "PROPOSAL_NOT_FOUND", "No proposal is known.")
        version = versions[-1]
        if ai_scope:
            require_ai_scope(version)
        if version.deleted_at is not None:
            raise JournalHttpError(410, "PROPOSAL_DELETED", "The proposal was deleted.")
        if version.revision_id != request.expected_revision_id:
            raise JournalHttpError(409, "REVISION_CONFLICT", "Reload the latest research version.")
        if trade_journal.workflow_origin(version) != "AI_NOMINATION":
            raise JournalHttpError(409, "AI_NOMINATION_REQUIRED", "Move this proposal to AI nomination before staging an order.")
    strategy = version.strategy
    data = {"client_intent_id": request.client_intent_id, "market": version.market,
        "symbol": version.symbol, "action": "Buy" if strategy.direction == 1 else "Sell",
        "condition": "CASH" if version.market == "US" or strategy.direction == 1 else "SHORT_SELLING",
        "lot": "Shares" if version.market == "US" else "Common" if strategy.shares % 1000 == 0 else "Odd",
        "quantity_shares": strategy.shares, "price": str(strategy.entry_price),
        "protection": {"stop_loss": str(strategy.stop_price), "take_profit": str(strategy.targets[-1].price),
            "exit_limit_price": str(strategy.stop_price), "stop_limit_price": str(strategy.stop_price),
            "direction": strategy.direction, "targets": [
                {"price": str(t.price), "fraction": str(t.fraction), "limit_price": str(t.price)} for t in strategy.targets]}}
    allowed = {"quantity_shares", "price", "condition", "lot", "settlement_mode", "protection"}
    if request.overrides.keys() - allowed:
        raise JournalHttpError(422, "INVALID_ORDER_OVERRIDE", "Only order size, price, condition, lot, settlement and protection can be overridden.")
    data.update(request.overrides)
    data["research_proposal"] = {"creation_id": identity, "revision_id": version.revision_id,
        "workflow_origin": "AI_NOMINATION", "market": version.market,
        "original_origin": trade_journal.workflow_origin(version.model_copy(update={"workflow_origin": None}))}
    try:
        order = ManualStageOrder.model_validate(data)
    except ValueError as exc:
        raise JournalHttpError(422, "INVALID_ORDER", str(exc)) from exc
    try:
        return CandidateService(db).create(order.canonical(), owner_id="MCP", manual_stage=True)
    except ValueError as exc:
        raise JournalHttpError(409, "RESEARCH_STAGE_CONFLICT", str(exc)) from exc
