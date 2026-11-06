"""Pure SDK 2.1.0 US mapping. SDK IO stays in KgiSessionOwner.

The public US Deal/ExecReport has no qualified stable fill ID. Such evidence is
quarantined, never converted into a fabricated canonical fill.
"""

from execution.validation import identifier, integer, require
from .contracts import Observation, ReportDiagnostic, decimal, digest
from .us_contracts import UsBrokerKey, UsCommand, UsObservation, us_symbol


def get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def label(value):
    return str(getattr(value, "name", value))


def whole(value):
    number = decimal(value)
    require(number >= 0 and number == number.to_integral_value(), "INVALID_US_QUANTITY")
    result = int(number)
    integer(result)
    return result


def instrument_snapshot(contracts, symbol):
    us_symbol(symbol)
    require(type(contracts) is dict and symbol in contracts, "US_INSTRUMENT_UNRESOLVED")
    contract = contracts[symbol]
    require(get(contract, "symbol") == symbol and label(get(contract, "market")) == "US",
            "US_INSTRUMENT_MISMATCH")
    require(get(contract, "currency") == "USD" and get(contract, "type") == "EQTY",
            "US_INSTRUMENT_UNQUALIFIED")
    lot = whole(get(contract, "board_lot"))
    require(lot > 0, "US_BOARD_LOT_INVALID")
    payload = {"market": "US", "symbol": symbol, "trade_currency": "USD", "board_lot": lot,
               "type": "EQTY", "isin": str(get(contract, "isin", ""))}
    return {**payload, "revision": digest(payload)}


def order_arguments(command, context, instrument, sdk, *, native_session):
    require(type(command) is UsCommand, "INVALID_US_COMMAND")
    command.validate()
    require(context.environment == command.environment == ("PRODUCTION" if native_session else "OFFLINE"),
            "US_ENVIRONMENT_MISMATCH")
    require((command.account_id, command.trade_date) == (context.account_id, context.trade_date)
            and context.date_matches(), "COMMAND_SESSION_MISMATCH")
    require(instrument["symbol"] == command.symbol and instrument["revision"] == command.instrument_revision,
            "US_INSTRUMENT_REVISION_CHANGED")
    require(command.quantity % instrument["board_lot"] == 0, "QUANTITY_UNIT_MISMATCH")
    # Buying power and available quantity are adjudicated by the broker. This
    # adapter does not turn missing local account evidence into an approval.
    price = decimal(command.price)
    native_price = int(price) if price == price.to_integral_value() else float(price)
    require(decimal(native_price) == price, "PRICE_PRECISION_LOSS")
    return dict(action=getattr(sdk.Action, command.action), symbol=command.symbol,
                qty=command.quantity, price=native_price,
                currency=getattr(sdk.Currency, command.settlement_mode), name="omi_execution_us")


def submission_identity(trade):
    order, status = get(trade, "order"), get(trade, "order_status")
    require(order is not None and status is not None, "INVALID_TRADE_RESPONSE")
    require(label(get(order, "market")) == "US", "US_TRADE_MARKET_MISMATCH")
    order_id, original = str(get(order, "order_id") or ""), str(get(order, "org_seqnum") or "")
    for value in (order_id, original):
        if value:
            identifier(value)
    rejected = any(label(get(op, "task")) == "NewOrder" and label(get(op, "status")) == "Failed"
                   for op in get(trade, "operations", []))
    return order_id, original, rejected


