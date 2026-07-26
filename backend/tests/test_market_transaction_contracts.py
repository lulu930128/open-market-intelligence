from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.crypto_market.service import persist_crypto_realtime_updates
from app.jp_market.service import upsert_jp_daily_price_records
from app.kr_market.service import upsert_kr_daily_price_records
from app.market import indices
from app.market.tw_futures import (
    TaiwanFuturesFetchError,
    refresh_taiwan_futures_daily_bars,
    refresh_taiwan_futures_quotes,
)
from app.us_market.service import upsert_us_daily_price_records


def _taiwan_index_upsert(db: Session):
    return indices._persist_market_index_daily_stats(
        db,
        index_id="TAIEX",
        market="TWSE",
        rows=[],
        source="transaction_contract_test",
        source_url=None,
    )


def _taiwan_futures_upsert(db: Session):
    with patch("app.market.tw_futures.fetch_taiwan_futures_quotes", return_value=[]):
        return refresh_taiwan_futures_quotes(db, symbols=["TXF"])


def _taiwan_futures_daily_upsert(db: Session):
    with patch("app.market.tw_futures.fetch_taiwan_futures_daily_bars", return_value=[]):
        return refresh_taiwan_futures_daily_bars(
            db,
            symbols=["TXF"],
            start_date=date(2026, 7, 13),
            end_date=date(2026, 7, 13),
            force=True,
        )


TRANSACTION_OWNERS = (
    ("tw", _taiwan_index_upsert),
    ("tw_futures", _taiwan_futures_upsert),
    ("tw_futures_daily", _taiwan_futures_daily_upsert),
    ("us", lambda db: upsert_us_daily_price_records(db, [])),
    ("jp", lambda db: upsert_jp_daily_price_records(db, [])),
    ("kr", lambda db: upsert_kr_daily_price_records(db, [])),
    ("crypto", lambda db: persist_crypto_realtime_updates(db, [])),
)


class MarketTransactionContractTests(unittest.TestCase):
    def test_representative_market_upserts_have_one_commit_owner(self) -> None:
        for market, owner in TRANSACTION_OWNERS:
            with self.subTest(market=market):
                db = MagicMock(spec=Session)

                owner(db)

                db.commit.assert_called_once_with()
                db.rollback.assert_not_called()

    def test_representative_market_upserts_rollback_failed_commit(self) -> None:
        for market, owner in TRANSACTION_OWNERS:
            with self.subTest(market=market):
                db = MagicMock(spec=Session)
                db.commit.side_effect = RuntimeError(f"{market} commit failed")

                with self.assertRaisesRegex(RuntimeError, f"{market} commit failed"):
                    owner(db)

                db.commit.assert_called_once_with()
                db.rollback.assert_called_once_with()

    def test_taiwan_index_coverage_query_does_not_commit(self) -> None:
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = []

        months = indices._existing_index_stat_months(
            db,
            index_id="TAIEX",
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 31),
        )

        self.assertEqual(months, set())
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    def test_taiwan_futures_provider_failure_rolls_back_owner_session(self) -> None:
        db = MagicMock(spec=Session)
        error = TaiwanFuturesFetchError("provider unavailable")

        with patch("app.market.tw_futures.fetch_taiwan_futures_quotes", side_effect=error):
            with self.assertRaisesRegex(TaiwanFuturesFetchError, "provider unavailable"):
                refresh_taiwan_futures_quotes(db, symbols=["TXF"])

        db.commit.assert_not_called()
        db.rollback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
