from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    ProviderEvent,
    USSecOwnershipFiling,
    USSecOwnershipSyncState,
    USSecOwnershipTransaction,
    USStockMaster,
)
from app.us_market.ownership_service import read_insider_transactions, sync_form4_symbol
from app.us_market.ownership_store import persist_form4_filing, update_form4_sync_state
from app.us_market.source_health import build_us_source_health

from app.us_market.sec_ownership import (
    parse_form4_submission_entries,
    parse_form4_xml,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "us_sec"


class USSecForm4ParserTests(unittest.TestCase):
    def test_parses_official_shape_without_flattening_transaction_semantics(self) -> None:
        filing = parse_form4_xml(
            (FIXTURE_DIR / "form4_official_shape.xml").read_bytes(),
            accession_number="0001000001-26-000001",
            filing_date=date(2026, 6, 17),
            source_url="https://www.sec.gov/Archives/example/form4.xml",
        )

        self.assertEqual(filing.form_type, "4")
        self.assertEqual(filing.issuer_cik, "0000320193")
        self.assertEqual(filing.issuer_trading_symbol, "AAPL")
        self.assertTrue(filing.aff10b5_one)
        self.assertEqual(len(filing.owners), 2)
        self.assertEqual(len(filing.transactions), 3)
        self.assertEqual(len(filing.positions), 1)
        self.assertEqual(len(filing.footnotes), 2)
        self.assertEqual(
            [item.transaction_code for item in filing.transactions],
            ["P", "F", "M"],
        )
        self.assertEqual(filing.transactions[0].shares_text, "1250.50")
        self.assertEqual(filing.transactions[0].price_per_share_text, "201.25")
        self.assertEqual(filing.transactions[2].table_type, "derivative")
        self.assertEqual(filing.transactions[2].underlying_shares_text, "500")
        self.assertEqual(filing.positions[0].nature_of_ownership, "By family trust")

    def test_amendment_is_append_only_metadata_not_an_implicit_delete(self) -> None:
        filing = parse_form4_xml(
            (FIXTURE_DIR / "form4_amendment_official_shape.xml").read_bytes(),
            accession_number="0001000001-26-000002",
            filing_date=date(2026, 6, 18),
            source_url="https://www.sec.gov/Archives/example/form4-amendment.xml",
        )

        self.assertEqual(filing.form_type, "4/A")
        self.assertTrue(filing.is_amendment)
        self.assertEqual(filing.original_submission_date, date(2026, 6, 17))
        self.assertEqual(filing.transactions[0].price_per_share_text, "202.00")
        self.assertIn("Corrects", filing.remarks or "")

    def test_invalid_decimal_is_visible_instead_of_becoming_zero(self) -> None:
        payload = (FIXTURE_DIR / "form4_official_shape.xml").read_text(encoding="utf-8")
        payload = payload.replace("<value>1250.50</value>", "<value>not-a-number</value>", 1)

        filing = parse_form4_xml(
            payload,
            accession_number="0001000001-26-000003",
            source_url="https://www.sec.gov/Archives/example/form4-invalid.xml",
        )

        self.assertIsNone(filing.transactions[0].shares_text)
        self.assertIn("USO001_invalid_decimal", filing.transactions[0].issue_codes)
        self.assertIn("USO001_invalid_decimal", filing.issue_codes)

    def test_malformed_xml_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_form4_xml(
                "<ownershipDocument>",
                accession_number="0001000001-26-000004",
                source_url="https://www.sec.gov/Archives/example/form4-bad.xml",
            )

    def test_submissions_parser_is_bounded_and_keeps_form4_amendments(self) -> None:
        payload = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "4", "4/A", "4"],
                    "filingDate": ["2026-06-20", "2026-06-19", "2026-06-18", "2025-01-01"],
                    "reportDate": ["2026-06-01", "2026-06-15", "2026-06-15", "2024-12-31"],
                    "acceptanceDateTime": [
                        "20260620120000",
                        "20260619120000",
                        "20260618120000",
                        "20250101120000",
                    ],
                    "accessionNumber": ["q", "one", "two", "old"],
                    "primaryDocument": ["q.xml", "xslF345X/form4.xml", "form4a.xml", "old.xml"],
                }
            }
        }

        entries = parse_form4_submission_entries(
            payload,
            from_date=date(2026, 1, 1),
            limit=2,
        )

        self.assertEqual([item.accession_number for item in entries], ["one", "two"])
        self.assertEqual([item.form_type for item in entries], ["4", "4/A"])
        self.assertEqual(entries[0].primary_document, "xslF345X/form4.xml")


