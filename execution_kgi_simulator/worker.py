"""Bounded no-network worker. Only PowerShell launches it; no OMI/PAOS reuse."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def offline_guard(event, args):
    if (event.startswith('socket.') or event == 'ctypes.dlopen'
            or (event == 'import' and str(args[0]).split('.')[0] == 'kgisuperpy')):
        raise RuntimeError('OFFLINE_IO_BLOCKED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['Preflight', 'ContractTest', 'Probe', 'Send'])
    args = parser.parse_args()
    sys.addaudithook(offline_guard)
    sys.path.insert(0, str(ROOT))
    from execution_kgi_simulator.inspection import inspect_sdk
    from execution_kgi_simulator.gates import preflight
    if args.mode == 'ContractTest':
        temp = ROOT / '.tmp/kgi-official-simulator'
        temp.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(temp)
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'execution_kgi_simulator/tests'),
                                                  top_level_dir=str(ROOT))
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
        print(json.dumps({'schema': 'omi.kgi-sim.contract.v1', 'mode': args.mode,
            'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'origin': 'LOCAL_MOCK',
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'sdk_imported': False, 'broker_calls': 0,
            'orders_sent': 0, 'scheduled_orders': 0, 'real_simulator': 'BLOCKED',
            'real_production': 'FORBIDDEN', 'frontend': 'NOT_CONNECTED'}))
        if not result.wasSuccessful():
            # Environment is scrubbed and all test inputs are invented fixtures.
            print(stream.getvalue(), file=sys.stderr)
        return 0 if result.wasSuccessful() else 1
    presence = json.loads(sys.stdin.read(4096) or '{}')
    if type(presence) is not dict or any(type(v) is not bool for v in presence.values()):
        raise ValueError('INVALID_PRESENCE_INPUT')
    result = preflight(inspect_sdk(ROOT), presence, datetime.now(timezone.utc), mode=args.mode)
    print(json.dumps(result, ensure_ascii=True))
    # All real modes remain blocked before any SDK import. No login retry or timer.
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Never emit exception values, paths, SDK prints or raw account payloads.
        print(json.dumps({'status': 'BLOCKED', 'reasonCodes': ['WORKER_FAILED_CLOSED'],
                          'broker_calls': 0, 'orders_sent': 0}))
        raise SystemExit(2)
