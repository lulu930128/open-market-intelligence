"""Internal, bounded acquisition receipt schema; not a market readiness owner."""
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator
from app.market_data.contracts import CanonicalModel


class AcquisitionBatchEvidence(CanonicalModel):
    batch_index: int = Field(ge=1, le=20)
    phase: Literal["scan", "rescue"]
    requested: int = Field(ge=0, le=100)
    returned: int = Field(ge=0)
    eligible_stock_rows: int = Field(ge=0)
    actual_z: int = Field(ge=0)
    missing_z: int = Field(ge=0)
    verified_no_trade: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    attempted: bool
    error: str | None = Field(default=None, max_length=64)
    timeout: bool = False
    receipt_at: datetime | None = None
    event_min: datetime | None = None
    event_max: datetime | None = None
    message_digest_sha256: str | None = Field(default=None, max_length=64)
    digest_basis: Literal["parsed_original_messages_before_classification"] | None = None
    missing_examples: tuple[dict[str, str], ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def bounded_examples(self):
        allowed = {"c", "d", "t", "z", "v", "tv", "ts", "pz", "ps", "o", "h", "l", "y"}
        if any(set(example) - allowed or any(len(value) > 96 for value in example.values())
               for example in self.missing_examples):
            raise ValueError("original-message examples must use bounded allowlisted fields")
        return self


class AcquisitionRescueEvidence(CanonicalModel):
    candidate_count: int = Field(ge=0)
    attempted_count: int = Field(ge=0, le=32)
    succeeded_count: int = Field(ge=0, le=32)
    failed_count: int = Field(ge=0, le=32)
    skipped_count: int = Field(ge=0)
    skip_reasons: dict[str, int] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def reconciled_counts(self):
        if (self.attempted_count + self.skipped_count != self.candidate_count
            or self.succeeded_count + self.failed_count != self.attempted_count
            or sum(self.skip_reasons.values()) != self.skipped_count):
            raise ValueError("rescue attempts and skip reasons must reconcile")
        return self


class BreadthAcquisitionEvidence(CanonicalModel):
    version: Literal["tw.mis.breadth.acquisition.v1"] = "tw.mis.breadth.acquisition.v1"
    acquisition_id: str = Field(max_length=64)
    market: Literal["TWSE", "TPEX"]
    provider: Literal["twse_mis"] = "twse_mis"
    source: str = Field(max_length=64)
    trade_date: date | None
    session: str = Field(max_length=32)
    started_at: datetime
    finished_at: datetime
    universe_count: int = Field(ge=0, le=2000)
    requested_symbol_count: int = Field(ge=0, le=2000)
    returned_row_count: int = Field(ge=0)
    eligible_stock_row_count: int = Field(ge=0)
    actual_trade_price_count: int = Field(ge=0)
    # Acquisition ratios are receipt facts; usable/ranking/research remain discovery-owned.
    count_ratios: dict[str, float] = Field(default_factory=dict, max_length=8)
    missing_z_count: int = Field(ge=0)
    verified_no_trade_count: int = Field(ge=0)
    batch_count: int = Field(ge=0, le=21)
    batches: tuple[AcquisitionBatchEvidence, ...] = Field(default=(), max_length=21)
    batch_duration_ms: dict[str, float | int | None]
    event_to_receipt_seconds: dict[str, float | int | None]
    budget_total_seconds: float = Field(ge=0)
    budget_elapsed_seconds: float = Field(ge=0)
    budget_remaining_seconds: float = Field(ge=0)
    scan_budget_seconds: float = Field(ge=0)
    rescue_max_budget_seconds: float = Field(ge=0, le=4)
    total_hard_deadline_seconds: float = Field(ge=0)
    deadline_exceeded: bool
    rescue: AcquisitionRescueEvidence
    error: str | None = Field(default=None, max_length=64)
    # Assigned by the persistence owner; not invented by the provider.
    raw_result_id: int | None = None
    raw_receipt_id: str | None = None
    content_hash: str | None = None
