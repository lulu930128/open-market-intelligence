from dataclasses import replace
from datetime import timedelta
import json
import unittest

from execution.contracts import Lot, State
from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.mock import Fixture
from execution_simulation.storage import connection
from execution_simulation_gateway.headless import Command, CommandStatus, HeadlessCommands
from execution_simulation_gateway.policy import SyntheticFixturePolicy
from execution_simulation_gateway.security import SyntheticAuth
from .support import ORIGIN, draft, evidence_for


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.scope = temporary_sandbox()
        self.box = self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)
        self.auth = SyntheticAuth(origins={ORIGIN})
        self.credentials = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        self.headers = {'authorization': 'Bearer ' + self.credentials.session,
                        'origin': ORIGIN, 'x-csrf-token': self.credentials.csrf}
        self.now = NOW
        self.evidence = evidence_for()
        self.evidence = replace(self.evidence, **{n: replace(getattr(self.evidence, n),
            ref=replace(getattr(self.evidence, n).ref, received_at=NOW))
            for n in ('market', 'account', 'permission')})
        self.gateway = self.build(self.evidence)

    def build(self, evidence):
        policy = SyntheticFixturePolicy({('synthetic-human', 'synthetic-account',
                                          evidence.market.instrument.symbol, Lot.BOARD): evidence})
        return HeadlessCommands(self.app, self.auth, policy, clock=lambda: self.now)

    def call(self, command, body, **kwargs):
        return self.gateway.execute(command, json.dumps(body).encode(), headers=kwargs.get('headers', self.headers))

    def preview(self, **changes):
        reply = self.call(Command.PREVIEW, draft(**changes))
        self.assertIs(reply.status, CommandStatus.OK, reply)
        self.assertEqual((reply.source, reply.execution_scope, reply.real_sim), ('SYNTHETIC', 'LOCAL_MOCK', 'BLOCKED'))
        return reply.data

    @staticmethod
    def access(p):
        return {k: p[k] for k in ('preview_id', 'order_access')}

    def confirm(self, p, **changes):
        body = self.access(p) | {k: p['confirmation'][k] for k in ('token', 'digest')}
        return self.call(Command.CONFIRM, body | {'manual_action': p['required_action']} | changes)

    def test_manual_vertical_slice_one_owner_no_dispatch_and_read_purity(self):
        p = self.preview()
        self.assertIs(self.confirm(p).status, CommandStatus.OK)
        self.assertIs(self.confirm(p).status, CommandStatus.OK)
        with connection(self.box, readonly=True) as db:
            self.assertEqual([db.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                              for t in ('confirmations', 'reservations', 'outbox', 'mock_effects')], [1, 1, 1, 0])
        before = self.box.database.read_bytes()
        result = self.call(Command.STATUS, self.access(p))
        self.assertEqual(result.data['order']['state'], State.SIMULATED_PENDING.value)
        self.assertEqual(before, self.box.database.read_bytes())
        for secret in (self.credentials.session, self.credentials.csrf, p['confirmation']['token'], p['order_access']):
            self.assertNotIn(secret, repr(result))
        self.assertTrue(self.app.verify().value['verified'])

    def test_no_evidence_or_identity_or_origin_in_consumer_payload(self):
        before = self.box.database.read_bytes()
        for field, value in (('account', 'synthetic-other'), ('principal', 'synthetic-other'),
                             ('evidence', {}), ('origin', 'REAL_SIM'), ('simulation', True)):
            r = self.call(Command.PREVIEW, draft(**{field: value}))
            self.assertEqual(r.reason_codes, ('INVALID_FIELDS',))
        self.assertEqual(before, self.box.database.read_bytes())

    def test_auth_revocation_origin_csrf_and_malformed_denied_without_writes(self):
        before = self.box.database.read_bytes()
        for headers in ({}, self.headers | {'origin': 'https://evil.invalid'},
                        self.headers | {'x-csrf-token': 'wrong'}, {'authorization': True}):
            self.assertIs(self.call(Command.PREVIEW, draft(), headers=headers).status, CommandStatus.DENIED)
        self.auth.revoke(self.credentials)
        self.assertEqual(self.call(Command.PREVIEW, draft()).reason_codes, ('SESSION_INVALID',))
        self.assertEqual(before, self.box.database.read_bytes())

    def test_confirmation_exact_action_digest_and_account_capability(self):
        p = self.preview()
        for changes in ({'manual_action': True}, {'manual_action': 'CONFIRM'},
                        {'digest': 'bad'}, {'token': 'bad'}, {'order_access': 'bad'}):
            self.assertIs(self.confirm(p, **changes).status, CommandStatus.DENIED)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)
        other = self.auth.issue('synthetic-peer', 'synthetic-account', now=NOW)
        other_headers = self.headers | {'authorization': 'Bearer ' + other.session, 'x-csrf-token': other.csrf}
        self.assertEqual(self.call(Command.STATUS, self.access(p), headers=other_headers).reason_codes,
                         ('ORDER_ACCESS_DENIED',))

    def test_ingress_missing_receipt_stale_and_future_denied(self):
        for ref in (replace(self.evidence.market.ref, received_at=None),
                    replace(self.evidence.market.ref, received_at=NOW + timedelta(seconds=1)),
                    replace(self.evidence.market.ref, valid_until=NOW)):
            self.gateway = self.build(replace(self.evidence, market=replace(self.evidence.market, ref=ref)))
            self.assertIs(self.call(Command.PREVIEW, draft()).status, CommandStatus.DENIED)

    def test_arbitrary_symbol_with_server_metadata_and_missing_quota(self):
        instrument = replace(self.evidence.market.instrument, symbol='7777')
        evidence = replace(self.evidence, **{n: replace(getattr(self.evidence, n), instrument=instrument)
                                            for n in ('market', 'account', 'permission')})
        evidence = replace(evidence, account=replace(evidence.account,
                           credit=replace(evidence.account.credit, instrument=instrument)))
        evidence = replace(evidence, market=replace(evidence.market,
                           trade_policy=replace(evidence.market.trade_policy, instrument=instrument)))
        self.gateway = self.build(evidence)
        self.preview(symbol='7777')
        self.assertIs(self.call(Command.PREVIEW, draft(symbol='8888')).status, CommandStatus.DENIED)
        self.gateway = self.build(replace(evidence, permission=replace(evidence.permission, maximum_notional=None)))
        self.assertIs(self.call(Command.PREVIEW, draft(symbol='7777', client_request_id='new')).status, CommandStatus.DENIED)

    def test_query_reconcile_cancel_are_manual_and_kill_preserves_control(self):
        p = self.preview()
        self.confirm(p)
        self.app.dispatch(p['preview_id'], now=NOW, fixture=Fixture.ACCEPT)
        self.app.set_mock_send_enabled(False, now=NOW, user_confirmed=True)
        for command in (Command.QUERY, Command.CANCEL):
            body = self.access(p) | {'manual_action': command.value + '_LOCAL_MOCK:' + p['preview_id']}
            self.assertIs(self.call(command, body).status, CommandStatus.OK)
        self.assertEqual(self.call(Command.STATUS, self.access(p)).data['order']['state'], 'CANCEL_PENDING')
        self.app.timeout(p['preview_id'], now=NOW)
        body = self.access(p) | {'manual_action': 'RECONCILE_LOCAL_MOCK:' + p['preview_id']}
        self.assertIs(self.call(Command.RECONCILE, body).status, CommandStatus.OK)

    def test_unknown_command_duplicate_keys_and_real_readiness(self):
        for command in ('SEND', 'AI_TRADE', 'CONFIRM', True, None):
            self.assertIs(self.call(command, {}).status, CommandStatus.DENIED)
        reply = self.gateway.execute(Command.PREVIEW, b'{"symbol":"a","symbol":"b"}', headers=self.headers)
        self.assertEqual(reply.reason_codes, ('INVALID_JSON',))
        self.assertIs(self.gateway.real_readiness().status, CommandStatus.BLOCKED)
        self.assertEqual(self.gateway.real_readiness().mcp_app_consumer, 'NOT_CONNECTED')

    def test_expired_confirmation_requires_new_manual_preview(self):
        p = self.preview()
        self.now += timedelta(seconds=61)
        self.assertEqual(self.confirm(p).reason_codes, ('PREVIEW_EXPIRED',))

    def test_auth_restart_does_not_allocate_second_order_for_same_request(self):
        p = self.preview()
        self.confirm(p)
        old_headers = self.headers
        self.auth = SyntheticAuth(origins={ORIGIN})
        credentials = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        self.headers = {'authorization': 'Bearer ' + credentials.session,
                        'origin': ORIGIN, 'x-csrf-token': credentials.csrf}
        self.app = SimulationApplication(self.box)
        self.gateway = self.build(self.evidence)
        self.assertEqual(self.call(Command.STATUS, self.access(p), headers=old_headers).reason_codes,
                         ('SESSION_INVALID',))
        same = self.preview()
        self.assertEqual(p['preview_id'], same['preview_id'])
        self.assertNotEqual(p['order_access'], same['order_access'])
        self.assertIs(self.confirm(same).status, CommandStatus.OK)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)
