"""OMI-local config bootstrap, executed with OMI .venv (python-dotenv installed).

No broker/application import here. Credentials travel only in the child process
environment, never arguments, files, stdout, stderr, or captured diagnostics.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
KEYS = ("KGI_SUPERPY_PERSON_ID", "KGI_SUPERPY_PASSWORD", "KGI_SUPERPY_TW_ACCOUNT", "KGI_SUPERPY_SIMULATION")


def child_environment(root, environment):
    # Same OMI-local file order and env-over-file precedence as app.config.
    # No backend import or settings initialization; reuse its dotenv parser.
    from dotenv import dotenv_values
    values = {}
    for name in (".env", ".env.runtime"):
        path = root / name
        if path.is_file():
            parsed = dotenv_values(path, encoding="utf-8")
            values.update({key: parsed[key] for key in KEYS if parsed.get(key) is not None})
    values.update({key: environment[key] for key in KEYS if key in environment})
    child = {key: value for key, value in environment.items() if not key.startswith("KGI_SUPERPY_")}
    child.update(values)
    return child


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load existing OMI .env/.env.runtime and start the native stdin runtime")
    parser.add_argument("--connect", action="store_true", help="Explicit native login; never sends an entry without confirm")
    parser.add_argument("--enable-strategy-effects", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--background", action="store_true")
    args = parser.parse_args(argv)
    if not args.connect:
        parser.error("--connect is required; no configuration or credentials loaded")
    if args.probe and args.enable_strategy_effects:
        parser.error("probe forbids strategy effects")
    interpreter = ROOT / ".venv-kgi" / "Scripts" / "python.exe"
    if not interpreter.is_file():
        print('{"status":"BLOCKED","error":"OMI_VENV_KGI_MISSING"}')
        return 2
    try:
        environment = child_environment(ROOT, os.environ)
        command = [str(interpreter), "-B", "-m", "execution_runtime", "native", "--connect"]
        if args.enable_strategy_effects:
            command.append("--enable-strategy-effects")
        if args.probe:
            command.append("--probe")
        if args.background:
            command.append("--persistent")
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startup,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            print('{"status":"STARTING","pid":' + str(process.pid) + ',"acceptance":"UNVERIFIED"}')
            return 0
        # Inherit one stdin/stdout pair; no server, polling, retries or daemon.
        process = subprocess.Popen(command, cwd=ROOT, env=environment)
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The console also delivers Ctrl+C to the child. Let its
                # runtime close/logout finish; never kill it from the bootstrap.
                continue
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('{"status":"BLOCKED","error":"OMI_CONFIG_OR_LAUNCH_FAILED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
