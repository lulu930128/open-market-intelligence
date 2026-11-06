"""MCP local staging via CandidateService; explicit effects via Native only.

No SDK import, local order store, account discovery, login, or submit primitive.
"""
from .candidate_control import ControlRejected, command, request_control
from .candidate_service import CandidateService
import json


class ManualDeskService:
    def __init__(self, db=None, *, control=request_control):
        self.db, self.control = db, control

    def status(self):
        return self.control({"operation": "status"})

    def draft(self, value):
        return CandidateService(self.db, control=self.control).create(value, owner_id="MCP", manual_stage=True)

    def staged(self, identity=None, *, after="", limit=100):
        return CandidateService(self.db, control=self.control).staged(identity, after=after, limit=limit)

    def send_staged(self, identity, *, expected_revision, expected_digest):
        return CandidateService(self.db, control=self.control).send_staged(identity,
            expected_revision=expected_revision, expected_digest=expected_digest)

    def readback(self):
        # A dedicated read operation reuses SDK normalization without query()'s
        # reconciliation writes / strategy wake. No retry or lifecycle effects.
        return self.control({"operation": "readback"})

    def fills(self):
        value = self.readback()
        return {key: value[key] for key in ("contract", "trade_date", "session_generation", "queried_at",
            "received_at", "quality", "sources", "fills", "fill_history_complete", "unparsed_reports")}

    def inventory(self):
        value = self.readback()
        return {key: value[key] for key in ("contract", "trade_date", "session_generation", "queried_at",
            "received_at", "quality", "inventory")}

    def confirm(self, identity, *, expected_revision, expected_digest):
        return command(self.control, ["confirm", identity, "--expected-revision", str(expected_revision),
                                      "--expected-digest", expected_digest])

    def cancel(self, identity, *, trade_date, broker_order_id):
        return command(self.control, ["cancel", "--execution-id", identity, "--account-id", "SELECTED",
            "--trade-date", trade_date, "--broker-order-id", broker_order_id])

    def order(self, identity, *, market):
        return command(self.control, ["desk-order", "--market", market, "--execution-id", identity])

    def cancel_order(self, identity, *, market):
        return command(self.control, ["desk-cancel", "--market", market, "--execution-id", identity])

    def protection(self, identity, *, market, rules, request_id, expected_revision):
        return command(self.control, ["desk-protection", "--market", market, "--execution-id", identity,
            "--rules-json", json.dumps(rules, allow_nan=False), "--request-id", request_id,
            "--expected-revision", str(expected_revision)])
