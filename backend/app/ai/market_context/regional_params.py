from __future__ import annotations

from typing import Any

from app.ai.agentic_common import _optional_bool, _safe_int


def _market_data_param(params: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(params, dict):
        return default
    value = params.get(key, default)
    return default if value is None else value


def _market_data_int(
    params: dict[str, Any] | None,
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    return _safe_int(
        _market_data_param(params, key, default),
        default,
        minimum=minimum,
        maximum=maximum,
    )


def _market_data_str(
    params: dict[str, Any] | None,
    key: str,
    default: str | None = None,
) -> str | None:
    value = _market_data_param(params, key, default)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _market_data_bool(
    params: dict[str, Any] | None,
    key: str,
    default: bool = False,
) -> bool:
    value = _market_data_param(params, key, default)
    return bool(_optional_bool(value)) if value is not None else default
