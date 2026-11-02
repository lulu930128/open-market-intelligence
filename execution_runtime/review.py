"""Typed pre-trade workflow and journal replay; no IO or strategy execution.

Review revision selects a command snapshot. Command.revision remains opaque
strategy lineage; this module does not freeze or implement a strategy.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime

from execution.validation import identifier, instant, integer, money, require
from .contracts import Command, decimal, digest


REVIEW_VERSION = 1  # versioned records inside the existing schema-v1 journal
KINDS = frozenset({"REVIEW_DRAFTED", "REVIEW_REVISED", "REVIEW_PREVIEWED",
                   "REVIEW_REJECTED", "REVIEW_CONFIRMED", "REVIEW_EXECUTION_CLAIMED"})


@dataclass(frozen=True)
class Draft:
    command: Command
    owner_id: str
    source: str  # provenance, never authentication or a second portfolio

    @property
    def review_id(self):
        return "review-" + digest([self.command.account_id, self.command.intent_id])

    def validate(self):
        require(type(self.command) is Command, "INVALID_COMMAND")
        identifier(self.owner_id)
        command = self.command
        for name in ("account_id", "trade_date", "request_id", "intent_id", "symbol",
                     "action", "price", "condition", "lot", "space_id"):
            require(type(getattr(command, name)) is str, "INVALID_COMMAND_FIELD")
        require(type(self.source) is str, "INVALID_DRAFT_SOURCE")
        allowed = {"USER_SPACE": {"MANUAL", "MOBILE", "LOCAL_STRATEGY"},
                   "AGENT_SPACE": {"AGENT_PROPOSAL"}}
        require(self.source in allowed.get(command.space_id, set()), "INVALID_DRAFT_SOURCE")
        command.validate()
        require((command.strategy_id is None) == (command.revision is None),
                "STRATEGY_LINEAGE_INCOMPLETE")
        require(self.source != "LOCAL_STRATEGY" or command.strategy_id is not None,
                "STRATEGY_LINEAGE_REQUIRED")
        # Reject known unsupported precision before a confirmation can be saved.
        # The adapter independently checks its actual native call mapping.
        require(len(command.price) <= 64, "INVALID_LIMIT_PRICE")
        price = decimal(command.price)
        money(price, positive=True)
        try:
            native = int(price) if price == price.to_integral_value() else float(price)
            require(decimal(native) == price, "PRICE_PRECISION_LOSS")
        except (OverflowError, ValueError):
            raise ValueError("PRICE_PRECISION_LOSS") from None


def draft_from(value):
    require(type(value) is dict and set(value) == {"command", "owner_id", "source"}, "INVALID_DRAFT")
    require(type(value["command"]) is dict, "INVALID_COMMAND")
    try:
        result = Draft(Command(**value["command"]), value["owner_id"], value["source"])
    except TypeError:
        raise ValueError("INVALID_COMMAND_FIELDS") from None
    result.validate()
    return result


def stamp(value):
    require(type(value) is str, "INVALID_REVIEW_TIMESTAMP")
    try:
        result = datetime.fromisoformat(value)
        instant(result)
    except ValueError:
        raise ValueError("INVALID_REVIEW_TIMESTAMP") from None
    return result


def expected(revision, command_digest):
    integer(revision, positive=True)
    require(type(command_digest) is str and len(command_digest) == 64 and
            all(c in "0123456789abcdef" for c in command_digest), "INVALID_REVIEW_DIGEST")


def snapshot(draft, revision, previewed_at):
    draft.validate()
    integer(revision, positive=True)
    stamp(previewed_at)
    command = draft.command
    body = {"review_version": REVIEW_VERSION, "review_id": draft.review_id,
            "review_revision": revision, "previewed_at": previewed_at,
            "draft": asdict(draft),
            "order_semantics": {"order_kind": "LIMIT", "time_in_force": "ROD",
                                "quantity_unit": "shares",
                                "broker_quantity": command.quantity // command.shares_per_unit}}
    return {**body, "digest": digest(body)}


@dataclass(frozen=True)
class Review:
    draft: Draft
    revision: int
    state: str
    created_at: str
    updated_at: str
    snapshot: dict | None = None
    confirmed_at: str | None = None
    execution_id: str | None = None


def replay(records):
    """Validate the entire versioned workflow stream, including old snapshots.

    ExecutionRuntime supplies journal rows and owns every transaction. There is
    no mutable review table/cache, migration, connection or second order reducer.
    """
    reviews = {}
    for record in records:
        kind, occurred_at, payload = record
        require(kind in KINDS, "UNSUPPORTED_REVIEW_EVENT")
        require(type(payload) is dict and type(payload.get("review_version")) is int
                and payload["review_version"] == REVIEW_VERSION, "UNSUPPORTED_REVIEW_VERSION")
        review_id, revision = payload.get("review_id"), payload.get("review_revision")
        identifier(review_id)
        integer(revision, positive=True)
        stamp(occurred_at)
        base = {"review_version", "review_id", "review_revision"}
        extras = {"REVIEW_DRAFTED": {"draft"}, "REVIEW_REVISED": {"draft"},
                  "REVIEW_PREVIEWED": {"snapshot"}, "REVIEW_REJECTED": {"reason"},
                  "REVIEW_CONFIRMED": {"digest"},
                  "REVIEW_EXECUTION_CLAIMED": {"digest", "execution_id"}}[kind]
        require(set(payload) == base | extras, "INVALID_REVIEW_RECORD")
        if kind == "REVIEW_DRAFTED":
            draft = draft_from(payload["draft"])
            require(review_id not in reviews and revision == 1 and draft.review_id == review_id,
                    "JOURNAL_REVIEW_IDENTITY_MISMATCH")
            require(not any(r.draft.command.account_id == draft.command.account_id and
                            r.draft.command.request_id == draft.command.request_id for r in reviews.values()),
                    "JOURNAL_REVIEW_REQUEST_CONFLICT")
            reviews[review_id] = Review(draft, 1, "DRAFT", occurred_at, occurred_at)
            continue
        require(review_id in reviews, "JOURNAL_REVIEW_MISSING_DRAFT")
        review = reviews[review_id]
        require(stamp(occurred_at) >= stamp(review.updated_at), "JOURNAL_REVIEW_TIME_REVERSED")
        if kind == "REVIEW_REVISED":
            draft = draft_from(payload["draft"])
            old = review.draft
            # Preserve ownership, request, intent, space and strategy identity.
            def lineage(d):
                c = d.command
                return (c.account_id, c.trade_date, c.request_id, c.intent_id, c.space_id,
                        c.strategy_id, d.owner_id, d.source)
            require(review.state in {"DRAFT", "PREVIEW"} and revision == review.revision + 1
                    and draft.review_id == review_id and lineage(draft) == lineage(old),
                    "INVALID_REVIEW_REVISION")
            review = replace(review, draft=draft, revision=revision, state="DRAFT", snapshot=None)
        else:
            require(revision == review.revision, "STALE_REVIEW_REVISION")
            if kind == "REVIEW_PREVIEWED":
                require(type(payload["snapshot"]) is dict, "JOURNAL_REVIEW_SNAPSHOT_MISMATCH")
                require(review.state == "DRAFT" and payload["snapshot"] ==
                        snapshot(review.draft, revision, payload["snapshot"].get("previewed_at")),
                        "JOURNAL_REVIEW_SNAPSHOT_MISMATCH")
                require(stamp(review.updated_at) <= stamp(payload["snapshot"]["previewed_at"])
                        <= stamp(occurred_at), "INVALID_REVIEW_TIMESTAMP")
                review = replace(review, state="PREVIEW", snapshot=payload["snapshot"])
            elif kind == "REVIEW_REJECTED":
                identifier(payload["reason"], "INVALID_REJECTION_REASON")
                require(review.state in {"DRAFT", "PREVIEW"}, "REVIEW_NOT_REJECTABLE")
                review = replace(review, state="REJECTED")
            else:
                expected(revision, payload["digest"])
                require(review.snapshot is not None and payload["digest"] == review.snapshot["digest"],
                        "REVIEW_DIGEST_MISMATCH")
                if kind == "REVIEW_CONFIRMED":
                    require(review.state == "PREVIEW", "REVIEW_NOT_CONFIRMABLE")
                    review = replace(review, state="CONFIRMED", confirmed_at=occurred_at)
                else:
                    require(review.state == "CONFIRMED" and payload["execution_id"] ==
                            review.draft.command.execution_id, "JOURNAL_REVIEW_EXECUTION_MISMATCH")
                    review = replace(review, state="EXECUTION", execution_id=payload["execution_id"])
        reviews[review_id] = replace(review, updated_at=occurred_at)
    return reviews
