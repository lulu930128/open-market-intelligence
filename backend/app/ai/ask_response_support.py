from __future__ import annotations

from typing import Any

from app.ai import answer_composer, decision_engine, llm, scope_resolution
from app.ai.evidence_passport import build_evidence_passport
from app.ai.schemas import AiAskRequest


CONTRACT_VERSION = "omi.ai.ask.v2"
ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
CONFIDENCE_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
CONSUMER_SUMMARY_LIMIT = 3
ScopeResolution = scope_resolution.ScopeResolution
_clarification_dict = scope_resolution._clarification_dict
_resolution_target = scope_resolution._resolution_target
_scope_resolution_dict = scope_resolution._scope_resolution_dict


def _extract_list(result: dict[str, Any], key: str) -> list[Any]:
    value = result.get(key)
    return value if isinstance(value, list) else []


def _result_as_of(result: dict[str, Any], analysis: dict[str, Any]) -> Any:
    if result.get("as_of"):
        return result.get("as_of")
    if analysis.get("as_of"):
        return analysis.get("as_of")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if summary.get("latest_trade_date"):
        return summary.get("latest_trade_date")
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    if overview.get("as_of"):
        return overview.get("as_of")
    return None


def _score_display(value: Any) -> str | None:
    return decision_engine.score_display(value)


def _text_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    texts: list[str] = []
    for item in value:
        text = _text_value(item)
        if text is None:
            continue
        if text in texts:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def _append_unique_texts(target: list[str], values: list[str], *, limit: int) -> None:
    for value in values:
        if value in target:
            continue
        target.append(value)
        if len(target) >= limit:
            return


def _llm_report_from_result(result: dict[str, Any]) -> dict[str, Any]:
    llm = result.get("llm") if isinstance(result.get("llm"), dict) else {}
    report = llm.get("report") if isinstance(llm.get("report"), dict) else None
    if isinstance(report, dict):
        return report

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    report = summary.get("llm") if isinstance(summary.get("llm"), dict) else None
    return report if isinstance(report, dict) else {}


def _consumer_detail_from_llm_report(
    report: dict[str, Any],
    *,
    missing_data_label: str = "資料限制",
) -> str:
    return answer_composer.consumer_detail_from_llm_report(
        report,
        missing_data_label=missing_data_label,
    )


