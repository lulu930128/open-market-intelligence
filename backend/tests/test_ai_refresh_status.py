from __future__ import annotations

import json
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import refresh_status
from app.ai.schemas import AiRefreshStatusRead
from app.db.models import Base
from app.jobs import service as job_service
from app.routers import ai as ai_router


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def refresh_request() -> dict:
    return {
        "normalized_target": "AAPL",
        "refresh_profile": "compact",
        "provider_set": ["yahoo"],
        "date_range": {"from": None, "to": None},
        "include_today": None,
        "requested_capabilities": [
            "daily.ohlcv",
            "us.refresh_daily_price",
        ],
        "api_key": "must-never-be-public",
    }


class AiRefreshStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    def test_running_status_is_redacted_and_does_not_claim_evidence(self) -> None:
        job = job_service.create_job(
            self.db,
            job_type=refresh_status.AI_REFRESH_JOB_TYPE,
            target="AAPL",
            request=refresh_request(),
            progress_total=1,
        )
        job_service.start_job(self.db, job.id)

        result = refresh_status.read_refresh_status(
            db=self.db,
            job_id=job.id,
        )
        validated = AiRefreshStatusRead.model_validate(result)

        self.assertEqual(validated.status, "running")
        self.assertEqual(validated.operation_status, "running")
        self.assertEqual(validated.evidence_status, "unobserved")
        self.assertFalse(validated.evidence_rebuild_required)
        self.assertIsNone(validated.resume)
        self.assertEqual(validated.operation, "us.refresh_daily_price")
        self.assertEqual(validated.requested_capabilities, ["daily.ohlcv"])
        self.assertEqual(validated.produced_capabilities, ["daily.ohlcv"])
        self.assertEqual(
            validated.poll_url,
            f"/api/ai/refresh-status/{job.id}",
        )
        serialized = json.dumps(result, default=str)
        self.assertNotIn("must-never-be-public", serialized)
        self.assertNotIn("api_key", serialized)

    def test_completed_status_requires_cache_only_evidence_rebuild(self) -> None:
        job = job_service.create_job(
            self.db,
            job_type=refresh_status.AI_REFRESH_JOB_TYPE,
            target="AAPL",
            request=refresh_request(),
            progress_total=1,
        )
        job_service.start_job(self.db, job.id)
        job_service.complete_job(
            self.db,
            job.id,
            result={
                "status": "completed",
                "tool": "us.refresh_daily_price",
                "result": {"fetched_count": 7, "inserted_count": 5},
            },
        )

        result = refresh_status.read_refresh_status(
            db=self.db,
            job_id=job.id,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["operation_status"], "succeeded")
        self.assertEqual(result["evidence_status"], "rebuild_required")
        self.assertTrue(result["evidence_rebuild_required"])
        self.assertEqual(result["result_summary"]["fetched_count"], 7)
        resume = result["resume"]["arguments"]
        self.assertEqual(resume["realtime_policy"], "cache_only")
        self.assertFalse(resume["allow_external_fetch"])
        self.assertFalse(resume["allow_llm"])
        self.assertFalse(resume["allow_write"])

    def test_failure_returns_stable_error_without_raw_provider_message(self) -> None:
        job = job_service.create_job(
            self.db,
            job_type=refresh_status.AI_REFRESH_JOB_TYPE,
            target="AAPL",
            request=refresh_request(),
        )
        job_service.start_job(self.db, job.id)
        job_service.fail_job(
            self.db,
            job.id,
            error_message="https://provider.test?token=private-token timed out",
            result={
                "status": "failed",
                "tool": "us.refresh_daily_price",
                "error": "private-token",
            },
        )

        result = refresh_status.read_refresh_status(
            db=self.db,
            job_id=job.id,
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["error"]["code"], "AI_REFRESH_FAILED")
        self.assertNotIn("private-token", json.dumps(result, default=str))

    def test_unknown_and_non_ai_jobs_share_the_same_public_404(self) -> None:
        other = job_service.create_job(
            self.db,
            job_type="market.backfill",
            target="2330",
            request={"private": "payload"},
        )
        for job_id in (other.id, other.id + 999):
            with self.subTest(job_id=job_id):
                with self.assertRaises(refresh_status.AiRefreshJobNotFoundError):
                    refresh_status.read_refresh_status(
                        db=self.db,
                        job_id=job_id,
                    )
                with self.assertRaises(HTTPException) as caught:
                    ai_router.read_ai_refresh_status(
                        job_id=job_id,
                        db=self.db,
                    )
                self.assertEqual(caught.exception.status_code, 404)
                self.assertEqual(
                    caught.exception.detail["code"],
                    "AI_REFRESH_JOB_NOT_FOUND",
                )


if __name__ == "__main__":
    unittest.main()
