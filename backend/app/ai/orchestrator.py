from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any
import copy

from sqlalchemy.orm import Session

from app.ai import llm, memory as ai_memory, report_store, reports


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _memory_ids_from_envelope(envelope: dict[str, Any]) -> list[int]:
    prompt = envelope.get("prompt") or {}
    memories = prompt.get("memories") or []
    return [
        int(memory["id"])
        for memory in memories
        if isinstance(memory, dict) and isinstance(memory.get("id"), int)
    ]


def _openai_tool_call(
    *,
    arguments: dict[str, Any],
    llm_result: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
    duration_ms: int,
) -> dict[str, Any]:
    report = llm_result.get("report") or {}
    return {
        "tool_name": "openai.responses.create",
        "source": "openai",
        "arguments": arguments,
        "result_summary": {
            "response_id": llm_result.get("response_id"),
            "model": llm_result.get("model"),
            "headline": report.get("headline"),
            "stance": report.get("stance"),
            "confidence": report.get("confidence"),
            "usage": llm_result.get("usage") or {},
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
    }


def _attach_llm_result(envelope: dict[str, Any], llm_result: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(envelope)
    summary = dict(enriched.get("summary") or {})
    summary["llm"] = llm_result["report"]
    summary["llm_usage"] = llm_result.get("usage") or {}
    enriched["summary"] = summary
    enriched["llm"] = {
        "provider": "openai",
        "model": llm_result.get("model"),
        "response_id": llm_result.get("response_id"),
        "report": llm_result["report"],
    }
    return enriched


def _build_non_persistent_analysis(envelope: dict[str, Any], *, kind: str) -> dict[str, Any]:
    llm_result = llm.generate_structured_report(envelope)
    enriched = _attach_llm_result(envelope, llm_result)
    enriched["kind"] = kind
    enriched["llm"]["usage"] = llm_result.get("usage") or {}
    warnings = list(enriched.get("warnings") or [])
    warnings.append("LLM analysis was generated on demand and was not persisted.")
    enriched["warnings"] = list(dict.fromkeys(warnings))
    return enriched


def _report_title(value: Any, fallback: str) -> str:
    title = str(value or fallback).strip() or fallback
    return title[:240]


def generate_stock_llm_analysis(
    db: Session,
    stock_id: str,
    *,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = 5,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    envelope = reports.build_stock_brief(
        db=db,
        stock_id=stock_id,
        strategy_profile=strategy_profile,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
    )
    return _build_non_persistent_analysis(envelope, kind="stock_llm_analysis")


def generate_watchlist_llm_analysis(
    db: Session,
    group_id: int,
    *,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = "score",
    sort_order: str = "desc",
) -> dict[str, Any]:
    envelope = reports.build_watchlist_brief(
        db=db,
        group_id=group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
    )
    return _build_non_persistent_analysis(envelope, kind="watchlist_llm_analysis")


def generate_stock_llm_report(
    db: Session,
    stock_id: str,
    *,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = 5,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    envelope = reports.build_stock_brief(
        db=db,
        stock_id=stock_id,
        strategy_profile=strategy_profile,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
    )

    started_at = _now()
    started_tick = perf_counter()
    llm_result = llm.generate_structured_report(envelope)
    ended_at = _now()
    duration_ms = int((perf_counter() - started_tick) * 1000)

    enriched = _attach_llm_result(envelope, llm_result)
    report = report_store.save_report(
        db=db,
        envelope=enriched,
        report_type="stock_llm_brief",
        scope_type="stock",
        scope_id=stock_id,
        strategy_profile=enriched["strategy_profile"],
        title=_report_title(llm_result["report"].get("headline"), f"AI stock brief {stock_id}"),
        model_name=llm_result.get("model"),
        tool_calls=[
            {
                "tool_name": "omi.generate_stock_brief",
                "source": "backend",
                "arguments": {
                    "stock_id": stock_id,
                    "strategy_profile": strategy_profile,
                    "branch_days": branch_days,
                    "include_intraday": include_intraday,
                    "analysis_horizon": analysis_horizon,
                },
                "result_summary": report_store.report_tool_summary(envelope),
            },
            _openai_tool_call(
                arguments={
                    "model": llm_result.get("model"),
                    "response_format": "omi_research_report",
                },
                llm_result=llm_result,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
            ),
        ],
    )
    ai_memory.mark_memories_used(db, _memory_ids_from_envelope(envelope))
    return report_store.serialize_report(report)


def generate_watchlist_llm_report(
    db: Session,
    group_id: int,
    *,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = "score",
    sort_order: str = "desc",
) -> dict[str, Any]:
    envelope = reports.build_watchlist_brief(
        db=db,
        group_id=group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
    )

    started_at = _now()
    started_tick = perf_counter()
    llm_result = llm.generate_structured_report(envelope)
    ended_at = _now()
    duration_ms = int((perf_counter() - started_tick) * 1000)

    enriched = _attach_llm_result(envelope, llm_result)
    report = report_store.save_report(
        db=db,
        envelope=enriched,
        report_type="watchlist_llm_brief",
        scope_type="watchlist",
        scope_id=str(group_id),
        strategy_profile=enriched["strategy_profile"],
        title=_report_title(
            llm_result["report"].get("headline"),
            f"AI watchlist brief {group_id}",
        ),
        model_name=llm_result.get("model"),
        tool_calls=[
            {
                "tool_name": "omi.generate_watchlist_brief",
                "source": "backend",
                "arguments": {
                    "group_id": group_id,
                    "strategy_profile": strategy_profile,
                    "rank_by": rank_by,
                    "sort_order": sort_order,
                },
                "result_summary": report_store.report_tool_summary(envelope),
            },
            _openai_tool_call(
                arguments={
                    "model": llm_result.get("model"),
                    "response_format": "omi_research_report",
                },
                llm_result=llm_result,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
            ),
        ],
    )
    ai_memory.mark_memories_used(db, _memory_ids_from_envelope(envelope))
    return report_store.serialize_report(report)
