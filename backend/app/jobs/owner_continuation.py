"""Job composition adapter for audited original owners' transaction ledgers."""
import json

from app.db.models import JobRun
from app.jobs.cooperative import current_job_stop, checkpoint_after_transaction
from app.jobs.resumption import OWNER_TASKS, period_binding
from app.utils.owner_checkpoint import OwnerOutcomeUnknown, validate_owner_state

LEDGER_KEY = "owner_continuation_v1"


def owner_continuation_arguments(db, owner):
    token = current_job_stop.get()
    if token is None:
        return {}
    if OWNER_TASKS.get(token.task_identity) != owner:
        raise ValueError("JOB_OWNER_UNSUPPORTED")
    job = db.get(JobRun, token.job_id)
    try:
        payload = json.loads(job.result_json or "{}")
        saved = payload.get(LEDGER_KEY)
        if saved is not None:
            validate_owner_state(saved, safe=True)
    except (ValueError, TypeError, AttributeError) as exc:
        raise OwnerOutcomeUnknown("JOB_OWNER_LEDGER_UNKNOWN") from exc
    checkpoint = token.resume_checkpoint
    if checkpoint and checkpoint.get("owner") == owner:
        if saved != checkpoint["state"]:
            raise OwnerOutcomeUnknown("JOB_OWNER_LEDGER_CHANGED")
    # Only the admission read is outstanding here, never caller mutations.
    db.rollback()

    def continuation(phase, state):
        if phase == "rollback":
            try:
                db.rollback()
            except Exception as exc:
                raise OwnerOutcomeUnknown("JOB_OWNER_ROLLBACK_UNKNOWN") from exc
            return
        if phase == "checkpoint":
            evidence = dict(safe_point="owner_transaction_complete", owner=owner, state=state,
                current=len(state["results"]), total=len(state["items"]), job_id=token.job_id,
                binding=period_binding(token.task_identity, token.task_args))
            checkpoint_after_transaction(db, evidence)
            return
        try:
            job = db.get(JobRun, token.job_id)
            result = json.loads(job.result_json or "{}")
            result[LEDGER_KEY] = state
            job.result_json = json.dumps(result, ensure_ascii=False, default=str)
            if phase == "save":
                db.commit()
            elif phase != "stage":
                raise ValueError("JOB_OWNER_PHASE_INVALID")
        except Exception as exc:
            raise OwnerOutcomeUnknown("JOB_OWNER_PERSISTENCE_UNKNOWN") from exc

    return {"continuation": continuation, "resume_state": saved}
