from __future__ import annotations

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import PROJECT_ROOT, settings
from app.routers.system import health_check, liveness_check, readiness_check


class SystemHealthTests(unittest.TestCase):
    def test_health_check_includes_runtime_metadata(self) -> None:
        payload = health_check()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["app_name"], settings.app_name)

        runtime = payload["runtime"]
        self.assertEqual(runtime["project_root"], str(PROJECT_ROOT))
        self.assertEqual(runtime["backend_dir"], str(PROJECT_ROOT / "backend"))
        self.assertEqual(runtime["python_executable"], sys.executable)
        self.assertTrue(runtime["python_version"])
        self.assertEqual(
            runtime["canonical_market_data_mode"],
            settings.canonical_market_data_mode,
        )
        expected_us_canary_count = len(
            {
                item.strip().upper()
                for item in settings.us_canonical_shadow_symbols.split(",")
                if item.strip()
            }
        )
        expected_us_mode = (
            settings.us_canonical_market_data_mode
            or settings.canonical_market_data_mode
        )
        self.assertEqual(runtime["us_canonical_market_data_mode"], expected_us_mode)
        self.assertEqual(runtime["canonical_market_data_rollout_stage"], expected_us_mode)
        self.assertEqual(
            runtime["us_canonical_shadow_enabled"],
            expected_us_mode != "off"
            and expected_us_canary_count > 0,
        )
        self.assertEqual(
            runtime["us_canonical_shadow_symbol_count"],
            expected_us_canary_count,
        )
        self.assertEqual(
            runtime["us_canonical_market_data_enabled"],
            expected_us_mode != "off"
            and (expected_us_mode == "on" or expected_us_canary_count > 0),
        )
        self.assertEqual(runtime["us_daily_read_binding_mode"], "canonical")
        self.assertEqual(
            runtime["us_daily_acquisition_rollout_mode"],
            expected_us_mode,
        )
        self.assertIn(
            runtime["us_daily_acquisition_scope"],
            {"none", "canary_targets", "all"},
        )
        self.assertIn(
            runtime["us_daily_acquisition_configuration_status"],
            {"valid", "invalid"},
        )
        self.assertEqual(
            runtime["fugle_realtime"]["provider"],
            "fugle_marketdata",
        )
        self.assertIn(
            runtime["fugle_realtime"]["connection"],
            {"disabled", "not_started", "connecting", "connected", "error"},
        )

    def test_health_check_keeps_invalid_canary_configuration_visible(self) -> None:
        with (
            unittest.mock.patch.object(
                settings,
                "us_canonical_market_data_mode",
                "canary",
            ),
            unittest.mock.patch.object(
                settings,
                "us_canonical_shadow_symbols",
                "AAPL,TSM,^SOX",
            ),
            unittest.mock.patch.object(
                settings,
                "us_canonical_canary_max_symbols",
                2,
            ),
        ):
            runtime = health_check()["runtime"]

        self.assertEqual(
            runtime["us_daily_acquisition_configuration_status"],
            "invalid",
        )
        self.assertFalse(runtime["us_daily_acquisition_enabled"])
        self.assertEqual(runtime["us_daily_acquisition_scope"], "none")
        self.assertIn("exceeds max_symbols=2", runtime["us_daily_acquisition_limitations"][0])

    def test_liveness_check_does_not_depend_on_runtime_or_database(self) -> None:
        payload = liveness_check()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"], {"process": "ok"})

    def test_readiness_check_requires_started_runtime_and_database(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(started=True)))
        )
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 1

        payload = readiness_check(request, db)

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["checks"], {"runtime": "ok", "database": "ok"})
        db.execute.assert_called_once()

    def test_readiness_check_returns_503_when_runtime_is_not_started(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(started=False)))
        )
        db = MagicMock()
        db.execute.return_value.scalar_one.return_value = 1

        response = readiness_check(request, db)
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["checks"], {"runtime": "not_ready", "database": "ok"})

    def test_readiness_check_returns_503_without_leaking_database_error(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(started=True)))
        )
        db = MagicMock()
        db.execute.side_effect = RuntimeError("private database detail")

        response = readiness_check(request, db)
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["checks"], {"runtime": "ok", "database": "not_ready"})
        self.assertNotIn("private database detail", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
