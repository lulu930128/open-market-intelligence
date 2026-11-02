from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal, ROUND_DOWN, localcontext

import pytest

from app.market.tw_trade_setup import TradeCosts, TradeSetup, evaluate_tw_trade_setup


D = Decimal
# Historical arithmetic assumptions only; excluded borrow/slippage are explicit
# zeros, not broker-confirmed terms or evidence of available short inventory.
EXAMPLE_COSTS = TradeCosts(
    commission_rate="0.001425", minimum_commission=0, sell_tax_rate="0.003",
    entry_slippage_bps=0, exit_slippage_bps=0, short_borrow_cost=0,
)
ZERO_COSTS = replace(EXAMPLE_COSTS, commission_rate=0, sell_tax_rate=0)


def proposal(**changes) -> TradeSetup:
    return replace(TradeSetup("long", "69.2", "65.5", ("75.1", "78.1"), 1000), **changes)


def ratio(numerator: str, denominator: str) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        return D(numerator) / D(denominator)


@pytest.mark.parametrize(
    "symbol,direction,entry,stop,targets,risk,stop_cost,profits,costs,net_profits",
    [
        ("6770", "long", "69.2", "65.5", ("75.1", "78.1"), "3700", "388.4475",
         ("5900", "8900"), ("430.9275", "444.2025"), ("5469.0725", "8455.7975")),
        ("3231", "long", "187", "180.5", ("199.5", "206.5"), "6500", "1065.1875",
         ("12500", "19500"), ("1149.2625", "1180.2375"), ("11350.7375", "18319.7625")),
        ("3481", "short", "48.5", "51.2", ("42.8", "39.15"), "2700", "287.5725",
         ("5700", "9350"), ("275.6025", "270.40125"), ("5424.3975", "9079.59875")),
    ],
)
def test_historical_20261027_exact_arithmetic(
    symbol, direction, entry, stop, targets, risk, stop_cost, profits, costs, net_profits,
):
    setup = TradeSetup(
        direction, entry, stop, targets, 1000,
        symbol=symbol, as_of_trade_date=date(2026, 10, 27),
    )
    result = evaluate_tw_trade_setup(setup, EXAMPLE_COSTS)
    assert result.gross_risk == D(risk)
    assert result.stop_scenario.gross_pnl == -D(risk)
    assert result.stop_scenario.costs.total == D(stop_cost)
    net_risk = D(risk) + D(stop_cost)
    assert result.net_stop_loss == net_risk
    assert result.stop_scenario.net_pnl == -net_risk
    assert result.stop_scenario.gross_rr == result.stop_scenario.net_rr == -1
    for i, outcome in enumerate(result.target_scenarios):
        assert outcome.gross_pnl == D(profits[i])
        assert outcome.costs.total == D(costs[i])
        assert outcome.net_pnl == D(net_profits[i])
        assert outcome.gross_rr == ratio(profits[i], risk)
        assert outcome.net_rr == ratio(net_profits[i], str(net_risk))
    assert result.missing_costs == ()
    assert result.staged_target_scenario is None  # no invented allocation
    assert result.price_adjustments == ()
    assert result.setup.as_of_trade_date == date(2026, 10, 27)
    assert result.status == "proposed"
    assert result.execution_ready is False
    assert result.execution_eligibility == "unknown"


def test_short_tax_is_paid_on_entry_sale_not_buyback_and_borrow_is_once():
    setup = TradeSetup("short", "48.5", "51.2", ("42.8", "39.15"), 1000, (400, 600))
    result = evaluate_tw_trade_setup(setup, replace(EXAMPLE_COSTS, short_borrow_cost="125.5"))
    for outcome in (result.stop_scenario, *result.target_scenarios, result.staged_target_scenario):
        assert outcome.costs.sell_tax == D("145.5")
        assert outcome.costs.entry_commission == D("69.1125")
        assert outcome.costs.short_borrow == D("125.5")
    assert result.target_scenarios[0].net_pnl == D("5298.8975")
    assert result.net_stop_loss == D("3113.0725")
    assert "BORROW_AVAILABILITY_UNKNOWN" in result.limitations


