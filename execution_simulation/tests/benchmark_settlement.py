"""Opt-in bounded v2 clone benchmark; stdlib, synthetic fixtures, no network.

Compare create/confirm with benchmark_journal; measure the last order's explicit
dispatch/fill/settle separately. Includes full replay on every operation.
"""

import json
from time import perf_counter

from execution.contracts import Funding
from execution.tests.fixtures import NOW
from execution_simulation.storage import connection
from .test_settlement import SettlementTests


def run():
    for count in (10, 30, 60):
        case = SettlementTests()
        case.setUp()
        try:
            start = perf_counter()
            for _ in range(count):
                p = case.order(funding=Funding.MARGIN, dispatch=False)
            create = perf_counter() - start
            start = perf_counter()
            case.app.dispatch(p.preview_id, now=NOW)
            case.fill(p)
            case.settle(p)
            settlement = perf_counter() - start
            start = perf_counter()
            case.app.snapshot(p.preview_id)
            snapshot = perf_counter() - start
            start = perf_counter()
            assert case.app.verify().value['verified']
            verify = perf_counter() - start
            with connection(case.box, readonly=True) as db:
                rows = db.execute('SELECT count(*) FROM audit').fetchone()[0]
            print(json.dumps(dict(schema=2, orders=count, audit_rows=rows,
                create_confirm_seconds=round(create, 4), last_dispatch_fill_settle_seconds=round(settlement, 4),
                snapshot_seconds=round(snapshot, 4), verify_seconds=round(verify, 4),
                simulated=True, broker_connected=False, test_only=True)), flush=True)
        finally:
            case.doCleanups()


if __name__ == '__main__':
    run()
