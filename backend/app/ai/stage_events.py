from __future__ import annotations

from typing import Any


STAGE_LABELS = {
    "accepted": "收到問題",
    "resolving": "確認目標",
    "tool_execution": "工具執行",
    "evidence_passport": "證據護照",
    "question_understanding": "理解問題",
    "evidence_read": "讀取資料",
    "score_model": "五因子評分",
    "price_levels": "推導價位",
    "position_math": "部位試算",
    "decision_synthesis": "組合回答",
    "answer_ready": "回答就緒",
}
TOOL_LABELS = {
    "tw.refresh_stock_evidence": "台股資料刷新",
    "tw.refresh_watchlist_evidence": "自選群組刷新",
    "us.read_intraday_trend": "美股盤中趨勢讀取",
    "us.refresh_daily_price": "美股日線刷新",
    "us.refresh_company_profile": "美股公司資料刷新",
    "us.refresh_sec_facts": "SEC 財報資料刷新",
    "us.refresh_finra_short_volume": "FINRA 放空資料刷新",
    "us.refresh_fred_macro": "FRED 總經資料刷新",
}


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


def status_payload(
    *,
    stage: str,
    message: str,
    sequence: int,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "stage_label": stage_label(stage),
        "message": message,
        "sequence": sequence,
        **extra,
    }


def progress_status_payload(
    progress_event: dict[str, Any],
    *,
    sequence: int,
) -> dict[str, Any] | None:
    if not isinstance(progress_event, dict):
        return None

    stage = _text_value(progress_event.get("stage"))
    message = _text_value(progress_event.get("message"))
    if not stage or not message:
        return None

    extra = {
        key: value
        for key, value in progress_event.items()
        if key not in {"stage", "stage_label", "message", "sequence"}
    }
    return status_payload(
        stage=stage,
        message=message,
        sequence=sequence,
        **extra,
    )


def initial_status_payloads(
    *,
    contract_version: str,
    start_sequence: int = 1,
) -> list[dict[str, Any]]:
    return [
        status_payload(
            stage="accepted",
            message="OMI 已收到 AI 請求。",
            sequence=start_sequence,
            contract_version=contract_version,
            phase="completed",
            dedupe_key="accepted:completed",
        ),
        status_payload(
            stage="resolving",
            message="正在確認目標、資料 freshness、可信度與可用工具。",
            sequence=start_sequence + 1,
            phase="running",
            dedupe_key="resolving:running",
        ),
    ]


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tool_label(tool_name: str) -> str:
    return TOOL_LABELS.get(tool_name, tool_name)


def _tool_status_message(tool_run: dict[str, Any]) -> str:
    tool_name = _text_value(tool_run.get("tool")) or _text_value(tool_run.get("tool_name")) or "工具"
    label = _tool_label(tool_name)
    status = (_text_value(tool_run.get("status")) or "unknown").lower()
    error = _text_value(tool_run.get("error")) or _text_value(tool_run.get("error_message"))

    if status == "success":
        return f"{label}已完成。"
    if status == "blocked":
        return f"{label}未執行" + (f"：{error}。" if error else "。")
    if status in {"failed", "error"}:
        return f"{label}失敗" + (f"：{error}。" if error else "。")
    if status == "skipped":
        return f"{label}已略過。"
    return f"{label}狀態：{status}。"


def tool_status_payload(
    tool_run: dict[str, Any],
    *,
    sequence: int,
) -> dict[str, Any] | None:
    if not isinstance(tool_run, dict):
        return None
    tool_name = _text_value(tool_run.get("tool")) or _text_value(tool_run.get("tool_name"))
    if not tool_name:
        return None
    status = _text_value(tool_run.get("status"))
    phase = {
        "success": "completed",
        "blocked": "blocked",
        "skipped": "skipped",
        "error": "failed",
        "failed": "failed",
    }.get((status or "").lower(), "completed")
    return status_payload(
        stage="tool_execution",
        message=_tool_status_message(tool_run),
        sequence=sequence,
        phase=phase,
        dedupe_key=f"tool:{tool_name}:{status or 'unknown'}",
        tool=tool_name,
        tool_label=_tool_label(tool_name),
        status=status,
    )


def evidence_status_payload(
    evidence_passport: dict[str, Any],
    *,
    sequence: int,
) -> dict[str, Any] | None:
    if not isinstance(evidence_passport, dict) or not evidence_passport:
        return None
    trust_level = _text_value(evidence_passport.get("trust_level"))
    trust_score = evidence_passport.get("trust_score")
    score_text = None
    if not isinstance(trust_score, bool) and isinstance(trust_score, (int, float)):
        score_text = f"{trust_score:.0f}"

    bits = []
    if trust_level:
        bits.append(f"信任度 {trust_level}")
    if score_text:
        bits.append(f"分數 {score_text}")
    message = "已建立證據護照" + (f"：{'，'.join(bits)}。" if bits else "。")
    return status_payload(
        stage="evidence_passport",
        message=message,
        sequence=sequence,
        phase="completed",
        dedupe_key="evidence_passport:completed",
        trust_level=trust_level,
        trust_score=trust_score,
    )


def reasoning_status_payloads(
    reasoning_steps: list[Any],
    *,
    start_sequence: int,
) -> tuple[list[dict[str, Any]], int]:
    payloads: list[dict[str, Any]] = []
    sequence = start_sequence
    for step in reasoning_steps:
        if not isinstance(step, dict):
            continue
        stage = _text_value(step.get("stage"))
        message = _text_value(step.get("message"))
        if not stage or not message:
            continue
        payloads.append(
            status_payload(
                stage=stage,
                message=message,
                sequence=sequence,
                phase="completed",
                dedupe_key=f"reasoning:{stage}:{message}",
            )
        )
        sequence += 1
    return payloads, sequence


def response_status_payloads(
    response: dict[str, Any],
    *,
    start_sequence: int,
) -> tuple[list[dict[str, Any]], int]:
    payloads: list[dict[str, Any]] = []
    sequence = start_sequence

    evidence = response.get("evidence_passport")
    evidence_payload = (
        evidence_status_payload(evidence, sequence=sequence)
        if isinstance(evidence, dict)
        else None
    )
    if evidence_payload:
        payloads.append(evidence_payload)
        sequence += 1

    for tool_run in response.get("tool_runs") or []:
        if not isinstance(tool_run, dict):
            continue
        tool_payload = tool_status_payload(tool_run, sequence=sequence)
        if tool_payload:
            payloads.append(tool_payload)
            sequence += 1

    reasoning_payloads, sequence = reasoning_status_payloads(
        response.get("reasoning_steps") or [],
        start_sequence=sequence,
    )
    payloads.extend(reasoning_payloads)

    payloads.append(
        status_payload(
            stage="answer_ready",
            message="已完成資料檢查與回應組裝。",
            sequence=sequence,
            phase="completed",
            dedupe_key="answer_ready:completed",
            answer_ready=bool(response.get("answer_ready", True)),
            report_level=response.get("report_level"),
        )
    )
    sequence += 1
    return payloads, sequence
