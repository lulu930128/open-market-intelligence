"""Deterministic, bounded event confirmation over canonical sampled trades."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def price_map_reaction(samples: list[dict[str, Any]], *, lower: float, upper: float, published_at: datetime, now: datetime, basis_revision: str) -> dict[str, Any]:
    result = {"status": "insufficient_evidence", "event": None, "basis_revision": basis_revision,
              "method": "ordered_canonical_trade_samples.v1", "confirmation_seconds": 60,
              "limitations": ["Sampled trade observations do not prove every intervening trade."]}
    if not 0 < lower < upper or not basis_revision:
        return result
    observations = []
    for sample in samples:
        try:
            stamp = datetime.fromisoformat(str(sample["time"]))
            price = float(sample["price"])
        except (KeyError, ValueError, TypeError):
            return result
        if stamp.tzinfo is None or not isfinite(price) or price <= 0:
            return result
        if stamp > now:
            return {**result, "status": "future_observation"}
        if stamp < published_at:
            continue
        if observations and (stamp <= observations[-1][0] or (stamp - observations[-1][0]).total_seconds() > 90):
            return {**result, "status": "sequence_gap"}
        observations.append((stamp, price))
    observations = observations[-32:]
    if len(observations) < 3 or (now - observations[-1][0]).total_seconds() > 90:
        return result
    side = lambda price: "above" if price > upper else "below" if price < lower else "touch"
    states = [side(price) for _, price in observations]
    event = None
    event_start = None
    for touch in range(1, len(states) - 1):
        if states[touch] != "touch" or states[touch - 1] == "touch":
            continue
        if (now - observations[touch][0]).total_seconds() > 300:
            continue
        direction = states[touch - 1]
        away = touch + 1
        while away < len(states) and states[away] == "touch":
            away += 1
        if away >= len(states) or states[away] != direction:
            continue
        if any(value != direction for value in states[away:]):
            continue
        if (observations[-1][0] - observations[away][0]).total_seconds() < 60:
            continue
        prior_opposite = any(value == ("below" if direction == "above" else "above") for value in states[:touch - 1])
        event = ("breakout_retest" if direction == "above" else "breakdown_retest") if prior_opposite else ("support_reaction" if direction == "above" else "resistance_reaction")
        event_start = observations[touch][0].isoformat()
    return {**result, "status": "confirmed" if event else "no_confirmed_event", "event": event,
            "touch_at": event_start, "confirmed_at": observations[-1][0].isoformat() if event else None,
            "sample_count": len(observations)}
