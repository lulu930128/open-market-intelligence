from __future__ import annotations

from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
import zipfile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Base,
    ProviderEvent,
    USSec13FFiling,
    USSec13FManager,
    USSec13FOtherManager,
    USSec13FSymbolQuarter,
    USSec13FWarehousePartition,
    USSecDatasetRelease,
    USSecIngestionCheckpoint,
    USSecurityIdentifierMap,
    USStockMaster,
)
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)
from app.us_market.ownership_13f_analytics import (
    get_13f_symbol_contract,
    rebuild_13f_symbol_quarter_projections,
)
from app.us_market.ownership_13f_mapping import _candidate_cusips, sync_13f_identifier_mappings
from app.us_market.ownership_13f_service import ingest_13f_release


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "us_sec"


def _write_release(path: Path, *, invalid_value: bool = False) -> None:
    value = "not-a-number" if invalid_value else "1000"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "SUBMISSION.tsv",
            "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
            "0001\t15-MAY-2026\t13F-HR\t100\t31-MAR-2026\n"
            "0002\t16-MAY-2026\t13F-HR/A\t100\t31-MAR-2026\n"
            "0003\t17-MAY-2026\t13F-NT\t200\t31-MAR-2026\n",
        )
        bundle.writestr(
            "COVERPAGE.tsv",
            "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\tFILINGMANAGER_NAME\tFILINGMANAGER_STREET1\tFILINGMANAGER_STREET2\tFILINGMANAGER_CITY\tFILINGMANAGER_STATEORCOUNTRY\tFILINGMANAGER_ZIPCODE\tREPORTTYPE\tFORM13FFILENUMBER\n"
            "0001\t31-MAR-2026\tN\t\t\tExample Manager\t1 Main St\t\tNew York\tNY\t10001\t13F HOLDINGS REPORT\t028-00001\n"
            "0002\t31-MAR-2026\tY\t1\tRESTATEMENT\tExample Manager\t1 Main St\t\tNew York\tNY\t10001\t13F HOLDINGS REPORT\t028-00001\n"
            "0003\t31-MAR-2026\tN\t\t\tNotice Manager\t2 Main St\t\tBoston\tMA\t02101\t13F NOTICE\t028-00002\n",
        )
        bundle.writestr(
            "SUMMARYPAGE.tsv",
            "ACCESSION_NUMBER\tOTHERINCLUDEDMANAGERSCOUNT\tTABLEENTRYTOTAL\tTABLEVALUETOTAL\tISCONFIDENTIALOMITTED\n"
            "0001\t0\t1\t1000\tN\n"
            "0002\t1\t1\t1200\tY\n"
            "0003\t0\t0\t0\tN\n",
        )
        bundle.writestr(
            "OTHERMANAGER2.tsv",
            "ACCESSION_NUMBER\tSEQUENCENUMBER\tCIK\tFORM13FFILENUMBER\tNAME\n"
            "0002\t1\t300\t028-00003\tIncluded Manager\n"
            "0002\t1\t301\t028-00004\tSecond Included Manager\n",
        )
        bundle.writestr(
            "INFOTABLE.tsv",
            "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
            f"0001\t1\tAPPLE INC\tCOM\t037833100\tBBG000B9XRY4\t{value}\t10\tSH\t\tSOLE\t\t10\t0\t0\n"
            "0002\t2\tAPPLE INC\tCOM\t037833100\tBBG000B9XRY4\t1200\t12\tSH\t\tSOLE\t1\t12\t0\t0\n",
        )


