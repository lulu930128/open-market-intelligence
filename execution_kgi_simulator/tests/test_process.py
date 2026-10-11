import json
from pathlib import Path
import subprocess
import sys
import unittest

from execution.contracts import State
from execution.tests.fixtures import NOW, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import temporary_sandbox
from execution_kgi_simulator.fake import FakeSDK
from execution_kgi_simulator.wire import send_fixture


ROOT = Path(__file__).resolve().parents[2]


class ProcessBoundary(unittest.TestCase):
    def worker(self, box, action):
        child = subprocess.Popen([sys.executable, '-B', '-S', '-m',
                                  'execution_kgi_simulator.tests.process_worker'],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ticket = box.ticket()
        child.stdin.write(json.dumps({'directory': ticket.directory, 'token': ticket.token, 'action': action}))
        child.stdin.close()
        child.stdin = None
        return child

    def finish(self, child):
        try:
            return child.communicate(timeout=15)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_actual_process_death_after_claim_and_effect(self):
        for boundary in ('after_claim', 'after_effect'):
            with self.subTest(boundary=boundary), temporary_sandbox() as box:
                app = SimulationApplication(box)
                app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
                child = self.worker(box, boundary)
                self.finish(child)
                self.assertEqual(child.returncode, 73)
                reopened = SimulationApplication(box)
                reopened.rehearsal_fence('child-worker', now=NOW)
                draft, evidence = fixture()
                p = reopened.preview(draft, evidence, now=NOW).value
                sdk = FakeSDK()
                send_fixture(reopened, p, sdk, 'new-worker', now=NOW)
                self.assertEqual(sdk.Order.calls, [])
                self.assertIs(reopened.status(p.preview_id).value['order'].state, State.UNKNOWN)
                self.assertTrue(reopened.verify().value['verified'])

    def test_two_processes_only_one_durable_claim(self):
        with temporary_sandbox() as box:
            app = SimulationApplication(box)
            app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
            children = [self.worker(box, 'race') for _ in range(2)]
            responses = [self.finish(child) for child in children]
            self.assertEqual([c.returncode for c in children], [0, 0], responses)
            self.assertEqual(sum(json.loads(stdout)['claimed'] for stdout, _ in responses), 1)
            self.assertTrue(SimulationApplication(box).verify().value['verified'])
