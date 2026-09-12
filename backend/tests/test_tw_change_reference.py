from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from app.market.quote_depth import _apply_change_reference, _apply_headline_compatibility_aliases
from app.market.schemas import TaiwanChangeReferenceRead
from app.market_data.contracts import AuthorityClass, SourceLineage

TZ = ZoneInfo("Asia/Taipei")
DAY = date(2026, 9, 8)
PRIOR = date(2026, 9, 7)


def lineage(day=DAY):
    return SourceLineage(provider="twse_rwd", source="official_test",
                         authority=AuthorityClass.EXCHANGE,
                         event_at=datetime.combine(day, datetime.min.time(), TZ),
                         observation_id=f"test:{day}")


def bar(day, close, change=None):
    return NS(end_at=datetime.combine(day, datetime.min.time(), TZ),
              close_price=Decimal(str(close)),
              price_change=Decimal(str(change)) if change is not None else None,
              lineage=lineage(day))


def result(**fields):
    return NS(resolved=NS(health=NS(facts_usable=True, research_usable=True),
                          quote=None, bars=(), depth=None, auction=None, **fields))


def project(*, bars=(), quote=None, session_quote=None, basis="official_close", depth_day=DAY):
    bundle = NS(requested_at=datetime(2026, 9, 8, 16, tzinfo=TZ),
                official_close=result(), quote=result(), session_close=result(),
                depth=result(), auction=result())
    bundle.official_close.resolved.bars = bars
    bundle.quote.resolved.quote = quote
    bundle.session_close.resolved.quote = session_quote
    bundle.depth.resolved.depth = NS(lineage=lineage(depth_day))
    bundle.auction.resolved.auction = NS(lineage=lineage(DAY))
    response = dict(session_phase="post_close_snapshot", headline_basis=basis,
                    headline_price=618, headline_trade_date=DAY, previous_close=None)
    _apply_change_reference(response, bundle)
    _apply_headline_compatibility_aliases(response)
    return response


def test_official_reference_preserves_raw_identity_and_confirms_prior_date():
    q = project(bars=(bar(PRIOR, 621, 33), bar(DAY, 618, -3)))
    r = TaiwanChangeReferenceRead.model_validate(q["change_reference"])
    assert (q["last_price"], q["change"], q["previous_close"]) == (618, -3, None)
    assert q["change_pct"] == pytest.approx(-3 / 621 * 100)
    assert (r.price, r.trade_date, r.applies_to_trade_date, r.type) == (621, PRIOR, DAY, "prior_regular_close")
    assert r.status == "current" and r.depth_usable and r.auction_usable
    assert r.lineage["observation_id"] == f"test:{DAY}"


def test_missing_prior_evidence_does_not_invent_date_or_prior_close_type():
    r = project(bars=(bar(DAY, 618, -3),))["change_reference"]
    assert r["price"] == 621
    assert r["trade_date"] is None and r["type"] == "official_change_reference"
    assert r["status"] == "partial" and not r["research_usable"]


@pytest.mark.parametrize("basis", ["actual_trade", "session_close"])
def test_same_session_quote_reference_does_not_use_daily_d_minus_two(basis):
    quote = NS(previous_close=Decimal(621), trade_date=DAY, lineage=lineage())
    q = project(bars=(bar(PRIOR, 621, 33),), quote=quote, basis=basis)
    assert q["change_reference"]["price"] == 621
    assert q["headline_change"] == -3


def test_old_quote_reference_and_prior_daily_change_are_not_today_basis():
    quote = NS(previous_close=Decimal(588), trade_date=PRIOR, lineage=lineage(PRIOR))
    q = project(bars=(bar(PRIOR, 621, 33),), quote=quote, basis="session_close")
    assert q["change_reference"]["status"] == "missing"
    assert q["change_reference"]["reason_code"] == "TW_CHANGE_REFERENCE_CORPORATE_ACTION_UNVERIFIED"
    assert q["headline_reference_price"] is None and q["change"] is None


def test_effective_official_exchange_basis_is_not_labelled_prior_close():
    r = project(bars=(bar(PRIOR, 630), bar(DAY, 618, -3)))["change_reference"]
    assert (r["price"], r["type"], r["trade_date"]) == (621, "exchange_reference_price", DAY)


def test_depth_from_another_session_cannot_use_current_basis():
    r = project(bars=(bar(PRIOR, 621), bar(DAY, 618, -3)), depth_day=PRIOR)["change_reference"]
    assert not r["depth_usable"] and r["auction_usable"]


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(-1)])
def test_invalid_reference_fails_closed(value):
    q = project(quote=NS(previous_close=value, trade_date=DAY, lineage=lineage()), basis="actual_trade")
    assert q["change_reference"]["status"] == "missing"
    assert q["change_pct"] is None


def test_reference_schema_rejects_usable_value_without_target_session():
    with pytest.raises(ValueError, match="target session"):
        TaiwanChangeReferenceRead(price=621, status="partial", display_usable=True)


def test_reference_schema_rejects_same_day_as_prior_close():
    with pytest.raises(ValueError, match="precede"):
        TaiwanChangeReferenceRead(price=621, status="current", type="prior_regular_close",
                                 trade_date=DAY, applies_to_trade_date=DAY)
