"""Fixed Windows B4 child. Real Uvicorn lifespan, no listener or OMI startup.

AST nodes are compiled unchanged from hash-bound existing owners; only globals
are injected. This is source/fixture evidence, not loaded production adoption.
The only app import used by the publisher resolves to an in-memory fake reader.
"""
from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager, closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
from threading import Event, Lock, Thread, current_thread
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Generator, Protocol

REPOSITORY = Path(__file__).resolve().parents[3]
# -I -S: no PYTHONPATH, site customization, .pth, user packages or dotenv.
sys.path.insert(0, str(REPOSITORY / '.venv/Lib/site-packages'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uvicorn
from r1e_stop_child import process_start, publish


def install_guard():
    def audit(event, args):
        if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'sqlite3.connect',
                     'subprocess.Popen', 'os.system'}:
            raise RuntimeError('B4 isolated guard denied ' + event)
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.fsdecode(args[0]).replace('\\', '/').lower()
            if (any(part in {'.env', '.env.runtime', '.secrets', 'data', 'weights', 'cache'}
                    or part.startswith('.env.') for part in name.split('/'))
                    or name.endswith(('.db', '.sqlite', '.sqlite3', '-wal', '-shm'))):
                raise RuntimeError('B4 isolated guard denied sensitive/persistent file')
        if event == 'import' and str(args[0]).startswith('app.'):
            raise RuntimeError('B4 forbids real application imports')
    sys.addaudithook(audit)


def hashes(expected):
    return {path: hashlib.sha256((REPOSITORY / path).read_bytes()).hexdigest()
            for path in expected}


def load_owner(relative, predicate, injected, source_bytes):
    """No copied implementation or import-time engine/settings side effects."""
    tree = ast.parse(source_bytes[relative].decode('utf-8-sig'))
    selected = [node for node in tree.body if predicate(node)]
    module = ModuleType('b4_' + Path(relative).stem)
    sys.modules[module.__name__] = module
    module.__dict__.update(injected)
    future = ast.parse('from __future__ import annotations').body
    exec(compile(ast.Module(future + selected, type_ignores=[]), relative, 'exec'), module.__dict__)
    return module


def node_name(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ''


@dataclass(frozen=True)
class EmptyJobsReceipt:
    drained: bool = True


def owners(root, read, session_factory, source_bytes):
    shared = dict(asyncio=asyncio, contextmanager=contextmanager, closing=closing,
                  dataclass=dataclass, replace=replace, time=time, math=math, Lock=Lock,
                  Thread=Thread, current_thread=current_thread, Any=Any, Callable=Callable,
                  Generator=Generator, Protocol=Protocol, Session=object,
                  logger=logging.getLogger('b4-fixture'))
    session_names = {'SessionAdmissionClosed', '_SessionScope', 'SessionDrainResult',
        'require_session_scope_admission', 'begin_session_scope_drain', 'owned_session',
        'session_scope_drain_status', 'drain_session_scopes', 'get_draining_db'}
    session = load_owner('backend/app/db/session.py',
        lambda n: node_name(n).startswith('_session_scope') or node_name(n) in session_names,
        dict(shared, SessionLocal=session_factory), source_bytes)
    # The unchanged R1F worker's local import receives only this injected reader.
    fake_reader = ModuleType('app.us_market.service')
    fake_reader.get_us_intraday_trend = read
    sys.modules['app.us_market.service'] = fake_reader
    publisher_names = {'_ReadModelPublishTask', 'PublisherDrainResult',
        'require_intraday_publisher_admission', 'begin_intraday_publisher_drain',
        '_reap_intraday_publishers_locked', 'intraday_publisher_drain_status',
        'drain_intraday_publishers', '_publish_intraday_consumer_read_model',
        '_schedule_intraday_consumer_read_model'}
    publisher = load_owner('backend/app/jobs/us_intraday_materializer_scheduler.py',
        lambda n: node_name(n).startswith('_READ_MODEL') or node_name(n) in publisher_names,
        dict(shared, SessionLocal=session_factory), source_bytes)
    async def drain_jobs(*, deadline):
        return EmptyJobsReceipt()
    jobs = SimpleNamespace(begin_job_drain=lambda: None, drain_job_executor=drain_jobs,
                           job_drain_status=EmptyJobsReceipt)
    runtime = load_owner('backend/app/runtime.py',
        lambda n: node_name(n) in {'RuntimeLock', 'RuntimeDrainResult', 'RuntimeDrainError', 'RuntimeCoordinator'},
        dict(shared, session_owner=session, intraday_publisher=publisher, job_service=jobs,
             settings=SimpleNamespace(runtime_lock_dir=root)), source_bytes)
    coordinator = runtime.RuntimeCoordinator(schema_lock=object(), background_lock=object(),
                                             drain_owned_sessions=True)
    return session, publisher, runtime, coordinator


async def rehearse(root, instance, runner_pid, runner_start, scenario):
    own_start = process_start(os.getpid())
    expected_hashes = json.loads((root / 'source.json').read_text())
    if hashes(expected_hashes) != expected_hashes:
        raise RuntimeError('SOURCE_DRIFT_BEFORE_START')
    source_bytes = {path: (REPOSITORY/path).read_bytes() for path in expected_hashes}
    for path, data in source_bytes.items():
        if hashlib.sha256(data).hexdigest() != expected_hashes[path]:
            raise RuntimeError('SOURCE_DRIFT_AT_LOAD')
        copy = root / 'source-preimages' / path
        copy.parent.mkdir(parents=True, exist_ok=True)
        with copy.open('xb') as stream:
            stream.write(data)
    release, api_entered, publisher_entered = Event(), Event(), Event()
    timeline = []
    state = dict(request=None, reason=None, receipt=None, lifespan_complete=False, stop_count=0,
                 unknown_fixture_work=False, dependency_finalized=False, worker_after_finalizer=False)
    def mark(name):
        timeline.append(dict(event=name, monotonic=time.monotonic()))

    class Session:
        def close(self):
            if scenario == 'partial-drain':
                raise RuntimeError('fixture close failure')
        def rollback(self): pass

    def read(**kwargs):
        publisher_entered.set()
        assert release.wait(6), 'finite fixture lease'
        if scenario == 'stuck-worker':
            time.sleep(2.5)

    session, publisher, runtime_module, runtime = owners(root, read, Session, source_bytes)
    # FastAPI is used only by the existing dependency generator, never OMI app.
    dependency = session.get_draining_db()
    borrowed = next(dependency)
    def api_worker():
        api_entered.set()
        assert release.wait(6), 'finite fixture lease'
        if scenario in {'cancel-worker', 'borrowed-escape'}:
            state['worker_after_finalizer'] = state['dependency_finalized']
            mark('real_worker_after_dependency_finalizer')
            time.sleep(0.1)
        # Borrowed fake Session remains held until this true worker returns.
        assert borrowed is not None
    api = Thread(target=api_worker, name='b4-admitted-api', daemon=False)
    api.start()
    assert publisher._schedule_intraday_consumer_read_model('B4_FIXTURE')
    publisher_thread = publisher._READ_MODEL_PUBLISH_TASKS['B4_FIXTURE'].thread
    until = time.monotonic() + 2
    while not (api_entered.is_set() and publisher_entered.is_set()):
        if time.monotonic() > until: raise RuntimeError('fixture owners not admitted')
        await asyncio.sleep(.005)
    mark('owners_admitted')

    async def finalize_dependency():
        if state['dependency_finalized']: return
        state['dependency_finalized'] = True
        mark('dependency_finalizer')
        try:
            if scenario == 'cancel-worker':
                dependency.throw(asyncio.CancelledError())
            else:
                next(dependency)
        except (StopIteration, asyncio.CancelledError):
            pass
        except RuntimeError:
            if scenario != 'partial-drain': raise

    async def app(scope, receive, send):
        assert scope['type'] == 'lifespan'
        assert (await receive())['type'] == 'lifespan.startup'
        await send({'type': 'lifespan.startup.complete'})
        assert (await receive())['type'] == 'lifespan.shutdown'
        mark('lifespan_shutdown_received')
        state['stop_count'] += 1
        if scenario == 'timeout': await asyncio.sleep(2.5)
        if scenario in {'cancel-worker', 'borrowed-escape'}:
            await finalize_dependency()
            if scenario == 'borrowed-escape': state['unknown_fixture_work'] = True
        if scenario == 'unknown-session':
            try:
                with session.owned_session('unknown'):
                    raise AssertionError('unknown owner admitted')
            except ValueError:
                state['unknown_fixture_work'] = True
        deadline = (datetime.fromisoformat(state['request']['deadline_utc']) - datetime.now(timezone.utc)).total_seconds() if state['request'] else .1
        drain = asyncio.create_task(runtime.stop(timeout_seconds=max(0, deadline)))
        # Runtime.stop fences owners before releasing admitted fixture work.
        await asyncio.sleep(0)
        mark('admission_fenced')
        assert session._session_scope_closed and publisher._READ_MODEL_PUBLISH_CLOSED
        release.set()
        while api.is_alive(): await asyncio.sleep(.005)
        api.join(0)
        await finalize_dependency()
        try:
            state['receipt'] = asdict(await drain)
        except runtime_module.RuntimeDrainError as exc:
            state['receipt'] = asdict(exc.result)
        mark('runtime_drain_receipt')
        # Repeated stop must return the same terminal owner receipt.
        try:
            repeated = await runtime.stop(timeout_seconds=0)
        except runtime_module.RuntimeDrainError as exc:
            repeated = exc.result
        assert asdict(repeated) == state['receipt']
        await send({'type': 'lifespan.shutdown.complete'})
        state['lifespan_complete'] = True
        mark('lifespan_shutdown_complete')

    server = uvicorn.Server(uvicorn.Config(app, lifespan='on', loop='asyncio', http='h11',
                             ws='none', log_config=None, access_log=False, timeout_graceful_shutdown=1))
    serving = asyncio.create_task(server.serve(sockets=[]))
    while not server.started:
        if serving.done(): await serving; raise RuntimeError('Uvicorn not started')
        await asyncio.sleep(.005)
    mark('uvicorn_started_without_listener')
    publish(root, 'ready.json', dict(instance=instance, child_pid=os.getpid(),
        child_start=str(int(own_start)+1) if scenario == 'ready-wrong-start' else own_start))
    lease = time.monotonic() + 5
    while time.monotonic() < lease:
        try:
            if process_start(runner_pid) != runner_start:
                state['reason'] = 'PARENT_IDENTITY_LOST'; break
        except OSError:
            state['reason'] = 'PARENT_DISAPPEARED'; break
        if (root / 'request.json').exists():
            request = json.loads((root / 'request.json').read_text())
            intent = json.loads((root / 'stop-intent.json').read_text())
            expected = dict(instance=instance, runner_pid=runner_pid, runner_start=runner_start,
                            child_pid=os.getpid(), child_start=own_start)
            if request != intent or any(request.get(k) != v for k,v in expected.items()):
                state['reason'] = 'REQUEST_IDENTITY_MISMATCH'; break
            remaining = (datetime.fromisoformat(request['deadline_utc']) - datetime.now(timezone.utc)).total_seconds()
            if not 0 < remaining <= 2:
                state['reason'] = 'INVALID_DEADLINE'; break
            state['request'] = request
            break
        await asyncio.sleep(.005)
    if state['request'] is None and state['reason'] is None: state['reason'] = 'ORPHAN_LEASE_EXPIRED'
    if scenario == 'child-crash': os._exit(75)
    mark('validated_stop_request' if state['request'] else 'unrequested_terminal_stop')
    server.should_exit = True
    await serving
    mark('uvicorn_serve_returned')
    workers_exited = not api.is_alive() and not publisher_thread.is_alive()
    if scenario == 'source-drift':
        # Real byte drift in our disposable copy only; canonical WIP untouched.
        with (root/'source-preimages/backend/app/runtime.py').open('ab') as stream:
            stream.write(b'\n# disposable drift injection\n')
    snapshot_hashes = {path: hashlib.sha256((root/'source-preimages'/path).read_bytes()).hexdigest()
                       for path in expected_hashes}
    if hashes(expected_hashes) != expected_hashes or snapshot_hashes != expected_hashes:
        state['reason'] = 'SOURCE_DRIFT'
    receipt = dict(state['request'] or {})
    receipt.update(scope='B4_SOURCE_FIXTURE_ONLY', forced=False,
        lifespan_complete=state['lifespan_complete'] and not server.lifespan.shutdown_failed,
        server_returned=True, workers_exited=workers_exited, stop_count=state['stop_count'],
        drain=state['receipt'], unknown_fixture_work=state['unknown_fixture_work'],
        source_hashes=hashes(expected_hashes), uvicorn_version=uvicorn.__version__,
        event_loop=type(asyncio.get_running_loop()).__name__, listener_count=len(server.servers),
        timeline=timeline, worker_after_finalizer=state['worker_after_finalizer'])
    if state['request'] and not state['reason'] and scenario != 'missing-ack':
        mutations = {'wrong-pid': ('child_pid', os.getpid()+1), 'wrong-start': ('child_start','0'),
            'wrong-instance': ('instance','wrong'), 'wrong-deadline': ('deadline_utc','wrong'),
            'wrong-request': ('request_id','wrong'), 'wrong-runner': ('runner_start','0')}
        if scenario in mutations:
            key,value=mutations[scenario]; receipt[key]=value
        if scenario == 'fake-ack': receipt['lifespan_complete'] = False
        # Wire-level corruption after genuine drain: receiver must independently
        # reject inconsistent/unknown fields, even with matching process identity.
        sessions, published = receipt['drain']['sessions'], receipt['drain']['publisher']
        if scenario == 'ack-session-type': sessions['admission_closed'] = 'True'
        if scenario == 'ack-publisher-type': published['admission_closed'] = 'True'
        if scenario == 'ack-unknown-type': receipt['unknown_fixture_work'] = 'False'
        if scenario == 'ack-pending-constructor': sessions['pending_constructors'] = 1
        if scenario == 'ack-close-failure': sessions['close_failures'] = 1
        if scenario == 'ack-uncertain-owner': sessions['uncertain_owners'] = ['api_request']
        if scenario == 'ack-unknown-publisher': published['unknown_symbols'] = ['B4_FIXTURE']
        if scenario == 'ack-incomplete-jobs': receipt['drain']['jobs']['drained'] = False
        if scenario == 'ack-global-drained': sessions['all_writers_drained'] = True
        if scenario == 'ack-null-owners': sessions['active_owners'] = None
        if scenario == 'ack-unknown-scheduler': receipt['drain']['scheduler_state'] = 'unknown'
        if scenario == 'ack-active-collector': receipt['drain']['collectors'] = {'fixture': 'timeout'}
        if scenario == 'double-signal':
            duplicate = json.loads((root/'request-duplicate.json').read_text())
            assert duplicate == state['request']
            receipt['duplicate_observed'] = True
        publish(root, 'ack.json', receipt)
    # Evidence after deadline remains diagnostic and cannot upgrade runner verdict.
    publish(root, 'child-observation.json', dict(state=state, timeline=timeline,
        workers_exited_at_ack=workers_exited, child_pid=os.getpid(), child_start=own_start,
        source_hashes=expected_hashes, snapshot_hashes_after=snapshot_hashes))
    if scenario == 'ack-without-exit': await asyncio.sleep(2.5)
    release.set()
    # Bounded own worker lease, no cancellation/kill of unknown or external work.
    publisher_thread.join(6)
    api.join(6)
    assert not publisher_thread.is_alive() and not api.is_alive(), 'ORPHAN: no force fallback'
    return 72 if state['reason'] else 0


def main():
    root, instance, runner_pid, runner_start, scenario = sys.argv[1:]
    root = Path(root)
    if process_start(int(runner_pid)) != runner_start: return 71
    # Native Windows loop self-pipe is constructed BEFORE denying all network.
    # No patched event loop or fake selector is used for B4 acceptance.
    loop = asyncio.new_event_loop()
    install_guard()
    with asyncio.Runner(loop_factory=lambda: loop) as runner:
        return runner.run(rehearse(root, instance, int(runner_pid), runner_start, scenario))


if __name__ == '__main__':
    raise SystemExit(main())
