"""Pure bounded-owner continuation ledger; no IO or lifecycle authority."""
from copy import deepcopy
from datetime import date, datetime

from app.utils.backfill_checkpoint import BackfillContextChanged


class OwnerOutcomeUnknown(BaseException):
    """No safe acknowledgement is possible; retain the actual worker outcome."""


COUNTERS = {
    "us_eod_symbols": ("attempted", "succeeded", "failed", "calls"),
    "us_priority_symbols": ("checked", "satisfied", "repaired", "calls", "rotated"),
    "tw_bootstrap_children": ("admitted", "calls"),
}


def validate_owner_state(state, *, safe=False):
    if type(state) is not dict or set(state) != {
        "version", "owner", "identity", "items", "results", "totals", "elapsed", "inflight", "context",
    }:
        raise ValueError("JOB_OWNER_STATE_INVALID")
    owner = state["owner"]
    if type(owner) is not str or owner not in COUNTERS or state["version"] != 1:
        raise ValueError("JOB_OWNER_STATE_INVALID")
    identity, items, results, totals = (state[k] for k in ("identity", "items", "results", "totals"))
    if (type(identity) is not dict or set(identity) != {"contract", "date", "release", "universe", "budget", "options"}
            or any(type(identity[k]) is not str or not identity[k] for k in ("contract", "date", "release"))
            or type(identity["universe"]) is not list or not all(type(x) is str for x in identity["universe"])
            or len(set(identity["universe"])) != len(identity["universe"])
            or type(identity["options"]) is not list
            or type(items) is not list or not all(type(x) is str for x in items)
            or len(set(items)) != len(items) or not set(items) <= set(identity["universe"])
            or type(results) is not list or len(results) > len(items)
            or type(totals) is not dict or set(totals) != set(COUNTERS[owner])
            or type(state["context"]) is not dict
            or type(state["elapsed"]) not in (int, float) or not 0 <= state["elapsed"] < float("inf")):
        raise ValueError("JOB_OWNER_STATE_INVALID")
    budget = identity["budget"]
    if (type(budget) is not dict or set(budget) != {"symbols", "calls", "runtime", "attempts"}
            or any(type(v) is not int or v < 0 for v in budget.values())
            or budget["symbols"] < len(items) or budget["runtime"] < 1):
        raise ValueError("JOB_OWNER_STATE_INVALID")
    try:
        for key in ("date", "release"):
            if date.fromisoformat(identity[key]).isoformat() != identity[key]:
                raise ValueError("date")
        _validate_context(owner, state["context"], identity, items)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("JOB_OWNER_CONTEXT_INVALID") from exc
    expected = dict.fromkeys(COUNTERS[owner], 0)
    for item, row in zip(items, results):
        if (type(row) is not dict or set(row) != {"item", "delta", "outcome"}
                or row["item"] != item or type(row["outcome"]) is not dict
                or type(row["delta"]) is not dict or set(row["delta"]) != set(expected)
                or any(type(v) is not int or v < 0 for v in row["delta"].values())):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        for key, value in row["delta"].items():
            expected[key] += value
        delta = row["delta"]
        outcome = row["outcome"]
        if delta["calls"] > budget["attempts"]:
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "us_eod_symbols" and (delta["attempted"] != 1 or delta["succeeded"] + delta["failed"] != 1):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "us_eod_symbols" and (
                set(outcome) != {"error", "rate_limited", "usage_known"}
                or type(outcome["rate_limited"]) is not bool or type(outcome["usage_known"]) is not bool
                or (outcome["error"] is not None and type(outcome["error"]) is not dict)
                or delta["failed"] != int(outcome["error"] is not None)):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "us_priority_symbols" and (delta["checked"] != 1 or not 0 <= delta["repaired"] <= delta["satisfied"] <= 1 or delta["rotated"] not in (0, 1)):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "us_priority_symbols" and (
                set(outcome) != {"error", "unresolved", "usage_unknown"}
                or type(outcome["usage_unknown"]) is not bool
                or any(outcome[k] is not None and type(outcome[k]) is not dict for k in ("error", "unresolved"))
                or delta["satisfied"] != int(outcome["error"] is None and outcome["unresolved"] is None)
                or delta["rotated"] != int(item in state["context"]["rotatable"])):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "tw_bootstrap_children" and (delta["admitted"] != 1 or delta["calls"] != 0):
            raise ValueError("JOB_OWNER_STATE_INVALID")
        if owner == "tw_bootstrap_children" and (
                set(outcome) != {"symbol", "job_id", "status", "created"} or outcome["symbol"] != item
                or (outcome["job_id"] is not None and (type(outcome["job_id"]) is not int or outcome["job_id"] <= 0))
                or type(outcome["status"]) is not str or type(outcome["created"]) is not bool):
            raise ValueError("JOB_OWNER_STATE_INVALID")
    inflight = state["inflight"]
    if inflight is not None:
        if (safe or type(inflight) is not dict or set(inflight) != {"item", "calls"}
                or len(results) >= len(items) or inflight["item"] != items[len(results)]
                or type(inflight["calls"]) is not int or inflight["calls"] < 0):
            raise ValueError("JOB_OWNER_INFLIGHT_UNKNOWN")
        expected["calls"] += inflight["calls"]
    if totals != expected or any(type(v) is not int for v in totals.values()) or totals["calls"] > budget["calls"]:
        raise ValueError("JOB_OWNER_STATE_INVALID")


