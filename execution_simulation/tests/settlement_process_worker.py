"""Test child only: actual process death inside/after a settlement transaction."""

import os
import sys

from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication
from execution_simulation.codec import loads
from execution_simulation.storage import SandboxTicket, connection, reopen_sandbox
from .test_settlement import SettlementTests


def main():
    directory, token, preview_id, action = sys.argv[1:]
    with reopen_sandbox(SandboxTicket(directory, token)) as box:
        case = SettlementTests()
        case.box, case.app = box, SimulationApplication(box)
        with connection(box, readonly=True) as db:
            p = loads(db.execute('SELECT payload FROM previews WHERE id=?', (preview_id,)).fetchone()[0])
        if action == 'verify':
            assert case.app.verify().value['verified']
            return
        def hard_crash(actual, boundary):
            if actual == boundary:
                os._exit(73)
        case.app._crash = hard_crash
        case.settle(p, crash_at=action, now=NOW)
        raise AssertionError('Crash boundary not reached')


if __name__ == '__main__':
    main()
