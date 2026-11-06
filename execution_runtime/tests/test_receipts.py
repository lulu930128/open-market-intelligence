"""Windows receipt publication: bounded contention, no ACL or partial-move retry."""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from execution_runtime import service


@unittest.skipUnless(os.name == 'nt', 'Windows ReplaceFile receipt contract')
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / 'receipt.json'
        self.pending = Path(temporary.name) / 'receipt.tmp'
        self.target.write_text('{"state":"old"}', encoding='utf-8')
        self.pending.write_text('{"state":"new"}', encoding='utf-8')

    def test_transient_contention_reuses_intact_files_then_publishes(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.ReplaceFileW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.LPVOID, W.LPVOID]
        kernel.ReplaceFileW.restype = W.BOOL
        errors = [1175, 32]
        def replace(*args):
            if errors:
                self.assertIn('old', self.target.read_text(encoding='utf-8'))
                self.assertIn('new', self.pending.read_text(encoding='utf-8'))
                ctypes.set_last_error(errors.pop(0))
                return 0
            return kernel.ReplaceFileW(*args)
        replace_call = Mock(side_effect=replace)
        with patch('ctypes.WinDLL', return_value=SimpleNamespace(ReplaceFileW=replace_call)):
            service.replace_receipt(self.pending, self.target)
        self.assertEqual(replace_call.call_count, 3)
        self.assertIn('new', self.target.read_text(encoding='utf-8'))
        self.assertFalse(self.pending.exists())

    def test_persistent_contention_is_bounded_and_preserves_both_files(self):
        def fail(*args):
            ctypes.set_last_error(1175)
            return 0
        replace_call = Mock(side_effect=fail)
        with patch('ctypes.WinDLL', return_value=SimpleNamespace(ReplaceFileW=replace_call)), \
             patch.object(service.time, 'monotonic', side_effect=[0.0, 0.0, 0.0, 0.6]), \
             patch.object(service.time, 'sleep') as sleep:
            with self.assertRaises(OSError) as failed:
                service.replace_receipt(self.pending, self.target)
        self.assertEqual(failed.exception.winerror, 1175)
        self.assertEqual(replace_call.call_count, 2)
        sleep.assert_called_once()
        self.assertIn('old', self.target.read_text(encoding='utf-8'))
        self.assertIn('new', self.pending.read_text(encoding='utf-8'))

    def test_access_denied_and_partial_move_failures_are_never_retried(self):
        for code in (5, 1176, 1177):
            with self.subTest(code=code):
                def fail(*args):
                    ctypes.set_last_error(code)
                    return 0
                replace_call = Mock(side_effect=fail)
                with patch('ctypes.WinDLL', return_value=SimpleNamespace(ReplaceFileW=replace_call)), \
                     patch.object(service.time, 'sleep') as sleep:
                    with self.assertRaises(OSError) as failed:
                        service.replace_receipt(self.pending, self.target)
                self.assertEqual(failed.exception.winerror, code)
                replace_call.assert_called_once()
                sleep.assert_not_called()

    def test_first_publication_uses_existing_atomic_rename(self):
        new_target = self.target.with_name('first.json')
        service.replace_receipt(self.pending, new_target)
        self.assertIn('new', new_target.read_text(encoding='utf-8'))
        self.assertFalse(self.pending.exists())


if __name__ == '__main__':
    unittest.main()
