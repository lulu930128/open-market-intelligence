"""Factory-only ASGI HTTP boundary; no framework singleton, lifecycle or listener."""

import asyncio
import json

from execution.contracts import Confirmation, ExecutionRejected
from execution_simulation import SimulationApplication
from .contracts import decode, domain_http_status, draft_from_wire, envelope, exact_fields
from .policy import SyntheticFixturePolicy
from .security import HttpRejected, SyntheticAuth


PREFIX = '/test-execution/v1'
MAX_BODY = 8192
MAX_HEADERS = 8192


def build_test_app(sandbox, server_fake_auth, synthetic_fixture_policy, *, clock):
    """Only a factory-issued M2A Sandbox and direct test dependencies are accepted."""
    if type(server_fake_auth) is not SyntheticAuth or type(synthetic_fixture_policy) is not SyntheticFixturePolicy:
        raise ValueError('TEST_DEPENDENCIES_REQUIRED')
    return _TestApp(SimulationApplication(sandbox), server_fake_auth, synthetic_fixture_policy, clock)


class _TestApp:
    def __init__(self, application, auth, policy, clock):
        self._application, self._auth, self._policy, self._clock = application, auth, policy, clock

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            raise ValueError('HTTP_TEST_SCOPE_ONLY')
        try:
            headers = {}
            raw_headers = scope.get('headers', ())
            if sum(len(k) + len(v) for k, v in raw_headers) > MAX_HEADERS:
                raise HttpRejected(400, 'HEADERS_TOO_LARGE')
            for key, value in raw_headers:
                try:
                    name = key.decode('ascii').lower()
                except UnicodeError:
                    raise HttpRejected(400, 'INVALID_HEADERS') from None
                if name in headers:
                    raise HttpRejected(400, 'DUPLICATE_HEADER')
                headers[name] = value.decode('latin-1')
            if scope.get('query_string'):
                raise HttpRejected(400, 'QUERY_NOT_ALLOWED')
            body = await asyncio.wait_for(self._body(receive), timeout=2)
            # Recheck auth after receiving the entire body, immediately before command.
            status, payload = await asyncio.to_thread(self._execute, scope, headers, body)
        except HttpRejected as exc:
            status, payload = exc.status, envelope('REJECTED', errors=(exc.code,))
        except ExecutionRejected as exc:
            status, payload = domain_http_status(exc.code), envelope('REJECTED', errors=(exc.code,))
        except TimeoutError:
            status, payload = 400, envelope('REJECTED', errors=('BODY_TIMEOUT',))
        except Exception:
            # Do not echo request, exception, challenge, credential or internal ledger.
            status, payload = 500, envelope('REJECTED', errors=('INTERNAL_TEST_ERROR',))
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'), (b'cache-control', b'no-store'),
            (b'pragma', b'no-cache'), (b'x-content-type-options', b'nosniff')]})
        await send({'type': 'http.response.body', 'body': encoded})

    @staticmethod
    async def _body(receive):
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] != 'http.request':
                raise HttpRejected(400, 'BODY_INTERRUPTED')
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > MAX_BODY:
                raise HttpRejected(400, 'BODY_TOO_LARGE')
            chunks.append(chunk)
            if not message.get('more_body', False):
                return b''.join(chunks)

    def _execute(self, scope, headers, raw):
        method, path = scope['method'], scope['path']
        mutation = method != 'GET'
        with self._auth.authorize(headers, clock=self._clock, mutation=mutation) as (session, now):
            if mutation:
                if headers.get('content-type', '').lower() != 'application/json':
                    raise HttpRejected(400, 'JSON_CONTENT_TYPE_REQUIRED')
                body = decode(raw)
            else:
                if raw:
                    raise HttpRejected(400, 'GET_BODY_NOT_ALLOWED')
                body = {}
            app = self._application
            if path == PREFIX + '/preview' and method == 'POST':
                draft, evidence = draft_from_wire(body, session, self._policy, self._auth)
                preview = app.preview(draft, evidence, now=now).value
                # The ONLY challenge delivery surface: authenticated preview.
                proof = app.status(preview.preview_id).value
                data = {'preview_id': preview.preview_id,
                        'order_access': self._auth.order_capability(session, preview.preview_id),
                        'confirmation': {'token': preview.challenge.token, 'digest': preview.challenge.digest,
                                         'expires_at': preview.challenge.expires_at},
                        'assessment': preview.assessment,
                        'warnings': ['FICTIONAL_FIXTURE_VALUES', 'EXPLICIT_CONFIRMATION_REQUIRED'],
                        'draft_digest': proof['draft_digest'],
                        'evidence_digest': proof['evidence_digest']}
                return 200, envelope('PREVIEWED', data)
            if path == PREFIX + '/confirm' and method == 'POST':
                exact_fields(body, ('preview_id', 'token', 'digest', 'user_confirmed'))
                preview_id = body['preview_id']
                self._auth.require_order(session, preview_id, headers.get('x-order-access', ''))
                if type(body['token']) is not str or type(body['digest']) is not str:
                    raise HttpRejected(422, 'INVALID_WIRE_TYPE')
                result = app.confirm(Confirmation(preview_id, body['token'], body['digest'],
                                                  session.principal, body['user_confirmed']), now=now).value
                return self._status(result)
            parts = path.removeprefix(PREFIX + '/orders/').split('/')
            if not path.startswith(PREFIX + '/orders/') or len(parts) not in (1, 2):
                raise HttpRejected(404, 'ROUTE_NOT_FOUND')
            preview_id, action = parts[0], parts[1] if len(parts) == 2 else 'status'
            self._auth.require_order(session, preview_id, headers.get('x-order-access', ''))
            if method == 'GET' and action in {'status', 'audit-summary'}:
                result = app.status(preview_id).value
                # Only order-scoped proof from status; global audit() spans other accounts.
                if action == 'audit-summary':
                    result = {key: result[key] for key in ('digest', 'draft_digest', 'evidence_digest', 'commands')}
                    return 200, envelope('AUDIT_SUMMARY', result)
                return 200, envelope(result['order'].state.value, result)
            if method != 'POST' or action not in {'cancel', 'query', 'reconcile'}:
                raise HttpRejected(404, 'ROUTE_NOT_FOUND')
            exact_fields(body, ('user_confirmed',))
            if body['user_confirmed'] is not True:
                raise HttpRejected(422, 'EXPLICIT_CONFIRMATION_REQUIRED')
            if action == 'query':
                result = app.query(preview_id, now=now).value
                # No raw report/event identifiers in outward output.
                data = {'outcome': result['outcome'], 'order': app.status(preview_id).value['order']}
                return (200 if result['outcome'] == 'AVAILABLE' else 409), envelope(result['outcome'], data)
            result = getattr(app, action)(preview_id, now=now, user_confirmed=True).value
            return self._status(result)

    @staticmethod
    def _status(result):
        state = result['order'].state.value
        status = 409 if state in {'UNKNOWN', 'RECONCILING'} else (202 if state == 'CANCEL_PENDING' else 200)
        return status, envelope(state, result)
