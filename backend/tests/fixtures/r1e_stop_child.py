"""Finite Windows disposable child, stdlib only; never imports or starts OMI.

The private IPC directory's ACL is established and verified by the runner.
This proves a synthetic worker drain, not RuntimeCoordinator or DB quiescence.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time


def process_start(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in values]):
            raise ctypes.WinError(ctypes.get_last_error())
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def publish(root, name, value):
    path = root / name
    temp = root / (name + '.tmp')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # No overwritten receipt. The directory is newly created per runner.
    os.rename(temp, path)


def main():
    root, instance, runner_pid, runner_start, scenario = sys.argv[1:]
    root = Path(root)
    runner_pid = int(runner_pid)
    own_start = process_start(os.getpid())
    if process_start(runner_pid) != runner_start:
        return 71
    stop = threading.Event()
    admitted = threading.Event()
    counts = {'accepted': 0, 'completed': 0}

    def work():
        # A real non-daemon worker holds an admitted unit through stop intent.
        counts['accepted'] += 1
        admitted.set()
        stop.wait(7)
        time.sleep(2.5 if scenario == 'incomplete-drain' else 0.03)
        counts['completed'] += 1

    worker = threading.Thread(target=work)
    worker.start()
    admitted.wait()
    publish(root, 'ready.json', dict(instance=instance, child_pid=os.getpid(),
                                    child_start=str(int(own_start) + 1) if scenario == 'ready-wrong-start' else own_start))
    lease = time.monotonic() + 6
    request = None
    while time.monotonic() < lease:
        path = root / 'request.json'
        if path.exists():
            request = json.loads(path.read_text(encoding='utf-8'))
            break
        time.sleep(0.01)
    if request is None:
        stop.set()
        worker.join()
        return 72  # parent disappearance / missing request, never ACK
    expected = dict(instance=instance, runner_pid=runner_pid, runner_start=runner_start,
                    child_pid=os.getpid(), child_start=own_start)
    intent = json.loads((root / 'stop-intent.json').read_text(encoding='utf-8'))
    if (request != intent or any(request.get(key) != value for key, value in expected.items())
            or process_start(runner_pid) != runner_start):
        stop.set()
        worker.join()
        return 73
    deadline = datetime.fromisoformat(request['deadline_utc'].replace('Z', '+00:00'))
    if not 0 < (deadline - datetime.now(timezone.utc)).total_seconds() <= 2:
        stop.set()
        worker.join()
        return 74
    if scenario == 'child-crash':
        os._exit(75)  # fault injection in this disposable process only
    if scenario == 'timeout':
        time.sleep(2.5)
    stop.set()  # terminal admission fence, idempotent for duplicate request
    worker.join(timeout=0.05 if scenario == 'incomplete-drain' else None)
    if scenario == 'missing-ack':
        return 0
    receipt = dict(request)
    receipt.update(forced=False, drain=dict(state='INCOMPLETE' if worker.is_alive() else 'FIXTURE_DRAINED', worker_joined=not worker.is_alive(),
                                           admission_closed=stop.is_set(), stop_count=1, **counts))
    if scenario == 'double-signal':
        until = time.monotonic() + 0.2
        while not (root / 'request-duplicate.json').exists() and time.monotonic() < until:
            time.sleep(0.005)
        duplicate = json.loads((root / 'request-duplicate.json').read_text(encoding='utf-8'))
        if duplicate != request:
            return 76
        stop.set()
        receipt['duplicate_observed'] = True
    mutations = {'wrong-pid': ('child_pid', os.getpid() + 1), 'wrong-start': ('child_start', str(int(own_start) + 1)),
                 'wrong-instance': ('instance', 'different'), 'wrong-deadline': ('deadline_utc', 'different')}
    if scenario in mutations:
        key, value = mutations[scenario]
        receipt[key] = value
    if scenario == 'invalid-drain-receipt':
        receipt['drain']['completed'] = 0
    if scenario == 'forced-receipt':
        receipt['forced'] = True
    publish(root, 'ack.json', receipt)
    if scenario == 'ack-without-exit':
        time.sleep(2.5)
    worker.join()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
