from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
import unittest

from execution.contracts import Asset, ExecutionRejected, Lot, Side, TickBand, Venue
from execution.validation import assess
from execution.tests.fixtures import NOW, fixture, service


class ValidationTests(unittest.TestCase):
    def rejects(self, draft, evidence, code=None, now=NOW):
        with self.assertRaises(ExecutionRejected) as exc:
            assess(draft, evidence, now)
        if code:
            self.assertEqual(exc.exception.code, code)

    def test_supported_synthetic_matrix(self):
        for asset in Asset:
            for venue in Venue:
                for lot in Lot:
                    for side in Side:
                        with self.subTest(asset=asset, venue=venue, lot=lot, side=side):
                            draft, evidence = fixture(side=side, lot=lot, asset=asset, venue=venue)
                            result = assess(draft, evidence, NOW)
                            self.assertEqual(result.notional, draft.limit_price * draft.quantity)
                            self.assertEqual(result.required_cash,
                                             result.notional + D(20) if side is Side.BUY else D(0))

    def test_unsupported_instruments_and_order_modes(self):
        draft, evidence = fixture()
        for field, values in {
            "market": ["US", "JP", "TW", None],
            "asset": ["FUTURES", "OPTIONS", "BOND", "LEVERAGED", None],
            "venue": ["UNKNOWN", "TWSE", None],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.rejects(replace(draft, instrument=replace(draft.instrument, **{field: value})),
                                 evidence, "UNSUPPORTED_INSTRUMENT")
        for field, values in {
            "side": ["SHORT", "BUY", None], "order_kind": ["MARKET", None],
            "funding": ["MARGIN", "SHORT", None], "time_in_force": ["GTC", "IOC", "FOK"],
            "currency": ["USD", None], "price_unit": ["PER_LOT", None], "lot": ["AFTER_HOURS", None],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.rejects(replace(draft, **{field: value}), evidence, "UNSUPPORTED_ORDER")

    def test_invalid_share_quantities(self):
        draft, evidence = fixture()
        for value in [None, True, False, 0, -1, 1.0, 1000.0, D(1000), "1000", float("nan"), 10**30]:
            with self.subTest(value=value):
                self.rejects(replace(draft, quantity=value), evidence, "INVALID_QUANTITY")

    def test_invalid_prices(self):
        draft, evidence = fixture()
        for value in [None, True, 25, 25.5, "25.50", D("NaN"), D("sNaN"), D("Infinity"),
                      D("-Infinity"), D(0), D(-1), D("1e-100000"), D("1e100000")]:
            with self.subTest(value=value):
                self.rejects(replace(draft, limit_price=value), evidence, "INVALID_DECIMAL")

    def test_invalid_identifiers(self):
        draft, evidence = fixture()
        for field in ("account_id", "client_request_id"):
            for value in (None, "", "a\nb", "a b", "x" * 129):
                with self.subTest(field=field, value=value):
                    self.rejects(replace(draft, **{field: value}), evidence, "INVALID_IDENTIFIER")

    def test_lot_quantity_rules(self):
        for lot, values in ((Lot.BOARD, (1, 999, 1001, 100_001)), (Lot.ODD, (1000, 1001))):
            draft, evidence = fixture(lot=lot)
            for value in values:
                with self.subTest(lot=lot, value=value):
                    self.rejects(replace(draft, quantity=value), evidence)

    def test_tick_band_boundary_and_price_limits(self):
        draft, evidence = fixture()
        for price in ("10", "49.95", "50", "50.10", "90"):
            assess(replace(draft, limit_price=D(price)), evidence, NOW)
        for price, code in (("25.51", "INVALID_PRICE_TICK"), ("50.05", "INVALID_PRICE_TICK"),
                            ("9.95", "PRICE_LIMIT"), ("90.1", "PRICE_LIMIT")):
            self.rejects(replace(draft, limit_price=D(price)), evidence, code)

    def test_rejects_missing_malformed_or_gapped_tick_rules(self):
        draft, evidence = fixture()
        bands = evidence.market.tick_bands
        for value in (None, (), list(bands), (None,),
                      (replace(bands[0], tick=D(0)), bands[1]),
                      (bands[0], replace(bands[1], lower=D(51))),
                      (bands[0], replace(bands[1], lower=D(49))),
                      (bands[0],), tuple(reversed(bands))):
            with self.subTest(value=value):
                self.rejects(draft, replace(evidence, market=replace(evidence.market, tick_bands=value)))

    def test_malformed_lot_rules(self):
        draft, evidence = fixture()
        rule = evidence.market.lot_rule
        for value in (None, replace(rule, step=1), replace(rule, board_size=0),
                      replace(rule, minimum=999), replace(rule, maximum=999),
                      replace(rule, maximum=1001), replace(rule, step=True)):
            with self.subTest(value=value):
                self.rejects(draft, replace(evidence, market=replace(evidence.market, lot_rule=value)))
        draft, evidence = fixture(lot=Lot.ODD)
        for changes in ({"maximum": 1000}, {"minimum": 2}, {"step": 2}):
            self.rejects(draft, replace(evidence, market=replace(
                evidence.market, lot_rule=replace(evidence.market.lot_rule, **changes))))

    def test_identity_price_units_and_account_binding(self):
        draft, evidence = fixture()
        for name in ("market", "account", "permission"):
            part = getattr(evidence, name)
            for field, value in (("symbol", "OTHER"), ("venue", Venue.TPEX), ("asset", Asset.ETF)):
                with self.subTest(name=name, field=field):
                    changed = replace(part, instrument=replace(part.instrument, **{field: value}))
                    self.rejects(draft, replace(evidence, **{name: changed}), "INSTRUMENT_MISMATCH")
        for name in ("account", "permission"):
            self.rejects(draft, replace(evidence, **{name: replace(getattr(evidence, name), account_id="other")}),
                         "ACCOUNT_MISMATCH")
        for name, changes, code in (("market", {"currency": "USD"}, "CURRENCY_MISMATCH"),
                                     ("account", {"currency": "TWD"}, "CURRENCY_MISMATCH"),
                                     ("market", {"price_unit": "PER_LOT"}, "PRICE_UNIT_MISMATCH"),
                                     ("market", {"lot": Lot.ODD}, "LOT_MISMATCH")):
            self.rejects(draft, replace(evidence, **{name: replace(getattr(evidence, name), **changes)}), code)

    def test_missing_evidence_and_refs(self):
        draft, evidence = fixture()
        self.rejects(draft, None, "MISSING_EVIDENCE")
        for name in ("market", "account", "permission"):
            self.rejects(draft, replace(evidence, **{name: None}), "MISSING_EVIDENCE")
            self.rejects(draft, replace(evidence, **{name: replace(getattr(evidence, name), ref=None)}),
                         "MISSING_EVIDENCE")

    def test_all_snapshots_require_owner_synthetic_origin_and_valid_window(self):
        draft, evidence = fixture()
        for name in ("market", "account", "permission"):
            part = getattr(evidence, name)
            for changes, code in (
                ({"origin": "LIVE"}, "SYNTHETIC_ONLY"),
                ({"owner": "portfolio"}, "EVIDENCE_OWNER_MISMATCH"),
                ({"owner": "watchlist"}, "EVIDENCE_OWNER_MISMATCH"),
                ({"observed_at": NOW + timedelta(seconds=1)}, "EVIDENCE_EXPIRED_OR_NOT_YET_VALID"),
                ({"valid_from": NOW + timedelta(seconds=1)}, "EVIDENCE_EXPIRED_OR_NOT_YET_VALID"),
                ({"valid_until": NOW}, "EVIDENCE_EXPIRED_OR_NOT_YET_VALID"),
                ({"valid_until": NOW - timedelta(days=1)}, "EVIDENCE_EXPIRED_OR_NOT_YET_VALID"),
                ({"valid_until": NOW + timedelta(minutes=6)}, "EVIDENCE_WINDOW_TOO_LONG"),
                ({"observed_at": NOW.replace(tzinfo=None)}, "INVALID_TIME"),
                ({"snapshot_id": ""}, "INVALID_IDENTIFIER"),
            ):
                with self.subTest(name=name, changes=changes):
                    changed = replace(part, ref=replace(part.ref, **changes))
                    self.rejects(draft, replace(evidence, **{name: changed}), code)

    def test_no_implicit_timezone_or_clock(self):
        draft, evidence = fixture()
        for now in (None, "2026-10-08", NOW.replace(tzinfo=None)):
            self.rejects(draft, evidence, "INVALID_TIME", now=now)

    def test_unknown_or_false_tradability_active_permission(self):
        draft, evidence = fixture()
        for name, field in (("market", "tradable"), ("market", "order_entry_open"),
                            ("account", "active"), ("permission", "can_trade")):
            for value in (None, False, 1, "true"):
                with self.subTest(name=name, field=field, value=value):
                    self.rejects(draft, replace(evidence, **{
                        name: replace(getattr(evidence, name), **{field: value})}))

    def test_resource_limits_include_buy_fee_reserve(self):
        draft, evidence = fixture()
        for name, changes, code in (
            ("permission", {"maximum_quantity": 999}, "QUANTITY_LIMIT"),
            ("permission", {"maximum_notional": D("25499")}, "NOTIONAL_LIMIT"),
            ("account", {"available_cash": D("25500")}, "INSUFFICIENT_CASH"),
            ("account", {"available_cash": None}, "INVALID_DECIMAL"),
            ("account", {"sellable_quantity": None}, "INVALID_QUANTITY"),
            ("permission", {"buy_fee_reserve": D(-1)}, "INVALID_DECIMAL"),
            ("permission", {"allowed_sides": frozenset({Side.SELL})}, "PERMISSION_DENIED"),
            ("permission", {"allowed_lots": frozenset({Lot.ODD})}, "PERMISSION_DENIED"),
            ("permission", {"allowed_sides": {Side.BUY}}, "INVALID_PERMISSION"),
            ("permission", {"allowed_lots": frozenset({"BOARD"})}, "INVALID_PERMISSION"),
        ):
            with self.subTest(name=name, changes=changes):
                self.rejects(draft, replace(evidence, **{name: replace(getattr(evidence, name), **changes)}), code)
        assess(draft, replace(evidence, account=replace(evidence.account, available_cash=D("25520"))), NOW)
        self.rejects(replace(draft, side=Side.SELL), replace(
            evidence, account=replace(evidence.account, sellable_quantity=999)), "INSUFFICIENT_SELLABLE")

    def test_decimal_context_cannot_round_checks_or_notional(self):
        draft, evidence = fixture()
        with localcontext() as ctx:
            ctx.prec = 2
            result = assess(draft, evidence, NOW)
            self.assertEqual(result.notional, D("25500"))
            self.assertEqual(result.required_cash, D("25520"))
            self.rejects(replace(draft, limit_price=D("25.51")), evidence, "INVALID_PRICE_TICK")

    def test_snapshot_and_preview_are_immutable(self):
        draft, evidence = fixture()
        preview = service().preview(draft, evidence, now=NOW)
        for value, field, replacement in ((draft, "quantity", 2000),
                                           (evidence.account, "active", False),
                                           (preview, "simulated", False)):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, field, replacement)
