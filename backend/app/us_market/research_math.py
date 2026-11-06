"""USD research arithmetic; no Taiwan ticks, taxes, lots or borrow assumptions."""
from decimal import Decimal

from app.research.trade_proposal import PaperCosts, PaperStrategy


def evaluate_us_strategy(strategy: PaperStrategy, costs: PaperCosts, horizon: int) -> dict:
    strategy = PaperStrategy.model_validate(strategy.model_dump())
    number = lambda value: Decimal(str(value))
    entry, stop = number(strategy.entry_price), number(strategy.stop_price)
    quantity, sign = strategy.shares, strategy.direction
    risk = abs(entry - stop) * quantity
    required = ["commission_rate", "minimum_commission", "sell_tax_rate", "slippage_per_share", "other_cost"]
    if sign == -1:
        required.append("short_borrow_per_share_session")
    missing = [name for name in required if getattr(costs, name) is None]

    def scenario(price):
        price = number(price)
        gross = sign * (price - entry) * quantity
        total = None
        if not missing:
            commission = sum(max(number(costs.minimum_commission), p * quantity * number(costs.commission_rate))
                             for p in (entry, price))
            total = (commission + (price if sign == 1 else entry) * quantity * number(costs.sell_tax_rate)
                     + 2 * number(costs.slippage_per_share) * quantity + number(costs.other_cost))
            if sign == -1:
                total += number(costs.short_borrow_per_share_session) * quantity * horizon
        net = gross - total if total is not None else None
        return {"price": str(price), "gross_pnl": str(gross), "gross_rr": str(gross / risk),
                "net_pnl": str(net) if net is not None else None, "net_rr": None,
                "costs": {"total": str(total) if total is not None else None}}

    stop_case = scenario(stop)
    net_loss = -number(stop_case["net_pnl"]) if stop_case["net_pnl"] is not None else None
    targets = [scenario(target.price) for target in strategy.targets]
    if net_loss is not None:
        for item in [stop_case, *targets]:
            item["net_rr"] = str(number(item["net_pnl"]) / net_loss)
    return {"status": "ready", "currency": "USD", "gross_risk": str(risk),
            "net_stop_loss": str(net_loss) if net_loss is not None else None,
            "setup": {"entry": str(entry), "stop": str(stop), "quantity": quantity,
                      "targets": [str(number(t.price)) for t in strategy.targets]},
            "stop_scenario": stop_case, "target_scenarios": targets, "missing_costs": missing,
            "limitations": ["USD research estimates; short borrow availability and execution eligibility remain unknown."]}
