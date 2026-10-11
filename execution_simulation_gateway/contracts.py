"""Strict wire conversion only. Central M1 owns trading admission."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import json

from execution.contracts import Currency, Draft, Funding, Lot, OrderKind, PositionAction, Side
from execution.validation import identifier
from .security import HttpRejected


def exact_fields(body, fields):
    if type(body) is not dict or set(body) != set(fields):
        raise HttpRejected(422, 'INVALID_FIELDS')


def decode(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('nonfinite')

    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise HttpRejected(400, 'INVALID_JSON') from None
    if type(value) is not dict:
        raise HttpRejected(422, 'INVALID_FIELDS')
    return value


def draft_from_wire(body, session, policy, auth):
    exact_fields(body, ('client_request_id', 'symbol', 'side', 'quantity', 'lot', 'limit_price',
                        'currency', 'order_kind', 'funding', 'contract_version', 'position_action'))
    identifier(body['client_request_id'])
    identifier(body['symbol'], 'INVALID_SYMBOL')
    try:
        side, lot = Side(body['side']), Lot(body['lot'])
        funding, kind = Funding(body['funding']), OrderKind(body['order_kind'])
        currency = Currency(body['currency'])
        action = None if body['position_action'] is None else PositionAction(body['position_action'])
        price = body['limit_price']
        if price is not None:
            if type(price) is not str or len(price) > 64:
                raise ValueError('decimal string required')
            price = Decimal(price)
    except (ValueError, TypeError, InvalidOperation):
        raise HttpRejected(422, 'INVALID_WIRE_TYPE') from None
    evidence = policy.select(session, body['symbol'], lot, funding, kind, currency)
    draft = Draft(evidence.market.instrument, session.account,
                  auth.request_id(session, body['client_request_id']), side, body['quantity'], lot, price,
                  currency=currency, order_kind=kind, funding=funding,
                  contract_version=body['contract_version'], position_action=action)
    return draft, evidence


def wire(value):
    if is_dataclass(value):
        return wire(asdict(value))
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    return value


def envelope(status, data=None, errors=()):
    return {'kind': 'omi.synthetic_execution.response', 'version': 'v1',
            'simulated': True, 'broker_connected': False, 'test_only': True,
            'status': status, 'limits': ['SYNTHETIC_ONLY', 'NO_REAL_AUTH', 'NO_BROKER',
                                        'RETAINED_RESERVATIONS', 'BOUNDED_TEST_APP'],
            'errorCodes': list(errors), 'data': wire(data)}


def domain_http_status(code):
    if code in {'PRINCIPAL_MISMATCH', 'CHALLENGE_MISMATCH'}:
        return 403
    if code in {'IDEMPOTENCY_CONFLICT', 'EVIDENCE_CONFLICT', 'CHALLENGE_CONSUMED',
                'PREVIEW_EXPIRED', 'PAYLOAD_DIGEST_MISMATCH', 'INVALID_TRANSITION',
                'CONFIRMATION_REQUIRED', 'UNKNOWN_PREVIEW', 'CLOCK_REGRESSION'}:
        return 409
    return 422