def callback_observation(raw, context):
    require(context.date_matches(), "US_REPORT_DATE_UNQUALIFIED")
    require(label(get(raw, "market")) == "US", "US_EVENT_MARKET_MISMATCH")
    task, status = label(get(raw, "task")), label(get(raw, "status"))
    require(task != "Deal", "US_FILL_ID_UNQUALIFIED")
    require(task in {"NewOrder", "CancelOrder"}, "US_EVENT_TASK_UNSUPPORTED")
    kind = {"處理中": "PENDING", "已下單至交易室": "PENDING", "委託上手中": "PENDING",
            "委託成功": "ACCEPTED", "Pending": "PENDING", "Failed": "REJECTED"}.get(status)
    require(kind is not None, "US_EVENT_STATUS_UNQUALIFIED")
    if task == "CancelOrder":
        kind = "UNCERTAIN" if kind == "REJECTED" else "CANCEL_ACK"
    oid = get(raw, "order_id")
    require(type(oid) is str and bool(oid), "US_ORDER_ID_UNAVAILABLE")
    # seqno is NOT a documented substitute for order_id.
    key = UsBrokerKey(context.account_id, context.trade_date, oid, context.environment)
    key.validate()
    original = get(raw, "org_seqnum")
    identifier(original, "US_ORIGIN_ID_UNAVAILABLE")
    symbol = get(raw, "symbol")
    us_symbol(symbol)
    action = {"B": "Buy", "S": "Sell"}.get(label(get(raw, "action")), label(get(raw, "action")))
    require(action in {"Buy", "Sell"}, "UNSUPPORTED_ACTION")
    return UsObservation(key, kind, "SubOrder.set_event", context.timestamp(get(raw, "ts")),
                       symbol, action, "CASH", "Shares", quantity=whole(get(raw, "quantity")),
                       price=str(decimal(get(raw, "price"))), original_id=original)


def report_observation(row, context):
    require(row.get("market") == "US", "US_REPORT_MARKET_MISMATCH")
    # Do not accept a missing account merely because the query was scoped.
    require(row.get("customer_id") == context.account_id, "BROKER_ACCOUNT_MISMATCH")
    stamp = context.timestamp(row.get("trade_date"))
    # Binding date semantics are not certified in production. Offline fixtures
    # explicitly qualify the date; reject other-day rows instead of relabeling.
    require(stamp[:10] == context.trade_date, "US_REPORT_DATE_UNQUALIFIED")
    oid, original = row.get("orderno"), row.get("orig_seqnum")
    identifier(oid, "US_ORDER_ID_UNAVAILABLE")
    identifier(original, "US_ORIGIN_ID_UNAVAILABLE")
    key = UsBrokerKey(context.account_id, context.trade_date, oid, context.environment)
    key.validate()
    symbol = row.get("symbol")
    us_symbol(symbol)
    action = {"B": "Buy", "S": "Sell"}.get(row.get("BuySell"))
    require(action is not None, "UNSUPPORTED_ACTION")
    require(row.get("trade_currency") == "USD" and row.get("settle_currency") in {"TWD", "MUT"},
            "US_REPORT_CURRENCY_INVALID")
    require(str(row.get("action")) == "0", "US_OPERATION_RESULT_UNQUALIFIED")
    require(str(row.get("order_err_code")) == "0", "BROKER_REPORT_ERROR")
    require(str(row.get("sales_status_code")) == "2", "US_ORDER_NOT_CONFIRMED")
    # Filled quantity remains a reported aggregate until stable fill evidence is
    # available. Never insert an artificial delta into the canonical fill table.
    require(whole(row.get("exe_qty")) == 0, "US_FILL_ID_UNQUALIFIED")
    return UsObservation(key, "ACCEPTED", "SubAccount.OrderReport", stamp, symbol, action,
                       "CASH", "Shares", quantity=whole(row.get("qty")),
                       price=str(decimal(row.get("price"))), original_id=original,
                       settlement_mode=row["settle_currency"])


def diagnostic(row, context, source, index, reason):
    fields = {key: str(row[key]) if row[key] is not None else None for key in
              ("orderno", "orig_seqnum", "symbol", "market", "action", "sales_status_code",
               "order_err_code", "exe_status_code", "exe_qty", "trade_currency", "settle_currency") if key in row}
    # Existing diagnostic correlation uses OrderNo. This is a projection alias,
    # never an assertion that the US payload used the TW schema.
    fields["OrderNo"] = fields.get("orderno")
    supplied = row.get("customer_id")
    matches = supplied == context.account_id if type(supplied) is str and supplied else None
    return ReportDiagnostic(source, index, reason, fields, matches, None)


