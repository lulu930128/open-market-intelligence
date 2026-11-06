"""Invented US/TW facade. Never imports the installed SDK or logs in."""

from dataclasses import replace
from types import SimpleNamespace as NS

from execution_runtime.kgi_us import instrument_snapshot
from execution_runtime.us_contracts import UsAccountBinding, UsCommand
from .fake_sdk import DAY, SDK, Frame, FakeSession


US_ACCOUNT = "fixture-us-account"
SYMBOL = "FIX/A"
CONTRACTS = {SYMBOL: NS(symbol=SYMBOL, market="US", currency="USD", board_lot=1,
                        type="EQTY", isin="fixture-instrument")}
US_SDK = NS(**vars(SDK), Currency=NS(TWD="TWD", MUT="MUT"))


def us_command(**changes):
    return replace(UsCommand(US_ACCOUNT, DAY, "us-request", "us-intent", SYMBOL, "Buy", 2, "12.5",
                   "MUT", "OFFLINE", instrument_snapshot(CONTRACTS, SYMBOL)["revision"]), **changes)


class FakeUs:
    def __init__(self):
        self.trades, self.rows, self.deals = {}, [], []
        self.attempts, self.cancels = [], []
        self.mode = "normal"
        self.event = None
        self.contracts = CONTRACTS
        self.before_create = None

    def contract(self, kind):
        assert kind == "dic"
        return self.contracts

    def set_event(self, callback):
        self.event = callback

    def create_order(self, **args):
        if self.before_create:
            self.before_create()
        self.attempts.append(args)
        index = len(self.attempts)
        original, oid = f"original-{index}", f"us-order-{index}"
        order = NS(market="US", org_seqnum=original, order_id=oid, symbol=args["symbol"],
                   action=args["action"], quantity=args["qty"], price=args["price"], currency=args["currency"])
        trade = NS(order=order, order_status=NS(status="Submitted", deals=[]),
                   operations=[NS(task="NewOrder", status="Pending")])
        self.trades[original] = trade
        self.rows.append({"customer_id": US_ACCOUNT, "market": "US", "orderno": oid, "orig_seqnum": original,
            "trade_date": DAY.replace("-", "/") + " 10:00:00", "symbol": args["symbol"],
            "BuySell": "B" if args["action"] == "Buy" else "S", "qty": args["qty"], "price": args["price"],
            "trade_currency": "USD", "settle_currency": args["currency"], "action": "0",
            "order_err_code": "0", "sales_status_code": "2", "exe_qty": "0"})
        if self.mode == "timeout":
            raise TimeoutError("synthetic uncertain send")
        if self.mode == "none":
            return None
        if self.mode == "pending":
            trade.order.order_id = ""
        if self.event:
            self.event(self.order_event(original))
        return trade

    def order_event(self, original="original-1", **changes):
        o = self.trades[original].order
        return NS(**{**dict(market="US", task="NewOrder", status="委託成功", order_id=o.order_id,
                           org_seqnum=original, symbol=o.symbol, action=o.action, quantity=o.quantity,
                           price=o.price, ts="100000"), **changes})

    def get_trades(self):
        return self.trades

    def cancel_order(self, original):
        assert original in self.trades
        self.cancels.append(original)
        self.event(self.order_event(original, task="CancelOrder"))
        return self.trades[original]

    def OrderReport(self):
        return Frame(self.rows, {"customer_id", "market", "orderno", "orig_seqnum", "trade_date"})

    def ExecReport(self):
        return Frame(self.deals, {"customer_id", "market", "orderno", "trade_date", "exe_qty"})


class DualFactory:
    def __init__(self):
        self.tw_day = self.us_day = DAY
        self.us = FakeUs()
        self.sessions = []
        self.native = False
        self.us_account = US_ACCOUNT

    def current_day(self):
        return self.tw_day

    def __call__(self):
        tw = FakeSession()
        self.sessions.append(tw)
        tw.SubOrder = self.us
        tw.SubAccount = self.us
        return replace(tw.binding(), trade_date=self.tw_day, current_day=self.current_day, sdk=US_SDK,
            us=UsAccountBinding(self.us_account, "OFFLINE", self.us_day, "Asia/Taipei", lambda: self.us_day),
            native_session=self.native)
