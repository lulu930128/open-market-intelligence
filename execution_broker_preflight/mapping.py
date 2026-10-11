"""Pure labels, never SDK objects, API arguments, price estimates or permissions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .contracts import (
    Action, ApprovedOrderFixture, Funding, Intent, Lot, PriceKind, Proof,
    RiskFixture, Session, TimeInForce, UnitConversionFixture, aware, nonempty,
    positive_decimal, positive_int, valid_scope,
)


@dataclass(frozen=True)
class OfficialPolicySnapshot:
    version: str
    reviewed_on: str
    sources: tuple[str, ...]
    runtime_sdk: str = "UNVERIFIED"


POLICY_20261010 = OfficialPolicySnapshot(
    "kgi-superpy-docs-20261010.v1", "2026-10-10",
    (
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/orderCreate",
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/eventObject",
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/tradeObject",
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/orderCancel",
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/orderTSECreditInfo",
        "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/accountOrderReport",
        "https://superpy.kgieworld.com.tw/kgipythonapi/faq",
        "https://www.twse.com.tw/zh/products/system/trading.html",
        "https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/continuous.html",
    ),
)


@dataclass(frozen=True)
class CapabilityRow:
    funding: Funding
    action: Action
    intent: Intent
    condition_label: str | None
    evidence: str
    block_reason: str | None


@dataclass(frozen=True)
class BrokerCapabilityMatrix:
    """Closed matrix: missing combinations are denied; no CASH fallback."""

    rows: tuple[CapabilityRow, ...] = (
        CapabilityRow(Funding.CASH, Action.BUY, Intent.OPEN, "CASH", "DOC_ENUM_AND_CASH_SEMANTICS", None),
        CapabilityRow(Funding.CASH, Action.SELL, Intent.CLOSE, "CASH", "DOC_ENUM_AND_CASH_SEMANTICS", None),
        CapabilityRow(Funding.MARGIN, Action.BUY, Intent.OPEN, "MARGIN", "DOC_ENUM_AND_FINANCING_SEMANTICS", None),
        CapabilityRow(Funding.MARGIN, Action.SELL, Intent.CLOSE, "MARGIN", "INFERRED", "MARGIN_REPAYMENT_MAPPING_UNVERIFIED"),
        CapabilityRow(Funding.CREDIT_SHORT, Action.SELL, Intent.OPEN, "SHORT_SELLING", "DOC_ENUM_AND_SHORT_SEMANTICS", None),
        CapabilityRow(Funding.CREDIT_SHORT, Action.BUY, Intent.CLOSE, "SHORT_SELLING", "INFERRED", "CREDIT_COVER_MAPPING_UNVERIFIED"),
        CapabilityRow(Funding.BORROWED_SHORT, Action.SELL, Intent.OPEN, "Lend_SELLING", "DOC_BORROWED_SALE", None),
        CapabilityRow(Funding.BORROWED_SHORT, Action.BUY, Intent.CLOSE, None, "UNVERIFIED", "BORROW_COVER_AND_RETURN_UNVERIFIED"),
        CapabilityRow(Funding.CASH_FIRST_SELL, Action.SELL, Intent.OPEN, "CASH_SELLING", "DOC_CONFLICT", "CASH_SELLING_SEMANTICS_AMBIGUOUS"),
    )


@dataclass(frozen=True)
class MappingLabels:
    action: str
    order_cond: str
    price: Decimal | str
    time_in_force: str
    odd_lot: str
    sdk_qty: int
    unit_evidence_id: str


@dataclass(frozen=True)
class KgiOrderMappingPreview:
    status: str
    reasons: tuple[str, ...]
    labels: MappingLabels | None
    policy_version: str
    semantic_evidence: str | None
    mode: str = "SYNTHETIC / no broker"
    runtime_gate: str = "BLOCKED_UNVERIFIED"


def preview(order: ApprovedOrderFixture, risk: RiskFixture,
            units: UnitConversionFixture | None, policy: OfficialPolicySnapshot,
            now: datetime) -> KgiOrderMappingPreview:
    """Requires fabricated evidence for every gate; never certifies broker mapping."""
    reasons: list[str] = []
    version = policy.version if type(policy) is OfficialPolicySnapshot else "INVALID"

    def blocked(code: str) -> KgiOrderMappingPreview:
        return KgiOrderMappingPreview("BLOCKED", (code,), None, version, None)

    if type(order) is not ApprovedOrderFixture or type(risk) is not RiskFixture:
        return blocked("INVALID_FIXTURE_TYPE")
    if policy != POLICY_20261010 or type(policy) is not OfficialPolicySnapshot:
        return blocked("POLICY_SNAPSHOT_UNSUPPORTED")
    if order.mode != "SYNTHETIC" or risk.mode != "SYNTHETIC":
        return blocked("SYNTHETIC_ONLY")
    if order.schema != "omi.kgi.preflight.order-fixture.v1" or order.approved is not True:
        return blocked("APPROVED_VERSIONED_FIXTURE_REQUIRED")
    if not valid_scope(order.scope) or not valid_scope(risk.scope) or order.scope != risk.scope:
        return blocked("ENTITY_ACCOUNT_SUBACCOUNT_CURRENCY_SCOPE_MISMATCH")
    if order.scope.currency != "TWD":
        return blocked("CURRENCY_POLICY_UNVERIFIED")
    if not nonempty(order.request_id) or not positive_int(order.shares):
        return blocked("INVALID_ID_OR_SHARES")
    for value, expected in ((order.action, Action), (order.intent, Intent),
                            (order.funding, Funding), (order.price_kind, PriceKind),
                            (order.time_in_force, TimeInForce), (order.lot, Lot),
                            (risk.session, Session)):
        if type(value) is not expected:
            return blocked("INVALID_ENUM")
    if not all(aware(t) for t in (now, risk.observed_at, risk.expires_at)):
        return blocked("AWARE_TIMESTAMPS_REQUIRED")
    if not risk.observed_at <= now < risk.expires_at or risk.expires_at - risk.observed_at > timedelta(seconds=300):
        reasons.append("STALE_OR_INVALID_FIXTURE_WINDOW")
    row = next((r for r in BrokerCapabilityMatrix().rows if
                (r.funding, r.action, r.intent) == (order.funding, order.action, order.intent)), None)
    if row is None:
        reasons.append("NO_MAPPING")
    elif row.block_reason:
        reasons.append(row.block_reason)
    for field in ("account_enabled", "api_agreement", "ca_certificate", "entitlement",
                  "sdk_compatibility", "session_coexistence", "instrument_tradable", "risk_limits",
                  "tick_and_price_bounds", "position_or_credit", "collateral_settlement"):
        if getattr(risk, field) is not Proof.SYNTHETIC_VERIFIED:
            reasons.append(field.upper() + "_UNVERIFIED_OR_DENIED")
    if order.funding is not Funding.CASH and risk.credit_terms is not Proof.SYNTHETIC_VERIFIED:
        reasons.append("CREDIT_TERMS_UNVERIFIED_OR_DENIED")
    short_open = order.action is Action.SELL and order.intent is Intent.OPEN and order.funding in (
        Funding.CREDIT_SHORT, Funding.BORROWED_SHORT,
    )
    if short_open:
        if risk.short_eligibility is not Proof.SYNTHETIC_VERIFIED:
            reasons.append("SHORT_ELIGIBILITY_UNVERIFIED_OR_DENIED")
        if risk.short_below_reference_allowed is not True:
            if risk.short_below_reference_allowed is not False:
                reasons.append("SHORT_BELOW_REFERENCE_FLAG_UNKNOWN")
            elif order.price_kind is PriceKind.MARKET:
                reasons.append("SHORT_MARKET_PROHIBITED")
            elif not positive_decimal(risk.short_reference) or not positive_decimal(order.price) or order.price < risk.short_reference:
                reasons.append("SHORT_REFERENCE_PRICE_VIOLATION_OR_UNKNOWN")
        if order.funding is Funding.BORROWED_SHORT and risk.borrow_allocation is not Proof.SYNTHETIC_VERIFIED:
            reasons.append("BORROW_ALLOCATION_UNVERIFIED_OR_DENIED")
    if order.price_kind is PriceKind.MARKET:
        if type(order.price) is not str or order.price != "kgi.PriceType.MKT":
            reasons.append("MARKET_REQUIRES_MKT_SENTINEL_LABEL")
        if risk.has_price_limit is not True or risk.extended_matching is not False:
            reasons.append("MARKET_SECURITY_RESTRICTIONS_OR_UNKNOWN")
    elif not positive_decimal(order.price):
        reasons.append("POSITIVE_FINITE_DECIMAL_LIMIT_REQUIRED")
    if order.time_in_force is not TimeInForce.ROD and risk.extended_matching is not False:
        reasons.append("IOC_FOK_MATCHING_RESTRICTIONS_OR_UNKNOWN")
    # Session is supplied by a future canonical owner, never derived from quote data.
    # Wall-clock bound is an additional documentation check, not a trading calendar.
    local = now.astimezone(timezone(timedelta(hours=8)))
    minute = local.hour * 60 + local.minute
    if order.lot is Lot.BOARD:
        if risk.session is Session.CONTINUOUS:
            if not 540 <= minute < 805:
                reasons.append("CONTINUOUS_CLOCK_MISMATCH")
        elif risk.session in (Session.OPEN_AUCTION, Session.CLOSE_AUCTION):
            if order.price_kind is not PriceKind.LIMIT or order.time_in_force is not TimeInForce.ROD:
                reasons.append("AUCTION_LIMIT_ROD_ONLY")
            bounds = (510, 540) if risk.session is Session.OPEN_AUCTION else (805, 810)
            if not bounds[0] <= minute < bounds[1]:
                reasons.append("AUCTION_CLOCK_MISMATCH")
        else:
            reasons.append("BOARD_SESSION_UNSUPPORTED")
    elif order.lot is Lot.ODD:
        if order.scope.venue != "TWSE":
            reasons.append("TPEX_ODD_POLICY_UNVERIFIED")
        if risk.session is not Session.ODD or not 540 <= minute < 810:
            reasons.append("ODD_SESSION_REQUIRED")
        if order.price_kind is not PriceKind.LIMIT or order.time_in_force is not TimeInForce.ROD or order.funding is not Funding.CASH:
            reasons.append("ODD_CASH_LIMIT_ROD_ONLY")
    else:
        reasons.append("AFTER_HOURS_LOT_POLICY_UNVERIFIED")
    sdk_qty = None
    if type(units) is not UnitConversionFixture:
        reasons.append("BROKER_QUANTITY_UNIT_UNVERIFIED")
    elif (units.mode != "SYNTHETIC" or units.verification is not Proof.SYNTHETIC_VERIFIED
          or units.scope != order.scope or units.lot is not order.lot
          or not nonempty(units.evidence_id) or not nonempty(units.sdk_version)
          or not positive_int(units.shares_per_sdk_qty) or not positive_int(units.board_shares)):
        reasons.append("BROKER_QUANTITY_UNIT_UNVERIFIED")
    else:
        if order.shares % units.shares_per_sdk_qty:
            reasons.append("NONINTEGRAL_BROKER_QUANTITY")
        else:
            sdk_qty = order.shares // units.shares_per_sdk_qty
        if order.lot is Lot.BOARD and order.shares % units.board_shares:
            reasons.append("BOARD_SIZE_MISMATCH")
        if order.lot is Lot.ODD and order.shares >= units.board_shares:
            reasons.append("ODD_SIZE_MISMATCH")
    labels = None
    if not reasons and row is not None and row.condition_label is not None and sdk_qty is not None:
        labels = MappingLabels("Buy" if order.action is Action.BUY else "Sell",
                               row.condition_label, order.price, order.time_in_force.value,
                               order.lot.value, sdk_qty, units.evidence_id)
    return KgiOrderMappingPreview(
        "BLOCKED" if reasons else "SYNTHETIC_PREVIEW_ONLY", tuple(reasons), labels,
        version, row.evidence if row else None,
    )
