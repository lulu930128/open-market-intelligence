"""Disposable Order Desk fixture. Every business command uses the real application.

Not a deployed runtime transport: invented SDK, fixed fixture account/date, temp
journal only. Scenario cursor and query receipt are presentation/test metadata.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from execution.validation import require
from execution_runtime.application import ExecutionApplication
from execution_runtime.contracts import BrokerKey
from execution_runtime.review import Draft, draft_from
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.strategy import SourceSnapshot, StrategyRules
from .fake_sdk import ACCOUNT, DAY, NOW, FakeSession, command
from .test_strategy import activate, idle, source


CONTRACT = "omi.order-desk.fake.v1"
STEPS = ("entry_60", "stop_cancel40_exit60", "exit_60", "late_entry_15", "exit_15", "cancel_final")


class OrderDeskFake:
    def __init__(self):
        self.directory = TemporaryDirectory(prefix="omi-order-desk-fake-")
        self.sdk = FakeSession()
        self.sdk.cancel_ack_only = True
        self.runtime = ExecutionRuntime(Path(self.directory.name) / "fake.sqlite", account_id=ACCOUNT,
            trade_date=DAY, session_factory=self.sdk.binding, clock=lambda: NOW)
        self.runtime.start()
        self.app = ExecutionApplication(self.runtime)
        self.cursor = 0
        activate(self.app, sid="scenario-100-60-15")
        for space, name in (("USER_SPACE", "user-review"), ("AGENT_SPACE", "agent-review")):
            draft = Draft(command(request_id=name, intent_id=name, quantity=100, price="500",
                strategy_id=name, revision=1, space_id=space), "fixture-operator",
                "LOCAL_STRATEGY" if space == "USER_SPACE" else "AGENT_PROPOSAL")
            self.app.draft(draft)
            self.app.preview(draft.review_id, expected_revision=1)
        self.query_receipt = self.app.query()

    def close(self):
        self.runtime.close()
        self.directory.cleanup()

    def read(self):
        idle(self.runtime)
        reviews = self.app.list()  # no query, broker IO, refresh or mutation
        strategies = []
        for review in reviews:
            sid = review["draft"]["command"]["strategy_id"]
            if sid:
                try:
                    strategies.append(self.app.strategy_status(sid))
                except ValueError as error:
                    if str(error) != "UNKNOWN_STRATEGY":
                        raise
        return {"contract": CONTRACT, "mode": "FAKE_ONLY", "live_broker": "NOT_DEPLOYED",
            "account_id": ACCOUNT, "trade_date": DAY, "reviews": reviews, "strategies": strategies,
            "broker_snapshot": self.query_receipt, "scenario": {"strategy_id": "scenario-100-60-15",
                "completed_steps": self.cursor, "next_step": STEPS[self.cursor] if self.cursor < len(STEPS) else None}}

    def dispatch(self, body):
        require(type(body) is dict and type(body.get("type")) is str, "INVALID_COMMAND")
        kind = body["type"]
        fields = {
            "preview": {"review_id", "expected_revision"},
            "confirm": {"review_id", "expected_revision", "expected_digest"},
            "reject": {"review_id", "expected_revision", "reason"},
            "revise": {"review_id", "expected_revision", "draft"},
            "cancel": {"execution_id", "key"},
            "create_strategy": {"review_id", "expected_digest", "rules", "source"},
            "revise_strategy": {"strategy_id", "expected_revision", "request_id", "rules", "source"},
            "query": set(), "fake_step": {"step"}, "fake_snapshot": {"status"},
            "fake_submit_unknown": set(),
        }
        require(kind in fields and set(body) == fields[kind] | {"type"}, "INVALID_COMMAND_FIELDS")
        args = {k: v for k, v in body.items() if k != "type"}
        if kind == "cancel":
            require(type(args["key"]) is dict and set(args["key"]) == {"account_id", "trade_date", "order_id"},
                    "INVALID_BROKER_KEY")
            result = self.app.cancel(args["execution_id"], BrokerKey(**args["key"]))
        elif kind == "revise":
            result = self.app.revise(args["review_id"], draft_from(args["draft"]),
                                     expected_revision=args["expected_revision"])
        elif kind in {"create_strategy", "revise_strategy"}:
            args["rules"] = StrategyRules(**args["rules"])
            args["source"] = SourceSnapshot(**args["source"])
            result = getattr(self.app, kind)(**args)
        elif kind == "query":
            result = self.query_receipt = self.app.query()
        elif kind == "fake_submit_unknown":
            # Next canonical confirm reaches a fabricated timeout before return.
            # The owner keeps its claim; neither UI nor fixture retries submission.
            self.sdk.submit_mode = "error_after"
            result = {"next_fake_submit": "UNKNOWN"}
        elif kind == "fake_snapshot":
            require(args["status"] in {"AVAILABLE", "PARTIAL", "UNAVAILABLE"}, "INVALID_FAKE_SNAPSHOT")
            self.sdk.query_error = args["status"] == "UNAVAILABLE"
            # Exercise actual row quarantine; do not manufacture PARTIAL output.
            self.sdk.broker.order_rows = [r for r in self.sdk.broker.order_rows if r.get("OrderNo") != "bad-fixture"]
            if args["status"] == "PARTIAL":
                self.sdk.broker.order_rows.append({"OrderNo": "bad-fixture", "ErrCode": "bad"})
            result = self.query_receipt = self.app.query()
        elif kind == "fake_step":
            result = self.step(args["step"])
        else:
            result = getattr(self.app, kind)(**args)
        return result

    def step(self, step):
        require(self.cursor < len(STEPS) and step == STEPS[self.cursor], "STALE_SCENARIO_STEP")
        value = self.app.strategy_status("scenario-100-60-15")
        entry = value["entry"]["broker_order_id"]
        if step == "entry_60":
            self.sdk.event(self.sdk.broker.fill(entry, 60, "scenario-entry60", "100001", "500"))
        elif step == "stop_cancel40_exit60":
            self.app.observe_strategy_price(value["strategy_id"], source("fixture-stop", 1),
                request_id="fixture-stop", expected_revision=value["strategy_revision"], symbol="TEST", price="480")
        elif step == "exit_60":
            self.sdk.event(self.sdk.broker.fill(value["exits"][0]["broker_order_id"], 60,
                "scenario-exit60", "100003", "480"))
        elif step == "late_entry_15":
            self.sdk.event(self.sdk.broker.fill(entry, 15, "scenario-late15", "100004", "500"))
        elif step == "exit_15":
            self.sdk.event(self.sdk.broker.fill(value["exits"][1]["broker_order_id"], 15,
                "scenario-exit15", "100005", "480"))
        else:
            self.sdk.broker.order_rows.append(self.sdk.broker.row(entry, "D", "100010"))
        idle(self.runtime)
        self.query_receipt = self.app.query()
        idle(self.runtime)
        self.cursor += 1
        return self.app.strategy_status("scenario-100-60-15")
