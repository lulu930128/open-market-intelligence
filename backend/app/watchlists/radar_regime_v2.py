from __future__ import annotations

from copy import deepcopy
from numbers import Real
from typing import Any, Iterable, Mapping

from app.watchlists.radar_rule_contract import (
    RADAR_V2_REGIME_CONFIG,
    RADAR_V2_SCORING_CONFIG,
    RADAR_V2_SIGNAL_DEFINITIONS,
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, value))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if number == number else None


def _nested_number(
    payload: Mapping[str, Any],
    section: str,
    key: str,
) -> float | None:
    values = payload.get(section)
    if not isinstance(values, Mapping):
        return None
    return _number(values.get(key))


def _directional_vote(signal_keys: Iterable[str]) -> tuple[float, list[str]]:
    vote = 0.0
    used: list[str] = []
    for raw_key in sorted({str(key) for key in signal_keys}):
        definition = RADAR_V2_SIGNAL_DEFINITIONS.get(raw_key)
        if not definition or definition["family"] not in {"trend", "structure"}:
            continue
        direction = int(definition["direction"])
        if direction == 0:
            continue
        signal_type_factor = 1.0 if definition["signal_type"] == "event" else 0.45
        vote += direction * float(definition["base_weight"]) * signal_type_factor
        used.append(raw_key)
    return vote, used


def classify_instrument_regime(
    *,
    indicator_snapshot: Mapping[str, Any],
    signal_keys: Iterable[str],
    close_price: float | None = None,
    config: Mapping[str, Any] = RADAR_V2_REGIME_CONFIG,
) -> dict[str, Any]:
    rule = config["instrument_regime"]
    normalized_keys = sorted({str(key) for key in signal_keys})
    adx = _nested_number(indicator_snapshot, "adx", "adx14")
    plus_di = _nested_number(indicator_snapshot, "adx", "plus_di14")
    minus_di = _nested_number(indicator_snapshot, "adx", "minus_di14")
    atr = _nested_number(indicator_snapshot, "atr", "atr14")
    bandwidth = _nested_number(
        indicator_snapshot,
        "bollinger",
        "bandwidth20_pct",
    )
    close = _number(close_price)
    atr_pct = (
        (atr / close) * 100.0
        if atr is not None and close not in {None, 0.0}
        else None
    )
    vote, vote_signals = _directional_vote(normalized_keys)
    if plus_di is not None and minus_di is not None:
        di_direction = 1 if plus_di > minus_di else -1 if minus_di > plus_di else 0
        di_separation = (
            abs(plus_di - minus_di) / max(plus_di + minus_di, 1.0)
        )
    else:
        di_direction = 0
        di_separation = 0.0

    evidence_fields = sum(
        value is not None
        for value in (adx, atr_pct, bandwidth)
    )
    has_directional_evidence = bool(vote_signals) or di_direction != 0
    limitations: list[dict[str, Any]] = []
    if adx is None:
        limitations.append({"code": "missing_adx14"})
    if atr_pct is None:
        limitations.append({"code": "missing_atr_pct"})
    if bandwidth is None:
        limitations.append({"code": "missing_bollinger_bandwidth"})

    compression_threshold = float(rule["bollinger_compression_bandwidth_pct"])
    high_volatility_threshold = float(rule["atr_high_volatility_pct"])
    volatility_state = (
        "high"
        if (
            (atr_pct is not None and atr_pct >= high_volatility_threshold)
            or "atr_high_volatility" in normalized_keys
        )
        else "expanding"
        if "atr_expanding" in normalized_keys
        else "normal"
        if atr_pct is not None
        else "unknown"
    )

    if evidence_fields == 0 and not normalized_keys:
        regime = "insufficient"
        clarity = 0.0
    elif (
        "bollinger_squeeze" in normalized_keys
        or (bandwidth is not None and bandwidth <= compression_threshold)
    ):
        regime = "compression"
        if bandwidth is None:
            clarity = 0.65
        else:
            clarity = _clamp(
                0.55
                + 0.45
                * (compression_threshold - bandwidth)
                / max(compression_threshold, 1.0)
            )
    elif (
        adx is not None
        and adx >= float(rule["adx_trend_threshold"])
        and abs(vote) >= float(rule["minimum_directional_vote"])
    ):
        resolved_vote = vote
        if di_direction and vote * di_direction < 0:
            resolved_vote *= 0.5
        regime = "trend_up" if resolved_vote > 0 else "trend_down"
        adx_clarity = _clamp(
            (adx - float(rule["adx_range_threshold"])) / 25.0
        )
        vote_clarity = _clamp(abs(vote) / 5.0)
        clarity = _clamp(
            0.45 * adx_clarity
            + 0.40 * vote_clarity
            + 0.15 * di_separation
        )
    elif adx is not None and adx < float(rule["adx_range_threshold"]):
        regime = "range"
        clarity = _clamp(
            0.50
            + 0.35
            * (float(rule["adx_range_threshold"]) - adx)
            / max(float(rule["adx_range_threshold"]), 1.0)
            + (0.15 if abs(vote) < 1.0 else 0.0)
        )
    else:
        regime = "transition"
        coverage = evidence_fields / 3.0
        directional_consistency = 1.0 if has_directional_evidence else 0.5
        clarity = _clamp(0.25 + 0.30 * coverage + 0.20 * directional_consistency)

    if volatility_state == "high" and regime in {"range", "transition"}:
        limitations.append(
            {
                "code": "high_volatility_regime_overlay",
                "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
            }
        )
        clarity *= 0.85

    return {
        "instrument_regime": regime,
        "instrument_regime_clarity": round(_clamp(clarity), 6),
        "volatility_state": volatility_state,
        "metrics": {
            "adx14": adx,
            "plus_di14": plus_di,
            "minus_di14": minus_di,
            "atr_pct": round(atr_pct, 6) if atr_pct is not None else None,
            "bollinger_bandwidth20_pct": bandwidth,
            "directional_vote": round(vote, 6),
        },
        "directional_vote_signal_keys": vote_signals,
        "limitations": limitations,
    }


