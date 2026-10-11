"""SDK 2.1.0 call shape rehearsal. This release accepts ONLY the closed fixture.

The real SDK cannot be substituted here. A reviewed real ingress / observation
normalizer and durable real-simulator ledger remain separate release blockers.
"""

from contextlib import contextmanager
from decimal import Decimal

from execution.contracts import Funding, Lot, OrderKind, PositionAction, Side
from execution.validation import require
from .fake import FakeSDK, FakeOrder, FixtureQuantityUnits


def _fixture_only(sdk):
    require(type(sdk) is FakeSDK and type(sdk.Order) is FakeOrder, 'REAL_SDK_NOT_ADMITTED')


def fixture_quantity(sdk, surface, quantity):
    """Normalize explicit fixture metadata to shares; missing units never default."""
    _fixture_only(sdk)
    units = sdk.quantity_units
    require(type(units) is FixtureQuantityUnits, 'QTY_UNIT_UNPROVEN')
    require(surface in {'order', 'query', 'modified_quantity', 'deal'}, 'QTY_SURFACE_UNPROVEN')
    factor = getattr(units, surface)
    require(type(factor) is int and 0 < factor <= 1_000_000_000, 'QTY_UNIT_UNPROVEN')
    require(type(quantity) is int and 0 <= quantity <= 1_000_000_000, 'INVALID_QUANTITY')
    shares = factor * quantity
    require(shares <= 1_000_000_000, 'INVALID_QUANTITY')
    return shares


@contextmanager
def fixture_session(sdk):
    _fixture_only(sdk)
    # The call shape has no configurable simulation argument or production fallback.
    api = sdk.login('fixture-person', 'fixture-password', simulation=True)
    try:
        yield api
    finally:
        api.logout()


def arguments(draft, sdk, *, fixture_shares_per_unit):
    _fixture_only(sdk)
    require(draft.account_id.startswith('synthetic-'), 'FIXTURE_IDENTITY_ONLY')
    require(draft.funding is Funding.CASH, 'CREDIT_UNSUPPORTED')
    require(draft.lot is Lot.BOARD, 'ODD_LOT_UNSUPPORTED')
    require((draft.side is Side.BUY and draft.position_action in {None, PositionAction.OPEN})
            or (draft.side is Side.SELL and draft.position_action in {None, PositionAction.CLOSE}),
            'POSITION_ACTION_UNSUPPORTED')
    require(type(fixture_shares_per_unit) is int and fixture_shares_per_unit > 0,
            'QTY_UNIT_UNPROVEN')
    require(type(draft.quantity) is int and draft.quantity > 0
            and draft.quantity % fixture_shares_per_unit == 0, 'QTY_UNIT_MISMATCH')
    if draft.order_kind is OrderKind.MARKET:
        require(draft.limit_price is None, 'INVALID_MARKET_PRICE')
        price = sdk.PriceType.MKT
    else:
        require(type(draft.limit_price) is Decimal and draft.limit_price.is_finite()
                and draft.limit_price > 0, 'INVALID_LIMIT_PRICE')
        price = float(draft.limit_price)
        require(Decimal(str(price)) == draft.limit_price, 'PRICE_PRECISION_LOSS')
    return {'action': sdk.Action.Buy if draft.side is Side.BUY else sdk.Action.Sell,
            'symbol': draft.instrument.symbol, 'qty': draft.quantity // fixture_shares_per_unit,
            'price': price, 'time_in_force': sdk.TimeInForce.ROD,
            'order_cond': sdk.OrderCond.CASH, 'odd_lot': sdk.OddLot.Common}


def send_fixture(app, preview, sdk, generation, *, now, crash_at=None):
    args = arguments(preview.draft, sdk, fixture_shares_per_unit=fixture_quantity(sdk, 'order', 1))
    claim = app.rehearsal_claim(preview.preview_id, kind='SEND', generation=generation,
        digest=preview.challenge.digest, request_id='send', now=now).value
    if claim is None:
        return app.status(preview.preview_id)
    app._crash(crash_at, 'after_claim')
    app.rehearsal_check_effect(claim, now=now)
    try:
        sdk.Order.create_order(**args)  # No SQLite transaction exists here.
    except Exception:
        # Do not persist exception text or arbitrary SDK payloads.
        app.rehearsal_result(claim, outcome='UNKNOWN', now=now)
        return app.status(preview.preview_id)
    app._crash(crash_at, 'after_effect')
    app.rehearsal_result(claim, outcome='PENDING', now=now)
    return app.status(preview.preview_id)


def query_fixture(app, preview, sdk, generation, request_id, *, now):
    _fixture_only(sdk)
    claim = app.rehearsal_claim(preview.preview_id, kind='QUERY', generation=generation,
        digest=preview.challenge.digest, request_id=request_id, now=now).value
    if claim is not None:
        app.rehearsal_check_effect(claim, now=now)
        try:
            sdk.Order.get_trades(full=True)
        except Exception:
            app.rehearsal_result(claim, outcome='UNKNOWN', now=now)
        else:
            app.rehearsal_result(claim, outcome='PENDING', now=now)
    return claim


def cancel_fixture(app, preview, sdk, generation, request_id, *, now):
    _fixture_only(sdk)
    claim = app.rehearsal_claim(preview.preview_id, kind='CANCEL', generation=generation,
        digest=preview.challenge.digest, request_id=request_id, now=now).value
    if claim is not None:
        app.rehearsal_check_effect(claim, now=now)
        try:
            sdk.Order.cancel_order('LOCAL-ORDER')
        except Exception:
            app.rehearsal_result(claim, outcome='UNKNOWN', now=now)
        else:
            app.rehearsal_result(claim, outcome='PENDING', now=now)
    return claim
