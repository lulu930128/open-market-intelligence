"""Production inherited ABORT_PREPARE branch with no sockets or database."""
import asyncio
import json
import os
import queue
import sys
import time
from types import SimpleNamespace
import uuid

import pytest

from app import owned_uvicorn
from app.runtime import RuntimeCoordinator
from app.runtime_admission import AsyncAdmission


@pytest.mark.parametrize('fault', ['', 'uuid', 'deadline', 'child', 'owner', 'unguarded', 'undo-failed', 'stop-after-abort'])
def test_abort_rearms_only_same_prepared_live_generation(monkeypatch, fault):
    async def check():
        runtime = RuntimeCoordinator.__new__(RuntimeCoordinator)
        runtime.started = True
        runtime.http_admission = AsyncAdmission()
        runtime._restart_rearmed = False
        runtime._restart_preparing = runtime._restart_committed = False
        runtime._restart_guard = runtime._restart_expiry = runtime._stop_task = None
        runtime._restart_undo = []
        runtime._restart_gates = []
        runtime._restart_owner_commits = []
        runtime._restart_deadline = 0
        runtime.owned_restart_preflight = lambda: {'state': ''}

        async def prepare(**kwargs):
            lease = runtime.http_admission.pause()
            runtime._restart_undo.append(lambda: runtime.http_admission.resume(lease))
            if fault == 'undo-failed':
                def fail():
                    raise RuntimeError('fixture undo failure')
                runtime._restart_undo.append(fail)
            return {'state': 'WRITERS_PREPARED'}
        runtime.prepare_owned_restart = prepare
        def forbidden():
            raise AssertionError('ABORT cannot commit STOP')
        runtime.commit_owned_restart = forbidden

        finish = asyncio.Event()
        servers = []
        class Server:
            def __init__(self, config):
                self.started = False
                self.should_exit = False
                servers.append(self)
            async def serve(self, sockets=None):
                self.started = True
                await finish.wait()

        frames = queue.Queue()
        class Input:
            def readline(self, size):
                return frames.get(timeout=3)
        created = owned_uvicorn.creation(os.getpid())
        boot = dict(scope='PRODUCTION', instance=str(uuid.uuid4()), nonce='a'*64,
                    launcher_pid=str(os.getpid()), launcher_created=created,
                    runner_pid=str(os.getpid()), runner_created=created,
                    host='127.0.0.1', port='65431', release_id='offline')
        for key in ('launcher_pid', 'launcher_created', 'host', 'port'):
            prefix = 'OMI_RUNTIME_' if key.startswith('launcher') else 'OMI_BACKEND_'
            monkeypatch.setenv(prefix + key.upper(), boot[key])
        monkeypatch.setitem(sys.modules, '_omi_owned_release', SimpleNamespace(release_id='offline'))
        observed = []
        original = None
        def send(value):
            frames.put(json.dumps(value) + '\n')
        def capture(value):
            nonlocal original
            observed.append(value.copy())
            if value['state'] == 'READY':
                assert value['restart_abort_protocol'] == '1'
                original = dict(value, action='PREPARE', request_id=str(uuid.uuid4()),
                                deadline=str(int(time.time()*1000)+10000))
                send(dict(original, action='ABORT_PREPARE') if fault == 'unguarded' else original)
            elif value['state'] == 'WRITERS_PREPARED':
                assert not runtime.http_admission.accepting
                abort = dict(original, action='ABORT_PREPARE')
                if fault == 'uuid': abort['request_id'] = str(uuid.uuid4())
                if fault == 'deadline': abort['deadline'] = '1'
                if fault == 'child': abort['child_created'] = 'wrong'
                if fault == 'owner': abort['launcher_created'] = 'wrong'
                send(abort)
            elif value['state'] == 'REJECTED':
                if fault in {'unguarded', 'stop-after-abort'}:
                    assert runtime.http_admission.accepting
                    finish.set()
                else:
                    assert not runtime.http_admission.accepting
                    send(dict(original, action='ABORT_PREPARE'))
            elif value['state'] in {'PREFLIGHT_REARMED', 'REARM_UNKNOWN'}:
                assert value['action'] == 'ABORT_PREPARE'
                assert value['request_id'] == original['request_id']
                assert value['deadline'] == original['deadline']
                assert value['rearmed'] == ('false' if fault == 'undo-failed' else 'true')
                assert runtime.http_admission.accepting is (fault != 'undo-failed')
                assert runtime.owned_restart_rearmed() is (fault != 'undo-failed')
                if fault == 'stop-after-abort':
                    send(dict(original, action='STOP'))
                else:
                    finish.set()
            return True
        monkeypatch.setattr(sys, 'stdin', Input())
        monkeypatch.setattr(owned_uvicorn.uvicorn, 'Server', Server)
        monkeypatch.setattr(owned_uvicorn, 'emit', capture)
        app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        try:
            assert await asyncio.wait_for(owned_uvicorn.serve_owned(app, boot=boot), 3) == 72
        finally:
            frames.put('')
        assert not servers[0].should_exit
        assert 'STOP_ACCEPTED' not in [v['state'] for v in observed]
        assert runtime._stop_task is None and not runtime._restart_committed
    asyncio.run(check())
