"""Run outside ContractTest's mutex. No real credentials or broker operations."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from queue import Queue
from threading import Thread


ROOT = Path(__file__).resolve().parents[2]
PS = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
SCRIPT = ROOT / 'scripts/test-kgi-official-simulator.ps1'


def main():
    # Deliberately invented sentinels; inherit only operating-system variables.
    base = {key: value for key, value in os.environ.items()
            if key.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP'}}
    checks = []
    for case, names in (
        ('ordinary_credentials_are_not_substituted', ('KGI_SUPERPY_PERSON_ID', 'KGI_SUPERPY_PASSWORD')),
        ('sim_presence_cannot_unlock', ('KGI_SIM_PERSON_ID', 'KGI_SIM_PASSWORD', 'KGI_SIM_ACCOUNT')),
    ):
        sentinel = 'INVENTED_FIXTURE_VALUE_NEVER_LOG'
        env = base | dict.fromkeys(names, sentinel)
        child = subprocess.run([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                str(SCRIPT), '-Mode', 'Probe'], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=20)
        assert sentinel not in child.stdout + child.stderr
        result = json.loads(child.stdout)
        assert child.returncode == 2 and result['status'] == 'BLOCKED'
        assert result['broker_calls'] == 0 and result['orders_sent'] == 0
        assert not any(result['dedicated_secret_presence'].values())
        assert result['credential_owner'] == 'app.config.Settings'
        assert result['credential_values_read'] is False
        assert 'SIM_ENTITLEMENT_UNVERIFIED' in result['probe']['reasonCodes']
        checks.append(case)
    script = r"""
$m = [System.Threading.Mutex]::new($false, 'Local\OMI_KGI_OFFICIAL_SIM_QUALIFICATION_V1')
$owned = $m.WaitOne(0)
try {
  if (-not $owned) { throw 'TEST_MUTEX_UNAVAILABLE' }
  [Console]::Out.WriteLine('READY')
  [Console]::Out.Flush()
  [Console]::In.ReadLine() | Out-Null
} finally { if ($owned) { $m.ReleaseMutex() }; $m.Dispose() }
"""
    with TemporaryDirectory(prefix='ps-mutex-', dir=ROOT / '.tmp/kgi-official-simulator') as temp:
        helper = Path(temp) / 'hold.ps1'
        helper.write_text(script, encoding='utf-8')
        holder = subprocess.Popen([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper)],
            cwd=ROOT, env=base, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = Queue()
            Thread(target=lambda: ready.put(holder.stdout.readline()), daemon=True).start()
            assert ready.get(timeout=5).strip() == 'READY'
            child = subprocess.run([str(PS), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                    str(SCRIPT), '-Mode', 'Preflight'], cwd=ROOT, env=base,
                                   capture_output=True, text=True, timeout=20)
        finally:
            try:
                holder.communicate(input='stop\n', timeout=5)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=5)
    assert child.stdout.strip(), child.stderr  # Scrubbed environment; no credentials in this case.
    result = json.loads(child.stdout)
    assert result['reasonCodes'] == ['DEDICATED_WORKER_ALREADY_OWNED']
    assert result['broker_calls'] == 0
    checks.append('cross_process_mutex_denial')
    print(json.dumps({'status': 'PASS', 'origin': 'LOCAL_MOCK', 'checks': checks,
                      'real_credentials_used': False, 'broker_calls': 0, 'orders_sent': 0}))


if __name__ == '__main__':
    main()
