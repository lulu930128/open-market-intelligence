from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.market_data.rollout import (
    CapabilityRolloutMode,
    CapabilityRolloutRegistry,
    CapabilityRolloutState,
)


NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


def test_capability_rollout_is_scoped_and_canary_is_target_bounded() -> None:
    registry = CapabilityRolloutRegistry()
    state = CapabilityRolloutState(
        capability_id="us.daily.ohlcv",
        mode=CapabilityRolloutMode.CANARY,
        canary_targets=("US:TSM", "US:^SOX"),
        changed_at=NOW,
        reason_code="SOURCE_CANARY",
    )
    registry.set(state)

    assert registry.require("us.daily.ohlcv").production_enabled_for("US:TSM") is True
    assert registry.require("us.daily.ohlcv").production_enabled_for("US:AAPL") is False
    assert registry.get("tw.quote.snapshot") is None


def test_capability_rollout_rollback_has_one_fail_closed_entrypoint() -> None:
    registry = CapabilityRolloutRegistry()
    registry.set(
        CapabilityRolloutState(
            capability_id="us.daily.ohlcv",
            mode=CapabilityRolloutMode.ON,
            changed_at=NOW,
            reason_code="SOURCE_GATE_PASSED",
        )
    )

    rolled_back = registry.rollback(
        "us.daily.ohlcv",
        changed_at=NOW,
        reason_code="POSTCONDITION_FAILED",
    )

    assert rolled_back.mode is CapabilityRolloutMode.OFF
    assert rolled_back.production_enabled_for("US:TSM") is False

    with pytest.raises(KeyError, match="unknown capability rollout"):
        registry.rollback(
            "unknown.capability",
            changed_at=NOW,
            reason_code="UNKNOWN",
        )


def test_canary_requires_targets_and_other_modes_reject_them() -> None:
    with pytest.raises(ValidationError, match="requires at least one target"):
        CapabilityRolloutState(
            capability_id="us.daily.ohlcv",
            mode=CapabilityRolloutMode.CANARY,
            changed_at=NOW,
            reason_code="INVALID",
        )
    with pytest.raises(ValidationError, match="only valid in canary mode"):
        CapabilityRolloutState(
            capability_id="us.daily.ohlcv",
            mode=CapabilityRolloutMode.ON,
            canary_targets=("US:TSM",),
            changed_at=NOW,
            reason_code="INVALID",
        )
