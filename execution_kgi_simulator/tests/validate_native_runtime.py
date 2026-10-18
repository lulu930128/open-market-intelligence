"""Independent offline PowerShell regression; never native/SIM acceptance.

Run separately from ContractTest. Private helper tests use invented observations
and process-local overrides, never a production proof/configuration ingress.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from execution_kgi_simulator.real_sim import qualify
from execution_kgi_simulator.tests.test_real_sim import NOW


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / 'scripts/test-kgi-native-runtime.ps1'
LAUNCHER = ROOT / 'scripts/test-kgi-official-simulator.ps1'
PS = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) /
         'System32/WindowsPowerShell/v1.0/powershell.exe')


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell contracts')
class NativeRuntimeContracts(unittest.TestCase):
    def shell(self, code, payload=None, extra_env=None, timeout=20):
        return subprocess.run(
            [PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
             "$ErrorActionPreference='Stop'; " + code],
            input=json.dumps(payload) if payload is not None else '',
            text=True, capture_output=True, timeout=timeout, cwd=ROOT,
            env={'SystemRoot': os.environ['SystemRoot']} | (extra_env or {}))

    def test_observation_positive_and_negative_contracts(self):
        good = {
            'schema': 'omi.kgi-interpreter-observation.v1', 'implementation': 'cpython',
            'version': [3, 12, 3], 'pointer_bits': 64,
            'executable': r'C:\fixture\.venv-kgi\Scripts\python.exe',
            'base_executable': r'C:\fixture\Python312\python.exe',
            'base_prefix': r'C:\fixture\Python312', 'isolated': 1, 'no_site': 1,
            'no_bytecode': 1, 'ignore_environment': 1, 'site_loaded': False,
            'sdk_loaded': False, 'sys_path': [r'C:\fixture\Python312\python312.zip',
                                            r'C:\fixture\Python312\DLLs',
                                            r'C:\fixture\Python312\Lib']}
        cases = [{'raw': json.dumps(good), 'exit': 0, 'stderr': '', 'accept': True}]
        for key, values in {
            'schema': ['PASS', None], 'implementation': ['pypy'],
            'version': [[3, 13, 3], [3, 12, -1], ['3', 12, 3], [True, 12, 3]],
            'pointer_bits': [32, '64', True], 'executable': [sys.executable, None],
            'base_executable': [r'C:\wrong\python.exe'], 'base_prefix': [r'C:\wrong'],
            'isolated': [False, '1', 0], 'no_site': [0], 'no_bytecode': [0],
            'ignore_environment': [0], 'sdk_loaded': [True, 'false'], 'site_loaded': [True],
            'sys_path': [[], [''], [str(ROOT)], [r'C:\fixture\Python312\Lib\site-packages'],
                         [r'\\server\share'], [r'C:\fixture\Python312\Lib\..\evil']],
            'endpoint_attested': [True], 'status': ['PASS'],
        }.items():
            for value in values:
                changed = good | {key: value}
                cases.append({'raw': json.dumps(changed), 'exit': 0, 'stderr': '', 'accept': False})
        for key in good:
            changed = dict(good)
            del changed[key]
            cases.append({'raw': json.dumps(changed), 'exit': 0, 'stderr': '', 'accept': False})
        for raw in ('{}', 'null', '[]', '{', ' ' * 16385,
                    json.dumps(good)[:-1] + ',"pointer_bits":64}'):
            cases.append({'raw': raw, 'exit': 0, 'stderr': '', 'accept': False})
        cases += [{'raw': json.dumps(good), 'exit': 103, 'stderr': '', 'accept': False},
                  {'raw': json.dumps(good), 'exit': 0, 'stderr': 'INVENTED_SECRET', 'accept': False},
                  {'raw': json.dumps(good | {'version': [3, 12, 10]}), 'exit': 0, 'stderr': '', 'accept': True}]
        code = f'. {quoted(CHECKER)}; ' + r'''
$cases = [Console]::In.ReadToEnd() | ConvertFrom-Json
$config = @{version='3.12.3';home='C:\fixture\Python312';executable='C:\fixture\Python312\python.exe'}
foreach ($case in $cases) {
    $accepted = $false
    try {
        $summary = Read-KgiInterpreterObservation $case.raw $case.exit $case.stderr $config 'C:\fixture\.venv-kgi\Scripts\python.exe'
        if (($summary | ConvertTo-Json -Compress).Contains('C:')) { throw 'PATH_LEAK' }
        if (($summary.version -cne '3.12.3') -ne $summary.patch_drift) { throw 'PATCH_DRIFT_HIDDEN' }
        $accepted = $true
    } catch {}
    if ($accepted -ne $case.accept) { throw 'OBSERVATION_CONTRACT_MISMATCH' }
}
[Console]::WriteLine('OBSERVATION_CONTRACTS_OK')
'''
        child = self.shell(code, cases)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn('OBSERVATION_CONTRACTS_OK', child.stdout)

    def test_environment_is_cleared_without_changing_parent(self):
        code = f'. {quoted(CHECKER)}; ' + r'''
$before = $env:PATH
$info = New-KgiPythonStartInfo 'C:\fixture\python.exe' 'C:\fixture'
if ($info.Environment.Count -ne 2 -or -not $info.Environment.ContainsKey('SystemRoot') -or
    -not $info.Environment.ContainsKey('WINDIR') -or $info.Arguments -cne '-I -S -B -' -or
    $info.UseShellExecute -or -not $info.CreateNoWindow -or $env:PATH -cne $before) { throw 'ENV_FAILURE' }
[Console]::WriteLine('ENV_OK')
'''
        child = self.shell(code, extra_env={
            'PATH': 'INVENTED_POISON_PATH', 'PYTHONHOME': 'INVENTED_SECRET',
            'PYTHONPATH': 'INVENTED_SECRET', 'KGI_SIM_PASSWORD': 'INVENTED_SECRET',
            'KGI_SUPERPY_PASSWORD': 'INVENTED_SECRET', 'TEMP': 'INVENTED_SECRET'})
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'ENV_OK')
        self.assertNotIn('INVENTED', child.stdout + child.stderr)

    def test_actual_probe_uses_no_site_and_ignores_poison_environment(self):
        # Actual available 3.13 stdlib execution verifies isolation, not 3.12 readiness.
        code = f'. {quoted(CHECKER)}; Get-KgiInterpreterProbe'
        source = self.shell(code)
        self.assertEqual(source.returncode, 0, source.stderr)
        child = subprocess.run([sys.executable, '-I', '-S', '-B', '-'],
            input=source.stdout, text=True, capture_output=True, timeout=10,
            env={'SystemRoot': os.environ['SystemRoot'], 'PATH': 'INVENTED_POISON',
                 'PYTHONHOME': 'INVENTED_SECRET', 'PYTHONPATH': 'INVENTED_SECRET',
                 'KGI_SIM_PASSWORD': 'INVENTED_SECRET'})
        self.assertEqual(child.returncode, 0, child.stderr)
        report = json.loads(child.stdout)
        for key in ('isolated', 'no_site', 'no_bytecode', 'ignore_environment'):
            self.assertEqual(report[key], 1)
        self.assertFalse(report['site_loaded'])
        self.assertFalse(report['sdk_loaded'])
        self.assertNotIn('INVENTED', child.stdout + child.stderr)

    def test_config_validation_and_read_only_missing_base(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp/kgi-official-simulator') as tmp:
            root = Path(tmp)
            env = root / '.venv-kgi'
            env.mkdir()
            config = env / 'pyvenv.cfg'
            base = root / 'missing'
            valid = (f'home = {base}\nversion = 3.12.3\n'
                     f'executable = {base / "python.exe"}\ninclude-system-site-packages = false\n')
            for value, reason in ((valid, 'PATH_NOT_FOUND'),
                                  (valid + 'version = 3.12.3\n', 'VENV_CONFIG_INVALID'),
                                  (valid.replace('3.12.3', '3.13.9'), 'VENV_CONFIG_MISMATCH'),
                                  (valid.replace('= false', '= true'), 'VENV_CONFIG_MISMATCH'),
                                  (valid.replace(str(base / 'python.exe'), r'C:\wrong\python.exe'), 'VENV_BASE_MISMATCH'),
                                  (valid.replace(str(base), r'\\server\share'), 'LOCAL_PATH_REQUIRED')):
                with self.subTest(reason=reason):
                    config.write_text(value, encoding='utf-8')
                    before = config.read_bytes()
                    code = (f'. {quoted(CHECKER)}; $r=Invoke-KgiNativeReadiness {quoted(root)} 1; '
                            '$r | ConvertTo-Json -Depth 6 -Compress; exit $r.exit_code')
                    child = self.shell(code)
                    self.assertEqual(child.returncode, 2, child.stderr)
                    report = json.loads(child.stdout)
                    self.assertEqual(report['reasonCodes'], [reason])
                    self.assertEqual(report['exit_code'], child.returncode)
                    self.assertEqual(config.read_bytes(), before)
                    self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob('*')),
                                     ['.venv-kgi', '.venv-kgi/pyvenv.cfg'])

    def test_image_wrong_version_arch_and_invalid_header(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp/kgi-official-simulator') as tmp:
            image = Path(tmp) / 'python.exe'
            # Minimal PE bytes are read as data only, never executed.
            for machine, expected in ((0x14c, 'PYTHON_ARCH_MISMATCH'),
                                      (0x8664, 'PYTHON_VERSION_MISMATCH')):
                data = bytearray(70)
                data[:2] = b'MZ'
                data[60:64] = (64).to_bytes(4, 'little')
                data[64:68] = b'PE\0\0'
                data[68:70] = machine.to_bytes(2, 'little')
                image.write_bytes(data)
                code = (f'. {quoted(CHECKER)}; try {{ Assert-KgiPythonImage {quoted(image)}; exit 1 }} '
                        f'catch {{ if ($_.Exception.Message -cne {quoted(expected)}) {{ throw }} }}; exit 0')
                child = self.shell(code)
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertEqual(image.read_bytes(), data)

    def test_timeout_invalid_output_and_nonzero_exit_are_redacted(self):
        # Process-local test overrides cannot be selected by the production CLI.
        for probe, reason in (("import time; time.sleep(5)", 'INTERPRETER_TIMEOUT'),
                              ("print('INVENTED_SECRET'); raise SystemExit(103)", 'INTERPRETER_EXIT_NONZERO'),
                              ("print('{\"status\":\"PASS\"}')", 'INTERPRETER_RESPONSE_INVALID')):
            with self.subTest(reason=reason):
                code = f'. {quoted(CHECKER)}; ' + f'''
function Read-KgiVenvConfig {{ return @{{version='3.12.3';home={quoted(Path(sys.executable).parent)};executable={quoted(sys.executable)}}} }}
function Assert-KgiPythonImage {{}}
$originalStart = ${{function:New-KgiPythonStartInfo}}
function New-KgiPythonStartInfo {{ param($Python,$WorkingDirectory); & $originalStart {quoted(sys.executable)} {quoted(ROOT)} }}
function Get-KgiInterpreterProbe {{ return {quoted(probe)} }}
$r=Invoke-KgiNativeReadiness {quoted(ROOT)} 1
$r | ConvertTo-Json -Depth 6 -Compress
exit $r.exit_code
'''
                child = self.shell(code)
                self.assertEqual(child.returncode, 2, child.stderr)
                report = json.loads(child.stdout)
                self.assertEqual(report['reasonCodes'], [reason])
                self.assertEqual(report['status'], 'BLOCKED')
                self.assertNotIn('INVENTED_SECRET', child.stdout + child.stderr)

    def test_actual_checker_cli_exit_payload_and_nonoverwrite(self):
        paths = [ROOT / '.venv-kgi/pyvenv.cfg', ROOT / '.venv-kgi/Scripts/python.exe']
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        child = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(CHECKER)],
            cwd=ROOT, env={'SystemRoot': os.environ['SystemRoot'], 'PATH': 'INVENTED_POISON',
                          'KGI_SIM_PASSWORD': 'INVENTED_SECRET'}, text=True, capture_output=True, timeout=20)
        report = json.loads(child.stdout)
        self.assertEqual(report['schema'], 'omi.kgi-native-runtime-readiness.v1')
        self.assertEqual(report['scope'], 'INTERPRETER_BASE_ONLY')
        self.assertEqual(report['exit_code'], child.returncode)
        self.assertIn((report['status'], child.returncode), [('PASS', 0), ('BLOCKED', 2)])
        self.assertEqual(report['real_sim'], 'BLOCKED')
        self.assertEqual(report['real_production'], 'FORBIDDEN')
        for key in ('sdk_imported', 'native_abi_verified', 'endpoint_attested', 'credential_verified'):
            self.assertIs(report[key], False)
        for key in ('login_attempts', 'broker_calls', 'orders_sent'):
            self.assertEqual(report[key], 0)
        self.assertNotIn('INVENTED', child.stdout + child.stderr)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_qualification_response_rejects_false_pass_and_fake_proof(self):
        good = qualify(ROOT, {}, NOW, mode='RealSimProbe')
        cases = [{'report': good, 'exit': 2, 'accept': True}]
        for key, value in (('schema', 'wrong'), ('status', 'PASS'), ('mode', 'Send'),
                           ('sdk_imported', True), ('broker_calls', '0'), ('orders_sent', 1),
                           ('login_attempts', True), ('native_probe_attempts', 1),
                           ('cancel_requests', 1), ('session_reuse', 'ALLOW'),
                           ('runtime_origin', 'REAL_SIM'), ('connector', 'READY'),
                           ('broker_connected', 'false'), ('execution_ingress', 'READY')):
            cases.append({'report': good | {key: value}, 'exit': 2, 'accept': False})
        for exit_code in (0, 1, 103):
            cases.append({'report': good, 'exit': exit_code, 'accept': False})
        for key in ('probe', 'order'):
            changed = copy.deepcopy(good)
            changed[key]['status'] = 'PASS'
            cases.append({'report': changed, 'exit': 2, 'accept': False})
        contract = {'schema': 'omi.kgi-sim.contract.v1', 'mode': 'ContractTest', 'status': 'PASS',
                    'origin': 'LOCAL_MOCK', 'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0,
                    'sdk_imported': False, 'broker_calls': 0, 'orders_sent': 0, 'scheduled_orders': 0,
                    'real_simulator': 'BLOCKED', 'real_production': 'FORBIDDEN'}
        cases += [{'report': contract, 'exit': 0, 'accept': True},
                  {'report': contract | {'status': 'FAIL', 'errors': 1}, 'exit': 1, 'accept': True},
                  {'report': contract, 'exit': 1, 'accept': False},
                  {'report': contract | {'errors': 1}, 'exit': 0, 'accept': False},
                  {'report': contract | {'tests': 0}, 'exit': 0, 'accept': False},
                  {'report': contract | {'skipped': 1}, 'exit': 0, 'accept': False}]
        code = f'. {quoted(LAUNCHER)}; ' + r'''
$cases = [Console]::In.ReadToEnd() | ConvertFrom-Json
foreach ($case in $cases) {
    $accepted=$false
    $mode=if ($case.report.mode -ceq 'ContractTest') {'ContractTest'} else {'RealSimProbe'}
    try { Assert-KgiQualificationResponse $case.report $case.exit $mode; $accepted=$true } catch {}
    if ($accepted -ne $case.accept) { throw 'QUALIFICATION_CONTRACT_MISMATCH' }
}
[Console]::WriteLine('QUALIFICATION_CONTRACTS_OK')
'''
        child = self.shell(code, cases)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn('QUALIFICATION_CONTRACTS_OK', child.stdout)

    def test_actual_launcher_rejects_worker_false_pass_and_normalizes_json(self):
        # Copy only source into a disposable harness. Never replace the repo
        # worker/interpreter. A fake child report is test data, not SIM evidence.
        good = qualify(ROOT, {}, NOW, mode='RealSimProbe')
        raw_good = json.dumps(good)
        cases = [
            (raw_good, 2, True),
            (raw_good, 0, False),
            (json.dumps(good | {'status': 'PASS'}), 0, False),
            (json.dumps(good | {'status': 'PASS'}), 2, False),
            (json.dumps(good | {'schema': 'invented'}), 2, False),
            (json.dumps(good | {'broker_calls': 1}), 2, False),
            ('{"status":"BLOCKED","reasonCodes":["WORKER_FAILED_CLOSED"]}', 2, False),
            (raw_good[:-1] + ',"schema":"omi.kgi-real-sim.qualification.v1"}', 2, False),
            # Last-key parser semantics are safe only after re-serialization.
            ('{"status":"PASS",' + raw_good[1:], 2, True),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp/kgi-official-simulator') as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'execution_kgi_simulator').mkdir()
            launcher = root / 'scripts/test-kgi-official-simulator.ps1'
            source = LAUNCHER.read_text(encoding='utf-8')
            assignment = "$python = Join-Path $repo '.venv\\Scripts\\python.exe'"
            self.assertEqual(source.count(assignment), 1)
            launcher.write_text(source.replace(assignment, '$python = ' + quoted(sys.executable)), encoding='utf-8')
            worker = root / 'execution_kgi_simulator/worker.py'
            for raw, exit_code, qualified in cases:
                worker.write_text(f'print({raw!r})\nraise SystemExit({exit_code})\n', encoding='utf-8')
                child = subprocess.run([PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(launcher), '-Mode', 'RealSimProbe', '-TimeoutSeconds', '5'],
                    cwd=root, env={'SystemRoot': os.environ['SystemRoot']},
                    text=True, capture_output=True, timeout=15)
                self.assertEqual(child.returncode, 2, child.stderr)
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        self.assertNotIn(key, result)
                        result[key] = value
                    return result
                report = json.loads(child.stdout, object_pairs_hook=unique)
                self.assertEqual(report['status'], 'BLOCKED')
                if qualified:
                    self.assertEqual(report['schema'], good['schema'])
                    self.assertEqual(report['mode'], 'RealSimProbe')
                else:
                    self.assertEqual(report['reasonCodes'], ['LAUNCHER_FAILED_CLOSED'])
                    self.assertNotIn('schema', report)


if __name__ == '__main__':
    unittest.main()
