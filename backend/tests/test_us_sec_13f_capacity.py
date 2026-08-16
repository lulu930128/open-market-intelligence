from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from uuid import uuid4
import zipfile

from app.us_market.sec_ownership.archive import validate_zip_archive, write_bounded_stream
from app.us_market.sec_ownership.form13f import (
    iter_13f_table_rows,
    normalize_cusip,
    parse_reported_value,
    reported_value_unit,
    reported_value_usd,
    parse_section_13f_list,
    table_members,
)
from app.us_market.sec_ownership.form13f_warehouse import (
    build_13f_holdings_parquet,
    query_13f_parquet,
)


class USSec13FArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.created_paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self.created_paths:
            path.unlink(missing_ok=True)

    def _path(self, name: str) -> Path:
        path = Path(__file__).parent / "fixtures" / "us_sec" / f".{uuid4().hex}-{name}"
        self.created_paths.append(path)
        return path

    def test_safe_zip_inventory_and_streaming_tables(self) -> None:
        path = self._path("quarter.zip")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr(
                    "SUBMISSION.tsv",
                    "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
                    "0001\t15-MAY-2026\t13F-HR\t100\t31-MAR-2026\n"
                    "0002\t15-MAY-2026\t13F-HR/A\t100\t31-MAR-2026\n"
                    "0003\t15-MAY-2026\t13F-NT\t200\t31-MAR-2026\n",
                )
                bundle.writestr("COVERPAGE.tsv", "ACCESSION_NUMBER\tREPORTTYPE\n0001\t13F HOLDINGS REPORT\n")
                bundle.writestr("SUMMARYPAGE.tsv", "ACCESSION_NUMBER\tTABLEENTRYTOTAL\tTABLEVALUETOTAL\tISCONFIDENTIALOMITTED\n0001\t2\t1500\tY\n")
                bundle.writestr(
                    "INFOTABLE.tsv",
                    "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
                    "0001\t1\tAPPLE INC\tCOM\t037833100\tBBG000B9XRY4\t1,000\t10\tSH\t\tSOLE\t\t10\t0\t0\n"
                    "0001\t2\tAPPLE INC\tCOM\t037833100\t\t500\t5\tSH\tCALL\tSHARED\t1\t0\t5\t0\n",
                )
        inventory = validate_zip_archive(
            path,
            max_archive_bytes=1_000_000,
            max_uncompressed_bytes=1_000_000,
        )
        self.assertEqual(inventory.entry_count, 4)
        with zipfile.ZipFile(path) as bundle:
            members = table_members(bundle)
            rows = list(iter_13f_table_rows(bundle, members["INFOTABLE"]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(parse_reported_value(rows[0]), 1000)
        self.assertEqual(reported_value_unit(date(2026, 5, 15)), "usd")
        self.assertEqual(reported_value_usd(Decimal("1000"), date(2022, 12, 31)), 1_000_000)
        self.assertEqual(normalize_cusip(rows[0]["CUSIP"]), "037833100")

        output = self._path("holdings.parquet")
        build = build_13f_holdings_parquet(
            archive_path=path,
            output_path=output,
            staging_dir=output.parent,
            dataset_release_id=7,
            period_key="2026Q1",
            source_sha256=inventory.sha256,
            max_archive_bytes=1_000_000,
            max_uncompressed_bytes=1_000_000,
            min_free_space_bytes=0,
        )
        self.assertEqual(build.row_count, 2)
        self.assertEqual(build.distinct_cusip_count, 1)
        self.assertEqual(build.total_reported_value_usd_text, "1500")
        aggregates = query_13f_parquet(
            [output],
            "SELECT cusip, sum(reported_value_usd)::VARCHAR AS value FROM holdings GROUP BY cusip",
        )
        self.assertEqual(aggregates, [{"cusip": "037833100", "value": "1500"}])

    def test_legacy_short_cusip_is_retained_as_quarantined_raw_evidence(self) -> None:
        path = self._path("legacy-short-cusip.zip")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "SUBMISSION.tsv",
                "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
                "0001\t15-MAY-2016\t13F-HR\t100\t31-MAR-2016\n",
            )
            bundle.writestr(
                "COVERPAGE.tsv",
                "ACCESSION_NUMBER\tREPORTTYPE\n0001\t13F HOLDINGS REPORT\n",
            )
            bundle.writestr(
                "SUMMARYPAGE.tsv",
                "ACCESSION_NUMBER\tTABLEENTRYTOTAL\tTABLEVALUETOTAL\n0001\t1\t1000\n",
            )
            bundle.writestr(
                "INFOTABLE.tsv",
                "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
                "0001\t1\tAPPLE INC\tCOM\t37833100 \t\t1000\t10\tSH\t\tSOLE\t\t10\t0\t0\n",
            )
        inventory = validate_zip_archive(
            path,
            max_archive_bytes=1_000_000,
            max_uncompressed_bytes=1_000_000,
        )
        output = self._path("legacy-short-cusip.parquet")
        build = build_13f_holdings_parquet(
            archive_path=path,
            output_path=output,
            staging_dir=output.parent,
            dataset_release_id=8,
            period_key="2016Q1",
            source_sha256=inventory.sha256,
            max_archive_bytes=1_000_000,
            max_uncompressed_bytes=1_000_000,
            min_free_space_bytes=0,
        )

        self.assertEqual(build.row_count, 1)
        self.assertEqual(build.invalid_cusip_count, 1)
        rows = query_13f_parquet(
            [output],
            "SELECT cusip_raw_text, cusip, issue_code FROM holdings",
        )
        self.assertEqual(rows[0]["cusip_raw_text"], "37833100")
        self.assertIsNone(rows[0]["cusip"])
        self.assertEqual(rows[0]["issue_code"], "US13F001_invalid_cusip")

    def test_zip_slip_and_oversize_download_fail_closed(self) -> None:
        unsafe = self._path("unsafe.zip")
        with zipfile.ZipFile(unsafe, "w") as bundle:
            bundle.writestr("../outside.tsv", "x")
        with self.assertRaisesRegex(ValueError, "Unsafe ZIP"):
            validate_zip_archive(
                unsafe,
                max_archive_bytes=1_000_000,
                max_uncompressed_bytes=1_000_000,
            )
        bounded = self._path("bounded.zip")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            write_bounded_stream([b"123", b"456"], bounded, max_bytes=5)
        self.assertFalse(bounded.with_name(f"{bounded.name}.part").exists())

    def test_fixed_width_official_list_keeps_cusip_identity(self) -> None:
        line = f"{'037833100':<9}{'*':1}{'APPLE INC':<30}{'COM':<27}{'*A*':<3}{'':<9}E"
        parsed = parse_section_13f_list(line)
        self.assertIn("037833100", parsed)
        self.assertTrue(parsed["037833100"].option_indicator)
        self.assertEqual(parsed["037833100"].status, "added")


if __name__ == "__main__":
    unittest.main()
