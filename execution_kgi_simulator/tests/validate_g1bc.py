"""Negative source/ABI contracts; these tests never confer OS isolation proof."""
import ast
import ctypes as C
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from execution_kgi_simulator.native import host_policy as policy, windows_host as host, readiness

ROOT = Path(__file__).resolve().parents[2]


def pe_fixture(name=b'KERNEL32.dll', delay=False):
    data = bytearray(1024)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<HH', data, 68, 0x8664, 1)
    struct.pack_into('<H', data, 84, 240)
    struct.pack_into('<H', data, 88, 0x20b)
    struct.pack_into('<I', data, 196, 16)
    struct.pack_into('<II', data, 208, 4096, 40)
    if delay: struct.pack_into('<II', data, 304, 4200, 32)
    struct.pack_into('<III', data, 340, 4096, 512, 512)
    struct.pack_into('<I', data, 524, 4160)
    data[576:576 + len(name)] = name
    return bytes(data)


class DependencyTests(unittest.TestCase):
    def test_pe_import_table_without_loading(self):
        self.assertEqual(policy.pe_imports(pe_fixture()), ('kernel32.dll',))

    def test_malformed_headers_rejected(self):
        for value in (b'', b'MZ', b'MZ' + b'\xff' * 100, pe_fixture()[:530]):
            with self.subTest(length=len(value)), self.assertRaises(policy.PolicyRejected):
                policy.pe_imports(value)

    def test_delay_imports_fail_closed(self):
        with self.assertRaisesRegex(policy.PolicyRejected, 'DELAY'):
            policy.pe_imports(pe_fixture(delay=True))

    def test_unsafe_dependency_paths_and_streams_rejected(self):
        for name in (b'../evil.dll', b'C:\\evil.dll', b'\\\\server\\x.dll', b'evil:ads.dll', b'evil\xff.dll'):
            with self.subTest(name=name), self.assertRaises(policy.PolicyRejected):
                policy.pe_imports(pe_fixture(name))

    def test_canary_source_and_binary_pins(self):
        self.assertEqual(sha256((ROOT / 'execution_kgi_simulator/native/sandbox_probe.c').read_bytes()).hexdigest(), policy.CANARY_SOURCE_SHA256)
        binary = ROOT / '.tmp/kgi-g1bc-build/sandbox_probe.exe'
        if binary.exists():
            data = binary.read_bytes()
            self.assertEqual(sha256(data).hexdigest(), policy.CANARY_IMAGE_SHA256)
            self.assertEqual(frozenset(policy.pe_imports(data)), policy.CANARY_IMPORTS)

    def test_source_drift_never_copies_file(self):
        workspace = Mock()
        with patch.object(host, '_lock_path'), patch.object(host, '_locked_bytes', return_value=b'INVENTED'):
            with self.assertRaisesRegex(host.HostDenied, 'SOURCE_SHA256_DRIFT'):
                host._stage_reviewed_sdk(Mock(), Mock(), workspace)
        self.assertTrue(all(len(call.args) < 3 for call in workspace.create.call_args_list))

    def test_copy_drift_rejected(self):
        workspace = Mock()
        data = b'INVENTED_SOURCE'
        with patch.object(readiness, 'REVIEWED_SHA256', (('main.py', sha256(data).hexdigest()),)), \
                patch.object(host, '_lock_path'), patch.object(host, '_locked_bytes', side_effect=[data, b'WRONG_COPY']):
            with self.assertRaisesRegex(host.HostDenied, 'COPY_SHA256_DRIFT'):
                host._stage_reviewed_sdk(Mock(), Mock(), workspace)

    def test_partial_copy_never_dependency_closure(self):
        workspace = Mock()
        data = b'INVENTED_SOURCE'
        with patch.object(readiness, 'REVIEWED_SHA256', (('main.py', sha256(data).hexdigest()),)), \
                patch.object(host, '_lock_path'), patch.object(host, '_locked_bytes', return_value=data):
            result = host._stage_reviewed_sdk(Mock(), Mock(), workspace)
        self.assertEqual(result['status'], 'SOURCE_COPY_PASS')
        self.assertEqual(result['sdk_execution'], 'REJECTED')
        self.assertIn('REJECTED', result['dependency_closure'])


