"""Test-only child process: real abrupt exit at an instrumented crash boundary."""

import os
import sys

from execution.tests.fixtures import NOW, confirmation, fixture
from execution_simulation import SimulationApplication
from execution_simulation.storage import SandboxTicket, reopen_sandbox


def main():
    directory, token, action = sys.argv[1:]
    with reopen_sandbox(SandboxTicket(directory, token)) as sandbox:
        app = SimulationApplication(sandbox)
        draft, evidence = fixture()
        p = app.preview(draft, evidence, now=NOW).value
        def hard_crash(actual, boundary):
            if actual == boundary:
                os._exit(73)
        if action in {'before_outbox', 'before_commit', 'after_commit'}:
            app._crash = hard_crash
            app.confirm(confirmation(p), now=NOW, crash_at=action)
            raise AssertionError('Crash boundary not reached')
        app.confirm(confirmation(p), now=NOW)
        if action in {'after_claim', 'after_effect'}:
            app._crash = hard_crash
            app.dispatch(p.preview_id, now=NOW, crash_at=action)
            raise AssertionError('Crash boundary not reached')
        if action == 'recover':
            app.recover(p.preview_id, now=NOW)
            app.dispatch(p.preview_id, now=NOW)
            app.reconcile(p.preview_id, now=NOW, user_confirmed=True)
            assert app.verify().value['verified']
        else:
            raise ValueError('Unknown test action')


if __name__ == '__main__':
    main()
