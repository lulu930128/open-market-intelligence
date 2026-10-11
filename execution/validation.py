"""Fail-closed validation of supplied synthetic facts; never acquires evidence."""

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
from enum import Enum
import hashlib
import json

from .contracts import (
    AccountFacts, Assessment, Asset, Currency, Draft, Evidence, EvidenceRef,
    ExecutionRejected, Funding, Instrument, Lot, LotRule, Market, MarketFacts,
    OrderKind, Origin, PermissionFacts, PriceUnit, Side, TickBand, TimeInForce, Venue,
    Capability, CreditFacts, EventKind, MarketTradePolicy, PositionAction,
    ResourceRequirements, TradingPhase,
)


def require(condition: bool, code: str, *, outcome: Capability = Capability.DENIED) -> None:
    if not condition:
        raise ExecutionRejected(code, outcome=outcome)


def identifier(value: object, code: str = "INVALID_IDENTIFIER") -> None:
    require(type(value) is str and 0 < len(value) <= 128, code)
    require(all(c.isascii() and (c.isalnum() or c in "-_:.") for c in value), code)


def instant(value: object) -> None:
    require(type(value) is datetime and value.utcoffset() is not None, "INVALID_TIME")


def integer(value: object, *, positive: bool = False) -> None:
    require(type(value) is int, "INVALID_QUANTITY")  # bool and float are not shares.
    require((1 if positive else 0) <= value <= 1_000_000_000, "INVALID_QUANTITY")


def money(value: object, *, positive: bool = False) -> None:
    require(type(value) is Decimal and value.is_finite(), "INVALID_DECIMAL")
    require(len(value.as_tuple().digits) <= 21 and -8 <= value.as_tuple().exponent <= 12,
            "INVALID_DECIMAL")
    require(Decimal(0) <= value <= Decimal("1000000000000"), "INVALID_DECIMAL")
    if positive:
        require(value > 0, "INVALID_DECIMAL")


def instrument(value: object) -> None:
    require(type(value) is Instrument, "INVALID_INSTRUMENT")
    for item, kind in ((value.market, Market), (value.asset, Asset), (value.venue, Venue)):
        require(type(item) is kind, "UNSUPPORTED_INSTRUMENT")
    identifier(value.symbol, "INVALID_SYMBOL")


def validate_draft(draft: Draft) -> None:
    require(type(draft) is Draft, "INVALID_DRAFT")
    instrument(draft.instrument)
    identifier(draft.account_id)
    identifier(draft.client_request_id)
    for value, kind in (
        (draft.side, Side), (draft.lot, Lot), (draft.order_kind, OrderKind),
        (draft.funding, Funding), (draft.time_in_force, TimeInForce),
        (draft.currency, Currency), (draft.price_unit, PriceUnit),
    ):
        require(type(value) is kind, "UNSUPPORTED_ORDER")
    integer(draft.quantity, positive=True)
    require(type(draft.contract_version) is int and draft.contract_version in (1, 2),
            "UNSUPPORTED_CONTRACT_VERSION")
    if draft.contract_version == 1:
        require(draft.funding is Funding.CASH and draft.order_kind is OrderKind.LIMIT
                and draft.position_action is None, "EXPANDED_CONTRACT_REQUIRED")
    else:
        require(type(draft.position_action) is PositionAction, "POSITION_ACTION_REQUIRED")
        expected = Side.SELL if draft.funding in {Funding.SHORT_SELLING, Funding.LEND_SELLING} else Side.BUY
        require(draft.side is (expected if draft.position_action is PositionAction.OPEN else
                              Side.SELL if expected is Side.BUY else Side.BUY), "SIDE_POSITION_MISMATCH")
    if draft.order_kind is OrderKind.MARKET:
        require(draft.limit_price is None, "MARKET_PRICE_MUST_BE_UNSPECIFIED")
    else:
        money(draft.limit_price, positive=True)


