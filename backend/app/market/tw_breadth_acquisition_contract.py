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
    # Caller-owned: remaining scan budget at batch start, before admission.
    # Nullable so old receipts remain valid; never infer a missing measurement.
    remaining_budget_at_start_seconds: float | None = Field(default=None, ge=0)
    # Caller-side elapsed bounded_fetch duration (not provider socket wait).
    # Null for a batch that never entered its IO worker, including in-flight skips.
    caller_wait_seconds: float | None = Field(default=None, ge=0)
    fetch_decode_seconds: float = Field(default=0, ge=0)
    transport_seconds: float | None = Field(default=None, ge=0)
    decode_seconds: float | None = Field(default=None, ge=0)
    classification_seconds: float = Field(default=0, ge=0)
    digest_seconds: float = Field(default=0, ge=0)
    fetch_completed_in_budget: bool = False
    attempted: bool
    error: str | None = Field(default=None, max_length=64)
    timeout: bool = False
    # Null for old receipts: absent detail must not become inferred socket truth.
    timeout_origin: Literal["provider", "acquisition_deadline"] | None = None
    timeout_stage: Literal["connect", "read", "request"] | None = None
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
    scan_start_code: str | None = Field(default=None, max_length=4)
    scan_next_code: str | None = Field(default=None, max_length=4)
    batches: tuple[AcquisitionBatchEvidence, ...] = Field(default=(), max_length=21)
    batch_duration_ms: dict[str, float | int | None]
    event_to_receipt_seconds: dict[str, float | int | None]
    budget_total_seconds: float = Field(ge=0)
    budget_elapsed_seconds: float = Field(ge=0)
    budget_remaining_seconds: float = Field(ge=0)
    scan_budget_seconds: float = Field(ge=0)
    rescue_max_budget_seconds: float = Field(ge=0, le=4)
    # Python finalization is bounded by row counts, not forcibly preemptible.
    total_hard_deadline_seconds: float | None = Field(default=None, ge=0)
    total_elapsed_seconds: float = Field(default=0, ge=0)
    finalization_allowance_seconds: float = Field(default=0, ge=0)
    total_ceiling_seconds: float = Field(default=0, ge=0)
    scan_deadline_exceeded: bool = False
    timing_policy: str = "legacy"
    phase_seconds: dict[str, float] = Field(default_factory=dict)
    deadline_exceeded: bool
    rescue: AcquisitionRescueEvidence
    error: str | None = Field(default=None, max_length=64)
    # Assigned by the persistence owner; not invented by the provider.
    raw_result_id: int | None = None
    raw_receipt_id: str | None = None
    content_hash: str | None = None
