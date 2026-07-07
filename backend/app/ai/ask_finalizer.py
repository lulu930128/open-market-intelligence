from __future__ import annotations

from typing import Any

from app.ai import ask_response_support, scope_resolution
from app.ai.evidence_passport import build_evidence_passport
from app.ai.schemas import AiAskRequest


_BASE_RESULT_KEYS = (
    "kind",
    "generated_at",
    "as_of",
    "scope",
    "strategy_profile",
    "response_preferences",
    "missing",
    "warnings",
    "source_refs",
    "evidence_passport",
)


def _base_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in _BASE_RESULT_KEYS if key in result}


def _brief_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        key: value
        for key, value in summary.items()
        if key not in {"decision_evidence"}
    }


def _compact_result_data(result: dict[str, Any]) -> dict[str, Any] | None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact = data.get("compact") if isinstance(data.get("compact"), dict) else {}
    if not compact:
        return None

    output: dict[str, Any] = {"compact": compact}
    payload_level = compact.get("payload_level")
    if payload_level:
        output["payload_level"] = payload_level
    quote = compact.get("quote") if isinstance(compact.get("quote"), dict) else {}
    if quote:
        output["quote"] = quote
    intraday_bars = compact.get("intraday_bars") if isinstance(compact.get("intraday_bars"), dict) else {}
    if intraday_bars:
        output["intraday_bars"] = intraday_bars
    technical = compact.get("technical") if isinstance(compact.get("technical"), dict) else {}
    if technical:
        output["technical"] = technical
        analysis = technical.get("analysis") if isinstance(technical.get("analysis"), dict) else {}
        if analysis:
            output["analysis"] = analysis
    freshness_by_domain = (
        compact.get("freshness_by_domain")
        if isinstance(compact.get("freshness_by_domain"), dict)
        else {}
    )
    if freshness_by_domain:
        output["freshness_by_domain"] = freshness_by_domain
    slots = compact.get("slots") if isinstance(compact.get("slots"), dict) else {}
    if slots:
        output["slots"] = slots
    return output


def _stock_from_compact(compact: dict[str, Any]) -> dict[str, Any]:
    target = compact.get("target") if isinstance(compact.get("target"), dict) else {}
    stock: dict[str, Any] = {}
    if target.get("type"):
        stock["type"] = target.get("type")
    if target.get("id"):
        stock["id"] = target.get("id")
    if target.get("label"):
        stock["name"] = target.get("label")
    if target.get("market"):
        stock["market"] = target.get("market")
    return stock


def _select_intraday_series(series: dict[str, Any]) -> dict[str, Any]:
    for interval in ("1m", "5m"):
        value = series.get(interval)
        if isinstance(value, dict) and (value.get("latest") or value.get("returned_point_count")):
            return value

    for value in series.values():
        if isinstance(value, dict) and (value.get("latest") or value.get("returned_point_count")):
            return value

    for interval in ("1m", "5m"):
        value = series.get(interval)
        if isinstance(value, dict):
            return value

    for value in series.values():
        if isinstance(value, dict):
            return value

    return {}


def _intraday_summary_from_compact(intraday_bars: dict[str, Any]) -> dict[str, Any]:
    if not intraday_bars:
        return {}

    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    selected = _select_intraday_series(series)
    points = selected.get("points") if isinstance(selected.get("points"), list) else []
    latest = selected.get("latest") if isinstance(selected.get("latest"), dict) else None
    enabled = bool(intraday_bars.get("enabled"))
    returned_count = selected.get("returned_point_count")
    if not isinstance(returned_count, int):
        returned_count = len(points)

    if not enabled:
        status = "not_requested"
    elif latest or returned_count > 0:
        status = "ok"
    else:
        status = "missing"

    latest_time = latest.get("time") if isinstance(latest, dict) else None
    source = selected.get("source") or selected.get("provider")
    if not source:
        source = "not_requested" if not enabled else "not_available"

    return {
        "status": status,
        "source": source,
        "interval": selected.get("interval"),
        "point_count": selected.get("point_count") or returned_count,
        "returned_point_count": returned_count,
        "latest_point": latest,
        "last_update": selected.get("to_time") or latest_time,
        "is_realtime": status == "ok",
        "bars": points,
        "warnings": intraday_bars.get("warnings") or [],
    }


def _apply_stock_compact_fields(output: dict[str, Any], compact: dict[str, Any]) -> None:
    if not compact:
        return

    target = _stock_from_compact(compact)
    if target:
        if target.get("type") in {"tw_stock", "stock"}:
            output["stock"] = target
        else:
            output["target"] = target

    quote = compact.get("quote") if isinstance(compact.get("quote"), dict) else {}
    if quote:
        output["quote"] = quote

    intraday_bars = compact.get("intraday_bars") if isinstance(compact.get("intraday_bars"), dict) else {}
    intraday = _intraday_summary_from_compact(intraday_bars)
    if intraday:
        output["intraday"] = intraday

    technical = compact.get("technical") if isinstance(compact.get("technical"), dict) else {}
    analysis = technical.get("analysis") if isinstance(technical.get("analysis"), dict) else {}
    if analysis:
        output["analysis"] = analysis

    freshness = (
        compact.get("freshness_by_domain")
        if isinstance(compact.get("freshness_by_domain"), dict)
        else {}
    )
    if freshness:
        output["freshness"] = freshness

    slots = compact.get("slots") if isinstance(compact.get("slots"), dict) else {}
    if slots:
        output["slots"] = slots


