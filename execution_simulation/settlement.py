"""Pure settlement projection used by the single application owner and replay.

No order reducer or admission calculator lives here. M1 owns both. Decimal
amounts are exact fictional contract amounts (no implicit currency rounding).
"""

from decimal import Context, Decimal, localcontext

from execution.contracts import Capability, Currency, Funding, Origin, PositionAction, Side, State
from execution.validation import digest_of, identifier, instant, integer, money, require
from .settlement_contracts import AccrualTick, FeeSchedule, FillLot, InterestPolicy, SettlementReceipt

ZERO = Decimal(0)
MAX_ORDERS = 60
MAX_AUDIT_ROWS = 2048
MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_LOTS_PER_ORDER = 64


def empty_projection():
    return dict(lots={}, settlements={}, accruals={}, restrictions={}, balances={}, loans={})


def unverified(condition, code):
    require(condition, code, outcome=Capability.UNVERIFIED)


def window(value, now):
    identifier(value.evidence_id if hasattr(value, 'evidence_id') else value.event_id)
    identifier(value.version)
    instant(value.valid_from)
    instant(value.valid_until)
    require(value.origin is Origin.SYNTHETIC and type(value.currency) is Currency, 'SETTLEMENT_IDENTITY')
    require(value.valid_from <= now < value.valid_until, 'SETTLEMENT_EVIDENCE_EXPIRED')
    require((value.valid_until - value.valid_from).total_seconds() <= 86400, 'SETTLEMENT_TTL_BOUND')


def policies(fees, interest, currency, now):
    unverified(type(fees) is FeeSchedule and type(interest) is InterestPolicy, 'COST_POLICY_UNVERIFIED')
    for policy in (fees, interest):
        window(policy, now)
        require(policy.currency is currency, 'SETTLEMENT_IDENTITY')
        money(policy.money_quantum, positive=True)
        require(policy.money_quantum <= 1 and policy.money_quantum.as_tuple().digits == (1,)
                and policy.rounding == 'ROUND_HALF_EVEN', 'ROUNDING_UNVERIFIED')
    require(fees.money_quantum == interest.money_quantum, 'ROUNDING_CONFLICT')
    for rate in (fees.commission_rate, fees.sale_levy_rate, fees.borrow_open_rate,
                 interest.financing_rate_per_second, interest.borrow_rate_per_second):
        money(rate)
        require(rate <= 1, 'RATE_BOUND')
    integer(interest.maximum_period_seconds, positive=True)
    require(interest.maximum_period_seconds <= 86400, 'PERIOD_BOUND')


def order_lots(projection, key):
    # JSON object persistence sorts keys; concurrent insertion order is not evidence.
    # Use the same identity order for snapshots, receipts and full journal replay.
    return tuple(projection['lots'][event_id] for event_id in sorted(projection['lots'])
                 if projection['lots'][event_id].preview_id == key)


def add_lot(projection, lot, preview, before, after, now):
    require(type(lot) is FillLot, 'INVALID_FILL_LOT')
    identifier(lot.event_id)
    integer(lot.shares, positive=True)
    money(lot.executed_price, positive=True)
    instant(lot.occurred_at)
    require(preview.preview_id == lot.preview_id and preview.created_at <= lot.occurred_at <= now,
            'INVALID_FILL_LOT')
    require(lot.event_id not in projection['lots'], 'EVENT_ID_CONFLICT')
    require(lot.preview_id not in projection['settlements'], 'LATE_FILL_AFTER_SETTLEMENT')
    lots = order_lots(projection, lot.preview_id)
    require(len(lots) < MAX_LOTS_PER_ORDER, 'FILL_LOT_QUOTA')
    require(sum(x.shares for x in lots) == before.cumulative_filled, 'FILL_LOT_HISTORY_UNVERIFIED')
    require(after.cumulative_filled - before.cumulative_filled == lot.shares, 'FILL_LOT_DELTA_MISMATCH')
    projection['lots'][lot.event_id] = lot


def balance(projection, preview):
    key = digest_of((preview.draft.account_id, preview.draft.instrument))
    return projection['balances'].setdefault(key, dict(account_id=preview.draft.account_id,
        instrument=preview.draft.instrument, cash=ZERO, credit=ZERO, collateral=ZERO,
        sellable=0, margin_position=0, short_position=0, lend_position=0,
        short_borrow_available=0, lend_borrow_available=0, restricted_proceeds=ZERO,
        financing_principal=ZERO, borrowed_shares=0, fees=ZERO, interest=ZERO))


