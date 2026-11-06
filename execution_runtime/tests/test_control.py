"""Control-client failures must never masquerade as a Native command rejection."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from execution.contracts import ExecutionRejected
from execution_runtime import control


class ControlTests(unittest.TestCase):
    def test_response_timeout_is_transport_uncertainty_after_one_send(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.poll.return_value = False
        with patch.object(control, "Client", return_value=connection), \
             patch.object(control, "authenticate", return_value=123):
            with self.assertRaises(TimeoutError):
                control.request_control({"operation": "command", "request": {"id": "fixture", "argv": ["list"]}},
                                        timeout=0.01)
        connection.send_bytes.assert_called_once()
        connection.recv_bytes.assert_not_called()
        connection.__exit__.assert_called_once()

    def test_cli_local_failures_have_fixed_transport_code_and_no_private_text(self):
        for error, code in (
            (FileNotFoundError("private pipe"), "EXECUTOR_UNAVAILABLE"),
            (TimeoutError("private timeout"), "EXECUTOR_RESPONSE_UNKNOWN"),
            (EOFError("private disconnect"), "EXECUTOR_RESPONSE_UNKNOWN"),
            (ValueError("private response"), "EXECUTOR_RESPONSE_UNKNOWN"),
            (ExecutionRejected("CONTROL_OWNER_MISMATCH"), "EXECUTOR_RESPONSE_UNKNOWN"),
        ):
            with self.subTest(error=type(error).__name__), \
                 patch.object(control, "request_control", side_effect=error) as request:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(control.main(["status"]), 2)
                value = json.loads(output.getvalue())
                self.assertEqual(value, {"ok": False, "code": code, "error_type": type(error).__name__,
                                        "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"})
                self.assertNotIn("private", output.getvalue())
                request.assert_called_once()

    def test_cli_preserves_received_native_rejection(self):
        response = {"ok": False, "error_type": "ExecutionRejected", "code": "EXECUTOR_BUSY",
                    "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}
        with patch.object(control, "request_control", return_value=response):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(control.main(["readback"]), 2)
        self.assertEqual(json.loads(output.getvalue()), response)


if __name__ == "__main__":
    unittest.main()
