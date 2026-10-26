"""JobService worker protocol; no executor, persistence or lifecycle owner."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event
from typing import Any


@dataclass
class JobStopToken:
    requested: Event = field(default_factory=Event)
    safe_point: str | None = None
    task_identity: tuple[str, str] | None = None
    task_args: tuple = ()
    job_id: int | None = None
    resume_checkpoint: dict | None = None


current_job_stop: ContextVar[JobStopToken | None] = ContextVar("job_stop", default=None)


class JobPaused(BaseException):
    """Expected owner unwind, deliberately outside broad provider Exception handlers."""

    def __init__(self, checkpoint: dict[str, Any]):
        self.checkpoint = checkpoint


def checkpoint_after_transaction(db, checkpoint: dict[str, Any]) -> None:
    """Called only by a worker with an audited commit/rollback boundary.

    Never commit caller work implicitly. An open transaction (even a read) must
    first be ended by its owner. The JobService persists the pause after unwind.
    """
    token = current_job_stop.get()
    if token is None:
        return
    if db.in_transaction():
        raise RuntimeError("JOB_CHECKPOINT_TRANSACTION_OPEN")
    token.safe_point = str(checkpoint["safe_point"])
    if token.requested.is_set():
        raise JobPaused(checkpoint)


def period_checkpoint_arguments(db, owner: str) -> dict:
    """Injection at audited Job entrypoints only; domain owns every transaction."""
    from app.jobs.resumption import PERIOD_TASK_OWNERS, period_binding

    token = current_job_stop.get()
    if token is None:
        return {}
    if PERIOD_TASK_OWNERS.get(token.task_identity) != owner:
        raise ValueError("JOB_PERIOD_OWNER_UNSUPPORTED")
    saved = token.resume_checkpoint
    resume_state = saved["state"] if saved and saved.get("owner") == owner else None

    def checkpoint(evidence):
        evidence = {**evidence, "job_id": token.job_id,
                    "binding": period_binding(token.task_identity, token.task_args)}
        checkpoint_after_transaction(db, evidence)

    return {"checkpoint": checkpoint, "resume_state": resume_state}


def radar_outcome_checkpoint_arguments(db) -> dict:
    """The outcome owner resumes from its existing pending-path ledger."""
    from app.jobs.resumption import RADAR_OUTCOME_TASK, period_binding

    token = current_job_stop.get()
    if token is None:
        return {}
    if token.task_identity != RADAR_OUTCOME_TASK:
        raise ValueError("JOB_OUTCOME_OWNER_UNSUPPORTED")

    def checkpoint(evidence):
        checkpoint_after_transaction(db, {**evidence, "job_id": token.job_id,
            "binding": period_binding(token.task_identity, token.task_args)})

    return {"checkpoint": checkpoint}
