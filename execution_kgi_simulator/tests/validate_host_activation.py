"""No-secret policy/lifecycle tests; OS denials are not native acceptance."""

import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, patch

from execution_kgi_simulator.native import host_policy as policy
from execution_kgi_simulator.native import parent, readiness, windows_host as host

ROOT = Path(__file__).resolve().parents[2]


class PolicyTests(unittest.TestCase):
    def test_exact_default_deny_for_both_families_and_directions(self):
        plan = policy.DenyAllPlan()
        policy.validate_deny_all(plan)
        self.assertEqual({f.layer for f in plan.filters}, {
            'FWPM_LAYER_ALE_AUTH_CONNECT_V4', 'FWPM_LAYER_ALE_AUTH_CONNECT_V6',
            'FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4', 'FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V6'})
        self.assertTrue(all(f.action == 'BLOCK' and f.protocols == 'ALL' for f in plan.filters))

    def test_bool_json_and_subclass_not_policy_authority(self):
        class Fake(policy.DenyAllPlan):
            pass
        for value in (True, {}, {'evidence': 'OS_VERIFIED'}, Fake(), 'signed'):
            with self.subTest(value=type(value)), self.assertRaises(policy.PolicyRejected):
                policy.validate_deny_all(value)

    def test_permit_endpoint_and_family_omission_rejected(self):
        plan = policy.DenyAllPlan()
        for bad in (replace(plan, permits=('127.0.0.1:443',)),
                    replace(plan, filters=plan.filters[:1]),
                    replace(plan, filters=(replace(plan.filters[0], action='PERMIT'),) + plan.filters[1:]),
                    replace(plan, filters=(replace(plan.filters[0], protocols='TCP'),) + plan.filters[1:]),
                    replace(plan, filters=(replace(plan.filters[0], destinations='TEST'),) + plan.filters[1:])):
            with self.assertRaises(policy.PolicyRejected): policy.validate_deny_all(bad)

    def test_proxy_dns_redirect_descendant_exceptions_rejected(self):
        for key in ('dns', 'proxy_redirect_fallback', 'descendants', 'evidence',
                    'subject', 'lifetime', 'global_policy'):
            with self.subTest(key=key), self.assertRaises(policy.PolicyRejected):
                policy.validate_deny_all(replace(policy.DenyAllPlan(), **{key: 'ALLOW'}))

    def test_nested_equality_hook_never_confers_trust(self):
        class Anything:
            def __eq__(self, _): return True
        with self.assertRaises(policy.PolicyRejected):
            policy.validate_deny_all(replace(policy.DenyAllPlan(), evidence=Anything()))

    def test_vendor_signatures_unknown_or_forged_always_rejected(self):
        for manifest in (None, True, {'signed': True, 'issuer': 'KGI', 'hosts': ['superpy.kgieworld.com.tw']},
                         {'signature': 'forged', 'endpoint': 'https://evil.invalid'},
                         {'endpoint': 'http://127.0.0.1'}, {'endpoint': '[::ffff:127.0.0.1]'}):
            with self.assertRaises(policy.PolicyRejected): policy.reject_vendor_manifest(manifest)

    def test_static_report_never_os_verified(self):
        result = policy.policy_status()
        self.assertEqual(result['evidence'], 'SOURCE_ONLY')
        self.assertFalse(result['activation_authority'])
        self.assertIn('NOT_INSTALLED', result['kernel_filters'])

    def test_workspace_requires_local_absolute_path(self):
        for value in ('C:/fake', Path('relative'), Path('//server/share'), Path('C:/x/../y'), Path('C:/x:stream')):
            with self.assertRaises((policy.PolicyRejected, OSError)):
                policy.validate_workspace(value)

    def test_log_or_ca_reparse_rejected_without_reading_content(self):
        fake = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=fake), patch.object(Path, 'read_bytes') as read:
            with self.assertRaisesRegex(policy.PolicyRejected, 'REPARSE'):
                policy.validate_workspace(ROOT / 'invented')
            read.assert_not_called()

    def test_empty_layout_static_only_and_no_existing_log_inspection(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('sdk', 'logs', 'ca'): (root / name).mkdir()
            self.assertEqual(policy.validate_workspace(root)['filesystem_isolation'], 'NOT_INSTALLED')
            (root / 'logs' / 'invented.log').write_text('INVENTED ONLY')
            with patch.object(Path, 'read_bytes') as read:
                with self.assertRaisesRegex(policy.PolicyRejected, 'EMPTY'):
                    policy.validate_workspace(root)
                read.assert_not_called()


class OwnershipTests(unittest.TestCase):
    def test_handles_close_once_and_reject_unowned(self):
        api = Mock()
        owned = host._OwnedHandles(api)
        owned.add(123)
        owned.close(123)
        with self.assertRaises(host.HostDenied): owned.close(123)
        api.k.CloseHandle.assert_called_once_with(123)

    def test_invalid_duplicate_handles_rejected(self):
        owned = host._OwnedHandles(Mock())
        for value in (0, None, host.C.c_void_p(-1).value):
            with self.assertRaises(host.HostDenied): owned.add(value)
        owned.add(123)
        with self.assertRaises(host.HostDenied): owned.add(123)

    def test_close_failure_retains_ownership(self):
        api = Mock()
        api.check.side_effect = host.HostDenied('INVENTED_CLOSE_FAILURE')
        owned = host._OwnedHandles(api)
        owned.add(123)
        with self.assertRaises(host.HostDenied): owned.close_all()
        self.assertEqual(owned.items, [123])

    def test_cleanup_continues_after_one_failed_handle(self):
        api = Mock()
        api.check.side_effect = [host.HostDenied('INVENTED_CLOSE_FAILURE'), None]
        owned = host._OwnedHandles(api)
        owned.add(123); owned.add(456)
        with self.assertRaises(host.HostDenied): owned.close_all()
        self.assertEqual(owned.items, [456])
        self.assertEqual(api.k.CloseHandle.call_count, 2)

    def test_no_caller_image_endpoint_proof_or_handle(self):
        for key in ('image', 'command', 'endpoint', 'proof', 'handles', 'env', 'simulation'):
            with self.assertRaises(TypeError): host.suspended_denial_probe(**{key: True})

    def test_os_api_failure_is_redacted_and_not_verified(self):
        with patch.object(host, 'WindowsAPI', side_effect=host.HostDenied('WINDOWS_API_DENIED', 5)):
            result = host.suspended_denial_probe()
        self.assertEqual(result['lifecycle'], 'UNVERIFIED')
        self.assertEqual(result['winerror'], 5)
        self.assertFalse(result['activation_authority'])

    def test_cancel_is_not_swallowed(self):
        with patch.object(host, 'WindowsAPI', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): host.suspended_denial_probe()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows required')
    def test_cancellation_after_real_handle_acquisition_closes_handle(self):
        api, created = host.WindowsAPI(), []
        def acquire(api, owned):
            value = owned.add(api.check(api.k.CreateJobObjectW(None, None), 'TEST_JOB'))
            created.append(value)
            return value
        with patch.object(host, 'WindowsAPI', return_value=api), \
                patch.object(host, '_lock_source_path', side_effect=acquire), \
                patch.object(host, '_locked_image_digest', return_value='SOURCE_TEST_ONLY'), \
                patch.object(api.a, 'OpenProcessToken', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): host.suspended_denial_probe()
        self.assertEqual(len(created), 1)
        flags = host.W.DWORD()
        self.assertFalse(api.k.GetHandleInformation(created[0], host.C.byref(flags)))
        self.assertEqual(host.C.get_last_error(), 6)

    def test_locked_image_wrong_path_and_empty_rejected(self):
        api = Mock()
        def path_query(handle, buffer, size, flags):
            buffer.value = 'C:/wrong.exe'
            return len(buffer.value)
        api.k.GetFinalPathNameByHandleW.side_effect = path_query
        with self.assertRaisesRegex(host.HostDenied, 'PATH_MISMATCH'):
            host._locked_image_digest(api, 123)
        def correct_path(handle, buffer, size, flags):
            buffer.value = '\\\\?\\' + str(host.IMAGE)
            return len(buffer.value)
        api.k.GetFinalPathNameByHandleW.side_effect = correct_path
        # Zero initialized count = empty file; no credentials or disk reads.
        with self.assertRaisesRegex(host.HostDenied, 'EMPTY'):
            host._locked_image_digest(api, 123)

    def test_locked_image_oversize_and_read_failure_rejected(self):
        api = Mock()
        def correct_path(handle, buffer, size, flags):
            buffer.value = '\\\\?\\' + str(host.IMAGE)
            return len(buffer.value)
        api.k.GetFinalPathNameByHandleW.side_effect = correct_path
        def oversized(handle, buffer, size, count, overlapped):
            host.C.cast(count, host.C.POINTER(host.W.DWORD))[0] = 64 * 1024 * 1024 + 1
            return True
        api.k.ReadFile.side_effect = oversized
        with self.assertRaisesRegex(host.HostDenied, 'SIZE'):
            host._locked_image_digest(api, 123)
        api.check.side_effect = host.HostDenied('LOCKED_IMAGE_READ', 5)
        with self.assertRaisesRegex(host.HostDenied, 'READ'):
            host._locked_image_digest(api, 123)

    def test_reparse_directory_handle_never_reaches_image(self):
        api = Mock()
        api.k.CreateFileW.return_value = 123
        def reparse(handle, pointer):
            host.C.cast(pointer, host.C.POINTER(host.FILE_INFORMATION))[0].attributes = 0x410
            return True
        api.k.GetFileInformationByHandle.side_effect = reparse
        owned = host._OwnedHandles(api)
        with self.assertRaisesRegex(host.HostDenied, 'REPARSE'):
            host._lock_source_path(api, owned)
        self.assertEqual(owned.items, [123])
        api.k.CreateFileW.assert_called_once()
        owned.close_all()

    def test_job_flags_no_breakaway_one_child(self):
        self.assertTrue(host.JOB_FLAGS & 0x2000)
        self.assertTrue(host.JOB_FLAGS & 8)
        self.assertFalse(host.JOB_FLAGS & (0x800 | 0x1000))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows required')
    def test_real_windows_job_handle_owner(self):
        api = host.WindowsAPI()
        owned = host._OwnedHandles(api)
        try:
            value = owned.add(api.check(api.k.CreateJobObjectW(None, None), 'TEST_JOB_CREATE'))
            flags = host.W.DWORD()
            api.check(api.k.GetHandleInformation(value, host.C.byref(flags)), 'TEST_JOB_QUERY')
            self.assertFalse(flags.value & 1)
        finally:
            owned.close_all()
        self.assertEqual(owned.items, [])


class AdmissionTests(unittest.TestCase):
    def test_report_mutation_never_unlocks_login(self):
        with patch.object(readiness, 'readiness', return_value={'gates': {'G1': 'PASS'}}), \
                patch.object(policy, 'policy_status', return_value={'evidence': 'OS_VERIFIED'}):
            with self.assertRaises(readiness.ActivationBlocked): parent.run_login_only()

    def test_settings_never_imported_by_parent(self):
        touched = []
        fake = types.ModuleType('app.config')
        fake.__getattr__ = lambda name: touched.append(name)
        with patch.dict(sys.modules, {'app.config': fake}):
            with self.assertRaises(readiness.ActivationBlocked): parent.run_login_only()
        self.assertEqual(touched, [])

    def test_gate_change_alone_still_cannot_create_secret_channel(self):
        with patch.object(readiness, 'require_verified_host'):
            with self.assertRaisesRegex(RuntimeError, 'ACTIVE_PRIVATE_CHANNEL'):
                parent.run_login_only()

    def test_parent_cold_context_rejects_session_reuse(self):
        with patch.dict(sys.modules, {'app': types.ModuleType('app')}):
            with self.assertRaisesRegex(RuntimeError, 'COLD_BACKEND_CONTEXT'):
                parent._backend_context()

    def test_no_resume_or_secret_source_in_host(self):
        source = (ROOT / 'execution_kgi_simulator/native/windows_host.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        # G1-A retains its exact no-resume contract; the new G1-B/C resume site
        # is separately guarded and only targets the pinned native canary.
        tree = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'suspended_denial_probe')
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {'ResumeThread', 'NtResumeProcess', 'environ', 'getenv', 'login'})
        self.assertIn('0x2000D', source)  # Atomic Job assignment, not launch/assign race.
        self.assertIn('0x20002', source)  # Exact handle allowlist.
        self.assertIn("C.create_unicode_buffer('\\0\\0')", source)

    def test_hostile_cli_and_env_never_unlock_parent(self):
        for arguments in (['login-only'], ['preflight'], ['--proof=INVENTED_SECRET']):
            child = subprocess.run([sys.executable, '-I', '-S', '-B',
                str(ROOT / 'execution_kgi_simulator/native/parent.py'), *arguments],
                capture_output=True, text=True, timeout=10,
                env={'NATIVE_HOST_VERIFIED': 'true', 'KGI_SUPERPY_ALLOW_INSECURE': 'true',
                     'HTTPS_PROXY': 'http://evil.invalid', 'PYTHONPATH': 'INVENTED_SECRET'})
            self.assertEqual(child.returncode, 2, child.stderr)
            self.assertNotIn('INVENTED_SECRET', child.stdout + child.stderr)
            self.assertEqual(json.loads(child.stdout)['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
