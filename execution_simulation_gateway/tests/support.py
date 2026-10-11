"""Direct server test injection only; every numeric value is invented."""

from dataclasses import replace

from execution.contracts import Lot
from execution.tests.expanded_fixtures import expanded_fixture
from execution.tests.fixtures import NOW
from execution_simulation_gateway import SyntheticAuth, SyntheticFixturePolicy, build_test_app


ORIGIN = 'https://synthetic.invalid'


def evidence_for(principal='synthetic-human', account='synthetic-account'):
    _, evidence = expanded_fixture()
    return replace(evidence,
        account=replace(evidence.account, account_id=account,
                        credit=replace(evidence.account.credit, account_id=account)),
        permission=replace(evidence.permission, principal_id=principal, account_id=account))


def policy_for(*identities):
    identities = identities or (('synthetic-human', 'synthetic-account'),)
    return SyntheticFixturePolicy({(p, a, '2330', Lot.BOARD): evidence_for(p, a) for p, a in identities})


def draft(**changes):
    result = dict(client_request_id='request-1', symbol='2330', side='BUY', quantity=1000,
                  lot='BOARD', limit_price='25.50', currency='TWD', order_kind='LIMIT',
                  funding='CASH', contract_version=2, position_action='OPEN')
    result.update(changes)
    return result


def headers(credentials, preview=None):
    result = {'Authorization': 'Bearer ' + credentials.session, 'Origin': ORIGIN,
              'X-CSRF-Token': credentials.csrf, 'Content-Type': 'application/json'}
    if preview:
        result['X-Order-Access'] = preview['order_access']
    return result


def confirm_body(preview, **changes):
    value = dict(preview_id=preview['preview_id'], token=preview['confirmation']['token'],
                 digest=preview['confirmation']['digest'], user_confirmed=True)
    value.update(changes)
    return value
