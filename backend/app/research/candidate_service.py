"""Sole Candidate/Pending transaction owner. Broker facts stay in Native Runtime."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
import json
from sqlalchemy.orm import Session

from . import candidate_store as store
from .candidate_control import ControlRejected, ControlUnavailable, command, request_control
from .candidate_evidence import read_market_evidence, order_qualification
from .conditional_candidate import ManualStageOrder, TAIPEI, Truth, digest, evaluate, lifecycle, validate_raw


TERMINAL_PENDING = {"CANCELLED", "STALE", "SELECTING", "SELECTED", "SELECTION_UNKNOWN"}


@contextmanager
def write(db):
    with db.begin():
        if db.get_bind().dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield


def require(value, code):
    if not value:
        raise ValueError(code)


class CandidateService:
    def __init__(self, db, *, control=request_control, evidence=read_market_evidence, clock=None):
        self.db, self.control, self.evidence = db, control, evidence
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _view(self, record):
        if record.get("kind") == "manual_stage":
            stage = record["manual_stage"]
            return {**record, "space_id": "USER_SPACE", "source": "MANUAL",
                    "lifecycle": stage["state"] if record["state"] == "ACTIVE" else record["state"]}
        spec, reasons = validate_raw(record["raw"])
        return {**record, "lifecycle": lifecycle(record["raw"], record["state"], self.clock()),
                "validation_reasons": reasons, "spec": spec.model_dump(mode="json") if spec else None}

    def create(self, raw, *, owner_id, research_revision=None, manual_stage=False):
        require(type(raw) is dict and bool(owner_id), "INVALID_CANDIDATE")
        digest(raw)  # JSON/finite values only; semantic failures remain preserved.
        identity = str(uuid4())
        created = True
        if manual_stage:
            require(owner_id == "MCP" and research_revision is None, "INVALID_MANUAL_STAGE_OWNER")
            raw = ManualStageOrder.model_validate(raw).canonical()
            identity = digest(["manual_stage", "MCP", raw["client_intent_id"]])
        with write(self.db):
            record = None
            if manual_stage:
                try:
                    record = store.get(self.db, store.candidates, identity)
                    require(record.get("kind") == "manual_stage" and
                            record["manual_stage"]["original_digest"] == digest(raw), "STAGE_IDEMPOTENCY_CONFLICT")
                except LookupError:
                    pass
            if research_revision is not None:
                from . import trade_journal
                from .trade_proposal import content_hash
                versions = trade_journal.list_versions(self.db, creation_id=research_revision.creation_id, as_of=self.clock())
                require(versions and versions[-1] == research_revision, "STALE_RESEARCH_REVISION")
                identity = digest({"research_revision": research_revision.revision_id,
                                   "proposal_digest": content_hash(research_revision.model_dump(mode="json"))})
                try:
                    record = store.get(self.db, store.candidates, identity)
                    created = False
                except LookupError:
                    pass
            if record is None:
                extra = {"kind": "manual_stage", "manual_stage": {"client_intent_id": raw["client_intent_id"],
                    "original_digest": digest(raw), "space_id": "USER_SPACE", "source": "MANUAL",
                    "state": "STAGED", "submission": None}} if manual_stage else {}
                record = store.append(self.db, store.candidates, identity, identity, 1,
                    {"raw": raw, "owner_id": owner_id, "state": "ACTIVE", "event": "CREATED", **extra}, self.clock())
        view = self._view(record)
        return {**view, "created": created} if research_revision is not None else view

    def get(self, identity):
        return self._view(store.get(self.db, store.candidates, identity))

    def list(self, *, after="", limit=100):
        return [self._view(r) for r in store.latest(self.db, store.candidates, after=after, limit=limit, kind="conditional")]

    def staged(self, identity=None, *, after="", limit=100):
        if identity is None:
            return [self._view(r) for r in store.latest(self.db, store.candidates,
                after=after, limit=limit, kind="manual_stage") if r["owner_id"] == "MCP"]
        record = store.get(self.db, store.candidates, identity)
        require(record.get("kind") == "manual_stage" and record["owner_id"] == "MCP", "MANUAL_STAGE_REQUIRED")
        return self._view(record)

    def _stage_progress(self, identity, pin, *, state, phase, **changes):
        with write(self.db):
            current = store.get(self.db, store.candidates, identity)
            stage = current["manual_stage"]
            require(stage["submission"]["pin"] == pin and stage["state"] == "SUBMITTING", "STAGE_SUBMISSION_LOCKED")
            stage = {**stage, "state": state,
                     "submission": {**stage["submission"], "phase": phase, **changes}}
            return self._view(store.append(self.db, store.candidates, identity, identity, current["revision"] + 1,
                {**store.body(current), "manual_stage": stage,
                 "event": "MANUAL_SUBMIT_PROGRESS" if state == "SUBMITTING" else "MANUAL_SUBMIT_RESULT"}, self.clock()))

    def send_staged(self, identity, *, expected_revision, expected_digest):
        """Explicit modal confirmation only. A durable latch admits one Native chain.

        No DB transaction spans IPC. Missing executor leaves STAGED unchanged;
        once latched, lost responses/crash retain the exact identity and never replay.
        """
        pin = {"revision": expected_revision, "digest": expected_digest}
        with self.db.begin():
            record = self.staged(identity)
            stage = record["manual_stage"]
            if stage["state"] != "STAGED":
                require(stage["submission"]["pin"] == pin, "STALE_STAGE_SELECTION")
                return record  # Includes in-flight/UNKNOWN. Never another control call.
            require(record["revision"] == expected_revision and record["digest"] == expected_digest, "STALE_STAGE_SELECTION")
            require(record["state"] == "ACTIVE", "STAGE_NOT_SENDABLE")
        status = self.control({"operation": "status"})
        ready = (isinstance(status, dict) and status.get("broker_session") == "CONNECTED" and
            status.get("session_date_matches") is not False and
            status.get("trade_date") == self.clock().astimezone(TAIPEI).date().isoformat())
        if not ready:
            raise ControlUnavailable("EXECUTOR_NOT_READY")
        order = record["raw"]
        token = digest(["manual_stage", identity, pin])
        draft = {"owner_id": "MCP", "source": "MANUAL", "command": {
            "account_id": "SELECTED", "trade_date": status["trade_date"], "request_id": token, "intent_id": token,
            "symbol": order["symbol"], "action": order["action"], "condition": order["condition"], "lot": order["lot"],
            "quantity": order["quantity_shares"], "price": order["price"], "space_id": "USER_SPACE",
            "shares_per_unit": 1000 if order["lot"] == "Common" else 1}}
        with write(self.db):
            current = store.get(self.db, store.candidates, identity)
            require(current["revision"] == expected_revision and current["digest"] == expected_digest and
                    current["state"] == "ACTIVE", "STALE_STAGE_SELECTION")
            submission = {"pin": pin, "native_intent_id": token, "draft": draft, "phase": "DRAFT"}
            store.append(self.db, store.candidates, identity, identity, current["revision"] + 1,
                {**store.body(current), "event": "MANUAL_SUBMIT_CLAIMED",
                 "manual_stage": {**stage, "state": "SUBMITTING", "submission": submission}}, self.clock())
        phase = "DRAFT"
        try:
            review = command(self.control, ["draft", "--draft-json", json.dumps(draft, allow_nan=False)])
            # Native adds command defaults; compare every pinned field before confirm.
            def matches(value):
                native_draft = value.get("draft", {}) if isinstance(value, dict) else {}
                native_command = native_draft.get("command", {})
                return (native_draft.get("owner_id") == "MCP" and native_draft.get("source") == "MANUAL" and
                        all(native_command.get(k) == v for k, v in draft["command"].items()))
            require(matches(review) and review.get("state") == "DRAFT" and
                    type(review.get("review_revision")) is int and review["review_revision"] == 1 and
                    isinstance(review.get("review_id"), str), "NATIVE_STAGE_RESPONSE_MISMATCH")
            link = {"review_id": review["review_id"], "review_revision": review["review_revision"]}
            phase = "PREVIEW"
            self._stage_progress(identity, pin, state="SUBMITTING", phase=phase, native=link)
            preview = command(self.control, ["preview", link["review_id"], "--expected-revision", str(link["review_revision"])])
            snapshot = preview.get("snapshot", {})
            native_digest = snapshot.get("digest") if isinstance(snapshot, dict) else None
            require(matches(preview) and preview.get("state") == "PREVIEW" and
                    preview.get("review_id") == link["review_id"] and preview.get("review_revision") == link["review_revision"] and
                    isinstance(native_digest, str) and len(native_digest) == 64 and
                    all(c in "0123456789abcdef" for c in native_digest), "NATIVE_STAGE_RESPONSE_MISMATCH")
            link = {**link, "digest": native_digest}
            phase = "CONFIRM"
            self._stage_progress(identity, pin, state="SUBMITTING", phase=phase, native=link)
            receipt = command(self.control, ["confirm", link["review_id"], "--expected-revision",
                str(link["review_revision"]), "--expected-digest", native_digest])
            require(matches(receipt) and receipt.get("review_id") == link["review_id"] and
                    receipt.get("state") == "EXECUTION" and isinstance(receipt.get("execution"), dict),
                    "NATIVE_STAGE_RESPONSE_MISMATCH")
        except ControlRejected:
            self._stage_progress(identity, pin, state="SUBMISSION_REJECTED", phase=phase, error="EXECUTOR_COMMAND_REJECTED")
            raise ControlRejected("EXECUTOR_COMMAND_REJECTED") from None
        except Exception:
            self._stage_progress(identity, pin, state="SUBMISSION_UNKNOWN", phase=phase, error="EXECUTOR_RESPONSE_UNKNOWN")
            raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN") from None
        # Submission projection only; Native retains the sole order-state reducer.
        state = {"ACCEPTED": "SUBMITTED", "PARTIALLY_FILLED": "SUBMITTED", "FILLED": "SUBMITTED",
                 "PENDING": "SUBMISSION_PENDING", "REJECTED": "SUBMISSION_REJECTED",
                 "CANCELLED": "SUBMISSION_CANCELLED"}.get(receipt["execution"].get("state"), "SUBMISSION_UNKNOWN")
        return self._stage_progress(identity, pin, state=state, phase="RESULT", receipt=receipt)

    def history(self, identity):
        return store.history(self.db, store.candidates, identity)

    def _pending_append(self, previous, **changes):
        return store.append(self.db, store.pending, previous["id"], previous["candidate_id"],
                            previous["revision"] + 1, {**store.body(previous), **changes}, self.clock())

    def _invalidate(self, pending, state):
        link = pending.get("native")
        invalidated = list(pending.get("invalidated_native", []))
        if link and link not in invalidated:
            invalidated.append(link)
        return self._pending_append(pending, state=state, native=None, invalidated_native=invalidated,
                                    native_invalidation="PENDING_EXECUTOR" if invalidated else "NOT_NEEDED")

    def drain_invalidations(self, candidate_id):
        # Read/commit -> IPC -> acknowledgement. Never retain a DB lock over IPC.
        with self.db.begin():
            pending_records = store.latest(self.db, store.pending, candidate_id=candidate_id)
        for pending in pending_records:
            for link in pending.get("invalidated_native", []):
                try:
                    status = command(self.control, ["status", link["review_id"]])
                    if status["state"] != "REJECTED":
                        command(self.control, ["reject", link["review_id"], "--expected-revision",
                            str(link["review_revision"]), "--reason", "CANDIDATE_REVISED"])
                except ControlUnavailable:
                    continue
                with write(self.db):
                    current = store.get(self.db, store.pending, pending["id"])
                    remaining = [v for v in current.get("invalidated_native", []) if v != link]
                    self._pending_append(current, invalidated_native=remaining,
                        native_invalidation="PENDING_EXECUTOR" if remaining else "REJECTED")

    def change(self, identity, *, expected_revision, operation, raw=None):
        require(operation in {"revise", "pause", "resume", "cancel"}, "INVALID_CANDIDATE_OPERATION")
        with write(self.db):
            old = store.get(self.db, store.candidates, identity)
            require(old["revision"] == expected_revision, "STALE_CANDIDATE_REVISION")
            require(old["state"] != "CANCELLED", "CANDIDATE_CANCELLED")
            if old.get("kind") == "manual_stage":
                require(old["manual_stage"]["state"] == "STAGED", "STAGE_SUBMISSION_LOCKED")
                value = store.body(old)
                if operation == "revise":
                    order = ManualStageOrder.model_validate(raw).canonical()
                    require(order["client_intent_id"] == old["manual_stage"]["client_intent_id"], "STAGE_IDENTITY_IMMUTABLE")
                    value["raw"] = order
                else:
                    value["state"] = {"pause": "PAUSED", "resume": "ACTIVE", "cancel": "CANCELLED"}[operation]
                value["event"] = operation.upper()
                return self._view(store.append(self.db, store.candidates, identity, identity,
                    expected_revision + 1, value, self.clock()))
            pendings = store.latest(self.db, store.pending, candidate_id=identity)
            require(not any(p["state"] == "SELECTING" for p in pendings), "ENTRY_SELECTION_IN_FLIGHT")
            for pending in pendings:
                if pending["state"] not in TERMINAL_PENDING:
                    self._invalidate(pending, "CANCELLED" if operation == "cancel" else "STALE")
            value = store.body(old)
            if operation == "revise":
                require(type(raw) is dict, "INVALID_CANDIDATE")
                digest(raw)
                # Revisions may edit intent, never silently move its provenance.
                previous, _ = validate_raw(old["raw"])
                if previous is not None:
                    require((raw.get("space_id", "AGENT_SPACE"), raw.get("source", "AGENT_PROPOSAL")) ==
                            (previous.space_id, previous.source), "CANDIDATE_PROVENANCE_IMMUTABLE")
                notes = old["raw"].get("reference_notes")
                link = notes.get("research_proposal") if isinstance(notes, dict) else None
                if link is not None:
                    revised_notes = raw.get("reference_notes")
                    require(isinstance(revised_notes, dict) and revised_notes.get("research_proposal") == link,
                            "RESEARCH_PROVENANCE_IMMUTABLE")
                value["raw"] = raw
            else:
                value["state"] = {"pause": "PAUSED", "resume": "ACTIVE", "cancel": "CANCELLED"}[operation]
            value["event"] = operation.upper()
            result = store.append(self.db, store.candidates, identity, identity, expected_revision + 1, value, self.clock())
        self.drain_invalidations(identity)
        return self._view(result)

    def pending(self, identity):
        return store.latest(self.db, store.pending, candidate_id=identity)

    def observe(self, identity):
        """No tick journal. A candidate revision has at most one pending per day."""
        with self.db.begin():
            candidate = store.get(self.db, store.candidates, identity)
            existing = store.latest(self.db, store.pending, candidate_id=identity)
        if candidate.get("kind") == "manual_stage":
            return {"truth": "UNKNOWN", "reason": "MANUAL_STAGE_NOT_MONITORED"}
        now = self.clock()
        if lifecycle(candidate["raw"], candidate["state"], now) != "ACTIVE":
            return {"truth": "UNKNOWN", "reason": "CANDIDATE_NOT_ACTIVE"}
        if any(p["state"] in {"SELECTING", "SELECTED", "SELECTION_UNKNOWN"} for p in existing):
            return {"truth": "UNKNOWN", "reason": "ENTRY_ALREADY_SELECTED"}
        spec, _ = validate_raw(candidate["raw"])
        market = self._market(spec, now)
        truth = evaluate(spec.conditions, market.values, now)
        if truth != Truth.TRUE:
            return {"truth": truth.value, "reason": "NO_MATCH"}
        day = now.astimezone(TAIPEI).date().isoformat()
        identity_key = digest([identity, candidate["revision"], day])
        qualification = self._qualification(spec, market.proposed_limit, market, now)
        with write(self.db):
            current = store.get(self.db, store.candidates, identity)
            if (current["revision"] != candidate["revision"] or
                lifecycle(current["raw"], current["state"], self.clock()) != "ACTIVE" or
                self.clock().astimezone(TAIPEI).date().isoformat() != day):
                return {"truth": "UNKNOWN", "reason": "CANDIDATE_CHANGED_DURING_EVALUATION"}
            existing = store.latest(self.db, store.pending, candidate_id=identity)
            if any(p["state"] in {"SELECTING", "SELECTED", "SELECTION_UNKNOWN"} for p in existing):
                return {"truth": "UNKNOWN", "reason": "ENTRY_ALREADY_SELECTED"}
            found = next((p for p in existing if p["id"] == identity_key), None)
            if found:
                if found["state"] == "PENDING_APPROVAL" and found["price"] is None and market.proposed_limit is not None:
                    found = self._pending_append(found, price=market.proposed_limit,
                        price_evidence=market.price_evidence, qualification=qualification)
                return {"truth": "TRUE", "pending": found, "created": False}
            for old in existing:
                if old["state"] not in TERMINAL_PENDING:
                    self._invalidate(old, "STALE")
            evidence = {key: value.model_dump(mode="json") for key, value in market.values.items()}
            result = store.append(self.db, store.pending, identity_key, identity, 1,
                {"candidate_id": identity, "candidate_revision": candidate["revision"],
                 "candidate_digest": candidate["digest"], "trade_date": day,
                 "trigger_id": digest(evidence), "evidence": evidence, "state": "PENDING_APPROVAL",
                 "price": market.proposed_limit, "quantity": spec.quantity,
                 "price_evidence": market.price_evidence,
                 "qualification": qualification,
                 "native": None}, now)
        return {"truth": "TRUE", "pending": result, "created": True}

    def revise_pending(self, identity, *, expected_revision, price, quantity):
        with write(self.db):
            old = store.get(self.db, store.pending, identity)
            require(old["revision"] == expected_revision, "STALE_PENDING_REVISION")
            require(old["state"] not in TERMINAL_PENDING, "PENDING_NOT_EDITABLE")
            candidate = store.get(self.db, store.candidates, old["candidate_id"])
            require(candidate["revision"] == old["candidate_revision"], "STALE_CANDIDATE_REVISION")
            self._invalidate(old, "STALE")
            current = store.get(self.db, store.pending, identity)
            result = self._pending_append(current, price=price, quantity=quantity, state="PENDING_APPROVAL",
                native=None, preparation=None, price_evidence={"basis": "operator"}, qualification={"send_ready": False, "reasons": ["RECHECK_REQUIRED"]})
        self.drain_invalidations(result["candidate_id"])
        with self.db.begin():
            return store.get(self.db, store.pending, identity)

    def cancel_pending(self, identity, *, expected_revision):
        with write(self.db):
            old = store.get(self.db, store.pending, identity)
            require(old["revision"] == expected_revision, "STALE_PENDING_REVISION")
            require(old["state"] not in TERMINAL_PENDING, "PENDING_NOT_EDITABLE")
            result = self._invalidate(old, "CANCELLED")
        self.drain_invalidations(result["candidate_id"])
        with self.db.begin():
            return store.get(self.db, store.pending, identity)

    def _current(self, pending, now):
        candidate = store.get(self.db, store.candidates, pending["candidate_id"])
        require(candidate["revision"] == pending["candidate_revision"], "STALE_CANDIDATE_REVISION")
        require(lifecycle(candidate["raw"], candidate["state"], now) == "ACTIVE", "CANDIDATE_NOT_ACTIVE")
        require(pending["trade_date"] == now.astimezone(TAIPEI).date().isoformat(), "STALE_PENDING_DATE")
        spec, reasons = validate_raw({**candidate["raw"], "quantity": pending["quantity"]})
        require(not reasons, "INVALID_CANDIDATE_SEMANTICS")
        return candidate, spec

    def _market(self, spec, now):
        # Canonical reads use their own read Session, never the Candidate writer.
        with Session(self.db.get_bind()) as reader:
            return self.evidence(reader, spec, now)

    def _evaluated_pending(self, identity):
        now = self.clock()
        with self.db.begin():
            pending = store.get(self.db, store.pending, identity)
            candidate, spec = self._current(pending, now)
        market = self._market(spec, now)
        require(evaluate(spec.conditions, market.values, now) == Truth.TRUE, "CONDITION_NOT_TRUE")
        qualification = self._qualification(spec, pending["price"], market, now)
        return pending, candidate, spec, qualification

    @staticmethod
    def _qualification(spec, price, market, now):
        value = order_qualification(spec, price, market, now)
        if (spec.space_id, spec.source) == ("USER_SPACE", "MANUAL"):
            # Research borrow evidence is not broker acceptance authority. Keep
            # the UNKNOWN fact visible; a manual entry is decided by the broker.
            hints = [r for r in value["reasons"] if r == "BORROW_UNKNOWN" and spec.condition == "SHORT_SELLING"]
            reasons = [r for r in value["reasons"] if r != "BORROW_UNKNOWN"]
            return {**value, "reasons": reasons, "send_ready": not reasons,
                    "borrow_status": value["borrow_status"] if spec.condition == "SHORT_SELLING" else "NOT_APPLICABLE",
                    "research_hints": hints, "broker_acceptance": "UNKNOWN"}
        return value

    def _recheck(self, pending):
        current = store.get(self.db, store.pending, pending["id"])
        require(current["revision"] == pending["revision"], "STALE_PENDING_REVISION")
        self._current(current, self.clock())
        return current

    def prepare(self, identity):
        pending, candidate, spec, qualification = self._evaluated_pending(identity)
        with write(self.db):
            pending = self._recheck(pending)
            require(pending["state"] not in TERMINAL_PENDING, "PENDING_NOT_PREPARABLE")
            if not qualification["send_ready"]:
                return {**pending, "qualification": qualification}
            if pending.get("native"):
                return pending
            preparation = pending.get("preparation")
            if preparation:
                draft, binding = preparation["draft"], preparation["binding"]
            else:
                draft, binding = self._preparation(candidate, spec, pending)
                pending = self._pending_append(pending, state="PREPARING", qualification=qualification,
                    preparation={"draft": draft, "binding": binding})
        # Preparation identity is durable before calling the existing pipe.
        try:
            status = self.control({"operation": "status"})
            if status.get("broker_session") != "CONNECTED" or status.get("trade_date") != pending["trade_date"]:
                return self._record_executor_status(pending, "NOT_READY")
            result = command(self.control, ["candidate-prepare", "--draft-json", json.dumps(draft),
                "--binding-json", json.dumps(binding)])
        except ControlUnavailable:
            return self._record_executor_status(pending, "OFFLINE_OR_UNKNOWN")
        native = {"review_id": result["review_id"], "review_revision": result["review_revision"],
                  "digest": result["snapshot"]["digest"], "selection": binding["selection"]}
        with write(self.db):
            current = store.get(self.db, store.pending, identity)
            candidate_now = store.get(self.db, store.candidates, pending["candidate_id"])
            if current.get("native") == native and candidate_now["revision"] == pending["candidate_revision"]:
                return current
            current_matches = (current["state"] == "PREPARING" and current.get("preparation") == pending.get("preparation") and
                candidate_now["revision"] == pending["candidate_revision"] and
                lifecycle(candidate_now["raw"], candidate_now["state"], self.clock()) == "ACTIVE")
            if current_matches:
                output = self._pending_append(current, native=native, state="NATIVE_PREVIEW",
                    qualification=qualification, protection_effects=status.get("strategy_effects", False), executor_status=None)
            else:
                invalidated = [*current.get("invalidated_native", []), native]
                output = self._pending_append(current, invalidated_native=invalidated, native_invalidation="PENDING_EXECUTOR")
        if not current_matches:
            self.drain_invalidations(pending["candidate_id"])
        return output

    def _record_executor_status(self, pending, status):
        with write(self.db):
            current = store.get(self.db, store.pending, pending["id"])
            if current["state"] == "PREPARING" and current.get("executor_status") != status:
                return self._pending_append(current, executor_status=status)
            return current

    @staticmethod
    def _preparation(candidate, spec, pending):
        selection = {"candidate_id": candidate["id"], "candidate_revision": candidate["revision"],
            "pending_id": pending["id"], "pending_revision": pending["revision"], "pending_digest": pending["digest"]}
        token = digest(selection)
        protected = spec.stop_loss is not None or spec.take_profit is not None
        draft = {"owner_id": candidate["owner_id"], "source": spec.source, "command": {
            "account_id": "SELECTED", "trade_date": pending["trade_date"], "request_id": token, "intent_id": token,
            "symbol": spec.symbol, "action": spec.action, "condition": spec.condition,
            "lot": spec.lot, "shares_per_unit": 1000 if spec.lot == "Common" else 1,
            "quantity": pending["quantity"], "price": pending["price"], "space_id": spec.space_id,
            "strategy_id": token if protected else None, "revision": 1 if protected else None}}
        protection = ({"stop_loss": str(spec.stop_loss) if spec.stop_loss is not None else None,
            "take_profit": str(spec.take_profit) if spec.take_profit is not None else None,
            "exit_limit_price": str(spec.exit_limit_price)} if protected else None)
        binding = {"selection": selection, "protection": protection}
        return draft, binding

    def approve(self, identity, *, expected_revision, expected_digest):
        """One explicit selection; no AI gate and no automatic replay after lost IPC."""
        pending, _, _, qualification = self._evaluated_pending(identity)
        with write(self.db):
            pending = self._recheck(pending)
            require(pending["revision"] == expected_revision and pending["digest"] == expected_digest, "STALE_PENDING_SELECTION")
            require(pending["state"] == "NATIVE_PREVIEW", "NATIVE_PREVIEW_REQUIRED")
            require(qualification["send_ready"], "ORDER_NOT_ACCEPTABLE")
            selected = self._pending_append(pending, state="SELECTING")
        link = pending["native"]
        try:
            receipt = command(self.control, ["confirm", link["review_id"], "--expected-revision", str(link["review_revision"]),
                "--expected-digest", link["digest"], "--candidate-selection-json", json.dumps(link["selection"])])
            state = "SELECTED"
        except ControlUnavailable:
            receipt, state = {"retry_policy": "CHECK_NATIVE_STATUS_DO_NOT_RESEND"}, "SELECTION_UNKNOWN"
        with write(self.db):
            return self._pending_append(selected, state=state, execution_receipt=receipt)
