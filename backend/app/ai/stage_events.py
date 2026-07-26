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
TOOL_STATUS_PRIORITY = {
    "running": 1,
    "skipped": 2,
    "blocked": 3,
    "success": 4,
    "completed": 4,
    "error": 5,
    "failed": 5,
}
TOOL_STATUS_LABELS = {
    "success": "成功",
    "completed": "成功",
    "blocked": "阻擋",
    "skipped": "略過",
    "error": "失敗",
    "failed": "失敗",
    "running": "執行中",
    "unknown": "未知",
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

    if stage == "tool_execution" and (
        _text_value(progress_event.get("tool")) or _text_value(progress_event.get("tool_name"))
    ):
        return tool_status_payload(progress_event, sequence=sequence)

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


def _tool_scope(tool_run: dict[str, Any]) -> str:
    tool_name = _text_value(tool_run.get("tool")) or _text_value(tool_run.get("tool_name")) or ""
    if tool_name != "us.refresh_daily_price":
        return "default"

    reason = (_text_value(tool_run.get("reason")) or "").lower()
    if any(marker in reason for marker in ("隔夜", "overnight", "cross_market", "us_overnight")):
        return "us_overnight_reference"
    return "default"


def _tool_label(tool_name: str, tool_run: dict[str, Any] | None = None) -> str:
    if tool_run is not None and _tool_scope(tool_run) == "us_overnight_reference":
        return "美股隔夜參考資料"
    return TOOL_LABELS.get(tool_name, tool_name)


def _status_counts_text(counts: dict[str, int]) -> str | None:
    parts = []
    for key in ("success", "blocked", "skipped", "error", "failed", "running", "unknown"):
        count = counts.get(key)
        if not isinstance(count, int) or count <= 0:
            continue
        label = TOOL_STATUS_LABELS.get(key, key)
        if key == "failed" and counts.get("error"):
            continue
        parts.append(f"{label} {count}")
    return "、".join(parts) if parts else None


def _tool_status_message(tool_run: dict[str, Any]) -> str:
    tool_name = _text_value(tool_run.get("tool")) or _text_value(tool_run.get("tool_name")) or "工具"
    label = _tool_label(tool_name, tool_run)
    status = (_text_value(tool_run.get("status")) or "unknown").lower()
    error = _text_value(tool_run.get("error")) or _text_value(tool_run.get("error_message"))
    counts = tool_run.get("status_counts") if isinstance(tool_run.get("status_counts"), dict) else {}
    counts_text = _status_counts_text(counts)
    count_suffix = f"（{counts_text}）" if counts_text else ""

    if status == "success":
        return f"{label}已完成{count_suffix}。"
    if status == "running":
        return f"{label}執行中。"
    if status == "blocked":
        return f"{label}未執行{count_suffix}" + (f"：{error}。" if error else "。")
    if status in {"failed", "error"}:
        return f"{label}失敗{count_suffix}" + (f"：{error}。" if error else "。")
    if status == "skipped":
        return f"{label}已略過{count_suffix}。"
    return f"{label}狀態：{status}。"


def _tool_status(status: Any) -> str:
    return (_text_value(status) or "unknown").lower()


def _tool_group_key(tool_run: dict[str, Any]) -> tuple[str, str] | None:
    tool_name = _text_value(tool_run.get("tool")) or _text_value(tool_run.get("tool_name"))
    if not tool_name:
        return None
    return tool_name, _tool_scope(tool_run)


def _representative_tool_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    def priority(run: dict[str, Any]) -> int:
        return TOOL_STATUS_PRIORITY.get(_tool_status(run.get("status")), 0)

    return max(runs, key=priority)


def _aggregate_tool_runs(tool_runs: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for tool_run in tool_runs:
        if not isinstance(tool_run, dict):
            continue
        key = _tool_group_key(tool_run)
        if key is None:
            continue
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(tool_run)

    aggregated: list[dict[str, Any]] = []
    for key in ordered_keys:
        runs = grouped[key]
        representative = dict(_representative_tool_run(runs))
        counts: dict[str, int] = {}
        for run in runs:
            status = _tool_status(run.get("status"))
            counts[status] = counts.get(status, 0) + 1
        representative["tool"] = key[0]
        representative["tool_scope"] = key[1]
        representative["attempt_count"] = len(runs)
        representative["status_counts"] = counts
        aggregated.append(representative)
    return aggregated


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
    status_key = (status or "unknown").lower()
    tool_scope = _tool_scope(tool_run)
    phase = {
        "running": "running",
        "success": "completed",
        "blocked": "blocked",
        "skipped": "skipped",
        "error": "failed",
        "failed": "failed",
    }.get(status_key, "completed")
    payload = status_payload(
        stage="tool_execution",
        message=_tool_status_message(tool_run),
        sequence=sequence,
        phase=phase,
        dedupe_key=f"tool:{tool_name}:{tool_scope}:{status or 'unknown'}",
        signal_key=f"tool:{tool_name}:{tool_scope}",
        tool=tool_name,
        tool_label=_tool_label(tool_name, tool_run),
        tool_scope=tool_scope,
        status=status,
    )
    for key in (
        "reason",
        "external_fetch",
        "writes_cache",
        "duration_ms",
        "attempt_count",
        "status_counts",
    ):
        if key in tool_run:
            payload[key] = tool_run[key]
    return payload


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

    canonical_evidence = (
        response.get("evidence")
        if isinstance(response.get("evidence"), dict)
        else {}
    )
    evidence = response.get("evidence_passport") or canonical_evidence.get("passport")
    evidence_payload = (
        evidence_status_payload(evidence, sequence=sequence)
        if isinstance(evidence, dict)
        else None
    )
    if evidence_payload:
        payloads.append(evidence_payload)
        sequence += 1

    canonical_execution = (
        response.get("execution")
        if isinstance(response.get("execution"), dict)
        else {}
    )
    tool_runs = response.get("tool_runs") or canonical_execution.get("tool_runs") or []
    for tool_run in _aggregate_tool_runs(tool_runs):
        tool_payload = tool_status_payload(tool_run, sequence=sequence)
        if tool_payload:
            payloads.append(tool_payload)
            sequence += 1

    reasoning_payloads, sequence = reasoning_status_payloads(
        response.get("reasoning_steps")
        or canonical_execution.get("reasoning_steps")
        or [],
        start_sequence=sequence,
    )
    payloads.extend(reasoning_payloads)

    canonical_status = (
        response.get("status")
        if isinstance(response.get("status"), dict)
        else {}
    )
    canonical_readiness = (
        canonical_status.get("readiness")
        if isinstance(canonical_status.get("readiness"), dict)
        else {}
    )
    payloads.append(
        status_payload(
            stage="answer_ready",
            message="已完成資料檢查與回應組裝。",
            sequence=sequence,
            phase="completed",
            dedupe_key="answer_ready:completed",
            answer_ready=bool(
                response.get(
                    "answer_ready",
                    canonical_readiness.get("answer_ready", True),
                )
            ),
            report_level=response.get("report_level")
            or canonical_execution.get("report_level"),
        )
    )
    sequence += 1
    return payloads, sequence
