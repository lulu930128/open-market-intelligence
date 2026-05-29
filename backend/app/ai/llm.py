from __future__ import annotations

from typing import Any
import json

import requests

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
        "- If evidence is stale, partial, or insufficient, lower confidence and say so.\n"
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
        response = requests.post(
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
