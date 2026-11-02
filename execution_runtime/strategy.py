"""Pure mutable-strategy contracts/replay/projections, never a broker ledger.

Broker quantities come from the runtime's existing order/fill facts. An exit
claim reserves its entire quantity until actual fills consume it. Cancellation,
rejection or UNKNOWN never makes an uncertain reservation reusable.
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta, timezone

from execution.validation import identifier, integer, money, require
from .contracts import Command, decimal, digest, encoded
from .review import stamp


STRATEGY_VERSION = 1
KINDS = frozenset({"STRATEGY_CREATED", "STRATEGY_REVISED", "STRATEGY_EXIT_REQUESTED",
                   "STRATEGY_PRICE_OBSERVED", "STRATEGY_EXIT_CLAIMED"})
CONSENT_POLICY = "MUTABLE_REDUCE_EXIT_V1_PROVISIONAL"


def price_trigger(rules, price):
    value = decimal(price)
    return ("STOP" if rules.stop_loss is not None and value <= decimal(rules.stop_loss) else
            "TAKE_PROFIT" if rules.take_profit is not None and value >= decimal(rules.take_profit) else None)


@dataclass(frozen=True)
class StrategyRules:
    stop_loss: str | None
    take_profit: str | None
    exit_limit_price: str
    protection_mode: str = "LOCAL_SYNTHETIC"

    def validate(self):
        require(self.protection_mode == "LOCAL_SYNTHETIC", "BROKER_NATIVE_PROTECTION_UNSUPPORTED")
        for value in (self.stop_loss, self.take_profit, self.exit_limit_price):
            if value is None:
                continue
            require(type(value) is str and len(value) <= 64, "INVALID_STRATEGY_PRICE")
            price = decimal(value)
            money(price, positive=True)
            native = int(price) if price == price.to_integral_value() else float(price)
            require(decimal(native) == price, "PRICE_PRECISION_LOSS")
        require(self.exit_limit_price is not None, "EXIT_LIMIT_REQUIRED")
        if self.stop_loss is not None and self.take_profit is not None:
            require(decimal(self.stop_loss) < decimal(self.take_profit), "INVALID_PROTECTION_LEVELS")


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    observed_at: str
    content: dict

    def validate(self):
        identifier(self.source_id)
        stamp(self.observed_at)
        require(type(self.content) is dict, "INVALID_STRATEGY_SOURCE")
        require(len(encoded(self.content)) <= 65536, "STRATEGY_SOURCE_TOO_LARGE")


def source_payload(source):
    require(type(source) is SourceSnapshot, "INVALID_STRATEGY_SOURCE")
    source.validate()
    body = asdict(source)
    return {**body, "digest": digest(body)}


def validate_source(value, occurred_at):
    require(type(value) is dict and set(value) == {"source_id", "observed_at", "content", "digest"},
            "INVALID_STRATEGY_SOURCE")
    source = SourceSnapshot(value["source_id"], value["observed_at"], value["content"])
    require(value == source_payload(source), "STRATEGY_SOURCE_DIGEST_MISMATCH")
    require(stamp(source.observed_at) <= stamp(occurred_at), "FUTURE_STRATEGY_SOURCE")


@dataclass(frozen=True)
class Strategy:
    entry: Command
    review_id: str
    review_digest: str
    owner_id: str
    source: str
    revision: int
    rules: StrategyRules
    source_snapshot: dict
    created_at: str
    updated_at: str
    target_position: int | None = None
    exit_owner: str | None = None
    exit_reason: str | None = None
    exits: tuple[Command, ...] = ()
    requests: dict = field(default_factory=dict)
    last_price_at: str | None = None


def exit_command(strategy, quantity, trade_date=None):
    """Deterministic child identity; all economic fields stay in the journal."""
    identity = "exit-" + digest([strategy.entry.execution_id, len(strategy.exits) + 1])
    return replace(strategy.entry, request_id=identity, intent_id=identity,
                   action="Sell", quantity=quantity, price=strategy.rules.exit_limit_price,
                   revision=strategy.revision, trade_date=trade_date or strategy.entry.trade_date)


def _target(strategy, target, request_id, reason):
    if strategy.target_position is None or target < strategy.target_position:
        return replace(strategy, target_position=target, exit_owner=request_id, exit_reason=reason)
    return strategy


def replay(records, reviews):
    """Same deterministic validation on append and startup; no database/cache."""
    strategies = {}
    for kind, occurred_at, payload in records:
        require(kind in KINDS, "UNSUPPORTED_STRATEGY_EVENT")
        require(type(payload) is dict and type(payload.get("strategy_version")) is int
                and payload["strategy_version"] == STRATEGY_VERSION, "UNSUPPORTED_STRATEGY_VERSION")
        sid, revision = payload.get("strategy_id"), payload.get("strategy_revision")
        identifier(sid)
        integer(revision, positive=True)
        stamp(occurred_at)
        base = {"strategy_version", "strategy_id", "strategy_revision"}
        extras = {
            "STRATEGY_CREATED": {"review_id", "review_digest", "rules", "source_snapshot", "consent_policy"},
            "STRATEGY_REVISED": {"request_id", "rules", "source_snapshot"},
            "STRATEGY_EXIT_REQUESTED": {"request_id", "target_position", "reason", "source_snapshot"},
            "STRATEGY_PRICE_OBSERVED": {"request_id", "symbol", "price", "source_snapshot"},
            "STRATEGY_EXIT_CLAIMED": {"command", "exit_owner", "target_position"},
        }[kind]
        require(set(payload) == base | extras, "INVALID_STRATEGY_RECORD")
        if "source_snapshot" in payload:
            validate_source(payload["source_snapshot"], occurred_at)
        if "rules" in payload:
            require(type(payload["rules"]) is dict, "INVALID_STRATEGY_RULES")
            rules = StrategyRules(**payload["rules"])
            rules.validate()
        if kind == "STRATEGY_CREATED":
            review = reviews.get(payload["review_id"])
            require(sid not in strategies and review is not None and review.state == "EXECUTION",
                    "EXECUTED_STRATEGY_REVIEW_REQUIRED")
            entry = review.draft.command
            require(entry.strategy_id == sid and entry.revision == revision and
                    review.snapshot["digest"] == payload["review_digest"], "STRATEGY_REVIEW_MISMATCH")
            require((entry.action, entry.condition) == ("Buy", "CASH"), "STRATEGY_ENTRY_UNSUPPORTED")
            require(payload["consent_policy"] == CONSENT_POLICY, "UNSUPPORTED_STRATEGY_CONSENT")
            require(stamp(review.confirmed_at) <= stamp(occurred_at), "STRATEGY_TIME_REVERSED")
            strategies[sid] = Strategy(entry, review.draft.review_id, payload["review_digest"],
                review.draft.owner_id, review.draft.source, revision, rules, payload["source_snapshot"],
                occurred_at, occurred_at)
            continue
        require(sid in strategies, "UNKNOWN_STRATEGY")
        strategy = strategies[sid]
        require(stamp(occurred_at) >= stamp(strategy.updated_at), "STRATEGY_TIME_REVERSED")
        require(revision == strategy.revision + (kind == "STRATEGY_REVISED"), "STALE_STRATEGY_REVISION")
        request_id = payload.get("request_id")
        if request_id is not None:
            identifier(request_id)
            require(request_id not in strategy.requests, "DUPLICATE_STRATEGY_REQUEST")
            strategy = replace(strategy, requests={**strategy.requests, request_id: (kind, payload)})
        if kind == "STRATEGY_REVISED":
            strategy = replace(strategy, rules=rules, revision=revision, source_snapshot=payload["source_snapshot"])
        elif kind == "STRATEGY_EXIT_REQUESTED":
            target = payload["target_position"]
            integer(target)
            require(target % strategy.entry.shares_per_unit == 0, "QUANTITY_UNIT_MISMATCH")
            require(payload["reason"] in {"MANUAL", "REDUCE"} and
                    (payload["reason"] == "REDUCE" or target == 0), "INVALID_EXIT_REASON")
            require(strategy.target_position is None or target <= strategy.target_position,
                    "NEW_EXPOSURE_REQUIRES_PREVIEW_CONFIRM")
            strategy = _target(strategy, target, request_id, payload["reason"])
        elif kind == "STRATEGY_PRICE_OBSERVED":
            require(payload["symbol"] == strategy.entry.symbol, "STRATEGY_SYMBOL_MISMATCH")
            require(type(payload["price"]) is str and decimal(payload["price"]) > 0,
                    "INVALID_STRATEGY_PRICE")
            observed_at = payload["source_snapshot"]["observed_at"]
            # Distinct ticks may share a source timestamp's precision. Only
            # strictly older ticks are ignored; request identity handles repeats.
            if strategy.last_price_at is None or stamp(observed_at) >= stamp(strategy.last_price_at):
                price, rules = decimal(payload["price"]), strategy.rules
                reason = price_trigger(rules, price)
                if reason:
                    strategy = _target(strategy, 0, request_id, reason)
                strategy = replace(strategy, last_price_at=observed_at)
        else:
            command = Command(**payload["command"])
            command.validate()
            claim_day = stamp(occurred_at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
            require(strategy.target_position is not None and payload["exit_owner"] == strategy.exit_owner
                    and payload["target_position"] == strategy.target_position and
                    strategy.entry.trade_date <= command.trade_date == claim_day and
                    command == exit_command(strategy, command.quantity, command.trade_date),
                    "STRATEGY_EXIT_CLAIM_MISMATCH")
            strategy = replace(strategy, exits=(*strategy.exits, command))
        strategies[sid] = replace(strategy, updated_at=occurred_at)
    return strategies


def quantities(strategy, entry, exits, trade_date=None):
    """Projection from canonical orders. No virtual ownership of fungible stock."""
    entered = entry["filled_shares"]
    exited = sum(o["filled_shares"] for o in exits)
    committed = sum(c.quantity for c, o in zip(strategy.exits, exits) if o["submit_stage"] != "NOT_SENT")
    require(0 <= exited <= committed <= entered, "STRATEGY_QUANTITY_CONFLICT")
    effective, reserved = entered - exited, committed - exited
    if entered == strategy.entry.quantity:
        remaining = 0
    elif entry["state"] in {"CANCELLED", "REJECTED"}:
        remaining = None if entry["reconcile_required"] else 0
    else:
        remaining = strategy.entry.quantity - entered
    prior_session = trade_date is not None and strategy.entry.trade_date < trade_date
    if prior_session and remaining:
        # Yesterday's ROD cannot be cancelled today. Absence from today's
        # reports neither proves its final balance nor erases historical fills.
        remaining = None
    target = strategy.target_position
    available = max(0, effective - reserved - target) if target is not None else 0
    unresolved = entry["reconcile_required"] or any(o["reconcile_required"] for o in exits)
    if target is None:
        lifecycle = ("RECONCILING" if entry["state"] in {"UNKNOWN", "RECONCILING"} else
                     "ENTRY_ACTIVE" if not entered else "ENTRY_PARTIAL" if remaining else "ACTIVE")
    elif effective == 0 and remaining == 0 and reserved == 0 and not unresolved:
        lifecycle = "CLOSED"
    elif target > 0 and effective == target and remaining == 0 and reserved == 0 and not unresolved:
        lifecycle = "ACTIVE"
    else:
        lifecycle = "RECONCILING" if strategy.exits or entry["cancel_stage"] else "EXITING"
    blocked = [o["execution_id"] for o in exits if o["state"] in
               {"UNKNOWN", "REJECTED", "CANCELLED", "RECONCILING"} and o["filled_shares"] < o["quantity"]
               and o["submit_stage"] != "NOT_SENT"]
    return {"state": lifecycle, "entry_filled": entered, "exit_filled": exited,
            "entry_remaining": remaining, "effective_position": effective,
            "protected_quantity": effective, "reserved_exit_quantity": reserved,
            "available_exit_quantity": available, "target_position": target,
            "entry_session": "PRIOR_SESSION" if prior_session else "CURRENT_SESSION",
            "entry_cancel_eligible": not prior_session,
            "position_basis": "STRATEGY_FILL_LINEAGE_NOT_ACCOUNT_INVENTORY",
            "protection_guaranteed": False, "exit_order_type": "LOCAL_LIMIT_ROD",
            "exit_fill_guaranteed": False,
            "trigger_state": "TRIGGERED" if target is not None else "NOT_TRIGGERED",
            "exit_execution_state": "FILLED" if committed and exited == committed else
                                    "CLAIMED_UNFILLED" if committed else "NOT_SUBMITTED",
            "unresolved_exit_claims": blocked, "reconcile_required": unresolved,
            "not_sent_exits": [o["execution_id"] for o in exits if o["submit_stage"] == "NOT_SENT"],
            "fill_history_complete": False}
