"""US Daily OHLCV binding and acquisition rollout policy."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.market_data.rollout import CapabilityRolloutMode, CapabilityRolloutState
from app.us_market.errors import USMarketConfigurationError
from app.us_market.symbols import normalize_us_symbol


US_DAILY_CAPABILITY_ID = "us.daily.ohlcv"
US_DAILY_READ_BINDING_MODE = "canonical"


def us_daily_target_key(symbol: str) -> str:
    normalized = normalize_us_symbol(symbol)
    if not normalized:
        raise ValueError("symbol is required")
    return f"US:{normalized}"


def _configured_targets(raw_symbols: str) -> tuple[str, ...]:
    targets: list[str] = []
    for raw_symbol in raw_symbols.split(","):
        if not raw_symbol.strip():
            continue
        target = us_daily_target_key(raw_symbol)
        if target not in targets:
            targets.append(target)
    return tuple(targets)


def build_us_daily_acquisition_rollout_state(
    *,
    mode: str | CapabilityRolloutMode | None = None,
    symbols: str | None = None,
    max_symbols: int | None = None,
    changed_at: datetime | None = None,
) -> CapabilityRolloutState:
    """Build the fail-closed acquisition state from runtime configuration."""

    raw_mode = mode or (
        settings.us_canonical_market_data_mode
        or settings.canonical_market_data_mode
    )
    try:
        effective_mode = CapabilityRolloutMode(raw_mode)
    except ValueError as exc:
        raise USMarketConfigurationError(
            f"US_DAILY_ACQUISITION_ROLLOUT_INVALID_MODE: {raw_mode}"
        ) from exc

    configured_targets = _configured_targets(
        settings.us_canonical_shadow_symbols if symbols is None else symbols
    )
    effective_max = (
        settings.us_canonical_canary_max_symbols
        if max_symbols is None
        else max_symbols
    )
    if effective_max < 1:
        raise USMarketConfigurationError(
            "US_DAILY_ACQUISITION_ROLLOUT_INVALID_LIMIT: max_symbols must be positive"
        )
    if effective_mode is CapabilityRolloutMode.CANARY:
        if not configured_targets:
            raise USMarketConfigurationError(
                "US_DAILY_ACQUISITION_ROLLOUT_INVALID_CANARY: at least one target is required"
            )
        if len(configured_targets) > effective_max:
            raise USMarketConfigurationError(
                "US_DAILY_ACQUISITION_ROLLOUT_INVALID_CANARY: "
                f"target_count={len(configured_targets)} exceeds max_symbols={effective_max}"
            )

    return CapabilityRolloutState(
        capability_id=US_DAILY_CAPABILITY_ID,
        mode=effective_mode,
        canary_targets=(
            configured_targets
            if effective_mode is CapabilityRolloutMode.CANARY
            else ()
        ),
        changed_at=changed_at or datetime.now(timezone.utc),
        reason_code="US_DAILY_RUNTIME_CONFIGURATION",
    )


def require_us_daily_acquisition_enabled(
    symbol: str,
    *,
    state: CapabilityRolloutState | None = None,
) -> None:
    rollout = state or build_us_daily_acquisition_rollout_state()
    target_key = us_daily_target_key(symbol)
    if rollout.production_enabled_for(target_key):
        return
    raise USMarketConfigurationError(
        "US_DAILY_ACQUISITION_ROLLOUT_DISABLED: "
        f"mode={rollout.mode.value} target={target_key}"
    )


def us_daily_full_market_acquisition_enabled() -> bool:
    """Return whether full-market acquisition may be scheduled."""

    try:
        state = build_us_daily_acquisition_rollout_state()
    except USMarketConfigurationError:
        return False
    return state.mode is CapabilityRolloutMode.ON


def us_daily_rollout_snapshot() -> dict[str, Any]:
    """Return health-safe rollout facts without exposing the symbol allowlist."""

    effective_mode = (
        settings.us_canonical_market_data_mode
        or settings.canonical_market_data_mode
    )
    configured_count = len(
        _configured_targets(settings.us_canonical_shadow_symbols)
    )
    try:
        state = build_us_daily_acquisition_rollout_state()
    except USMarketConfigurationError as exc:
        return {
            "read_binding_mode": US_DAILY_READ_BINDING_MODE,
            "acquisition_rollout_mode": effective_mode,
            "acquisition_enabled": False,
            "acquisition_scope": "none",
            "canary_target_count": configured_count,
            "configuration_status": "invalid",
            "limitations": [str(exc)],
        }
    return {
        "read_binding_mode": US_DAILY_READ_BINDING_MODE,
        "acquisition_rollout_mode": state.mode.value,
        "acquisition_enabled": state.mode
        in {CapabilityRolloutMode.CANARY, CapabilityRolloutMode.ON},
        "acquisition_scope": (
            "all"
            if state.mode is CapabilityRolloutMode.ON
            else "canary_targets"
            if state.mode is CapabilityRolloutMode.CANARY
            else "none"
        ),
        "canary_target_count": len(state.canary_targets),
        "configuration_status": "valid",
        "limitations": [],
    }


__all__ = [
    "US_DAILY_CAPABILITY_ID",
    "US_DAILY_READ_BINDING_MODE",
    "build_us_daily_acquisition_rollout_state",
    "require_us_daily_acquisition_enabled",
    "us_daily_full_market_acquisition_enabled",
    "us_daily_rollout_snapshot",
    "us_daily_target_key",
]
