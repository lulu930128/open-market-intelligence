"""Source-only deny policy. No policy installer and no admission authority.

Only a reviewed issuer may eventually translate this into kernel objects. A
serialized plan, vendor signature claim, endpoint, or probe receipt is not one.
"""

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import stat
import struct

# Synthetic binary only. These pins are not SDK/vendor or activation authority.
CANARY_SOURCE_SHA256 = '3de973a9621bf4a1f10c4f1ca4b96e4298533e7c6600a445410e6a826c367852'
CANARY_IMAGE_SHA256 = '6510f4f27fc613a45aeac5a42de6e6961b0cd93d291d5e837833601db703d9f3'
# Only a separately approved, reviewed deployment may enroll (name, exact SID).
# No env/CLI/receipt/config override. No profile has been authorized this cycle.
APPROVED_APPCONTAINER_PROFILE = None
CANARY_IMPORTS = frozenset({'kernel32.dll', 'msvcrt.dll', 'ws2_32.dll'})
NETWORK_CASES = ('tcp4', 'tcp6', 'udp4', 'udp6', 'loopback_tcp4', 'loopback_tcp6',
                 'loopback_udp4', 'loopback_udp6', 'mapped_loopback',
                 'explicit_proxy4', 'explicit_proxy6', 'udp_dns_port')
FILE_CASES = ('outside_read', 'outside_write', 'sdk_write', 'empty_ca_list',
              'logs_write_control', 'sdk_read_control', 'native_cwd_write', 'native_cwd_control')


def local_path(path: Path) -> None:
    """Lexical checks before any IO; handle checks still required by the owner."""
    if type(path) is not type(Path()) or not path.is_absolute():
        raise PolicyRejected('ABSOLUTE_LOCAL_PATH_REQUIRED')
    win = PureWindowsPath(str(path))
    if (win.drive.startswith('\\\\') or '..' in path.parts
            or any(':' in p or p.endswith(('.', ' ')) for p in path.parts[1:])):
        raise PolicyRejected('UNC_DEVICE_ADS_ESCAPE_REJECTED')


