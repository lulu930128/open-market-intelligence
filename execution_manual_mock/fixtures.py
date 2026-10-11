"""Explicit invented catalog. Symbols are keys, never a tradability assumption."""

from dataclasses import replace
from datetime import timedelta
import re

from execution.contracts import Lot
from execution.tests.expanded_fixtures import expanded_fixture
from execution_simulation.mock import Fixture
from execution_simulation_gateway.policy import SyntheticFixturePolicy
from execution_simulation_gateway.security import HttpRejected


PRINCIPAL = 'synthetic-manual-human'
ACCOUNT = 'synthetic-manual-account'
ORIGIN = 'https://synthetic.invalid'
DEFAULT_SYMBOLS = ('2330', '2317', '2454', '2303', '2882', '9998', '9997', '9996', '9995')


class ManualCatalog(SyntheticFixturePolicy):
    def select(self, session, symbol, lot, funding, kind, currency):
        if not re.fullmatch(r'[0-9]{4,6}[A-Z]?', symbol, flags=re.ASCII):
            raise HttpRejected(422, 'INVALID_SYMBOL')
        if not any(p == session.principal and a == session.account and s == symbol
                   for p, a, s, _ in self.evidence):
            raise HttpRejected(422, 'INSTRUMENT_UNVERIFIED')
        if (session.principal, session.account, symbol, lot) not in self.evidence:
            raise HttpRejected(422, 'LOT_UNVERIFIED')
        return super().select(session, symbol, lot, funding, kind, currency)


def catalog(symbols, now):
    entries = {}
    if not 1 <= len(symbols) <= 32 or len(set(symbols)) != len(symbols):
        raise ValueError('BOUNDED_UNIQUE_CATALOG_REQUIRED')
    for symbol in symbols:
        if not re.fullmatch(r'[0-9]{4,6}[A-Z]?', symbol, flags=re.ASCII):
            raise ValueError('INVALID_SYMBOL')
        _, e = expanded_fixture()
        instrument = replace(e.market.instrument, symbol=symbol)
        def stamp(ref):
            return replace(ref, observed_at=now, valid_from=now, valid_until=now + timedelta(seconds=240))
        m, a, p = e.market, e.account, e.permission
        market_ref = stamp(m.ref)
        m = replace(m, instrument=instrument, ref=market_ref,
            trade_policy=replace(m.trade_policy, instrument=instrument, ref=market_ref))
        a = replace(a, instrument=instrument, account_id=ACCOUNT, ref=stamp(a.ref), credit=None)
        p = replace(p, instrument=instrument, account_id=ACCOUNT, principal_id=PRINCIPAL, ref=stamp(p.ref))
        # Named negative fixtures, not claims about actual symbols.
        if symbol == '9998':
            m = replace(m, tradable=False)
        if symbol == '9997':
            m = replace(m, ref=replace(m.ref, observed_at=now-timedelta(seconds=2),
                valid_from=now-timedelta(seconds=2), valid_until=now-timedelta(seconds=1)))
        if symbol == '9996':
            p = replace(p, can_trade=False)
        if symbol == '9995':
            m = replace(m, order_entry_open=False)
        entries[(PRINCIPAL, ACCOUNT, symbol, Lot.BOARD)] = replace(e, market=m, account=a, permission=p)
    scenarios = {symbol: {'2317': Fixture.SDK_PENDING, '2454': Fixture.SDK_REJECT,
                         '2303': Fixture.SDK_TIMEOUT, '2882': Fixture.SDK_AMBIGUOUS}.get(symbol, Fixture.SDK_ACCEPT)
                 for symbol in symbols}
    return ManualCatalog(entries), scenarios