def _validate_context(owner, context, identity, items):
    universe = identity["universe"]
    if owner == "us_eod_symbols":
        if (set(context) != {"candidates", "priority", "dispatch_offset", "initial_current", "consecutive_errors", "next_retry_at"}
                or any(type(context[k]) is not list or not all(type(x) is str for x in context[k]) for k in ("candidates", "priority"))
                or len(set(context["candidates"])) != len(context["candidates"])
                or not set(items) <= set(context["candidates"]) <= set(universe)
                or any(type(context[k]) is not int or context[k] < 0 for k in ("dispatch_offset", "initial_current", "consecutive_errors"))):
            raise ValueError("context")
        if context["next_retry_at"] is not None:
            parsed = datetime.fromisoformat(context["next_retry_at"])
            if parsed.utcoffset() is None:
                raise ValueError("retry")
    elif owner == "us_priority_symbols":
        if (set(context) != {"rotatable", "remaining", "cursor", "stopped_reason"}
                or type(context["rotatable"]) is not list or not all(type(x) is str for x in context["rotatable"])
                or not set(context["rotatable"]) <= set(universe)
                or type(context["remaining"]) is not int or not 0 <= context["remaining"] <= len(context["rotatable"])
                or (context["cursor"] is not None and type(context["cursor"]) is not str)
                or type(context["stopped_reason"]) is not str):
            raise ValueError("context")
    else:
        if (set(context) != {"requested_at", "target_plan"} or type(context["target_plan"]) is not dict
                or context["target_plan"].get("symbols") != items
                or datetime.fromisoformat(context["requested_at"]).utcoffset() is None):
            raise ValueError("context")


class OwnerWork:
    def __init__(self, owner, identity, items, *, continuation=None, resume_state=None, context=None):
        self.callback = continuation
        if resume_state is None:
            self.state = dict(version=1, owner=owner, identity=deepcopy(identity), items=list(items),
                results=[], totals=dict.fromkeys(COUNTERS[owner], 0), elapsed=0.0, inflight=None,
                context=deepcopy(context or {}))
        else:
            validate_owner_state(resume_state, safe=True)
            if resume_state["owner"] != owner or resume_state["identity"] != identity:
                raise BackfillContextChanged("JOB_OWNER_CONTEXT_CHANGED")
            self.state = deepcopy(resume_state)
        validate_owner_state(self.state, safe=True)

    def notify(self, phase):
        validate_owner_state(self.state, safe=phase == "checkpoint")
        if self.callback:
            self.callback(phase, deepcopy(self.state))

    def begin(self, calls):
        self.state["inflight"] = {"item": self.state["items"][len(self.state["results"])], "calls": calls}
        self.state["totals"]["calls"] += calls
        self.notify("save")

    def finish(self, delta, outcome):
        admission = self.state["inflight"]
        if admission is None or delta["calls"] > admission["calls"]:
            raise OwnerOutcomeUnknown("JOB_OWNER_CALL_ACCOUNTING_UNKNOWN")
        self.state["totals"]["calls"] -= admission["calls"]
        for key, value in delta.items():
            self.state["totals"][key] += value
        self.state["results"].append(dict(item=admission["item"], delta=delta, outcome=outcome))
        self.state["inflight"] = None
        validate_owner_state(self.state, safe=True)