class ReceiptTests(unittest.TestCase):
    def payload(self):
        return dict(schema='omi.kgi-synthetic-child.v1', pid=123,
                    network_errors=[10013] * 12, file_errors=[5, 5, 5, 5, 0, 0, 5, 0])

    def test_strict_denial_with_inside_controls(self):
        result = policy.classify_canary(self.payload(), 123, 0)
        self.assertEqual(result['network'], 'OS_OBSERVED_SYNTHETIC_DENIAL')
        self.assertEqual(result['filesystem'], 'OS_OBSERVED_SYNTHETIC_DENIAL')
        with self.assertRaises(readiness.ActivationBlocked): readiness.require_verified_host()

    def test_refusal_timeout_unreachable_and_success_not_denial(self):
        for code in (0, 10061, 10060, 10051, 10047, 10035):
            value = self.payload(); value['network_errors'][0] = code
            self.assertEqual(policy.classify_canary(value, 123, 3)['network'], 'UNVERIFIED')

    def test_missing_wrong_pid_bool_extra_and_exit_rejected(self):
        values = [None, {}, True, dict(self.payload(), pid=True), dict(self.payload(), pid=124), dict(self.payload(), proof=True)]
        for value in values:
            self.assertEqual(policy.classify_canary(value, 123, 0)['network'], 'UNVERIFIED')
        self.assertEqual(policy.classify_canary(self.payload(), 123, 97)['network'], 'UNVERIFIED')

    def test_each_missing_network_case_rejected(self):
        for i in range(12):
            value = self.payload(); del value['network_errors'][i]
            self.assertEqual(policy.classify_canary(value, 123, 0)['network'], 'UNVERIFIED')

    def test_missing_files_and_failed_controls_not_pass(self):
        for i in range(8):
            value = self.payload(); value['file_errors'][i] = 32
            self.assertEqual(policy.classify_canary(value, 123, 3)['filesystem'], 'UNVERIFIED')


