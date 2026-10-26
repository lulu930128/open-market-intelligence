"""Disposable transport only: no OMI import, DB, listener or provider."""
import json
import subprocess
import sys
import time

mode = sys.argv[1]
child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.readline()"], stdin=subprocess.PIPE)
print(child.pid, flush=True)
command = json.loads(sys.stdin.readline())
if mode == "graceful":
    child.communicate(b"exit\n", timeout=2)
    command.update(state="SUCCEEDED_PRODUCTION", reason="LIFESPAN_AND_EXACT_EXIT", no_respawn="true")
    print(json.dumps(command), flush=True)
elif mode == "rearmed":
    command.update(state="PREFLIGHT_REARMED", rearmed="true", stage="JOB_QUIESCENCE", stop_not_sent="true")
    print(json.dumps(command), flush=True)
    time.sleep(20)
elif mode == "child-exited":
    child.communicate(b"exit\n", timeout=2)
    time.sleep(20)
elif mode == "runner-exited":
    # Child holds its own stdin pipe; closing ours makes it naturally exit, so
    # this mode tests an already-exited pair with no graceful ACK.
    sys.exit(79)
else:
    time.sleep(20)