def evidence_ref(ref: EvidenceRef, owner: str, now: datetime) -> None:
    require(type(ref) is EvidenceRef, "MISSING_EVIDENCE", outcome=Capability.UNVERIFIED)
    identifier(ref.snapshot_id)
    require(type(ref.origin) is Origin and ref.origin is Origin.SYNTHETIC,
            "SYNTHETIC_ONLY")
    require(ref.owner == owner, "EVIDENCE_OWNER_MISMATCH")
    for value in (ref.observed_at, ref.valid_from, ref.valid_until):
        instant(value)
    require(ref.valid_from <= ref.observed_at <= now < ref.valid_until,
            "EVIDENCE_EXPIRED_OR_NOT_YET_VALID", outcome=Capability.UNVERIFIED)
    require((ref.valid_until - ref.valid_from).total_seconds() <= 300,
            "EVIDENCE_WINDOW_TOO_LONG")
    if ref.received_at is not None:
        instant(ref.received_at)
        require(ref.observed_at <= ref.received_at <= now, "EVIDENCE_RECEIPT_TIME_INVALID")


def assess(draft: Draft, evidence: Evidence, now: datetime) -> Assessment:
    instant(now)
    validate_draft(draft)
    require(type(evidence) is Evidence, "MISSING_EVIDENCE")
    m, a, p = evidence.market, evidence.account, evidence.permission
    require(type(m) is MarketFacts and type(a) is AccountFacts and type(p) is PermissionFacts,
            "MISSING_EVIDENCE")
    for facts, owner in ((m, "market-rules"), (a, "account-facts"), (p, "execution-permissions")):
        evidence_ref(facts.ref, owner, now)
        instrument(facts.instrument)
        require(facts.instrument == draft.instrument, "INSTRUMENT_MISMATCH")
    identifier(a.account_id)
    identifier(p.account_id)
    identifier(p.principal_id)
    identifier(m.session_id)
    require(a.account_id == p.account_id == draft.account_id, "ACCOUNT_MISMATCH")
    require(type(m.currency) is Currency and type(a.currency) is Currency
            and m.currency == a.currency == draft.currency, "CURRENCY_MISMATCH")
    require(type(m.price_unit) is PriceUnit and m.price_unit == draft.price_unit,
            "PRICE_UNIT_MISMATCH")
    require(type(m.lot) is Lot and m.lot == draft.lot, "LOT_MISMATCH")
    require(m.order_entry_open is True, "SESSION_NOT_OPEN")
    require(m.tradable is True, "NOT_TRADABLE")
    require(a.active is True, "ACCOUNT_NOT_ACTIVE")
    require(p.can_trade is True, "PERMISSION_DENIED")
    require(type(p.allowed_sides) is frozenset and p.allowed_sides
            and all(type(s) is Side for s in p.allowed_sides), "INVALID_PERMISSION")
    require(type(p.allowed_lots) is frozenset and p.allowed_lots
            and all(type(lot) is Lot for lot in p.allowed_lots), "INVALID_PERMISSION")
    require(draft.side in p.allowed_sides and draft.lot in p.allowed_lots, "PERMISSION_DENIED")
    integer(p.maximum_quantity, positive=True)
    integer(a.sellable_quantity)
    money(a.available_cash)
    money(p.maximum_notional, positive=True)
    money(p.buy_fee_reserve)
    require(draft.quantity <= p.maximum_quantity, "QUANTITY_LIMIT")

    rule = m.lot_rule
    require(type(rule) is LotRule, "MISSING_LOT_RULE")
    for number in (rule.board_size, rule.minimum, rule.maximum, rule.step):
        integer(number, positive=True)
    require(rule.board_size > 1 and rule.minimum <= rule.maximum, "INVALID_LOT_RULE")
    if draft.lot is Lot.BOARD:
        require(rule.step == rule.board_size and rule.minimum % rule.board_size == 0
                and rule.maximum % rule.board_size == 0, "INVALID_LOT_RULE")
    else:
        require(rule.step == 1 and rule.minimum == 1 and rule.maximum < rule.board_size,
                "INVALID_LOT_RULE")
    require(rule.minimum <= draft.quantity <= rule.maximum
            and draft.quantity % rule.step == 0, "LOT_QUANTITY_MISMATCH")

    money(m.minimum_price, positive=True)
    money(m.maximum_price, positive=True)
    require(m.minimum_price <= m.maximum_price, "PRICE_LIMIT")
    price = draft.limit_price if draft.order_kind is OrderKind.LIMIT else (
        m.maximum_price if draft.side is Side.BUY else m.minimum_price)
    require(m.minimum_price <= price <= m.maximum_price, "PRICE_LIMIT")
    require(type(m.tick_bands) is tuple and 0 < len(m.tick_bands) <= 32, "MISSING_TICK_RULE")
    previous_upper = None
    selected = None
    for band in m.tick_bands:
        require(type(band) is TickBand, "INVALID_TICK_RULE")
        money(band.lower)
        money(band.upper, positive=True)
        money(band.tick, positive=True)
        with localcontext(Context(prec=64)):
            require(band.lower < band.upper and band.tick <= band.upper - band.lower,
                    "INVALID_TICK_RULE")
        require(previous_upper is None or previous_upper == band.lower, "INVALID_TICK_RULE")
        previous_upper = band.upper
        if band.lower <= price < band.upper:
            selected = band
    require(m.tick_bands[0].lower <= m.minimum_price
            and m.tick_bands[-1].upper > m.maximum_price, "INCOMPLETE_TICK_RULE")
    require(selected is not None, "MISSING_TICK_RULE")
    # Do not inherit an embedding caller's Decimal precision/rounding settings.
    with localcontext(Context(prec=64)):
        require(price % selected.tick == 0, "INVALID_PRICE_TICK")
        notional = price * draft.quantity
        required_cash = notional + p.buy_fee_reserve if draft.side is Side.BUY else Decimal(0)
    if draft.contract_version == 2:
        return _expanded_assessment(draft, evidence, now, price)
    require(m.trade_policy is None and a.credit is None and not p.allowed_funding
            and p.authenticated is False and p.maximum_intraday_risk is None
            and p.used_intraday_risk is None, "EXPANDED_CONTRACT_REQUIRED")
    require(notional <= p.maximum_notional, "NOTIONAL_LIMIT")
    if draft.side is Side.BUY:
        require(required_cash <= a.available_cash, "INSUFFICIENT_CASH")
    else:
        require(draft.quantity <= a.sellable_quantity, "INSUFFICIENT_SELLABLE")
    return Assessment(notional, required_cash, min(m.ref.valid_until, a.ref.valid_until, p.ref.valid_until))


