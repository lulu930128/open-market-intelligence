from sqlalchemy.orm import Session

from app.dispatch import service as dispatch_service
from app.jobs.service import ProgressCallback, run_tracked_job


def run_dispatch_delivery_job(job_id: int, delivery_id: int) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Sending dispatch mail.")
        result = dispatch_service.send_delivery(db=db, delivery_id=delivery_id)
        progress(1, 1, "Dispatch mail sent.")
        return {
            "status": result["status"],
            "delivery_id": result["id"],
            "recipient_count": result["recipient_count"],
        }

    run_tracked_job(job_id, worker)


def run_dispatch_schedule_run_job(job_id: int, schedule_run_id: int, delivery_id: int) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Sending scheduled dispatch mail.")
        result = dispatch_service.send_delivery(
            db=db,
            delivery_id=delivery_id,
            schedule_run_id=schedule_run_id,
        )
        progress(1, 1, "Scheduled dispatch mail sent.")
        return {
            "status": result["status"],
            "schedule_run_id": schedule_run_id,
            "delivery_id": result["id"],
            "recipient_count": result["recipient_count"],
            "message_id": result.get("message_id"),
        }

    run_tracked_job(job_id, worker)
