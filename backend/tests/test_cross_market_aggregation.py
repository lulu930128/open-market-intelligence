from __future__ import annotations

from datetime import date, datetime
import unittest

from app.market.cross_market.aggregation import aggregate_cross_market_signals
from app.market.cross_market.schemas import (
    CrossMarketContextSignalRead,
    CrossMarketRelationRead,
    InstrumentRefRead,
)


SOURCE = InstrumentRefRead(
    market="US",
    instrument_type="stock",
    canonical_symbol="US:MU",
    provider_symbol="MU",
    exchange="NASDAQ",
    currency="USD",
)
TARGET = InstrumentRefRead(
    market="TW",
    instrument_type="stock",
    canonical_symbol="TW:2408",
    provider_symbol="2408",
    exchange="TWSE",
    currency="TWD",
)


class CrossMarketAggregationTests(unittest.TestCase):
    def test_bucket_normalization_does_not_inflate_missing_signal_coverage(self) -> None:
        relations = [
            CrossMarketRelationRead(
                relation_id=index,
                relation_version=1,
                source=SOURCE.model_copy(
                    update={"canonical_symbol": f"US:MU{index}", "provider_symbol": f"MU{index}"}
                ),
                target=TARGET,
                relation_type="industry_peer",
                relation_subtype="dram_memory_cycle_proxy",
                bucket="industry_peer",
                directionality="positive",
                base_weight=0.4,
                confidence_tier="C",
                evidence_grade="industry_mechanism",
                valid_from=date(2026, 8, 8),
                verified_at=datetime(2026, 8, 8),
                review_status="approved",
                status="ready",
                decision_usable=True,
            )
            for index in (1, 2)
        ]
        signals = [
            CrossMarketContextSignalRead(
                signal_id="usable",
                relation_id=1,
                relation_version=1,
                source=relations[0].source,
                target=TARGET,
                bucket="industry_peer",
                relation_type="industry_peer",
                calculation={"raw_return_pct": 3.0, "excess_return_pct": 2.0},
                direction="supportive",
                configured_weight=0.4,
                quality_multiplier=0.6,
                effective_weight=0.24,
                contribution=0.48,
                status="ready",
                decision_usable=True,
                confidence_tier="C",
            ),
            CrossMarketContextSignalRead(
                signal_id="blocked",
                relation_id=2,
                relation_version=1,
                source=relations[1].source,
                target=TARGET,
                bucket="industry_peer",
                relation_type="industry_peer",
                calculation={"raw_return_pct": 1.0, "excess_return_pct": None},
                direction="unknown",
                configured_weight=0.4,
                quality_multiplier=0.0,
                effective_weight=0.0,
                contribution=None,
                status="blocked",
                decision_usable=False,
                confidence_tier="C",
                excluded_reason="benchmark_or_return_missing",
            ),
        ]

        normalized, bucket_scores, coverage = aggregate_cross_market_signals(
            relations=relations,
            signals=signals,
        )

        self.assertEqual(normalized[0].normalized_weight, 1.0)
        self.assertIsNone(normalized[1].normalized_weight)
        self.assertEqual(bucket_scores["industry_peer"], 0.48)
        self.assertEqual(coverage.coverage_ratio, 0.5)
        self.assertEqual(coverage.excluded_by_reason, {"benchmark_or_return_missing": 1})


if __name__ == "__main__":
    unittest.main()