def order_total(row, context):
    """Broker cumulative evidence. Raw broker time is not assigned a timezone.

    The runtime joins this to its persisted original ID and broker order ID;
    it is never treated as a uniquely identified execution or invented fill.
    """
    require(row.get("customer_id") == context.account_id and row.get("market") == "US", "BROKER_ACCOUNT_MISMATCH")
    original, oid = row.get("orig_seqnum"), row.get("orderno")
    identifier(original, "US_ORIGIN_ID_UNAVAILABLE")
    identifier(oid, "US_ORDER_ID_UNAVAILABLE")
    require(str(row.get("order_err_code")) == "0" and str(row.get("sales_status_code")) == "2", "US_ORDER_NOT_CONFIRMED")
    action = str(row.get("action"))
    require(action in {"0", "1"}, "US_OPERATION_RESULT_UNQUALIFIED")
    side = {"B": "Buy", "S": "Sell"}.get(row.get("BuySell"))
    require(side is not None, "UNSUPPORTED_ACTION")
    require(row.get("trade_currency") == "USD" and row.get("settle_currency") in {"TWD", "MUT"}, "US_REPORT_CURRENCY_INVALID")
    quantity, filled = whole(row.get("qty")), whole(row.get("exe_qty"))
    require(0 <= filled <= quantity, "OVERFILL")
    return {"account_id": context.account_id, "broker_order_id": oid, "original_order_id": original,
        "symbol": row.get("symbol"), "action": side, "quantity": quantity, "price": str(decimal(row.get("price"))),
        "settlement_mode": row["settle_currency"], "cumulative_filled": filled, "cancelled": action == "1",
        "source": "SubAccount.OrderReport", "source_time_raw": str(row.get("trade_date") or ""),
        "time_basis": "LOCAL_QUERY_RECEIPT", "fill_history_complete": False}


def validate_cancel(trades, original, key, command, context):
    require(type(trades) is dict and original in trades, "US_ORIGIN_NOT_IN_SDK_SESSION")
    require(key == UsBrokerKey(command.account_id, command.trade_date, key.order_id, command.environment)
            and context.account_id == command.account_id, "CANCEL_SESSION_MISMATCH")
    trade = trades[original]
    oid, origin, _ = submission_identity(trade)
    order = get(trade, "order")
    require((oid, origin) == (key.order_id, original), "US_CANCEL_IDENTITY_MISMATCH")
    require((get(order, "symbol"), label(get(order, "action")), whole(get(order, "quantity")),
             decimal(get(order, "price")), label(get(order, "currency"))) ==
            (command.symbol, command.action, command.quantity, decimal(command.price), command.settlement_mode),
            "CANCEL_TARGET_MISMATCH")
    return original


def trade_snapshot(trade, command, *, original_id=None, order_id=None):
    """Exact SDK order readback, separate from reconciled fill accounting."""
    oid, origin, rejected = submission_identity(trade)
    order = get(trade, "order")
    require((not original_id or origin == original_id) and (not order_id or oid == order_id),
            "US_TRADE_IDENTITY_MISMATCH")
    require((get(order, "symbol"), label(get(order, "action")), whole(get(order, "quantity")),
             decimal(get(order, "price")), label(get(order, "currency"))) ==
            (command.symbol, command.action, command.quantity, decimal(command.price), command.settlement_mode),
            "US_TRADE_COMMAND_MISMATCH")
    return {"available": True, "source": "SubOrder.get_trades", "broker_order_id": oid or None,
            "original_order_id": origin or None, "rejected": rejected,
            "broker_status": label(get(get(trade, "order_status"), "status")),
            "operations": [{"task": label(get(op, "task")), "status": label(get(op, "status")),
                            "status_code": str(get(op, "status_code") or "")[:64]}
                           for op in list(get(trade, "operations", []))[-20:]],
            "fill_history_complete": False}
