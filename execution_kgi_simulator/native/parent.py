"""Canonical backend-context entry for future G2; no secret access today.

Separate from production quote processes. The suspended OS probe never feeds
credentials: its pipes are owned and destroyed without writing a byte. A future
active channel requires a reviewed issuer and bounded IPC, not a report dict.
"""

from pathlib import Path
import json
import sys


def _backend_context() -> None:
    root = Path(__file__).resolve().parents[2]
    # Isolated CLI supplies only these source roots; no PYTHONPATH/env fallback.
    # Do not import app.config while establishing context (it reads Settings).
    if 'app' in sys.modules or 'app.config' in sys.modules:
        raise RuntimeError('PARENT_MUST_START_IN_COLD_BACKEND_CONTEXT')
    for path in (root, root / 'backend'):
        for part in (path, *path.parents):
            if getattr(part.lstat(), 'st_file_attributes', 0) & 0x400:
                raise RuntimeError('PARENT_SOURCE_REPARSE_REJECTED')
    sys.path[:0] = [str(root / 'backend'), str(root)]


def run_login_only() -> None:
    from execution_kgi_simulator.native.readiness import require_verified_host

    # No caller-supplied proof or stream; no Settings/SDK import before admission.
    require_verified_host()
    # Deliberate second stop. Implementing the issuer must not accidentally
    # activate an unbounded pipe exchange or reuse a suspended probe child.
    raise RuntimeError('G2_ACTIVE_PRIVATE_CHANNEL_NOT_IMPLEMENTED')


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ('preflight', 'suspended-probe', 'login-only',
                                              'sandbox-preflight', 'sandbox-stage', 'sandbox-probe'):
        print(json.dumps({'status': 'BLOCKED', 'reasonCodes': ['UNEXPECTED_ARGUMENTS']}))
        return 2
    try:
        if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
            raise RuntimeError('ISOLATED_NO_SITE_NO_BYTECODE_REQUIRED')
        _backend_context()
        from execution_kgi_simulator.native.host_policy import policy_status
        from execution_kgi_simulator.native.readiness import require_verified_host

        result = {'schema': 'omi.kgi-host-parent.v1', 'status': 'BLOCKED',
                  'gates': {'G1': 'BLOCKED', 'G2': 'BLOCKED', 'G3': 'BLOCKED'},
                  'policy': policy_status(), 'credential_values_read': False,
                  'sdk_imported': False, 'broker_calls': 0, 'orders_sent': 0,
                  'backend_context': 'FIXED_SOURCE_ROOTS_NO_SETTINGS_IMPORT',
                  'reasonCodes': ['OFFICIAL_TEST_DESTINATION_ATTESTATION_MISSING',
                      'KERNEL_NETWORK_FILESYSTEM_ISOLATION_NOT_INSTALLED',
                      'G2_ACTIVE_PRIVATE_CHANNEL_NOT_IMPLEMENTED']}
        if sys.argv[1] == 'suspended-probe':
            from execution_kgi_simulator.native.windows_host import suspended_denial_probe
            result['host_probe'] = suspended_denial_probe()
        elif sys.argv[1] == 'sandbox-preflight':
            from execution_kgi_simulator.native.windows_host import sandbox_capabilities
            result['sandbox'] = sandbox_capabilities()
        elif sys.argv[1] in ('sandbox-stage', 'sandbox-probe'):
            from execution_kgi_simulator.native.windows_host import sandbox_probe
            result['sandbox'] = sandbox_probe(stage_only=sys.argv[1] == 'sandbox-stage')
        elif sys.argv[1] == 'login-only':
            run_login_only()
        # Probe/plan receipts can never be exchanged for authority.
        try:
            require_verified_host()
        except RuntimeError:
            pass
        print(json.dumps(result))
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'reasonCodes': ['NATIVE_HOST_ACTIVATION_BLOCKED'],
                          'credential_values_read': False, 'sdk_imported': False,
                          'broker_calls': 0, 'orders_sent': 0}))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
