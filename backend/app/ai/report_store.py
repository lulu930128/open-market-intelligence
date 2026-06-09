from __future__ import annotations

from datetime import date, datetime
from typing import Any
import json

from sqlalchemy.orm import Session

from app.db.models import AiReport, AiToolCall, utc_now


class AiReportNotFoundError(Exception):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return str(value)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _from_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _tool_call_dict(row: AiToolCall) -> dict[str, Any]:
    return {
        "id": row.id,
        "report_id": row.report_id,
        "tool_name": row.tool_name,
        "status": row.status,
        "source": row.source,
        "arguments": _from_json(row.arguments_json, {}),
        "result_summary": _from_json(row.result_summary_json, {}),
        "error_message": row.error_message,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
    }


def serialize_report(report: AiReport, include_payload: bool = True) -> dict[str, Any]:
    return {
        "id": report.id,
        "report_type": report.report_type,
        "scope_type": report.scope_type,
        "scope_id": report.scope_id,
        "strategy_profile": report.strategy_profile,
        "title": report.title,
        "as_of": report.as_of,
        "status": report.status,
        "model_name": report.model_name,
        "job_run_id": report.job_run_id,
        "summary": _from_json(report.summary_json, {}),
        "prompt": _from_json(report.prompt_json, {}),
        "payload": _from_json(report.payload_json, {}) if include_payload else {},
        "missing": _from_json(report.missing_json, []),
        "warnings": _from_json(report.warnings_json, []),
        "source_refs": _from_json(report.source_refs_json, []),
        "memory_refs": _from_json(report.memory_refs_json, []),
        "tool_calls": [_tool_call_dict(row) for row in report.tool_calls],
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def get_report(db: Session, report_id: int) -> AiReport:
    report = db.query(AiReport).filter(AiReport.id == report_id).first()

    if report is None:
        raise AiReportNotFoundError(f"AI report id={report_id} not found.")

    return report


def list_reports(
    db: Session,
    *,
    report_type: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    strategy_profile: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AiReport]:
    query = db.query(AiReport)

    if report_type:
        query = query.filter(AiReport.report_type == report_type)

    if scope_type:
        query = query.filter(AiReport.scope_type == scope_type)

    if scope_id:
        query = query.filter(AiReport.scope_id == scope_id)

    if strategy_profile:
        query = query.filter(AiReport.strategy_profile == strategy_profile)

    if status:
        query = query.filter(AiReport.status == status)

    return (
        query.order_by(AiReport.created_at.desc(), AiReport.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def save_report(
    db: Session,
    *,
    envelope: dict[str, Any],
    report_type: str,
    scope_type: str,
    scope_id: str | None,
    strategy_profile: str,
    title: str | None = None,
    model_name: str | None = None,
    job_run_id: int | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> AiReport:
    prompt = envelope.get("prompt") or {}
    memories = prompt.get("memories") or []
    memory_refs = [
        int(memory["id"])
        for memory in memories
        if isinstance(memory, dict) and isinstance(memory.get("id"), int)
    ]

    report = AiReport(
        report_type=report_type,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=strategy_profile,
        title=title,
        as_of=envelope.get("as_of"),
        status="success",
        model_name=model_name,
        job_run_id=job_run_id,
        summary_json=_to_json(envelope.get("summary") or {}),
        prompt_json=_to_json(prompt),
        payload_json=_to_json(envelope),
        missing_json=_to_json(envelope.get("missing") or []),
        warnings_json=_to_json(envelope.get("warnings") or []),
        source_refs_json=_to_json(envelope.get("source_refs") or []),
        memory_refs_json=_to_json(memory_refs),
    )
    db.add(report)
    db.flush()

    for tool_call in tool_calls or []:
        db.add(
            AiToolCall(
                report_id=report.id,
                tool_name=tool_call["tool_name"],
                status=tool_call.get("status", "success"),
                source=tool_call.get("source", "backend"),
                arguments_json=_to_json(tool_call.get("arguments") or {}),
                result_summary_json=_to_json(tool_call.get("result_summary") or {}),
                error_message=tool_call.get("error_message"),
                started_at=tool_call.get("started_at"),
                ended_at=tool_call.get("ended_at"),
                duration_ms=tool_call.get("duration_ms"),
            )
        )

    db.commit()
    db.refresh(report)
    return report


def report_tool_summary(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    analysis = data.get("analysis") if isinstance(data, dict) else None
    analysis_summary = {}
    if isinstance(analysis, dict) and analysis:
        analysis_summary = {
            "selected_horizon": analysis.get("selected_horizon"),
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": analysis.get("selected_score"),
            "selected_confidence": analysis.get("selected_confidence"),
        }

    return {
        "kind": envelope.get("kind"),
        "as_of": envelope.get("as_of"),
        "analysis": analysis_summary,
        "missing_count": len(envelope.get("missing") or []),
        "warning_count": len(envelope.get("warnings") or []),
        "source_ref_count": len(envelope.get("source_refs") or []),
    }
