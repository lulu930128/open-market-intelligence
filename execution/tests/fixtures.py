"""Invented rules and balances. Never use these values as exchange/broker rules."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from execution.contracts import (
    AccountFacts, Asset, Confirmation, Currency, Draft, Evidence, EvidenceRef,
    Instrument, Lot, LotRule, Market, MarketFacts, PermissionFacts, PriceUnit,
    Side, TickBand, Venue,
)
from execution.service import OfflineExecution


NOW = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
FIXTURE_KEY = b"synthetic-test-key-not-a-secret!!"


def fixture(*, side=Side.BUY, lot=Lot.BOARD, asset=Asset.CASH_STOCK, venue=Venue.TWSE):
    instrument = Instrument(Market.TW, "TESTETF" if asset is Asset.ETF else "TESTSTOCK", asset, venue)
    draft = Draft(instrument, "synthetic-account", "request-1", side,
                  1000 if lot is Lot.BOARD else 17, lot, D("25.50"))

    def ref(owner):
        return EvidenceRef("fixture-" + owner, owner, NOW - timedelta(seconds=1),
                           NOW - timedelta(seconds=1), NOW + timedelta(seconds=120))

    market = MarketFacts(
        ref("market-rules"), instrument, lot, Currency.TWD, PriceUnit.PER_SHARE,
        "synthetic-session", True, True,
        (TickBand(D("0"), D("50"), D("0.05")), TickBand(D("50"), D("100"), D("0.1"))),
        D("10"), D("90"),
        LotRule(1000, 1000, 100_000, 1000) if lot is Lot.BOARD else LotRule(1000, 1, 999, 1),
    )
    account = AccountFacts(ref("account-facts"), draft.account_id, instrument,
                           Currency.TWD, D("1000000"), 100_000, True)
    permission = PermissionFacts(
        ref("execution-permissions"), "synthetic-human", draft.account_id, instrument,
        frozenset(Side), frozenset(Lot), True, 100_000, D("1000000"), D("20"),
    )
    return draft, Evidence(market, account, permission)


def service():
    return OfflineExecution(fixture_challenge_key=FIXTURE_KEY)


def confirmation(preview):
    c = preview.challenge
    return Confirmation(preview.preview_id, c.token, c.digest, c.principal_id, True)
