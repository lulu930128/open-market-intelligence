from __future__ import annotations

from datetime import date, datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, RawFetchResult, SourceRegistry, StockMaster
from app.parsers.tpex_daily_quotes import parse_tpex_daily_quotes_raw
from app.quality.checker import check_raw_data_quality
from app.scripts.seed_sources import DEFAULT_SOURCES
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TPEX_DOMESTIC_COMPANY_PROFILE_SOURCE_NAME,
    TPEX_FOREIGN_COMPANY_PROFILE_SOURCE_NAME,
    TWSE_COMPANY_PROFILE_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)
from app.stocks.bootstrap import bootstrap_stock_master


class StockMasterBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _success_result() -> dict:
        return {
            "fetch_status": "success",
            "parse_status": "success",
            "parsed_count": 1,
            "error_message": None,
        }

    def test_existing_stock_master_skips_external_bootstrap(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.commit()

        with patch("app.stocks.bootstrap.refresh_source") as refresh:
            result = bootstrap_stock_master(self.db)

        refresh.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["stock_count"], 1)

    def test_tpex_bootstrap_source_uses_bounded_openapi_list_contract(self) -> None:
        source_payload = next(
            payload
            for payload in DEFAULT_SOURCES
            if payload["source_name"] == TPEX_DAILY_QUOTES_SOURCE_NAME
        )
        self.assertEqual(
            source_payload["endpoint_url"],
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
        )

        payload = [
            {
                "SecuritiesCompanyCode": "6488",
                "CompanyName": "環球晶",
                "Date": "1150731",
                "Close": "495.5",
                "Change": "3.5",
                "Open": "493",
                "High": "498",
                "Low": "490",
                "TradingShares": "1,234",
                "TransactionAmount": "612,345",
                "TransactionNumber": "456",
            },
            {
                "SecuritiesCompanyCode": "00679B",
                "CompanyName": "元大美債20年",
                "Date": "1150731",
                "Close": "26.68",
            },
            "invalid-row",
        ]
        raw = RawFetchResult(
            id=7,
            source_id=1,
            fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            url=source_payload["endpoint_url"],
            method="GET",
            raw_text=json.dumps(payload, ensure_ascii=False),
        )

        rows, skipped_count = parse_tpex_daily_quotes_raw(raw)

        self.assertEqual(skipped_count, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["stock_id"], "6488")
        self.assertEqual(rows[0]["trade_date"], date(2026, 7, 31))
        self.assertEqual(rows[0]["trade_volume"], 1234)
        self.assertEqual(rows[1]["stock_id"], "00679B")

        source = SourceRegistry(**source_payload)
        self.db.add(source)
        self.db.commit()
        quality = check_raw_data_quality(
            db=self.db,
            source=source,
            raw_text=raw.raw_text,
            status_code=200,
            content_type="application/json",
            content_hash=None,
        )
        self.assertEqual(quality.status, "valid")
        self.assertEqual(quality.check_name, "tpex_openapi_payload")
        self.assertEqual(quality.row_count, 2)

    def test_empty_stock_master_fetches_official_daily_universes(self) -> None:
        self.db.add(
            SourceRegistry(
                **{
                    **next(
                        payload
                        for payload in DEFAULT_SOURCES
                        if payload["source_name"] == TWSE_DAILY_TRADING_SOURCE_NAME
                    ),
                    "endpoint_url": "https://example.test/custom-twse-source",
                }
            )
        )
        self.db.commit()

        def fake_refresh(db, source_id: int) -> dict:
            source = db.query(SourceRegistry).filter(SourceRegistry.id == source_id).one()
            if source.source_name == TWSE_DAILY_TRADING_SOURCE_NAME:
                db.add(
                    StockMaster(
                        stock_id="2330",
                        stock_name="台積電",
                        market="TWSE",
                        instrument_type="stock",
                    )
                )
            elif source.source_name == TPEX_DAILY_QUOTES_SOURCE_NAME:
                db.add(
                    StockMaster(
                        stock_id="6488",
                        stock_name="環球晶",
                        market="TPEx",
                        instrument_type="stock",
                    )
                )
            db.commit()
            return self._success_result()

        progress = Mock()
        with (
            patch("app.stocks.bootstrap.refresh_source", side_effect=fake_refresh) as refresh,
            patch(
                "app.stocks.bootstrap.sync_stocks_from_market_daily",
                return_value={"status": "success", "scanned_count": 2},
            ) as sync,
        ):
            result = bootstrap_stock_master(self.db, progress)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["stock_count"], 2)
        self.assertEqual(result["source_attempt_count"], 2)
        self.assertEqual(result["created_source_count"], len(DEFAULT_SOURCES) - 1)
        self.assertEqual(refresh.call_count, 2)
        sync.assert_called_once_with(self.db)
        self.assertEqual(progress.call_count, 6)

        sources = self.db.query(SourceRegistry).all()
        self.assertEqual(len(sources), len(DEFAULT_SOURCES))
        twse_source = next(
            source
            for source in sources
            if source.source_name == TWSE_DAILY_TRADING_SOURCE_NAME
        )
        self.assertEqual(
            twse_source.endpoint_url,
            "https://example.test/custom-twse-source",
        )

    def test_company_profiles_are_bounded_fallbacks_and_partial_is_visible(self) -> None:
        def fake_refresh(db, source_id: int) -> dict:
            source = db.query(SourceRegistry).filter(SourceRegistry.id == source_id).one()
            if source.source_name == TWSE_COMPANY_PROFILE_SOURCE_NAME:
                db.add(
                    StockMaster(
                        stock_id="2330",
                        stock_name="台積電",
                        market="TWSE",
                        instrument_type="stock",
                    )
                )
                db.commit()
                return self._success_result()

            if source.source_name in {
                TPEX_DOMESTIC_COMPANY_PROFILE_SOURCE_NAME,
                TPEX_FOREIGN_COMPANY_PROFILE_SOURCE_NAME,
            }:
                raise RuntimeError("TPEx provider unavailable")

            return {
                "fetch_status": "error",
                "parse_status": None,
                "parsed_count": None,
                "error_message": "daily provider unavailable",
            }

        with (
            patch("app.stocks.bootstrap.refresh_source", side_effect=fake_refresh),
            patch(
                "app.stocks.bootstrap.sync_stocks_from_market_daily",
                return_value={"status": "success", "scanned_count": 0},
            ),
        ):
            result = bootstrap_stock_master(self.db)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["market_counts"], {"TWSE": 1})
        self.assertEqual(result["source_attempt_count"], 5)
        self.assertEqual(result["source_success_count"], 1)
        self.assertEqual(result["source_error_count"], 4)
        self.assertEqual(len(result["results"]), 5)

    def test_all_provider_failures_leave_empty_master_as_error(self) -> None:
        with (
            patch(
                "app.stocks.bootstrap.refresh_source",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch(
                "app.stocks.bootstrap.sync_stocks_from_market_daily",
                return_value={"status": "success", "scanned_count": 0},
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "did not produce any stock master rows",
            ):
                bootstrap_stock_master(self.db)


if __name__ == "__main__":
    unittest.main()
