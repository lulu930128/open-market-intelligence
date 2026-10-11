"""Private factory capability via stdin only; no broker or arbitrary DB path."""
import json
import sys

from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication
from execution_simulation.storage import SandboxTicket, reopen_sandbox
from execution_simulation.mock import Fixture, SimulatedCrash


value = json.loads(sys.stdin.read())
with reopen_sandbox(SandboxTicket(**value['ticket'])) as sandbox:
    app = SimulationApplication(sandbox)
    try:
        app.dispatch(value['preview'], now=NOW, fixture=Fixture.SDK_ACCEPT, crash_at=value.get('crash'))
    except SimulatedCrash:
        sys.exit(17)
    print(json.dumps({'effects': app.status(value['preview']).value['commands'][0]['mock_effects']}))
