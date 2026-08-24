from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    BrokerBranchSnapshotQuality,
    BrokerBranchTradeDaily,
    RawFetchResult,
    SourceRegistry,
)
from app.market import broker_branch
from app.market.broker_branch_quality import (
    BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
    BROKER_BRANCH_COVERAGE_CENSORED,
    BROKER_BRANCH_COVERAGE_COMPLETE,
    BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
    BROKER_BRANCH_COVERAGE_PARTIAL,
    BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE,
    BROKER_BRANCH_FETCH_EMPTY,
    BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH,
    BROKER_BRANCH_FETCH_PROVIDER_FAILURE,
    BROKER_BRANCH_FETCH_SUCCESS,
    NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
    reconcile_nstock_snapshot_quality_from_trade_rows,
    upsert_broker_branch_snapshot_quality,
)


class BrokerBranchSnapshotQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.trade_date = date(2026, 8, 21)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _fetch_result(
        self,
        *,
        trade_date: date | None = None,
        stock_id: str = "2330",
        buy_rows: list[dict] | None = None,
        sell_rows: list[dict] | None = None,
    ) -> broker_branch.BrokerBranchFetchResult:
        payload = {
            "data": {
                "更新日期": (trade_date or self.trade_date).isoformat(),
                "股票代號": stock_id,
                "股票名稱": "台積電",
                "顯示": "買賣超",
                "買超top15": buy_rows or [],
                "賣超top15": sell_rows or [],
            }
        }
        return broker_branch.BrokerBranchFetchResult(
            url="https://example.test/branch?stock_id=2330",
            status_code=200,
            content_type="application/json",
            raw_text=json.dumps(payload, ensure_ascii=False),
            payload=payload,
        )

    @staticmethod
    def _buy_row(*, branch_code: str = "A001") -> dict:
        return {
            "分點代號": branch_code,
            "分點名稱": "測試分點",
            "買張": "10",
            "賣張": "0",
            "買均價": "100.5",
            "賣均價": "0",
            "買超排名": "1",
            "買超": "10",
        }

    def test_success_persists_censored_quality_and_normalizes_zero_side_price(
        self,
    ) -> None:
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            return_value=self._fetch_result(buy_rows=[self._buy_row()]),
        ):
            rows = broker_branch.fetch_and_store_broker_branch_daily(
                self.db,
                stock_id="2330",
                requested_trade_date=self.trade_date,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].buy_avg_price, 100.5)
        self.assertIsNone(rows[0].sell_avg_price)
        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(quality.coverage_mode, "ranked_top_n")
        self.assertEqual(quality.coverage_status, "censored")
        self.assertEqual(quality.fetch_status, "success")
        self.assertEqual(quality.observed_branch_count, 1)
        self.assertEqual(quality.expected_trade_date, self.trade_date)
        self.assertEqual(quality.provider_trade_date, self.trade_date)
        self.assertIsNotNone(quality.raw_result_id)
        self.assertIn(
            "ranked_top_n_absence_is_censored",
            json.loads(quality.warnings_json),
        )

    def test_empty_topn_persists_raw_and_partial_quality(self) -> None:
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            return_value=self._fetch_result(),
        ):
            rows = broker_branch.fetch_and_store_broker_branch_daily(
                self.db,
                stock_id="2330",
                requested_trade_date=self.trade_date,
            )

        self.assertEqual(rows, [])
        self.assertEqual(self.db.query(RawFetchResult).count(), 1)
        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(quality.coverage_status, BROKER_BRANCH_COVERAGE_PARTIAL)
        self.assertEqual(quality.fetch_status, BROKER_BRANCH_FETCH_EMPTY)
        self.assertEqual(quality.observed_branch_count, 0)
        self.assertNotEqual(quality.coverage_status, "ready_empty")

    def test_provider_date_mismatch_is_not_written_as_trade_rows(self) -> None:
        provider_date = date(2026, 8, 20)
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            return_value=self._fetch_result(
                trade_date=provider_date,
                buy_rows=[self._buy_row()],
            ),
        ):
            rows = broker_branch.fetch_and_store_broker_branch_daily(
                self.db,
                stock_id="2330",
                requested_trade_date=self.trade_date,
            )

        self.assertEqual(rows, [])
        self.assertEqual(self.db.query(BrokerBranchTradeDaily).count(), 0)
        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(quality.expected_trade_date, self.trade_date)
        self.assertEqual(quality.provider_trade_date, provider_date)
        self.assertEqual(
            quality.fetch_status,
            BROKER_BRANCH_FETCH_PROVIDER_DATE_MISMATCH,
        )

    def test_provider_failure_persists_quality_without_raw_payload(self) -> None:
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            side_effect=broker_branch.BrokerBranchFetchError(
                "provider unavailable",
                failure_kind="provider_failure",
            ),
        ):
            with self.assertRaises(broker_branch.BrokerBranchFetchError):
                broker_branch.fetch_and_store_broker_branch_daily(
                    self.db,
                    stock_id="2330",
                    requested_trade_date=self.trade_date,
                )

        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(
            quality.coverage_status,
            BROKER_BRANCH_COVERAGE_PROVIDER_FAILURE,
        )
        self.assertEqual(
            quality.fetch_status,
            BROKER_BRANCH_FETCH_PROVIDER_FAILURE,
        )
        self.assertIsNone(quality.raw_result_id)

    def test_invalid_identity_is_not_silently_canonicalized_by_name(self) -> None:
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            return_value=self._fetch_result(
                buy_rows=[self._buy_row(branch_code="")]
            ),
        ):
            with self.assertRaises(broker_branch.BrokerBranchFetchError):
                broker_branch.fetch_and_store_broker_branch_daily(
                    self.db,
                    stock_id="2330",
                    requested_trade_date=self.trade_date,
                )

        self.assertEqual(self.db.query(BrokerBranchTradeDaily).count(), 0)
        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(quality.coverage_status, "invalid")
        self.assertIn("no_valid_branch_identity", json.loads(quality.warnings_json))

    def test_force_refresh_updates_one_selected_quality_row(self) -> None:
        fetch_result = self._fetch_result(buy_rows=[self._buy_row()])
        with patch.object(
            broker_branch,
            "_fetch_nstock_branch_top15",
            return_value=fetch_result,
        ):
            broker_branch.fetch_and_store_broker_branch_daily(
                self.db,
                stock_id="2330",
                requested_trade_date=self.trade_date,
            )
            broker_branch.fetch_and_store_broker_branch_daily(
                self.db,
                stock_id="2330",
                requested_trade_date=self.trade_date,
                force=True,
            )

        self.assertEqual(self.db.query(BrokerBranchSnapshotQuality).count(), 1)
        self.assertEqual(self.db.query(BrokerBranchTradeDaily).count(), 1)
        self.assertEqual(self.db.query(RawFetchResult).count(), 2)

    def test_reconcile_existing_trade_rows_is_bounded_and_idempotent(self) -> None:
        source = SourceRegistry(
            source_name=broker_branch.NSTOCK_BRANCH_SOURCE_NAME,
            source_type="http_api",
            category="broker_branch_trade",
        )
        raw = RawFetchResult(
            source=source,
            url="https://example.test/branch",
            method="GET",
        )
        self.db.add_all([source, raw])
        self.db.flush()
        self.db.add(
            BrokerBranchTradeDaily(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=self.trade_date,
                stock_id="2330",
                stock_name="台積電",
                branch_code="A001",
                branch_name="測試分點",
                net_lots=10,
            )
        )
        self.db.commit()

        first = reconcile_nstock_snapshot_quality_from_trade_rows(
            self.db,
            source_name=broker_branch.NSTOCK_BRANCH_SOURCE_NAME,
            expected_trade_date=self.trade_date,
            max_stocks=1,
        )
        self.db.commit()
        second = reconcile_nstock_snapshot_quality_from_trade_rows(
            self.db,
            source_name=broker_branch.NSTOCK_BRANCH_SOURCE_NAME,
            expected_trade_date=self.trade_date,
            max_stocks=1,
        )

        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["skipped_count"], 1)
        quality = self.db.query(BrokerBranchSnapshotQuality).one()
        self.assertEqual(quality.coverage_status, BROKER_BRANCH_COVERAGE_CENSORED)
        self.assertIn(
            "reconciled_from_existing_trade_rows",
            json.loads(quality.warnings_json),
        )

    def test_ranked_topn_cannot_claim_complete_absence(self) -> None:
        source = SourceRegistry(
            source_name="test",
            source_type="http_api",
            category="broker_branch_trade",
        )
        self.db.add(source)
        self.db.flush()

        with self.assertRaisesRegex(ValueError, "cannot claim complete"):
            upsert_broker_branch_snapshot_quality(
                self.db,
                source_id=source.id,
                stock_id="2330",
                expected_trade_date=self.trade_date,
                provider_trade_date=self.trade_date,
                fetched_at=None,
                coverage_mode=BROKER_BRANCH_COVERAGE_MODE_RANKED_TOP_N,
                buy_rank_limit=15,
                sell_rank_limit=15,
                observed_branch_count=0,
                absence_semantics=BROKER_BRANCH_ABSENCE_UNKNOWN_NOT_RANKED,
                coverage_status=BROKER_BRANCH_COVERAGE_COMPLETE,
                fetch_status=BROKER_BRANCH_FETCH_SUCCESS,
                source_contract_version=NSTOCK_BROKER_BRANCH_CONTRACT_VERSION,
            )


if __name__ == "__main__":
    unittest.main()