def _capability(value: Capability) -> None:
    require(type(value) is Capability, "CAPABILITY_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(value is not Capability.UNVERIFIED, "CAPABILITY_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(value is Capability.ALLOWED, "CAPABILITY_DENIED")


def _expanded_assessment(draft, evidence, now, price):
    m, a, p = evidence.market, evidence.account, evidence.permission
    policy = m.trade_policy
    require(type(policy) is MarketTradePolicy, "POLICY_UNVERIFIED", outcome=Capability.UNVERIFIED)
    evidence_ref(policy.ref, "market-rules", now)
    identifier(policy.version)
    instrument(policy.instrument)
    require(all(type(value) is Capability for value in (
        policy.market_orders, policy.margin, policy.short_selling, policy.lend_selling)),
        'CAPABILITY_UNVERIFIED', outcome=Capability.UNVERIFIED)
    require(policy.instrument == draft.instrument and type(policy.lot) is Lot
            and policy.lot == draft.lot, "POLICY_IDENTITY_MISMATCH")
    require(policy.session_id == m.session_id and policy.market_snapshot_id == m.ref.snapshot_id
            and policy.authoritative_session is True
            and policy.ref.observed_at >= m.ref.observed_at, "SESSION_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(type(policy.phase) is TradingPhase and policy.phase is not TradingPhase.UNKNOWN,
            "SESSION_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(policy.regular_security is True, "SECURITY_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(type(policy.short_below_reference) is bool, "SHORT_POLICY_UNVERIFIED", outcome=Capability.UNVERIFIED)
    money(policy.reference_price, positive=True)
    require(m.minimum_price <= policy.reference_price <= m.maximum_price, "INVALID_REFERENCE_PRICE")
    require(p.authenticated is True, "ACCOUNT_AUTH_UNVERIFIED", outcome=Capability.UNVERIFIED)
    require(draft.account_id.startswith('synthetic-') and p.principal_id.startswith('synthetic-'),
            'FIXTURE_IDENTITY_ONLY')
    require(type(p.allowed_funding) is frozenset
            and all(type(v) is Funding for v in p.allowed_funding)
            and draft.funding in p.allowed_funding, "FUNDING_PERMISSION_DENIED")
    money(p.maximum_intraday_risk, positive=True)
    money(p.used_intraday_risk)
    credit_mode = draft.funding is not Funding.CASH
    if draft.lot is Lot.ODD:
        require(policy.phase is TradingPhase.ODD_LOT_AUCTION, 'LOT_CAPABILITY_UNVERIFIED', outcome=Capability.UNVERIFIED)
    else:
        require(policy.phase is not TradingPhase.ODD_LOT_AUCTION, 'LOT_CAPABILITY_UNVERIFIED', outcome=Capability.UNVERIFIED)
    # Conservative envelope: expanded credit and MARKET only on ordinary board lots.
    if credit_mode or draft.order_kind is OrderKind.MARKET:
        require(draft.lot is Lot.BOARD, "LOT_CAPABILITY_UNVERIFIED", outcome=Capability.UNVERIFIED)
        require(policy.phase is TradingPhase.MARKET_CONTINUOUS, "CONTINUOUS_SESSION_REQUIRED")
    if draft.order_kind is OrderKind.MARKET:
        _capability(policy.market_orders)
    if credit_mode:
        _capability({Funding.MARGIN: policy.margin, Funding.SHORT_SELLING: policy.short_selling,
                     Funding.LEND_SELLING: policy.lend_selling}[draft.funding])
    short_open = draft.funding in {Funding.SHORT_SELLING, Funding.LEND_SELLING} and draft.side is Side.SELL
    if short_open and not policy.short_below_reference:
        require(draft.order_kind is OrderKind.LIMIT, "SHORT_MARKET_RESTRICTED")
        require(price >= policy.reference_price, "SHORT_PRICE_RESTRICTED")
    # Guard both endpoints: MARKET never changes the outward instruction into a limit.
    floor = m.minimum_price if draft.order_kind is OrderKind.MARKET else price
    ceiling = m.maximum_price if draft.order_kind is OrderKind.MARKET or draft.side is Side.SELL else price
    for bound in (floor, ceiling):
        band = next((b for b in m.tick_bands if b.lower <= bound < b.upper), None)
        require(band is not None, "MISSING_TICK_RULE")
        with localcontext(Context(prec=64)):
            require(bound % band.tick == 0, "INVALID_PRICE_TICK")
    expiry = min(m.ref.valid_until, a.ref.valid_until, p.ref.valid_until, policy.ref.valid_until)
    c = a.credit
    if credit_mode or c is not None:
        require(type(c) is CreditFacts, "CREDIT_UNVERIFIED", outcome=Capability.UNVERIFIED)
        evidence_ref(c.ref, "account-facts", now)
        identifier(c.version)
        instrument(c.instrument)
        require(c.account_id == a.account_id and c.account_snapshot_id == a.ref.snapshot_id
                and c.ref.observed_at >= a.ref.observed_at and c.instrument == draft.instrument
                and type(c.currency) is Currency and c.currency == draft.currency,
                "CREDIT_IDENTITY_MISMATCH")
        require(c.authenticated is True, "CREDIT_AUTH_UNVERIFIED", outcome=Capability.UNVERIFIED)
        for value in (c.available_credit, c.available_collateral):
            money(value)
        for value in (c.margin_cash_ratio, c.short_collateral_ratio,
                      c.maintenance_ratio, c.minimum_maintenance_ratio):
            money(value, positive=True)
        require(c.margin_cash_ratio <= 1, "INVALID_MARGIN_RATIO")
        require(c.maintenance_ratio >= c.minimum_maintenance_ratio, "MAINTENANCE_RESTRICTED")
        for value in (c.short_borrow_available, c.lend_borrow_available,
                      c.margin_position, c.short_position, c.lend_position):
            integer(value)
        expiry = min(expiry, c.ref.valid_until)
    with localcontext(Context(prec=64)):
        upper, lower = ceiling * draft.quantity, floor * draft.quantity
        require(upper <= p.maximum_notional, "NOTIONAL_LIMIT")
        require(upper + p.used_intraday_risk <= p.maximum_intraday_risk, "INTRADAY_RISK_LIMIT")
        resources = dict(risk_notional=upper, proceeds_floor=lower if draft.side is Side.SELL else Decimal(0),
                         price_floor=floor, price_ceiling=ceiling)
        cash = upper + p.buy_fee_reserve if draft.side is Side.BUY else Decimal(0)
        if draft.funding is Funding.CASH:
            resources['sellable'] = draft.quantity if draft.side is Side.SELL else 0
            require(resources['sellable'] <= a.sellable_quantity, "INSUFFICIENT_SELLABLE")
        elif draft.funding is Funding.MARGIN:
            if draft.position_action is PositionAction.OPEN:
                cash = upper * c.margin_cash_ratio + p.buy_fee_reserve
                resources['credit'] = upper * (1 - c.margin_cash_ratio)
                require(resources['credit'] <= c.available_credit, "INSUFFICIENT_CREDIT")
            else:
                resources['margin_position'] = draft.quantity
                require(draft.quantity <= c.margin_position, "INSUFFICIENT_MARGIN_POSITION")
        elif short_open:
            # No sale proceeds are spendable. Collateral covers upper-bound exposure,
            # while estimated proceeds use the lower bound; no naked short admission.
            resources['collateral'] = upper * c.short_collateral_ratio
            require(resources['collateral'] <= c.available_collateral, "INSUFFICIENT_COLLATERAL")
            name = 'short_borrow' if draft.funding is Funding.SHORT_SELLING else 'lend_borrow'
            resources[name] = draft.quantity
            require(draft.quantity <= getattr(c, name + '_available'), "INSUFFICIENT_BORROW")
            cash = p.buy_fee_reserve  # Conservative supplied fee reserve for short opening too.
        else:
            name = 'short_position' if draft.funding is Funding.SHORT_SELLING else 'lend_position'
            resources[name] = draft.quantity
            require(draft.quantity <= getattr(c, name), "INSUFFICIENT_SHORT_POSITION")
        require(cash <= a.available_cash, "INSUFFICIENT_CASH")
        return Assessment(upper, cash, expiry, ResourceRequirements(**resources))


def validate_fill(draft, evidence, event):
    """Price evidence for v2 fills, independent of report ordering and settlement."""
    if event.kind not in {EventKind.PARTIAL_FILL, EventKind.FILLED}:
        require(event.fill_price is None, "UNEXPECTED_FILL_PRICE")
        return
    if draft.contract_version == 1 and event.fill_price is None:
        return
    money(event.fill_price, positive=True)
    m = evidence.market
    require(m.minimum_price <= event.fill_price <= m.maximum_price, "FILL_PRICE_GUARD")
    if draft.order_kind is OrderKind.LIMIT:
        require(event.fill_price <= draft.limit_price if draft.side is Side.BUY else
                event.fill_price >= draft.limit_price, "FILL_PRICE_GUARD")
    band = next((b for b in m.tick_bands if b.lower <= event.fill_price < b.upper), None)
    require(band is not None, "FILL_PRICE_GUARD")
    with localcontext(Context(prec=64)):
        require(event.fill_price % band.tick == 0, "INVALID_PRICE_TICK")


def _canonical(value: object) -> object:
    if is_dataclass(value):
        return {f.name: _canonical(getattr(value, f.name)) for f in fields(value)
                if not (f.metadata.get("additive") and type(getattr(value, f.name)) is type(f.default)
                        and getattr(value, f.name) == f.default)}
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if type(value) is datetime:
        return value.astimezone(timezone.utc).isoformat()
    if type(value) is frozenset:
        return sorted(_canonical(v) for v in value)
    if type(value) is tuple:
        return [_canonical(v) for v in value]
    return value


def digest_of(value: object) -> str:
    data = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