def classify_market_regime(
    *,
    market_snapshot: Mapping[str, Any] | None,
    config: Mapping[str, Any] = RADAR_V2_REGIME_CONFIG,
) -> dict[str, Any]:
    rule = config["market_regime"]
    if not market_snapshot:
        return {
            "market_regime": "insufficient",
            "market_regime_clarity": 0.0,
            "metrics": {},
            "limitations": [{"code": "missing_market_snapshot"}],
        }

    quality_status = str(market_snapshot.get("quality_status") or "unknown")
    breadth_scope = str(market_snapshot.get("breadth_scope") or "unknown")
    advance = _number(market_snapshot.get("advance_count"))
    decline = _number(market_snapshot.get("decline_count"))
    total = _number(market_snapshot.get("total_count"))
    unknown = _number(market_snapshot.get("unknown_count")) or 0.0
    missing = _number(market_snapshot.get("missing_count")) or 0.0
    index_change_pct = _number(market_snapshot.get("index_change_pct"))
    index_above_ma20 = market_snapshot.get("index_above_ma20")
    index_above_ma60 = market_snapshot.get("index_above_ma60")

    categorized = (
        (advance or 0.0) + (decline or 0.0)
        if advance is not None or decline is not None
        else 0.0
    )
    breadth_ratio = (
        ((advance or 0.0) - (decline or 0.0)) / categorized
        if categorized > 0
        else None
    )
    coverage = (
        max(0.0, (total - unknown - missing) / total)
        if total not in {None, 0.0}
        else None
    )
    limitations: list[dict[str, Any]] = []
    if quality_status not in set(rule["accepted_quality_statuses"]):
        limitations.append(
            {
                "code": "market_quality_not_ready",
                "quality_status": quality_status,
            }
        )
    if breadth_scope not in set(rule["accepted_breadth_scopes"]):
        limitations.append(
            {
                "code": "market_breadth_not_full_market",
                "breadth_scope": breadth_scope,
            }
        )
    if coverage is None or coverage < float(rule["minimum_breadth_coverage"]):
        limitations.append(
            {
                "code": "insufficient_market_breadth_coverage",
                "coverage": round(coverage, 6) if coverage is not None else None,
            }
        )
    if breadth_ratio is None:
        limitations.append({"code": "missing_market_breadth_direction"})
    if index_change_pct is None:
        limitations.append({"code": "missing_index_change_pct"})

    quality_blocked = any(
        limitation["code"]
        in {
            "market_quality_not_ready",
            "market_breadth_not_full_market",
            "insufficient_market_breadth_coverage",
        }
        for limitation in limitations
    )
    if quality_blocked or breadth_ratio is None or index_change_pct is None:
        regime = "insufficient"
        clarity = 0.0
    else:
        strong_breadth = float(rule["strong_breadth_ratio"])
        moderate_breadth = float(rule["moderate_breadth_ratio"])
        strong_change = float(rule["strong_index_change_pct"])
        moderate_change = float(rule["moderate_index_change_pct"])
        if breadth_ratio >= strong_breadth and index_change_pct >= strong_change:
            regime = "risk_on"
        elif breadth_ratio <= -strong_breadth and index_change_pct <= -strong_change:
            regime = "risk_off"
        elif breadth_ratio >= moderate_breadth and index_change_pct >= moderate_change:
            regime = "broad_up"
        elif breadth_ratio <= -moderate_breadth and index_change_pct <= -moderate_change:
            regime = "broad_down"
        elif breadth_ratio * index_change_pct < 0:
            regime = "mixed"
        else:
            regime = "transition"

        breadth_strength = _clamp(abs(breadth_ratio) / strong_breadth)
        change_strength = _clamp(abs(index_change_pct) / strong_change)
        trend_confirmation = sum(
            value is True
            for value in (index_above_ma20, index_above_ma60)
        )
        if regime in {"risk_off", "broad_down"}:
            trend_confirmation = sum(
                value is False
                for value in (index_above_ma20, index_above_ma60)
            )
        clarity = _clamp(
            0.15
            + 0.40 * breadth_strength
            + 0.35 * change_strength
            + 0.05 * trend_confirmation
        )
        if regime in {"mixed", "transition"}:
            clarity *= 0.65

    return {
        "market_regime": regime,
        "market_regime_clarity": round(_clamp(clarity), 6),
        "metrics": {
            "breadth_ratio": (
                round(breadth_ratio, 6) if breadth_ratio is not None else None
            ),
            "breadth_coverage": (
                round(coverage, 6) if coverage is not None else None
            ),
            "index_change_pct": index_change_pct,
            "index_above_ma20": (
                index_above_ma20 if isinstance(index_above_ma20, bool) else None
            ),
            "index_above_ma60": (
                index_above_ma60 if isinstance(index_above_ma60, bool) else None
            ),
        },
        "limitations": limitations,
    }


