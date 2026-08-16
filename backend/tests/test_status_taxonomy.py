from __future__ import annotations

import unittest

from app.observability.status_taxonomy import (
    STATUS_CONTRACT_VERSION,
    build_status_dimensions,
    status_dimensions_from_quality_contract,
    summarize_status_dimensions,
)


class StatusTaxonomyTests(unittest.TestCase):
    def test_service_availability_does_not_hide_stale_data(self) -> None:
        result = build_status_dimensions(
            {
                "status": "stale",
                "data_quality": "stale",
                "required": True,
            }
        )

        self.assertEqual(result["version"], STATUS_CONTRACT_VERSION)
        self.assertEqual(result["service_status"], "available")
        self.assertEqual(result["data_quality"], "stale")
        self.assertEqual(result["decision_readiness"], "limited")
        self.assertEqual(result["provider_status"], "unknown")
        self.assertIn("data_stale", result["reason_codes"])

    def test_provider_failure_is_independent_and_blocks_missing_required_data(self) -> None:
        result = build_status_dimensions(
            {
                "status": "error",
                "data_quality": "error",
                "required": True,
                "health_dimensions": {
                    "provider_availability": {"status": "unavailable"}
                },
            }
        )

        self.assertEqual(result["service_status"], "available")
        self.assertEqual(result["data_quality"], "failed")
        self.assertEqual(result["decision_readiness"], "blocked")
        self.assertEqual(result["provider_status"], "unavailable")

    def test_repair_exhaustion_is_visible_in_decision_readiness(self) -> None:
        result = build_status_dimensions(
            {
                "status": "partial",
                "data_quality": "partial",
                "required": True,
                "health_dimensions": {"repair": {"status": "exhausted"}},
            }
        )

        self.assertEqual(result["decision_readiness"], "blocked")
        self.assertIn("repair_exhausted", result["reason_codes"])

    def test_summary_uses_worst_axis_without_overwriting_independent_axes(self) -> None:
        result = summarize_status_dimensions(
            [
                {
                    "status_dimensions": build_status_dimensions(
                        {"status": "current", "data_quality": "ok"}
                    )
                },
                {
                    "status_dimensions": build_status_dimensions(
                        {
                            "status": "stale",
                            "data_quality": "stale",
                            "health_dimensions": {
                                "provider_availability": {"status": "degraded"}
                            },
                        }
                    )
                },
            ]
        )

        self.assertEqual(result["service_status"], "available")
        self.assertEqual(result["data_quality"], "stale")
        self.assertEqual(result["decision_readiness"], "limited")
        self.assertEqual(result["provider_status"], "degraded")

    def test_ai_quality_contract_projects_the_same_axis_names(self) -> None:
        result = status_dimensions_from_quality_contract(
            {
                "status": "partial",
                "decision_ready": False,
                "limited_required_capabilities": ["market.indices"],
                "blocked_required_capabilities": [],
                "capabilities": {
                    "market.indices": {
                        "required": True,
                        "selected_provider": "twse_mis",
                        "fallback_used": True,
                        "availability_status": "available",
                    }
                },
                "issues": [{"code": "stale_index"}],
            }
        )

        self.assertEqual(result["service_status"], "available")
        self.assertEqual(result["data_quality"], "partial")
        self.assertEqual(result["decision_readiness"], "limited")
        self.assertEqual(result["provider_status"], "degraded")
        self.assertEqual(result["reason_codes"], ["stale_index"])


if __name__ == "__main__":
    unittest.main()
