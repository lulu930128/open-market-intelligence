"""Pure period ledger shared by domain owners and the continuation codec.

No Session, persistence, stop signal or provider dependency. Only the caller
knows whether a period has committed/rolled back and may notify its checkpoint.
"""
from copy import deepcopy
from typing import Callable


class BackfillContextChanged(ValueError):
    """The durable cursor cannot be applied to this canonical period universe."""


class BackfillProgress:
    def __init__(self, *, owner: str, identity: list, items: list,
                 counters: tuple[str, ...], checkpoint: Callable[[dict], None] | None = None,
                 resume_state: dict | None = None):
        self.owner = owner
        self.identity = identity
        self.callback = checkpoint
        if resume_state is None:
            self.state = dict(items=items, completed=0, results=[],
                              totals={name: 0 for name in counters}, identity=identity, deltas=[])
        else:
            validate_period_state(resume_state)
            if (resume_state["identity"] != identity or resume_state["items"] != items
                    or set(resume_state["totals"]) != set(counters)):
                raise BackfillContextChanged("JOB_PERIOD_CONTEXT_CHANGED")
            self.state = deepcopy(resume_state)

    @property
    def items(self):
        return self.state["items"]

    @property
    def completed(self):
        return self.state["completed"]

    @property
    def totals(self):
        return self.state["totals"]

    @property
    def results(self):
        return self.state["results"]

    def advance(self, *, notify: bool = True):
        previous = {name: sum(delta[name] for delta in self.state["deltas"])
                    for name in self.totals}
        self.state["deltas"].append({name: value - previous[name]
                                     for name, value in self.totals.items()})
        self.state["completed"] += 1
        validate_period_state(self.state)
        if notify:
            self.checkpoint()

    def checkpoint(self):
        """Also usable after rollback, without advancing the failed item."""
        validate_period_state(self.state)
        if self.callback is not None:
            self.callback(dict(safe_point="period_transaction_complete", owner=self.owner,
                               state=deepcopy(self.state), current=self.completed,
                               total=len(self.items)))


def validate_period_state(state):
    if type(state) is not dict or set(state) != {"items", "completed", "results", "totals", "identity", "deltas"}:
        raise ValueError("JOB_PERIOD_STATE_INVALID")
    if (type(state["items"]) is not list or not all(type(v) is str for v in state["items"])
            or len(set(state["items"])) != len(state["items"])
            or type(state["completed"]) is not int
            or not 0 <= state["completed"] <= len(state["items"])
            or type(state["results"]) is not list
            or len(state["results"]) != state["completed"]
            or not all(type(v) is dict for v in state["results"])
            or type(state["identity"]) is not list
            or type(state["deltas"]) is not list
            or len(state["deltas"]) != state["completed"]
            or type(state["totals"]) is not dict
            or not all(type(k) is str and type(v) is int and v >= 0 for k, v in state["totals"].items())):
        raise ValueError("JOB_PERIOD_STATE_INVALID")
    for delta in state["deltas"]:
        if (type(delta) is not dict or set(delta) != set(state["totals"])
                or not all(type(value) is int and value >= 0 for value in delta.values())):
            raise ValueError("JOB_PERIOD_STATE_INVALID")
    if any(sum(delta[name] for delta in state["deltas"]) != value
           for name, value in state["totals"].items()):
        raise ValueError("JOB_PERIOD_STATE_INVALID")
    for item, result in zip(state["items"], state["results"]):
        result_item = result.get("period", result.get("date"))
        if "month" in result:
            result_item = result["month"] + "-01"
        elif "trade_date" in result and "source_id" in result:
            result_item = f"{result['trade_date']}|{result['source_id']}"
        elif "group_id" in result and "mode" in result:
            result_item = f"{result['group_id']}|{result['mode']}"
        if result_item != item:
            raise ValueError("JOB_PERIOD_STATE_INVALID")
    totals, results = state["totals"], state["results"]
    expected = {}
    if "total_parsed_count" in totals:
        expected = {
            "total_parsed_count": sum(row["parsed_count"] for row in results),
            "total_inserted_count": sum(row["inserted_count"] for row in results),
            "total_skipped_count": sum(row["skipped_count"] for row in results),
            "fetched_month_count": sum(row["status"] == "success" for row in results),
            "skipped_existing_month_count": sum(row["status"] == "skipped_existing" for row in results),
        }
    elif "error_count" in totals:
        expected = {
            "error_count": sum(row["status"] == "error" for row in results),
            "skipped_existing_count": sum(row["status"] == "skipped_existing" for row in results),
        }
        if "updated_count" in totals:
            expected.update(inserted_count=sum(row["status"] == "inserted" for row in results),
                            updated_count=sum(row["status"] == "updated" for row in results))
        else:
            expected["inserted_count"] = sum(row["inserted_count"] for row in results)
    elif "metric_error_count" in totals:
        expected = {
            "metric_error_count": sum(row["status"] not in {"success", "skipped_existing"} for row in results),
            "metric_skipped_existing_count": sum(row["status"] == "skipped_existing" for row in results),
            "metric_inserted_count": sum(row["inserted_count"] for row in results),
        }
        for row, delta in zip(results, state["deltas"]):
            allowed = {0} if row["status"] == "skipped_existing" else {1} if row["status"] == "success" else {0, 1}
            if delta["metric_fetched_count"] not in allowed:
                raise ValueError("JOB_PERIOD_STATE_INVALID")
    elif "radar_saved_count" in totals:
        persisted = [row for row in results if row.get("snapshot_status") == "persisted"]
        evaluated = sum(row["radar_v2_active"]["outcomes"]["evaluated_count"] for row in persisted)
        expected = {
            "radar_saved_count": len(persisted), "radar_existing_count": 0,
            "radar_evaluated_count": evaluated, "radar_active_outcome_evaluated_count": evaluated,
            "radar_active_persisted_count": sum(row["radar_v2_active"]["evaluation_created_count"] for row in persisted),
            "radar_skipped_count": sum(row.get("snapshot_status") == "skipped" for row in results),
            "radar_invalid_count": sum(row.get("snapshot_status") == "stale" for row in results),
            "radar_shadow_persisted_count": 0, "radar_shadow_outcome_evaluated_count": 0,
        }
    if any(totals.get(name) != value for name, value in expected.items()):
        raise ValueError("JOB_PERIOD_STATE_INVALID")
