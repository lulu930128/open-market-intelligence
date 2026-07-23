from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
import json
from queue import Queue
from threading import Thread
from typing import Any

from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import llm as ai_llm
from app.ai import stage_events
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


def _tool_run_event_payload(tool_run: dict[str, Any]) -> dict[str, Any]:
    payload = dict(tool_run)
    status_payload = stage_events.tool_status_payload(tool_run, sequence=0)
    if not status_payload:
        return payload
    for key in (
        "message",
        "phase",
        "dedupe_key",
        "signal_key",
        "tool_label",
        "tool_scope",
    ):
        if key in status_payload:
            payload[key] = status_payload[key]
    return payload


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
    canonical_answer = (
        response.get("answer")
        if isinstance(response.get("answer"), dict)
        else {}
    )
    canonical_text = _first_text(
        canonical_answer.get("text"),
        canonical_answer.get("detail"),
        canonical_answer.get("headline"),
    )
    if canonical_text:
        return canonical_text
    canonical_summary = canonical_answer.get("summary")
    if isinstance(canonical_summary, list) and canonical_summary:
        return "\n".join(
            str(line)
            for line in canonical_summary
            if str(line).strip()
        )

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


def _status_dedupe_key(payload: dict[str, Any]) -> tuple[str, ...]:
    stage = str(payload.get("stage") or "")
    dedupe_key = payload.get("dedupe_key")
    if dedupe_key:
        return (stage, str(dedupe_key))
    if stage == "tool_execution":
        return (
            stage,
            str(payload.get("tool") or ""),
            str(payload.get("status") or ""),
        )
    return (
        stage,
        str(payload.get("phase") or ""),
        str(payload.get("message") or ""),
    )


def _ask_worker(
    *,
    event_queue: Queue[tuple[str, Any]],
    db: Session,
    payload: AiAskRequest,
    server_policy: ai_ask.AiAskServerPolicy,
) -> None:
    def progress_callback(progress_event: dict[str, Any]) -> None:
        event_queue.put(("progress", progress_event))

    try:
        response = ai_ask.ask(
            db=db,
            payload=payload,
            server_policy=server_policy,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        event_queue.put(("error", exc))
    else:
        event_queue.put(("response", response))
    finally:
        event_queue.put(("worker_done", None))


def iter_ask_sse_events(
    *,
    db: Session,
    payload: AiAskRequest,
    server_policy: ai_ask.AiAskServerPolicy,
) -> Iterator[str]:
    initial_payloads = stage_events.initial_status_payloads(
        contract_version=payload.contract_version,
    )
    emitted_statuses: set[tuple[str, ...]] = set()
    for status_payload in initial_payloads:
        emitted_statuses.add(_status_dedupe_key(status_payload))
        yield sse_event("status", status_payload)
    sequence = len(initial_payloads) + 1

    event_queue: Queue[tuple[str, Any]] = Queue()
    worker = Thread(
        target=_ask_worker,
        kwargs={
            "event_queue": event_queue,
            "db": db,
            "payload": payload,
            "server_policy": server_policy,
        },
        name="omi-ai-ask-stream",
        daemon=True,
    )
    worker.start()

    response: dict[str, Any] | None = None
    try:
        while True:
            event_kind, event_payload = event_queue.get()
            if event_kind == "progress":
                status_payload = stage_events.progress_status_payload(
                    event_payload,
                    sequence=sequence,
                )
                if status_payload:
                    status_key = _status_dedupe_key(status_payload)
                    if status_key not in emitted_statuses:
                        emitted_statuses.add(status_key)
                        yield sse_event("status", status_payload)
                        sequence += 1
                continue

            if event_kind == "error":
                yield sse_event("error", _error_payload(event_payload))
                yield sse_event(
                    "done",
                    {
                        "ok": False,
                        "transport_ok": False,
                        "request_status": "transport_error",
                    },
                )
                return

            if event_kind == "response":
                response = event_payload
                continue

            if event_kind == "worker_done":
                break
    finally:
        worker.join(timeout=1)

    if response is None:
        yield sse_event(
            "error",
            {"status_code": 500, "error": "OMI stream worker finished without a response.", "kind": "internal_error"},
        )
        yield sse_event(
            "done",
            {
                "ok": False,
                "transport_ok": False,
                "request_status": "transport_error",
            },
        )
        return

    canonical_evidence = (
        response.get("evidence")
        if isinstance(response.get("evidence"), dict)
        else {}
    )
    evidence = response.get("evidence_passport") or canonical_evidence.get("passport")
    if isinstance(evidence, dict) and evidence:
        yield sse_event("evidence", evidence)

    canonical_execution = (
        response.get("execution")
        if isinstance(response.get("execution"), dict)
        else {}
    )
    tool_runs = response.get("tool_runs") or canonical_execution.get("tool_runs") or []
    for tool_run in tool_runs:
        if isinstance(tool_run, dict):
            yield sse_event("tool_run", _tool_run_event_payload(tool_run))

    status_payloads, sequence = stage_events.response_status_payloads(
        response,
        start_sequence=sequence,
    )
    for status_payload in status_payloads:
        status_key = _status_dedupe_key(status_payload)
        if status_key in emitted_statuses:
            continue
        emitted_statuses.add(status_key)
        yield sse_event("status", status_payload)

    answer_text = extract_answer_text(response)
    for chunk in chunk_text(answer_text):
        yield sse_event("delta", {"text": chunk})

    yield sse_event("final", response)
    business_ok = response.get("ok") is not False
    yield sse_event(
        "done",
        {
            "ok": business_ok,
            "transport_ok": True,
            "request_status": response.get("request_status") or "completed",
        },
    )
