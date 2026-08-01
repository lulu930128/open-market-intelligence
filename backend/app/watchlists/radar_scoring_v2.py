from __future__ import annotations

from math import exp
from numbers import Real
from typing import Any, Iterable, Mapping

from app.watchlists.radar_rule_contract import RADAR_V2_SCORING_CONFIG


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _score(value: Any, *, default: float, scale: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        return default
    number = float(value)
    if number != number:
        return default
    return _clamp(number / scale, 0.0, 1.0)


def _signed_score(value: Any, *, default: float, scale: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        return default
    number = float(value)
    if number != number:
        return default
    return _clamp(number / scale, -1.0, 1.0)


def _saturate(raw_score: float, *, cap: float, k: float) -> float:
    if raw_score <= 0:
        return 0.0
    return cap * (1.0 - exp(-raw_score / k))


def _conflict_ratio(bullish: float, bearish: float) -> float:
    total = bullish + bearish
    if total <= 0:
        return 0.0
    return (2.0 * min(bullish, bearish)) / total


def _evidence_grade(*, evidence: float, confidence: float, config: Mapping[str, Any]) -> str:
    grades = config["evidence_grades"]
    strong = grades["strong"]
    if (
        evidence >= float(strong["minimum_evidence"])
        and confidence >= float(strong["minimum_confidence"])
    ):
        return "strong"

    medium = grades["medium"]
    if (
        evidence >= float(medium["minimum_evidence"])
        and confidence >= float(medium["minimum_confidence"])
    ):
        return "medium"

    weak = grades["weak"]
    if evidence >= float(weak["minimum_evidence"]):
        return "weak"
    return "insufficient"


def _primary_bucket(
    *,
    direction: int,
    state_tags: set[str],
    risk_score: float,
    has_signals: bool,
) -> str:
    if not has_signals:
        return "quiet"
    if direction < 0 and {
        "support_break",
        "long_support_break",
        "breakout_down",
    }.intersection(state_tags):
        return "support_break"
    if direction > 0 and "breakout_up" in state_tags:
        return "breakout_high"
    if direction > 0 and {
        "trend_reclaim",
        "long_trend_reclaim",
    }.intersection(state_tags):
        return "trend_reclaim"
    if direction < 0 and "volume_down" in state_tags:
        return "volume_down"
    if direction > 0 and "volume_up" in state_tags:
        return "volume_up"
    if direction < 0:
        return "bearish_momentum"
    if direction > 0:
        return "momentum"
    if "overheated" in state_tags:
        return "overheated"
    if {
        "high_volatility",
        "volatility_expansion",
    }.intersection(state_tags) or risk_score >= 50:
        return "volatility_risk"
    if "compression" in state_tags:
        return "compression_watch"
    return "watch"


def derive_radar_v2_urgency(
    *,
    direction_score: float,
    evidence_score: float,
    risk_score: float,
    event_actionability_score: float,
) -> str:
    direction_strength = abs(direction_score)
    if (
        risk_score >= 65.0
        or (
            event_actionability_score >= 55.0
            and direction_strength >= 25.0
        )
    ):
        return "high"
    if (
        risk_score >= 35.0
        or direction_strength >= 35.0
        or evidence_score >= 45.0
        or event_actionability_score >= 30.0
    ):
        return "medium"
    return "low"


def score_radar_signals(
    *,
    signal_keys: Iterable[str],
    strengths: Mapping[str, float] | None = None,
    freshness_by_signal: Mapping[str, float] | None = None,
    data_quality_score: float = 1.0,
    regime_clarity: float = 1.0,
    timeframe_conflict_score: float = 0.0,
    urgency: str | float | None = "low",
    context_alignment_score: float = 0.0,
    config: Mapping[str, Any] = RADAR_V2_SCORING_CONFIG,
) -> dict[str, Any]:
    definitions = config["signal_definitions"]
    type_factors = config["signal_type_factors"]
    directional_families = list(config["directional_families"])
    family_weights = config["family_direction_weights"]
    family_saturation = config["family_saturation"]
    strengths = strengths or {}
    freshness_by_signal = freshness_by_signal or {}

    normalized_keys = sorted(
        {
            str(key).strip()
            for key in signal_keys
            if str(key or "").strip()
        }
    )
    unknown_signals = [key for key in normalized_keys if key not in definitions]
    known_signals = [key for key in normalized_keys if key in definitions]

    family_raw: dict[str, dict[str, Any]] = {
        family: {
            "bullish_raw": 0.0,
            "bearish_raw": 0.0,
            "risk_raw": 0.0,
            "signal_keys": [],
        }
        for family in {
            *directional_families,
            "location",
            "volatility",
        }
    }
    contributions: list[dict[str, Any]] = []
    state_tags: set[str] = set()
    risk_tags: set[str] = set()
    total_directional_raw = 0.0
    event_directional_raw = 0.0

    for key in known_signals:
        definition = definitions[key]
        family = str(definition["family"])
        family_state = family_raw.setdefault(
            family,
            {
                "bullish_raw": 0.0,
                "bearish_raw": 0.0,
                "risk_raw": 0.0,
                "signal_keys": [],
            },
        )
        signal_type = str(definition["signal_type"])
        strength = _score(strengths.get(key), default=1.0)
        freshness = _score(freshness_by_signal.get(key), default=1.0)
        direction = int(definition["direction"])
        type_factor = float(type_factors[signal_type])
        base_weight = float(definition["base_weight"])
        risk_weight = float(definition["risk_weight"])
        directional_raw = base_weight * strength * freshness * type_factor
        risk_raw = risk_weight * strength * freshness

        if direction > 0:
            family_state["bullish_raw"] += directional_raw
        elif direction < 0:
            family_state["bearish_raw"] += directional_raw
        family_state["risk_raw"] += risk_raw
        family_state["signal_keys"].append(key)

        total_directional_raw += directional_raw
        if signal_type == "event":
            event_directional_raw += directional_raw
        state_tags.update(str(tag) for tag in definition.get("state_tags", []))
        risk_tags.update(str(tag) for tag in definition.get("risk_tags", []))
        contributions.append(
            {
                "signal_key": key,
                "family": family,
                "direction": direction,
                "signal_type": signal_type,
                "strength": round(strength, 6),
                "freshness_factor": round(freshness, 6),
                "directional_raw": round(directional_raw, 6),
                "risk_raw": round(risk_raw, 6),
            }
        )

    cap = float(family_saturation["cap"])
    saturation_k = float(family_saturation["k"])
    family_scores: dict[str, dict[str, Any]] = {}
    weighted_direction = 0.0
    weighted_evidence = 0.0
    within_conflict_weighted = 0.0
    within_conflict_denominator = 0.0
    global_bullish = 0.0
    global_bearish = 0.0

    for family, values in sorted(family_raw.items()):
        bullish = _saturate(
            float(values["bullish_raw"]),
            cap=cap,
            k=saturation_k,
        )
        bearish = _saturate(
            float(values["bearish_raw"]),
            cap=cap,
            k=saturation_k,
        )
        evidence = max(bullish, bearish)
        conflict = _conflict_ratio(bullish, bearish)
        direction_score = bullish - bearish
        weight = float(family_weights.get(family, 0.0))
        weighted_direction += weight * direction_score
        weighted_evidence += weight * evidence
        within_conflict_weighted += weight * evidence * conflict
        within_conflict_denominator += weight * evidence
        if direction_score > 0:
            global_bullish += weight * direction_score
        elif direction_score < 0:
            global_bearish += weight * abs(direction_score)

        family_scores[family] = {
            "bullish_raw": round(float(values["bullish_raw"]), 6),
            "bearish_raw": round(float(values["bearish_raw"]), 6),
            "bullish_score": round(bullish, 6),
            "bearish_score": round(bearish, 6),
            "direction_score": round(direction_score, 6),
            "evidence_score": round(evidence, 6),
            "conflict_score": round(conflict * 100.0, 6),
            "risk_raw": round(float(values["risk_raw"]), 6),
            "signal_keys": list(values["signal_keys"]),
        }

    maximum_weighted_score = cap * sum(
        float(family_weights[family]) for family in directional_families
    )
    direction_score = (
        100.0 * weighted_direction / maximum_weighted_score
        if maximum_weighted_score > 0
        else 0.0
    )
    evidence_score = (
        100.0 * weighted_evidence / maximum_weighted_score
        if maximum_weighted_score > 0
        else 0.0
    )
    within_family_conflict = (
        100.0 * within_conflict_weighted / within_conflict_denominator
        if within_conflict_denominator > 0
        else 0.0
    )
    cross_family_conflict = 100.0 * _conflict_ratio(
        global_bullish,
        global_bearish,
    )
    timeframe_conflict = 100.0 * _score(
        timeframe_conflict_score,
        default=0.0,
        scale=100.0,
    )
    conflict_weights = config["conflict_weights"]
    conflict_score = (
        float(conflict_weights["within_family"]) * within_family_conflict
        + float(conflict_weights["cross_family"]) * cross_family_conflict
        + float(conflict_weights["timeframe"]) * timeframe_conflict
    )

    total_risk_raw = sum(float(values["risk_raw"]) for values in family_raw.values())
    risk_config = config["risk_saturation"]
    risk_score = 100.0 * _saturate(
        total_risk_raw,
        cap=float(risk_config["cap"]),
        k=float(risk_config["k"]),
    ) / float(risk_config["cap"])
    data_quality = _score(data_quality_score, default=0.0)
    clarity = _score(regime_clarity, default=0.0)
    conflict_penalty = float(config["confidence"]["conflict_penalty"])
    confidence_score = (
        evidence_score
        * max(0.0, 1.0 - (conflict_score / 100.0) * conflict_penalty)
        * data_quality
        * clarity
    )

    direction_threshold = float(config["direction_threshold"])
    direction = 0
    if direction_score >= direction_threshold:
        direction = 1
    elif direction_score <= -direction_threshold:
        direction = -1

    event_actionability = (
        100.0 * event_directional_raw / total_directional_raw
        if total_directional_raw > 0
        else 0.0
    )
    if urgency is None:
        urgency_label = derive_radar_v2_urgency(
            direction_score=direction_score,
            evidence_score=evidence_score,
            risk_score=risk_score,
            event_actionability_score=event_actionability,
        )
        urgency_score = float(config["urgency_scores"][urgency_label])
    elif isinstance(urgency, str):
        urgency_score = float(config["urgency_scores"].get(urgency, 20.0))
        urgency_label = urgency if urgency in config["urgency_scores"] else "low"
    else:
        urgency_score = 100.0 * _score(urgency, default=0.0, scale=100.0)
        urgency_label = (
            "high"
            if urgency_score >= 70
            else "medium"
            if urgency_score >= 40
            else "low"
        )
    priority_weights = config["priority_weights"]
    priority_score = (
        float(priority_weights["direction_strength"]) * abs(direction_score)
        + float(priority_weights["confidence"]) * confidence_score
        + float(priority_weights["risk"]) * risk_score
        + float(priority_weights["urgency"]) * urgency_score
        + float(priority_weights["event_actionability"]) * event_actionability
    )

    limitations = []
    if unknown_signals:
        limitations.append(
            {
                "code": "unknown_signal_definitions",
                "signal_keys": unknown_signals,
            }
        )
    if data_quality < 1.0:
        limitations.append(
            {
                "code": "data_quality_discount",
                "score": round(data_quality, 6),
            }
        )

    primary_bucket = _primary_bucket(
        direction=direction,
        state_tags=state_tags,
        risk_score=risk_score,
        has_signals=bool(known_signals),
    )
    return {
        "direction": direction,
        "direction_score": round(_clamp(direction_score, -100.0, 100.0), 6),
        "evidence_score": round(_clamp(evidence_score, 0.0, 100.0), 6),
        "within_family_conflict_score": round(
            _clamp(within_family_conflict, 0.0, 100.0),
            6,
        ),
        "cross_family_conflict_score": round(
            _clamp(cross_family_conflict, 0.0, 100.0),
            6,
        ),
        "timeframe_conflict_score": round(timeframe_conflict, 6),
        "conflict_score": round(_clamp(conflict_score, 0.0, 100.0), 6),
        "risk_score": round(_clamp(risk_score, 0.0, 100.0), 6),
        "confidence_score": round(_clamp(confidence_score, 0.0, 100.0), 6),
        "priority_score": round(_clamp(priority_score, 0.0, 100.0), 6),
        "context_alignment_score": round(
            100.0
            * _signed_score(
                context_alignment_score,
                default=0.0,
                scale=100.0,
            ),
            6,
        ),
        "primary_bucket": primary_bucket,
        "urgency": urgency_label,
        "evidence_grade": _evidence_grade(
            evidence=evidence_score,
            confidence=confidence_score,
            config=config,
        ),
        "state_tags": sorted(state_tags),
        "risk_tags": sorted(risk_tags),
        "family_scores": family_scores,
        "signal_contributions": contributions,
        "event_actionability_score": round(
            _clamp(event_actionability, 0.0, 100.0),
            6,
        ),
        "known_signal_count": len(known_signals),
        "unknown_signal_keys": unknown_signals,
        "limitations": limitations,
    }


__all__ = ["derive_radar_v2_urgency", "score_radar_signals"]
