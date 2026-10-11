"""Single-owner in-memory M1 harness. Deliberately unsuitable for live trading."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import hmac

from .contracts import (
    AuditEvent, Challenge, Confirmation, Draft, DryRunResult, Evidence, ExecutionRejected,
    OrderState, Preview, SimulationEvent, State,
)
from .state_machine import transition
from .validation import assess, digest_of, identifier, instant, require, validate_draft, validate_fill


@dataclass(frozen=True)
class _Record:
    preview: Preview
    order: OrderState | None = None
    confirmation: Confirmation | None = None


class OfflineExecution:
    """No clock or IO. Caller serializes calls and supplies synthetic challenge material.

    Records/audit disappear with this object. Recreating it removes idempotency history.
    The fixture key is NOT a broker credential, real 2FA, or a production security boundary.
    """

    def __init__(self, *, fixture_challenge_key: bytes, preview_ttl: timedelta = timedelta(seconds=60)):
        require(type(fixture_challenge_key) is bytes and len(fixture_challenge_key) >= 32,
                "INVALID_FIXTURE_KEY")
        require(type(preview_ttl) is timedelta and timedelta(0) < preview_ttl <= timedelta(seconds=60),
                "INVALID_PREVIEW_TTL")
        self._key = fixture_challenge_key
        self._ttl = preview_ttl
        self._records: dict[str, _Record] = {}
        self._requests: dict[tuple[str, str], str] = {}
        self._audit: tuple[AuditEvent, ...] = ()
        self._last_now: datetime | None = None

    @property
    def audit(self) -> tuple[AuditEvent, ...]:
        return self._audit

    def _time(self, now: datetime) -> None:
        instant(now)
        require(self._last_now is None or now >= self._last_now, "CLOCK_REGRESSION")
        self._last_now = now

    def _trace(self, now: datetime, operation: str, record: _Record | None, reason: str,
               event: SimulationEvent | None = None) -> None:
        self._audit += (AuditEvent(
            len(self._audit) + 1, now, operation,
            record.preview.preview_id if record else None,
            record.preview.challenge.digest if record else None,
            record.order.state if record and record.order else State.PREVIEWED if record else None,
            reason, event,
        ),)

    def _get(self, preview_id: str) -> _Record:
        identifier(preview_id)
        require(preview_id in self._records, "UNKNOWN_PREVIEW")
        return self._records[preview_id]

    def preview(self, draft: Draft, evidence: Evidence, *, now: datetime) -> Preview:
        self._time(now)
        record = None
        try:
            validate_draft(draft)
            key = (draft.account_id, draft.client_request_id)
            if key in self._requests:
                record = self._get(self._requests[key])
                require(record.preview.draft == draft, "IDEMPOTENCY_CONFLICT")
                require(record.preview.evidence == evidence, "EVIDENCE_CONFLICT")
                require(record.order is None, "REQUEST_ALREADY_CONSUMED")
                require(now < record.preview.challenge.expires_at, "PREVIEW_EXPIRED")
                self._trace(now, "PREVIEW", record, "IDEMPOTENT_PREVIEW")
                return record.preview
            assessment = assess(draft, evidence, now)
            assessment = replace(assessment, valid_until=min(assessment.valid_until, now + self._ttl))
            preview_id = "simulation-" + digest_of(key)
            digest = digest_of((preview_id, draft, evidence, assessment, now))
            token = hmac.new(self._key, digest.encode("ascii"), hashlib.sha256).hexdigest()
            challenge = Challenge(token, digest, evidence.permission.principal_id, assessment.valid_until)
            preview = Preview(preview_id, draft, evidence, assessment, now, challenge)
            record = _Record(preview)
            self._records[preview_id] = record
            self._requests[key] = preview_id
            self._trace(now, "PREVIEW", record, "PREVIEW_CREATED")
            return preview
        except ExecutionRejected as exc:
            self._trace(now, "PREVIEW", record, exc.code)
            raise

    def confirm(self, preview: Preview, confirmation: Confirmation, *, now: datetime) -> DryRunResult:
        self._time(now)
        record = None
        try:
            require(type(preview) is Preview and type(confirmation) is Confirmation, "INVALID_CONFIRMATION")
            record = self._get(preview.preview_id)
            require(preview == record.preview, "PREVIEW_TAMPERED")
            challenge = record.preview.challenge
            require(digest_of((preview.preview_id, preview.draft, preview.evidence,
                               preview.assessment, preview.created_at)) == challenge.digest,
                    "PREVIEW_TAMPERED")
            require(confirmation.preview_id == preview.preview_id, "CHALLENGE_MISMATCH")
            require(type(confirmation.token) is str and confirmation.token.isascii()
                    and hmac.compare_digest(confirmation.token, challenge.token), "CHALLENGE_MISMATCH")
            require(confirmation.digest == challenge.digest, "PAYLOAD_DIGEST_MISMATCH")
            require(confirmation.principal_id == challenge.principal_id, "PRINCIPAL_MISMATCH")
            require(confirmation.user_confirmed is True, "EXPLICIT_CONFIRMATION_REQUIRED")
            if record.order is not None:
                # Exact command replay returns the current receipt, never consumes a token again.
                require(record.confirmation == confirmation, "CHALLENGE_CONSUMED")
                self._trace(now, "CONFIRM", record, "IDEMPOTENT_RECEIPT")
                return self._result(record)
            require(now < challenge.expires_at, "PREVIEW_EXPIRED")
            assess(preview.draft, preview.evidence, now)
            order = OrderState(preview.preview_id, preview.draft.quantity, State.SIMULATED_PENDING, now)
            record = replace(record, order=order, confirmation=confirmation)
            self._records[preview.preview_id] = record
            self._trace(now, "CONFIRM", record, "SIMULATION_STARTED")
            return self._result(record)
        except ExecutionRejected as exc:
            self._trace(now, "CONFIRM", record, exc.code)
            raise

    def apply(self, event: SimulationEvent, *, now: datetime) -> DryRunResult:
        self._time(now)
        record = None
        try:
            require(type(event) is SimulationEvent, "INVALID_EVENT")
            record = self._get(event.preview_id)
            instant(event.occurred_at)
            require(event.occurred_at >= record.preview.created_at, "INVALID_EVENT_TIME")
            order = record.order or OrderState(
                record.preview.preview_id, record.preview.draft.quantity,
                State.PREVIEWED, None,
            )
            validate_fill(record.preview.draft, record.preview.evidence, event)
            updated, reason = transition(order, event, now)
            record = replace(record, order=updated)
            self._records[event.preview_id] = record
            self._trace(now, "EVENT:" + event.event_id, record, reason, event)
            return self._result(record)
        except ExecutionRejected as exc:
            self._trace(now, "EVENT_REJECTED", record, exc.code)
            raise

    def result(self, preview_id: str) -> DryRunResult:
        """Pure read: no time advance, expiry repair, audit append or state transition."""
        return self._result(self._get(preview_id))

    @staticmethod
    def _result(record: _Record) -> DryRunResult:
        return DryRunResult(
            record.preview.preview_id, record.preview.draft.client_request_id,
            record.order.state if record.order else State.PREVIEWED,
            record.order.cumulative_filled if record.order else 0,
            1 if record.confirmation else 0,
            record.order.cancel_requested if record.order else False,
        )
