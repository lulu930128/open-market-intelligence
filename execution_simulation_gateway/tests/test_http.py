import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from itertools import product
import json
from threading import Event
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from execution.contracts import Funding, Lot, OrderKind, PositionAction
from execution.tests.fixtures import NOW
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.mock import Fixture
from execution_simulation.storage import connection
from execution_simulation_gateway import SyntheticAuth, SyntheticFixturePolicy, build_test_app
from execution_simulation_gateway.gateway import PREFIX
from .http_driver import request
from .support import ORIGIN, confirm_body, draft, evidence_for, headers, policy_for


class HttpTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope = temporary_sandbox()
        self.box = self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.now = NOW
        self.auth = SyntheticAuth(origins={ORIGIN})
        self.credentials = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        self.policy = policy_for(('synthetic-human', 'synthetic-account'),
                                 ('synthetic-other', 'synthetic-other-account'),
                                 ('synthetic-peer', 'synthetic-account'))
        self.app = self.build()
        self.runner = SimulationApplication(self.box)

    def build(self):
        return build_test_app(self.box, self.auth, self.policy, clock=lambda: self.now)

    async def call(self, method, path, *, preview=None, credentials=None, **kwargs):
        return await request(self.app, method, PREFIX + path,
                             headers=kwargs.pop('headers', headers(credentials or self.credentials, preview)), **kwargs)

    async def preview(self, **changes):
        status, result = await self.call('POST', '/preview', body=draft(**changes))
        self.assertEqual(status, 200, result)
        return result['data']

    async def confirm(self, preview):
        return await self.call('POST', '/confirm', preview=preview, body=confirm_body(preview))

    def counts(self):
        with connection(self.box, readonly=True) as db:
            return {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                    for t in ('previews', 'confirmations', 'outbox', 'mock_effects', 'reservations', 'audit')}

    async def test_full_cash_path_duplicate_restart_read_purity_and_secrets(self):
        p = await self.preview()
        self.assertEqual((await self.confirm(p))[0], 200)
        self.runner.dispatch(p['preview_id'], now=self.now)
        self.assertEqual((await self.confirm(p))[0], 200)
        before = self.box.database.read_bytes()
        self.app = self.build()
        for suffix in ('', '/audit-summary'):
            code, result = await self.call('GET', '/orders/' + p['preview_id'] + suffix, preview=p)
            self.assertEqual(code, 200)
            for secret in (p['confirmation']['token'], p['order_access'], self.credentials.session, self.credentials.csrf):
                self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn('synthetic-account', json.dumps(result))
        self.assertEqual(before, self.box.database.read_bytes())
        self.assertEqual(self.counts()['mock_effects'], 1)
        self.assertEqual(self.counts()['outbox'], 1)
        self.assertEqual(self.counts()['confirmations'], 1)
        code, result = await self.call('GET', '/orders/' + p['preview_id'], preview=p)
        self.assertEqual(result['status'], 'SIMULATED_ACCEPTED')

    async def test_all_v2_modes_open_close_limit_market_via_http(self):
        for funding, action, kind in product(Funding, PositionAction, OrderKind):
            with self.subTest(funding=funding, action=action, kind=kind), temporary_sandbox() as box:
                app = build_test_app(box, self.auth, self.policy, clock=lambda: NOW)
                short = funding in {Funding.SHORT_SELLING, Funding.LEND_SELLING}
                side = 'SELL' if short == (action is PositionAction.OPEN) else 'BUY'
                code, result = await request(app, 'POST', PREFIX + '/preview', headers=headers(self.credentials),
                    body=draft(funding=funding.value, side=side, position_action=action.value,
                               order_kind=kind.value, limit_price=None if kind is OrderKind.MARKET else '25.50'))
                self.assertEqual(code, 200, result)
                p = result['data']
                code, result = await request(app, 'POST', PREFIX + '/confirm', headers=headers(self.credentials, p), body=confirm_body(p))
                self.assertEqual(code, 200, result)
                runner = SimulationApplication(box)
                runner.dispatch(p['preview_id'], now=NOW)
                runner.simulate_fill(p['preview_id'], cumulative_filled=1000, now=NOW)
                code, result = await request(app, 'GET', PREFIX + '/orders/' + p['preview_id'], headers=headers(self.credentials, p))
                self.assertEqual(result['status'], 'SIMULATED_FILLED')

    async def test_auth_origin_csrf_expiry_revoke_fail_without_db_writes(self):
        p = await self.preview()
        before = self.box.database.read_bytes()
        cases = [({}, 401), ({'Authorization': 'Bearer wrong'}, 401)]
        for field, value, expected in [('Origin', 'https://evil.invalid', 403), ('X-CSRF-Token', 'wrong', 403)]:
            h = headers(self.credentials, p)
            h[field] = value
            cases.append((h, expected))
        for h, expected in cases:
            self.assertEqual((await self.call('POST', '/confirm', body=confirm_body(p), headers=h))[0], expected)
        self.now += timedelta(minutes=5)
        self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'], preview=p))[0], 401)
        self.now = NOW
        self.auth.revoke(self.credentials)
        self.assertEqual((await self.call('POST', '/confirm', preview=p, body=confirm_body(p)))[0], 401)
        self.assertEqual(before, self.box.database.read_bytes())

    async def test_cross_principal_account_all_commands_and_same_request(self):
        p = await self.preview()
        for identity in [('synthetic-other', 'synthetic-other-account'), ('synthetic-peer', 'synthetic-account')]:
            other = self.auth.issue(*identity, now=NOW)
            before = self.box.database.read_bytes()
            for method, suffix, body in [('GET', '', None), ('GET', '/audit-summary', None),
                    ('POST', '/cancel', {'user_confirmed': True}), ('POST', '/query', {'user_confirmed': True}),
                    ('POST', '/reconcile', {'user_confirmed': True})]:
                self.assertEqual((await self.call(method, '/orders/' + p['preview_id'] + suffix,
                                                  preview=p, credentials=other, body=body))[0], 403)
            self.assertEqual((await self.call('POST', '/confirm', credentials=other, preview=p, body=confirm_body(p)))[0], 403)
            self.assertEqual(before, self.box.database.read_bytes())
            code, result = await self.call('POST', '/preview', credentials=other, body=draft())
            self.assertEqual(code, 200, result)
            self.assertNotEqual(result['data']['preview_id'], p['preview_id'])

    async def test_idempotency_conflicts_and_expired_unconsumed_challenge(self):
        p = await self.preview()
        self.assertEqual((await self.preview())['confirmation'], p['confirmation'])
        self.assertEqual((await self.call('POST', '/preview', body=draft(quantity=2000)))[0], 409)
        self.assertEqual((await self.call('POST', '/confirm', preview=p, body=confirm_body(p, digest='bad')))[0], 409)
        self.now += timedelta(seconds=61)
        code, result = await self.confirm(p)
        self.assertEqual(code, 409)
        self.assertEqual(result['errorCodes'], ['PREVIEW_EXPIRED'])
        self.assertEqual(self.counts()['outbox'], 0)

    async def test_cancel_unknown_query_manual_reconcile(self):
        p = await self.preview()
        await self.confirm(p)
        self.runner.dispatch(p['preview_id'], now=NOW, fixture=Fixture.TIMEOUT)
        code, result = await self.call('GET', '/orders/' + p['preview_id'], preview=p)
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'UNKNOWN')
        for action in ('cancel', 'query', 'reconcile'):
            self.assertEqual((await self.call('POST', '/orders/' + p['preview_id'] + '/' + action,
                                             preview=p, body={'user_confirmed': False}))[0], 422)
        code, result = await self.call('POST', '/orders/' + p['preview_id'] + '/cancel', preview=p, body={'user_confirmed': True})
        self.assertEqual((code, result['status']), (409, 'UNKNOWN'))
        self.assertEqual(self.counts()['mock_effects'], 1)
        self.assertEqual((await self.call('POST', '/orders/' + p['preview_id'] + '/query', preview=p, body={'user_confirmed': True}))[0], 200)
        code, result = await self.call('POST', '/orders/' + p['preview_id'] + '/reconcile', preview=p, body={'user_confirmed': True})
        self.assertEqual((code, result['status']), (202, 'CANCEL_PENDING'))
        # M2A deliberately requires renewed cancel after uncertainty resolves.
        await self.call('POST', '/orders/' + p['preview_id'] + '/cancel', preview=p, body={'user_confirmed': True})
        self.runner.dispatch(p['preview_id'], now=NOW, kind='CANCEL', fixture=Fixture.CANCEL)
        self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'], preview=p))[1]['status'], 'SIMULATED_CANCELLED')

    async def test_unavailable_query_remains_unresolved(self):
        p = await self.preview()
        await self.confirm(p)
        code, result = await self.call('POST', '/orders/' + p['preview_id'] + '/query', preview=p, body={'user_confirmed': True})
        self.assertEqual((code, result['status']), (409, 'UNAVAILABLE'))
        self.runner.timeout(p['preview_id'], now=NOW)
        code, result = await self.call('POST', '/orders/' + p['preview_id'] + '/reconcile', preview=p, body={'user_confirmed': True})
        self.assertEqual((code, result['status']), (409, 'RECONCILING'))
        self.assertEqual(self.counts()['mock_effects'], 0)

    async def test_schema_payload_and_unexposed_routes(self):
        for changes in [{'account_id': 'synthetic-evil'}, {'principal_id': 'synthetic-evil'}, {'scenario': 'ACCEPT'},
                        {'database': 'data/open_market_intelligence.db'}, {'side': 'BAD'}, {'funding': 'BORROWED'},
                        {'quantity': True}, {'quantity': 1.5}, {'quantity': 1}, {'limit_price': '25.51'},
                        {'order_kind': 'MARKET'}, {'order_kind': 'MKT'}, {'limit_price': 'NaN'},
                        {'contract_version': True}]:
            code, result = await self.call('POST', '/preview', body=draft(**changes))
            self.assertEqual(code, 422, (changes, result))
        for raw in [b'{', b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b' ' * 8193]:
            self.assertEqual((await self.call('POST', '/preview', raw=raw))[0], 400)
        for path in ('/dispatch', '/callback', '/recover', '/sessions'):
            self.assertEqual((await self.call('POST', path, body={}))[0], 404)
        self.assertEqual(self.counts()['previews'], 0)

    async def test_central_policy_credit_borrow_admission(self):
        base = evidence_for()
        cases = [replace(base, market=replace(base.market, trade_policy=None)),
                 replace(base, account=replace(base.account, credit=None)),
                 replace(base, account=replace(base.account, credit=replace(base.account.credit, short_borrow_available=0))),
                 replace(base, account=replace(base.account, credit=replace(base.account.credit, lend_borrow_available=0))),
                 replace(base, market=replace(base.market, ref=replace(base.market.ref, valid_until=NOW)))]
        for index, evidence in enumerate(cases):
            policy = SyntheticFixturePolicy({('synthetic-human', 'synthetic-account', '2330', Lot.BOARD): evidence})
            self.app = build_test_app(self.box, self.auth, policy, clock=lambda: NOW)
            funding = 'LEND_SELLING' if index == 3 else 'SHORT_SELLING'
            code, result = await self.call('POST', '/preview', body=draft(funding=funding, side='SELL'))
            self.assertEqual(code, 422, result)
        self.assertEqual(self.counts()['previews'], 0)

    async def test_margin_missing_credit_and_market_price_are_central_rejections(self):
        base = evidence_for()
        policy = SyntheticFixturePolicy({('synthetic-human', 'synthetic-account', '2330', Lot.BOARD):
                                         replace(base, account=replace(base.account, credit=None))})
        self.app = build_test_app(self.box, self.auth, policy, clock=lambda: NOW)
        code, result = await self.call('POST', '/preview', body=draft(funding='MARGIN'))
        self.assertEqual((code, result['errorCodes']), (422, ['CREDIT_UNVERIFIED']))
        code, result = await self.call('POST', '/preview', body=draft(order_kind='MARKET'))
        self.assertEqual((code, result['errorCodes']), (422, ['MARKET_PRICE_MUST_BE_UNSPECIFIED']))
        self.assertEqual(self.counts()['previews'], 0)

    async def test_reads_require_origin_auth_and_order_capability_without_writes(self):
        p = await self.preview()
        before = self.box.database.read_bytes()
        for suffix in ('', '/audit-summary'):
            for field, code in [('Authorization', 401), ('Origin', 403), ('X-Order-Access', 403)]:
                h = headers(self.credentials, p)
                h.pop(field)
                self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'] + suffix, headers=h))[0], code)
        self.assertEqual(before, self.box.database.read_bytes())

    async def test_concurrent_sessions_confirm_and_revoke_during_receive(self):
        second = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        p = await self.preview()
        results = await asyncio.gather(*[self.call('POST', '/confirm', preview=p,
            credentials=self.credentials if n % 2 else second, body=confirm_body(p)) for n in range(8)])
        self.assertTrue(all(code == 200 for code, _ in results), results)
        self.assertEqual(self.counts()['outbox'], 1)
        q = await self.preview(client_request_id='request-2')
        before = self.box.database.read_bytes()
        code, _ = await self.call('POST', '/confirm', preview=q, body=confirm_body(q),
                                  before_receive=lambda: self.auth.revoke(self.credentials))
        self.assertEqual(code, 401)
        self.assertEqual(before, self.box.database.read_bytes())

    async def test_rate_limit_and_arbitrary_sandbox_rejected(self):
        auth = SyntheticAuth(origins={ORIGIN}, requests_per_minute=1)
        cred = auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        app = build_test_app(self.box, auth, self.policy, clock=lambda: NOW)
        for expected in (200, 429):
            self.assertEqual((await request(app, 'POST', PREFIX + '/preview', headers=headers(cred), body=draft()))[0], expected)
        with self.assertRaises(Exception):
            build_test_app('data/open_market_intelligence.db', auth, self.policy, clock=lambda: NOW)

    async def test_waiting_for_lock_rechecks_expiry_before_http_command(self):
        cred = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW, ttl=timedelta(seconds=1))
        reached = Event()
        original = self.auth.authorize
        def queued(*args, **kwargs):
            reached.set()
            return original(*args, **kwargs)
        def run():
            return asyncio.run(request(self.app, 'POST', PREFIX + '/preview', headers=headers(cred), body=draft()))
        before = self.box.database.read_bytes()
        with patch.object(self.auth, 'authorize', queued), ThreadPoolExecutor(max_workers=1) as pool:
            with self.auth._lock:
                future = pool.submit(run)
                self.assertTrue(reached.wait(3))
                self.now = NOW + timedelta(seconds=2)
            code, result = future.result(timeout=5)
        self.assertEqual(code, 401, result)
        self.assertEqual(before, self.box.database.read_bytes())

    async def test_confirmed_replay_after_challenge_expiry_returns_receipt(self):
        p = await self.preview()
        await self.confirm(p)
        self.now += timedelta(seconds=61)
        self.assertEqual((await self.confirm(p))[0], 200)
        self.assertEqual(self.counts()['outbox'], 1)
        self.assertEqual(self.counts()['mock_effects'], 0)

    async def test_new_issuer_rejects_old_credentials_and_access(self):
        p = await self.preview()
        self.auth = SyntheticAuth(origins={ORIGIN})
        self.app = self.build()
        self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'], preview=p))[0], 401)
        self.credentials = self.auth.issue('synthetic-human', 'synthetic-account', now=NOW)
        self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'], preview=p))[0], 403)

    async def test_chunked_size_limit_content_type_allowlist_and_untrusted_url(self):
        before = self.box.database.read_bytes()
        self.assertEqual((await self.call('POST', '/preview', chunks=[b' ' * 4096, b' ' * 4097]))[0], 400)
        h = headers(self.credentials)
        h['Content-Type'] = 'text/plain'
        self.assertEqual((await self.call('POST', '/preview', headers=h, body=draft()))[0], 400)
        self.assertEqual((await self.call('POST', '/preview?account_id=other', body=draft()))[0], 400)
        self.assertEqual((await self.call('POST', '/preview', body=draft(symbol='0050')))[0], 403)
        self.assertEqual(before, self.box.database.read_bytes())

    async def test_connection_io_tripwire(self):
        # Event loop exists before socket constructor is forbidden.
        actual_connect = __import__('sqlite3').connect
        def temp_only(path, *args, **kwargs):
            self.assertIn(self.box.database.as_uri(), str(path))
            return actual_connect(path, *args, **kwargs)
        with patch('socket.socket.connect', side_effect=AssertionError('NO_NETWORK')), \
                patch('socket.socket.connect_ex', side_effect=AssertionError('NO_NETWORK')), \
                patch('socket.socket.bind', side_effect=AssertionError('NO_LISTENER')), \
                patch('socket.socket.listen', side_effect=AssertionError('NO_LISTENER')), \
                patch('socket.create_connection', side_effect=AssertionError('NO_NETWORK')), \
                patch('subprocess.Popen', side_effect=AssertionError('NO_PROCESS')), \
                patch('sqlite3.connect', side_effect=temp_only):
            p = await self.preview()
            await self.confirm(p)
            self.runner.dispatch(p['preview_id'], now=NOW)
            self.assertEqual((await self.call('GET', '/orders/' + p['preview_id'], preview=p))[0], 200)
