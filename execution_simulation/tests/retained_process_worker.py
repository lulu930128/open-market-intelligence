"""Fixture subprocess with abrupt termination; only private stdin tickets."""
import json
import os
from pathlib import Path
import sys
import tempfile

from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import retained_mock_sandbox, reopen_sandbox, SandboxTicket


def main():
    request = json.load(sys.stdin)
    tempfile.tempdir = request['temp_root']
    if request['action'] == 'create_crash':
        with retained_mock_sandbox() as box:
            app = SimulationApplication(box)
            draft, evidence = fixture()
            p = app.preview(draft, evidence, now=NOW).value
            app.confirm(confirmation(p), now=NOW)
            app.set_mock_send_enabled(True, now=NOW, user_confirmed=True)
            app.rehearsal_claim(p.preview_id, kind='SEND', generation='dead-worker',
                                digest=p.challenge.digest, request_id='send', now=NOW)
            ticket = box.ticket()
            # Private pipe only, captured by parent, never emitted by test runner.
            print(json.dumps(dict(directory=ticket.directory, token=ticket.token,
                                  preview_id=p.preview_id, digest=p.challenge.digest)), flush=True)
            os._exit(73)
    with reopen_sandbox(SandboxTicket(request['directory'], request['token'])) as box:
        app = SimulationApplication(box)
        p = request['preview_id']
        if request['action'] == 'fence':
            app.rehearsal_fence('dead-worker', now=NOW)
        if request['action'] == 'confirm':
            draft, evidence = fixture()
            preview = app.preview(draft, evidence, now=NOW).value
            app.confirm(confirmation(preview), now=NOW)
        print(json.dumps({'verified': app.verify().value['verified'],
                          'state': app.status(p).value['order'].state.value}))


if __name__ == '__main__':
    main()
