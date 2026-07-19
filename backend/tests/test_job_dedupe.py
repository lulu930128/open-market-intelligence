from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, utc_now
from app.jobs import service


class JobDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_recent_success_is_reused_within_cooldown(self) -> None:
        request = {"group_id": 3, "trade_date": "2026-07-17"}
        existing = service.create_job(
            self.db,
            job_type="watchlist.group_daily_price_refresh_latest",
            target="3",
            request=request,
        )
        existing.status = "success"
        existing.ended_at = utc_now()
        self.db.commit()

        task = Mock()
        with patch.object(service, "submit_job_task") as submit:
            job, created = service.enqueue_job(
                self.db,
                job_type="watchlist.group_daily_price_refresh_latest",
                target="3",
                request=request,
                task=task,
                reuse_success_within_seconds=300,
            )

        self.assertFalse(created)
        self.assertEqual(job.id, existing.id)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
