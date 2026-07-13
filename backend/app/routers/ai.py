from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai import agentic_tools
from app.ai import ask as ai_ask
from app.ai import llm as ai_llm
from app.ai import memory as ai_memory
from app.ai import orchestrator, prompts, reports, tools
from app.ai import report_store
from app.ai import streaming as ai_streaming
from app.ai.schemas import (
    AiAskRequest,
    AiAskResponse,
    AiDataEnvelope,
    AiMemoryCreate,
    AiMemoryRead,
    AiMemoryUpdate,
    AiReportEnvelope,
    AiStoredReportRead,
    AiToolListRead,
    StrategyProfileRead,
)
from app.config import settings
from app.db.session import get_db
from app.watchlists import service as watchlist_service


router = APIRouter()
AI_TRUST_TOKEN_HEADER = "x-omi-ai-trust-token"


def _csv_values(value: str | None) -> set[str]:
    if not value:
        return set()

    return {item.strip() for item in value.split(",") if item.strip()}


def _clean_token(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _trusted_ai_source(request: Request) -> str:
    configured_token = _clean_token(settings.omi_ai_trust_token)
    request_token = _clean_token(request.headers.get(AI_TRUST_TOKEN_HEADER))
    if configured_token and request_token and compare_digest(configured_token, request_token):
        return "token"

    client_host = request.client.host if request.client else ""
    trusted_hosts = _csv_values(settings.omi_ai_trusted_client_hosts)
    if settings.omi_ai_allow_local_trust and client_host in trusted_hosts:
        return "local_allowlist"

    return "untrusted"


def _ai_server_policy(request: Request) -> ai_ask.AiAskServerPolicy:
    trust_source = _trusted_ai_source(request)
    trusted = trust_source != "untrusted"
    return ai_ask.AiAskServerPolicy(
        can_call_llm=trusted,
        can_write=trusted,
        can_external_fetch=trusted,
        trust_source=trust_source,
    )


def _require_trusted_ai_request(request: Request, action: str) -> None:
    if _trusted_ai_source(request) != "untrusted":
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"{action} requires a server-side trusted AI request.",
    )


