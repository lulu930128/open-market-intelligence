"""Only factory temp SQLite and invented 2330 prices/rates/session evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
import subprocess
import sys
import unittest
from unittest.mock import patch

from execution.contracts import EventKind, ExecutionRejected, Funding, OrderKind, PositionAction, SimulationEvent
from execution.tests.expanded_fixtures import expanded_fixture
from execution.tests.fixtures import NOW, confirmation
from execution.validation import digest_of
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.codec import dumps, loads
from execution_simulation.mock import Fixture, SimulatedCrash
from execution_simulation.storage import connection, reopen_sandbox, settlement_sandbox_clone
from execution_simulation.settlement_contracts import (
    AccrualTick, FeeSchedule, FillLot, InterestPolicy, RestrictionEvidence, SettlementReceipt,
)


class SettlementTests(unittest.TestCase):
    def setUp(self):
        scope = temporary_sandbox()
        self.source = scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)
        clone = settlement_sandbox_clone(self.source)
        self.box = clone.__enter__()
        self.addCleanup(clone.__exit__, None, None, None)
        self.app = SimulationApplication(self.box)
        self.counter = 0

    def reject(self, code, fn, *args, **kwargs):
        with self.assertRaises(ExecutionRejected) as raised:
            fn(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def order(self, *, funding=Funding.CASH, action=PositionAction.OPEN, kind=OrderKind.LIMIT,
              cash=D('1000000'), quantity=1000, now=NOW, dispatch=True, position=100000,
              account_id='synthetic-account', symbol='2330'):
        self.counter += 1
        d, e = expanded_fixture(funding=funding, action=action, kind=kind)
        instrument = replace(d.instrument, symbol=symbol)
        d = replace(d, instrument=instrument, account_id=account_id, quantity=quantity,
                    client_request_id='settlement-' + str(self.counter))
        e = replace(e, market=replace(e.market, instrument=instrument,
            trade_policy=replace(e.market.trade_policy, instrument=instrument)),
            account=replace(e.account, instrument=instrument, account_id=account_id,
                available_cash=cash, sellable_quantity=position,
                credit=replace(e.account.credit, instrument=instrument, account_id=account_id,
                    margin_position=position, short_position=position, lend_position=position)),
            permission=replace(e.permission, instrument=instrument, account_id=account_id))
        p = self.app.preview(d, e, now=now).value
        self.app.confirm(confirmation(p), now=now)
        if dispatch:
            self.app.dispatch(p.preview_id, now=now)
        return p

    def fill(self, p, shares=1000, price='25.50', identity=None, now=NOW, **kwargs):
        lot = FillLot(identity or 'lot-' + str(self.counter), p.preview_id, shares, D(price), now)
        self.app.record_fill(lot, now=now, **kwargs)
        return lot

    def policies(self, p):
        fees = FeeSchedule('fake-fees', 'fictional-v1', NOW, NOW + timedelta(hours=1),
                           p.draft.currency, D('0.0001'), D('0.0002'), D('0.0003'), D('0.000001'), 'ROUND_HALF_EVEN')
        interest = InterestPolicy('fake-interest', 'fictional-v1', NOW, NOW + timedelta(hours=1),
                                  p.draft.currency, D('0.000001'), D('0.000002'), 600, D('0.000001'), 'ROUND_HALF_EVEN')
        return fees, interest

    def receipt(self, p, *, now=NOW, opening=None, ack=None):
        with connection(self.box, readonly=True) as db:
            order = loads(db.execute('SELECT payload FROM orders WHERE id=?', (p.preview_id,)).fetchone()[0])
        lots = self.app.snapshot(p.preview_id).value['fills']
        return SettlementReceipt('receipt-' + p.preview_id, 'synthetic-finality-v2', p.preview_id,
            p.draft.account_id, p.evidence.market.session_id, p.draft.currency, p.draft.instrument,
            p.challenge.digest, digest_of(order), digest_of(lots),
            NOW, NOW + timedelta(minutes=10), now, True, opening, ack)

    def settle(self, p, *, now=NOW, opening=None, ack=None, **kwargs):
        fees, interest = self.policies(p)
        return self.app.settle(p.preview_id, self.receipt(p, now=now, opening=opening, ack=ack),
                               fees=fees, interest=interest, now=now, **kwargs)

    def test_exact_distinct_fill_lots_and_idempotency(self):
        p = self.order()
        first = self.fill(p, 400, '24.50', 'first')
        second = self.fill(p, 600, '25.00', 'second')
        self.app.record_fill(first, now=NOW)
        self.app.record_fill(second, now=NOW)
        self.reject('EVENT_ID_CONFLICT', self.app.record_fill, replace(first, executed_price=D('24.55')), now=NOW)
        result = self.settle(p).value
        self.assertEqual(result['stage'], 'SETTLED')
        b = result['account_deltas'][0]
        self.assertEqual(b['cash'], -D('24802.480000'))
        self.assertEqual(b['sellable'], 1000)
        self.assertEqual(b['fees'], D('2.48'))
        receipt = self.receipt(p)
        fees, interest = self.policies(p)
        self.app.settle(p.preview_id, receipt, fees=fees, interest=interest, now=NOW)
        self.reject('SETTLEMENT_CONFLICT', self.app.settle, p.preview_id,
                    replace(receipt, event_id='other'), fees=fees, interest=interest, now=NOW)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM releases').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_market_unused_hold_and_cross_order_consumption(self):
        p = self.order(kind=OrderKind.MARKET, cash=D('100000'))
        self.assertIsNone(p.draft.limit_price)
        self.fill(p)
        self.settle(p)
        q = self.order(cash=D('100000'))
        self.fill(q)
        self.settle(q)
        r = self.order(cash=D('100000'))
        self.assertEqual(self.app.snapshot(r.preview_id).value['stage'], 'UNSETTLED')
        self.reject('INSUFFICIENT_CASH', self.order, cash=D('100000'))

    def test_sale_proceeds_not_spendable_until_receipt(self):
        p = self.order(action=PositionAction.CLOSE, cash=D('26000'))
        self.fill(p)
        q = self.order(cash=D('26000'))
        self.reject('INSUFFICIENT_CASH', self.order, cash=D('26000'))
        self.settle(p)
        r = self.order(cash=D('26000'))
        self.assertNotEqual(q.preview_id, r.preview_id)

    def test_financing_and_short_loans_close_ack(self):
        for funding in (Funding.MARGIN, Funding.SHORT_SELLING, Funding.LEND_SELLING):
            with self.subTest(funding=funding):
                p = self.order(funding=funding)
                self.fill(p)
                self.settle(p)
                q = self.order(funding=funding, action=PositionAction.CLOSE)
                self.fill(q)
                self.reject('PAYBACK_ACK_UNVERIFIED', self.settle, q)
                result = self.settle(q, opening=p.preview_id, ack='ack-' + p.preview_id).value
                b = result['account_deltas'][0]
                self.assertEqual(b['financing_principal'], 0)
                self.assertEqual(b['borrowed_shares'], 0)
                self.assertEqual(b['collateral'], 0)
                self.assertEqual(b['restricted_proceeds'], 0)
        self.assertTrue(self.app.verify().value['verified'])

    def test_explicit_accrual_exact_and_duplicate_period(self):
        p = self.order(funding=Funding.MARGIN)
        self.fill(p)
        self.settle(p)
        now = NOW + timedelta(seconds=10)
        tick = AccrualTick('tick1', p.preview_id, NOW, now)
        result = self.app.accrue(tick, now=now).value
        self.assertEqual(result['account_deltas'][0]['interest'], D('0.153'))
        self.app.accrue(tick, now=now)
        self.reject('EVENT_ID_CONFLICT', self.app.accrue, replace(tick, period_end=now + timedelta(seconds=1)), now=now)
        self.reject('ACCRUAL_PERIOD_CONFLICT', self.app.accrue, replace(tick, event_id='tick2'), now=now)

    def test_borrow_cost_and_collateral_are_not_available_cash(self):
        p = self.order(funding=Funding.SHORT_SELLING)
        self.fill(p)
        b = self.settle(p).value['account_deltas'][0]
        self.assertEqual(b['cash'], -D('15.30'))
        self.assertEqual(b['restricted_proceeds'], D('25500'))
        self.assertEqual(b['collateral'], -D('30600'))
        self.assertEqual(b['borrowed_shares'], 1000)
        now = NOW + timedelta(seconds=10)
        b = self.app.accrue(AccrualTick('borrow-tick', p.preview_id, NOW, now), now=now).value['account_deltas'][0]
        self.assertEqual(b['interest'], D('0.51'))

    def test_unknown_cancel_pending_and_partial_cannot_release(self):
        p = self.order()
        self.fill(p, 400)
        self.reject('SETTLEMENT_STATE_BLOCKED', self.settle, p)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.reject('SETTLEMENT_STATE_BLOCKED', self.settle, p)
        self.app.timeout(p.preview_id, now=NOW)
        self.reject('SETTLEMENT_STATE_BLOCKED', self.settle, p)
        self.assertFalse(self.app.snapshot(p.preview_id).value['reservation_released'])

    def test_cancel_late_partial_then_receipted_release(self):
        p = self.order()
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, kind='CANCEL', fixture=Fixture.CANCEL, now=NOW)
        self.fill(p, 400)
        self.assertEqual(self.settle(p).value['account_deltas'][0]['sellable'], 400)
        self.reject('LATE_FILL_AFTER_SETTLEMENT', self.fill, p, 600, identity='late')
        self.assertTrue(self.app.snapshot(p.preview_id).value['restricted'])
        self.reject('ACCOUNT_RESTRICTED', self.order)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])

    def test_legacy_cumulative_fill_does_not_invent_lots(self):
        p = self.order()
        self.app.simulate_fill(p.preview_id, cumulative_filled=1000, now=NOW)
        self.reject('FILL_LOT_HISTORY_UNVERIFIED', self.settle, p)

    def test_restriction_has_no_forced_liquidation(self):
        p = self.order(funding=Funding.LEND_SELLING)
        self.app.restrict(p.preview_id, RestrictionEvidence('recall', p.draft.account_id, 'BORROW_RECALL', NOW), now=NOW)
        self.reject('ACCOUNT_RESTRICTED', self.order)
        self.assertTrue(self.app.snapshot(p.preview_id).value['restricted'])

    def test_missing_policy_wrong_receipt_and_nonfinite_money(self):
        p = self.order()
        for price in (D('NaN'), D('Infinity'), 25, True):
            self.reject('INVALID_DECIMAL', self.app.record_fill,
                        FillLot('bad', p.preview_id, 1000, price, NOW), now=NOW)
        self.fill(p)
        receipt = self.receipt(p)
        fees, interest = self.policies(p)
        self.reject('COST_POLICY_UNVERIFIED', self.app.settle, p.preview_id, receipt, fees=None, interest=interest, now=NOW)
        for changed in (replace(receipt, session_id='different'), replace(receipt, account_id='synthetic-other'),
                        replace(receipt, fills_digest='0' * 64)):
            self.reject('FINALITY_SCOPE_MISMATCH', self.app.settle, p.preview_id, changed,
                        fees=fees, interest=interest, now=NOW)
        self.reject('LATE_FILL_RISK_UNVERIFIED', self.app.settle, p.preview_id,
                    replace(receipt, no_outstanding_late_fills=False), fees=fees, interest=interest, now=NOW)
        self.assertFalse(self.app.snapshot(p.preview_id).value['reservation_released'])

    def test_crash_atomicity_restart_and_concurrent_duplicate(self):
        p = self.order()
        with self.assertRaises(SimulatedCrash):
            self.fill(p, crash_at='before_commit')
        self.assertEqual(self.app.snapshot(p.preview_id).value['fills'], ())
        lot = self.fill(p)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: SimulationApplication(self.box).record_fill(lot, now=NOW), range(3)))
        with self.assertRaises(SimulatedCrash):
            self.settle(p, crash_at='before_commit')
        self.assertFalse(self.app.snapshot(p.preview_id).value['reservation_released'])
        with self.assertRaises(SimulatedCrash):
            self.settle(p, crash_at='after_commit')
        with reopen_sandbox(self.box.ticket()) as reopened:
            app = SimulationApplication(reopened)
            self.assertTrue(app.snapshot(p.preview_id).value['reservation_released'])
            self.assertTrue(app.verify().value['verified'])

    def test_projection_corruption_and_read_only_lookup(self):
        p = self.order()
        self.fill(p)
        self.settle(p)
        before = self.box.database.read_bytes()
        self.app.snapshot(p.preview_id)
        self.app.status(p.preview_id)
        self.reject('UNKNOWN_PREVIEW', self.app.snapshot, 'missing')
        self.assertEqual(before, self.box.database.read_bytes())
        with connection(self.box) as db:
            db.execute('UPDATE settlement_projection SET payload=?', (dumps({}),))
        self.reject('SETTLEMENT_PROJECTION_MISMATCH', SimulationApplication, self.box)

    def test_bounded_quota_rejection_does_not_grow_journal(self):
        p = self.order()
        before = self.box.database.read_bytes()
        with patch('execution_simulation.settlement.MAX_AUDIT_ROWS', 1):
            for _ in range(3):
                self.reject('SYNTHETIC_JOURNAL_QUOTA', self.app.query, p.preview_id, now=NOW)
        self.assertEqual(before, self.box.database.read_bytes())

    def test_v1_clone_preserves_private_bytes_and_migration_crashes(self):
        app = SimulationApplication(self.source)
        p = app.preview(*expanded_fixture(), now=NOW).value
        app.confirm(confirmation(p), now=NOW)
        original = self.source.database.read_bytes()
        with connection(self.source, readonly=True) as db:
            rows = [tuple(r) for r in db.execute('SELECT * FROM audit')]
        for boundary in ('before_commit', 'after_commit'):
            with self.assertRaises(SimulatedCrash):
                with settlement_sandbox_clone(self.source, crash_at=boundary):
                    self.fail('crash expected')
            self.assertEqual(original, self.source.database.read_bytes())
        with settlement_sandbox_clone(self.source) as clone:
            with connection(clone, readonly=True) as db:
                self.assertEqual(rows, [tuple(r) for r in db.execute('SELECT * FROM audit')])
            self.assertTrue(SimulationApplication(clone).verify().value['verified'])
        self.assertEqual(original, self.source.database.read_bytes())

    def test_zero_baseline_acquired_positions_can_close_all_modes(self):
        for funding in Funding:
            with self.subTest(funding=funding):
                p = self.order(funding=funding, position=0)
                self.fill(p)
                self.settle(p)
                q = self.order(funding=funding, action=PositionAction.CLOSE, position=0)
                self.fill(q)
                self.settle(q, opening=p.preview_id if funding is not Funding.CASH else None,
                            ack='ack-' + p.preview_id if funding is not Funding.CASH else None)
        self.assertTrue(self.app.verify().value['verified'])

    def test_settled_sale_cross_symbol_allows_above_original_cash(self):
        p = self.order(action=PositionAction.CLOSE, cash=D('1000'))
        self.fill(p)
        self.settle(p)
        q = self.order(cash=D('1000'), symbol='FAKEOTHER')
        self.fill(q)
        self.settle(q)
        self.reject('INSUFFICIENT_CASH', self.order, cash=D('1000'), symbol='FAKEOTHER')

    def test_dispatch_restriction_before_claim_and_effect(self):
        p = self.order(dispatch=False)
        block = RestrictionEvidence('recall', p.draft.account_id, 'BORROW_RECALL', NOW)
        self.app.restrict(p.preview_id, block, now=NOW)
        self.reject('ACCOUNT_RESTRICTED', self.app.dispatch, p.preview_id, now=NOW)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mock_effects').fetchone()[0], 0)

    def test_restriction_between_claim_and_effect_is_fenced(self):
        p = self.order(dispatch=False)
        original = self.app._crash
        def inject(actual, boundary):
            if boundary == 'after_claim':
                self.app.restrict(p.preview_id,
                    RestrictionEvidence('call', p.draft.account_id, 'MARGIN_CALL', NOW), now=NOW)
            return original(actual, boundary)
        with patch.object(self.app, '_crash', side_effect=inject):
            self.reject('ACCOUNT_RESTRICTED', self.app.dispatch, p.preview_id, now=NOW)
        with connection(self.box, readonly=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mock_effects').fetchone()[0], 0)

    def test_account_restriction_does_not_block_other_account_settle(self):
        p = self.order()
        q = self.order(account_id='synthetic-account-B')
        self.fill(q)
        self.app.restrict(p.preview_id, RestrictionEvidence('recall', p.draft.account_id, 'BORROW_RECALL', NOW), now=NOW)
        self.assertTrue(self.settle(q).value['reservation_released'])

    def test_decimal_context_stable_with_partial_credit_closes(self):
        p = self.order(funding=Funding.MARGIN, quantity=3000, position=0)
        self.fill(p, 3000)
        with localcontext() as context:
            context.prec = 6
            self.settle(p)
        for _ in range(3):
            q = self.order(funding=Funding.MARGIN, action=PositionAction.CLOSE, position=0)
            self.fill(q)
            with localcontext() as context:
                context.prec = 6
                self.settle(q, opening=p.preview_id, ack='ack-' + q.preview_id)
        b = self.app.snapshot(p.preview_id).value['account_deltas'][0]
        self.assertEqual(b['financing_principal'], D(0))
        self.assertEqual(b['margin_position'], 0)

    def test_late_conflicting_callback_blocks_after_zero_fill_rejection_release(self):
        p = self.order(dispatch=False)
        self.app.dispatch(p.preview_id, fixture=Fixture.REJECT, now=NOW)
        self.assertTrue(self.settle(p).value['reservation_released'])
        event = SimulationEvent('late', p.preview_id, EventKind.FILLED, NOW, 2, 1000, D('25.50'))
        self.reject('LATE_FILL_AFTER_SETTLEMENT', self.app.callback, event, now=NOW)
        self.assertTrue(self.app.snapshot(p.preview_id).value['restricted'])

    def test_root_and_old_prefix_corruption_fail_closed(self):
        p = self.order()
        with connection(self.box) as db:
            db.execute('DROP TRIGGER immutable_audit_UPDATE')
            db.execute("UPDATE audit SET hash=? WHERE seq=1", ('f' * 64,))
        self.reject('AUDIT_CHAIN_BROKEN', SimulationApplication, self.box)

    def test_modified_migration_anchor_and_alternate_sandbox(self):
        with connection(self.box) as db:
            root = loads(db.execute('SELECT payload FROM settlement_root').fetchone()[0])
            db.execute('DROP TRIGGER immutable_settlement_root_UPDATE')
            db.execute('UPDATE settlement_root SET payload=?', (dumps(dict(root, head='f' * 64)),))
        self.reject('SETTLEMENT_ROOT_MISMATCH', SimulationApplication, self.box)
        with settlement_sandbox_clone(self.source) as alternate:
            with connection(alternate) as db:
                db.execute('DROP TRIGGER immutable_settlement_root_UPDATE')
                db.execute('UPDATE settlement_root SET payload=?', (dumps(root),))
            self.reject('SANDBOX_ROOT_MISMATCH', SimulationApplication, alternate)

    def test_insolvent_short_fee_is_blocked_not_released(self):
        p = self.order(funding=Funding.SHORT_SELLING, cash=D('20'))
        self.fill(p)
        fees, interest = self.policies(p)
        self.reject('RESERVATION_INTEGRITY', self.app.settle, p.preview_id, self.receipt(p),
                    fees=replace(fees, commission_rate=D('0.1')), interest=interest, now=NOW)
        snapshot = self.app.snapshot(p.preview_id).value
        self.assertFalse(snapshot['reservation_released'])
        self.assertTrue(snapshot['restricted'])

    def test_concurrent_distinct_lots_and_close_open_admission(self):
        p = self.order(position=0, cash=D('26000'))
        lots = [FillLot('parallel-' + str(i), p.preview_id, 500, D('25'), NOW) for i in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda lot: SimulationApplication(self.box).record_fill(lot, now=NOW), lots))
        self.settle(p)
        q = self.order(action=PositionAction.CLOSE, position=0, cash=D('26000'))
        self.reject('INSUFFICIENT_SELLABLE', self.order, action=PositionAction.CLOSE, position=0, cash=D('26000'))
        self.fill(q)
        self.settle(q)
        self.order(position=0, cash=D('26000'))

    def test_reverse_fill_identity_order_survives_settlement_replay(self):
        p = self.order()
        self.fill(p, 500, '25', 'z-first')
        self.fill(p, 500, '25', 'a-second')
        self.settle(p)
        self.assertTrue(SimulationApplication(self.box).verify().value['verified'])
        self.assertEqual([lot.event_id for lot in self.app.snapshot(p.preview_id).value['fills']],
                         ['a-second', 'z-first'])

    def test_coarse_fee_quantum_cannot_round_up_returned_proceeds(self):
        p = self.order(funding=Funding.SHORT_SELLING)
        self.fill(p, 1)
        self.app.cancel(p.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(p.preview_id, kind='CANCEL', fixture=Fixture.CANCEL, now=NOW)
        fees, interest = self.policies(p)
        fees, interest = replace(fees, money_quantum=D('1')), replace(interest, money_quantum=D('1'))
        self.app.settle(p.preview_id, self.receipt(p), fees=fees, interest=interest, now=NOW)
        q = self.order(funding=Funding.SHORT_SELLING, action=PositionAction.CLOSE)
        self.fill(q, 1)
        self.app.cancel(q.preview_id, now=NOW, user_confirmed=True)
        self.app.dispatch(q.preview_id, kind='CANCEL', fixture=Fixture.CANCEL, now=NOW)
        b = self.app.settle(q.preview_id, self.receipt(q, opening=p.preview_id, ack='ack'),
            fees=fees, interest=interest, now=NOW).value['account_deltas'][0]
        self.assertEqual(b['cash'], D(0))
        self.assertEqual(b['restricted_proceeds'], D(0))
        self.assertEqual(b['borrowed_shares'], 0)

    def test_actual_process_death_before_and_after_settlement_commit(self):
        p = self.order()
        self.fill(p)
        ticket = self.box.ticket()
        args = [sys.executable, '-B', '-m', 'execution_simulation.tests.settlement_process_worker',
                ticket.directory, ticket.token, p.preview_id]
        for boundary in ('before_commit', 'after_commit'):
            child = subprocess.run(args + [boundary], capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 73, child.stderr)
            child = subprocess.run(args + ['verify'], capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(self.app.snapshot(p.preview_id).value['reservation_released'], boundary == 'after_commit')

    def test_lifecycle_and_receipt_time_scope_fail_closed(self):
        p = self.order(dispatch=False)
        self.assertEqual(self.app.snapshot(p.preview_id).value['lifecycle'], 'ORDER_CONFIRM')
        self.app.dispatch(p.preview_id, now=NOW)
        self.assertEqual(self.app.snapshot(p.preview_id).value['lifecycle'], 'BROKER_MOCK_ACCEPT')
        self.fill(p)
        self.assertEqual(self.app.snapshot(p.preview_id).value['lifecycle'], 'TRADE_FILL')
        receipt, (fees, interest) = self.receipt(p), self.policies(p)
        for changed, code in (
            (replace(receipt, eligible_at=NOW + timedelta(seconds=1)), 'SETTLEMENT_NOT_ELIGIBLE'),
            (replace(receipt, valid_until=NOW), 'SETTLEMENT_EVIDENCE_EXPIRED'),
            (replace(receipt, instrument=replace(p.draft.instrument, symbol='OTHER')), 'FINALITY_SCOPE_MISMATCH'),
            (replace(receipt, preview_digest='0' * 64), 'FINALITY_SCOPE_MISMATCH'),
        ):
            self.reject(code, self.app.settle, p.preview_id, changed, fees=fees, interest=interest, now=NOW)
        self.settle(p)
        self.assertEqual(self.app.snapshot(p.preview_id).value['lifecycle'], 'SETTLED')

    def test_policy_evidence_conflict_and_missing_interest(self):
        p = self.order()
        self.fill(p)
        self.settle(p)
        q = self.order()
        self.fill(q)
        fees, interest = self.policies(q)
        self.reject('COST_POLICY_UNVERIFIED', self.app.settle, q.preview_id, self.receipt(q),
                    fees=fees, interest=None, now=NOW)
        self.reject('POLICY_EVIDENCE_CONFLICT', self.app.settle, q.preview_id, self.receipt(q),
                    fees=replace(fees, commission_rate=D('0')), interest=interest, now=NOW)

    def test_close_requires_accrual_through_settlement_and_ack_unique(self):
        p = self.order(funding=Funding.MARGIN, quantity=2000, position=0)
        self.fill(p, 2000)
        self.settle(p)
        now = NOW + timedelta(seconds=1)
        q = self.order(funding=Funding.MARGIN, action=PositionAction.CLOSE, position=0, now=now)
        self.fill(q, now=now)
        self.reject('ACCRUAL_REQUIRED', self.settle, q, opening=p.preview_id, ack='ack', now=now)
        self.app.accrue(AccrualTick('period', p.preview_id, NOW, now), now=now)
        self.settle(q, opening=p.preview_id, ack='ack', now=now)
        r = self.order(funding=Funding.MARGIN, action=PositionAction.CLOSE, position=0, now=now)
        self.fill(r, now=now)
        self.reject('LENDER_ACK_REUSED', self.settle, r, opening=p.preview_id, ack='ack', now=now)

    def test_out_of_order_fill_does_not_enter_lot_ledger(self):
        p = self.order()
        now = NOW + timedelta(seconds=1)
        self.fill(p, 400, identity='first', now=now)
        self.reject('REPORT_TIME_REGRESSION', self.app.record_fill,
                    FillLot('delayed', p.preview_id, 600, D('25.50'), NOW), now=now)
        self.assertEqual(len(self.app.snapshot(p.preview_id).value['fills']), 1)
        self.assertFalse(self.app.snapshot(p.preview_id).value['reservation_released'])

    def test_materialized_release_corruption_fails_closed(self):
        p = self.order()
        self.fill(p)
        self.settle(p)
        with connection(self.box) as db:
            db.execute('DROP TRIGGER immutable_releases_UPDATE')
            db.execute("UPDATE releases SET receipt_id='corrupt'")
        self.reject('RELEASE_PROJECTION_MISMATCH', SimulationApplication, self.box)


if __name__ == '__main__':
    unittest.main()
