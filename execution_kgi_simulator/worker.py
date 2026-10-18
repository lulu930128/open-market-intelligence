"""Bounded no-network worker. Only PowerShell launches it; no OMI/PAOS reuse."""

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('INVALID_WORKER_ARGUMENTS')


def offline_guard(event, args):
    if (event.startswith('socket.') or event == 'ctypes.dlopen'
            or (event == 'import' and str(args[0]).split('.')[0] == 'kgisuperpy')):
        raise RuntimeError('OFFLINE_IO_BLOCKED')


def readonly_guard(event, args):
    """Defense in depth for qualification only, not a native SDK sandbox."""
    offline_guard(event, args)
    if event == 'open':
        flags = args[2]
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError('READONLY_WRITE_BLOCKED')
    if (event.startswith(('subprocess.', 'os.spawn', 'os.exec'))
            or event in {'os.system', 'os.mkdir', 'os.remove', 'os.rename',
                         'os.rmdir', 'os.chmod', 'os.link', 'os.symlink', 'os.truncate',
                         'os.utime', 'os.chown', 'os.startfile', 'os.startfile/2'}):
        raise RuntimeError('READONLY_EFFECT_BLOCKED')


def read_presence(stream):
    """Only bounded boolean presence crosses this pipe; reject proof/credentials."""
    from execution_kgi_simulator.gates import SIM_NAMES
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('INVALID_PRESENCE_INPUT')
            result[key] = value
        return result
    raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('INVALID_PRESENCE_INPUT')
    presence = json.loads(raw or '{}', object_pairs_hook=unique)
    if (type(presence) is not dict or set(presence) - set(SIM_NAMES)
            or any(type(v) is not bool for v in presence.values())):
        raise ValueError('INVALID_PRESENCE_INPUT')
    return presence


def main():
    parser = ClosedArgumentParser(allow_abbrev=False)
    parser.add_argument('mode', choices=['Preflight', 'ContractTest', 'Probe', 'Send',
                                         'RealSimPreflight', 'RealSimProbe'])
    args = parser.parse_args()
    sys.addaudithook(offline_guard)
    sys.path.insert(0, str(ROOT))
    if args.mode != 'ContractTest':
        sys.addaudithook(readonly_guard)
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
    presence = read_presence(sys.stdin)
    if args.mode in ('RealSimPreflight', 'RealSimProbe'):
        from execution_kgi_simulator.real_sim import qualify
        result = qualify(ROOT, presence, datetime.now(timezone.utc), mode=args.mode)
    else:
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