def pe_imports(data: bytes) -> tuple[str, ...]:
    """Bounded AMD64 PE import parser. Delay imports are rejected, never ignored."""
    def u16(at):
        if at < 0 or at + 2 > len(data): raise PolicyRejected('PE_BOUNDS')
        return struct.unpack_from('<H', data, at)[0]
    def u32(at):
        if at < 0 or at + 4 > len(data): raise PolicyRejected('PE_BOUNDS')
        return struct.unpack_from('<I', data, at)[0]
    if len(data) < 64 or data[:2] != b'MZ': raise PolicyRejected('PE_REQUIRED')
    pe = u32(60)
    if data[pe:pe + 4] != b'PE\0\0' or u16(pe + 4) != 0x8664:
        raise PolicyRejected('AMD64_PE_REQUIRED')
    optional = pe + 24
    opt_size, count = u16(pe + 20), u16(pe + 6)
    if u16(optional) != 0x20b or opt_size < 240 or not 1 <= count <= 96:
        raise PolicyRejected('PE_OPTIONAL_HEADER_REJECTED')
    if u32(optional + 108) < 14: raise PolicyRejected('PE_DIRECTORIES_MISSING')
    if u32(optional + 112 + 13 * 8) or u32(optional + 116 + 13 * 8):
        raise PolicyRejected('DELAY_IMPORTS_UNREVIEWED')
    sections = optional + opt_size
    def offset(rva, length):
        matches = []
        for i in range(count):
            at = sections + 40 * i
            va, size, raw = u32(at + 12), u32(at + 16), u32(at + 20)
            if va <= rva and rva + length <= va + size and raw + rva - va + length <= len(data):
                matches.append(raw + rva - va)
        if len(matches) != 1: raise PolicyRejected('PE_RVA_REJECTED')
        return matches[0]
    rva, size = u32(optional + 120), u32(optional + 124)
    if not rva or not 20 <= size <= 65536: raise PolicyRejected('PE_IMPORT_TABLE_REQUIRED')
    names = []
    for i in range(min(size // 20, 128)):
        at = offset(rva + i * 20, 20)
        if data[at:at + 20] == b'\0' * 20: return tuple(names)
        name_rva = u32(at + 12)
        raw = bytearray()
        for j in range(128):
            char = data[offset(name_rva + j, 1)]
            if not char: break
            raw.append(char)
        else: raise PolicyRejected('PE_IMPORT_NAME_TOO_LONG')
        try: name = raw.decode('ascii').lower()
        except UnicodeError as error: raise PolicyRejected('PE_IMPORT_NAME_REJECTED') from error
        if (not name.endswith('.dll') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_.' for c in name)
                or '..' in name):
            raise PolicyRejected('UNSAFE_DEPENDENCY_NAME')
        names.append(name)
    raise PolicyRejected('PE_IMPORT_TERMINATOR_MISSING')


def classify_canary(payload: object, pid: int, exit_code: int) -> dict:
    """A receipt never authorizes G1/G2/G3; caller must separately verify OS token."""
    unknown = {'network': 'UNVERIFIED', 'filesystem': 'UNVERIFIED'}
    if (type(payload) is not dict or set(payload) != {'schema', 'pid', 'network_errors', 'file_errors'}
            or payload['schema'] != 'omi.kgi-synthetic-child.v1'
            or type(payload['pid']) is not int or payload['pid'] != pid):
        return unknown
    network, files = payload['network_errors'], payload['file_errors']
    if (type(network) is not list or len(network) != len(NETWORK_CASES)
            or type(files) is not list or len(files) != len(FILE_CASES)
            or any(type(v) is not int for v in network + files)):
        return unknown
    expected = [5, 5, 5, 5, 0, 0, 5, 0]
    # Success with wrong exit, missing controls, timeout, refusal, unreachable and
    # unsupported family are never access-denied proof.
    consistent_exit = exit_code == (0 if network == [10013] * len(NETWORK_CASES) and files == expected else 3)
    return {
        'network': ('OS_OBSERVED_SYNTHETIC_DENIAL' if consistent_exit and all(v == 10013 for v in network) else 'UNVERIFIED'),
        'filesystem': ('OS_OBSERVED_SYNTHETIC_DENIAL' if consistent_exit and files == expected else 'UNVERIFIED'),
        'network_cases': dict(zip(NETWORK_CASES, network)),
        'file_cases': dict(zip(FILE_CASES, files)),
        'scope': 'FIXED_SYNTHETIC_CASES_ONLY_NOT_GENERAL_DEPENDENCY_OR_SECRET_PROOF',
    }


class PolicyRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DenyFilter:
    layer: str
    action: str = 'BLOCK'
    protocols: str = 'ALL'
    destinations: str = 'ALL_INCLUDING_LOOPBACK'


@dataclass(frozen=True, slots=True)
class DenyAllPlan:
    """A construction specification, deliberately incapable of granting access."""
    schema: str = 'omi.kgi-host-deny-all.v1'
    filters: tuple = (
        DenyFilter('FWPM_LAYER_ALE_AUTH_CONNECT_V4'),
        DenyFilter('FWPM_LAYER_ALE_AUTH_CONNECT_V6'),
        DenyFilter('FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4'),
        DenyFilter('FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V6'),
    )
    permits: tuple = ()
    dns: str = 'DENY'
    proxy_redirect_fallback: str = 'DENY'
    descendants: str = 'DENY_CREATION'
    evidence: str = 'SOURCE_ONLY'
    subject: str = 'OWNED_CHILD_KERNEL_IDENTITY_REQUIRED'
    lifetime: str = 'OWNED_DYNAMIC_SESSION_REQUIRED'
    global_policy: str = 'FORBIDDEN'


def validate_deny_all(plan: DenyAllPlan) -> None:
    # Exact types prevent truthy booleans, dicts, subclasses and equality hooks.
    if type(plan) is not DenyAllPlan or type(plan.filters) is not tuple:
        raise PolicyRejected('DENY_ALL_SCHEMA_REQUIRED')
    if any(type(f) is not DenyFilter for f in plan.filters):
        raise PolicyRejected('DENY_ALL_FILTER_REQUIRED')
    for item in plan.filters:
        if any(type(v) is not str for v in (item.layer, item.action, item.protocols, item.destinations)):
            raise PolicyRejected('DENY_ALL_FIELD_TYPE')
    if (type(plan.permits) is not tuple or plan.permits
            or any(type(v) is not str for v in (plan.schema, plan.dns,
                plan.proxy_redirect_fallback, plan.descendants, plan.evidence,
                plan.subject, plan.lifetime, plan.global_policy))
            or plan != DenyAllPlan()):
        raise PolicyRejected('DENY_ALL_MODIFICATION_REJECTED')


def reject_vendor_manifest(manifest: object) -> None:
    """No vendor trust root/verified destination list exists. Parse nothing."""
    raise PolicyRejected('VENDOR_SIGNATURE_AND_TEST_DESTINATIONS_UNVERIFIED')


def validate_workspace(root: Path) -> dict:
    """Validate an existing empty layout, without reading SDK/log/CA contents.

    This is static validation, NOT a filesystem sandbox or TOCTOU-safe lease.
    Never creates directories/ACLs, copies SDK bytes, or opens a CA file.
    """
    if type(root) is not type(Path()) or not root.is_absolute():
        raise PolicyRejected('LOCAL_ABSOLUTE_WORKSPACE_REQUIRED')
    windows = PureWindowsPath(str(root))
    if (windows.drive.startswith('\\\\') or '..' in root.parts
            or any(':' in part for part in root.parts[1:])):
        raise PolicyRejected('WORKSPACE_DEVICE_UNC_OR_STREAM_REJECTED')
    for directory in (root, root / 'sdk', root / 'logs', root / 'ca'):
        for part in (directory, *directory.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise PolicyRejected('WORKSPACE_REPARSE_REJECTED')
            if not stat.S_ISDIR(info.st_mode):
                raise PolicyRejected('WORKSPACE_DIRECTORY_REQUIRED')
        if directory != root and next(directory.iterdir(), None) is not None:
            raise PolicyRejected('WORKSPACE_MUST_BE_EMPTY_NO_SECRET_INSPECTION')
    if {p.name for p in root.iterdir()} != {'sdk', 'logs', 'ca'}:
        raise PolicyRejected('WORKSPACE_LAYOUT_REJECTED')
    return {'evidence': 'SOURCE_ONLY', 'filesystem_isolation': 'NOT_INSTALLED',
            'sdk_copy': 'NOT_CREATED', 'ca_access': 'DENY_REQUIRED',
            'sdk_log_cwd_escape': 'KERNEL_BOUNDARY_REQUIRED'}


def policy_status() -> dict:
    validate_deny_all(DenyAllPlan())
    return {'schema': 'omi.kgi-host-policy.v1', 'evidence': 'SOURCE_ONLY',
            'network_policy': 'DENY_ALL_CONSTRUCTION_VALIDATED',
            'kernel_filters': 'NOT_INSTALLED_BY_THIS_IMPLEMENTATION',
            'filesystem_policy': 'NOT_INSTALLED_BY_THIS_IMPLEMENTATION',
            'vendor_trust_root': 'NOT_PROVISIONED', 'activation_authority': False}
