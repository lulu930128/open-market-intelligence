"""Injected KGI call shapes; no SDK import, login, credentials or default factory.

Order mapping follows manual v2.7. Callback shape is statically checked against
SDK 2.1.0 Order.py; native behavior is deliberately NOT certified by these tests.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from threading import RLock

from execution.contracts import ExecutionRejected
from execution.validation import identifier, require
from .contracts import BrokerKey, Command, Observation, QueryBatch, ReportDiagnostic, SourceRead, day, decimal, parse_stamp


# v2.7 public_report fields plus fill identity/quantity and source channel.
# Account/person identifiers and free-form ErrMsg are deliberately not copied.
REPORT_FIELDS = (
    "StockID", "Side", "Price", "Qty", "OrdLot", "OrderNo", "OrderFunc",
    "OrdClass", "TimeInForceN", "TradeDate", "BeforeQty", "AfterQty",
    "ErrCode", "ClientOrderTime", "ReportTime", "CNT", "DealQty", "Channel",
)


def get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def label(value):
    return str(getattr(value, "name", value))


def whole(value):
    number = decimal(value)
    require(number >= 0 and number == number.to_integral_value(), "INVALID_BROKER_QUANTITY")
    return int(number)


def price_observation(raw, received_at):
    """Strict execution price evidence from the SDK's real tick schema.

    Unlike a display fallback, missing/invalid event time never becomes receipt
    time. Trial, suspended, delayed and zero-volume ticks cannot trigger exits.
    """
    require(get(raw, "simtrade") in (0, "0", False) and get(raw, "suspend") in (0, "0", False),
            "PRICE_NOT_FORMAL_TRADE")
    require(decimal(get(raw, "delay_time")) == 0 and decimal(get(raw, "volume")) > 0,
            "PRICE_DELAYED_OR_NO_TRADE")
    stamp = get(raw, "datetime")
    if isinstance(stamp, datetime):
        observed = stamp
    else:
        require(stamp is not None, "PRICE_TIME_MISSING")
        stamp = str(stamp)
        observed = (datetime.strptime(stamp, "%Y%m%d%H%M%S") if len(stamp) == 14 and stamp.isdigit()
                    else datetime.fromisoformat(stamp.replace("Z", "+00:00")))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone(timedelta(hours=8)))
    observed = observed.astimezone(timezone.utc)
    require(0 <= (received_at - observed).total_seconds() <= 5, "PRICE_STALE_OR_FUTURE")
    symbol = get(raw, "symbol")
    identifier(symbol)
    price = decimal(get(raw, "close"))
    total = whole(get(raw, "total_volume"))
    require(total > 0, "PRICE_NO_TRADE_PROGRESS")
    require(price > 0 and get(raw, "odd_lot") in (True, False, 0, 1, "0", "1"), "PRICE_MAPPING_UNAVAILABLE")
    return {"symbol": symbol, "price": str(price), "odd_lot": get(raw, "odd_lot") in (True, 1, "1"),
            "observed_at": observed.isoformat(), "received_at": received_at.isoformat(),
            "total_volume": total,
            "source": "KGI.Quote.set_cb_all"}


def labels(action, condition, lot):
    action = {"B": "Buy", "S": "Sell"}.get(label(action), label(action))
    condition = {"0": "CASH", "3": "MARGIN", "4": "SHORT_SELLING", "9": "CASH_SELLING"}.get(
        label(condition), label(condition))
    lot = {"0": "Common", "4": "Odd"}.get(label(lot), label(lot))
    require(action in {"Buy", "Sell"} and condition in {"CASH", "MARGIN", "SHORT_SELLING", "CASH_SELLING"}
            and lot in {"Common", "Odd"}, "UNSUPPORTED_BROKER_MAPPING")
    return action, condition, lot


def callback_observation(raw, account_id: str, trade_date: str) -> Observation:
    task, status = label(get(raw, "task")), label(get(raw, "status"))
    if task == "Deal":
        require(status in {"None", "Success"}, "INVALID_DEAL_STATUS")
        kind = "DEAL"
        require(bool(get(raw, "seqno")), "DEAL_ID_UNAVAILABLE")
    elif task == "NewOrder":
        kind = {"Pending": "PENDING", "Success": "ACCEPTED", "Failed": "REJECTED"}.get(status)
    elif task == "CancelOrder":
        kind = {"Pending": "CANCEL_ACK", "Success": "CANCEL_ACK", "Failed": "UNCERTAIN"}.get(status)
    else:
        kind = None
    require(kind is not None, "UNSUPPORTED_CALLBACK")
    key = BrokerKey(account_id, trade_date, str(get(raw, "order_id") or ""))
    # Pending without an order number is journaled as uncorrelated by the caller.
    action, condition, lot = labels(get(raw, "action"), get(raw, "order_cond"), get(raw, "odd_lot"))
    require(label(get(raw, "time_in_force")) in {"ROD", "0", "R"}, "UNSUPPORTED_TIF")
    return Observation(key, kind, "Order.set_event", parse_stamp(trade_date, get(raw, "ts")),
                       str(get(raw, "symbol")), action, condition, lot, str(get(raw, "seqno") or ""),
                       whole(get(raw, "quantity")), str(decimal(get(raw, "price"))))


def report_day(row: dict) -> str:
    raw_date = str(row.get("TradeDate", "")).replace("-", "")
    require(len(raw_date) == 8 and raw_date.isdigit(), "BROKER_DATE_UNAVAILABLE")
    try:
        return day(raw_date[:4] + "-" + raw_date[4:6] + "-" + raw_date[6:])
    except ValueError:
        raise ValueError("BROKER_DATE_INVALID") from None


def report_account_matches(row: dict, account_id: str) -> bool | None:
    # v2.7 public anonymous reports omit Account; the endpoint is account-scoped.
    # A supplied but unreadable cell is unknown, not a proven foreign account.
    account = row.get("Account", account_id)
    return account == account_id if type(account) is str and account else None


def report_observation(row: dict, account_id: str, *, deal: bool) -> Observation:
    require(report_account_matches(row, account_id) is True, "BROKER_ACCOUNT_MISMATCH")
    trade_date = report_day(row)
    order_id = row.get("OrderNo")
    # 0000 is present in the v2.7 rejected history; it is not an allocated ID.
    require(type(order_id) is str and order_id not in {"", "0000"}, "BROKER_ORDER_ID_UNAVAILABLE")
    key = BrokerKey(account_id, trade_date, order_id)
    key.validate()
    symbol = row.get("StockID")
    identifier(symbol, "BROKER_SYMBOL_UNAVAILABLE")
    action, condition, lot = labels(row.get("Side"), row.get("OrdClass"), row.get("OrdLot"))
    if deal:
        kind = "DEAL"
        seqno = row.get("CNT")
        require(type(seqno) in {str, int} and bool(seqno), "DEAL_ID_UNAVAILABLE")
        identifier(str(seqno), "DEAL_ID_UNAVAILABLE")
    else:
        require(str(row.get("TimeInForceN")) in {"R", "ROD", "0"}, "UNSUPPORTED_TIF")
        error = row.get("ErrCode")
        require(error is not None and str(error) != "", "BROKER_REPORT_ERROR_UNAVAILABLE")
        # Failed operations describe an attempted action, not current order
        # truth. Preserve them as diagnostics, including codes other than MAT0095.
        require(str(error) == "0", "BROKER_REPORT_ERROR")
        function = str(row.get("OrderFunc"))
        kind = {"I": "ACCEPTED", "D": "CANCELLED"}.get(function)
        require(kind is not None, "UNSUPPORTED_ORDER_AMENDMENT")
        if kind == "CANCELLED":
            require(whole(row.get("AfterQty")) == 0, "CANCEL_REMAINDER_NOT_ZERO")
    return Observation(key, kind, "Order.ExecReport" if deal else "Account.OrderReport",
                       parse_stamp(trade_date, row.get("ReportTime")), symbol,
                       action, condition, lot, str(row.get("CNT") or ""),
                       whole(row.get("DealQty" if deal else "Qty")), str(decimal(row.get("Price"))),
                       None if deal else whole(row.get("AfterQty")),
                       str(row["Channel"]) if row.get("Channel") is not None else None)


def report_diagnostic(row: dict, account_id: str, *, deal: bool, row_index: int,
                      reason: str) -> ReportDiagnostic:
    try:
        trade_date = report_day(row)
    except ValueError:
        trade_date = None
    return ReportDiagnostic(
        "Order.ExecReport" if deal else "Account.OrderReport", row_index, reason,
        {key: None if row[key] is None else str(row[key]) for key in REPORT_FIELDS if key in row},
        report_account_matches(row, account_id), trade_date)


def records(frame, required):
    require(frame is not None and callable(getattr(frame, "to_dict", None)), "REPORT_UNAVAILABLE")
    require(set(required) <= set(frame.columns), "REPORT_SCHEMA_MISMATCH")
    result = frame.to_dict(orient="records")
    require(type(result) is list and all(type(row) is dict for row in result), "REPORT_SCHEMA_MISMATCH")
    return result


@dataclass(frozen=True)
class SessionBinding:
    api: object
    sdk: object  # constants only; supplied by the operator, never imported here
    account_id: str
    trade_date: str
    current_day: object = None  # native clock guard; fixtures may use historical dates
    cash_inventory_required: bool = False  # native factory always enables; historical engine fixtures do not


@dataclass(frozen=True)
class Submission:
    order_id: str
    rejected: bool
    not_sent: str | None = None


def submission(trade):
    # v2.7 checks NewOrder operations, including the SDK invalid-order bucket.
    require(get(trade, "order") is not None and get(trade, "order_status") is not None,
            "INVALID_TRADE_RESPONSE")
    rejected = any(label(get(op, "task")) == "NewOrder" and label(get(op, "status")) == "Failed"
                   for op in get(trade, "operations", []))
    return Submission(str(get(get(trade, "order"), "order_id") or ""), rejected)


class KgiSessionOwner:
    """One owner of an injected session; all SDK operations serialize here.

    The factory owns login selection outside this source slice. Reconnect closes
    the old session before creating the next; it never resubmits an order.
    """

    def __init__(self, factory, account_id, trade_date, on_event, on_price=None):
        self._factory = factory
        self.account_id, self.trade_date = account_id, day(trade_date)
        self._on_event = on_event
        self._on_price = on_price
        self._price_symbols = set()
        self.callback_counts = {"order": 0, "deal": 0, "other": 0}
        self._lock = RLock()
        self._binding = None
        self._pending = {}
        self.generation = 0

    def start(self):
        with self._lock:
            require(self._binding is None, "SESSION_ALREADY_STARTED")
            binding = self._factory()
            require(type(binding) is SessionBinding, "INVALID_SESSION_FACTORY_RESULT")
            self._binding = binding
            try:
                require(type(binding) is SessionBinding and binding.account_id == self.account_id
                        and binding.trade_date == self.trade_date, "SESSION_BINDING_MISMATCH")
                self.generation += 1
                generation = self.generation
                # Freeze vendor values before the SDK can mutate a Trade/Event.
                def callback(event):
                    if generation != self.generation:
                        return
                    kind = label(get(event, "task"))
                    key = "deal" if kind == "Deal" else "order" if kind in {"NewOrder", "CancelOrder"} else "other"
                    self.callback_counts[key] += 1
                    self._on_event(event, generation)
                binding.api.Order.set_event(callback)
                quote = getattr(binding.api, "Quote", None)
                # Do not initialize lazy quote connections for account-only login.
                # Quotes are registered only after an explicit strategy exists.
                if self._on_price is not None and self._price_symbols:
                    self._attach_prices(quote, generation)
            except BaseException:
                self.close()
                raise

    def close(self):
        with self._lock:
            if self._binding is not None:
                self.generation += 1
                self._binding.api.logout()
                self._binding = None
                self._pending.clear()

    def reconnect(self):
        self.close()
        self.start()

    def _active(self):
        require(self._binding is not None, "SESSION_NOT_STARTED")
        require(self.date_matches(), "SESSION_DATE_EXPIRED")
        return self._binding

    def date_matches(self):
        binding = self._binding
        return binding is None or binding.current_day is None or binding.current_day() == self.trade_date

    @property
    def connected(self):
        return self._binding is not None

    @property
    def cash_inventory_required(self):
        return self._binding is not None and self._binding.cash_inventory_required

    def cash_inventory(self, clock, *, partial=False):
        """Read account-scoped evidence, never infer sellable from field names.

        SDK 2.1.0 documents shares for FType B but neither SALEQTY deduction
        semantics nor a complete/as-of watermark. NETQTY0 is only an upper
        bound; NETQTY9 is its component, not another position to add.
        """
        with self._lock:
            b = self._active()
            query = getattr(b.api.Account, "InventorySum", None)
            require(callable(query), "CASH_INVENTORY_UNAVAILABLE")
            started = clock().isoformat()
            rows = records(query("B"), {"Symbol", "NETQTY0", "NETQTY9"})
            holdings, reported = {}, []
            for row in rows:
                symbol = row.get("Symbol")
                identifier(symbol)
                require(report_account_matches(row, self.account_id) is True, "BROKER_ACCOUNT_MISMATCH")
                total, odd = whole(row["NETQTY0"]), whole(row["NETQTY9"])
                require(symbol not in holdings, "CASH_INVENTORY_AMBIGUOUS")
                holdings[symbol] = max(total, odd)  # OMI also supports 0/120 odd-only responses
                reported.append({"symbol": symbol, "reported_total_shares": total, "odd_shares": odd,
                                 "holding_upper_bound_shares": holdings[symbol]})
            # All account channels, not the external_orders projection. An empty
            # or partial report does not certify that no external sell exists.
            report_error = None
            try:
                reports = records(b.api.Account.OrderReport(), {"OrderNo", "TradeDate", "StockID", "Side"})
            except Exception as exc:
                if not partial:
                    raise
                reports = []
                report_error = exc.code if isinstance(exc, ExecutionRejected) else "SDK_READ_FAILED"
            orders, diagnostics = [], []
            for index, row in enumerate(reports):
                try:
                    orders.append(report_observation(row, self.account_id, deal=False))
                except ValueError as exc:
                    diagnostics.append(report_diagnostic(row, self.account_id, deal=False,
                                                         row_index=index, reason=str(exc)))
            return {"source": "Account.InventorySum(B)+Account.OrderReport", "holdings": holdings,
                    "reported": reported,
                    "orders": tuple(orders), "diagnostics": tuple(diagnostics),
                    "queried_at": started, "received_at": clock().isoformat(),
                    "generation": self.generation, "sellable_status": "UNVERIFIED",
                    "source_as_of": None, "report_complete": False, "report_error": report_error}

    def watch_price(self, symbol, odd_lot):
        identifier(symbol)
        with self._lock:
            binding = self._active()
            quote = getattr(binding.api, "Quote", None)
            require(self._on_price is not None and callable(getattr(quote, "subscribe_all", None))
                    and callable(getattr(quote, "set_cb_all", None)), "NATIVE_PRICE_SOURCE_UNAVAILABLE")
            key = (symbol, odd_lot)
            if key not in self._price_symbols:
                if not self._price_symbols:
                    generation = self.generation
                    quote.set_cb_all(lambda event: self._on_price(event, generation))
                quote.subscribe_all(symbol, odd_lot=odd_lot)
                self._price_symbols.add(key)

    def _attach_prices(self, quote, generation):
        require(callable(getattr(quote, "set_cb_all", None)) and callable(getattr(quote, "subscribe_all", None)),
                "NATIVE_PRICE_SOURCE_UNAVAILABLE")
        quote.set_cb_all(lambda event: self._on_price(event, generation))
        for symbol, odd in self._price_symbols:
            quote.subscribe_all(symbol, odd_lot=odd)

    def submit(self, command: Command, *, before_send=None):
        command.validate()
        with self._lock:
            b = self._active()
            if before_send is not None:
                try:
                    allowed = before_send()  # Runtime-owned check under this same SDK lock
                except Exception:
                    return Submission("", False, "PRE_EFFECT_CHECK_FAILED")
                if not allowed:
                    return Submission("", False, "CASH_EXIT_CAPACITY_CHANGED_NOT_SENT")
            price = decimal(command.price)
            native_price = int(price) if price == price.to_integral_value() else float(price)
            require(decimal(native_price) == price, "PRICE_PRECISION_LOSS")
            trade = b.api.Order.create_order(
                action=getattr(b.sdk.Action, command.action), symbol=command.symbol,
                qty=command.quantity // command.shares_per_unit, price=native_price,
                time_in_force=b.sdk.TimeInForce.ROD, order_cond=getattr(b.sdk.OrderCond, command.condition),
                odd_lot=getattr(b.sdk.OddLot, command.lot), name="omi_execution")
            self._pending[command.execution_id] = trade
            return submission(trade)

    def pending_returns(self):
        with self._lock:
            return {execution_id: submission(trade)
                    for execution_id, trade in self._pending.items()}

    def _trade_query(self, binding):
        trade_map = binding.api.Order.get_trades(full=True)
        require(type(trade_map) is dict, "TRADE_QUERY_UNAVAILABLE")
        invalid = trade_map.get("無效單", [])
        require(type(invalid) is list, "INVALID_TRADE_BUCKET_FORMAT")
        for trade in [*invalid, *(t for key, t in trade_map.items() if key != "無效單")]:
            require(get(trade, "order") is not None and get(trade, "order_status") is not None,
                    "INVALID_TRADE_RESPONSE")
        cached, snapshots = set(), []
        for order_id, trade in trade_map.items():
            if order_id == "無效單":
                continue
            require(str(get(get(trade, "order"), "order_id")) == str(order_id), "CACHE_ID_MISMATCH")
            key = BrokerKey(self.account_id, self.trade_date, str(order_id))
            cached.add(key)
            order, status = get(trade, "order"), get(trade, "order_status")
            action, condition, lot = labels(get(order, "action"), get(order, "order_cond"), get(order, "odd_lot"))
            deals = get(status, "deals")
            require(type(deals) is list, "CACHE_FILL_HISTORY_UNAVAILABLE")
            if get(status, "modified_time") and get(status, "modified_quantity") is not None:
                snapshots.append(Observation(key, "SNAPSHOT", "Order.get_trades(full=True)",
                    parse_stamp(self.trade_date, get(status, "modified_time")), str(get(order, "symbol")),
                    action, condition, lot, quantity=whole(get(order, "quantity")),
                    price=str(decimal(get(order, "price"))), remaining=whole(get(status, "modified_quantity")),
                    cumulative=sum(whole(get(deal, "quantity")) for deal in deals),
                    broker_status=label(get(status, "status"))))
        return cached, snapshots, len(invalid)

    def query(self, *, partial=False) -> QueryBatch:
        with self._lock:
            b = self._active()
            sources = []

            def read(source, operation, fallback):
                try:
                    value = operation()
                except Exception as exc:
                    if not partial:
                        raise
                    # Only fixed validation codes leave the SDK owner. Never
                    # serialize arbitrary vendor messages/account information.
                    sources.append(SourceRead(source, "UNAVAILABLE",
                        reason=exc.code if isinstance(exc, ExecutionRejected) else "SDK_READ_FAILED"))
                    return fallback
                sources.append(SourceRead(source, "AVAILABLE", len(value[0]) if source == "Order.get_trades(full=True)" else len(value)))
                return value

            order_rows = read("Account.OrderReport", lambda: records(b.api.Account.OrderReport(),
                {"OrderNo", "TradeDate", "StockID", "Qty"}), [])
            cached, snapshots, invalid_count = read("Order.get_trades(full=True)", lambda: self._trade_query(b), (set(), [], 0))
            # SDK 2.1.0 main.set_Account exposes this on Account, although
            # OrderAPI itself owns ExecReport. Preserve the physical source.
            exec_report = getattr(b.api.Order, "ExecReport", None)
            deal_source = "Order.ExecReport"
            if not callable(exec_report):
                exec_report = getattr(b.api.Account, "ExecReport", None)
                deal_source = "Account.ExecReport"
            def exec_rows():
                require(callable(exec_report), "EXEC_REPORT_UNAVAILABLE")
                return records(exec_report(), {"OrderNo", "TradeDate", "DealQty", "CNT"})
            deal_rows = read(deal_source, exec_rows, [])
            observations, diagnostics = [], []
            for deal, rows in ((False, order_rows), (True, deal_rows)):
                for index, row in enumerate(rows):
                    try:
                        observation = report_observation(row, self.account_id, deal=deal)
                        observations.append(replace(observation, source=deal_source) if deal else observation)
                    except ValueError as exc:
                        # Only row normalization errors are isolated. Session IO,
                        # schema/cache errors and unexpected bugs still propagate.
                        diagnostic = report_diagnostic(row, self.account_id, deal=deal,
                                                       row_index=index, reason=str(exc))
                        diagnostics.append(replace(diagnostic, source=deal_source) if deal else diagnostic)
            sources = tuple(replace(s, status="PARTIAL") if s.status == "AVAILABLE" and
                            any(d.source == s.source for d in diagnostics) else s for s in sources)
            return QueryBatch(tuple(observations), frozenset(cached), invalid_count, tuple(snapshots),
                              diagnostics=tuple(diagnostics), sources=sources)

    def cancel(self, key: BrokerKey, command: Command):
        key.validate()
        with self._lock:
            b = self._active()
            require(key.account_id == self.account_id and key.trade_date == self.trade_date,
                    "CANCEL_SESSION_MISMATCH")
            trades = b.api.Order.get_trades(full=True)
            require(type(trades) is dict and key.order_id in trades, "ORDER_NOT_IN_SDK_SESSION")
            order = get(trades[key.order_id], "order")
            action, condition, lot = labels(get(order, "action"), get(order, "order_cond"), get(order, "odd_lot"))
            require(str(get(order, "order_id")) == key.order_id and str(get(order, "symbol")) == command.symbol
                    and (action, condition, lot) == (command.action, command.condition, command.lot)
                    and whole(get(order, "quantity")) * command.shares_per_unit == command.quantity
                    and decimal(get(order, "price")) == decimal(command.price), "CANCEL_TARGET_MISMATCH")
            return b.api.Order.cancel_order(key.order_id)
