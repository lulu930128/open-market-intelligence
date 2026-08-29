"""Provider-neutral per-capability rollout and rollback contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, model_validator

from app.market_data.contracts import CanonicalModel


class CapabilityRolloutMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    COMPARE = "compare"
    CANARY = "canary"
    ON = "on"


class CapabilityRolloutState(CanonicalModel):
    contract_version: str = "omi.market.capability_rollout.v1"
    capability_id: str = Field(min_length=1, max_length=128)
    mode: CapabilityRolloutMode = CapabilityRolloutMode.OFF
    canary_targets: tuple[str, ...] = Field(default=(), max_length=100)
    changed_at: datetime
    reason_code: str = Field(min_length=1, max_length=64)

    @field_validator("changed_at")
    @classmethod
    def _require_aware_changed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_canary_scope(self) -> CapabilityRolloutState:
        if self.mode is CapabilityRolloutMode.CANARY and not self.canary_targets:
            raise ValueError("canary rollout requires at least one target")
        if self.mode is not CapabilityRolloutMode.CANARY and self.canary_targets:
            raise ValueError("canary_targets are only valid in canary mode")
        if len(set(self.canary_targets)) != len(self.canary_targets):
            raise ValueError("canary_targets must be unique")
        return self

    def production_enabled_for(self, target_key: str | None = None) -> bool:
        if self.mode is CapabilityRolloutMode.ON:
            return True
        return (
            self.mode is CapabilityRolloutMode.CANARY
            and target_key is not None
            and target_key in self.canary_targets
        )


class CapabilityRolloutRegistry:
    """In-process source contract; durable runtime ownership is injected separately."""

    def __init__(self) -> None:
        self._states: dict[str, CapabilityRolloutState] = {}

    def set(self, state: CapabilityRolloutState) -> None:
        self._states[state.capability_id] = state

    def get(self, capability_id: str) -> CapabilityRolloutState | None:
        return self._states.get(capability_id)

    def require(self, capability_id: str) -> CapabilityRolloutState:
        try:
            return self._states[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability rollout: {capability_id}") from exc

    def rollback(
        self,
        capability_id: str,
        *,
        changed_at: datetime,
        reason_code: str,
    ) -> CapabilityRolloutState:
        self.require(capability_id)
        state = CapabilityRolloutState(
            capability_id=capability_id,
            mode=CapabilityRolloutMode.OFF,
            changed_at=changed_at,
            reason_code=reason_code,
        )
        self.set(state)
        return state


__all__ = [
    "CapabilityRolloutMode",
    "CapabilityRolloutRegistry",
    "CapabilityRolloutState",
]
