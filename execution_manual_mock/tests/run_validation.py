"""Bounded execution-only validation; no app/production runtime imports."""
import json
import io
import logging
from pathlib import Path
import tempfile
import unittest


def main():
    root = Path(__file__).resolve().parents[2]
    temp = root / '.tmp'
    temp.mkdir(exist_ok=True)
    tempfile.tempdir = str(temp)
    logging.getLogger('asyncio').setLevel(logging.ERROR)
    results = []
    for name in ('execution', 'execution_simulation', 'execution_simulation_gateway',
                 'execution_broker_preflight', 'execution_manual_mock'):
        suite = unittest.defaultTestLoader.discover(str(root / name / 'tests'), top_level_dir=str(root))
        diagnostics = io.StringIO()
        result = unittest.TextTestRunner(stream=diagnostics, verbosity=0).run(suite)
        value = {'suite': name, 'tests': result.testsRun,
                 'pass': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
                 'fail': len(result.failures) + len(result.errors), 'skip': len(result.skipped),
                 'skip_reasons': [reason for _, reason in result.skipped]}
        results.append(value)
        print(json.dumps(value), flush=True)
        if not result.wasSuccessful():
            print(diagnostics.getvalue(), flush=True)
    passed = all(value['fail'] == 0 for value in results)
    print(json.dumps({'source_gate': 'PASS' if passed else 'FAIL',
                      'tests': sum(value['tests'] for value in results),
                      'pass': sum(value['pass'] for value in results),
                      'fail': sum(value['fail'] for value in results),
                      'skip': sum(value['skip'] for value in results),
                      'live': 'BLOCKED', 'frontend': 'BLOCKED'}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