def test_staged_exit_uses_allocated_shares_and_charges_entry_only_once():
    result = evaluate_tw_trade_setup(proposal(target_quantities=(400, 600)), EXAMPLE_COSTS)
    staged = result.staged_target_scenario
    assert staged.exit_quantities == (400, 600)
    assert staged.gross_pnl == D("7700")
    assert staged.costs.entry_commission == D("98.61")
    assert staged.costs.exit_commission == D("109.5825")
    assert staged.costs.sell_tax == D("230.7")
    assert staged.costs.total == D("438.8925")
    assert staged.net_pnl == D("7261.1075")
    assert staged.gross_rr == ratio("7700", "3700")
    assert staged.net_rr == ratio("7261.1075", "4088.4475")


def test_per_exit_minimum_commission_can_make_staging_lose_more_than_gross_risk():
    setup = TradeSetup("long", 10, 9, (11, 12), 2, (1, 1))
    costs = replace(ZERO_COSTS, commission_rate="0.001", minimum_commission=20)
    result = evaluate_tw_trade_setup(setup, costs)
    assert result.net_stop_loss == 42
    assert result.target_scenarios[0].costs.total == 40
    staged = result.staged_target_scenario
    assert staged.costs.entry_commission == 20
    assert staged.costs.exit_commission == 40
    assert staged.gross_pnl == 3
    assert staged.net_pnl == -57
    assert staged.net_rr == ratio("-57", "42")


def test_single_target_and_odd_number_of_shares():
    result = evaluate_tw_trade_setup(proposal(targets=("75.1",), quantity=137), ZERO_COSTS)
    assert result.gross_risk == D("506.9")
    assert result.target_scenarios[0].gross_pnl == D("808.3")
    assert result.staged_target_scenario == result.target_scenarios[0]


def test_default_costs_remain_unknown_without_destroying_gross_math():
    result = evaluate_tw_trade_setup(proposal())
    assert result.gross_risk == 3700
    assert result.target_scenarios[0].gross_pnl == 5900
    assert result.target_scenarios[0].gross_rr == ratio("5900", "3700")
    assert result.net_stop_loss is None
    assert result.target_scenarios[0].net_pnl is None
    assert result.target_scenarios[0].net_rr is None
    assert result.stop_scenario.costs.total is None
    assert result.missing_costs == (
        "commission_rate", "minimum_commission", "sell_tax_rate",
        "entry_slippage_bps", "exit_slippage_bps",
    )


@pytest.mark.parametrize("field", [
    "commission_rate", "minimum_commission", "sell_tax_rate",
    "entry_slippage_bps", "exit_slippage_bps", "short_borrow_cost",
])
def test_each_missing_short_cost_makes_net_unknown(field):
    setup = TradeSetup("short", "48.5", "51.2", ("42.8",), 1000)
    result = evaluate_tw_trade_setup(setup, replace(EXAMPLE_COSTS, **{field: None}))
    assert result.missing_costs == (field,)
    assert result.net_stop_loss is None
    assert result.target_scenarios[0].net_pnl is None
    assert result.target_scenarios[0].net_rr is None
    if field == "short_borrow_cost":
        assert result.stop_scenario.costs.sell_tax == D("145.5")
        assert result.stop_scenario.costs.short_borrow is None


def test_long_borrow_cost_is_not_applicable_and_explicit_zeros_are_known():
    result = evaluate_tw_trade_setup(proposal(), replace(ZERO_COSTS, short_borrow_cost=None))
    assert result.missing_costs == ()
    assert result.target_scenarios[0].costs.short_borrow == 0
    assert result.target_scenarios[0].net_pnl == 5900
    assert result.target_scenarios[0].net_rr == result.target_scenarios[0].gross_rr


