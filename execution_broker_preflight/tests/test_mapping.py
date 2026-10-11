from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
import unittest

from execution_broker_preflight.contracts import (
    Action, Funding, Intent, Lot, PriceKind, Proof, RiskFixture, Session, TimeInForce,
)
from execution_broker_preflight.mapping import BrokerCapabilityMatrix, POLICY_20261010, preview
from execution_broker_preflight.tests.fixtures import NOW, ORDER, RISK, UNITS


class MappingTests(unittest.TestCase):
    def check(self, order=ORDER, risk=RISK, units=UNITS, policy=POLICY_20261010, now=NOW):
        return preview(order, risk, units, policy, now)

    def blocked(self, result, code=None):
        self.assertEqual(result.status, "BLOCKED")
        self.assertIsNone(result.labels)
        if code:
            self.assertIn(code, result.reasons)

    def test_exact_mapping_matrix_all_combinations(self):
        accepted = {(Funding.CASH, Action.BUY, Intent.OPEN): "CASH",
                    (Funding.CASH, Action.SELL, Intent.CLOSE): "CASH",
                    (Funding.MARGIN, Action.BUY, Intent.OPEN): "MARGIN",
                    (Funding.CREDIT_SHORT, Action.SELL, Intent.OPEN): "SHORT_SELLING",
                    (Funding.BORROWED_SHORT, Action.SELL, Intent.OPEN): "Lend_SELLING"}
        for funding in Funding:
            for action in Action:
                for intent in Intent:
                    with self.subTest(funding=funding, action=action, intent=intent):
                        result = self.check(replace(ORDER, funding=funding, action=action, intent=intent))
                        key = funding, action, intent
                        if key not in accepted:
                            self.blocked(result)
                        else:
                            self.assertEqual(result.labels.order_cond, accepted[key])
                            self.assertEqual(result.labels.action, "Buy" if action is Action.BUY else "Sell")
                            self.assertEqual(result.runtime_gate, "BLOCKED_UNVERIFIED")

    def test_matrix_has_explicit_ambiguous_close_reasons(self):
        rows = BrokerCapabilityMatrix().rows
        for funding in (Funding.MARGIN, Funding.CREDIT_SHORT, Funding.BORROWED_SHORT):
            self.assertTrue(next(r for r in rows if r.funding is funding and r.intent is Intent.CLOSE).block_reason)

    def test_no_default_evidence(self):
        bare = RiskFixture(ORDER.scope, RISK.observed_at, RISK.expires_at, Session.CONTINUOUS)
        self.blocked(self.check(risk=bare, units=None))

    def test_each_required_account_risk_gate_unknown_denied_or_fake_bool(self):
        for name in ("account_enabled", "api_agreement", "ca_certificate", "entitlement",
                     "sdk_compatibility", "session_coexistence", "instrument_tradable", "risk_limits", "tick_and_price_bounds",
                     "position_or_credit", "collateral_settlement"):
            for value in (Proof.UNKNOWN, Proof.DENIED, True, "SYNTHETIC_VERIFIED"):
                with self.subTest(name=name, value=value):
                    self.blocked(self.check(risk=replace(RISK, **{name: value})))

    def test_scope_identity_currency_and_subaccount(self):
        for name in ("entity", "account", "subaccount", "currency", "symbol", "venue"):
            self.blocked(self.check(risk=replace(RISK, scope=replace(RISK.scope, **{name: "OTHER"}))))
        self.blocked(self.check(replace(ORDER, scope=replace(ORDER.scope, subaccount=""))))
        scope = replace(ORDER.scope, currency="CNY")
        self.blocked(self.check(replace(ORDER, scope=scope), replace(RISK, scope=scope), replace(UNITS, scope=scope)))

    def test_no_hardcoded_unit_conversion(self):
        self.assertEqual(self.check().labels.sdk_qty, 4)
        self.blocked(self.check(units=None), "BROKER_QUANTITY_UNIT_UNVERIFIED")
        self.blocked(self.check(units=replace(UNITS, verification=Proof.UNKNOWN)))
        for value in (0, -1, True, 1.5, "3"):
            self.blocked(self.check(units=replace(UNITS, shares_per_sdk_qty=value)))
        self.blocked(self.check(replace(ORDER, shares=13)), "NONINTEGRAL_BROKER_QUANTITY")
        self.blocked(self.check(units=replace(UNITS, sdk_version="")))

    def test_market_exact_sentinel_and_all_tifs(self):
        for tif in TimeInForce:
            order = replace(ORDER, price_kind=PriceKind.MARKET, price="kgi.PriceType.MKT", time_in_force=tif)
            self.assertEqual(self.check(order).labels.price, "kgi.PriceType.MKT")
            self.assertEqual(self.check(order).labels.time_in_force, tif.value)
            for price in (0, Decimal(0), "0", "LimitUp", "kgi.PriceType.LimitUp", None):
                self.blocked(self.check(replace(order, price=price)), "MARKET_REQUIRES_MKT_SENTINEL_LABEL")

    def test_limit_decimal_no_coercion(self):
        for price in (True, 25.0, "25", Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(-1)):
            self.blocked(self.check(replace(ORDER, price=price)))

    def test_unknown_enums_schema_approval_and_live_input(self):
        for field, value in (("action", "BUY"), ("funding", "CASH"), ("lot", "Common"),
                             ("shares", True), ("approved", 1), ("schema", "future"), ("mode", "LIVE")):
            self.blocked(self.check(replace(ORDER, **{field: value})))
        self.blocked(self.check(policy=replace(POLICY_20261010, version="future")))
        self.blocked(self.check(policy=replace(POLICY_20261010, runtime_sdk="verified")))

    def test_session_boundaries_auction_and_closed(self):
        market = replace(ORDER, price_kind=PriceKind.MARKET, price="kgi.PriceType.MKT")
        for minute in (539, 805, 810):
            now = NOW.replace(hour=minute // 60 - 8, minute=minute % 60)
            risk = replace(RISK, observed_at=now, expires_at=now + timedelta(seconds=30))
            self.blocked(self.check(market, risk, now=now), "CONTINUOUS_CLOCK_MISMATCH")
        for session, hour, minute in ((Session.OPEN_AUCTION, 0, 45), (Session.CLOSE_AUCTION, 5, 26)):
            now = NOW.replace(hour=hour, minute=minute)
            risk = replace(RISK, session=session, observed_at=now, expires_at=now + timedelta(seconds=30))
            self.assertIsNotNone(self.check(ORDER, risk, now=now).labels)
            self.blocked(self.check(market, risk, now=now), "AUCTION_LIMIT_ROD_ONLY")
            self.blocked(self.check(replace(ORDER, time_in_force=TimeInForce.IOC), risk, now=now))
        self.blocked(self.check(risk=replace(RISK, session=Session.CLOSED)))

    def test_disposition_no_price_limit_and_unknown(self):
        market = replace(ORDER, price_kind=PriceKind.MARKET, price="kgi.PriceType.MKT")
        for field, values in (("has_price_limit", (None, False, 1)), ("extended_matching", (None, True, 0))):
            for value in values:
                self.blocked(self.check(market, replace(RISK, **{field: value})))
        self.blocked(self.check(replace(ORDER, time_in_force=TimeInForce.IOC), replace(RISK, extended_matching=True)))

    def test_short_market_reference_flags_credit_borrow_and_terms(self):
        for funding in (Funding.CREDIT_SHORT, Funding.BORROWED_SHORT):
            order = replace(ORDER, funding=funding, action=Action.SELL, price_kind=PriceKind.MARKET, price="kgi.PriceType.MKT")
            for flag in (None, False):
                self.blocked(self.check(order, replace(RISK, short_below_reference_allowed=flag)))
            for field in ("short_eligibility", "credit_terms"):
                self.blocked(self.check(order, replace(RISK, **{field: Proof.UNKNOWN})))
            limit = replace(order, price_kind=PriceKind.LIMIT, price=Decimal(25))
            self.blocked(self.check(limit, replace(RISK, short_below_reference_allowed=False, short_reference=Decimal(26))))
            self.assertIsNotNone(self.check(limit, replace(RISK, short_below_reference_allowed=False, short_reference=Decimal(25))).labels)
        self.blocked(self.check(order, replace(RISK, borrow_allocation=Proof.UNKNOWN)))

    def test_odd_and_after_hours(self):
        order = replace(ORDER, lot=Lot.ODD, shares=2)
        units = replace(UNITS, lot=Lot.ODD, shares_per_sdk_qty=1)
        risk = replace(RISK, session=Session.ODD)
        self.assertEqual(self.check(order, risk, units).labels.odd_lot, "Odd")
        for changed in (replace(order, shares=3), replace(order, funding=Funding.MARGIN),
                        replace(order, price_kind=PriceKind.MARKET, price="kgi.PriceType.MKT"),
                        replace(order, time_in_force=TimeInForce.FOK)):
            self.blocked(self.check(changed, risk, units))
        for lot in (Lot.FIXING, Lot.AFTER_ODD):
            self.blocked(self.check(replace(order, lot=lot), risk, replace(units, lot=lot)))

    def test_time_freshness_and_naive_rejected(self):
        self.blocked(self.check(now=NOW + timedelta(minutes=1)))
        self.blocked(self.check(now=NOW.replace(tzinfo=None)))
        self.blocked(self.check(risk=replace(RISK, expires_at=NOW + timedelta(days=1))))

    def test_tpex_board_supported_but_odd_policy_unknown(self):
        scope = replace(ORDER.scope, venue="TPEX")
        order, risk, units = replace(ORDER, scope=scope), replace(RISK, scope=scope), replace(UNITS, scope=scope)
        self.assertIsNotNone(self.check(order, risk, units).labels)
        self.blocked(self.check(replace(order, lot=Lot.ODD, shares=2), replace(risk, session=Session.ODD),
                                replace(units, lot=Lot.ODD, shares_per_sdk_qty=1)), "TPEX_ODD_POLICY_UNVERIFIED")

    def test_no_financing_rate_defaults(self):
        # This preflight consumes a risk-owner attestation, never computes rates.
        self.assertFalse(any("rate" in f.name for f in fields(RiskFixture)))
        self.blocked(self.check(replace(ORDER, funding=Funding.MARGIN), replace(RISK, credit_terms=Proof.UNKNOWN)))


if __name__ == "__main__":
    unittest.main()
