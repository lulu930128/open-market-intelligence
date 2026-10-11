"""Owned LOCAL MOCK child. Receives only a factory ticket over private stdin."""

import json
import os
from pathlib import Path
import sys
import tempfile

from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import SandboxTicket, reopen_sandbox
from execution_kgi_simulator.fake import FakeSDK
from execution_kgi_simulator.wire import send_fixture


def main():
    value = json.load(sys.stdin)
    tempfile.tempdir = str(Path(value['directory']).parent)
    with reopen_sandbox(SandboxTicket(value['directory'], value['token'])) as box:
        app = SimulationApplication(box)
        draft, evidence = fixture()
        p = app.preview(draft, evidence, now=NOW).value
        app.confirm(confirmation(p), now=NOW)
        if value['action'] == 'race':
            claim = app.rehearsal_claim(p.preview_id, kind='SEND', generation='child-worker',
                digest=p.challenge.digest, request_id='send', now=NOW).value
            print(json.dumps({'claimed': claim is not None}), flush=True)
        else:
            def hard_crash(actual, boundary):
                if actual == boundary:
                    os._exit(73)
            app._crash = hard_crash
            send_fixture(app, p, FakeSDK(), 'child-worker', now=NOW, crash_at=value['action'])
            raise AssertionError('crash boundary not reached')


if __name__ == '__main__':
    main()
