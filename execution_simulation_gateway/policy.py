"""Immutable server fixture ingress. No prices, admission rules, or IO here."""

from dataclasses import dataclass
from types import MappingProxyType

from execution.contracts import Currency, Evidence, Funding, OrderKind
from .security import HttpRejected


@dataclass(frozen=True)
class SyntheticFixturePolicy:
    evidence: object
    funding: frozenset = frozenset(Funding)
    order_kinds: frozenset = frozenset(OrderKind)
    currencies: frozenset = frozenset({Currency.TWD})

    def __post_init__(self):
        entries = dict(self.evidence)
        if not entries or len(entries) > 128:
            raise ValueError('BOUNDED_FIXTURES_REQUIRED')
        for (principal, account, symbol, lot), evidence in entries.items():
            if (type(evidence) is not Evidence or not principal.startswith('synthetic-')
                    or not account.startswith('synthetic-')
                    or evidence.permission.principal_id != principal
                    or evidence.permission.account_id != account
                    or evidence.account.account_id != account
                    or evidence.market.instrument.symbol != symbol or evidence.market.lot != lot):
                raise ValueError('FIXTURE_BINDING_MISMATCH')
        object.__setattr__(self, 'evidence', MappingProxyType(entries))
        for name in ('funding', 'order_kinds', 'currencies'):
            object.__setattr__(self, name, frozenset(getattr(self, name)))

    def select(self, session, symbol, lot, funding, kind, currency):
        evidence = self.evidence.get((session.principal, session.account, symbol, lot))
        if evidence is None or funding not in self.funding or kind not in self.order_kinds or currency not in self.currencies:
            raise HttpRejected(403, 'FIXTURE_NOT_ALLOWED')
        return evidence