class USSec13FEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                asset_type="stock",
                listing_source="test",
                cik="0000320193",
                is_test_issue=False,
                is_active=True,
            )
        )
        self.db.commit()
        self.root = FIXTURE_ROOT / f".{uuid4().hex}-13f-engine"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_ingestion_promotes_partition_and_preserves_filing_semantics(self) -> None:
        archive = self.root / "release.zip"
        _write_release(archive)
        warehouse = self.root / "warehouse"
        with (
            patch.object(settings, "us_sec_13f_warehouse_path", warehouse),
            patch.object(settings, "us_sec_ownership_min_free_space_gb", 0),
            patch.object(settings, "us_sec_13f_storage_budget_gb", 1),
        ):
            result = ingest_13f_release(
                self.db,
                period_key="2026Q1",
                source_url="https://www.sec.gov/files/dera/data/form-13f/release.zip",
                archive_path=archive,
            )
            replay = ingest_13f_release(
                self.db,
                period_key="2026Q1",
                source_url="https://www.sec.gov/files/dera/data/form-13f/release.zip",
                archive_path=archive,
            )

        self.assertEqual(result["status"], "current")
        self.assertEqual(result["row_count"], 2)
        self.assertTrue(replay["idempotent"])
        self.assertEqual(self.db.query(USSecDatasetRelease).count(), 1)
        partition = self.db.query(USSec13FWarehousePartition).one()
        self.assertTrue(partition.is_current)
        self.assertTrue(Path(partition.holdings_path).is_file())
        self.assertEqual(self.db.query(USSec13FManager).count(), 2)
        self.assertEqual(self.db.query(USSec13FOtherManager).count(), 2)
        statuses = {
            row.accession_number: (row.effective_status, row.supersedes_accession_number)
            for row in self.db.query(USSec13FFiling).all()
        }
        self.assertEqual(statuses["0001"], ("superseded", None))
        self.assertEqual(statuses["0002"], ("effective_base", "0001"))
        self.assertEqual(statuses["0003"], ("notice_only", None))
        checkpoint = self.db.query(USSecIngestionCheckpoint).one()
        self.assertEqual(checkpoint.status, "completed")
        self.assertEqual(checkpoint.processed_count, 2)
        self.assertEqual(self.db.query(ProviderEvent).filter(ProviderEvent.status == "success").count(), 1)

        with patch(
            "app.us_market.ownership_13f_mapping.fetch_openfigi_mappings",
            return_value=(
                [
                    {
                        "data": [
                            {
                                "figi": "BBG000B9XRY4",
                                "compositeFIGI": "BBG000B9XRY4",
                                "shareClassFIGI": "BBG001S5N8V8",
                                "ticker": "AAPL",
                                "exchCode": "US",
                                "marketSector": "Equity",
                                "securityType": "Common Stock",
                                "securityType2": "Common Stock",
                            },
                            {
                                "figi": "BBG000DGZJ27",
                                "compositeFIGI": "BBG000DGZJ27",
                                "shareClassFIGI": "BBG001S5N8V8",
                                "ticker": "APC",
                                "exchCode": "GR",
                                "marketSector": "Equity",
                                "securityType": "Common Stock",
                                "securityType2": "Common Stock",
                            },
                        ]
                    }
                ],
                "https://api.openfigi.com/v3/mapping",
            ),
        ):
            mapping = sync_13f_identifier_mappings(
                self.db,
                cusips=["037833100"],
                max_identifiers=1,
            )
        self.assertEqual(mapping["status_counts"], {"approved": 1})
        self.assertEqual(self.db.query(USSecurityIdentifierMap).one().symbol, "AAPL")
        projection = rebuild_13f_symbol_quarter_projections(self.db, symbols=["AAPL"])
        self.assertEqual(projection["projection_count"], 1)
        contract = get_13f_symbol_contract(self.db, symbol="AAPL")
        self.assertEqual(contract["status"], "current")
        self.assertEqual(contract["summary"]["report_quarter"], "2026Q1")
        self.assertEqual(contract["summary"]["reported_long_value_usd"], "1200")
        self.assertEqual(contract["managers"][0]["manager_name"], "Example Manager")

        stored_projection = self.db.query(USSec13FSymbolQuarter).one()
        stored_projection.mapping_row_coverage = 0.0
        stored_projection.mapping_value_coverage = 0.0
        stored_projection.unresolved_row_count = 2
        stored_projection.unresolved_value_usd_text = "1200"
        self.db.commit()
        self.db.expunge(stored_projection)

        refreshed_projection = rebuild_13f_symbol_quarter_projections(
            self.db,
            symbols=["AAPL"],
        )
        self.assertEqual(refreshed_projection["coverage"]["basis"], "warehouse_scan")
        self.assertEqual(refreshed_projection["coverage"]["row_coverage"], 1.0)
        rebuilt_row = self.db.query(USSec13FSymbolQuarter).one()
        self.assertEqual(rebuilt_row.mapping_row_coverage, 1.0)
        self.assertEqual(rebuilt_row.unresolved_row_count, 0)

    def test_failed_new_release_retains_prior_current_partition(self) -> None:
        valid = self.root / "valid.zip"
        invalid = self.root / "invalid.zip"
        _write_release(valid)
        _write_release(invalid, invalid_value=True)
        warehouse = self.root / "warehouse"
        with (
            patch.object(settings, "us_sec_13f_warehouse_path", warehouse),
            patch.object(settings, "us_sec_ownership_min_free_space_gb", 0),
            patch.object(settings, "us_sec_13f_storage_budget_gb", 1),
        ):
            first = ingest_13f_release(
                self.db,
                period_key="2026Q1",
                source_url="https://www.sec.gov/files/dera/data/form-13f/valid.zip",
                archive_path=valid,
            )
            with self.assertRaisesRegex(ValueError, "invalid reported-value"):
                ingest_13f_release(
                    self.db,
                    period_key="2026Q1",
                    source_url="https://www.sec.gov/files/dera/data/form-13f/invalid.zip",
                    archive_path=invalid,
                )

        current = (
            self.db.query(USSec13FWarehousePartition)
            .filter(USSec13FWarehousePartition.is_current.is_(True))
            .one()
        )
        self.assertEqual(current.id, first["partition_id"])
        self.assertEqual(
            self.db.query(USSecDatasetRelease).filter(USSecDatasetRelease.status == "failed").count(),
            1,
        )

    def test_full_market_mapping_slice_excludes_checked_identifiers(self) -> None:
        self.db.add(
            USSecurityIdentifierMap(
                identifier_type="ID_CUSIP",
                identifier_value="037833100",
                mapping_version="openfigi.v3",
                mapping_source="openfigi",
                status="approved",
                confidence="exact",
                symbol="AAPL",
            )
        )
        self.db.commit()
        with patch(
            "app.us_market.ownership_13f_mapping.query_13f_parquet_context",
            return_value=[{"cusip": "594918104"}],
        ) as query:
            requested = _candidate_cusips(
                self.db,
                cusips=None,
                limit=25,
                mapping_version="openfigi.v3",
                refresh=False,
            )

        self.assertEqual(requested, ["594918104"])
        self.assertEqual(
            query.call_args.kwargs["identifier_mappings"],
            [("037833100", "checked")],
        )
        self.assertEqual(query.call_args.kwargs["parameters"], [25])

    def test_authenticated_mapping_paces_batches(self) -> None:
        cusips = [f"{index:09d}" for index in range(101)]
        clock = Mock()
        clock.monotonic.side_effect = [0.0, 0.1, 0.26]

        def response_for(jobs, **_kwargs):
            return (
                [{"warning": "No identifier found."} for _ in jobs],
                "https://api.openfigi.com/v3/mapping",
            )

        with (
            patch.object(settings, "openfigi_api_key", "configured"),
            patch(
                "app.us_market.ownership_13f_mapping._candidate_cusips",
                return_value=cusips,
            ),
            patch(
                "app.us_market.ownership_13f_mapping.fetch_openfigi_mappings",
                side_effect=response_for,
            ) as fetch,
            patch("app.us_market.ownership_13f_mapping.time", clock),
        ):
            result = sync_13f_identifier_mappings(
                self.db,
                cusips=cusips,
                max_identifiers=len(cusips),
            )

        self.assertEqual(fetch.call_count, 2)
        clock.sleep.assert_called_once_with(0.16)
        self.assertEqual(result["processed_count"], 101)
        self.assertEqual(result["status_counts"], {"unmapped": 101})
        self.assertEqual(result["retry_count"], 0)

    def test_mapping_retries_one_rate_limited_batch(self) -> None:
        clock = Mock()
        clock.monotonic.return_value = 0.0
        context = ProviderRequestContext(
            market="us",
            provider="openfigi",
            resource="sec_13f_identifier_mapping",
            target="jobs:1",
        )
        rate_limited = ProviderHttpError(
            "OpenFIGI rate limited.",
            failure=ProviderHttpFailure(
                context=context,
                status="rate_limited",
                source_url="https://api.openfigi.com/v3/mapping",
                http_status_code=429,
                rate_limited=True,
                retry_after_seconds=2,
            ),
        )
        success = (
            [{"warning": "No identifier found."}],
            "https://api.openfigi.com/v3/mapping",
        )
        with (
            patch.object(settings, "openfigi_api_key", "configured"),
            patch(
                "app.us_market.ownership_13f_mapping._candidate_cusips",
                return_value=["000000001"],
            ),
            patch(
                "app.us_market.ownership_13f_mapping.fetch_openfigi_mappings",
                side_effect=[rate_limited, success],
            ) as fetch,
            patch("app.us_market.ownership_13f_mapping.time", clock),
        ):
            result = sync_13f_identifier_mappings(
                self.db,
                cusips=["000000001"],
                max_identifiers=1,
            )

        self.assertEqual(fetch.call_count, 2)
        clock.sleep.assert_called_once_with(2.0)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
