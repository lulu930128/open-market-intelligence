from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from app.market.cross_market.schemas import (
    CrossMarketContextCoverageRead,
    CrossMarketContextSignalRead,
    CrossMarketRelationRead,
)


def aggregate_cross_market_signals(
    *,
    relations: Iterable[CrossMarketRelationRead],
    signals: Iterable[CrossMarketContextSignalRead],
) -> tuple[
    list[CrossMarketContextSignalRead],
    dict[str, float | None],
    CrossMarketContextCoverageRead,
]:
    relation_rows = list(relations)
    signal_rows = list(signals)
    usable_weight_by_bucket: dict[str, float] = defaultdict(float)
    for signal in signal_rows:
        if signal.decision_usable:
            usable_weight_by_bucket[signal.bucket] += signal.effective_weight

    normalized: list[CrossMarketContextSignalRead] = []
    for signal in signal_rows:
        denominator = usable_weight_by_bucket.get(signal.bucket, 0.0)
        normalized_weight = (
            round(signal.effective_weight / denominator, 6)
            if signal.decision_usable and denominator > 0
            else None
        )
        normalized.append(
            signal.model_copy(update={"normalized_weight": normalized_weight})
        )

    bucket_names = list(
        dict.fromkeys(
            [relation.bucket for relation in relation_rows]
            + [signal.bucket for signal in normalized]
        )
    )
    bucket_scores = {
        bucket: (
            round(
                sum(
                    float(signal.contribution or 0.0)
                    for signal in normalized
                    if signal.bucket == bucket and signal.decision_usable
                ),
                6,
            )
            if any(
                signal.bucket == bucket and signal.decision_usable
                for signal in normalized
            )
            else None
        )
        for bucket in bucket_names
    }
    configured_weight = sum(float(relation.base_weight) for relation in relation_rows)
    configured_count = len(relation_rows)
    if not relation_rows and signal_rows:
        configured_weight = sum(
            float(signal.configured_weight) for signal in signal_rows
        )
        configured_count = len(signal_rows)
    available_weight = sum(
        float(signal.configured_weight)
        for signal in normalized
        if signal.calculation.get("raw_return_pct") is not None
        or signal.calculation.get("implied_gap_pct") is not None
    )
    usable_weight = sum(
        float(signal.configured_weight)
        for signal in normalized
        if signal.decision_usable
    )
    excluded = Counter(
        str(signal.excluded_reason)
        for signal in normalized
        if not signal.decision_usable and signal.excluded_reason
    )
    coverage = CrossMarketContextCoverageRead(
        configured_signal_count=configured_count,
        available_signal_count=sum(
            signal.calculation.get("raw_return_pct") is not None
            or signal.calculation.get("implied_gap_pct") is not None
            for signal in normalized
        ),
        decision_usable_signal_count=sum(
            signal.decision_usable for signal in normalized
        ),
        configured_weight=round(configured_weight, 6),
        available_weight=round(available_weight, 6),
        decision_usable_weight=round(usable_weight, 6),
        coverage_ratio=(
            round(usable_weight / configured_weight, 6)
            if configured_weight > 0
            else 0.0
        ),
        excluded_by_reason=dict(excluded),
    )
    return normalized, bucket_scores, coverage


__all__ = ["aggregate_cross_market_signals"]
