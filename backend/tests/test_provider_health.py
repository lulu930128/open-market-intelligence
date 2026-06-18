from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, SourceHealthSnapshot
from app.observability import provider_health
from app.observability.provider_health import (
    enrich_source_health_entries,
    list_provider_events,
    list_source_health_snapshots,
    provider_event_summary,
    record_provider_event,
    sync_source_health_snapshots,
)


class ProviderHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_provider_events_are_queryable_and_summarized(self) -> None:
        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        with patch.object(provider_health, "_now", return_value=now):
            record_provider_event(
                self.db,
                market="tw",
                provider="twse",
                resource="market_daily_price",
                target="2330",
                status="success",
                event_time=now - timedelta(hours=2),
                message="ok",
            )
            latest = record_provider_event(
                self.db,
                market="tw",
                provider="twse",
                resource="market_daily_price",
                target="2330",
                status="error",
                event_time=now,
                http_status_code=502,
                error_message="TWSE 502",
            )

            events = list_provider_events(self.db, market="tw", provider="twse", limit=10)
            summary = provider_event_summary(
                self.db,
                market="tw",
                provider="twse",
                resource="market_daily_price",
                target="2330",
            )

        self.assertEqual(events[0]["id"], latest.id)
        self.assertEqual(events[0]["status"], "error")
        self.assertEqual(summary["latest_event"]["id"], latest.id)
        self.assertEqual(summary["recent_event_count"], 2)
        self.assertEqual(summary["recent_error_count"], 1)
        self.assertEqual(summary["consecutive_error_count"], 1)

    def test_source_health_entries_are_enriched_and_snapshots_upsert(self) -> None:
        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        with patch.object(provider_health, "_now", return_value=now):
            event = record_provider_event(
                self.db,
                market="us",
                provider="yahoo_chart",
                resource="daily_price",
                target="MU",
                status="rate_limited",
                severity="warning",
                event_time=now,
                rate_limited=True,
                retry_after_seconds=60,
                error_message="429",
            )
            entries = enrich_source_health_entries(
                self.db,
                market="us",
                entries=[
                    {
                        "resource": "daily_price",
                        "provider": "yahoo_chart",
                        "target": "MU",
                        "status": "stale",
                        "ok": False,
                        "row_count": 10,
                        "required": True,
                        "latest_data_date": "2026-06-12",
                        "expected_data_date": "2026-06-15",
                        "freshness_lag_days": 3,
                        "data_quality": "stale",
                        "reason": "behind expected date",
                    }
                ],
            )
        snapshots = sync_source_health_snapshots(
            self.db,
            market="us",
            entries=entries,
            checked_at=now,
        )
        entries[0]["status"] = "current"
        entries[0]["ok"] = True
        entries[0]["latest_data_date"] = "2026-06-15"
        entries[0]["freshness_lag_days"] = 0
        sync_source_health_snapshots(
            self.db,
            market="us",
            entries=entries,
            checked_at=now + timedelta(minutes=1),
        )

        rows = self.db.query(SourceHealthSnapshot).all()
        snapshot_rows = list_source_health_snapshots(self.db, market="us", target="MU")

        self.assertEqual(snapshots[0].latest_event_id, event.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "current")
        self.assertEqual(rows[0].latest_data_date, date(2026, 6, 15))
        self.assertEqual(rows[0].latest_event_status, "rate_limited")
        self.assertEqual(rows[0].recent_error_count, 1)
        self.assertEqual(snapshot_rows[0]["resource"], "daily_price")


if __name__ == "__main__":
    unittest.main()