@pytest.mark.parametrize(
    "setup,target_entry,target_exit,target_slip,net_profit,net_risk",
    [
        (TradeSetup("long", "49.95", "48", ("51",), 1000), "50", "50.9", "150", "900", "2050"),
        (TradeSetup("short", "50", "51", ("49.5",), 1000), "49.95", "49.55", "100", "400", "1150"),
    ],
)
def test_adverse_slippage_respects_tick_bands_on_both_sides(
    setup, target_entry, target_exit, target_slip, net_profit, net_risk,
):
    result = evaluate_tw_trade_setup(setup, replace(ZERO_COSTS, entry_slippage_bps=10, exit_slippage_bps=10))
    target = result.target_scenarios[0]
    assert target.modeled_entry == D(target_entry)
    assert target.modeled_exits == (D(target_exit),)
    assert target.costs.slippage == D(target_slip)
    assert target.net_pnl == D(net_profit)
    assert result.net_stop_loss == D(net_risk)
    assert target.net_rr == ratio(net_profit, net_risk)
    assert result.status == "proposed"


def test_commissions_and_sell_tax_use_slipped_notional_without_double_counting_slippage():
    setup = TradeSetup("long", "49.95", "48", ("51",), 1000)
    costs = replace(EXAMPLE_COSTS, entry_slippage_bps=10, exit_slippage_bps=10)
    result = evaluate_tw_trade_setup(setup, costs)
    target = result.target_scenarios[0]
    assert target.costs.entry_commission == D("71.25")
    assert target.costs.exit_commission == D("72.5325")
    assert target.costs.sell_tax == D("152.7")
    assert target.net_pnl == D("603.5175")


@pytest.mark.parametrize("rounding,entry_fee,exit_fee,tax", [
    ("down", "10", "11", "33"), ("nearest", "10", "11", "33"), ("up", "11", "12", "34"),
])
def test_optional_per_charge_rounding(rounding, entry_fee, exit_fee, tax):
    setup = TradeSetup("long", "10.05", 10, ("11.05",), 1000)
    costs = replace(EXAMPLE_COSTS, commission_rate="0.001", commission_quantum=1, tax_quantum=1, charge_rounding=rounding)
    target = evaluate_tw_trade_setup(setup, costs).target_scenarios[0]
    assert target.costs.entry_commission == D(entry_fee)
    assert target.costs.exit_commission == D(exit_fee)
    assert target.costs.sell_tax == D(tax)


def test_charge_rounding_never_reduces_the_minimum_commission():
    costs = replace(ZERO_COSTS, minimum_commission="20.5", commission_quantum=1, charge_rounding="down")
    target = evaluate_tw_trade_setup(proposal(), costs).target_scenarios[0]
    assert target.costs.entry_commission == target.costs.exit_commission == D("20.5")


@pytest.mark.parametrize("changes,message", [
    ({"direction": "SHORT"}, "direction"),
    ({"direction": "short"}, "stop must be on the loss side"),
    ({"stop": "69.2"}, "nonzero risk"),
    ({"stop": "70"}, "loss side"),
    ({"targets": ("65",)}, "profit side"),
    ({"targets": ("69.2",)}, "profit side"),
    ({"targets": ("78.1", "75.1")}, "target_2"),
    ({"targets": ()}, "one or two"),
    ({"targets": ("75.1", "78.1", "80")}, "one or two"),
    ({"entry": "69.21"}, "entry is not a legal"),
    ({"stop": "65.51"}, "stop is not a legal"),
    ({"targets": ("75.11",)}, "target_1 is not a legal"),
    ({"targets": ("75.1", "78.11")}, "target_2 is not a legal"),
    ({"instrument_type": "etf"}, "only regular Taiwan stock"),
    ({"price_rounding": "guess"}, "unsupported price_rounding"),
    ({"target_quantities": (500,)}, "must match targets"),
    ({"target_quantities": (500, 499)}, "must sum to quantity"),
    ({"target_quantities": (0, 1000)}, "positive integer"),
    ({"target_quantities": (False, 1000)}, "positive integer"),
    ({"target_quantities": (500.5, 499.5)}, "positive integer"),
])
def test_invalid_setups_fail_explicitly(changes, message):
    with pytest.raises(ValueError, match=message):
        evaluate_tw_trade_setup(proposal(**changes), EXAMPLE_COSTS)


