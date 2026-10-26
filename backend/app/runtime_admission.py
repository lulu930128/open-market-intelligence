"""Reversible admission primitive embedded in existing async lifecycle owners.

It neither starts work nor owns transactions. Pause never cancels admitted work;
only the exact private lease can resume or commit that owner's admission.
"""
import asyncio
from contextlib import asynccontextmanager
from threading import Lock, Thread


class AdmissionCommitted(RuntimeError):
    pass


class AsyncAdmission:
    def __init__(self):
        self._open = asyncio.Event()
        self._open.set()
        self._lease = None
        self._active = 0
        self._committed = False

    @asynccontextmanager
    async def work(self, *, wait=True):
        if not wait and (self._lease is not None or self._committed):
            raise AdmissionCommitted("Owner admission is paused")
        while self._lease is not None and not self._committed:
            await self._open.wait()
        if self._committed:
            raise AdmissionCommitted("Owner admission is terminal")
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1

    def pause(self):
        if self._lease is not None or self._committed:
            raise RuntimeError("Owner quiescence already in progress")
        self._lease = object()
        self._open.clear()
        return self._lease

    def idle(self, lease):
        return lease is self._lease and not self._committed and self._active == 0

    @property
    def accepting(self):
        return self._lease is None and not self._committed

    def resume(self, lease):
        if lease is not self._lease or self._committed:
            raise RuntimeError("Invalid quiescence lease")
        self._lease = None
        self._open.set()

    def commit(self, lease):
        if not self.idle(lease):
            raise RuntimeError("Owner has not quiesced")
        self._committed = True
        self._open.set()


class DetachedAdmission:
    """Retain existing detached workers before Thread.start, including lazy DB use."""
    def __init__(self):
        self._lock = Lock()
        self._workers = set()
        self._lease = None

    def enter(self):
        with self._lock:
            if self._lease is not None:
                raise AdmissionCommitted("Detached worker admission is paused")
            token = object()
            self._workers.add(token)
            return token

    def leave(self, token):
        with self._lock:
            self._workers.remove(token)

    def observation(self):
        """Memory-only retention count, including starts without completion proof."""
        with self._lock:
            return {"retained_worker_count": len(self._workers),
                    "admission_paused": self._lease is not None}

    def pause_if_idle(self):
        with self._lock:
            if self._lease is not None:
                raise AdmissionCommitted("Detached workers already paused")
            if self._workers:
                return None
            self._lease = object()
            return self._lease

    def resume(self, lease):
        with self._lock:
            if self._lease is not lease:
                raise RuntimeError("Invalid detached worker lease")
            self._lease = None


detached_admission = DetachedAdmission()


class OwnedWorkThread(Thread):
    """Same business worker and join semantics; no cancellation or new executor."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._admission_start_lock = Lock()
        self._admission_owner = None

    def start(self):
        with self._admission_start_lock:
            if self._admission_owner is not None:
                raise RuntimeError("threads can only be started once")
            self._admission_owner = detached_admission
            self._admission_token = self._admission_owner.enter()
            # start() can fail after native dispatch but before its caller sees
            # success. Only run()'s finally proves completion; an exception or
            # is_alive()==False cannot safely release this reservation.
            super().start()

    def run(self):
        try:
            super().run()
        finally:
            self._admission_owner.leave(self._admission_token)


class RuntimeAdmissionMiddleware:
    """ASGI scope lifetime includes streaming and Starlette background work."""
    def __init__(self, app):
        self.app = app
        self._scopes = set()

    async def __call__(self, scope, receive, send):
        runtime = getattr(getattr(scope.get("app"), "state", None), "runtime", None)
        if (scope["type"] != "http" or runtime is None
                or scope.get("path", "").startswith("/api/system/runtime-control/")):
            return await self.app(scope, receive, send)
        if not runtime.http_admission.accepting:
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"1")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Backend restart preflight in progress"}'})
            return
        # Retain the actual ASGI lifetime when its caller is cancelled. This
        # includes background work; only normal scope completion releases the
        # reservation without an unknown-ownership latch. Never cancel work to
        # make PREPARE succeed (including thread-pool work behind the scope).
        reservation = runtime.http_admission.work(wait=False)
        await reservation.__aenter__()  # Reserve before scheduling can yield to PREPARE.

        async def admitted_scope():
            try:
                await self.app(scope, receive, send)
            except (asyncio.CancelledError, GeneratorExit):
                runtime.http_ownership_unknown = True
                raise
            finally:
                await reservation.__aexit__(None, None, None)

        task = asyncio.create_task(admitted_scope())
        self._scopes.add(task)

        def completed(done):
            self._scopes.discard(done)
            if not done.cancelled():
                done.exception()  # Retrieve errors even if the caller departed.

        task.add_done_callback(completed)
        return await asyncio.shield(task)
