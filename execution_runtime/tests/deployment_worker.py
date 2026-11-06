"""Test-only Launcher supervisor/Native composition, always synthetic state + SDK."""
import argparse
from dataclasses import replace
import io
import os
from pathlib import Path
import sys

from execution_runtime import __main__ as entry, control, service
from execution_runtime.launch import LauncherOwner, supervise
from execution_runtime.native import NativeSettings
from .fake_sdk import DAY, FakeBroker, FakeSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--native-python', required=True)
    parser.add_argument('--scenario', choices=('normal', 'backoff'), default='normal')
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--persistent', action='store_true')
    parser.add_argument('--startup-id', required=True)
    parser.add_argument('--owner-pid', type=int)
    parser.add_argument('--owner-created')
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    assert (root / 'SYNTHETIC_ONLY').is_file()
    control.ADDRESS = service.ADDRESS = args.address
    if not args.native:
        owner = LauncherOwner(args.owner_pid, args.owner_created)
        command = [args.native_python, '-B', '-m', __spec__.name,
                   '--directory', str(root), '--address', args.address,
                   '--native-python', args.native_python, '--scenario', args.scenario, '--native']
        try:
            return supervise(command, {}, root, args.startup_id, owner=owner, retry_base=10, retry_cap=10)
        finally:
            owner.close()
    entry.STATE = root
    entry.NativeSettings.from_environment = lambda: NativeSettings(True, 'synthetic', 'synthetic')

    class Factory:
        def __init__(self, settings, owner_lease):
            assert owner_lease.held
        def current_day(self):
            return DAY
        def __call__(self):
            with (root / 'fake-logins.txt').open('a', encoding='ascii') as output:
                output.write('synthetic\n')
            sdk = FakeSession(FakeBroker(root / 'fake-broker.json'))
            return replace(sdk.binding(), current_day=self.current_day)
        def close_unclaimed(self):
            pass
    entry.NativeSessionFactory = Factory
    if args.scenario == 'backoff':
        original = service.record_startup
        def crash_after_ready(path, identity, value):
            original(path, identity, value)
            if value['status'] == 'READY':
                os._exit(73)
        service.record_startup = crash_after_ready
    entry.native_run(io.StringIO(), persistent=True, startup_id=args.startup_id)
    assert not any(k == 'kgisuperpy' or k.startswith('kgisuperpy.') for k in sys.modules)
    return 0


if __name__ == '__main__':
    try:
        result = main()
    except Exception:
        # Supervisor/Native stdio is deliberately suppressed. Preserve fixture
        # failures in synthetic state only, so process races remain diagnosable.
        import traceback
        directory = Path(sys.argv[sys.argv.index('--directory') + 1])
        if (directory / 'SYNTHETIC_ONLY').is_file():
            (directory / ('fixture-error-' + str(os.getpid()) + '.txt')).write_text(traceback.format_exc(), encoding='utf-8')
        raise
    raise SystemExit(result)
