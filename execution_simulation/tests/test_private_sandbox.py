import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from execution.contracts import ExecutionRejected
from execution_simulation.storage import temporary_sandbox


class PrivateSandboxTests(unittest.TestCase):
    def test_windows_old_python_rejected_before_temp_creation(self):
        with patch('execution_simulation.storage.sys.platform', 'win32'), \
                patch('execution_simulation.storage.sys.version_info', (3, 12)), \
                patch('execution_simulation.storage.TemporaryDirectory', side_effect=AssertionError('NO WRITE')):
            with self.assertRaises(ExecutionRejected) as caught, temporary_sandbox():
                self.fail('Unprotected Windows temp directory admitted')
            self.assertEqual(caught.exception.code, 'PRIVATE_TEMP_ACL_REQUIRED')

    def test_factory_directory_and_files_are_private(self):
        with temporary_sandbox() as box:
            if os.name != 'nt':
                self.assertEqual(box.directory.stat().st_mode & 0o777, 0o700)
                return
            self.assertGreaterEqual(sys.version_info, (3, 13))
            # Read ACL only on this test's factory directory; no ACL changes or elevation.
            path = str(box.directory).replace("'", "''")
            script = """
$ErrorActionPreference = 'Stop'
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed = @($current, 'S-1-3-4', 'S-1-5-18', 'S-1-5-32-544')
$paths = @('PATH_VALUE', (Join-Path 'PATH_VALUE' 'simulation.sqlite3'), (Join-Path 'PATH_VALUE' 'sandbox.token'))
$unexpected = 0
foreach ($path in $paths) {
    $acl = Get-Acl -LiteralPath $path
    if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $current) { $unexpected++ }
    foreach ($ace in $acl.Access) {
        $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($ace.AccessControlType -eq 'Allow' -and $sid -notin $allowed) { $unexpected++ }
    }
}
@{unexpected_allow_aces=$unexpected; checked=$paths.Count} | ConvertTo-Json -Compress
""".replace('PATH_VALUE', path)
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(unexpected_allow_aces=0, checked=3))