def _consumer_text(answer: dict[str, Any]) -> str:
    return answer_composer.consumer_text(
        answer,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _generic_data_limits(*, missing: list[Any], warnings: list[Any]) -> list[str]:
    return answer_composer.generic_data_limits(
        missing=missing,
        warnings=warnings,
    )


def _numeric_score(value: Any) -> float | None:
    return decision_engine.numeric_score(value)


def _stance_from_score(score: float | None) -> str:
    return decision_engine.stance_from_score(score)


def _numeric_data_value(value: Any) -> float | None:
    return decision_engine.numeric_data_value(value)


def _format_price(value: float | None) -> str:
    return decision_engine.format_price(value)


def _format_signed_price(value: float | None) -> str:
    return decision_engine.format_signed_price(value)


def _format_pct_value(value: float | None) -> str:
    return decision_engine.format_pct_value(value)


def _level_price_text(level: Any) -> str | None:
    return decision_engine.level_price_text(level)


def _zone_text(zone: Any) -> str | None:
    return decision_engine.zone_text(zone)


def _zone_bounds(zone: Any) -> tuple[float | None, float | None]:
    return decision_engine.zone_bounds(zone)


def _technical_level_fields(levels: dict[str, Any]) -> dict[str, str]:
    return decision_engine.technical_level_fields(levels)


def _technical_level_numbers(levels: dict[str, Any]) -> dict[str, float | None]:
    return decision_engine.technical_level_numbers(levels)


def _entry_price_position(numbers: dict[str, float | None]) -> str:
    return decision_engine.entry_price_position(numbers)


def _entry_risk_text(fields: dict[str, str]) -> str:
    return decision_engine.entry_risk_text(fields)


def _entry_confirmation_text(
    fields: dict[str, str],
    numbers: dict[str, float | None],
) -> str | None:
    return decision_engine.entry_confirmation_text(fields, numbers)


def _entry_decision_summary_lines(
    fields: dict[str, str],
    numbers: dict[str, float | None],
    price_position: str,
) -> list[str]:
    return decision_engine.entry_decision_summary_lines(
        fields,
        numbers,
        price_position,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _entry_decision_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
) -> tuple[str, list[str], list[dict[str, str]]]:
    return decision_engine.entry_decision_with_levels(
        target_label=target_label,
        score=score,
        weak_evidence=weak_evidence,
        fields=fields,
        numbers=numbers,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _technical_level_summary_lines(levels: dict[str, Any]) -> list[str]:
    return decision_engine.technical_level_summary_lines(
        levels,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _result_data(result: dict[str, Any]) -> dict[str, Any]:
    return decision_engine.result_data(result)


def _latest_price_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    return decision_engine.latest_price_snapshot(result)


def _chart_points(result: dict[str, Any]) -> list[dict[str, Any]]:
    return decision_engine.chart_points(result)


def _position_support_levels(result: dict[str, Any]) -> dict[str, Any]:
    return decision_engine.position_support_levels(result)


def _level_text(levels: dict[str, Any]) -> str:
    return decision_engine.level_text(levels)


def _build_position_decision(
    *,
    question: str,
    position_context: dict[str, Any],
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return decision_engine.build_position_decision(
        question=question,
        position_context=position_context,
        target=target,
        result=result,
        analysis_digest=analysis_digest,
        supplemental_data_limits=_generic_data_limits(missing=missing, warnings=warnings),
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _try_attach_position_decision_llm(
    *,
    payload: AiAskRequest,
    policy: dict[str, Any],
    target: dict[str, Any],
    position_context: dict[str, Any],
    position_decision: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    if not position_decision:
        return {}

    if not policy.get("can_call_llm"):
        position_decision["llm_status"] = "skipped_policy"
        return position_decision

    decision_input = {
        "question": payload.question,
        "target": target,
        "position_context": position_context,
        "position_decision": {
            key: value
            for key, value in position_decision.items()
            if key not in {"llm", "text"}
        },
        "analysis_digest": analysis_digest,
        "missing": missing,
        "warnings": warnings,
        "rules": [
            "Answer the user's position-risk question directly.",
            "Use only the supplied evidence and calculations.",
            "Do not give a blanket buy/sell command; make conditions explicit.",
        ],
    }
    try:
        llm_result = llm.generate_decision_answer(decision_input)
    except llm.OpenAIConfigurationError:
        position_decision["llm_status"] = "skipped_not_configured"
        return position_decision
    except llm.OpenAILLMError as exc:
        position_decision["llm_status"] = "failed"
        position_decision["llm_error"] = str(exc)
        return position_decision

    position_decision["llm_status"] = "completed"
    position_decision["llm"] = llm_result
    return position_decision


def _build_position_decision_consumer_answer(
    *,
    position_decision: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return answer_composer.build_position_decision_consumer_answer(
        position_decision=position_decision,
        missing=missing,
        warnings=warnings,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


QUESTION_INTENT_STAGE_LABELS = {
    "entry_decision": "進場問題",
    "exit_decision": "出場問題",
    "risk_check": "風險檢查",
    "trend_view": "走勢解讀",
    "general": "一般問答",
}


def _build_reasoning_steps(
    *,
    question_intent: str,
    position_context: dict[str, Any],
    position_decision: dict[str, Any],
    analysis_digest: dict[str, Any],
) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    if question_intent == "position_risk_decision":
        entry_price = _numeric_data_value(position_context.get("entry_price"))
        entry_text = f"，成本價 {_format_price(entry_price)}" if entry_price is not None else ""
        steps.append(
            {
                "stage": "question_understanding",
                "message": f"已解析為持倉/停損問題{entry_text}。",
            }
        )
        latest_price = _numeric_data_value(position_decision.get("latest_price"))
        latest_text = f"最新價 {_format_price(latest_price)}" if latest_price is not None else "最新價不足"
        steps.append(
            {
                "stage": "evidence_read",
                "message": f"已讀取標的日線與技術摘要，{latest_text}。",
            }
        )
        pnl_pct = position_decision.get("unrealized_return_pct")
        pnl_number = None
        if not isinstance(pnl_pct, bool) and isinstance(pnl_pct, (int, float)):
            pnl_number = float(pnl_pct)
        pnl_text = _format_pct_value(pnl_number) if pnl_number is not None else "無法計算"
        steps.append(
            {
                "stage": "position_math",
                "message": f"已計算成本距離與浮動損益：{pnl_text}。",
            }
        )
        llm_status = position_decision.get("llm_status")
        synthesis = "已完成 LLM 決策綜合。" if llm_status == "completed" else "已完成規則化決策綜合。"
        steps.append({"stage": "decision_synthesis", "message": synthesis})
        return steps

    if analysis_digest:
        intent_label = QUESTION_INTENT_STAGE_LABELS.get(question_intent, "問題解析")
        selected_horizon = _text_value(analysis_digest.get("horizon_label")) or _text_value(
            analysis_digest.get("selected_horizon")
        )
        score_text = _score_display(_numeric_score(analysis_digest.get("selected_score")))
        confidence = _text_value(analysis_digest.get("selected_confidence"))
        digest_bits = []
        if selected_horizon:
            digest_bits.append(f"{selected_horizon}視角")
        if score_text:
            digest_bits.append(f"評分 {score_text}")
        if confidence:
            digest_bits.append(f"信心 {CONFIDENCE_LABELS.get(confidence, confidence)}")

        steps.append(
            {
                "stage": "question_understanding",
                "message": f"已判斷為{intent_label}，後續回答會依這個意圖組合。",
            }
        )
        steps.append(
            {
                "stage": "evidence_read",
                "message": "已讀取目前畫面標的的技術摘要與資料限制"
                + (f"：{'，'.join(digest_bits)}。" if digest_bits else "。"),
            }
        )
        score_model = analysis_digest.get("score_model") if isinstance(analysis_digest.get("score_model"), dict) else {}
        if score_model.get("version"):
            horizon_scores = (
                score_model.get("horizon_factor_scores")
                if isinstance(score_model.get("horizon_factor_scores"), dict)
                else {}
            )
            selected_key = _text_value(analysis_digest.get("selected_horizon"))
            factors = (
                horizon_scores.get(selected_key)
                if selected_key and isinstance(horizon_scores.get(selected_key), dict)
                else {}
            )
            factor_names = {
                "trend": "趨勢",
                "momentum": "動能",
                "volume": "量能",
                "volatility": "波動",
                "chips": "籌碼",
            }
            factor_text = "、".join(
                f"{factor_names.get(key, key)} {value:+.1f}"
                for key, value in factors.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            )
            steps.append(
                {
                    "stage": "score_model",
                    "message": (
                        f"已用五因子權重重算分數：{factor_text}。"
                        if factor_text
                        else "已用五因子權重重算技術分數。"
                    ),
                }
            )

        technical_levels = (
            analysis_digest.get("technical_levels")
            if isinstance(analysis_digest.get("technical_levels"), dict)
            else {}
        )
        level_fields = _technical_level_fields(technical_levels)
        if level_fields:
            level_parts = []
            if level_fields.get("preferred"):
                level_parts.append(f"回檔區 {level_fields['preferred']}")
            if level_fields.get("breakout"):
                level_parts.append(f"突破 {level_fields['breakout']}")
            if level_fields.get("stop"):
                level_parts.append(f"停損 {level_fields['stop']}")
            if level_fields.get("invalidation"):
                level_parts.append(f"失效 {level_fields['invalidation']}")
            steps.append(
                {
                    "stage": "price_levels",
                    "message": "已從 MA、ATR、Donchian 推導條件價位"
                    + (f"：{'，'.join(level_parts)}。" if level_parts else "。"),
                }
            )

        synthesis_message = {
            "entry_decision": "已將進場條件、追價上限與風控線組合成回答。",
            "exit_decision": "已將續抱、出場與失效條件組合成回答。",
            "risk_check": "已將主要風險與防守條件組合成回答。",
            "trend_view": "已將趨勢、分數與資料限制組合成回答。",
        }.get(question_intent, "已完成資料摘要與回答組裝。")
        steps.append({"stage": "decision_synthesis", "message": synthesis_message})
    return steps


def _digest_summary_lines(analysis_digest: dict[str, Any]) -> list[str]:
    return answer_composer.digest_summary_lines(
        analysis_digest,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _decision_evidence_summary_lines(decision_evidence: dict[str, Any]) -> list[str]:
    return answer_composer.decision_evidence_summary_lines(decision_evidence)


def _decision_evidence_risk_lines(decision_evidence: dict[str, Any]) -> list[str]:
    return answer_composer.decision_evidence_risk_lines(decision_evidence)


def _decision_evidence_data_lines(decision_evidence: dict[str, Any]) -> list[str]:
    return answer_composer.decision_evidence_data_lines(decision_evidence)


def _build_question_aware_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return answer_composer.build_question_aware_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _build_llm_consumer_answer(
    *,
    report: dict[str, Any],
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return answer_composer.build_llm_consumer_answer(
        report=report,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _build_watchlist_consumer_answer(
    *,
    human_answer: dict[str, Any],
    overview: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return answer_composer.build_watchlist_consumer_answer(
        human_answer=human_answer,
        overview=overview,
        missing=missing,
        warnings=warnings,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _build_digest_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    return answer_composer.build_digest_consumer_answer(
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _build_consumer_human_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    position_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return answer_composer.build_consumer_human_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        position_decision=position_decision,
        llm_report=_llm_report_from_result(result),
        summary_limit=CONSUMER_SUMMARY_LIMIT,
    )


def _extract_analysis_digest(result: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    analysis = (data or {}).get("analysis") if isinstance(data, dict) else None
    if isinstance(analysis, dict) and analysis:
        policy_horizon = policy.get("analysis_horizon") if isinstance(policy, dict) else {}
        selected_horizon = (
            analysis.get("selected_horizon")
            or (policy_horizon or {}).get("effective")
            or "swing"
        )
        horizon_label = ANALYSIS_HORIZON_LABELS.get(str(selected_horizon), str(selected_horizon))
        selected_score = analysis.get("selected_score")
        score_text = _score_display(selected_score)
        title = analysis.get("selected_title")
        summary = analysis.get("selected_summary")
        display_parts = [f"{horizon_label}評分 {score_text}" if score_text is not None else f"{horizon_label}評分 -"]
        if title:
            display_parts.append(str(title))
        if summary:
            display_parts.append(str(summary))

        return {
            "kind": "stock_analysis_digest",
            "requested_horizon": analysis.get("requested_horizon") or (policy_horizon or {}).get("requested"),
            "selected_horizon": selected_horizon,
            "horizon_label": horizon_label,
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": selected_score,
            "score_display": score_text,
            "selected_title": title,
            "selected_summary": summary,
            "selected_confidence": analysis.get("selected_confidence"),
            "display": "｜".join(display_parts),
            "scores": analysis.get("scores") or {},
            "score_model": analysis.get("score_model") or {},
            "technical_levels": data.get("technical_levels") or {},
            "decision_evidence": data.get("decision_evidence") or {},
            "source_health": data.get("source_health") or {},
            "components": analysis.get("components") or [],
            "source_refs": result.get("source_refs") or [],
            "source": "result.data.analysis",
        }

    overview = (data or {}).get("overview") if isinstance(data, dict) else None
    if isinstance(overview, dict) and overview.get("kind") == "watchlist_sector_overview":
        human_answer = overview.get("human_answer") if isinstance(overview.get("human_answer"), dict) else {}
        answer_outline = human_answer.get("lines") or overview.get("answer_outline") or []
        return {
            "kind": "watchlist_sector_digest",
            "group_id": overview.get("group_id"),
            "group_name": overview.get("group_name"),
            "stance": overview.get("stance"),
            "confidence": overview.get("confidence"),
            "as_of": overview.get("as_of"),
            "display": overview.get("display"),
            "answer_outline": answer_outline,
            "human_answer": human_answer,
            "breadth": overview.get("breadth") or {},
            "strong_rows": overview.get("strong_rows") or [],
            "weak_rows": overview.get("weak_rows") or [],
            "watch_rows": overview.get("watch_rows") or [],
            "follow_rows": overview.get("follow_rows") or [],
            "pullback_rows": overview.get("pullback_rows") or [],
            "defensive_rows": overview.get("defensive_rows") or [],
            "radar": overview.get("radar") or {},
            "radar_rows": overview.get("radar_rows") or [],
            "data_status": overview.get("data_status") or {},
            "source_refs": result.get("source_refs") or [],
            "guidance": (
                "Prefer analysis.human_answer for the user-facing reply; avoid exposing raw missing dataset keys "
                "unless the user explicitly asks for debugging detail."
            ),
            "source": "result.data.overview",
        }

    return {}


def _report_level(effective_mode: str, freshness_result: dict[str, Any]) -> str:
    if effective_mode == "clarification":
        return "clarification"

    if effective_mode == "report":
        return "full_report"

    if effective_mode == "analysis":
        return "analysis"

    if effective_mode == "brief":
        if freshness_result and not freshness_result.get("is_current", True):
            return "brief_with_gaps"
        return "brief"

    return "data_only"


def _build_next_actions(
    *,
    resolution: ScopeResolution,
    clarification: dict[str, Any],
    freshness_result: dict[str, Any],
    effective_mode: str,
    policy: dict[str, Any],
    requested_mode: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    if clarification.get("required"):
        actions.append(
            {
                "type": "ask_clarification",
                "label": "Ask user to clarify the OMI target scope.",
                "question": clarification.get("question"),
                "reason": clarification.get("reason"),
            }
        )
        return actions

    if freshness_result and freshness_result.get("refresh_recommended"):
        actions.append(
            {
                "type": "refresh_data",
                "label": "Refresh local OMI evidence before relying on a full AI report.",
                "endpoint": freshness_result.get("refresh_endpoint"),
                "params": freshness_result.get("refresh_params") or {},
                "missing": freshness_result.get("missing") or [],
            }
        )

    if resolution.selected_scope_type != "us_stock" and any(
        (candidate.get("target") or {}).get("type") == "us_stock"
        for candidate in resolution.candidates
    ):
        actions.append(
            {
                "type": "connect_us_stock_context",
                "label": "Use US/ADR evidence before making ADR-specific conclusions.",
                "target": {
                    "type": "us_stock",
                    "id": "TSM",
                    "label": "TSM ADR",
                    "market": "US",
                },
            }
        )

    if (
        effective_mode == "brief"
        and requested_mode != "report"
        and policy.get("can_generate_report")
        and not (freshness_result and freshness_result.get("refresh_recommended"))
    ):
        actions.append(
            {
                "type": "generate_report",
                "label": "Generate a persisted OMI AI report for this resolved scope.",
                "target": _resolution_target(resolution),
            }
        )

    return actions


def _clarification_response(
    *,
    payload: AiAskRequest,
    resolution: ScopeResolution,
    requested_mode: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    clarification = _clarification_dict(resolution)
    next_actions = _build_next_actions(
        resolution=resolution,
        clarification=clarification,
        freshness_result={},
        effective_mode="clarification",
        policy=policy,
        requested_mode=requested_mode,
    )
    result = {
        "kind": "clarification_required",
        "message": clarification.get("question"),
        "reason": clarification.get("reason"),
    }
    response_warnings = [clarification["reason"]] if clarification.get("reason") else []
    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        missing=["target_scope"],
        warnings=response_warnings,
        confidence="low",
    )

    return {
        "kind": "ai_ask",
        "contract_version": CONTRACT_VERSION,
        "question": payload.question,
        "target": _resolution_target(resolution),
        "mode": {
            "requested": requested_mode,
            "effective": "clarification",
        },
        "action": "omi.ask.clarify",
        "strategy_profile": payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": _scope_resolution_dict(resolution),
        "clarification": clarification,
        "next_actions": next_actions,
        "answer_ready": False,
        "report_level": "clarification",
        "analysis": {},
        "policy": policy,
        "tool_plan": {},
        "tool_runs": [],
        "result": result,
        "freshness": {},
        "missing": [],
        "warnings": response_warnings,
        "source_refs": [],
        "evidence_passport": evidence_passport,
    }
