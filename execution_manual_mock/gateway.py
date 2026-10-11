"""Manual mock-only HTTP bridge reusing M2B transport/auth and M2A transaction owner."""

import json

from execution_simulation.mock import Fixture
from execution_simulation_gateway.gateway import _TestApp, PREFIX
from execution_simulation_gateway.contracts import decode, exact_fields, draft_from_wire, envelope
from execution_simulation_gateway.security import HttpRejected


class ManualMockApp(_TestApp):
    """Private M2B test transport seam; no production app or real auth claim."""

    def __init__(self, application, auth, policy, clock, scenarios):
        super().__init__(application, auth, policy, clock)
        if any(type(value) is not Fixture or not value.value.startswith('SDK_')
               or value is Fixture.SDK_CANCEL for value in scenarios.values()):
            raise ValueError('CLOSED_FAKE_SCENARIOS_REQUIRED')
        self._scenarios = dict(scenarios)

    async def __call__(self, scope, receive, send):
        async def project(message):
            if message['type'] == 'http.response.body':
                result = json.loads(message['body'])
                result['kind'] = 'omi.manual_mock_execution.response'
                result['reasonCodes'] = result['errorCodes'] or ((result.get('data') or {}).get('broker') or {}).get('reasonCodes', [])
                if result['errorCodes']:
                    result['status'] = 'VALIDATION_BLOCKED'
                message = dict(message, body=json.dumps(result, allow_nan=False).encode())
            await send(message)
        await super().__call__(scope, receive, project)

    def _execute(self, scope, headers, raw):
        method, path = scope['method'], scope['path']
        special = path == PREFIX + '/preview' or path.endswith(('/submit', '/cancel')) or path == PREFIX + '/kill-switch'
        if not special:
            status, result = super()._execute(scope, headers, raw)
            if result['data'] is not None and 'order' in result['data']:
                key = result['data']['order']['preview_id']
                broker = self._application.mock_broker_status(key).value
                result['data']['broker'] = broker
                result['status'] = broker['status']
                if path == PREFIX + '/confirm':
                    result['data']['phase'] = 'CONFIRMED'
            return status, result
        with self._auth.authorize(headers, clock=self._clock, mutation=True) as (session, now):
            if method != 'POST':
                raise HttpRejected(405, 'POST_REQUIRED')
            if headers.get('content-type', '').lower() != 'application/json':
                raise HttpRejected(400, 'JSON_CONTENT_TYPE_REQUIRED')
            body = decode(raw)
            app = self._application
            if path == PREFIX + '/kill-switch':
                exact_fields(body, ('enabled', 'user_confirmed'))
                app.set_mock_send_enabled(body['enabled'], now=now, user_confirmed=body['user_confirmed'])
                return 200, envelope('MOCK_SEND_ENABLED' if body['enabled'] else 'KILL_SWITCH_ACTIVE')
            if path == PREFIX + '/preview':
                draft, evidence = draft_from_wire(body, session, self._policy, self._auth)
                if draft.instrument.symbol not in self._scenarios:
                    raise HttpRejected(422, 'BROKER_CAPABILITY_UNVERIFIED')
                p = app.preview(draft, evidence, now=now, mock_broker=True).value
                return 200, envelope('PREVIEWED', {
                    'status': 'READY', 'preview_id': p.preview_id,
                    'order_access': self._auth.order_capability(session, p.preview_id),
                    'confirmation': {'token': p.challenge.token, 'digest': p.challenge.digest,
                                     'expires_at': p.challenge.expires_at},
                    'draft': {'symbol': draft.instrument.symbol, 'side': draft.side.value,
                              'shares': draft.quantity, 'lot': draft.lot.value,
                              'funding': draft.funding.value, 'position_action': draft.position_action.value,
                              'order_kind': draft.order_kind.value, 'limit_price': draft.limit_price},
                    'assessment': p.assessment,
                    'expense': {'fee_reserve': evidence.permission.buy_fee_reserve,
                                'required_cash': p.assessment.required_cash, 'actual_fees': 'UNVERIFIED'},
                    'constraints': {'minimum_price': evidence.market.minimum_price,
                                    'maximum_price': evidence.market.maximum_price,
                                    'lot_rule': evidence.market.lot_rule,
                                    'tick_bands': evidence.market.tick_bands,
                                    'valid_until': p.assessment.valid_until},
                    'warnings': ['SYNTHETIC_ONLY', 'FAKE_SDK_UNITS_ONLY', 'REAL_INGRESS_UNVERIFIED',
                                 'BROKER_ACCEPTANCE_IS_NOT_FILL', 'RESERVATIONS_RETAINED']})
            prefix = PREFIX + '/orders/'
            parts = path.removeprefix(prefix).split('/')
            if not path.startswith(prefix) or len(parts) != 2 or parts[1] not in {'submit', 'cancel'}:
                raise HttpRejected(404, 'ROUTE_NOT_FOUND')
            key = parts[0]
            self._auth.require_order(session, key, headers.get('x-order-access', ''))
            exact_fields(body, ('user_confirmed',))
            if body['user_confirmed'] is not True:
                raise HttpRejected(422, 'EXPLICIT_CONFIRMATION_REQUIRED')
            current = app.mock_broker_status(key).value
            if parts[1] == 'cancel':
                if current['status'] not in {'READY', 'UNKNOWN', 'RECONCILING', 'CANCELLED', 'FILLED'} and not current['order_id_verified']:
                    raise HttpRejected(409, 'BROKER_ORDER_ID_UNVERIFIED')
                app.cancel(key, now=now, user_confirmed=True)
                current = app.mock_broker_status(key).value
                if current['status'] == 'CANCEL_PENDING':
                    app.dispatch(key, now=now, fixture=Fixture.SDK_CANCEL, kind='CANCEL')
            else:
                app.dispatch(key, now=now, fixture=self._scenarios[current['symbol']])
            result = app.mock_broker_status(key).value
            return 200, envelope(result['status'], {'phase': 'SENT', 'broker': result})