def deltas(projection, draft):
    result = dict(cash=ZERO, credit=ZERO, collateral=ZERO, sellable=0, margin_position=0,
                  short_position=0, lend_position=0, short_borrow_available=0, lend_borrow_available=0)
    with localcontext(Context(prec=64)):
        for b in projection['balances'].values():
            if b['account_id'] != draft.account_id:
                continue
            for name in result:
                if name in {'cash', 'credit', 'collateral'} or b['instrument'] == draft.instrument:
                    result[name] += b[name]
    return result


def settle_projection(projection, preview, order, receipt, fees, interest, now):
    unverified(type(receipt) is SettlementReceipt, 'FINALITY_UNVERIFIED')
    window(receipt, now)
    require(receipt.version == 'synthetic-finality-v2', 'FINALITY_VERSION')
    instant(receipt.eligible_at)
    require(receipt.eligible_at <= now and receipt.valid_from <= receipt.eligible_at, 'SETTLEMENT_NOT_ELIGIBLE')
    unverified(receipt.no_outstanding_late_fills is True, 'LATE_FILL_RISK_UNVERIFIED')
    require(order.confirmed_at is not None and order.state in {
        State.SIMULATED_FILLED, State.SIMULATED_CANCELLED, State.SIMULATED_REJECTED}, 'SETTLEMENT_STATE_BLOCKED')
    require(receipt.eligible_at >= (order.last_report_at or order.confirmed_at), 'SETTLEMENT_NOT_ELIGIBLE')
    lots = order_lots(projection, preview.preview_id)
    require(sum(x.shares for x in lots) == order.cumulative_filled, 'FILL_LOT_HISTORY_UNVERIFIED')
    require((receipt.preview_id, receipt.account_id, receipt.session_id, receipt.currency,
             receipt.instrument, receipt.preview_digest, receipt.order_digest, receipt.fills_digest) ==
            (preview.preview_id, preview.draft.account_id, preview.evidence.market.session_id,
             preview.draft.currency, preview.draft.instrument, preview.challenge.digest,
             digest_of(order), digest_of(lots)), 'FINALITY_SCOPE_MISMATCH')
    require(preview.preview_id not in projection['settlements'], 'SETTLEMENT_CONFLICT')
    require(not any(x['receipt'].event_id == receipt.event_id for x in projection['settlements'].values()),
            'EVENT_ID_CONFLICT')
    require(preview.draft.account_id not in projection['restrictions'], 'ACCOUNT_RESTRICTED')
    policies(fees, interest, preview.draft.currency, now)
    for old in projection['settlements'].values():
        for name, policy in (('fees', fees), ('interest', interest)):
            if old[name].evidence_id == policy.evidence_id:
                require(old[name] == policy, 'POLICY_EVIDENCE_CONFLICT')
    d, c = preview.draft, preview.evidence.account.credit
    if d.funding is Funding.CASH or d.position_action is PositionAction.OPEN:
        require(receipt.opening_preview_id is None and receipt.lender_ack_id is None, 'UNEXPECTED_LENDER_ACK')
    quantity = sum(x.shares for x in lots)
    with localcontext(Context(prec=64)):
        notional = sum((x.executed_price * x.shares for x in lots), ZERO)
        rounded = lambda value: value.quantize(fees.money_quantum, rounding=fees.rounding)
        commission = rounded(notional * fees.commission_rate)
        levy = rounded(notional * fees.sale_levy_rate) if d.side is Side.SELL else ZERO
        borrow_fee = (rounded(notional * fees.borrow_open_rate) if d.funding in {
            Funding.SHORT_SELLING, Funding.LEND_SELLING} and d.position_action is PositionAction.OPEN else ZERO)
        cost = commission + levy + borrow_fee
        b = balance(projection, preview)
        b['fees'] += cost
        if d.funding is Funding.CASH:
            b['cash'] += -notional - cost if d.side is Side.BUY else notional - cost
            b['sellable'] += quantity if d.side is Side.BUY else -quantity
        elif d.position_action is PositionAction.OPEN:
            unverified(c is not None, 'CREDIT_UNVERIFIED')
            principal = rounded(notional * (1 - c.margin_cash_ratio)) if d.funding is Funding.MARGIN else ZERO
            collateral = ZERO if d.funding is Funding.MARGIN else rounded(notional * c.short_collateral_ratio)
            proceeds = notional if d.funding is not Funding.MARGIN else ZERO
            b['cash'] -= notional - principal + cost if d.funding is Funding.MARGIN else cost
            b['credit'] -= principal
            b['financing_principal'] += principal
            b['collateral'] -= collateral
            b['restricted_proceeds'] += proceeds
            name = {Funding.MARGIN: 'margin', Funding.SHORT_SELLING: 'short', Funding.LEND_SELLING: 'lend'}[d.funding]
            b[name + '_position'] += quantity
            if name != 'margin':
                b[name + '_borrow_available'] -= quantity
                b['borrowed_shares'] += quantity
            projection['loans'][preview.preview_id] = dict(account_id=d.account_id, instrument=d.instrument,
                funding=d.funding, shares=quantity, principal=principal, collateral=collateral,
                proceeds=proceeds, borrow_basis=notional if name != 'margin' else ZERO,
                interest_policy=interest, accrued_through=now)
        elif quantity:
            # Baseline credit positions alone do not prove principal/borrow ownership.
            loan = projection['loans'].get(receipt.opening_preview_id)
            unverified(loan is not None and receipt.lender_ack_id is not None, 'PAYBACK_ACK_UNVERIFIED')
            identifier(receipt.lender_ack_id)
            require(not any(x['receipt'].lender_ack_id == receipt.lender_ack_id
                            for x in projection['settlements'].values()), 'LENDER_ACK_REUSED')
            require((loan['account_id'], loan['instrument'], loan['funding']) ==
                    (d.account_id, d.instrument, d.funding), 'PAYBACK_SCOPE_MISMATCH')
            require(0 < quantity <= loan['shares'], 'PAYBACK_QUANTITY')
            require(loan['accrued_through'] == now, 'ACCRUAL_REQUIRED')
            require(loan['interest_policy'].money_quantum == fees.money_quantum, 'ROUNDING_CONFLICT')
            # Fee rounding never rounds executed proceeds or creates a residual
            # liability. Final return consumes the exact remainder; partial
            # allocations floor to M1's smallest money unit, leaving residue on
            # the opening obligation until its last share is returned.
            ratio = Decimal(quantity) / loan['shares']
            principal, collateral, proceeds, basis = (
                loan[x] if quantity == loan['shares'] else
                (loan[x] * ratio).quantize(Decimal('0.00000001'), rounding='ROUND_DOWN')
                for x in ('principal', 'collateral', 'proceeds', 'borrow_basis'))
            b['cash'] += notional - principal - cost if d.funding is Funding.MARGIN else proceeds - notional - cost
            b['credit'] += principal
            b['financing_principal'] -= principal
            b['collateral'] += collateral
            b['restricted_proceeds'] -= proceeds
            name = {Funding.MARGIN: 'margin', Funding.SHORT_SELLING: 'short', Funding.LEND_SELLING: 'lend'}[d.funding]
            b[name + '_position'] -= quantity
            if name != 'margin':
                b[name + '_borrow_available'] += quantity
                b['borrowed_shares'] -= quantity
            for field, amount in (('principal', principal), ('collateral', collateral),
                                  ('proceeds', proceeds), ('borrow_basis', basis)):
                loan[field] -= amount
            loan['shares'] -= quantity
        projection['settlements'][preview.preview_id] = dict(receipt=receipt, fees=fees, interest=interest,
            quantity=quantity, notional=notional, commission=commission, levy=levy, borrow_fee=borrow_fee)


