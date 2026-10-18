"""Separate SIM-only activation entry. This release never starts a native host.

Arguments/stdin/JSON cannot authorize it. The parent channel is intentionally
not activated until Windows containment and private handle ownership exist.
"""

import json
import os
from pathlib import Path
import secrets
import sys


def _run_private_channel(private_reader, private_writer) -> int:
    from execution_kgi_simulator.native.readiness import require_verified_host, revalidate_reviewed_bytes

    require_verified_host()
    revalidate_reviewed_bytes()
    # This contract is exercised with invented secrets only. Actual pipes, PID,
    # Job/token, stdout/stderr and deadline must come from the missing host issuer.
    generation = secrets.token_hex(16)
    private_writer.write(json.dumps({'schema': 'omi.kgi-native-private-ready.v1',
                                    'generation': generation}).encode('ascii') + b'\n')
    private_writer.flush()
    from execution_kgi_simulator.login_probe import read_private_frame
    from execution_kgi_simulator.native.adapter import _login_readback_logout

    credentials = read_private_frame(private_reader, generation)
    try:
        require_verified_host()
        result = _login_readback_logout(credentials)
    finally:
        credentials.clear()
    # Adapter returns no account identifiers, token, raw error or SDK object.
    private_writer.write(json.dumps(result).encode('ascii') + b'\n')
    private_writer.flush()
    return 2  # No live acceptance until broker logout acknowledgement is defined.


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from execution_kgi_simulator.native.readiness import require_verified_host

    control = None
    try:
        if len(sys.argv) != 1:
            raise ValueError('UNEXPECTED_ARGUMENTS')
        require_verified_host()
        # Only a future host with kernel-verified private standard handles may
        # reach this. Preserve control output; permanently suppress SDK/FD noise,
        # including destructors/threads during interpreter shutdown. CWD alone
        # does not isolate SDK logs; G1 must cover copied SDK/native directories.
        control = os.fdopen(os.dup(1), 'wb', buffering=0)
        with open(os.devnull, 'wb') as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
        return _run_private_channel(sys.stdin.buffer, control)
    except Exception:
        result = {'schema': 'omi.kgi-native-activation.v1',
                          'status': 'BLOCKED', 'reasonCodes': ['NATIVE_HOST_ACTIVATION_BLOCKED'],
                          'runtime_origin': 'NOT_CONNECTED', 'credential_values_read': False,
                          'sdk_imported': False, 'broker_calls': 0, 'orders_sent': 0,
                          'login_attempts': 0}
        if control is None:
            print(json.dumps(result))
        else:
            # After admission, never claim zero attempts if an unexpected error
            # crossed the adapter boundary. No retries, no inferred logout.
            control.write(json.dumps({'status': 'UNKNOWN',
                'reasonCodes': ['NATIVE_WORKER_OUTCOME_UNVERIFIED']}).encode('ascii') + b'\n')
        return 2
    finally:
        if control is not None:
            control.close()


if __name__ == '__main__':
    raise SystemExit(main())
