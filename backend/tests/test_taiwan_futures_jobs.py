from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, JobRun
from app.market.tw_futures import TaiwanFuturesFetchError
from app.market.tw_futures_jobs import record_taiwan_futures_quote_refresh_issue


class TaiwanFuturesJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_refresh_issue_with_cache_records_partial_success(self) -> None:
        job = record_taiwan_futures_quote_refresh_issue(
            self.db,
            symbols="txf,mxf",
            session="regular",
            provider="taifex_mis",
            exc=TaiwanFuturesFetchError("provider returned 520"),
            cached_count=1,
        )
        result = json.loads(job.result_json or "{}")

        self.assertEqual(job.status, "success")
        self.assertEqual(job.target, "TXF,MXF")
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["success_count"], 1)
        self.assertIn("520", job.message or "")

    def test_refresh_issue_reuses_recent_job_and_records_missing_cache(self) -> None:
        first = record_taiwan_futures_quote_refresh_issue(
            self.db,
            symbols="TXF",
            session="after_hours",
            provider="taifex_mis",
            exc=TaiwanFuturesFetchError("provider unavailable"),
            cached_count=1,
        )
        second = record_taiwan_futures_quote_refresh_issue(
            self.db,
            symbols="TXF",
            session="after_hours",
            provider="taifex_mis",
            exc=TaiwanFuturesFetchError("provider unavailable"),
            cached_count=0,
        )
        result = json.loads(second.result_json or "{}")

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(JobRun).count(), 1)
        self.assertEqual(second.status, "error")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_count"], 1)
        self.assertIn("沒有可用快取", second.error_message or "")


if __name__ == "__main__":
    unittest.main()
