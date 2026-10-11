"""Ephemeral fictional identities; explicitly NOT production authentication."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import hmac
import secrets
from threading import RLock

from execution.validation import identifier, instant


class HttpRejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


@dataclass(frozen=True)
class Session:
    principal: str
    account: str
    issued_at: object
    expires_at: object
    csrf: str = field(repr=False)


@dataclass(frozen=True)
class TestCredentials:
    session: str = field(repr=False)
    csrf: str = field(repr=False)


class SyntheticAuth:
    """One direct test issuer, shared across reconstructed app instances.

    The lock linearizes revoke/auth/command across concurrent test sessions.
    Rate counters and sessions are auth state, never order/business state.
    A new issuer invalidates every old session and order capability.
    """

    def __init__(self, *, origins, requests_per_minute=120, max_sessions=32):
        if not origins or any(not o.startswith('https://') or o.endswith('/') for o in origins):
            raise ValueError('EXPLICIT_HTTPS_ORIGINS_REQUIRED')
        if not 1 <= requests_per_minute <= 1000 or not 1 <= max_sessions <= 128:
            raise ValueError('INVALID_AUTH_LIMIT')
        self.origins = frozenset(origins)
        self.requests_per_minute = requests_per_minute
        self.max_sessions = max_sessions
        self._key = secrets.token_bytes(32)
        self._sessions = {}
        self._rates = {}
        self._lock = RLock()

    def issue(self, principal, account, *, now, ttl=timedelta(minutes=5)):
        instant(now)
        for value in (principal, account):
            identifier(value)
            if not value.startswith('synthetic-'):
                raise ValueError('SYNTHETIC_IDENTITY_REQUIRED')
        if not timedelta(0) < ttl <= timedelta(minutes=5):
            raise ValueError('INVALID_SESSION_TTL')
        with self._lock:
            for key, session in tuple(self._sessions.items()):
                if now >= session.expires_at:
                    self._sessions.pop(key)
                    self._rates.pop(key, None)
            if len(self._sessions) >= self.max_sessions:
                raise ValueError('SESSION_CAPACITY')
            token, csrf = secrets.token_hex(32), secrets.token_hex(32)
            self._sessions[self._hash(token)] = Session(principal, account, now, now + ttl, csrf)
            return TestCredentials(token, csrf)

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    def revoke(self, credentials):
        with self._lock:
            key = self._hash(credentials.session)
            self._sessions.pop(key, None)
            self._rates.pop(key, None)

    @contextmanager
    def authorize(self, headers, *, clock, mutation):
        with self._lock:
            now = clock()
            instant(now)
            authorization = headers.get('authorization', '')
            token = authorization.removeprefix('Bearer ')
            if not authorization.startswith('Bearer ') or len(token) != 64 or not token.isascii():
                raise HttpRejected(401, 'SESSION_REQUIRED')
            key = self._hash(token)
            session = self._sessions.get(key)
            if session is None or not session.issued_at <= now < session.expires_at:
                raise HttpRejected(401, 'SESSION_INVALID')
            if headers.get('origin') not in self.origins:
                raise HttpRejected(403, 'ORIGIN_DENIED')
            if mutation and not hmac.compare_digest(headers.get('x-csrf-token', '').encode(), session.csrf.encode()):
                raise HttpRejected(403, 'CSRF_DENIED')
            start, count = self._rates.get(key, (now, 0))
            if now < start:
                raise HttpRejected(401, 'SESSION_CLOCK_REGRESSION')
            if now - start >= timedelta(minutes=1):
                start, count = now, 0
            if count >= self.requests_per_minute:
                raise HttpRejected(429, 'RATE_LIMITED')
            self._rates[key] = (start, count + 1)
            yield session, now

    def _binding(self, label, session, value):
        message = '\n'.join((label, session.principal, session.account, value)).encode('ascii')
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def request_id(self, session, client_request_id):
        # Same-account different principals cannot retrieve each other's challenge.
        return self._binding('request-v1', session, client_request_id)

    def order_capability(self, session, preview_id):
        return self._binding('order-v1', session, preview_id)

    def require_order(self, session, preview_id, supplied):
        identifier(preview_id)
        expected = self.order_capability(session, preview_id)
        if not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise HttpRejected(403, 'ORDER_ACCESS_DENIED')
