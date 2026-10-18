"""Fixed disposable app; shares app.owned_uvicorn transport with production entry.

Uses unchanged RuntimeCoordinator + session/publisher owner source through the
existing B4 AST fixture. No production app import/start, DB or network access.
"""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
from pathlib import Path
import sys
from threading import Event, Thread
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.venv/Lib/site-packages'))
sys.path.insert(0, str(Path(__file__).parent))
from b4_lifespan_child import install_guard, owners
from fastapi import FastAPI

spec = importlib.util.spec_from_file_location('owned_uvicorn', ROOT / 'backend/app/owned_uvicorn.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)

# Read once here only to select fixed fixture fault behavior; the real transport
# validates this same boot message against live OS identities.
import json
boot_line = sys.stdin.readline(8193)
boot = json.loads(boot_line)
original_stdin = sys.stdin


class PrefixedInput:
    def __init__(self): self.first = True
    def readline(self, limit=-1):
        if self.first:
            self.first = False
            return boot_line
        return original_stdin.readline(limit)


sys.stdin = PrefixedInput()
scenario = boot['scenario']
allowed = {'normal', 'active', 'unknown', 'stuck', 'stuck-worker', 'ack-alive', 'runner-crash', 'shutdown-error', 'cancel-worker', 'lifespan-alive', 'startup-error'}
if scenario not in allowed:
    raise ValueError('UNKNOWN_FIXTURE_SCENARIO')


class FixtureAdmission:
    def __init__(self):
        self.closed = False
        self.accepted = 0
        self.completed = 0
        self.event = Event()
        self.entered = Event()
        self.worker = Thread(target=self.work)
        self.worker.start()
        if not self.entered.wait(1): raise RuntimeError('WORKER_NOT_ADMITTED')

    def work(self):
        self.accepted += 1
        self.entered.set()
        self.event.wait(7)
        if scenario == 'stuck-worker':
            time.sleep(3)
        self.completed += 1

    def release(self): self.event.set()

    async def prepare(self):
        # Unknown coverage refuses before changing admission, like production.
        if scenario == 'unknown': return 'UNKNOWN_WRITER'
        if scenario == 'active': return 'ACTIVE_WRITER'
        self.closed = True
        self.release()
        while self.worker.is_alive(): await asyncio.sleep(.01)
        if self.accepted != self.completed or not self.closed: return 'INCOMPLETE'
        return 'DISPOSABLE_DRAINED'


async def main():
    admission = FixtureAdmission()
    source_paths = ['backend/app/db/session.py', 'backend/app/jobs/us_intraday_materializer_scheduler.py',
                    'backend/app/runtime.py', 'backend/app/runtime_admission.py']
    source = {p: (ROOT / p).read_bytes() for p in source_paths}
    session, publisher, runtime_module, runtime = owners(Path(boot['journal']), lambda *a, **k: None, lambda: None, source)

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime
        try:
            if scenario == 'startup-error':
                raise RuntimeError('DISPOSABLE_STARTUP_FAILURE')
            yield
        finally:
            if scenario in {'stuck', 'ack-alive'}: await asyncio.sleep(3)
            if scenario == 'shutdown-error': raise RuntimeError('DISPOSABLE_SHUTDOWN_FAILURE')
            if scenario == 'cancel-worker': raise asyncio.CancelledError()
            await runtime.stop(timeout_seconds=1)
            if runtime.drain_result.state != 'REGISTERED_DRAINED': raise RuntimeError('REGISTERED_DRAIN_FAILED')
            # Explicitly retain all_writers_drained=False. Fixture admission above
            # only attests this disposable app's worker, never production writers.
            if runtime.drain_result.all_writers_drained: raise RuntimeError('INVALID_GLOBAL_AUTHORITY')

    try:
        code = await transport.serve_owned(FastAPI(lifespan=lifespan), fixture_owner=admission)
        if scenario == 'lifespan-alive':
            # A genuine completed lifespan ACK is still not process exit.
            await asyncio.sleep(3)
        return code
    finally:
        admission.release()
        admission.worker.join(2)


# Like B4, construct only asyncio's internal wakeup pair before installing the
# strict fixture guard. No listener/DB/provider is ever created by the app.
loop = asyncio.new_event_loop()
install_guard()
try:
    raise SystemExit(loop.run_until_complete(main()))
finally:
    loop.close()
