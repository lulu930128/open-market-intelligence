"""F03 internal Taiwan stock research math; public v4 projection belongs to G6.

No quote, broker, account, clock, persistence, trigger or fill is consulted here.
Prices are caller-supplied TWD regular-stock prices, quantities are shares.
Target scenarios each close the *whole* position at one target. An optional
target_quantities allocation additionally evaluates the actual staged exit,
charging one entry commission and a separate commission for each exit leg.

Costs are assumptions, never verified broker terms. None means unknown; use
explicit zero to model an excluded cost. short_borrow_cost is a caller-supplied
total TWD borrow/interest estimate for the whole position and assumed horizon,
charged once in every short scenario (including stop). It is not a borrow quote.
Fee/tax rounding is optional and per charge; otherwise amounts remain exact.
Slippage moves prices adversely, then rounds adversely using the existing TW
tick owner. Those modeled prices are sensitivity assumptions, never fills.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import (
    Context, Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR,
    ROUND_HALF_UP, localcontext,
)
from typing import Literal

from app.market.taiwan_price_rules import normalize_taiwan_stock_price


Number = Decimal | int | float | str
PriceRounding = Literal["reject", "nearest", "up", "down"]
ChargeRounding = Literal["nearest", "up", "down"]
_ROUNDING = {"nearest": ROUND_HALF_UP, "up": ROUND_CEILING, "down": ROUND_FLOOR}
_MATH_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class TradeCosts:
    commission_rate: Number | None = None
    minimum_commission: Number | None = None
    sell_tax_rate: Number | None = None
    entry_slippage_bps: Number | None = None
    exit_slippage_bps: Number | None = None
    short_borrow_cost: Number | None = None
    commission_quantum: Number | None = None
    tax_quantum: Number | None = None
    charge_rounding: ChargeRounding = "nearest"


@dataclass(frozen=True, slots=True)
class TradeSetup:
    direction: Literal["long", "short"]
    entry: Number
    stop: Number
    targets: tuple[Number, ...]
    quantity: int
    target_quantities: tuple[int, ...] | None = None
    price_rounding: PriceRounding = "reject"
    instrument_type: Literal["stock"] = "stock"
    symbol: str | None = None
    as_of_trade_date: date | None = None


@dataclass(frozen=True, slots=True)
class PriceAdjustment:
    field: str
    original: Decimal
    normalized: Decimal


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    entry_commission: Decimal | None
    exit_commission: Decimal | None
    sell_tax: Decimal | None
    slippage: Decimal | None
    short_borrow: Decimal | None
    total: Decimal | None


@dataclass(frozen=True, slots=True)
class ExitScenario:
    exit_prices: tuple[Decimal, ...]
    exit_quantities: tuple[int, ...]
    modeled_entry: Decimal | None
    modeled_exits: tuple[Decimal | None, ...]
    gross_pnl: Decimal
    costs: CostBreakdown
    net_pnl: Decimal | None
    gross_rr: Decimal
    net_rr: Decimal | None


@dataclass(frozen=True, slots=True)
class TradeSetupEvaluation:
    setup: TradeSetup
    cost_assumptions: TradeCosts
    price_adjustments: tuple[PriceAdjustment, ...]
    gross_risk: Decimal
    net_stop_loss: Decimal | None
    stop_scenario: ExitScenario
    target_scenarios: tuple[ExitScenario, ...]
    staged_target_scenario: ExitScenario | None
    missing_costs: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: Literal["tw.trade_setup.math.v1"] = field(
        default="tw.trade_setup.math.v1", init=False,
    )
    status: Literal["proposed"] = field(default="proposed", init=False)
    execution_ready: Literal[False] = field(default=False, init=False)
    execution_eligibility: Literal["unknown"] = field(default="unknown", init=False)


def _number(value: Number, name: str, *, positive: bool = False) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite() or (result <= 0 if positive else result < 0):
            raise ValueError
    except (InvalidOperation, ValueError):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be a finite {qualifier} number") from None
    return result


def _quantity(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer number of shares")
    return value


def _price(value: Number, name: str, rounding: PriceRounding) -> tuple[Decimal, PriceAdjustment | None]:
    original = _number(value, name, positive=True)
    direction = "nearest" if rounding == "reject" else rounding
    normalized = _number(
        normalize_taiwan_stock_price(original, direction=direction), name, positive=True,
    )
    if normalized != original:
        if rounding == "reject":
            raise ValueError(f"{name} is not a legal Taiwan stock tick: {original}")
        return normalized, PriceAdjustment(name, original, normalized)
    return normalized, None


def _costs(value: TradeCosts) -> TradeCosts:
    fields = (
        "commission_rate", "minimum_commission", "sell_tax_rate",
        "entry_slippage_bps", "exit_slippage_bps", "short_borrow_cost",
        "commission_quantum", "tax_quantum",
    )
    parsed = {
        name: None if getattr(value, name) is None else _number(
            getattr(value, name), name, positive=name.endswith("quantum"),
        )
        for name in fields
    }
    for name in ("commission_rate", "sell_tax_rate"):
        if parsed[name] is not None and parsed[name] > 1:
            raise ValueError(f"{name} must be a fraction between 0 and 1")
    for name in ("entry_slippage_bps", "exit_slippage_bps"):
        if parsed[name] is not None and parsed[name] >= 10_000:
            raise ValueError(f"{name} must be less than 10000")
    if value.charge_rounding not in _ROUNDING:
        raise ValueError("unsupported charge_rounding")
    return TradeCosts(**parsed, charge_rounding=value.charge_rounding)


def _round_charge(value: Decimal, quantum: Decimal | None, mode: ChargeRounding) -> Decimal:
    if quantum is None:
        return value
    return (value / quantum).to_integral_value(rounding=_ROUNDING[mode]) * quantum


def _commission(notional: Decimal | None, costs: TradeCosts) -> Decimal | None:
    if notional is None or costs.commission_rate is None or costs.minimum_commission is None:
        return None
    # Minimum is an absolute floor even if the requested charge rounding is down.
    return max(
        costs.minimum_commission,
        _round_charge(notional * costs.commission_rate, costs.commission_quantum, costs.charge_rounding),
    )


def _slipped(price: Decimal, bps: Decimal | None, *, buy: bool) -> Decimal | None:
    if bps is None:
        return None
    multiplier = 1 + bps / 10_000 if buy else 1 - bps / 10_000
    return _number(normalize_taiwan_stock_price(
        price * multiplier, direction="up" if buy else "down",
    ), "modeled_price", positive=True)


def _scenario(
    setup: TradeSetup, costs: TradeCosts, prices: tuple[Decimal, ...],
    quantities: tuple[int, ...], gross_risk: Decimal, net_risk: Decimal | None,
) -> ExitScenario:
    long = setup.direction == "long"
    sign = 1 if long else -1
    entry = setup.entry
    modeled_entry = _slipped(entry, costs.entry_slippage_bps, buy=long)
    modeled_exits = tuple(_slipped(p, costs.exit_slippage_bps, buy=not long) for p in prices)
    gross_pnl = sum((sign * (p - entry) * q for p, q in zip(prices, quantities)), Decimal(0))
    entry_notional = modeled_entry * setup.quantity if modeled_entry is not None else None
    exit_notionals = tuple(p * q if p is not None else None for p, q in zip(modeled_exits, quantities))
    entry_commission = _commission(entry_notional, costs)
    exit_commissions = tuple(_commission(n, costs) for n in exit_notionals)
    exit_commission = (
        sum(exit_commissions, Decimal(0)) if all(c is not None for c in exit_commissions) else None
    )
    sell_notionals = exit_notionals if long else (entry_notional,)
    sell_tax = None
    if costs.sell_tax_rate is not None and all(n is not None for n in sell_notionals):
        sell_tax = sum((
            _round_charge(n * costs.sell_tax_rate, costs.tax_quantum, costs.charge_rounding)
            for n in sell_notionals
        ), Decimal(0))
    slippage = None
    if modeled_entry is not None and all(p is not None for p in modeled_exits):
        slippage = abs(modeled_entry - entry) * setup.quantity + sum((
            abs(modeled - price) * q
            for modeled, price, q in zip(modeled_exits, prices, quantities)
        ), Decimal(0))
    borrow = Decimal(0) if long else costs.short_borrow_cost
    components = (entry_commission, exit_commission, sell_tax, slippage, borrow)
    total = sum(components, Decimal(0)) if all(c is not None for c in components) else None
    net_pnl = gross_pnl - total if total is not None else None
    return ExitScenario(
        exit_prices=prices, exit_quantities=quantities,
        modeled_entry=modeled_entry, modeled_exits=modeled_exits,
        gross_pnl=gross_pnl,
        costs=CostBreakdown(entry_commission, exit_commission, sell_tax, slippage, borrow, total),
        net_pnl=net_pnl, gross_rr=gross_pnl / gross_risk,
        net_rr=net_pnl / net_risk if net_pnl is not None and net_risk is not None else None,
    )


def evaluate_tw_trade_setup(setup: TradeSetup, costs: TradeCosts | None = None) -> TradeSetupEvaluation:
    """Evaluate one long/short proposal without IO or execution qualification.

    Invalid direction/prices/ticks/quantity/config raise ValueError. Unknown
    costs still return gross math, with net values None and named missing costs.
    Strict tick rejection is default. Explicit price rounding is audited and
    direction/order constraints are checked again on the normalized prices.
    Daily price limits, instrument eligibility, cash/margin, borrow availability
    and quote freshness are outside this internal math entry point.
    """
    with localcontext(_MATH_CONTEXT):
        return _evaluate(setup, costs or TradeCosts())


def _evaluate(setup: TradeSetup, costs: TradeCosts) -> TradeSetupEvaluation:
    if setup.direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    if setup.instrument_type != "stock":
        raise ValueError("only regular Taiwan stock tick policy is supported")
    if setup.price_rounding not in ("reject", "nearest", "up", "down"):
        raise ValueError("unsupported price_rounding")
    _quantity(setup.quantity, "quantity")
    if not isinstance(setup.targets, (tuple, list)) or len(setup.targets) not in (1, 2):
        raise ValueError("targets must contain one or two prices")
    allocations = setup.target_quantities
    if allocations is not None:
        if not isinstance(allocations, (tuple, list)) or len(allocations) != len(setup.targets):
            raise ValueError("target_quantities must match targets")
        allocations = tuple(_quantity(q, "target_quantities") for q in allocations)
        if sum(allocations) != setup.quantity:
            raise ValueError("target_quantities must sum to quantity")
    elif len(setup.targets) == 1:
        allocations = (setup.quantity,)

    parsed = tuple(_price(value, name, setup.price_rounding) for name, value in (
        ("entry", setup.entry), ("stop", setup.stop),
        *((f"target_{i + 1}", p) for i, p in enumerate(setup.targets)),
    ))
    entry, stop, *targets = (p for p, _ in parsed)
    sign = 1 if setup.direction == "long" else -1
    if entry == stop:
        raise ValueError("entry and stop must have nonzero risk")
    if sign * (entry - stop) <= 0:
        raise ValueError("stop must be on the loss side of entry")
    if any(sign * (p - entry) <= 0 for p in targets):
        raise ValueError("targets must be on the profit side of entry")
    if len(targets) == 2 and sign * (targets[1] - targets[0]) < 0:
        raise ValueError("target_2 must be at least as far in the profit direction as target_1")
    normalized = replace(setup, entry=entry, stop=stop, targets=tuple(targets), target_quantities=allocations)
    costs = _costs(costs)
    required = ["commission_rate", "minimum_commission", "sell_tax_rate", "entry_slippage_bps", "exit_slippage_bps"]
    if setup.direction == "short":
        required.append("short_borrow_cost")
    missing = tuple(name for name in required if getattr(costs, name) is None)
    gross_risk = abs(entry - stop) * setup.quantity
    stop_scenario = _scenario(normalized, costs, (stop,), (setup.quantity,), gross_risk, None)
    net_risk = -stop_scenario.net_pnl if stop_scenario.net_pnl is not None else None
    stop_scenario = replace(stop_scenario, net_rr=Decimal(-1) if net_risk is not None else None)
    target_scenarios = tuple(
        _scenario(normalized, costs, (p,), (setup.quantity,), gross_risk, net_risk) for p in targets
    )
    staged = (
        _scenario(normalized, costs, tuple(targets), allocations, gross_risk, net_risk)
        if allocations is not None else None
    )
    limitations = (
        "COSTS_ARE_UNVERIFIED_ASSUMPTIONS", "QUOTE_FRESHNESS_NOT_ASSESSED",
        "INSTRUMENT_ELIGIBILITY_NOT_ASSESSED", "DAILY_PRICE_LIMITS_NOT_ASSESSED",
        "FUNDING_SUFFICIENCY_UNKNOWN", "STOP_GAP_LOSS_MAY_EXCEED_SCENARIO",
    )
    if setup.direction == "short":
        limitations += ("BORROW_AVAILABILITY_UNKNOWN", "BORROW_COST_IS_FIXED_HORIZON_ASSUMPTION")
    return TradeSetupEvaluation(
        setup=normalized, cost_assumptions=costs,
        price_adjustments=tuple(adjustment for _, adjustment in parsed if adjustment is not None),
        gross_risk=gross_risk, net_stop_loss=net_risk,
        stop_scenario=stop_scenario, target_scenarios=target_scenarios,
        staged_target_scenario=staged, missing_costs=missing, limitations=limitations,
    )
