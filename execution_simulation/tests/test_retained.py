import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from execution.contracts import ExecutionRejected, State
from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import retained_mock_sandbox, reopen_sandbox, SandboxTicket, connection


ROOT = Path(__file__).resolve().parents[2]


class RetainedLedgerTests(unittest.TestCase):
    def cleanup_fixture(self, directory):
        path = Path(directory)
        # Delete only this test's factory-created, resolved private directory.
        self.assertEqual(path.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(path.name.startswith('omi-synthetic-m2a-'))
        self.assertEqual(path.resolve(), path)
        shutil.rmtree(path)

    def child(self, request):
        return subprocess.run([sys.executable, '-B', '-S', '-m',
                               'execution_simulation.tests.retained_process_worker'],
            input=json.dumps(request | {'temp_root': tempfile.gettempdir()}), text=True,
            capture_output=True, cwd=ROOT, timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_exit_retains_same_ledger_read_reopen_never_dispatches(self):
        with retained_mock_sandbox() as box:
            self.addCleanup(self.cleanup_fixture, box.directory)
            ticket = box.ticket()
            app = SimulationApplication(box)
            draft, evidence = fixture()
            p = app.preview(draft, evidence, now=NOW).value
            app.confirm(confirmation(p), now=NOW)
            before = box.database.read_bytes()
        self.assertNotIn(ticket.token, repr(ticket))
        with reopen_sandbox(ticket) as reopened:
            app = SimulationApplication(reopened)
            self.assertIs(app.status(p.preview_id).value['order'].state, State.SIMULATED_PENDING)
            self.assertEqual(before, reopened.database.read_bytes())
            with connection(reopened, readonly=True) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM mock_effects').fetchone()[0], 0)

    def test_creator_process_dies_replay_fence_never_reclaims(self):
        child = self.child({'action': 'create_crash'})
        self.assertEqual(child.returncode, 73, child.stderr)
        issued = json.loads(child.stdout)
        self.addCleanup(self.cleanup_fixture, issued['directory'])
        ticket = SandboxTicket(issued['directory'], issued['token'])
        child = self.child(issued | {'action': 'fence'})
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout), {'verified': True, 'state': 'UNKNOWN'})
        with reopen_sandbox(ticket) as box:
            app = SimulationApplication(box)
            claim = app.rehearsal_claim(issued['preview_id'], kind='SEND', generation='new-worker',
                digest=issued['digest'], request_id='send', now=NOW).value
            self.assertIsNone(claim)
            self.assertIs(app.status(issued['preview_id']).value['order'].state, State.UNKNOWN)

    def test_two_process_confirmation_shares_one_reservation_and_outbox(self):
        with retained_mock_sandbox() as box:
            self.addCleanup(self.cleanup_fixture, box.directory)
            app = SimulationApplication(box)
            draft, evidence = fixture()
            p = app.preview(draft, evidence, now=NOW).value
            ticket = box.ticket()
        request = dict(action='confirm', directory=ticket.directory, token=ticket.token,
                       preview_id=p.preview_id, temp_root=tempfile.gettempdir())
        children = [subprocess.Popen([sys.executable, '-B', '-S', '-m',
                    'execution_simulation.tests.retained_process_worker'], cwd=ROOT,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) for _ in range(2)]
        try:
            for child in children:
                child.stdin.write(json.dumps(request))
                child.stdin.close()
                child.stdin = None
            for child in children:
                stdout, stderr = child.communicate(timeout=20)
                self.assertEqual(child.returncode, 0, stderr)
                self.assertTrue(json.loads(stdout)['verified'])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        with reopen_sandbox(ticket) as box, connection(box, readonly=True) as db:
            self.assertEqual([db.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                for t in ('confirmations', 'reservations', 'outbox')], [1, 1, 1])

    def test_forged_ticket_and_wrong_temp_root_fail_closed(self):
        with retained_mock_sandbox() as box:
            self.addCleanup(self.cleanup_fixture, box.directory)
            ticket = box.ticket()
        with self.assertRaises(ExecutionRejected), reopen_sandbox(SandboxTicket(ticket.directory, '0' * 64)):
            pass
        with patch('execution_simulation.storage.gettempdir', return_value=str(ROOT)), \
                self.assertRaises(ExecutionRejected), reopen_sandbox(ticket):
            pass

    def test_old_windows_python_denied_before_creating_retained_directory(self):
        with patch('execution_simulation.storage.sys.platform', 'win32'), \
                patch('execution_simulation.storage.sys.version_info', (3, 12)), \
                patch('execution_simulation.storage.mkdtemp', side_effect=AssertionError('NO WRITE')):
            with self.assertRaises(ExecutionRejected), retained_mock_sandbox():
                pass
