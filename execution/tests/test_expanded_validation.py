from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
from itertools import product
import unittest
from unittest.mock import patch

from execution.contracts import (
    Asset, Capability, EventKind, ExecutionRejected, Funding, Lot, OrderKind,
    PositionAction, Side, SimulationEvent, TradingPhase, Venue,
)
from execution.validation import assess, digest_of
from execution.tests.expanded_fixtures import expanded_fixture
from execution.tests.fixtures import NOW, confirmation, fixture, service


class ExpandedValidationTests(unittest.TestCase):
    def reject(self, draft, evidence, code=None):
        with self.assertRaises(ExecutionRejected) as caught:
            assess(draft, evidence, NOW)
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_full_mode_matrix(self):
        # Each exact security/venue has its own synthetic allowlisted policy.
        for funding, action, kind, asset, venue in product(
                Funding, PositionAction, OrderKind, Asset, Venue):
            with self.subTest(funding=funding, action=action, kind=kind, asset=asset, venue=venue):
                d, e = expanded_fixture(funding=funding, action=action, kind=kind, asset=asset, venue=venue)
                result = assess(d, e, NOW)
                self.assertGreater(result.resources.risk_notional, 0)
                self.assertEqual(d.limit_price is None, kind is OrderKind.MARKET)
                self.assertTrue(d.simulated and d.test_only)
                self.assertFalse(d.broker_connected)
                self.reject(replace(d, side=Side.SELL if d.side is Side.BUY else Side.BUY), e,
                            'SIDE_POSITION_MISMATCH')

    def test_cash_market_worst_case_and_no_credit_needed(self):
        d, e = expanded_fixture(kind=OrderKind.MARKET)
        e = replace(e, account=replace(e.account, credit=None))
        a = assess(d, e, NOW)
        self.assertEqual(a.required_cash, D('90020'))
        self.reject(d, replace(e, account=replace(e.account, available_cash=D('25520'))), 'INSUFFICIENT_CASH')
        d, e = expanded_fixture(kind=OrderKind.MARKET, action=PositionAction.CLOSE)
        a = assess(d, e, NOW)
        self.assertEqual((a.resources.proceeds_floor, a.resources.risk_notional), (D('10000'), D('90000')))

    def test_margin_credit_and_short_collateral_not_sale_proceeds(self):
        d, e = expanded_fixture(funding=Funding.MARGIN, kind=OrderKind.MARKET)
        a = assess(d, e, NOW)
        self.assertEqual((a.required_cash, a.resources.credit), (D('36020'), D('54000')))
        for funding in (Funding.SHORT_SELLING, Funding.LEND_SELLING):
            d, e = expanded_fixture(funding=funding, kind=OrderKind.MARKET)
            a = assess(d, e, NOW)
            self.assertEqual((a.resources.collateral, a.resources.proceeds_floor), (D('108000'), D('10000')))
            self.assertEqual(a.resources.sellable, 0)
            self.assertEqual(a.required_cash, D('20'))

    def test_missing_credit_borrow_collateral_and_positions(self):
        for funding in (Funding.MARGIN, Funding.SHORT_SELLING, Funding.LEND_SELLING):
            d, e = expanded_fixture(funding=funding)
            self.reject(d, replace(e, account=replace(e.account, credit=None)), 'CREDIT_UNVERIFIED')
            for field, value in (('available_credit', None), ('available_collateral', None),
                                 ('margin_cash_ratio', None), ('maintenance_ratio', None),
                                 ('short_borrow_available', None), ('lend_borrow_available', None)):
                self.reject(d, replace(e, account=replace(e.account, credit=replace(e.account.credit, **{field: value}))))
        cases = ((Funding.MARGIN, PositionAction.OPEN, 'available_credit', D(0), 'INSUFFICIENT_CREDIT'),
                 (Funding.SHORT_SELLING, PositionAction.OPEN, 'short_borrow_available', 0, 'INSUFFICIENT_BORROW'),
                 (Funding.LEND_SELLING, PositionAction.OPEN, 'lend_borrow_available', 0, 'INSUFFICIENT_BORROW'),
                 (Funding.SHORT_SELLING, PositionAction.OPEN, 'available_collateral', D(0), 'INSUFFICIENT_COLLATERAL'),
                 (Funding.MARGIN, PositionAction.CLOSE, 'margin_position', 0, 'INSUFFICIENT_MARGIN_POSITION'),
                 (Funding.SHORT_SELLING, PositionAction.CLOSE, 'short_position', 0, 'INSUFFICIENT_SHORT_POSITION'),
                 (Funding.LEND_SELLING, PositionAction.CLOSE, 'lend_position', 0, 'INSUFFICIENT_SHORT_POSITION'))
        for funding, action, field, value, code in cases:
            d, e = expanded_fixture(funding=funding, action=action)
            self.reject(d, replace(e, account=replace(e.account, credit=replace(e.account.credit, **{field: value}))), code)

    def test_policy_session_security_lot_and_short_restrictions(self):
        for phase in (TradingPhase.OPENING_AUCTION, TradingPhase.CLOSING_AUCTION):
            d, e = expanded_fixture()
            e = replace(e, market=replace(e.market, trade_policy=replace(e.market.trade_policy, phase=phase)))
            assess(d, e, NOW)
            self.reject(replace(d, funding=Funding.MARGIN), e, 'CONTINUOUS_SESSION_REQUIRED')
        for venue in Venue:
            d, e = expanded_fixture(kind=OrderKind.MARKET, venue=venue)
            self.reject(d, replace(e, market=replace(e.market, trade_policy=None)), 'POLICY_UNVERIFIED')
            policy = e.market.trade_policy
            for field, value in (('phase', TradingPhase.OPENING_AUCTION), ('phase', TradingPhase.CLOSING_AUCTION),
                                 ('phase', TradingPhase.UNKNOWN), ('phase', 'market_continuous'),
                                 ('regular_security', False), ('authoritative_session', False),
                                 ('session_id', 'previous-session'), ('market_orders', Capability.UNVERIFIED),
                                 ('market_orders', Capability.DENIED), ('market_orders', 'ALLOWED')):
                self.reject(d, replace(e, market=replace(e.market, trade_policy=replace(policy, **{field: value}))))
        for funding, kind in product(Funding, OrderKind):
            d, e = expanded_fixture(funding=funding, kind=kind, lot=Lot.ODD)
            if funding is Funding.CASH and kind is OrderKind.LIMIT:
                assess(d, e, NOW)
            else:
                self.reject(d, e, 'LOT_CAPABILITY_UNVERIFIED')
        for funding in (Funding.SHORT_SELLING, Funding.LEND_SELLING):
            d, e = expanded_fixture(funding=funding, kind=OrderKind.MARKET)
            e = replace(e, market=replace(e.market, trade_policy=replace(e.market.trade_policy, short_below_reference=False)))
            self.reject(d, e, 'SHORT_MARKET_RESTRICTED')
            self.reject(replace(d, order_kind=OrderKind.LIMIT, limit_price=D('24')), e, 'SHORT_PRICE_RESTRICTED')
            assess(replace(d, order_kind=OrderKind.LIMIT, limit_price=D('25')), e, NOW)

    def test_expiry_owner_and_identity_fail_closed(self):
        d, e = expanded_fixture(funding=Funding.SHORT_SELLING)
        for target in ('policy', 'credit'):
            original = e.market.trade_policy if target == 'policy' else e.account.credit
            for ref in (replace(original.ref, valid_until=NOW), replace(original.ref, owner='provider'),
                        replace(original.ref, observed_at=NOW + timedelta(seconds=1)),
                        replace(original.ref, origin='SYNTHETIC')):
                changed = replace(original, ref=ref)
                bad = replace(e, market=replace(e.market, trade_policy=changed)) if target == 'policy' else replace(
                    e, account=replace(e.account, credit=changed))
                self.reject(d, bad)
            for field, value in (('instrument', replace(d.instrument, venue=Venue.TPEX)),
                                 ('instrument', replace(d.instrument, symbol='other')), ('version', '')):
                changed = replace(original, **{field: value})
                bad = replace(e, market=replace(e.market, trade_policy=changed)) if target == 'policy' else replace(
                    e, account=replace(e.account, credit=changed))
                self.reject(d, bad)
        self.reject(d, replace(e, account=replace(e.account, credit=replace(e.account.credit, account_id='other'))))
        self.reject(d, replace(e, market=replace(e.market, trade_policy=replace(e.market.trade_policy, lot=Lot.ODD))))

    def test_auth_maintenance_entitlement_intraday_limits(self):
        d, e = expanded_fixture(funding=Funding.MARGIN)
        for field, value in (('authenticated', False), ('allowed_funding', frozenset({Funding.CASH})),
                             ('maximum_intraday_risk', None), ('used_intraday_risk', None),
                             ('maximum_intraday_risk', D('1')), ('used_intraday_risk', D('10000000'))):
            self.reject(d, replace(e, permission=replace(e.permission, **{field: value})))
        for field, value in (('authenticated', False), ('maintenance_ratio', D('1')),
                             ('margin_cash_ratio', D('1.01')), ('short_collateral_ratio', D('NaN'))):
            self.reject(d, replace(e, account=replace(e.account, credit=replace(e.account.credit, **{field: value}))))

    def test_snapshot_binding_and_eligibility_not_asset_or_venue_inference(self):
        for funding, field in ((Funding.MARGIN, 'margin'), (Funding.SHORT_SELLING, 'short_selling'),
                               (Funding.LEND_SELLING, 'lend_selling')):
            for asset, venue, capability in product(Asset, Venue, (Capability.UNVERIFIED, Capability.DENIED)):
                d, e = expanded_fixture(funding=funding, asset=asset, venue=venue)
                self.reject(d, replace(e, market=replace(e.market, trade_policy=replace(
                    e.market.trade_policy, **{field: capability}))), 'CAPABILITY_' + capability.value)
        d, e = expanded_fixture(funding=Funding.MARGIN)
        self.reject(d, replace(e, market=replace(e.market, trade_policy=replace(
            e.market.trade_policy, market_snapshot_id='previous'))), 'SESSION_UNVERIFIED')
        self.reject(d, replace(e, account=replace(e.account, credit=replace(
            e.account.credit, account_snapshot_id='previous'))), 'CREDIT_IDENTITY_MISMATCH')
        self.reject(d, replace(e, market=replace(e.market, ref=replace(e.market.ref,
            observed_at=NOW))), 'SESSION_UNVERIFIED')

    def test_rejection_has_typed_denied_or_unverified_outcome(self):
        d, e = expanded_fixture(kind=OrderKind.MARKET)
        with self.assertRaises(ExecutionRejected) as caught:
            assess(d, replace(e, market=replace(e.market, trade_policy=None)), NOW)
        self.assertIs(caught.exception.outcome, Capability.UNVERIFIED)
        with self.assertRaises(ExecutionRejected) as caught:
            assess(replace(d, limit_price=D('25')), e, NOW)
        self.assertIs(caught.exception.outcome, Capability.DENIED)
        d, e = expanded_fixture()  # Even an unused capability must be well typed.
        for field in ('market_orders', 'margin', 'short_selling', 'lend_selling'):
            self.reject(d, replace(e, market=replace(e.market, trade_policy=replace(
                e.market.trade_policy, **{field: None}))), 'CAPABILITY_UNVERIFIED')

    def test_price_quantity_and_version_semantics(self):
        d, e = expanded_fixture(kind=OrderKind.MARKET)
        for price in (D('25.5'), D(0), 'MKT'):
            self.reject(replace(d, limit_price=price), e, 'MARKET_PRICE_MUST_BE_UNSPECIFIED')
        for quantity in (True, 0, -1, 1000.0, '1000', 1001):
            self.reject(replace(d, quantity=quantity), e)
        for version in (1, True, 3):
            self.reject(replace(d, contract_version=version), e)
        for tif in ('DAY', 'ROD', 'IOC', 'FOK', None):
            self.reject(replace(d, time_in_force=tif), e, 'UNSUPPORTED_ORDER')
        for field, value in (('minimum_price', None), ('maximum_price', None), ('maximum_price', D('Infinity')),
                             ('maximum_price', D('9')), ('maximum_price', D('89.99')), ('tick_bands', ())):
            self.reject(d, replace(e, market=replace(e.market, **{field: value})))
        self.reject(replace(d, order_kind=OrderKind.LIMIT), e, 'INVALID_DECIMAL')
        d, e = expanded_fixture()
        for price in (None, 25.5, D('NaN'), D('25.51'), D('100')):
            self.reject(replace(d, limit_price=price), e)
        old, old_evidence = fixture()
        self.reject(old, e, 'INSTRUMENT_MISMATCH')
        self.reject(replace(d, contract_version=1, position_action=None), e, 'EXPANDED_CONTRACT_REQUIRED')
        assess(old, old_evidence, NOW)

    def test_decimal_context_and_complete_evidence_digest(self):
        d, e = expanded_fixture(funding=Funding.MARGIN, kind=OrderKind.MARKET)
        expected = assess(d, e, NOW)
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(assess(d, e, NOW), expected)
        self.assertNotEqual(digest_of(e), digest_of(replace(e, account=replace(
            e.account, credit=replace(e.account.credit, version='synthetic-new')))))

    def test_m1_workflow_partial_fills_and_price_guard_no_io(self):
        with patch('socket.socket', side_effect=AssertionError('NO NETWORK')), \
                patch('builtins.open', side_effect=AssertionError('NO IO')):
            d, e = expanded_fixture(kind=OrderKind.MARKET)
            app = service()
            p = app.preview(d, e, now=NOW)
            app.confirm(p, confirmation(p), now=NOW)
            app.apply(SimulationEvent('accepted', p.preview_id, EventKind.ACCEPTED, NOW, 1), now=NOW)
            for price in (None, D('91'), D('9'), D('25.51')):
                with self.assertRaises(ExecutionRejected):
                    app.apply(SimulationEvent('bad', p.preview_id, EventKind.PARTIAL_FILL, NOW, 2, 500, price), now=NOW)
            app.apply(SimulationEvent('partial', p.preview_id, EventKind.PARTIAL_FILL, NOW, 2, 500, D('90')), now=NOW)
            self.assertEqual(app.result(p.preview_id).cumulative_filled, 500)
