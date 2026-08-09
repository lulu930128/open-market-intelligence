from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import DispatchDelivery, DispatchSchedule, DispatchScheduleRun, JobRun
from app.db.session import SessionLocal
from app.dispatch import schedule_runs
from app.dispatch import service as dispatch_service
from app.dispatch.mail_sender import SmtpMailSender
from app.dispatch.schemas import DispatchRecipientGroupCreate, DispatchScheduleCreate
from app.dispatch.tasks import run_dispatch_schedule_run_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one auditable OMI Dispatch Scheduler v2 SMTP smoke message."
    )
    parser.add_argument("--recipient", required=True, help="Single smoke-test recipient.")
    parser.add_argument(
        "--confirm-live-send",
        action="store_true",
        help="Required guard acknowledging that this command sends one real email.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_live_send:
        raise SystemExit("Refusing live SMTP smoke without --confirm-live-send.")

    # Validate configuration before creating any durable dispatch records.
    SmtpMailSender.from_settings()

    recipient = args.recipient.strip()
    token = uuid.uuid4().hex[:12]
    group_id: int | None = None
    schedule_id: int | None = None
    run_id: int | None = None
    delivery_id: int | None = None
    job_id: int | None = None

    db = SessionLocal()
    try:
        group = dispatch_service.create_recipient_group(
            db,
            DispatchRecipientGroupCreate(
                name=f"OMI SMTP smoke {token}",
                description="Ephemeral one-recipient Dispatch Scheduler v2 smoke group.",
                emails=[recipient],
                enabled=True,
            ),
        )
        group_id = int(group["id"])
        schedule = dispatch_service.create_schedule(
            db,
            DispatchScheduleCreate(
                name=f"OMI SMTP smoke {token}",
                description="Ephemeral manual-only Dispatch Scheduler v2 smoke schedule.",
                recipient_group_id=group_id,
                enabled=False,
                send_time="00:00",
                day_of_week="mon-sun",
                timezone="Asia/Taipei",
                calendar_mode="calendar_days",
                catchup_mode="latest_only",
                misfire_policy="skip",
                max_retries=0,
                readiness_profile="generic",
                readiness_policy="immediate",
                template_key="market_overview",
                scope_type="market",
                scope_id="tw",
                content_depth="standard",
            ),
        )
        schedule_id = int(schedule["id"])
        schedule_model = db.get(DispatchSchedule, schedule_id)
        if schedule_model is None:
            raise RuntimeError("Smoke schedule disappeared before run creation.")

        run = schedule_runs.create_manual_run(
            db,
            schedule=schedule_model,
            force_immediate=True,
        )
        run_id = int(run.id)
        readiness = schedule_runs.evaluate_run_readiness(db, run_id=run_id)
        if readiness.get("action") != "queue":
            raise RuntimeError("Smoke run did not reach the queue action.")

        queued = dispatch_service.queue_schedule_run(
            db,
            run_id=run_id,
            submit_task=False,
        )
        delivery_id = int(queued["delivery"]["id"])
        job_id = int(queued["job"]["id"])
        if int(queued["delivery"]["recipient_count"]) != 1:
            raise RuntimeError("Smoke delivery recipient count was not exactly one.")

        delivery = db.get(DispatchDelivery, delivery_id)
        if delivery is None:
            raise RuntimeError("Smoke delivery disappeared before SMTP submission.")
        delivery.subject = f"[OMI TEST] Dispatch Scheduler v2 run-{run_id}"
        delivery.body_text = (
            "OMI Dispatch Scheduler v2 live SMTP smoke.\n\n" + delivery.body_text
        )
        delivery.body_html = (
            "<p><strong>OMI Dispatch Scheduler v2 live SMTP smoke.</strong></p>"
            + delivery.body_html
        )
        db.commit()
    finally:
        db.close()

    # Run synchronously exactly once. The worker records sent, error, or unknown;
    # this script never retries an SMTP attempt with an uncertain outcome.
    run_dispatch_schedule_run_job(job_id, run_id, delivery_id)

    db = SessionLocal()
    try:
        run = db.get(DispatchScheduleRun, run_id)
        delivery = db.get(DispatchDelivery, delivery_id)
        job = db.get(JobRun, job_id)
        if run is None or delivery is None or job is None:
            raise RuntimeError("Smoke audit records were incomplete after SMTP submission.")
        result = {
            "status": "success" if delivery.status == "success" else "failed",
            "schedule_run_id": run.id,
            "schedule_run_status": run.status,
            "delivery_id": delivery.id,
            "delivery_status": delivery.status,
            "job_id": job.id,
            "job_status": job.status,
            "recipient_count": delivery.recipient_count,
            "message_id": delivery.message_id,
            "error_code": run.error_code,
            "retryable": run.retryable,
        }
        return_code = 0 if delivery.status == "success" else 1
    finally:
        if schedule_id is not None:
            try:
                dispatch_service.delete_schedule(db, schedule_id)
            except Exception:
                db.rollback()
        if group_id is not None:
            try:
                dispatch_service.delete_recipient_group(db, group_id)
            except Exception:
                db.rollback()
        db.close()

    print(json.dumps(result, ensure_ascii=False, default=str))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
