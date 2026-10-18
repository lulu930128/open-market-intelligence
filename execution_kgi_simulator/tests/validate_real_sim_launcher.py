"""Run independently: ContractTest already holds the dedicated worker mutex."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from queue import Queue
from threading import Thread

from execution_kgi_simulator.gates import SIM_NAMES

ROOT = Path(__file__).resolve().parents[2]


class LauncherRegression(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows launcher only')
    def test_owned_mutex_denial_is_distinct_from_qualification_report(self):
        ps = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        env = {'SystemRoot': os.environ['SystemRoot']}
        script = r'''
$m = [System.Threading.Mutex]::new($false, 'Local\OMI_KGI_OFFICIAL_SIM_QUALIFICATION_V1')
$owned = $m.WaitOne(0)
try {
    if (-not $owned) { throw 'TEST_MUTEX_UNAVAILABLE' }
    [Console]::Out.WriteLine('READY')
    [Console]::Out.Flush()
    [Console]::In.ReadLine() | Out-Null
} finally { if ($owned) { $m.ReleaseMutex() }; $m.Dispose() }
'''
        holder = subprocess.Popen([ps, '-NoProfile', '-Command', script], cwd=ROOT, env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            ready = Queue()
            Thread(target=lambda: ready.put(holder.stdout.readline()), daemon=True).start()
            self.assertEqual(ready.get(timeout=5).strip(), 'READY')
            child = subprocess.run(
                [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                 str(ROOT / 'scripts/test-kgi-official-simulator.ps1'), '-Mode', 'RealSimProbe',
                 '-TimeoutSeconds', '10'], cwd=ROOT, env=env, capture_output=True,
                text=True, timeout=20)
        finally:
            try:
                holder.communicate(input='stop\n', timeout=5)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.communicate(timeout=5)
        self.assertEqual(child.returncode, 2, child.stderr)
        report = json.loads(child.stdout)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(report['reasonCodes'], ['DEDICATED_WORKER_ALREADY_OWNED'])
        self.assertNotIn('dedicated_secret_presence', report)
        self.assertEqual(report['broker_calls'], 0)
        self.assertEqual(report['orders_sent'], 0)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows launcher only')
    def test_actual_launcher_never_passes_invented_credentials_to_child(self):
        ps = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        for mode, names in (('RealSimProbe', SIM_NAMES),
                            ('RealSimPreflight', ('KGI_SUPERPY_PERSON_ID', 'KGI_SUPERPY_PASSWORD')),
                            ('Preflight', SIM_NAMES)):
            with self.subTest(mode=mode):
                child = subprocess.run(
                    [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                     str(ROOT / 'scripts/test-kgi-official-simulator.ps1'), '-Mode', mode,
                     '-TimeoutSeconds', '10'], cwd=ROOT, capture_output=True, text=True,
                    timeout=20, env={'SystemRoot': os.environ['SystemRoot']} |
                    dict.fromkeys(names, 'INVENTED_SECRET_NEVER_COPY'))
                self.assertEqual(child.returncode, 2, child.stderr)
                self.assertNotIn('INVENTED_SECRET', child.stdout + child.stderr)
                report = json.loads(child.stdout)
                self.assertEqual(report.get('mode'), mode,
                                 'Run this profile after ContractTest has released the mutex: ' + child.stdout)
                self.assertEqual(report['broker_calls'], 0)
                self.assertEqual(report['orders_sent'], 0)
                self.assertFalse(any(report['dedicated_secret_presence'].values()))
                self.assertEqual(report['credential_owner'], 'app.config.Settings')
                self.assertFalse(report['credential_values_read'])


if __name__ == '__main__':
    unittest.main()
