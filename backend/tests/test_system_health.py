from __future__ import annotations

import sys
import unittest

from app.config import PROJECT_ROOT, settings
from app.routers.system import health_check


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


if __name__ == "__main__":
    unittest.main()
