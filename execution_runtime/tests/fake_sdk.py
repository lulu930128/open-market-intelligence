"""Invented KGI-shaped objects; never imports native SDK or opens a socket."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace as NS

from execution_runtime.contracts import Command
from execution_runtime.kgi import SessionBinding


NOW = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
DAY = "2026-10-29"
ACCOUNT = "fixture-account"
SDK = NS(Action=NS(Buy="Buy", Sell="Sell"), TimeInForce=NS(ROD="ROD"),
         OrderCond=NS(CASH="CASH", MARGIN="MARGIN", CASH_SELLING="CASH_SELLING", SHORT_SELLING="SHORT_SELLING"),
         OddLot=NS(Odd="Odd", Common="Common"))


def command(**changes):
    return replace(Command(ACCOUNT, DAY, "request-1", "intent-1", "TEST", "Buy", 10, "50"), **changes)


class Frame:
    def __init__(self, rows, columns):
        self.rows, self.columns = rows, set(columns)

    def to_dict(self, orient):
        assert orient == "records"
        return [dict(row) for row in self.rows]


class FakeBroker:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.orders, self.order_rows, self.deal_rows = {}, [], []
        self.attempts, self.cancels = [], []
        if self.path and self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            self.__dict__.update(value)

    def save(self):
        if self.path:
            self.path.write_text(json.dumps({key: getattr(self, key) for key in
                ("orders", "order_rows", "deal_rows", "attempts", "cancels")}), encoding="utf-8")

    def add(self, args, order_id=None, *, channel="API"):
        order_id = order_id or f"O{len(self.orders)+1:04}"
        self.orders[order_id] = {**args, "order_id": order_id, "quantity": args["qty"]}
        self.order_rows.append(self.row(order_id, "I", "100000", channel=channel))
        self.save()
        return order_id

    def row(self, oid, function, stamp, *, channel="API"):
        o = self.orders[oid]
        return {"Account": ACCOUNT, "TradeDate": DAY.replace("-", ""), "OrderNo": oid,
                "StockID": o["symbol"], "Side": {"Buy": "B", "Sell": "S"}[o["action"]],
                "Qty": o["qty"], "Price": o["price"], "OrdLot": o["odd_lot"], "OrdClass": o["order_cond"],
                "TimeInForceN": "R", "OrderFunc": function, "ErrCode": "0", "ReportTime": stamp,
                "AfterQty": 0 if function == "D" else o["qty"], "Channel": channel, "CNT": "order-" + stamp}

    def fill(self, oid, quantity, fill_id="fill-1", stamp="100001", price="50"):
        row = self.row(oid, "I", stamp)
        row.update(DealQty=quantity, CNT=fill_id, Price=price)
        self.deal_rows.append(row)
        self.save()
        o = self.orders[oid]
        return NS(task="Deal", status=None, order_id=oid, seqno=fill_id, action=o["action"],
                  symbol=o["symbol"], quantity=quantity, price=price, order_cond=o["order_cond"],
                  time_in_force="ROD", odd_lot=o["odd_lot"], ts=stamp)


class FakeSession:
    def __init__(self, broker=None, *, submit_mode="accept", callback_before_return=False):
        self.broker = broker or FakeBroker()
        self.submit_mode = submit_mode
        self.callback_before_return = callback_before_return
        self.Order = self
        self.Account = NS(OrderReport=self.account_report)
        self.event = lambda event: None
        self.disconnect_callback = lambda: None
        self.query_count = 0
        self.full_reads = []
        self.closed = False
        self.query_error = False
        self.cache_missing = False
        self.cancel_ack_only = False
        self.cancel_fill = None
        self.before_create = None
        self.after_create = None
        self.pending_trade = None
        self.invalid = []

    def binding(self):
        return SessionBinding(self, SDK, ACCOUNT, DAY)

    def logout(self):
        self.closed = True

    def set_event(self, callback):
        self.event = callback

    def set_disconnect_cb(self, callback):
        self.disconnect_callback = callback

    def create_order(self, **args):
        if self.before_create:
            self.before_create()
        self.broker.attempts.append(args)
        self.broker.save()
        if self.submit_mode == "error_before":
            raise TimeoutError("fixture")
        if self.submit_mode == "reject":
            trade = NS(order=NS(**args, order_id="", quantity=args["qty"]), order_status=NS(status="Failed", deals=[]),
                       operations=[NS(task="NewOrder", status="Failed")])
            self.invalid.append(trade)
            return trade
        oid = self.broker.add(args)
        if self.after_create:
            self.after_create()
        if self.submit_mode == "error_after":
            raise TimeoutError("fixture")
        if self.callback_before_return:
            self.event(self.event_for(oid))
        trade = self.trade(oid)
        if self.submit_mode == "pending":
            trade.order.order_id = ""
            self.pending_trade = trade
        return trade

    def event_for(self, oid, *, task="NewOrder", status="Success", stamp="100000"):
        o = self.broker.orders[oid]
        return NS(task=task, status=status, order_id=oid, seqno="order-" + stamp,
                  action=o["action"], symbol=o["symbol"], quantity=o["qty"], price=o["price"],
                  order_cond=o["order_cond"], time_in_force="ROD", odd_lot=o["odd_lot"], ts=stamp)

    def trade(self, oid):
        o = self.broker.orders[oid]
        deals = [r for r in self.broker.deal_rows if r["OrderNo"] == oid]
        total = sum(r["DealQty"] for r in deals)
        reports = [r for r in self.broker.order_rows if r["OrderNo"] == oid]
        report = max(reports, key=lambda r: r["ReportTime"])
        cancelled = report["OrderFunc"] == "D"
        status = ("Filled" if total == o["qty"] else
                  "PartFilled_Cancelled" if cancelled and total else "Cancelled" if cancelled else
                  "PartFilled" if total else "Submitted")
        stamp = max([report["ReportTime"], *(r["ReportTime"] for r in deals)])
        return NS(order=NS(**o), order_status=NS(status=status,
            deals=[NS(quantity=r["DealQty"], price=r["Price"], ts=r["ReportTime"]) for r in deals],
            modified_time=stamp, modified_quantity=0 if cancelled else o["qty"]-total))

    def get_trades(self, full):
        self.full_reads.append(full)
        if self.cache_missing:
            return {"無效單": []}
        return {"無效單": self.invalid, **{oid: self.trade(oid) for oid in self.broker.orders}}

    def account_report(self):
        self.query_count += 1
        if self.query_error:
            raise TimeoutError("fixture")
        return Frame(self.broker.order_rows, {"OrderNo", "TradeDate", "StockID", "Qty"})

    def ExecReport(self):
        return Frame(self.broker.deal_rows, {"OrderNo", "TradeDate", "DealQty", "CNT"})

    def cancel_order(self, oid):
        assert oid in self.broker.orders
        self.broker.cancels.append(oid)
        self.broker.save()
        self.event(self.event_for(oid, task="CancelOrder", stamp="100002"))
        if self.cancel_fill:
            self.event(self.broker.fill(oid, self.cancel_fill, "race-fill", "100001"))
        if not self.cancel_ack_only:
            self.broker.order_rows.append(self.broker.row(oid, "D", "100002"))
            self.broker.save()
        return NS(status="Success")
