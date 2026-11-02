"""Candidate intent and three-valued predicates; never a broker command or ledger."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import operator
import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


TAIPEI = ZoneInfo("Asia/Taipei")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Metric(Model):
    kind: Literal["price", "rsi", "macd"]
    field: Literal["last_trade", "bid", "ask", "indicative", "value", "macd", "signal", "histogram"]
    timeframe: Literal["snapshot", "1d"]
    completed: bool = True
    parameters: tuple[int, ...] = ()

    @model_validator(mode="after")
    def supported_shape(self):
        if self.kind == "price":
            valid = self.timeframe == "snapshot" and not self.parameters and self.field in {"last_trade", "bid", "ask", "indicative"}
        elif self.kind == "rsi":
            valid = self.timeframe == "1d" and self.field == "value" and len(self.parameters) == 1 and self.parameters[0] > 0
        else:
            valid = (self.timeframe == "1d" and self.field in {"macd", "signal", "histogram"} and
                     len(self.parameters) == 3 and 0 < self.parameters[0] < self.parameters[1] and self.parameters[2] > 0)
        if not valid:
            raise ValueError("UNSUPPORTED_METRIC_CONTRACT")
        return self

    @property
    def key(self):
        return digest(self.model_dump(mode="json"))


class Comparison(Model):
    kind: Literal["compare"] = "compare"
    metric: Metric
    operator: Literal["<", "<=", ">", ">=", "=="]
    value: Decimal = Field(allow_inf_nan=False)


class Group(Model):
    kind: Literal["AND", "OR"]
    clauses: tuple[Annotated[Comparison | Group, Field(discriminator="kind")], ...] = Field(min_length=1)


Condition = Annotated[Comparison | Group, Field(discriminator="kind")]


class CandidateSpec(Model):
    symbol: str = Field(pattern=r"^[0-9A-Za-z]{2,12}$")
    space_id: Literal["AGENT_SPACE", "USER_SPACE"] = "AGENT_SPACE"
    source: Literal["AGENT_PROPOSAL", "MANUAL"] = "AGENT_PROPOSAL"
    direction: Literal["long", "short"]
    action: Literal["Buy", "Sell"]
    condition: Literal["CASH", "MARGIN", "CASH_SELLING", "SHORT_SELLING"]
    lot: Literal["Odd", "Common"]
    quantity: int = Field(gt=0, strict=True)
    reference_entry: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    exit_limit_price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    price_basis: Literal["support", "resistance", "explicit"] = "support"
    proposed_limit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    valid_from_date: str | None = None
    valid_until_date: str | None = None
    hold_overnight: bool = True
    conditions: Condition | None = None
    reference_notes: dict = Field(default_factory=dict)

    @field_validator("valid_from_date", "valid_until_date")
    @classmethod
    def absolute_date(cls, value):
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("DATE_MUST_BE_YYYY_MM_DD")
            date.fromisoformat(value)
        return value


def validate_raw(raw: dict) -> tuple[CandidateSpec | None, list[str]]:
    """Semantic failures remain raw research evidence instead of rejected writes."""
    try:
        spec = CandidateSpec.model_validate(raw)
    except ValidationError as exc:
        return None, ["INVALID_INPUT:" + ".".join(map(str, e["loc"])) + ":" + e["type"]
                      for e in exc.errors(include_input=False, include_url=False)]
    reasons = []
    if not spec.valid_from_date or not spec.valid_until_date:
        reasons.append("INCOMPLETE_DATE")
    elif spec.valid_from_date > spec.valid_until_date:
        reasons.append("INVALID_DATE_RANGE")
    if (spec.space_id, spec.source) not in {("AGENT_SPACE", "AGENT_PROPOSAL"), ("USER_SPACE", "MANUAL")}:
        reasons.append("INVALID_CANDIDATE_SPACE")
    allowed = ({("Buy", "CASH"), ("Buy", "MARGIN")} if spec.direction == "long" else
               {("Sell", "CASH"), ("Sell", "CASH_SELLING"), ("Sell", "SHORT_SELLING")})
    if spec.space_id == "AGENT_SPACE":
        allowed = {("Buy", "CASH")} if spec.direction == "long" else {("Sell", "SHORT_SELLING")}
    if (spec.action, spec.condition) not in allowed:
        reasons.append("INVALID_ENTRY_DIRECTION")
    if spec.lot == "Common" and spec.quantity % 1000:
        reasons.append("QUANTITY_UNIT_MISMATCH")
    if spec.condition != "CASH" and spec.lot != "Common":
        reasons.append("CREDIT_COMMON_REQUIRED")
    entry = spec.proposed_limit if spec.price_basis == "explicit" else spec.reference_entry
    sign = 1 if spec.direction == "long" else -1
    if entry is not None and ((spec.stop_loss is not None and sign * (entry - spec.stop_loss) <= 0)
                             or (spec.take_profit is not None and sign * (spec.take_profit - entry) <= 0)):
        reasons.append("INVALID_LEVEL_DIRECTION")
    if spec.conditions is None:
        reasons.append("INCOMPLETE_CONDITION")
    return spec, reasons


class Truth(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class ManualStageOrder(Model):
    client_intent_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_:.-]+$")
    symbol: str = Field(pattern=r"^[0-9A-Za-z]{2,12}$")
    action: Literal["Buy", "Sell"]
    condition: Literal["CASH", "CASH_SELLING", "MARGIN", "SHORT_SELLING"]
    lot: Literal["Odd", "Common"]
    quantity_shares: int = Field(gt=0, le=1_000_000_000, strict=True)
    price: Decimal = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def order_shape(self):
        if self.lot == "Common" and self.quantity_shares % 1000:
            raise ValueError("QUANTITY_UNIT_MISMATCH")
        if self.condition != "CASH" and self.lot != "Common":
            raise ValueError("UNSUPPORTED_CREDIT_LOT")
        if self.condition == "MARGIN" and self.action != "Buy":
            raise ValueError("UNQUALIFIED_MARGIN_SIDE")
        if self.condition in {"CASH_SELLING", "SHORT_SELLING"} and self.action != "Sell":
            raise ValueError("UNQUALIFIED_SHORT_SIDE")
        return self

    def canonical(self):
        # Decimal formatting differences do not create a second intent.
        price = format(self.price, "f")
        return {**self.model_dump(mode="json"), "price": price.rstrip("0").rstrip(".") if "." in price else price}


class ManualStageMetadata(Model):
    client_intent_id: str
    original_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    space_id: Literal["USER_SPACE"] = "USER_SPACE"
    source: Literal["MANUAL"] = "MANUAL"
    state: Literal["STAGED", "SUBMITTING", "SUBMITTED", "SUBMISSION_PENDING", "SUBMISSION_CANCELLED",
                   "SUBMISSION_UNKNOWN", "SUBMISSION_REJECTED"] = "STAGED"
    submission: dict | None = None


class CandidateBody(Model):
    raw: dict
    owner_id: str = Field(min_length=1, max_length=128)
    state: Literal["ACTIVE", "PAUSED", "CANCELLED"]
    event: Literal["CREATED", "REVISE", "PAUSE", "RESUME", "CANCEL", "MANUAL_SUBMIT_CLAIMED", "MANUAL_SUBMIT_PROGRESS", "MANUAL_SUBMIT_RESULT"]
    kind: Literal["conditional", "manual_stage"] = "conditional"
    manual_stage: ManualStageMetadata | None = None

    @model_validator(mode="after")
    def stage_owner(self):
        if self.kind == "manual_stage":
            order = ManualStageOrder.model_validate(self.raw)
            if (self.owner_id != "MCP" or self.manual_stage is None or
                    order.client_intent_id != self.manual_stage.client_intent_id):
                raise ValueError("INVALID_MANUAL_STAGE_OWNER")
        elif self.manual_stage is not None or self.event.startswith("MANUAL_"):
            raise ValueError("INVALID_MANUAL_STAGE_KIND")
        return self


class NativeSelection(Model):
    candidate_id: str
    candidate_revision: int = Field(gt=0)
    pending_id: str
    pending_revision: int = Field(gt=0)
    pending_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class NativeReviewLink(Model):
    review_id: str
    review_revision: int = Field(gt=0)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: NativeSelection


class Evidence(Model):
    value: Decimal | None = Field(default=None, allow_inf_nan=False)
    source: str
    source_at: datetime
    received_at: datetime
    available_at: datetime
    valid_until: datetime
    revision: str
    quality: Literal["usable", "unknown", "stale", "partial"]
    completed: bool = False
    timeframe: Literal["snapshot", "1d"]
    parameters: tuple[int, ...] = ()
    algorithm_version: str | None = None

    @field_validator("source_at", "received_at", "available_at", "valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AWARE_TIMESTAMP_REQUIRED")
        return value


class PendingBody(Model):
    candidate_id: str
    candidate_revision: int = Field(gt=0)
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    trigger_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: dict[str, Evidence]
    state: Literal["PENDING_APPROVAL", "PREPARING", "NATIVE_PREVIEW", "CANCELLED", "STALE",
                   "SELECTING", "SELECTED", "SELECTION_UNKNOWN"]
    price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    quantity: int = Field(gt=0, strict=True)
    price_evidence: dict
    qualification: dict
    native: NativeReviewLink | None = None
    invalidated_native: list[NativeReviewLink] = Field(default_factory=list)
    native_invalidation: Literal["NOT_NEEDED", "PENDING_EXECUTOR", "REJECTED"] = "NOT_NEEDED"
    preparation: dict | None = None
    protection_effects: bool | None = None
    execution_receipt: dict | None = None
    executor_status: Literal["NOT_READY", "OFFLINE_OR_UNKNOWN"] | None = None


def metrics(condition: Condition | None) -> tuple[Metric, ...]:
    if condition is None:
        return ()
    if isinstance(condition, Comparison):
        return (condition.metric,)
    return tuple(m for clause in condition.clauses for m in metrics(clause))


def evaluate(condition: Condition, evidence: dict[str, Evidence], now: datetime) -> Truth:
    if isinstance(condition, Group):
        values = [evaluate(c, evidence, now) for c in condition.clauses]
        decisive, unanimous = ((Truth.FALSE, Truth.TRUE) if condition.kind == "AND"
                               else (Truth.TRUE, Truth.FALSE))
        return decisive if decisive in values else unanimous if all(v == unanimous for v in values) else Truth.UNKNOWN
    metric = condition.metric
    item = evidence.get(metric.key)
    if (item is None or item.value is None or item.quality != "usable" or not item.source or not item.revision
        or item.source_at > now or item.received_at > now or not item.available_at <= now <= item.valid_until
        or item.timeframe != metric.timeframe or item.parameters != metric.parameters
        or (metric.kind != "price" and (not metric.completed or not item.completed or not item.algorithm_version))):
        return Truth.UNKNOWN
    compare = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}
    return Truth.TRUE if compare[condition.operator](item.value, condition.value) else Truth.FALSE


def lifecycle(raw: dict, state: str, now: datetime) -> str:
    if state in {"PAUSED", "CANCELLED"}:
        return state
    spec, reasons = validate_raw(raw)
    if reasons:
        return "DRAFT"
    today = now.astimezone(TAIPEI).date().isoformat()
    if today < spec.valid_from_date:
        return "SCHEDULED"
    return "EXPIRED" if today > spec.valid_until_date else "ACTIVE"
