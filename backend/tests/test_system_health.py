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
