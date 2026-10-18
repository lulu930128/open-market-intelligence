"""Login-only lifecycle building blocks, exercised ONLY by the offline harness.

There is no native adapter or authorization issuer. The shipping worker cannot
dispatch here. A successful fixture is always LOCAL_MOCK, never broker proof.
This owns no execution state, account repository, transaction or order method.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import hmac
import json
import math
import secrets
import time
from typing import Protocol


CREDENTIAL_OWNER = 'app.config.Settings'
CREDENTIAL_FIELDS = ('kgi_superpy_person_id', 'kgi_superpy_password')
MAX_FRAME = 4096


@dataclass(frozen=True, slots=True)
class CredentialOwnerReference:
    """Fixed metadata, not a credential provider or caller-selected source."""
    owner: str = field(default=CREDENTIAL_OWNER, init=False)
    fields: tuple[str, str] = field(default=CREDENTIAL_FIELDS, init=False)
    target: str = field(default='SIM', init=False)
    ingress: str = field(default='BLOCKED_BEFORE_SETTINGS_READ', init=False)


def credential_owner_reference() -> CredentialOwnerReference:
    return CredentialOwnerReference()


class Phase(str, Enum):
    PREFLIGHT = 'PREFLIGHT'
    AUTHORIZED = 'TEST_AUTHORIZED'
    LOGIN = 'LOGIN'
    READBACK = 'READBACK'
    LOGOUT = 'LOGOUT'
    CLOSED = 'CLOSED'


class Outcome(str, Enum):
    ACCEPTED = 'LOCAL_MOCK_ACCEPTED'
    REJECTED = 'REJECTED'
    UNKNOWN = 'UNKNOWN'
    BLOCKED = 'BLOCKED'


class Reason(str, Enum):
    COMPLETE = 'FIXTURE_LOGIN_READBACK_COMPLETE'
    PREFLIGHT = 'TEST_PREFLIGHT_DENIED'
    PORT = 'CLOSED_FIXTURE_PORT_REQUIRED'
    REJECTED = 'LOGIN_REJECTED'
    MALFORMED = 'LOGIN_READBACK_UNVERIFIED'
    TARGET = 'NON_SIM_RESPONSE'
    FENCED = 'SESSION_FENCED'
    TIMEOUT = 'LOGIN_ONLY_TIMEOUT'
    CANCELLED = 'LOGIN_ONLY_CANCELLED'
    FAILURE = 'LOGIN_ONLY_FAILURE'
    LOGOUT = 'LOGOUT_UNVERIFIED'


@dataclass(repr=False, slots=True)
class Credentials:
    """Ephemeral pipe payload; never a new Settings source or disk format."""
    person_id: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self):
        return 'Credentials(<redacted>)'

    def clear(self):
        # Release references. Python/SDK strings cannot promise memory zeroing.
        self.person_id = ''
        self.password = ''


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('INVALID_PRIVATE_FRAME')
        result[key] = value
    return result


def read_private_frame(stream, expected_generation: str) -> Credentials:
    """One bounded frame, exact keys and EOF. Not used by the shipping worker.

    No target/flag/proof/path/SDK/executable is accepted. Only a future attested
    parent can read Settings and create this pipe; this release tests invented
    values and has no live credential reader.
    """
    try:
        raw = stream.read(MAX_FRAME + 1)
        if type(raw) is not bytes or len(raw) > MAX_FRAME:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != {'generation', 'person_id', 'password'}:
            raise ValueError
        if value['generation'] != expected_generation or not valid_generation(expected_generation):
            raise ValueError
        for key in ('person_id', 'password'):
            item = value[key]
            if type(item) is not str or not 1 <= len(item) <= 512 or any(ord(c) < 32 for c in item):
                raise ValueError
        return Credentials(value['person_id'], value['password'])
    except Exception:
        raise ValueError('INVALID_PRIVATE_FRAME') from None


def valid_generation(value):
    return type(value) is str and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def encode_private_frame(credentials: Credentials, generation: str) -> bytes:
    """Ephemeral parent-to-child frame. Never argv/env/log/a stored secret source.

    This codec does not read Settings or grant authority. Only invented values
    exercise it until an independently attested parent credential reader exists.
    """
    import io
    try:
        if type(credentials) is not Credentials:
            raise ValueError
        raw = json.dumps({'generation': generation, 'person_id': credentials.person_id,
                          'password': credentials.password}, ensure_ascii=True).encode('ascii')
        checked = read_private_frame(io.BytesIO(raw), generation)
        checked.clear()
        return raw
    except Exception:
        raise ValueError('INVALID_PRIVATE_FRAME') from None


@dataclass(frozen=True, slots=True)
class Receipt:
    """Opaque per-attempt identity, never raw broker account/person/session IDs."""
    receipt_id: str
    identity_digest: str
    broker: str = 'KGI'
    target: str = 'SIM'
    origin: str = 'LOCAL_MOCK'


@dataclass(frozen=True, slots=True)
class ProbeResult:
    outcome: Outcome
    reason: Reason
    phases: tuple[Phase, ...]
    generation: str
    receipt: Receipt | None = None
    logout_confirmed: bool = False

    def public(self):
        # Construct an allowlisted document; never serialize SDK objects/errors.
        return {'schema': 'omi.kgi-sim.login-only.fixture.v1',
                'status': self.outcome.value, 'reasonCodes': [self.reason.value],
                'origin': 'LOCAL_MOCK', 'runtime_origin': 'NOT_CONNECTED',
                'target': 'SIM', 'generation': self.generation,
                'phases': [p.value for p in self.phases],
                'receipt': None if self.receipt is None else {
                    'receipt_id': self.receipt.receipt_id,
                    'identity_digest': self.receipt.identity_digest,
                    'broker': 'KGI', 'target': 'SIM', 'origin': 'LOCAL_MOCK'},
                'logout_confirmed': self.logout_confirmed,
                'broker_connected': False, 'broker_calls': 0, 'orders_sent': 0,
                'sdk_imported': False, 'real_sim': 'BLOCKED'}


class LoginOnlyPort(Protocol):
    """Only a login/readback/logout view, never expose the returned SDK API."""
    def login(self, person_id: str, password: str, *, simulation: bool): ...
    def readback(self): ...
    def logout(self): ...


class _Stop(Exception):
    def __init__(self, outcome, reason):
        self.outcome, self.reason = outcome, reason


def exercise_fixture(port: LoginOnlyPort, credentials: Credentials, *, generation: str,
                     timeout_seconds: float = 2.0, cancelled=lambda: False,
                     test_preflight=False) -> ProbeResult:
    """Test-only dependency seam. Cannot issue any REAL_SIM authorization.

    Hard hangs require an owned-process supervisor. Deadlines here catch late
    returns, including teardown. No callback is registered and no retry occurs.
    Native adapter, Settings loading and OS confinement are deliberately absent.
    """
    if (not valid_generation(generation) or type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 10):
        credentials.clear()
        raise ValueError('INVALID_FIXTURE_SESSION')
    phases = [Phase.PREFLIGHT]
    outcome, reason, receipt = Outcome.BLOCKED, Reason.PREFLIGHT, None
    attempted, logout_ok = False, False
    deadline = time.monotonic() + timeout_seconds
    identity_key = secrets.token_bytes(32)

    def check():
        if cancelled():
            raise _Stop(Outcome.UNKNOWN, Reason.CANCELLED)
        if time.monotonic() >= deadline:
            raise _Stop(Outcome.UNKNOWN, Reason.TIMEOUT)

    def identity(value):
        check()
        if type(value) is not dict:
            raise _Stop(Outcome.UNKNOWN, Reason.MALFORMED)
        if value.get('generation') != generation:
            raise _Stop(Outcome.UNKNOWN, Reason.FENCED)
        if value.get('target') != 'SIM':
            raise _Stop(Outcome.UNKNOWN, Reason.TARGET)
        if value.get('accepted') is False:
            raise _Stop(Outcome.REJECTED, Reason.REJECTED)
        if value.get('accepted') is not True or value.get('broker') != 'KGI':
            raise _Stop(Outcome.UNKNOWN, Reason.MALFORMED)
        if value.get('person_id') != credentials.person_id:
            raise _Stop(Outcome.UNKNOWN, Reason.MALFORMED)
        account = value.get('account')
        if type(account) is not str or not account.strip() or len(account) > 256:
            raise _Stop(Outcome.UNKNOWN, Reason.MALFORMED)
        data = json.dumps([credentials.person_id, account], ensure_ascii=True).encode()
        return hmac.new(identity_key, data, hashlib.sha256).hexdigest()

    try:
        if test_preflight is not True:
            raise _Stop(outcome, reason)
        # This cold dependency is reachable ONLY by the offline test seam.
        # A caller-supplied Protocol implementation/SDK cannot activate IO.
        # The shipping worker is separately forbidden from calling this seam.
        from execution_kgi_simulator.tests.login_fixture_worker import FakeLoginPort
        if type(port) is not FakeLoginPort:
            raise _Stop(Outcome.BLOCKED, Reason.PORT)
        check()
        phases.extend((Phase.AUTHORIZED, Phase.LOGIN))
        attempted = True
        first = identity(port.login(credentials.person_id, credentials.password, simulation=True))
        phases.append(Phase.READBACK)
        second = identity(port.readback())
        if not hmac.compare_digest(first, second):
            raise _Stop(Outcome.UNKNOWN, Reason.MALFORMED)
        receipt = Receipt(secrets.token_hex(16), first)
        outcome, reason = Outcome.ACCEPTED, Reason.COMPLETE
    except _Stop as exc:
        outcome, reason = exc.outcome, exc.reason
    except TimeoutError:
        outcome, reason = Outcome.UNKNOWN, Reason.TIMEOUT
    except Exception:
        # Never stringify, log, chain or return a native exception.
        outcome, reason = Outcome.UNKNOWN, Reason.FAILURE
    finally:
        if attempted:
            phases.append(Phase.LOGOUT)
            try:
                logout_ok = port.logout() is True
                check()
                if not logout_ok:
                    outcome, reason = Outcome.UNKNOWN, Reason.LOGOUT
            except _Stop as exc:
                outcome, reason = exc.outcome, exc.reason
            except Exception:
                outcome, reason = Outcome.UNKNOWN, Reason.LOGOUT
        credentials.clear()
        phases.append(Phase.CLOSED)
    if outcome is not Outcome.ACCEPTED:
        receipt = None
    return ProbeResult(outcome, reason, tuple(phases), generation, receipt, logout_ok)
