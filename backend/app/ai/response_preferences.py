from __future__ import annotations

from typing import Any


DEFAULT_RESPONSE_LOCALE = "zh-TW"
ENABLED_RESPONSE_LOCALES = {"zh-TW", "en-US", "ja-JP"}
RESERVED_RESPONSE_LOCALES: set[str] = set()
LANGUAGE_BY_LOCALE = {
    "zh-TW": "Traditional Chinese",
    "en-US": "English",
    "ja-JP": "Japanese",
}
LANGUAGE_INSTRUCTIONS = {
    "zh-TW": "Write all human-readable output strings in Traditional Chinese.",
    "en-US": "Write all human-readable output strings in English.",
    "ja-JP": "Write all human-readable output strings in Japanese.",
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _normalize_theme(value: Any) -> str | None:
    text = _text(value)
    return text if text in {"light", "dark"} else None


def _effective_locale(requested_locale: str) -> str:
    if requested_locale in ENABLED_RESPONSE_LOCALES:
        return requested_locale
    return DEFAULT_RESPONSE_LOCALE


def build_response_preferences(conversation_context: dict[str, Any] | None) -> dict[str, Any]:
    context = _mapping(conversation_context)
    ui_context = _mapping(context.get("ui_context"))
    settings = _mapping(ui_context.get("settings"))
    requested_locale = _first_text(
        settings.get("response_locale"),
        settings.get("locale"),
        ui_context.get("response_locale"),
        ui_context.get("ui_locale"),
        ui_context.get("locale"),
    ) or DEFAULT_RESPONSE_LOCALE
    effective_locale = _effective_locale(requested_locale)
    reserved = requested_locale in RESERVED_RESPONSE_LOCALES

    return {
        "requested_locale": requested_locale,
        "effective_locale": effective_locale,
        "reserved_locale": reserved,
        "language": LANGUAGE_BY_LOCALE.get(effective_locale, LANGUAGE_BY_LOCALE[DEFAULT_RESPONSE_LOCALE]),
        "requested_language": _first_text(
            settings.get("response_language"),
            ui_context.get("response_language"),
        )
        or LANGUAGE_BY_LOCALE.get(requested_locale),
        "language_instruction": LANGUAGE_INSTRUCTIONS[effective_locale],
        "theme": _normalize_theme(settings.get("theme") or ui_context.get("theme")),
        "technical_analysis_parameters": _first_text(
            settings.get("technical_analysis_parameters"),
            ui_context.get("technical_analysis_parameters"),
        )
        or "server_persisted",
        "source": "conversation_context.ui_context.settings" if settings else "conversation_context.ui_context",
    }
