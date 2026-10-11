"""Owned loopback test process. Parent pipe controls lifetime; no OMI startup import."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
import msvcrt
import os
import socket
import sys
import tempfile
from pathlib import Path
from threading import Thread
import time

import uvicorn

from execution_simulation import SimulationApplication
from execution_simulation.storage import temporary_sandbox
from execution_simulation_gateway.security import SyntheticAuth
from .fixtures import ACCOUNT, PRINCIPAL, ORIGIN, DEFAULT_SYMBOLS, catalog
from .gateway import ManualMockApp


@contextmanager
def worker_lock(sandbox):
    """OS-released lifetime mutex, scoped only to the factory sandbox (Windows)."""
    path = sandbox.directory / 'manual-worker.lock'
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('DEDICATED_WORKER_ALREADY_OWNED') from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def run():
    parser = argparse.ArgumentParser(description='SYNTHETIC ONLY manual loopback; no real SDK')
    parser.add_argument('--symbols', default=','.join(DEFAULT_SYMBOLS))
    args = parser.parse_args()
    # Child-local factory temp root; no environment or credential lookup.
    temp_root = Path(__file__).resolve().parents[1] / '.tmp'
    temp_root.mkdir(exist_ok=True)
    tempfile.tempdir = str(temp_root)
    clock = lambda: datetime.now(timezone.utc)
    with temporary_sandbox() as sandbox, worker_lock(sandbox):
        application = SimulationApplication(sandbox)
        now = clock()
        policy, scenarios = catalog(tuple(args.symbols.split(',')), now)
        auth = SyntheticAuth(origins={ORIGIN}, requests_per_minute=1000)
        credentials = auth.issue(PRINCIPAL, ACCOUNT, now=now)
        app = ManualMockApp(application, auth, policy, clock, scenarios)
        # This enables only the closed fake protocol in this disposable test process.
        application.set_mock_send_enabled(True, now=now, user_confirmed=True)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            config = uvicorn.Config(app, host='127.0.0.1', lifespan='off', access_log=False,
                                    log_level='error', proxy_headers=False)
            server = uvicorn.Server(config)
            thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.02)
            if not server.started:
                raise RuntimeError('MOCK_LISTENER_START_FAILED')
            # Only the spawning PowerShell receives this private pipe. Never log it.
            print(json.dumps({'port': listener.getsockname()[1], 'session': credentials.session,
                'csrf': credentials.csrf, 'origin': ORIGIN, 'simulated': True,
                'runtime': {'pid': os.getpid(), 'root': str(temp_root.parent),
                    'interpreter': sys.executable, 'python': sys.version.split()[0],
                    'host': '127.0.0.1', 'storage': 'factory-temporary-schema-v1',
                    'code_sha256': hashlib.sha256(b''.join(
                        str(path.relative_to(temp_root.parent)).encode() + b'\0' + path.read_bytes()
                        for name in ('execution', 'execution_simulation', 'execution_simulation_gateway', 'execution_manual_mock')
                        for path in sorted((temp_root.parent / name).glob('*.py')))).hexdigest()}}), flush=True)
            stop = Thread(target=sys.stdin.readline, daemon=True)
            stop.start()
            try:
                stop.join(timeout=300)
            finally:
                auth.revoke(credentials)
                application.set_mock_send_enabled(False, now=clock(), user_confirmed=True)
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError('MOCK_LISTENER_STOP_FAILED')


if __name__ == '__main__':
    run()
