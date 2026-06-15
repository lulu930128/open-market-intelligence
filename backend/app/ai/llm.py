from __future__ import annotations

from typing import Any
import json

import requests

from app.http_client import post as http_post
from app.config import settings


class OpenAILLMError(Exception):
    """Base error for OpenAI-backed report generation."""


class OpenAIConfigurationError(OpenAILLMError):
    pass


class OpenAIHTTPError(OpenAILLMError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


LLM_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "stance": {
            "type": "string",
            "enum": ["bullish", "bearish", "neutral", "mixed", "insufficient_data"],
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "as_of": {"type": "string"},
        "key_observations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "interpretation": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_data": {
            "type": "array",
            "items": {"type": "string"},
        },
        "next_checks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "disclaimer": {"type": "string"},
    },
    "required": [
        "headline",
        "stance",
        "confidence",
        "as_of",
        "key_observations",
        "interpretation",
        "risks",
        "missing_data",
        "next_checks",
        "disclaimer",
    ],
    "additionalProperties": False,
}

LLM_TOOL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "tool_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": [
                            "tw.refresh_stock_evidence",
                            "us.read_intraday_trend",
                            "us.refresh_daily_price",
                            "us.refresh_company_profile",
                            "us.refresh_sec_facts",
                            "us.read_sec_fundamentals",
                            "us.refresh_corporate_actions",
                        ],
                    },
                    "stock_id": {"type": ["string", "null"]},
                    "symbol": {"type": ["string", "null"]},
                    "provider": {"type": ["string", "null"]},
                    "outputsize": {"type": ["string", "null"]},
                    "adjusted": {"type": ["boolean", "null"]},
                    "series_id": {"type": ["string", "null"]},
                    "include_today": {"type": ["boolean", "null"]},
                    "sleep_seconds": {"type": ["number", "null"]},
                    "reason": {"type": "string"},
                },
                "required": [
                    "tool",
                    "stock_id",
                    "symbol",
                    "provider",
                    "outputsize",
                    "adjusted",
                    "series_id",
                    "include_today",
                    "sleep_seconds",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reason", "tool_plan"],
    "additionalProperties": False,
}

LLM_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "direct_answer": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "position_math": {
            "type": "array",
            "items": {"type": "string"},
        },
        "evidence_used": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decision_conditions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risk_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_context": {
            "type": "array",
            "items": {"type": "string"},
        },
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "headline",
        "direct_answer",
        "confidence",
        "position_math",
        "evidence_used",
        "decision_conditions",
        "risk_notes",
        "missing_context",
        "next_steps",
    ],
    "additionalProperties": False,
}


def _json_default(value: Any) -> str:
    return str(value)


def _build_user_prompt(envelope: dict[str, Any]) -> str:
    evidence = {
        "kind": envelope.get("kind"),
        "as_of": envelope.get("as_of"),
        "scope": envelope.get("scope") or {},
        "strategy_profile": envelope.get("strategy_profile"),
        "profile": (envelope.get("prompt") or {}).get("profile") or {},
        "memories": (envelope.get("prompt") or {}).get("memories") or [],
        "summary": envelope.get("summary") or {},
        "data": envelope.get("data") or {},
        "missing": envelope.get("missing") or [],
        "warnings": envelope.get("warnings") or [],
        "source_refs": envelope.get("source_refs") or [],
    }
    evidence_json = json.dumps(evidence, ensure_ascii=False, default=_json_default)

    return (
        "Create one OMI research report from the following JSON evidence pack.\n"
        "Rules:\n"
        "- Use only values present in the evidence pack.\n"
        "- Do not infer live prices, future events, or missing datasets.\n"
        "- If evidence.data.technical_levels is present, use those explicit prices for entry, stop-loss, "
        "and invalidation levels; do not invent alternative price levels.\n"
        "- If evidence is stale, partial, or insufficient, lower confidence and say so.\n"
        "- Put items in missing_data only when the evidence pack explicitly reports missing, stale, "
        "or unavailable datasets. Put future price/intraday confirmations in next_checks, not missing_data.\n"
        "- Write all human-readable output strings in Traditional Chinese.\n"
        "- Keep the report concise and focused on actionable next checks.\n"
        "- The output must be JSON that matches the provided schema.\n\n"
        f"Evidence JSON:\n{evidence_json}"
    )


def build_responses_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    system_prompt = (envelope.get("prompt") or {}).get("system") or (
        "You are an Open Market Intelligence research assistant. Use only provided evidence."
    )
    user_prompt = _build_user_prompt(envelope)

    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "omi_research_report",
                "strict": True,
                "schema": LLM_REPORT_SCHEMA,
            }
        },
        "max_output_tokens": settings.openai_max_output_tokens,
    }


