from __future__ import annotations

from datetime import date
import unittest

from app.ai.capability_contract import CAPABILITY_SPECS
from app.market.adr_parity import ADR_MAPPINGS
from app.market.overnight_impact import _factor_weights_for_mapping
from app.watchlists.radar_scoring_v2 import score_radar_signals


class CrossMarketGoldenContractTests(unittest.TestCase):
    def test_verified_adr_registry_baseline_is_explicit(self) -> None:
        self.assertEqual(
            {
                stock_id: {
                    "adr_symbol": mapping.adr_symbol,
                    "exchange": mapping.adr_exchange,
                    "local_shares_per_adr": mapping.local_shares_per_adr,
                    "verified_on": mapping.verified_on,
                }
                for stock_id, mapping in ADR_MAPPINGS.items()
            },
            {
                "2330": {
                    "adr_symbol": "TSM",
                    "exchange": "NYSE",
                    "local_shares_per_adr": 5,
                    "verified_on": date(2026, 7, 22),
                },
                "2303": {
                    "adr_symbol": "UMC",
                    "exchange": "NYSE",
                    "local_shares_per_adr": 5,
                    "verified_on": date(2026, 7, 22),
                },
                "3711": {
                    "adr_symbol": "ASX",
                    "exchange": "NYSE",
                    "local_shares_per_adr": 2,
                    "verified_on": date(2026, 7, 22),
                },
                "8150": {
                    "adr_symbol": "IMOS",
                    "exchange": "NASDAQ",
                    "local_shares_per_adr": 20,
                    "verified_on": date(2026, 7, 22),
                },
            },
        )

    def test_memory_profile_factor_weight_baseline_is_frozen(self) -> None:
        factor_weights, basket_weights = _factor_weights_for_mapping(
            {"profiles": ["memory", "semiconductor", "technology"]}
        )

        self.assertEqual(
            factor_weights,
            {
                "^GSPC": 0.08,
                "^IXIC": 0.14,
                "QQQ": 0.08,
                "^SOX": 0.20,
                "SMH": 0.14,
                "TSM": 0.08,
                "NVDA": 0.08,
                "MU": 0.20,
            },
        )
        self.assertEqual(
            basket_weights,
            {
                "記憶體_儲存": 0.18,
                "半導體_GPU_ASIC": 0.08,
                "ETF_科技": 0.05,
            },
        )

    def test_stock_cross_market_capability_baseline_is_frozen(self) -> None:
        capability = next(
            item
            for item in CAPABILITY_SPECS
            if item.capability_id == "cross_market.overnight"
        )

        self.assertEqual(capability.domain, "cross_market")
        self.assertEqual(capability.slot, "cross_market")
        self.assertEqual(capability.scopes, ("stock",))
        self.assertEqual(
            capability.fields,
            (
                "kind",
                "stock_id",
                "stock_name",
                "as_of",
                "generated_at",
                "stance",
                "context_status",
                "decision_usable",
                "summary",
                "signals",
                "bucket_scores",
                "coverage",
                "methodology_version",
                "relation_snapshot_version",
                "snapshot_id",
                "projection_source",
                "source_cutoff_at",
                "materialized_at",
                "materialized_by",
                "payload_hash",
                "limitations",
                "adr_parity",
                "factors",
                "baskets",
                "source",
                "source_refs",
                "freshness",
                "missing",
                "warnings",
            ),
        )
        self.assertTrue(
            {
                "as_of",
                "summary",
                "signals",
                "projection_source",
                "source_cutoff_at",
                "materialized_at",
                "materialized_by",
                "payload_hash",
                "source",
                "freshness",
                "warnings",
            }
            <= set(capability.default_fields)
        )

    def test_radar_context_is_independent_from_technical_priority(self) -> None:
        baseline = score_radar_signals(
            signal_keys=("ma20_bullish", "volume_price_up"),
            context_alignment_score=0.0,
        )
        supportive = score_radar_signals(
            signal_keys=("ma20_bullish", "volume_price_up"),
            context_alignment_score=100.0,
        )
        contradictory = score_radar_signals(
            signal_keys=("ma20_bullish", "volume_price_up"),
            context_alignment_score=-100.0,
        )

        for result in (supportive, contradictory):
            self.assertEqual(result["direction"], baseline["direction"])
            self.assertEqual(result["direction_score"], baseline["direction_score"])
            self.assertEqual(result["priority_score"], baseline["priority_score"])
            self.assertEqual(result["primary_bucket"], baseline["primary_bucket"])

        self.assertEqual(supportive["context_alignment_score"], 100.0)
        self.assertEqual(contradictory["context_alignment_score"], -100.0)


if __name__ == "__main__":
    unittest.main()
