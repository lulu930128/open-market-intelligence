"""All identities, versions, units and approvals here are fabricated."""

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from execution_broker_preflight.contracts import (
    Action, ApprovedOrderFixture, Funding, Intent, Lot, PriceKind, Proof,
    RiskFixture, Scope, Session, TimeInForce, UnitConversionFixture,
)
from execution_broker_preflight.events import EventFixture


NOW = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
SCOPE = Scope("SYNTHETIC_ENTITY", "FAKE_ACCOUNT", "FAKE_SUBACCOUNT", "TWD", "TWSE", "FAKE_SYMBOL")
ORDER = ApprovedOrderFixture(SCOPE, "fake-request", Action.BUY, Intent.OPEN,
                             Funding.CASH, PriceKind.LIMIT, TimeInForce.ROD,
                             Lot.BOARD, 12, Decimal("25"), approved=True)
# Deliberately 3 shares per fictitious board, not Taiwan's assumed real unit.
UNITS = UnitConversionFixture(SCOPE, Lot.BOARD, 3, 3, "fake-unit-proof", "FAKE-SDK",
                              Proof.SYNTHETIC_VERIFIED)
_PROOFS = {f.name: Proof.SYNTHETIC_VERIFIED for f in fields(RiskFixture) if f.default is Proof.UNKNOWN}
RISK = RiskFixture(SCOPE, NOW - timedelta(seconds=1), NOW + timedelta(seconds=30),
                   Session.CONTINUOUS, **_PROOFS, has_price_limit=True,
                   extended_matching=False, short_below_reference_allowed=True)


def event(identifier="fake-event", task="NewOrder", status="Success", **kwargs):
    values = dict(event_id=identifier, request_id=ORDER.request_id, scope=SCOPE,
                  generation=1, task=task, status=status, arrival_at=NOW,
                  source_at=NOW - timedelta(seconds=1), source_ts="095959",
                  order_id="FAKE_ORDER", seqno="fake-seq")
    values.update(kwargs)
    return EventFixture(**values)