def _raise_llm_http_error(exc: ai_llm.OpenAILLMError) -> None:
    if isinstance(exc, ai_llm.OpenAIConfigurationError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if isinstance(exc, ai_llm.OpenAIHTTPError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _market_data_params_from_query(
    *,
    include_intraday: bool | None = None,
    payload_level: str | None = None,
    intraday_limit: int | None = None,
    session_scope: str | None = None,
    daily_limit: int | None = None,
    timeframe: str | None = None,
    bars: int | None = None,
    provider: str | None = None,
) -> dict:
    params: dict = {}
    if include_intraday is not None:
        params["include_intraday"] = include_intraday
    if payload_level:
        params["payload_level"] = payload_level
    if intraday_limit is not None:
        params["intraday_limit"] = intraday_limit
    if session_scope:
        params["session_scope"] = session_scope
    if daily_limit is not None:
        params["daily_limit"] = daily_limit
    if timeframe:
        params["timeframe"] = timeframe
    if bars is not None:
        params["bars"] = bars
    if provider:
        params["provider"] = provider
    return params


def _memory_ids_from_envelope(envelope: dict) -> list[int]:
    prompt = envelope.get("prompt") or {}
    memories = prompt.get("memories") or []
    return [
        int(memory["id"])
        for memory in memories
        if isinstance(memory, dict) and isinstance(memory.get("id"), int)
    ]


def _save_brief_report(
    *,
    db: Session,
    envelope: dict,
    report_type: str,
    scope_type: str,
    scope_id: str,
    strategy_profile: str,
    title: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    report = report_store.save_report(
        db=db,
        envelope=envelope,
        report_type=report_type,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=strategy_profile,
        title=title,
        tool_calls=[
            {
                "tool_name": tool_name,
                "source": "backend",
                "arguments": arguments,
                "result_summary": report_store.report_tool_summary(envelope),
            }
        ],
    )
    ai_memory.mark_memories_used(db, _memory_ids_from_envelope(envelope))
    return report_store.serialize_report(report)


@router.get("/tools", response_model=AiToolListRead)
def list_ai_tools(
    request: Request,
    include_internal: bool = Query(default=False),
    debug: bool = Query(default=False),
):
    wants_internal = include_internal or debug
    if wants_internal and _trusted_ai_source(request) == "untrusted":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal AI tools require a server-side trusted request.",
        )

    return tools.list_ai_tools(include_internal=wants_internal)


@router.get("/strategy-profiles", response_model=list[StrategyProfileRead])
def list_strategy_profiles():
    return prompts.list_strategy_profiles()


@router.get("/data-freshness", response_model=AiDataEnvelope)
def read_data_freshness(
    stock_id: str | None = None,
    db: Session = Depends(get_db),
):
    return tools.read_data_freshness(db=db, stock_id=stock_id)


@router.get("/market-overview", response_model=AiDataEnvelope)
def read_market_overview(
    limit: int = Query(default=10, ge=1, le=50),
    include_intraday: bool = Query(default=False),
    payload_level: str = Query(default="compact", pattern="^(summary|compact|standard|full)$"),
    intraday_limit: int | None = Query(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return tools.read_market_overview(
        db=db,
        limit=limit,
        include_intraday=include_intraday,
        market_data_params=_market_data_params_from_query(
            include_intraday=include_intraday,
            payload_level=payload_level,
            intraday_limit=intraday_limit,
        ),
    )


@router.post("/ask", response_model=AiAskResponse)
def ask_omi(
    request: Request,
    payload: AiAskRequest,
    db: Session = Depends(get_db),
):
    try:
        return ai_ask.ask(db=db, payload=payload, server_policy=_ai_server_policy(request))
    except watchlist_service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ai_llm.OpenAILLMError as exc:
        _raise_llm_http_error(exc)


@router.post("/ask/stream")
def ask_omi_stream(
    request: Request,
    payload: AiAskRequest,
    db: Session = Depends(get_db),
):
    return StreamingResponse(
        ai_streaming.iter_ask_sse_events(
            db=db,
            payload=payload,
            server_policy=_ai_server_policy(request),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/memories",
    response_model=AiMemoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_memory(
    request: Request,
    payload: AiMemoryCreate,
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Creating AI memory")
    return ai_memory.serialize_memory(ai_memory.create_memory(db=db, payload=payload))


@router.get("/memories", response_model=list[AiMemoryRead])
def list_memories(
    memory_type: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    status_filter: str | None = Query(default="active", alias="status"),
    keyword: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = ai_memory.list_memories(
        db=db,
        memory_type=memory_type,
        scope_type=scope_type,
        scope_id=scope_id,
        status=status_filter,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return [ai_memory.serialize_memory(row) for row in rows]


@router.patch("/memories/{memory_id}", response_model=AiMemoryRead)
def update_memory(
    memory_id: int,
    request: Request,
    payload: AiMemoryUpdate,
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Updating AI memory")
    try:
        return ai_memory.serialize_memory(
            ai_memory.update_memory(db=db, memory_id=memory_id, payload=payload)
        )
    except ai_memory.AiMemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/memories/{memory_id}/archive", response_model=AiMemoryRead)
def archive_memory(
    memory_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Archiving AI memory")
    try:
        return ai_memory.serialize_memory(
            ai_memory.archive_memory(db=db, memory_id=memory_id)
        )
    except ai_memory.AiMemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reports", response_model=list[AiStoredReportRead])
def list_reports(
    report_type: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    strategy_profile: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = report_store.list_reports(
        db=db,
        report_type=report_type,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=strategy_profile,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [report_store.serialize_report(row, include_payload=False) for row in rows]


@router.get("/reports/{report_id}", response_model=AiStoredReportRead)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
):
    try:
        return report_store.serialize_report(report_store.get_report(db=db, report_id=report_id))
    except report_store.AiReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/stocks/{stock_id}/context", response_model=AiDataEnvelope)
def read_stock_context(
    stock_id: str,
    branch_days: int = Query(default=5, ge=1, le=120),
    bars: int = Query(default=120, ge=20, le=1000),
    revenue_months: int = Query(default=12, ge=1, le=120),
    financial_quarters: int = Query(default=8, ge=1, le=40),
    include_intraday: bool = Query(default=False),
    payload_level: str = Query(default="compact", pattern="^(summary|compact|standard|full)$"),
    intraday_limit: int | None = Query(default=None, ge=1, le=500),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    return tools.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
        bars=bars,
        revenue_months=revenue_months,
        financial_quarters=financial_quarters,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=_market_data_params_from_query(
            include_intraday=include_intraday,
            payload_level=payload_level,
            intraday_limit=intraday_limit,
        ),
    )


@router.get("/watchlists/{group_id}/context", response_model=AiDataEnvelope)
def read_watchlist_context(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = Query(default="score", pattern="^(watchlist|score|change_pct|volume)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    radar_mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    limit: int = Query(default=100, ge=20, le=500),
    db: Session = Depends(get_db),
):
    try:
        return tools.read_watchlist_context(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
            radar_mode=radar_mode,
            limit=limit,
        )
    except watchlist_service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/stocks/{stock_id}/brief", response_model=AiReportEnvelope)
def build_stock_brief(
    stock_id: str,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = Query(default=5, ge=1, le=120),
    include_intraday: bool = Query(default=False),
    payload_level: str = Query(default="compact", pattern="^(summary|compact|standard|full)$"),
    intraday_limit: int | None = Query(default=None, ge=1, le=500),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    return reports.build_stock_brief(
        db=db,
        stock_id=stock_id,
        strategy_profile=strategy_profile,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=_market_data_params_from_query(
            include_intraday=include_intraday,
            payload_level=payload_level,
            intraday_limit=intraday_limit,
        ),
    )


@router.post("/stocks/{stock_id}/brief/save", response_model=AiStoredReportRead)
def save_stock_brief(
    stock_id: str,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = Query(default=5, ge=1, le=120),
    include_intraday: bool = Query(default=False),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Saving stock brief")
    envelope = reports.build_stock_brief(
        db=db,
        stock_id=stock_id,
        strategy_profile=strategy_profile,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
    )
    return _save_brief_report(
        db=db,
        envelope=envelope,
        report_type="stock_brief",
        scope_type="stock",
        scope_id=stock_id,
        strategy_profile=envelope["strategy_profile"],
        title=f"Stock brief {stock_id}",
        tool_name="omi.generate_stock_brief",
        arguments={
            "stock_id": stock_id,
            "strategy_profile": strategy_profile,
            "branch_days": branch_days,
            "include_intraday": include_intraday,
            "analysis_horizon": analysis_horizon,
        },
    )


@router.post("/stocks/{stock_id}/brief/generate", response_model=AiStoredReportRead)
def generate_stock_llm_report(
    stock_id: str,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = Query(default=5, ge=1, le=120),
    include_intraday: bool = Query(default=False),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Generating stock LLM report")
    try:
        return orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=strategy_profile,
            branch_days=branch_days,
            include_intraday=include_intraday,
            analysis_horizon=analysis_horizon,
        )
    except ai_llm.OpenAILLMError as exc:
        _raise_llm_http_error(exc)


@router.get("/us-stocks/{symbol}/context", response_model=AiDataEnvelope)
def read_us_stock_context(
    symbol: str,
    include_intraday: bool = Query(default=False),
    payload_level: str = Query(default="compact", pattern="^(summary|compact|standard|full)$"),
    intraday_limit: int | None = Query(default=None, ge=1, le=500),
    session_scope: str = Query(default="regular", pattern="^(regular|extended|all)$"),
    daily_limit: int = Query(default=10, ge=1, le=200),
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    provider: str = Query(default="auto", pattern="^(auto|alphavantage|yahoo_chart)$"),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    return agentic_tools.read_us_stock_context(
        db=db,
        symbol=symbol,
        market_data_params=_market_data_params_from_query(
            include_intraday=include_intraday or analysis_horizon == "intraday",
            payload_level=payload_level,
            intraday_limit=intraday_limit,
            session_scope=session_scope,
            daily_limit=daily_limit,
            timeframe=timeframe,
            bars=bars,
            provider=provider,
        ),
    )


@router.get("/us-stocks/{symbol}/brief", response_model=AiReportEnvelope)
def build_us_stock_brief(
    symbol: str,
    strategy_profile: str = "short_term_momentum",
    include_intraday: bool = Query(default=False),
    payload_level: str = Query(default="compact", pattern="^(summary|compact|standard|full)$"),
    intraday_limit: int | None = Query(default=None, ge=1, le=500),
    session_scope: str = Query(default="regular", pattern="^(regular|extended|all)$"),
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    return reports.build_us_stock_brief(
        db=db,
        symbol=symbol,
        strategy_profile=strategy_profile,
        analysis_horizon=analysis_horizon,
        market_data_params=_market_data_params_from_query(
            include_intraday=include_intraday or analysis_horizon == "intraday",
            payload_level=payload_level,
            intraday_limit=intraday_limit,
            session_scope=session_scope,
        ),
    )


@router.post("/us-stocks/{symbol}/brief/save", response_model=AiStoredReportRead)
def save_us_stock_brief(
    symbol: str,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Saving US stock brief")
    envelope = reports.build_us_stock_brief(
        db=db,
        symbol=symbol,
        strategy_profile=strategy_profile,
        analysis_horizon=analysis_horizon,
    )
    target = (envelope.get("scope") or {}).get("target") or {}
    normalized_symbol = str(target.get("id") or symbol).upper()
    return _save_brief_report(
        db=db,
        envelope=envelope,
        report_type="us_stock_brief",
        scope_type="us_stock",
        scope_id=normalized_symbol,
        strategy_profile=envelope["strategy_profile"],
        title=f"US stock brief {normalized_symbol}",
        tool_name="omi.generate_us_stock_brief",
        arguments={
            "symbol": normalized_symbol,
            "strategy_profile": strategy_profile,
            "analysis_horizon": analysis_horizon,
        },
    )


@router.post("/us-stocks/{symbol}/brief/generate", response_model=AiStoredReportRead)
def generate_us_stock_llm_report(
    symbol: str,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    analysis_horizon: str = Query(default="swing", pattern="^(auto|intraday|short|swing|long)$"),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Generating US stock LLM report")
    try:
        return orchestrator.generate_us_stock_llm_report(
            db=db,
            symbol=symbol,
            strategy_profile=strategy_profile,
            analysis_horizon=analysis_horizon,
        )
    except ai_llm.OpenAILLMError as exc:
        _raise_llm_http_error(exc)


@router.get("/watchlists/{group_id}/brief", response_model=AiReportEnvelope)
def build_watchlist_brief(
    group_id: int,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = Query(default="score", pattern="^(watchlist|score|change_pct|volume)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    radar_mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    db: Session = Depends(get_db),
):
    try:
        return reports.build_watchlist_brief(
            db=db,
            group_id=group_id,
            strategy_profile=strategy_profile,
            rank_by=rank_by,
            sort_order=sort_order,
            radar_mode=radar_mode,
        )
    except watchlist_service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/watchlists/{group_id}/brief/generate", response_model=AiStoredReportRead)
def generate_watchlist_llm_report(
    group_id: int,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = Query(default="score", pattern="^(watchlist|score|change_pct|volume)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    radar_mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Generating watchlist LLM report")
    try:
        return orchestrator.generate_watchlist_llm_report(
            db=db,
            group_id=group_id,
            strategy_profile=strategy_profile,
            rank_by=rank_by,
            sort_order=sort_order,
            radar_mode=radar_mode,
        )
    except watchlist_service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ai_llm.OpenAILLMError as exc:
        _raise_llm_http_error(exc)


@router.post("/watchlists/{group_id}/brief/save", response_model=AiStoredReportRead)
def save_watchlist_brief(
    group_id: int,
    request: Request,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = Query(default="score", pattern="^(watchlist|score|change_pct|volume)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    radar_mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    db: Session = Depends(get_db),
):
    _require_trusted_ai_request(request, "Saving watchlist brief")
    try:
        envelope = reports.build_watchlist_brief(
            db=db,
            group_id=group_id,
            strategy_profile=strategy_profile,
            rank_by=rank_by,
            sort_order=sort_order,
            radar_mode=radar_mode,
        )
        return _save_brief_report(
            db=db,
            envelope=envelope,
            report_type="watchlist_brief",
            scope_type="watchlist",
            scope_id=str(group_id),
            strategy_profile=envelope["strategy_profile"],
            title=f"Watchlist brief {group_id}",
            tool_name="omi.generate_watchlist_brief",
            arguments={
                "group_id": group_id,
                "strategy_profile": strategy_profile,
                "rank_by": rank_by,
                "sort_order": sort_order,
                "radar_mode": radar_mode,
            },
        )
    except watchlist_service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
