"""Pure deterministic candidate gate. Selection is not a recommendation to chase."""
from __future__ import annotations

from hashlib import sha256
import json

from app.market.tw_intraday_radar_contracts import (
    IntradayCandidate, IntradayCandidateConfig, IntradayDiscovery, IntradayRadarResult,
)


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def evaluate_intraday_candidates(
    discovery: IntradayDiscovery, *, config: IntradayCandidateConfig | None = None,
) -> IntradayRadarResult:
    config = config or IntradayCandidateConfig()
    config_hash = _digest(config.model_dump(mode="json"))
    limitations = (*discovery.limitations, "RESEARCH_CANDIDATE_NOT_ENTRY_SIGNAL",
                   "CANDIDATE_ESCALATION_NOT_IMPLEMENTED", "EVENT_LIFECYCLE_NOT_IMPLEMENTED")
    candidates = []
    exclusions = {}
    for observation in sorted(discovery.observations, key=lambda row: (row.market, row.stock_id)):
        reasons = list(observation.exclusion_reasons)
        if not observation.research_eligible:
            reasons.append("CURRENT_RESEARCH_EVIDENCE_REQUIRED")
        features = observation.features
        for name, feature, threshold, minimum in (
            ("CHANGE_PCT", features.change_pct, config.min_change_pct, True),
            ("RETURN_3M", features.return_3m, config.min_return_3m, True),
            ("DISTANCE_FROM_HIGH", features.distance_from_high_pct, config.max_distance_from_high_pct, False),
        ):
            if feature.value is None:
                reasons.append(f"{name}:{feature.reason}")
            elif (feature.value < threshold if minimum else feature.value > threshold):
                reasons.append(f"{name}:THRESHOLD_NOT_MET")
        volume = observation.cumulative_volume_lots
        if volume is None or volume < config.min_cumulative_volume_lots:
            reasons.append("BASIC_LIQUIDITY_NOT_MET")
        if reasons:
            exclusions[observation.stock_id] = tuple(dict.fromkeys(reasons))
        else:
            candidates.append(IntradayCandidate(observation=observation, limitations=limitations))
    # Include all evaluated evidence, not just winners: corrections and universe
    # changes must invalidate an evaluation even when the candidate list is stable.
    evidence = discovery.model_dump(mode="json")
    evidence["observations"] = sorted(evidence["observations"], key=lambda row: (row["market"], row["stock_id"]))
    return IntradayRadarResult(
        evaluated_at=discovery.evaluated_at, status=discovery.coverage.status,
        config=config, config_hash=config_hash,
        evaluation_id=_digest({"config_hash": config_hash, "discovery": evidence}),
        coverage=discovery.coverage, candidates=tuple(candidates),
        gate_exclusions=exclusions, limitations=limitations,
    )