@pytest.mark.parametrize("stop,targets,message", [
    ("47", ("42.8",), "loss side"),
    ("51.2", ("49",), "profit side"),
    ("51.2", ("48.5",), "profit side"),
    ("51.2", ("39.15", "42.8"), "target_2"),
])
def test_short_direction_and_target_order_rejections(stop, targets, message):
    with pytest.raises(ValueError, match=message):
        evaluate_tw_trade_setup(TradeSetup("short", "48.5", stop, targets, 1000), EXAMPLE_COSTS)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, 1000.0, True, "1000", None])
def test_invalid_quantity(quantity):
    with pytest.raises(ValueError, match="quantity must be a positive integer"):
        evaluate_tw_trade_setup(proposal(quantity=quantity))


@pytest.mark.parametrize("price", [0, -1, "NaN", "Infinity", float("nan"), True, None, "broken"])
def test_invalid_prices(price):
    with pytest.raises(ValueError, match="entry must be a finite positive"):
        evaluate_tw_trade_setup(proposal(entry=price))


@pytest.mark.parametrize("changes,message", [
    ({"commission_rate": -1}, "commission_rate"),
    ({"commission_rate": "1.1"}, "commission_rate"),
    ({"minimum_commission": True}, "minimum_commission"),
    ({"sell_tax_rate": "NaN"}, "sell_tax_rate"),
    ({"sell_tax_rate": 2}, "sell_tax_rate"),
    ({"short_borrow_cost": -1}, "short_borrow_cost"),
    ({"entry_slippage_bps": -1}, "entry_slippage_bps"),
    ({"exit_slippage_bps": 10000}, "exit_slippage_bps"),
    ({"commission_quantum": 0}, "commission_quantum"),
    ({"tax_quantum": -1}, "tax_quantum"),
    ({"charge_rounding": "guess"}, "charge_rounding"),
])
def test_invalid_cost_configuration(changes, message):
    with pytest.raises(ValueError, match=message):
        evaluate_tw_trade_setup(proposal(), replace(EXAMPLE_COSTS, **changes))


@pytest.mark.parametrize("rounding,expected", [("down", "49.95"), ("up", "50"), ("nearest", "50")])
def test_explicit_price_rounding_reuses_owner_and_records_adjustments(rounding, expected):
    setup = TradeSetup("long", "49.99", 49, (51,), 1000, price_rounding=rounding)
    result = evaluate_tw_trade_setup(setup, ZERO_COSTS)
    assert result.setup.entry == D(expected)
    assert result.price_adjustments[0].field == "entry"
    assert result.price_adjustments[0].original == D("49.99")
    assert result.price_adjustments[0].normalized == D(expected)
    assert setup.entry == "49.99"  # caller's proposal is not rewritten


def test_rounding_cannot_hide_zero_risk():
    with pytest.raises(ValueError, match="nonzero risk"):
        evaluate_tw_trade_setup(TradeSetup("long", "69.21", "69.22", (75,), 1000, price_rounding="nearest"))


def test_same_two_targets_are_allowed_with_explicit_allocation():
    result = evaluate_tw_trade_setup(proposal(targets=("75.1", "75.1"), target_quantities=(500, 500)), ZERO_COSTS)
    assert result.staged_target_scenario.net_pnl == 5900


def test_math_does_not_depend_on_ambient_decimal_context_or_current_date():
    setup = proposal(as_of_trade_date=date(2026, 10, 27))
    expected = evaluate_tw_trade_setup(setup, EXAMPLE_COSTS)
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.rounding = ROUND_DOWN
        assert evaluate_tw_trade_setup(setup, EXAMPLE_COSTS) == expected
    later = evaluate_tw_trade_setup(replace(setup, as_of_trade_date=date(2026, 10, 30)), EXAMPLE_COSTS)
    assert later.target_scenarios == expected.target_scenarios
    assert later.status == "proposed"
    assert "QUOTE_FRESHNESS_NOT_ASSESSED" in later.limitations
    assert "COSTS_ARE_UNVERIFIED_ASSUMPTIONS" in later.limitations
    with pytest.raises(FrozenInstanceError):
        expected.status = "triggered"
