from __future__ import annotations

from pathlib import Path
import shutil
import unittest
import uuid

from app.runtime_lock import ProcessFileLock


class ProcessFileLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = (
            Path(__file__).resolve().parents[2]
            / ".tmp"
            / "test_runtime_lock"
            / uuid.uuid4().hex
        )
        self.directory.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_lock_is_exclusive_and_released_for_the_next_owner(self) -> None:
        path = self.directory / "runtime.lock"
        first = ProcessFileLock(path)
        second = ProcessFileLock(path)

        self.assertTrue(first.acquire())
        self.assertTrue(first.acquired)
        self.assertFalse(second.acquire())

        first.release()
        first.release()
        self.assertFalse(first.acquired)
        self.assertTrue(second.acquire())
        self.assertTrue(second.acquired)

        second.release()


if __name__ == "__main__":
    unittest.main()
