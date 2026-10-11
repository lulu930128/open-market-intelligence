"""Versioned wire schema. Enum vocabulary comes from the central M1 contract."""

from execution.contracts import Currency, Funding, Lot, OrderKind, PositionAction, Side


def contract_schema():
    preview = {
        'client_request_id': {'type': 'string'}, 'symbol': {'type': 'string'},
        'quantity': {'type': 'integer'}, 'limit_price': {'type': ['string', 'null']},
        'contract_version': {'type': 'integer'},
    }
    for name, enum in [('side', Side), ('lot', Lot), ('currency', Currency),
                       ('funding', Funding), ('order_kind', OrderKind)]:
        preview[name] = {'type': 'string', 'enum': [value.value for value in enum]}
    preview['position_action'] = {'enum': [None] + [value.value for value in PositionAction]}

    def closed(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}

    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'urn:omi:synthetic-execution:gateway:v1',
            '$defs': {
                'previewRequest': closed(preview),
                'confirmRequest': closed({'preview_id': {'type': 'string'}, 'token': {'type': 'string'},
                                          'digest': {'type': 'string'}, 'user_confirmed': {'const': True}}),
                'manualRequest': closed({'user_confirmed': {'const': True}}),
                'response': closed({
                    'kind': {'const': 'omi.synthetic_execution.response'}, 'version': {'const': 'v1'},
                    'simulated': {'const': True}, 'broker_connected': {'const': False}, 'test_only': {'const': True},
                    'status': {'type': 'string'}, 'limits': {'type': 'array', 'items': {'type': 'string'}},
                    'errorCodes': {'type': 'array', 'items': {'type': 'string'}},
                    'data': {'type': ['object', 'null']}})}}
