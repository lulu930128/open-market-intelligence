"""Read-only REAL_SIM qualification seam; deliberately no broker connector.

This is source evidence, never an execution EvidenceRef or a runtime attestation.
No credential, session, proof file, SDK object or callback can be supplied here.
M1 admission/reducer and M2A transaction/outbox remain the only future owners.
"""

from datetime import datetime
from pathlib import Path
import struct
import sys

from execution_kgi_simulator.gates import preflight
from execution_kgi_simulator.inspection import inspect_sdk, inspect_connection_surface
from execution_kgi_simulator.login_probe import credential_owner_reference
from execution_kgi_simulator.native.readiness import readiness


def qualify(root: Path, presence: dict, now: datetime, *, mode: str) -> dict:
    """Inspect local installed source only, including for RealSimProbe.

    A future native connector requires a reviewed source change and independent
    runtime proof, not a replacement object, configuration flag or JSON claim.
    """
    if mode not in ('RealSimPreflight', 'RealSimProbe'):
        raise ValueError('REAL_SIM_MODE_INVALID')
    report = preflight(inspect_sdk(root), presence, now, mode=mode)
    report.update({
        'schema': 'omi.kgi-real-sim.qualification.v1',
        'target': 'REAL_SIM',
        'origin': 'SOURCE_INSPECTION',
        'runtime_origin': 'NOT_CONNECTED',
        'broker_connected': False,
        'native_probe_attempts': 0,
        'cancel_requests': 0,
        'external_response': 'NOT_REQUESTED',
        'connector': 'NOT_IMPLEMENTED',
        'sdk_runtime_interpreter': 'UNVERIFIED',
        'credential_ingress': credential_owner_reference().ingress,
        'credential_scope': 'CANONICAL_SETTINGS_SIM_SESSION_ONLY',
        'login_only_plumbing': 'OFFICIAL_ADAPTER_SOURCE_ACTIVATION_BLOCKED',
        'login_only_connector': 'KGISUPERPY_2_1_0_SIM_ONLY_SOURCE',
        'native_readiness': readiness(),
        'session_reuse': 'FORBIDDEN',
        'execution_ingress': 'BLOCKED',
        'worker': {'python': '.'.join(map(str, sys.version_info[:3])),
                   'pointer_bits': struct.calcsize('P') * 8,
                   'isolated': bool(sys.flags.isolated),
                   'no_site': bool(sys.flags.no_site),
                   'no_bytecode': bool(sys.flags.dont_write_bytecode)},
        'connection_source': inspect_connection_surface(root),
    })
    # These remain unconditional. Source matches or presence are not proof.
    gaps = [
        'SECURE_SIM_CREDENTIAL_INGRESS_MISSING',
        'LOGIN_MARKET_INITIALIZATION_CONFINEMENT_UNVERIFIED',
        'PERSISTED_PROBE_INTENT_NOT_IMPLEMENTED',
        'REAL_SIM_ORIGIN_INGRESS_NOT_IMPLEMENTED',
        'BROKER_CALLBACK_FINALITY_UNVERIFIED',
    ]
    report['probe']['reasonCodes'].extend(gaps)
    report['order']['reasonCodes'].extend(gaps)
    return report
