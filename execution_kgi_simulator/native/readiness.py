"""Independent fixed-path G1 checker; observations are never launch authority.

No input proof/host/flag and no import of Settings, SDK or Windows native code.
The reviewed digest establishes local integrity only, NOT vendor authenticity.
Missing enforcement cannot be repaired by a JSON receipt or environment value.
"""

from hashlib import sha256
from pathlib import Path
import struct

from execution_kgi_simulator.inspection import _source_path, inspect_connection_surface


ROOT = Path(__file__).resolve().parents[2]
SDK_PREFIX = '.venv-kgi/Lib/site-packages/kgisuperpy/'
REVIEWED_SHA256 = (
    ('main.py', 'f7498639e825770e640bb1e2efea7afaae844fe4d689715b8d6d8df5c9c1082c'),
    ('CA.py', 'f62898cfcd8bd395979bc6d16be72ccb224cd9f568c8bf1740b7b7243e86fdc6'),
    ('pushClient/pyTradeCom.py', '010c50c53c1254a38f0b2064b30ff70b3552a3abbf31954e865af24290a8c28b'),
    ('url.cp312-win_amd64.pyd', 'b0f0e7f67db0244f9d8c91e29cb84530e5815bfa6f0169cb1ff9608146213e1e'),
    ('pushClient/tradecom_windows_bridge64.dll', 'ac899ec69a5f359eac9f637ec79900af257095391365508f7d5887718fc91097'),
)
# Intentionally empty: only vendor-authenticated TEST destinations may be reviewed
# into source. Binary strings / DNS / simulation=True cannot populate this set.
OFFICIAL_TEST_DESTINATIONS = ()
MAX_FILE_BYTES = 32 * 1024 * 1024


class ActivationBlocked(RuntimeError):
    def __init__(self):
        super().__init__('NATIVE_HOST_ACTIVATION_BLOCKED')


def _binary_observation(data: bytes) -> dict:
    """Bounded PE header and named-marker inspection, without loader execution."""
    machine = 'UNKNOWN'
    if len(data) >= 64 and data[:2] == b'MZ':
        offset = struct.unpack_from('<I', data, 60)[0]
        if offset <= len(data) - 26 and data[offset:offset + 4] == b'PE\0\0':
            value = struct.unpack_from('<H', data, offset + 4)[0]
            magic = struct.unpack_from('<H', data, offset + 24)[0]
            if value == 0x8664 and magic == 0x20B:
                machine = 'AMD64_PE32_PLUS'
    markers = ('AutoRefresh', 'host', 'simulation', 'requests', 'token',
               'pyTradeCom_Connect', 'pyTradeCom_Login', 'pyTradeCom_Logout',
               'pyTradeCom_GetAccounts', 'SetCA_PFX', 'SetCA_PW', 'WINHTTP', 'WS2_32')
    return {'format': machine,
            'named_markers': {name: name.lower().encode() in data.lower() for name in markers},
            'code_executed': False, 'behavior_verified': False}


def _inspect_files() -> list[dict]:
    observations = []
    for relative, expected in REVIEWED_SHA256:
        item = {'path': relative, 'integrity': 'UNVERIFIED'}
        try:
            path = _source_path(ROOT, SDK_PREFIX + relative)
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                item['reason'] = 'SDK_FILE_TOO_LARGE'
            else:
                item['sha256'] = sha256(data).hexdigest()
                item['integrity'] = ('MATCHES_REVIEWED_LOCAL_BYTES'
                                     if item['sha256'] == expected else 'DRIFT')
                if relative.endswith(('.pyd', '.dll')):
                    item['binary'] = _binary_observation(data)
        except FileNotFoundError:
            item['reason'] = 'SDK_FILE_MISSING'
        except PermissionError:
            item['reason'] = 'SDK_FILE_ACCESS_DENIED'
        except (OSError, ValueError):
            item['reason'] = 'SDK_FILE_UNSAFE_OR_UNREADABLE'
        observations.append(item)
    return observations