def build_tool_plan_payload(planner_input: dict[str, Any]) -> dict[str, Any]:
    planner_json = json.dumps(planner_input, ensure_ascii=False, default=_json_default)
    system_prompt = (
        "You are the OMI tool planner. Choose a minimal, bounded tool plan. "
        "Only select tools listed in allowed_tools. Do not invent tools or broad refreshes."
    )
    user_prompt = (
        "Create an OMI tool plan from the following JSON.\n"
        "Rules:\n"
        "- Use at most the requested budget.\n"
        "- Prefer local cached evidence when gaps are not material.\n"
        "- Use external fetch tools only when they directly reduce missing evidence.\n"
        "- If no tool is needed, return an empty tool_plan.\n"
        "- For single-stock US/ADR questions, keep all symbol fields to the target symbol.\n\n"
        f"Planner input JSON:\n{planner_json}"
    )

    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "omi_tool_plan",
                "strict": True,
                "schema": LLM_TOOL_PLAN_SCHEMA,
            }
        },
        "max_output_tokens": min(settings.openai_max_output_tokens, 900),
    }


def build_decision_payload(decision_input: dict[str, Any]) -> dict[str, Any]:
    decision_json = json.dumps(decision_input, ensure_ascii=False, default=_json_default)
    system_prompt = (
        "You are OMI's position-risk decision synthesizer. "
        "Use only the supplied evidence and calculations. "
        "Do not provide personalized financial advice; make the decision conditional on explicit rules."
    )
    user_prompt = (
        "Answer the user's position-risk question from this JSON decision pack.\n"
        "Rules:\n"
        "- Write all human-readable output strings in Traditional Chinese.\n"
        "- Start with the direct answer to the user's question.\n"
        "- Use the provided entry price, latest price, unrealized P/L, technical digest, and data limits.\n"
        "- Do not invent live prices, support levels, events, or missing personal risk tolerance.\n"
        "- Make stop-loss conditions explicit instead of giving a blanket buy/sell command.\n"
        "- The output must be JSON that matches the provided schema.\n\n"
        f"Decision JSON:\n{decision_json}"
    )

    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "omi_position_decision",
                "strict": True,
                "schema": LLM_DECISION_SCHEMA,
            }
        },
        "max_output_tokens": min(settings.openai_max_output_tokens, 1200),
    }


def _raise_for_openai_error(response: requests.Response) -> None:
    if response.status_code < 400:
        return

    message = response.text
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])
    except ValueError:
        pass

    raise OpenAIHTTPError(
        response.status_code,
        f"OpenAI Responses API returned HTTP {response.status_code}: {message}",
    )


def _extract_text(response_payload: dict[str, Any]) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    texts: list[str] = []
    refusals: list[str] = []
    for item in response_payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("refusal"):
                refusals.append(str(content["refusal"]))
            if content.get("text"):
                texts.append(str(content["text"]))

    if texts:
        return "\n".join(texts)

    if refusals:
        raise OpenAILLMError(f"OpenAI refused the report request: {' '.join(refusals)}")

    raise OpenAILLMError("OpenAI response did not include output text.")


