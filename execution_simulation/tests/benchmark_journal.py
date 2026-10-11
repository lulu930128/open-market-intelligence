"""Bounded, opt-in synthetic journal measurement; no provider or production DB.

Run: python -B -m execution_simulation.tests.benchmark_journal
"""

from dataclasses import replace
from decimal import Decimal
import json
from time import perf_counter

from execution.tests.expanded_fixtures import expanded_fixture
from execution.tests.fixtures import NOW, confirmation
from execution.contracts import Funding
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.storage import connection


def run():
    results = []
    for count in (10, 30, 60):
        with temporary_sandbox() as box:
            app = SimulationApplication(box)
            draft, evidence = expanded_fixture(funding=Funding.MARGIN)
            evidence = replace(evidence, account=replace(evidence.account, available_cash=Decimal('10000000'),
                credit=replace(evidence.account.credit, available_credit=Decimal('10000000'))))
            start = perf_counter()
            for index in range(count):
                preview = app.preview(replace(draft, client_request_id='benchmark-' + str(index)), evidence, now=NOW).value
                app.confirm(confirmation(preview), now=NOW)
            build = perf_counter() - start
            start = perf_counter()
            app.status(preview.preview_id)
            status = perf_counter() - start
            start = perf_counter()
            assert app.verify().value['verified']
            verify = perf_counter() - start
            with connection(box, readonly=True) as db:
                rows = db.execute('SELECT count(*) FROM audit').fetchone()[0]
            row = dict(orders=count, audit_rows=rows, bytes=box.database.stat().st_size,
                       create_confirm_seconds=round(build, 4), status_seconds=round(status, 4),
                       verify_seconds=round(verify, 4), simulated=True, broker_connected=False, test_only=True)
            results.append(row)
            print(json.dumps(row), flush=True)
    return results


if __name__ == '__main__':
    run()
