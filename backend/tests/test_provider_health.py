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
        with patch.object(
            provider_health,
            "_now",
            return_value=now + timedelta(minutes=2),
        ):
            snapshot_rows = list_source_health_snapshots(self.db, market="us", target="MU")

        self.assertEqual(snapshots[0].latest_event_id, event.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "current")
        self.assertEqual(rows[0].latest_data_date, date(2026, 6, 15))
        self.assertEqual(rows[0].latest_event_status, "rate_limited")
        self.assertEqual(rows[0].recent_error_count, 1)
        self.assertEqual(snapshot_rows[0]["resource"], "daily_price")
        self.assertEqual(snapshot_rows[0]["snapshot_age_seconds"], 60)
        self.assertFalse(snapshot_rows[0]["snapshot_is_stale"])

    def test_source_health_snapshot_reports_stale_snapshot_age(self) -> None:
        checked_at = datetime(2026, 6, 14, 11, 59, 59, tzinfo=timezone.utc)
        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        sync_source_health_snapshots(
            self.db,
            market="tw",
            entries=[
                {
                    "resource": "daily_price",
                    "provider": "twse",
                    "target": "all",
                    "status": "current",
                    "ok": True,
                    "row_count": 10,
                    "required": True,
                    "data_quality": "ok",
                }
            ],
            checked_at=checked_at,
        )

        with patch.object(provider_health, "_now", return_value=now):
            snapshots = list_source_health_snapshots(self.db, market="tw")

        self.assertEqual(snapshots[0]["snapshot_age_seconds"], 86401)
        self.assertTrue(snapshots[0]["snapshot_is_stale"])

    def test_degraded_source_health_transition_creates_one_trace_event(self) -> None:
        checked_at = datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc)
        entry = {
            "resource": "daily_price",
            "provider": "yahoo_chart",
            "target": "^N225",
            "status": "stale",
            "ok": False,
            "row_count": 90,
            "required": True,
            "data_quality": "stale",
            "latest_data_date": "2026-07-21",
            "expected_data_date": "2026-07-23",
            "freshness_lag_days": 2,
            "reason": "Latest daily price is behind the expected session.",
        }

        first = sync_source_health_snapshots(
            self.db,
            market="jp",
            entries=[entry],
            checked_at=checked_at,
        )
        second = sync_source_health_snapshots(
            self.db,
            market="jp",
            entries=[entry],
            checked_at=checked_at + timedelta(minutes=1),
        )
        events = list_provider_events(
            self.db,
            market="jp",
            provider="yahoo_chart",
            target="^N225",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "source_health_transition")
        self.assertEqual(events[0]["status"], "stale")
        self.assertEqual(first[0].recent_event_count, 1)
        self.assertEqual(second[0].latest_event_status, "stale")

    def test_composite_source_provider_matches_any_component_event(self) -> None:
        now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
        with patch.object(provider_health, "_now", return_value=now):
            event = record_provider_event(
                self.db,
                market="kr",
                provider="krx_data",
                resource="symbol_master",
                target="005930.KS",
                status="error",
                event_time=now,
                error_message="KRX unavailable",
            )
            entries = enrich_source_health_entries(
                self.db,
                market="kr",
                entries=[
                    {
                        "resource": "symbol_master",
                        "provider": "krx_data+yahoo_chart",
                        "target": "005930.KS",
                        "status": "available",
                        "ok": True,
                        "row_count": 1,
                        "data_quality": "ok",
                        "reason": "local row available",
                    }
                ],
            )

        self.assertEqual(entries[0]["latest_event_id"], event.id)
        self.assertEqual(entries[0]["latest_event_status"], "error")
        self.assertEqual(entries[0]["recent_error_count"], 1)

    def test_source_health_exposes_refresh_cooldown_from_latest_event(self) -> None:
        now = datetime(2026, 7, 25, 5, 0, tzinfo=timezone.utc)
        next_eligible = now + timedelta(minutes=45)
        with patch.object(provider_health, "_now", return_value=now):
            record_provider_event(
                self.db,
                market="tw",
                provider="tdcc",
                resource="shareholding_distribution_weekly",
                target="2330",
                status="success",
                event_type="refresh_no_change",
                event_time=now,
                detail={
                    "refresh_outcome": "unchanged",
                    "next_eligible_refresh_at": next_eligible.isoformat(),
                },
            )
            entries = enrich_source_health_entries(
                self.db,
                market="tw",
                entries=[
                    {
                        "resource": "shareholding_distribution_weekly",
                        "provider": "tdcc",
                        "target": "2330",
                        "status": "stale",
                        "ok": False,
                        "row_count": 10,
                    }
                ],
            )

        self.assertFalse(entries[0]["refresh_eligible"])
        self.assertEqual(
            entries[0]["next_eligible_refresh_at"],
            next_eligible.isoformat(),
        )
        self.assertEqual(
            entries[0]["latest_event_detail"]["refresh_outcome"],
            "unchanged",
        )


if __name__ == "__main__":
    unittest.main()
