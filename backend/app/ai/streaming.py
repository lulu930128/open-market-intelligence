from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
import json
from typing import Any

from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import llm as ai_llm
from app.ai.schemas import AiAskRequest
from app.watchlists import service as watchlist_service


DEFAULT_DELTA_CHARS = 160


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=_json_default)
    return f"event: {event}\ndata: {payload}\n\n"


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lines_from_report(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    headline = _first_text(report.get("headline"))
    if headline:
        lines.append(f"結論：{headline}")

    sections = (
        ("key_observations", "觀察"),
        ("interpretation", "解讀"),
        ("risks", "風險"),
        ("missing_data", "資料限制"),
        ("next_checks", "下一步"),
    )
    for key, label in sections:
        values = report.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines.append(f"{label}：")
        lines.extend(f"- {value}" for value in values if str(value).strip())

    disclaimer = _first_text(report.get("disclaimer"))
    if disclaimer:
        lines.append(f"限制：{disclaimer}")
    return lines


def extract_answer_text(response: dict[str, Any]) -> str:
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}

    human_answer = analysis.get("human_answer") if isinstance(analysis.get("human_answer"), dict) else {}
    text = _first_text(human_answer.get("text"))
    if text:
        return text

    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    overview_human = overview.get("human_answer") if isinstance(overview.get("human_answer"), dict) else {}
    text = _first_text(overview_human.get("text"))
    if text:
        return text

    llm_report = (
        (result.get("llm") or {}).get("report")
        if isinstance(result.get("llm"), dict)
        else None
    )
    if not isinstance(llm_report, dict):
        llm_report = summary.get("llm") if isinstance(summary.get("llm"), dict) else None
    if isinstance(llm_report, dict):
        lines = _lines_from_report(llm_report)
        if lines:
            return "\n".join(lines)

    outline = analysis.get("answer_outline")
    if isinstance(outline, list) and outline:
        return "\n".join(str(line) for line in outline if str(line).strip())

    text = _first_text(
        analysis.get("display"),
        (summary.get("analysis") or {}).get("display") if isinstance(summary.get("analysis"), dict) else None,
        result.get("message"),
    )
    if text:
        return text

    highlights = summary.get("highlights")
    if isinstance(highlights, list) and highlights:
        return "\n".join(str(line) for line in highlights if str(line).strip())

    action = _first_text(response.get("action"))
    target = response.get("target") if isinstance(response.get("target"), dict) else {}
    target_label = _first_text(target.get("label"), target.get("id"), target.get("type")) or "目前目標"
    return f"OMI 已完成 {action or '資料讀取'}：{target_label}。"


def chunk_text(text: str, *, max_chars: int = DEFAULT_DELTA_CHARS) -> Iterator[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.splitlines(keepends=True):
        if len(line) <= max_chars:
            yield line
            continue
        for index in range(0, len(line), max_chars):
            yield line[index : index + max_chars]


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, watchlist_service.WatchlistGroupNotFoundError):
        return {"status_code": 404, "error": str(exc), "kind": "watchlist_not_found"}
    if isinstance(exc, ValueError):
        return {"status_code": 400, "error": str(exc), "kind": "bad_request"}
    if isinstance(exc, ai_llm.OpenAIConfigurationError):
        return {"status_code": 503, "error": str(exc), "kind": "llm_configuration_error"}
    if isinstance(exc, ai_llm.OpenAIHTTPError):
        return {"status_code": 502, "error": str(exc), "kind": "llm_http_error"}
    if isinstance(exc, ai_llm.OpenAILLMError):
        return {"status_code": 502, "error": str(exc), "kind": "llm_error"}
    return {"status_code": 500, "error": str(exc), "kind": "internal_error"}


def iter_ask_sse_events(
    *,
    db: Session,
    payload: AiAskRequest,
    server_policy: ai_ask.AiAskServerPolicy,
) -> Iterator[str]:
    yield sse_event(
        "status",
        {
            "stage": "accepted",
            "message": "OMI 已收到 AI 請求。",
            "contract_version": payload.contract_version,
        },
    )
    yield sse_event(
        "status",
        {
            "stage": "resolving",
            "message": "正在確認目標、資料 freshness、可信度與可用工具。",
        },
    )

    try:
        response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)
    except Exception as exc:
        yield sse_event("error", _error_payload(exc))
        yield sse_event("done", {"ok": False})
        return

    evidence = response.get("evidence_passport")
    if isinstance(evidence, dict) and evidence:
        yield sse_event("evidence", evidence)

    for tool_run in response.get("tool_runs") or []:
        if isinstance(tool_run, dict):
            yield sse_event("tool_run", tool_run)

    yield sse_event(
        "status",
        {
            "stage": "answer_ready",
            "message": "已完成資料檢查與回應組裝。",
            "answer_ready": bool(response.get("answer_ready", True)),
            "report_level": response.get("report_level"),
        },
    )

    answer_text = extract_answer_text(response)
    for chunk in chunk_text(answer_text):
        yield sse_event("delta", {"text": chunk})

    yield sse_event("final", response)
    yield sse_event("done", {"ok": True})