def _parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise OpenAILLMError("OpenAI response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise OpenAILLMError("OpenAI response JSON must be an object.")

    return parsed


def _validate_report_shape(report: dict[str, Any]) -> None:
    missing = [key for key in LLM_REPORT_SCHEMA["required"] if key not in report]
    if missing:
        raise OpenAILLMError(f"OpenAI report JSON missed required keys: {', '.join(missing)}")

    stance = report.get("stance")
    valid_stances = LLM_REPORT_SCHEMA["properties"]["stance"]["enum"]
    if stance not in valid_stances:
        raise OpenAILLMError(f"OpenAI report stance is invalid: {stance}")

    confidence = report.get("confidence")
    valid_confidences = LLM_REPORT_SCHEMA["properties"]["confidence"]["enum"]
    if confidence not in valid_confidences:
        raise OpenAILLMError(f"OpenAI report confidence is invalid: {confidence}")

    for key in ("key_observations", "interpretation", "risks", "missing_data", "next_checks"):
        if not isinstance(report.get(key), list):
            raise OpenAILLMError(f"OpenAI report field must be a list: {key}")


def _validate_decision_shape(decision: dict[str, Any]) -> None:
    missing = [key for key in LLM_DECISION_SCHEMA["required"] if key not in decision]
    if missing:
        raise OpenAILLMError(f"OpenAI decision JSON missed required keys: {', '.join(missing)}")

    confidence = decision.get("confidence")
    valid_confidences = LLM_DECISION_SCHEMA["properties"]["confidence"]["enum"]
    if confidence not in valid_confidences:
        raise OpenAILLMError(f"OpenAI decision confidence is invalid: {confidence}")

    for key in (
        "position_math",
        "evidence_used",
        "decision_conditions",
        "risk_notes",
        "missing_context",
        "next_steps",
    ):
        if not isinstance(decision.get(key), list):
            raise OpenAILLMError(f"OpenAI decision field must be a list: {key}")


def generate_structured_report(envelope: dict[str, Any]) -> dict[str, Any]:
    openai_api_key = settings.effective_openai_api_key
    if not openai_api_key:
        raise OpenAIConfigurationError(
            "OPENAI_API_KEY is not configured for OMI. Set OPENAI_API_KEY, "
            "OPENAI_LLM_API_KEY, or OMI_OPENAI_ENV_FILE in the OMI environment."
        )

    payload = build_responses_payload(envelope)
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = http_post(
            settings.openai_responses_url,
            headers=headers,
            json=payload,
            timeout=settings.openai_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise OpenAILLMError(f"OpenAI Responses API request failed: {exc}") from exc

    _raise_for_openai_error(response)

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise OpenAILLMError("OpenAI Responses API returned non-JSON response.") from exc

    if response_payload.get("status") == "incomplete":
        details = response_payload.get("incomplete_details") or {}
        raise OpenAILLMError(f"OpenAI response was incomplete: {details}")

    report = _parse_json_text(_extract_text(response_payload))
    _validate_report_shape(report)

    return {
        "report": report,
        "response_id": response_payload.get("id"),
        "model": response_payload.get("model") or settings.openai_model,
        "usage": response_payload.get("usage") or {},
    }


def generate_decision_answer(decision_input: dict[str, Any]) -> dict[str, Any]:
    openai_api_key = settings.effective_openai_api_key
    if not openai_api_key:
        raise OpenAIConfigurationError(
            "OPENAI_API_KEY is not configured for OMI position decisions. Set OPENAI_API_KEY, "
            "OPENAI_LLM_API_KEY, or OMI_OPENAI_ENV_FILE in the OMI environment."
        )

    payload = build_decision_payload(decision_input)
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = http_post(
            settings.openai_responses_url,
            headers=headers,
            json=payload,
            timeout=min(settings.openai_timeout_seconds, 45),
        )
    except requests.RequestException as exc:
        raise OpenAILLMError(f"OpenAI Responses API decision request failed: {exc}") from exc

    _raise_for_openai_error(response)

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise OpenAILLMError("OpenAI Responses API returned non-JSON response for position decision.") from exc

    if response_payload.get("status") == "incomplete":
        details = response_payload.get("incomplete_details") or {}
        raise OpenAILLMError(f"OpenAI decision response was incomplete: {details}")

    decision = _parse_json_text(_extract_text(response_payload))
    _validate_decision_shape(decision)

    return {
        "decision": decision,
        "response_id": response_payload.get("id"),
        "model": response_payload.get("model") or settings.openai_model,
        "usage": response_payload.get("usage") or {},
    }


def generate_tool_plan(planner_input: dict[str, Any]) -> dict[str, Any]:
    openai_api_key = settings.effective_openai_api_key
    if not openai_api_key:
        raise OpenAIConfigurationError(
            "OPENAI_API_KEY is not configured for OMI tool planning. Set OPENAI_API_KEY, "
            "OPENAI_LLM_API_KEY, or OMI_OPENAI_ENV_FILE in the OMI environment."
        )

    payload = build_tool_plan_payload(planner_input)
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = http_post(
            settings.openai_responses_url,
            headers=headers,
            json=payload,
            timeout=min(settings.openai_timeout_seconds, 45),
        )
    except requests.RequestException as exc:
        raise OpenAILLMError(f"OpenAI Responses API tool-plan request failed: {exc}") from exc

    _raise_for_openai_error(response)

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise OpenAILLMError("OpenAI Responses API returned non-JSON response for tool planning.") from exc

    if response_payload.get("status") == "incomplete":
        details = response_payload.get("incomplete_details") or {}
        raise OpenAILLMError(f"OpenAI tool-plan response was incomplete: {details}")

    plan = _parse_json_text(_extract_text(response_payload))
    if not isinstance(plan.get("tool_plan"), list):
        raise OpenAILLMError("OpenAI tool-plan JSON missed tool_plan list.")

    plan["provider"] = "openai"
    plan["response_id"] = response_payload.get("id")
    plan["model"] = response_payload.get("model") or settings.openai_model
    plan["usage"] = response_payload.get("usage") or {}
    return plan