def combined_regime_clarity(
    *,
    instrument_regime_clarity: float,
    market_regime_clarity: float | None,
    config: Mapping[str, Any] = RADAR_V2_REGIME_CONFIG,
) -> float:
    rule = config["combined_clarity"]
    instrument = _clamp(_number(instrument_regime_clarity) or 0.0)
    market_number = _number(market_regime_clarity)
    market = (
        _clamp(market_number)
        if market_number is not None
        else float(rule["missing_market_clarity"])
    )
    weighted_market_factor = (
        float(rule["instrument_weight"])
        + float(rule["market_weight"]) * market
    )
    return round(_clamp(instrument * weighted_market_factor), 6)


def scoring_config_for_instrument_regime(
    instrument_regime: str,
    *,
    scoring_config: Mapping[str, Any] = RADAR_V2_SCORING_CONFIG,
    regime_config: Mapping[str, Any] = RADAR_V2_REGIME_CONFIG,
) -> dict[str, Any]:
    adjusted = deepcopy(dict(scoring_config))
    multipliers_by_regime = regime_config["instrument_regime"][
        "family_weight_multipliers"
    ]
    multipliers = multipliers_by_regime.get(
        instrument_regime,
        multipliers_by_regime["transition"],
    )
    adjusted["family_direction_weights"] = {
        family: float(weight) * float(multipliers.get(family, 1.0))
        for family, weight in adjusted["family_direction_weights"].items()
    }
    adjusted["applied_instrument_regime"] = instrument_regime
    return adjusted


__all__ = [
    "classify_instrument_regime",
    "classify_market_regime",
    "combined_regime_clarity",
    "scoring_config_for_instrument_regime",
]