class OwnershipTests(unittest.TestCase):
    def test_profile_absent_never_creates_child_or_workspace(self):
        api = Mock()
        with patch.object(host, 'SandboxAPI', return_value=api), patch.object(host, '_SandboxWorkspace') as workspace:
            result = host.sandbox_probe()
        self.assertEqual(result['reasonCodes'], ['APPROVED_PREEXISTING_PROFILE_NOT_ENROLLED'])
        api.a.OpenProcessToken.assert_not_called()
        api.a.CreateProcessAsUserW.assert_not_called()
        api.k.ResumeThread.assert_not_called()
        workspace.assert_not_called()

    def test_no_cli_profile_or_image_or_endpoint_ingress(self):
        for key in ('profile', 'proof', 'command', 'image', 'endpoint', 'pid', 'handles'):
            with self.assertRaises(TypeError): host.sandbox_probe(**{key: True})

    def test_stage_mode_exact_bool(self):
        for value in (1, 'true', None, {}):
            with self.assertRaises(host.HostDenied): host.sandbox_probe(stage_only=value)

    def test_capability_failure_not_os_pass(self):
        with patch.object(host, 'SandboxAPI', side_effect=host.HostDenied('API_UNAVAILABLE', 127)):
            result = host.sandbox_capabilities()
        self.assertEqual(result['network'], 'UNVERIFIED')
        self.assertEqual(result['winerror'], 127)

    def test_non_appcontainer_token_rejected(self):
        values = [C.create_string_buffer(b'\0' * 4), C.create_string_buffer(C.sizeof(C.c_void_p)), C.create_string_buffer(b'\0' * 4)]
        with patch.object(host, '_verify_token'), patch.object(host, '_token_buffer', side_effect=values):
            with self.assertRaisesRegex(host.HostDenied, 'NOT_APPCONTAINER'):
                host._verify_appcontainer(Mock(), 123, 456)

    def test_wrong_sid_rejected(self):
        api = Mock(); api.a.EqualSid.return_value = False
        values = [C.create_string_buffer(b'\1\0\0\0'), C.create_string_buffer(C.sizeof(C.c_void_p)), C.create_string_buffer(b'\0' * 4)]
        with patch.object(host, '_verify_token'), patch.object(host, '_token_buffer', side_effect=values):
            with self.assertRaisesRegex(host.HostDenied, 'SID_MISMATCH'):
                host._verify_appcontainer(api, 123, 456)

    def test_any_capability_rejected(self):
        values = [C.create_string_buffer(b'\1\0\0\0'), C.create_string_buffer(C.sizeof(C.c_void_p)), C.create_string_buffer(b'\1\0\0\0')]
        with patch.object(host, '_verify_token'), patch.object(host, '_token_buffer', side_effect=values):
            with self.assertRaisesRegex(host.HostDenied, 'CAPABILITIES_NOT_EMPTY'):
                host._verify_appcontainer(Mock(), 123, 456)

    def test_ads_stream_rejected_and_enumeration_closed(self):
        api = Mock(); api.k.FindFirstStreamW.return_value = 123
        def first(path, kind, pointer, flags):
            C.cast(pointer, C.POINTER(host.STREAM_DATA))[0].name = ':secret:$DATA'
            return 123
        api.k.FindFirstStreamW.side_effect = first
        with self.assertRaisesRegex(host.HostDenied, 'ALTERNATE_DATA_STREAM'):
            host._no_streams(api, ROOT / 'synthetic')
        api.k.FindClose.assert_called_once_with(123)

    def test_unc_ads_dotdot_relative_rejected_before_io(self):
        for value in (Path('relative'), Path('//server/share'), Path('C:/x:ads'), Path('C:/x/../y'), Path('C:/x.')):
            with self.assertRaises(policy.PolicyRejected): policy.local_path(value)

    def test_source_hardlink_and_reparse_rejected_before_read(self):
        path = ROOT / 'invented-sdk.dll'
        for attributes, links in ((0, 2), (0x400, 1), (0x10, 1)):
            api, owned = Mock(), Mock()
            api.k.CreateFileW.return_value = 123
            counter = [0]
            def info(handle, pointer):
                counter[0] += 1
                data = C.cast(pointer, C.POINTER(host.FILE_INFORMATION))[0]
                data.attributes = 0x10 if counter[0] <= len(path.parents) else attributes
                data.links = links
                return True
            api.k.GetFileInformationByHandle.side_effect = info
            with self.assertRaisesRegex(host.HostDenied, 'REPARSE_HARDLINK'):
                host._lock_path(api, owned, path)
            api.k.ReadFile.assert_not_called()

    def test_unapproved_source_records_never_query_os(self):
        for value in (True, {}, ('unapproved', 'S-1-15-2-1'), ('OMI.KGI.Canary.x', 'S-1-1-0')):
            api = Mock()
            with patch.object(policy, 'APPROVED_APPCONTAINER_PROFILE', value):
                with self.assertRaises(host.HostDenied): host._approved_profile_sid(api)
            api.u.DeriveAppContainerSidFromAppContainerName.assert_not_called()

    def test_canary_unknown_or_unpinned_image_never_creates_process(self):
        api, workspace = Mock(), Mock()
        workspace.root = ROOT / '.tmp/invented'
        with patch.object(host, '_lock_path'), patch.object(host, '_locked_bytes', return_value=pe_fixture(b'evil.dll')):
            with self.assertRaisesRegex(host.HostDenied, 'DEPENDENCY_DRIFT'):
                host._canary_run(api, Mock(), workspace, 1, 2, {})
        api.k.CreateJobObjectW.assert_not_called()
        api.a.CreateProcessAsUserW.assert_not_called()
        api.k.ResumeThread.assert_not_called()

    def test_cleanup_failure_revokes_observation(self):
        # The top-level cleanup must not leave a claimed kernel PASS on errors.
        source = (ROOT / 'execution_kgi_simulator/native/windows_host.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'sandbox_probe')
        self.assertTrue(any(isinstance(n, ast.keyword) and n.arg == 'workspace_cleanup'
                            and isinstance(n.value, ast.Constant) and n.value.value == 'UNVERIFIED_RETAINED_FOR_SCOPED_REVIEW'
                            for n in ast.walk(function)))

    def test_job_close_failure_still_terminates_owned_child(self):
        api, owned, report = Mock(), Mock(), {}
        owned.close.side_effect = host.HostDenied('CLOSE_FAILED')
        api.k.WaitForSingleObject.side_effect = [258, 0]
        with self.assertRaisesRegex(host.HostDenied, 'CLOSE_FAILED'):
            host._stop_canary(api, owned, 123, 456, report)
        api.k.TerminateProcess.assert_called_once_with(456, 2)
        self.assertEqual(report['teardown'], 'NO_LIVE_OWNED_CHILD')

    def test_child_teardown_timeout_never_claims_stopped(self):
        api, owned, report = Mock(), Mock(), {}
        api.k.WaitForSingleObject.return_value = 258
        with self.assertRaisesRegex(host.HostDenied, 'TEARDOWN_UNVERIFIED'):
            host._stop_canary(api, owned, 123, 456, report)
        self.assertNotIn('teardown', report)

    def test_normal_job_stop_does_not_terminate_unrelated_process(self):
        api, owned, report = Mock(), Mock(), {}
        api.k.WaitForSingleObject.return_value = 0
        host._stop_canary(api, owned, 123, 456, report)
        api.k.TerminateProcess.assert_not_called()
        owned.close.assert_called_once_with(123)


class ArchitectureTests(unittest.TestCase):
    def test_single_resume_after_os_identity_job_and_token_checks(self):
        tree = ast.parse((ROOT / 'execution_kgi_simulator/native/windows_host.py').read_text(encoding='utf-8'))
        resumes = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'ResumeThread']
        self.assertEqual(len(resumes), 1)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_canary_run')
        self.assertIn(resumes[0], list(ast.walk(function)))
        calls = {getattr(n.func, 'id', getattr(n.func, 'attr', '')): n.lineno
                 for n in ast.walk(function) if isinstance(n, ast.Call)}
        for name in ('_verify_appcontainer', '_verify_identity', 'IsProcessInJob', 'CreateProcessAsUserW'):
            self.assertLess(calls[name], resumes[0].lineno)

    def test_no_profile_installer_fallback_or_sdk_loader(self):
        source = (ROOT / 'execution_kgi_simulator/native/windows_host.py').read_text(encoding='utf-8')
        calls = {getattr(n.func, 'attr', '') for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {'CreateAppContainerProfile', 'DeleteAppContainerProfile', 'CreateProcessW',
                                 'SetNamedSecurityInfoW', 'FwpmFilterAdd0', 'LoadLibraryW', 'LoadLibraryExW'})
        self.assertIsNone(policy.APPROVED_APPCONTAINER_PROFILE)

    def test_canary_never_discovers_ambient_secret_or_proxy(self):
        source = (ROOT / 'execution_kgi_simulator/native/sandbox_probe.c').read_text(encoding='utf-8')
        for forbidden in ('getenv(', 'GetEnvironmentVariable', 'LoadLibrary', 'CreateProcess', 'WinHttpGetIEProxyConfig', 'kgisuperpy'):
            self.assertNotIn(forbidden, source)

    def test_cli_cannot_unlock_with_environment_or_extra_arguments(self):
        for args in (['sandbox-probe'], ['sandbox-probe', '--approved=true']):
            child = subprocess.run([sys.executable, '-I', '-S', '-B', str(ROOT / 'execution_kgi_simulator/native/parent.py'), *args],
                env={'OMI_APPROVED_PROFILE': 'INVENTED', 'HTTPS_PROXY': 'INVENTED'}, capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 2)
            self.assertNotIn('INVENTED', child.stdout + child.stderr)
            self.assertEqual(json.loads(child.stdout)['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
