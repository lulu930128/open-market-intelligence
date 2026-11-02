"""Point-in-time hypothetical outcomes, never execution fills or realized profit.

``decision_at`` pins the journal version. ``outcome_as_of`` separately bounds
future outcome observations. Input bars must already be resolved by their owner;
this module performs no acquisition, market-data fallback, or database writes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.market.trading_calendar import TAIWAN_TZ
from app.research.trade_journal import proposal_at
from app.research.trade_proposal import PaperBar, ProposalVersion, content_hash, utc_text
from app.watchlists.radar_outcome_v2_service import (
    OutcomePathBar, calculate_outcome_path,
)


HORIZONS = (10, 15)
OUTCOME_VERSION = "research.paper_outcome.v1"


def _path_metrics(version: ProposalVersion, bars: list[PaperBar]) -> dict:
    """Reuse Radar's price path math, discarding its ATR and signal labels.

    Signal-relative MFE/MAE use the frozen proposed entry; Radar's entry-relative
    fields use next-open and must not be presented as this proposal's Trade-R.
    """
    if not bars:
        return {}
    strategy = version.strategy
    result = calculate_outcome_path(
        bars=[OutcomePathBar(
            trade_date=bar.trade_date, open_price=bar.open_price,
            high_price=bar.high_price, low_price=bar.low_price, close_price=bar.close_price,
            source=bar.source_ref,
        ) for bar in bars],
        reference_price=strategy.entry_price, signal_atr=None, direction=strategy.direction,
    )
    favorable = result["signal_mfe_pct"] * strategy.entry_price / 100
    adverse = result["signal_mae_pct"] * strategy.entry_price / 100
    return {
        "basis": "hypothetical_full_window_from_proposed_entry_not_position_excursions",
        "mfe_price": favorable, "mae_price": adverse,
        "mfe_pct": result["signal_mfe_pct"], "mae_pct": result["signal_mae_pct"],
        "mfe_trade_r": favorable / version.initial_stop_distance,
        "mae_trade_r": adverse / version.initial_stop_distance,
        "close_trade_r": strategy.direction * (bars[-1].close_price - strategy.entry_price)
        / version.initial_stop_distance,
        "open_gap_pct": result["signal_open_gap_pct"],
        "observed_sessions": len(bars),
    }


def _paper_assessment(version: ProposalVersion, bars: list[PaperBar], complete: bool) -> dict:
    strategy = version.strategy
    direction = strategy.direction
    result = {
        "fill_assessment": "unfilled" if complete else "unknown",
        "triggered": False if complete else None, "state": "untriggered" if complete else "pending",
        "entry_price": None, "entry_trade_date": None, "exits": [],
        "gross_pnl": None, "net_pnl": None, "trade_r": None, "net_trade_r": None,
        "cost_amount": None, "limitations": [],
    }
    entry = None
    entry_index = 0
    remaining = 1.0
    target_index = 0
    for index, bar in enumerate(bars):
        entered_at_open = False
        if entry is None:
            if strategy.entry_rule == "next_open":
                entry = bar.open_price
                entered_at_open = True
            elif strategy.entry_rule == "at_or_above" and bar.high_price >= strategy.entry_price:
                entry = max(bar.open_price, strategy.entry_price)
                entered_at_open = bar.open_price >= strategy.entry_price
            elif strategy.entry_rule == "at_or_below" and bar.low_price <= strategy.entry_price:
                entry = min(bar.open_price, strategy.entry_price)
                entered_at_open = bar.open_price <= strategy.entry_price
            if entry is None:
                continue
            entry_index = index
            result.update(triggered=True, entry_price=entry, entry_trade_date=bar.trade_date.isoformat())
            if strategy.paper_eligibility != "eligible":
                result.update(fill_assessment=("unfilled" if strategy.paper_eligibility == "ineligible" else "unknown"),
                              state="paper_fill_assessed")
                result["limitations"].append("paper_qualification:" + strategy.paper_eligibility)
                return result
            # A next-open/threshold gap can invalidate the assumed bracket itself.
            if direction * (entry - strategy.stop_price) <= 0 or direction * (strategy.targets[0].price - entry) <= 0:
                result.update(fill_assessment="unknown", state="invalidated")
                result["limitations"].append("entry_gap_outside_strategy_bracket")
                return result
            result.update(fill_assessment="paper", state="open")

        stop_hit = bar.low_price <= strategy.stop_price if direction == 1 else bar.high_price >= strategy.stop_price
        target_hit = direction * ((bar.high_price if direction == 1 else bar.low_price)
                                  - strategy.targets[target_index].price) >= 0
        gap_stop = direction * (bar.open_price - strategy.stop_price) <= 0
        if index == entry_index and not entered_at_open and (stop_hit or target_hit):
            result.update(fill_assessment="ambiguous", state="ambiguous")
            result["limitations"].append("entry_exit_order_unknown_in_daily_bar")
            return result
        if stop_hit and target_hit and not gap_stop:
            result.update(fill_assessment="ambiguous", state="ambiguous")
            result["limitations"].append("stop_target_order_unknown_in_daily_bar")
            return result
        if stop_hit:
            result["exits"].append({"kind": "stop", "price": bar.open_price if gap_stop else strategy.stop_price,
                                    "fraction": remaining, "trade_date": bar.trade_date.isoformat(),
                                    "held_sessions": index - entry_index + 1})
            remaining = 0
            result["state"] = "stop"
        elif target_hit:
            while target_index < len(strategy.targets):
                target = strategy.targets[target_index]
                extreme = bar.high_price if direction == 1 else bar.low_price
                if direction * (extreme - target.price) < 0:
                    break
                result["exits"].append({"kind": "target", "price": target.price,
                                        "fraction": target.fraction, "trade_date": bar.trade_date.isoformat(),
                                        "held_sessions": index - entry_index + 1})
                remaining = max(0.0, remaining - target.fraction)
                target_index += 1
            if remaining < 1e-9:
                remaining = 0
                result["state"] = "target"
        if remaining == 0:
            break

    if entry is None:
        return result
    if remaining and complete:
        result["exits"].append({"kind": "expiry", "price": bars[-1].close_price,
                                "fraction": remaining, "trade_date": bars[-1].trade_date.isoformat(),
                                "held_sessions": len(bars) - entry_index})
        result["state"] = "expired"
        remaining = 0
    if remaining:
        result["limitations"].append("outcome_window_incomplete")
        return result
    gross = sum(direction * (exit["price"] - entry) * strategy.shares * exit["fraction"]
                for exit in result["exits"])
    result.update(gross_pnl=gross, trade_r=gross / version.initial_risk_amount)
    costs = version.costs
    required = (costs.commission_rate, costs.minimum_commission, costs.sell_tax_rate,
                costs.slippage_per_share, costs.other_cost)
    if any(value is None for value in required) or (
        direction == -1 and costs.short_borrow_per_share_session is None
    ):
        result["limitations"].append("cost_unknown")
        return result
    entry_notional = entry * strategy.shares
    cost = max(entry_notional * costs.commission_rate, costs.minimum_commission)
    if direction == -1:
        cost += entry_notional * costs.sell_tax_rate
    for exit in result["exits"]:
        shares = strategy.shares * exit["fraction"]
        notional = exit["price"] * shares
        cost += max(notional * costs.commission_rate, costs.minimum_commission)
        if direction == 1:
            cost += notional * costs.sell_tax_rate
        else:
            cost += shares * costs.short_borrow_per_share_session * exit["held_sessions"]
    cost += 2 * strategy.shares * costs.slippage_per_share + costs.other_cost
    result.update(cost_amount=cost, net_pnl=gross - cost,
                  net_trade_r=(gross - cost) / version.initial_risk_amount)
    result["limitations"].append("cost_model_assumptions_not_broker_verified")
    return result


def calculate_paper_outcomes(
    *, version: ProposalVersion, decision_at: datetime, outcome_as_of: datetime,
    bars: Iterable[PaperBar], horizon_sessions: int | None = None,
) -> dict:
    """Pure replay for a selected T+7..20; legacy default remains T+10/T+15.

    Horizons use the version's frozen calendar after its effective Taiwan date,
    not after the first touched bar. Later revisions are separate prospective
    hypotheses; they are never spliced into an earlier version's paper position.
    A missing session breaks the evaluable prefix; later bars never bridge a gap.
    Multiple providers for a date are rejected, since selection belongs upstream.
    """
    utc_text(decision_at)
    utc_text(outcome_as_of)
    if max(version.recorded_at, version.effective_at, version.evidence.cutoff) > decision_at:
        raise ValueError("Proposal version was unavailable at decision_at.")
    if outcome_as_of < decision_at:
        raise ValueError("Outcome knowledge time precedes decision_at.")
    # Storage capacity/preference never changes the established API default.
    selected_horizon = horizon_sessions
    if selected_horizon is not None and (type(selected_horizon) is not int or not 7 <= selected_horizon <= 20):
        raise ValueError("Outcome horizon must be 7 to 20 trading sessions.")
    anchor = version.effective_at.astimezone(TAIWAN_TZ).date()
    expected = version.planned_trade_dates
    selected: dict = {}
    for bar in bars:
        if bar.symbol != version.symbol:
            raise ValueError("Outcome bar symbol does not match proposal.")
        if bar.trade_date not in expected or max(bar.source_available_at, bar.received_at) > outcome_as_of:
            continue
        if not bar.final:
            continue
        previous = selected.get(bar.trade_date)
        if previous is not None:
            if previous.source_ref != bar.source_ref:
                raise ValueError("Resolve provider selection before evaluating paper outcomes.")
            old_key = (max(previous.source_available_at, previous.received_at), previous.source_available_at, previous.received_at)
            key = (max(bar.source_available_at, bar.received_at), bar.source_available_at, bar.received_at)
            if key == old_key and previous != bar:
                raise ValueError("Conflicting bar revisions have indistinguishable availability.")
            if key <= old_key:
                continue
        selected[bar.trade_date] = bar
    results = []
    for horizon in (selected_horizon,) if selected_horizon is not None else HORIZONS:
        dates = expected[:horizon]
        calendar_complete = len(dates) == horizon
        missing = [day.isoformat() for day in dates if day not in selected]
        visible = [selected[day] for day in dates if day in selected]
        limitations = ["research_only_not_execution", "daily_ohlc_unordered",
                       "path_metrics_are_hypothetical_not_realized_profit"]
        costs = version.costs
        if any(value is None for value in (costs.commission_rate, costs.minimum_commission,
                                           costs.sell_tax_rate, costs.slippage_per_share, costs.other_cost)) or (
            version.strategy.direction == -1 and costs.short_borrow_per_share_session is None
        ):
            limitations.append("cost_unknown")
        if missing:
            limitations.append("missing_daily_bars:" + ",".join(missing))
        if not version.calendar_verified:
            limitations.append("trading_calendar_year_unverified")
        if not calendar_complete:
            limitations.append(f"frozen_calendar_insufficient:{len(dates)}/{horizon}")
        discontinuous = any(bar.price_basis != version.evidence.price_basis
                            or bar.corporate_action == "discontinuous" for bar in visible)
        if any(bar.corporate_action == "unknown" for bar in visible):
            limitations.append("corporate_action_coverage_unknown")
        prefix = []
        for day in dates:
            if day not in selected:
                break
            prefix.append(selected[day])
        if discontinuous:
            limitations.append("corporate_action_or_price_basis_discontinuity")
            metrics = {}
            assessment = {"fill_assessment": "unknown", "triggered": None, "state": "unevaluable",
                          "trade_r": None, "net_trade_r": None, "gross_pnl": None, "net_pnl": None,
                          "exits": [], "limitations": []}
        else:
            metrics = _path_metrics(version, prefix)
            assessment = _paper_assessment(version, prefix, not missing and calendar_complete)
        limitations.extend(assessment.pop("limitations"))
        results.append({
            "horizon_sessions": horizon, "horizon_end_trade_date": dates[-1].isoformat() if calendar_complete else None,
            "expected_trade_dates": [day.isoformat() for day in dates], "missing_trade_dates": missing,
            "coverage": "complete" if not missing and calendar_complete else "partial",
            "path_metrics": metrics, "paper": assessment,
            "limitations": list(dict.fromkeys(limitations)),
            "bar_receipts": [bar.model_dump(mode="json") for bar in visible],
        })
    payload = {
        "contract_version": OUTCOME_VERSION, "creation_id": version.creation_id,
        "revision_id": version.revision_id, "revision": version.revision,
        "evidence_cutoff": utc_text(version.evidence.cutoff), "evidence_hash": version.evidence_hash,
        "strategy_hash": content_hash(version.strategy.model_dump(mode="json")),
        "cost_hash": content_hash(version.costs.model_dump(mode="json")),
        "decision_at": utc_text(decision_at), "outcome_as_of": utc_text(outcome_as_of),
        "window_anchor_trade_date": anchor.isoformat(),
        "one_r_basis": "creation_initial_stop_risk", "initial_stop_distance": version.initial_stop_distance,
        "initial_risk_amount": version.initial_risk_amount,
        "actual_fill": None, "realized_trade_r": None, "outcomes": results,
    }
    payload["replay_hash"] = content_hash(payload)
    return payload


def evaluate_proposal(
    db: Session, *, creation_id: str, decision_at: datetime,
    outcome_as_of: datetime, bars: Iterable[PaperBar], horizon_sessions: int | None = None,
) -> dict:
    """Minimal read-only Backend entry; no HTTP/AI/MCP wiring until G6."""
    return calculate_paper_outcomes(
        version=proposal_at(db, creation_id=creation_id, decision_at=decision_at),
        decision_at=decision_at, outcome_as_of=outcome_as_of, bars=bars, horizon_sessions=horizon_sessions,
    )