class USSecForm4StoreAndServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Example Issuer",
                asset_type="stock",
                listing_source="test",
                cik="0000320193",
                is_test_issue=False,
                is_active=True,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _filing(self, name: str, accession: str, filing_date: date):
        return parse_form4_xml(
            (FIXTURE_DIR / name).read_bytes(),
            accession_number=accession,
            filing_date=filing_date,
            accepted_at=datetime.combine(filing_date, datetime.min.time(), tzinfo=timezone.utc),
            source_url=f"https://www.sec.gov/Archives/example/{accession}/form4.xml",
        )

    def test_store_is_idempotent_and_refuses_hash_overwrite(self) -> None:
        filing = self._filing(
            "form4_official_shape.xml",
            "0001000001-26-000001",
            date(2026, 6, 17),
        )

        first = persist_form4_filing(self.db, filing)
        self.db.commit()
        second = persist_form4_filing(self.db, filing)
        self.db.commit()

        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(self.db.query(USSecOwnershipFiling).count(), 1)
        self.assertEqual(self.db.query(USSecOwnershipTransaction).count(), 3)

        changed = parse_form4_xml(
            (FIXTURE_DIR / "form4_amendment_official_shape.xml").read_bytes(),
            accession_number="0001000001-26-000001",
            filing_date=date(2026, 6, 17),
            source_url="https://www.sec.gov/Archives/example/changed/form4.xml",
        )
        with self.assertRaisesRegex(ValueError, "content hash changed"):
            persist_form4_filing(self.db, changed)

    def test_amendment_replaces_matching_row_but_preserves_unaffected_rows(self) -> None:
        original = self._filing(
            "form4_official_shape.xml",
            "0001000001-26-000001",
            date(2026, 6, 17),
        )
        amendment = self._filing(
            "form4_amendment_official_shape.xml",
            "0001000001-26-000002",
            date(2026, 6, 18),
        )
        persist_form4_filing(self.db, original)
        persist_form4_filing(self.db, amendment)
        update_form4_sync_state(
            self.db,
            symbol="AAPL",
            issuer_cik="0000320193",
            status="current",
            latest_accession_number=amendment.accession_number,
            latest_filing_date=amendment.filing_date,
            fetched_count=2,
            errors=[],
            source_url="https://data.sec.gov/submissions/CIK0000320193.json",
            checked_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        )
        self.db.commit()

        contract = read_insider_transactions(
            self.db,
            symbol="AAPL",
            now=datetime(2026, 6, 18, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(contract["status"], "current")
        self.assertEqual(contract["summary"]["filing_count"], 2)
        self.assertEqual(contract["summary"]["amendment_count"], 1)
        self.assertEqual(contract["summary"]["transaction_count"], 3)
        self.assertEqual(
            [row["price_per_share"] for row in contract["transactions"] if row["transaction_code"] == "P"],
            ["202.00"],
        )
        self.assertEqual(
            {row["transaction_code"] for row in contract["transactions"]},
            {"P", "F", "M"},
        )
        self.assertIn("without Forms 3 and 5", contract["quality"]["limitations"][0])

        first_page = read_insider_transactions(
            self.db,
            symbol="AAPL",
            limit=1,
            now=datetime(2026, 6, 18, 1, tzinfo=timezone.utc),
        )
        second_page = read_insider_transactions(
            self.db,
            symbol="AAPL",
            limit=1,
            cursor=first_page["pagination"]["next_cursor"],
            now=datetime(2026, 6, 18, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(first_page["pagination"]["returned_count"], 1)
        self.assertIsNotNone(first_page["pagination"]["next_cursor"])
        self.assertNotEqual(
            first_page["transactions"][0]["transaction_id"],
            second_page["transactions"][0]["transaction_id"],
        )

        with self.assertRaisesRegex(ValueError, "cursor"):
            read_insider_transactions(
                self.db,
                symbol="AAPL",
                cursor="not-a-valid-cursor",
            )

    def test_sync_is_bounded_and_second_run_does_not_refetch_existing_xml(self) -> None:
        xml = (FIXTURE_DIR / "form4_official_shape.xml").read_bytes()
        submissions = {
            "filings": {
                "recent": {
                    "form": ["4"],
                    "filingDate": ["2026-06-17"],
                    "reportDate": ["2026-06-15"],
                    "acceptanceDateTime": ["20260617120000"],
                    "accessionNumber": ["0001000001-26-000001"],
                    "primaryDocument": ["xslF345X06/form4.xml"],
                }
            }
        }
        with (
            patch(
                "app.us_market.ownership_service.settings.us_sec_user_agent",
                "Open Market Intelligence tests contact=test@example.com",
            ),
            patch(
                "app.us_market.ownership_service.sec_provider.fetch_sec_submissions_payload",
                return_value=(submissions, "https://data.sec.gov/submissions/CIK0000320193.json"),
            ) as fetch_submissions,
            patch(
                "app.us_market.ownership_service.sec_provider.fetch_sec_ownership_xml",
                return_value=(xml, "https://www.sec.gov/Archives/example/form4.xml"),
            ) as fetch_xml,
        ):
            first = sync_form4_symbol(self.db, symbol="AAPL", max_filings=1)
            second = sync_form4_symbol(self.db, symbol="AAPL", max_filings=1)

        self.assertEqual(first["status"], "current")
        self.assertEqual(first["inserted_count"], 1)
        self.assertEqual(second["inserted_count"], 0)
        self.assertEqual(fetch_submissions.call_count, 2)
        self.assertEqual(fetch_xml.call_count, 1)
        self.assertEqual(self.db.query(USSecOwnershipSyncState).one().status, "current")
        self.assertEqual(
            self.db.query(ProviderEvent)
            .filter(ProviderEvent.resource == "sec_insider_transactions")
            .count(),
            2,
        )

    def test_successful_observation_without_filings_is_ready_empty(self) -> None:
        empty_submissions = {"filings": {"recent": {"form": []}}}
        with (
            patch(
                "app.us_market.ownership_service.settings.us_sec_user_agent",
                "Open Market Intelligence tests contact=test@example.com",
            ),
            patch(
                "app.us_market.ownership_service.sec_provider.fetch_sec_submissions_payload",
                return_value=(empty_submissions, "https://data.sec.gov/submissions/CIK0000320193.json"),
            ),
        ):
            result = sync_form4_symbol(self.db, symbol="AAPL", max_filings=1)

        contract = read_insider_transactions(self.db, symbol="AAPL")
        self.assertEqual(result["status"], "ready_empty")
        self.assertEqual(contract["status"], "ready_empty")
        self.assertEqual(contract["transactions"], [])

        health = build_us_source_health(
            self.db,
            symbol="AAPL",
            now=datetime.now(timezone.utc),
            expected_daily_price_date=date(2026, 6, 18),
        )
        insider_entry = next(
            entry
            for entry in health["entries"]
            if entry["resource"] == "sec_insider_transactions"
        )
        self.assertEqual(insider_entry["status"], "ready_empty")
        self.assertTrue(insider_entry["ok"])
        self.assertEqual(insider_entry["row_count"], 0)

    def test_source_health_marks_old_form4_observation_stale(self) -> None:
        update_form4_sync_state(
            self.db,
            symbol="AAPL",
            issuer_cik="0000320193",
            status="ready_empty",
            latest_accession_number=None,
            latest_filing_date=None,
            fetched_count=0,
            errors=[],
            source_url="https://data.sec.gov/submissions/CIK0000320193.json",
            checked_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        )
        self.db.commit()

        health = build_us_source_health(
            self.db,
            symbol="AAPL",
            now=datetime(2026, 6, 19, tzinfo=timezone.utc),
            expected_daily_price_date=date(2026, 6, 18),
        )
        insider_entry = next(
            entry
            for entry in health["entries"]
            if entry["resource"] == "sec_insider_transactions"
        )
        self.assertEqual(insider_entry["status"], "stale")
        self.assertFalse(insider_entry["ok"])
        self.assertEqual(
            insider_entry["freshness_basis"],
            "sec_submissions_observation_window",
        )

    def test_read_path_never_calls_sec_provider(self) -> None:
        with (
            patch("app.us_market.ownership_service.sec_provider.fetch_sec_submissions_payload") as submissions,
            patch("app.us_market.ownership_service.sec_provider.fetch_sec_ownership_xml") as xml,
        ):
            contract = read_insider_transactions(self.db, symbol="AAPL")

        self.assertEqual(contract["status"], "missing")
        submissions.assert_not_called()
        xml.assert_not_called()


if __name__ == "__main__":
    unittest.main()