def _apply_market_brief_fields(output: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get("kind") != "market_brief":
        return

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    data_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    summary_source = summary or data_summary

    output["latest_trade_date"] = result.get("as_of") or summary_source.get("as_of")
    for key in (
        "breadth",
        "distribution",
        "top_gainers",
        "top_losers",
        "value_leaders",
        "top_industries",
        "weak_industries",
        "index_intraday",
        "slots",
    ):
        if key in data:
            output[key] = data[key]
        elif key in summary_source:
            output[key] = summary_source[key]


def _project_data_only_result(result: dict[str, Any]) -> dict[str, Any]:
    compact_data = _compact_result_data(result)
    if not compact_data:
        return result

    output = _base_result(result)
    output["data"] = compact_data
    compact = compact_data.get("compact") if isinstance(compact_data.get("compact"), dict) else {}
    _apply_stock_compact_fields(output, compact)
    output["result_view"] = {
        "mode": "data_only",
        "detail": "compact_core",
        "full_mode": "full",
        "omitted_fields": [
            "chart",
            "technical_reports",
            "revenue_history",
            "financial_history",
            "broker_branch",
            "prompt",
        ],
    }
    return output


def _project_brief_result(
    result: dict[str, Any],
    *,
    consumer_human_answer: dict[str, Any],
) -> dict[str, Any]:
    output = _base_result(result)
    summary = _brief_summary(result.get("summary") if isinstance(result.get("summary"), dict) else {})
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact_data = _compact_result_data(result)

    if summary:
        output["summary"] = summary
    if consumer_human_answer:
        output["human_answer"] = consumer_human_answer

    if compact_data:
        output["data"] = compact_data
        compact = compact_data.get("compact") if isinstance(compact_data.get("compact"), dict) else {}
        _apply_stock_compact_fields(output, compact)
    elif result.get("kind") in {"market_brief", "watchlist_brief"}:
        output["data"] = data
        _apply_market_brief_fields(output, result)
    elif summary:
        output["data"] = {"summary": summary}

    output["result_view"] = {
        "mode": "brief",
        "detail": "human_summary_plus_key_numbers",
        "full_mode": "full",
        "omitted_fields": [
            "chart",
            "technical_reports",
            "revenue_history",
            "financial_history",
            "broker_branch",
            "summary.decision_evidence",
            "prompt",
        ],
    }
    return output


def _public_result_for_mode(
    result: dict[str, Any],
    *,
    effective_mode: str,
    consumer_human_answer: dict[str, Any],
) -> dict[str, Any]:
    if effective_mode == "brief":
        return _project_brief_result(
            result,
            consumer_human_answer=consumer_human_answer,
        )
    if effective_mode == "data_only":
        return _project_data_only_result(result)
    return result


def finalize_ask_response(
    *,
    payload: AiAskRequest,
    resolution: scope_resolution.ScopeResolution,
    requested_mode: str,
    effective_mode: str,
    action: str,
    result: dict[str, Any],
    response_target: dict[str, Any],
    assembled: Any,
    policy: dict[str, Any],
    tool_plan: dict[str, Any],
    tool_runs: list[dict[str, Any]],
    freshness_result: dict[str, Any],
    progress: Any,
) -> dict[str, Any]:
    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        as_of=ask_response_support._result_as_of(result, assembled.analysis_digest),
        source_refs=assembled.result_source_refs,
        missing=assembled.combined_missing,
        warnings=assembled.combined_warnings,
        freshness=freshness_result,
        tool_runs=tool_runs,
        analysis=assembled.analysis_digest,
    )
    report_level = ask_response_support._report_level(effective_mode, freshness_result)
    progress.evidence_passport(evidence_passport)
    progress.answer_ready(
        answer_ready=assembled.answer_ready,
        report_level=report_level,
    )
    public_result = _public_result_for_mode(
        result,
        effective_mode=effective_mode,
        consumer_human_answer=getattr(assembled, "consumer_human_answer", {}) or {},
    )

    return {
        "kind": "ai_ask",
        "contract_version": ask_response_support.CONTRACT_VERSION,
        "question": payload.question,
        "target": response_target,
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
        },
        "action": action,
        "strategy_profile": result.get("strategy_profile") or payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": scope_resolution._scope_resolution_dict(resolution),
        "clarification": assembled.clarification,
        "next_actions": assembled.next_actions,
        "answer_ready": assembled.answer_ready,
        "report_level": report_level,
        "analysis": assembled.response_analysis,
        "reasoning_steps": assembled.reasoning_steps,
        "policy": policy,
        "tool_plan": tool_plan,
        "tool_runs": tool_runs,
        "result": public_result,
        "freshness": freshness_result,
        "missing": assembled.combined_missing,
        "warnings": assembled.combined_warnings,
        "source_refs": assembled.result_source_refs,
        "evidence_passport": evidence_passport,
    }
