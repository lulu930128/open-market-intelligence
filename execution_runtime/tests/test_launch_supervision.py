"""Real child exit and same canonical leases, exclusively synthetic fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from execution_runtime.launch import supervise, request_supervisor_stop, read_receipt, optional_receipt
from execution_runtime.service import record_startup
from execution_runtime import control
from .test_connection_lifecycle import eventually
from execution_runtime.storage import OwnerLease


@unittest.skipUnless(os.name == "nt", "Windows process/pipe")
class SupervisionTests(unittest.TestCase):
    def scenario(self, mode):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory).resolve()
            (root / "SYNTHETIC_ONLY").touch()
            startup = uuid4().hex
            address = r"\\.\pipe\omi-supervisor-fixture-" + uuid4().hex
            command = [sys.executable, "-B", "-m", "execution_runtime.tests.connection_process_worker",
                       "--directory", str(root), "--address", address,
                       "--scenario", mode]
            children = []
            def start(arguments, **kwargs):
                child = subprocess.Popen(arguments, **kwargs)
                children.append((child, arguments[-1]))
                return child
            spawn = Mock(side_effect=start)
            try:
                code = supervise(command, {}, root, startup, spawn=spawn, retry_base=0.02, retry_cap=0.1)
            finally:
                for child, identity in children:
                    if child.poll() is None:
                        receipt = optional_receipt(root / ("startup-" + identity + ".json"))
                        if receipt and receipt.get("pid"):
                            with patch.object(control, "ADDRESS", address):
                                try:
                                    control.request_control({"operation": "stop"}, expected_pid=receipt["pid"], timeout=2)
                                except FileNotFoundError:
                                    pass  # Fixture can finish its deliberate crash before this stop.
                        child.wait(timeout=5)  # No kill/terminate; prove exit before temp cleanup.
            receipt = json.loads((root / ("startup-" + startup + ".json")).read_text(encoding="utf-8"))
            if mode == "crash_then_stop":
                self.assertEqual(code, 0)
                self.assertEqual(spawn.call_count, 2)
                self.assertTrue((root / "no-replay-verified").exists())
                self.assertEqual(receipt["reason"], "OPERATOR_STOP")
            elif mode == "fatal":
                self.assertEqual(code, 2)
                self.assertEqual(spawn.call_count, 1)
            else:
                self.assertEqual(code, 0)
                self.assertEqual(spawn.call_count, 1)
                self.assertEqual(receipt["desired"], "OFFLINE")

    def test_actual_crash_restart_same_journal_unknown_not_replayed_then_stop(self):
        self.scenario("crash_then_stop")

    def test_fatal_child_not_restarted(self):
        self.scenario("fatal")

    def test_durable_operator_stop_followed_by_crash_not_restarted(self):
        self.scenario("stop_then_crash")

    def test_unknown_native_owner_and_duplicate_supervisor_never_spawn(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            spawn = Mock(side_effect=AssertionError("must not spawn"))
            for name in ("native-session", "launch-supervisor"):
                lease = OwnerLease(root / name)
                lease.acquire()
                try:
                    if name == "native-session":
                        self.assertEqual(supervise([], {}, root, uuid4().hex, spawn=spawn), 2)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "EXECUTION_OWNER_ALREADY_ACTIVE"):
                            supervise([], {}, root, uuid4().hex, spawn=spawn)
                finally:
                    lease.release()
            spawn.assert_not_called()

    def test_stop_arriving_between_receipt_read_and_exit_check_wins(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            def spawn(command, **kwargs):
                identity = command[-1]
                record_startup(root, identity, {"status": "READY", "pid": 123})
                class Child:
                    def poll(self):
                        record_startup(root, identity, {"status": "STOPPING", "reason": "OPERATOR_STOP", "desired": "OFFLINE"})
                        return 73
                return Child()
            called = Mock(side_effect=spawn)
            self.assertEqual(supervise([], {}, root, uuid4().hex, spawn=called), 0)
            self.assertEqual(called.call_count, 1)

    def test_launch_stop_in_backoff_persists_offline_without_native_pipe(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            def spawn(command, **kwargs):
                record_startup(root, command[-1], {"status": "READY", "pid": 123})
                return Mock(poll=Mock(return_value=73))
            called = Mock(side_effect=spawn)
            results = []
            thread = Thread(target=lambda: results.append(supervise([], {}, root, uuid4().hex,
                spawn=called, retry_base=2, retry_cap=2)), daemon=True)
            thread.start()
            path = root / "supervisor-status.json"
            eventually(lambda: (optional_receipt(path) or {}).get("status") == "RECOVERING")
            response = request_supervisor_stop(root, timeout=2)
            self.assertTrue(response["acknowledged"])
            self.assertEqual(response["desired"], "OFFLINE")
            thread.join(3)
            self.assertEqual(results, [0])
            self.assertEqual(called.call_count, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "STOPPED")

    def test_stale_supervisor_receipt_does_not_acknowledge_stop(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "supervisor-status.json").write_text(json.dumps({"startup_id": uuid4().hex, "status": "READY"}), encoding="utf-8")
            result = request_supervisor_stop(root, timeout=0)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertFalse(result["acknowledged"])
            # An exclusive fixture reader proves persistent sharing contention is
            # bounded and reported, never converted to READY or stale content.
            import ctypes
            from ctypes import wintypes as W
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
            kernel.CreateFileW.restype = W.HANDLE
            kernel.CloseHandle.argtypes = [W.HANDLE]
            target = root / "supervisor-status.json"
            handle = kernel.CreateFileW(os.path.abspath(target), 0x80000000, 0, None, 3, 0, None)
            self.assertNotEqual(handle, W.HANDLE(-1).value)
            started = time.monotonic()
            try:
                with self.assertRaises(PermissionError) as failure:
                    read_receipt(target)
                self.assertEqual(failure.exception.winerror, 32)
                self.assertLess(time.monotonic() - started, 1.5)
            finally:
                kernel.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