def accrue_projection(projection, tick, preview, now):
    require(type(tick) is AccrualTick, 'INVALID_ACCRUAL')
    identifier(tick.event_id)
    for stamp in (tick.period_start, tick.period_end):
        instant(stamp)
    loan = projection['loans'].get(tick.opening_preview_id)
    unverified(loan is not None and loan['shares'] > 0, 'LOAN_UNVERIFIED')
    policy = loan['interest_policy']
    window(policy, now)
    require(tick.period_start == loan['accrued_through'] and tick.period_start < tick.period_end <= now,
            'ACCRUAL_PERIOD_CONFLICT')
    seconds = Decimal(str((tick.period_end - tick.period_start).total_seconds()))
    require(seconds <= policy.maximum_period_seconds and policy.valid_from <= tick.period_start
            and tick.period_end < policy.valid_until, 'PERIOD_BOUND')
    require(tick.event_id not in projection['accruals'], 'EVENT_ID_CONFLICT')
    with localcontext(Context(prec=64)):
        cost = (seconds * (loan['principal'] * policy.financing_rate_per_second
                          + loan['borrow_basis'] * policy.borrow_rate_per_second)).quantize(
                              policy.money_quantum, rounding=policy.rounding)
        b = balance(projection, preview)
        b['cash'] -= cost
        b['interest'] += cost
    loan['accrued_through'] = tick.period_end
    projection['accruals'][tick.event_id] = dict(tick=tick, cost=cost)
