"""Invented 2330-shaped evidence, never actual prices, credit ratios or eligibility."""

from dataclasses import replace
from decimal import Decimal as D

from execution.contracts import (
    Capability, CreditFacts, Funding, Lot, MarketTradePolicy, OrderKind,
    PositionAction, Side, TradingPhase,
)
from execution.tests.fixtures import fixture


def expanded_fixture(*, funding=Funding.CASH, action=PositionAction.OPEN,
                     kind=OrderKind.LIMIT, **kwargs):
    draft, evidence = fixture(**kwargs)
    instrument = replace(draft.instrument, symbol='2330')
    short = funding in {Funding.SHORT_SELLING, Funding.LEND_SELLING}
    side = Side.SELL if short == (action is PositionAction.OPEN) else Side.BUY
    draft = replace(draft, instrument=instrument, funding=funding, position_action=action,
                    contract_version=2, order_kind=kind, side=side,
                    limit_price=None if kind is OrderKind.MARKET else draft.limit_price)
    m, a, p = evidence.market, evidence.account, evidence.permission
    policy = MarketTradePolicy(
        m.ref, 'synthetic-policy-v2', instrument, draft.lot, m.session_id, m.ref.snapshot_id,
        TradingPhase.ODD_LOT_AUCTION if draft.lot is Lot.ODD else TradingPhase.MARKET_CONTINUOUS, True, True,
        Capability.ALLOWED, Capability.ALLOWED, Capability.ALLOWED, Capability.ALLOWED,
        True, D('25'),
    )
    credit = CreditFacts(
        a.ref, 'synthetic-credit-v2', a.account_id, a.ref.snapshot_id, instrument, a.currency, True,
        D('1000000'), D('1000000'), D('0.4'), D('1.2'), D('2'), D('1.5'),
        100_000, 100_000, 100_000, 100_000, 100_000,
    )
    return draft, replace(evidence,
        market=replace(m, instrument=instrument, trade_policy=policy),
        account=replace(a, instrument=instrument, credit=credit),
        permission=replace(p, instrument=instrument, authenticated=True,
                           allowed_funding=frozenset(Funding), maximum_intraday_risk=D('10000000'),
                           used_intraday_risk=D('0')))
