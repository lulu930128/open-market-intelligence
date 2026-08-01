from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Base,
    ProviderEvent,
    USCorporateAction,
    USCorporateEvent,
    USStockMaster,
)
from app.us_market.corporate_events import (
    get_us_stock_event_summary,
    list_us_corporate_events,
    parse_alphavantage_earnings_calendar_csv,
    refresh_us_corporate_events,
)
from app.us_market.errors import USMarketDataFetchError


CSV_HEADER = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"


class USCorporateEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_parser_skips_malformed_rows_without_losing_valid_rows(self) -> None:
        records, malformed_count = parse_alphavantage_earnings_calendar_csv(
            CSV_HEADER
            + "AAPL,Apple Inc.,2026-08-01,2026-06-30,1.23,USD\n"
            + "MSFT,Microsoft,not-a-date,2026-06-30,2.00,USD\n"
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(malformed_count, 1)
        self.assertEqual(records[0].event_uid, "us:AAPL:earnings:2026-06-30")
        self.assertEqual(records[0].event_date, date(2026, 8, 1))
        self.assertEqual(records[0].estimated_eps, 1.23)

    def test_parser_rejects_an_unrecognized_csv_contract(self) -> None:
        with self.assertRaises(USMarketDataFetchError):
            parse_alphavantage_earnings_calendar_csv("ticker,date\nAAPL,2026-08-01\n")

    def test_refresh_updates_same_logical_event_when_report_date_is_revised(self) -> None:
        first_payload = (
            CSV_HEADER
            + "AAPL,Apple Inc.,2026-08-01,2026-06-30,1.23,USD\n"
        )
        revised_payload = (
            CSV_HEADER
            + "AAPL,Apple Inc.,2026-08-02,2026-06-30,1.25,USD\n"
        )

        with (
            patch.object(settings, "alphavantage_api_key", "test-key"),
            patch(
                "app.us_market.corporate_events."
                "fetch_alphavantage_earnings_calendar_csv",
                side_effect=[
                    (first_payload, "https://example.test/query?apikey=REDACTED"),
                    (revised_payload, "https://example.test/query?apikey=REDACTED"),
                ],
            ) as fetch_mock,
        ):
            first = refresh_us_corporate_events(
                db=self.db,
                now=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
            )
            second = refresh_us_corporate_events(
                db=self.db,
                now=datetime(2026, 7, 29, 15, tzinfo=timezone.utc),
            )

        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(first["request_count"], 1)
        self.assertEqual(first["request_limit"], 1)
        self.assertEqual(first["inserted_count"], 1)
        self.assertEqual(second["updated_count"], 1)
        self.assertEqual(self.db.query(USCorporateEvent).count(), 1)
        event = self.db.query(USCorporateEvent).one()
        self.assertEqual(event.event_uid, "us:AAPL:earnings:2026-06-30")
        self.assertEqual(event.event_date, date(2026, 8, 2))
        self.assertEqual(event.estimated_eps, 1.25)
        self.assertEqual(
            self.db.query(ProviderEvent)
            .filter(ProviderEvent.resource == "corporate_events")
            .count(),
            2,
        )

    def test_failed_refresh_preserves_cache_and_records_provider_failure(self) -> None:
        cached = USCorporateEvent(
            event_uid="us:AAPL:earnings:2026-06-30",
            provider="alphavantage",
            symbol="AAPL",
            company_name="Apple Inc.",
            event_type="earnings",
            event_subtype="quarterly_earnings",
            title="Apple Inc. Earnings",
            event_status="scheduled",
            verification_status="third_party",
            event_date=date(2026, 8, 1),
            timezone_name="America/New_York",
            market_session="unknown",
            is_all_day=True,
            fiscal_period_end=date(2026, 6, 30),
            fetched_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
            first_seen_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
            is_active=True,
            created_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
        )
        self.db.add(cached)
        self.db.commit()

        with (
            patch.object(settings, "alphavantage_api_key", "test-key"),
            patch(
                "app.us_market.corporate_events."
                "fetch_alphavantage_earnings_calendar_csv",
                side_effect=USMarketDataFetchError("provider timeout"),
            ),
        ):
            with self.assertRaises(USMarketDataFetchError):
                refresh_us_corporate_events(
                    db=self.db,
                    now=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
                )

        self.assertEqual(self.db.query(USCorporateEvent).count(), 1)
        provider_event = (
            self.db.query(ProviderEvent)
            .filter(ProviderEvent.resource == "corporate_events")
            .one()
        )
        self.assertEqual(provider_event.status, "error")
        self.assertEqual(provider_event.error_message, "provider timeout")

    def test_list_combines_earnings_and_cached_actions_with_explicit_coverage(
        self,
    ) -> None:
        fetched_at = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="test",
                is_test_issue=False,
                is_active=True,
            )
        )
        self.db.add(
            USCorporateEvent(
                event_uid="us:AAPL:earnings:2026-06-30",
                provider="alphavantage",
                symbol="AAPL",
                company_name="Apple Inc.",
                event_type="earnings",
                event_subtype="quarterly_earnings",
                title="Apple Inc. Earnings",
                event_status="scheduled",
                verification_status="third_party",
                event_date=date(2026, 8, 1),
                timezone_name="America/New_York",
                market_session="unknown",
                is_all_day=True,
                fiscal_period_end=date(2026, 6, 30),
                fetched_at=fetched_at,
                first_seen_at=fetched_at,
                last_seen_at=fetched_at,
                is_active=True,
                created_at=fetched_at,
                updated_at=fetched_at,
            )
        )
        self.db.add(
            USCorporateAction(
                provider="alphavantage",
                symbol="AAPL",
                action_type="dividend",
                event_date=date(2026, 8, 3),
                amount=0.25,
                fetched_at=fetched_at,
                created_at=fetched_at,
                updated_at=fetched_at,
            )
        )
        self.db.commit()

        listing = list_us_corporate_events(
            db=self.db,
            date_from=date(2026, 7, 29),
            date_to=date(2026, 8, 5),
            now=fetched_at,
        )

        self.assertEqual(listing["result_count"], 2)
        self.assertEqual(
            [item["event_type"] for item in listing["results"]],
            ["earnings", "dividend"],
        )
        self.assertEqual(
            listing["sources"]["alphavantage_actions"]["status"],
            "watchlist_only",
        )
        self.assertEqual(
            listing["sources"]["alphavantage_actions"]["coverage"],
            "cached_symbols_only",
        )
        self.assertIn("watchlist cache", listing["warning"])

    def test_summary_uses_new_york_market_date_for_seven_day_window(self) -> None:
        fetched_at = datetime(2026, 7, 29, 1, tzinfo=timezone.utc)
        self.db.add(
            USCorporateEvent(
                event_uid="us:MSFT:earnings:2026-06-30",
                provider="alphavantage",
                symbol="MSFT",
                company_name="Microsoft",
                event_type="earnings",
                event_subtype="quarterly_earnings",
                title="Microsoft Earnings",
                event_status="scheduled",
                verification_status="third_party",
                event_date=date(2026, 8, 4),
                timezone_name="America/New_York",
                market_session="unknown",
                is_all_day=True,
                fiscal_period_end=date(2026, 6, 30),
                fetched_at=fetched_at,
                first_seen_at=fetched_at,
                last_seen_at=fetched_at,
                is_active=True,
                created_at=fetched_at,
                updated_at=fetched_at,
            )
        )
        self.db.commit()

        summary = get_us_stock_event_summary(
            db=self.db,
            symbol="MSFT",
            reminder_days=7,
            now=fetched_at,
        )

        self.assertEqual(summary["as_of"], date(2026, 7, 28))
        self.assertEqual(summary["result_count"], 1)
        self.assertEqual(summary["results"][0]["days_until"], 7)


if __name__ == "__main__":
    unittest.main()