def readiness() -> dict:
    """Safe to call from source CLI; never reads secrets or opens a native host."""
    files = _inspect_files()
    concerns = {}
    try:
        concerns = inspect_connection_surface(ROOT)['review_locations']
    except (OSError, ValueError, SyntaxError, UnicodeError):
        concerns = {'SOURCE_UNREADABLE': []}
    blockers = [
        'OFFICIAL_TEST_DESTINATION_ATTESTATION_MISSING',
        'COMPILED_AUTOREFRESH_EGRESS_UNVERIFIED',
        'OWNED_WINDOWS_CONTAINMENT_ENFORCER_NOT_IMPLEMENTED',
        'KERNEL_NETWORK_FILESYSTEM_ISOLATION_NOT_INSTALLED',
        'G2_ACTIVE_PRIVATE_CHANNEL_NOT_IMPLEMENTED',
        'NATIVE_IPV4_IPV6_REDIRECT_FALLBACK_DENY_UNVERIFIED',
        'SDK_LOG_CA_FILESYSTEM_ISOLATION_UNVERIFIED',
        'OWNED_SUSPENDED_CHILD_JOB_TOKEN_HANDLES_UNVERIFIED',
        'SETTINGS_PRIVATE_CHANNEL_NOT_ACTIVATED',
        'SIM_ENTITLEMENT_AND_SESSION_COEXISTENCE_UNVERIFIED',
        'NATIVE_LOGOUT_ACK_CONTRACT_UNVERIFIED',
    ]
    if any(item['integrity'] != 'MATCHES_REVIEWED_LOCAL_BYTES' for item in files):
        blockers.insert(0, 'REVIEWED_SDK_BYTES_UNAVAILABLE_OR_CHANGED')
    return {
        'schema': 'omi.kgi-native-readiness.v1', 'status': 'BLOCKED',
        'origin': 'SOURCE_INSPECTION', 'runtime_origin': 'NOT_CONNECTED',
        'target': 'OFFICIAL_SIM_ONLY', 'reasonCodes': blockers,
        'files': files, 'review_locations': concerns,
        'official_target': {'status': 'UNVERIFIED', 'pinned_destinations': 0,
                            'caller_target_accepted': False},
        'containment': {
            'status': 'NOT_IMPLEMENTED', 'owned_child': 'NOT_CREATED',
            'network': 'UNVERIFIED', 'filesystem': 'UNVERIFIED',
            'ca_access': 'UNVERIFIED', 'native_output': 'UNVERIFIED',
            'python_audit_hook_is_native_sandbox': False,
        },
        'gates': {'G1': 'BLOCKED', 'G2': 'BLOCKED', 'G3': 'BLOCKED'},
        'source_implementation': 'READINESS_REAL_ADAPTER_PRIVATE_PROTOCOL_IMPLEMENTED',
        'host_building_blocks': {'suspended_lifecycle': 'SOURCE_IMPLEMENTED_OS_PROBE_REQUIRED',
            'deny_all_network_contract': 'SOURCE_ONLY_NOT_INSTALLED',
            'parent': 'BACKEND_CONTEXT_ENTRY_NO_ACTIVE_CHANNEL',
            'receipt_is_authority': False},
        'credential_owner': 'app.config.Settings',
        'credential_values_read': False, 'sdk_imported': False,
        'login_attempts': 0, 'broker_calls': 0, 'orders_sent': 0,
        'cancel_requests': 0, 'native_probe_attempts': 0,
    }


def require_verified_host() -> None:
    """Non-issuing activation boundary, deliberately independent of reports.

    Even a tampered readiness dict saying ALL VERIFIED cannot unlock this.
    A future implementation needs kernel-query-backed, one-use live authority
    bound to child creation time, Job/token, private handles, image/dependencies,
    vendor target policy and expiry; revalidate immediately before secret read
    AND in the child before SDK import. No such enforcer exists in this release.
    """
    raise ActivationBlocked()


def revalidate_reviewed_bytes() -> None:
    """Secondary drift check, not a substitute for locked images or containment."""
    if any(item['integrity'] != 'MATCHES_REVIEWED_LOCAL_BYTES' for item in _inspect_files()):
        raise ActivationBlocked()
