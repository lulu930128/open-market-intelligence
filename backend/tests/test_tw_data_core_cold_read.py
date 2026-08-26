from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import (
    TaiwanOfficialDailyPlatform,
    read_taiwan_official_daily,
)
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.official_breadth_platform import read_taiwan_official_breadth
from app.market.official_index_acquisition import TaiwanOfficialIndexAcquisitionExecutor
from app.market.official_index_platform import (
    TaiwanOfficialIndexCandidateReader,
    TaiwanOfficialIndexPlatform,
    read_taiwan_official_index,
)
from app.market.official_index_repository import TaiwanOfficialIndexRepository
from app.market.official_index_transaction import TaiwanOfficialIndexTransaction
from app.market.providers.tw_official_daily import TWSE_DAILY_RESOURCE_ID
from app.market.providers.tw_official_index import (
    TWSE_INDEX_RESOURCE_ID,
    TW_INDEX_DATASET_ID,
)
from app.market.providers.tw_public_quote import TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR
from app.market.public_quote_acquisition import TaiwanPublicQuoteAcquisitionExecutor
from app.market.public_quote_platform import (
    acquire_taiwan_public_last_trade_quote,
    read_taiwan_public_last_trade_quote,
)
from app.market.service import list_stock_ohlc_chart_data
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_dashboard_data_core import attach_taiwan_dashboard_data_core
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import (
    DatasetTarget,
    InstrumentTarget,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose, RealtimePolicy


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tw_market_data"
DAILY_DATE = date(2026, 8, 24)
CACHE_REQUESTED_AT = datetime(2026, 8, 25, 2, 31, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int = 200
    url: str = "https://official.example.test/resource"
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(
                self,
                "headers",
                {"content-type": "application/json;charset=UTF-8"},
            )


def _payload(name: str) -> str:
    fixture = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return json.dumps(
        fixture["payload"],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _quote_record() -> tuple[str, datetime]:
    fixture = json.loads(
        (FIXTURE_ROOT / "twse_mis_public_quote_actual_20260825.json").read_text(
            encoding="utf-8"
        )
    )
    record = next(item for item in fixture["records"] if item["stock_id"] == "2330")
    raw_text = base64.b64decode(record["raw_text_base64"]).decode("utf-8")
    return raw_text, datetime.fromisoformat(record["received_at"])


def _daily_refresh() -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="2330",
                instrument_type=InstrumentType.STOCK,
                venue="TWSE",
            )
        ),
        from_date=DAILY_DATE,
        to_date=DAILY_DATE,
        requested_at=datetime(2026, 8, 25, 2, 30, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition="Official daily bar rereads with raw receipt lineage.",
    )


def _index_refresh() -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id=TW_INDEX_DATASET_ID,
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_INDEX_DATASET_ID,
            scope_key="TAIEX",
        ),
        from_date=DAILY_DATE,
        to_date=DAILY_DATE,
        requested_at=datetime(2026, 8, 25, 2, 30, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition="Official index row rereads with raw receipt lineage.",
    )


def test_actual_data_survives_engine_restart_and_cold_platform_read() -> None:
    database_path = (
        Path(__file__).parents[1]
        / f".test-tw-data-core-cold-{uuid4().hex}.sqlite3"
    )
    try:
        database_url = f"sqlite:///{database_path.as_posix()}"
        engine = create_engine(database_url)
        Base.metadata.create_all(bind=engine)
        with Session(engine) as db:
            db.add(
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
            )
            db.commit()

            daily_platform = TaiwanOfficialDailyPlatform(
                reader=TaiwanCompletedDailyCandidateReader(
                    TaiwanOfficialDailyBarRepository(db)
                ),
                transaction=TaiwanOfficialDailyTransaction(db),
                acquisition=TaiwanOfficialDailyAcquisitionExecutor(
                    fetchers={
                        TWSE_DAILY_RESOURCE_ID: lambda _route: FakeResponse(
                            _payload("twse_stock_day_all_excerpt_20260825.json")
                        )
                    },
                    clock=lambda: datetime(
                    2026, 8, 25, 2, 30, tzinfo=timezone.utc
                    ),
                    monotonic=lambda: 10.0,
                ),
            )
            assert daily_platform.refresh_instrument(
                _daily_refresh()
            ).postcondition_satisfied

            index_platform = TaiwanOfficialIndexPlatform(
                reader=TaiwanOfficialIndexCandidateReader(
                    TaiwanOfficialIndexRepository(db)
                ),
                transaction=TaiwanOfficialIndexTransaction(db),
                acquisition=TaiwanOfficialIndexAcquisitionExecutor(
                    fetchers={
                        TWSE_INDEX_RESOURCE_ID: lambda _route: FakeResponse(
                            _payload("twse_fmtqik_20260825.json")
                        )
                    },
                    clock=lambda: datetime(
                    2026, 8, 25, 2, 30, tzinfo=timezone.utc
                    ),
                    monotonic=lambda: 10.0,
                ),
            )
            assert index_platform.refresh_index(
                _index_refresh()
            ).postcondition_satisfied

            raw_quote, received_at = _quote_record()
            quote_result = acquire_taiwan_public_last_trade_quote(
                db,
                stock_id="2330",
                policy=RealtimePolicy.PREFER_LIVE,
                requested_at=datetime(2026, 8, 25, 13, 29, 55, tzinfo=TAIWAN_TZ),
                acquisition=TaiwanPublicQuoteAcquisitionExecutor(
                    fetchers={
                        TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: (
                            lambda _route, _instrument: FakeResponse(raw_quote)
                        )
                    },
                    clock=lambda: received_at,
                ),
            )
            assert quote_result.persistence.committed
        engine.dispose()

        restarted_engine = create_engine(database_url)
        with Session(restarted_engine) as restarted_db:
            daily = read_taiwan_official_daily(
                restarted_db,
                stock_id="2330",
                from_date=DAILY_DATE,
                to_date=DAILY_DATE,
                requested_at=CACHE_REQUESTED_AT,
            )
            index = read_taiwan_official_index(
                restarted_db,
                index_id="TAIEX",
                trade_date=DAILY_DATE,
                requested_at=CACHE_REQUESTED_AT,
            )
            breadth = read_taiwan_official_breadth(
                restarted_db,
                venue="TWSE",
                trade_date=DAILY_DATE,
                requested_at=CACHE_REQUESTED_AT,
            )
            quote = read_taiwan_public_last_trade_quote(
                restarted_db,
                stock_id="2330",
                requested_at=datetime(2026, 8, 25, 13, 29, 56, tzinfo=TAIWAN_TZ),
            )
            chart = list_stock_ohlc_chart_data(
                restarted_db,
                stock_id="2330",
                timeframe="daily",
                bars=1,
                ensure_history=False,
                include_intraday=False,
                to_date=DAILY_DATE,
            )
            dashboard = attach_taiwan_dashboard_data_core(
                restarted_db,
                {
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "breadth": {"scope": "full_market"},
                        }
                    ]
                },
                requested_at=CACHE_REQUESTED_AT,
            )

            for result in (daily, index, breadth, quote):
                assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
            assert daily.acquisition.external_calls == 0
            assert index.acquisition.external_calls == 0
            assert breadth.acquisition.external_calls == 0
            assert quote.acquisition.external_calls == 0
            assert daily.resolved.bars[0].lineage.raw_receipt_id
            assert index.resolved.market_index.lineage.raw_receipt_id
            assert breadth.resolved.breadth.lineage.raw_receipt_id
            assert quote.resolved.quote.lineage.raw_receipt_id
            assert chart["points"][0]["close"] == 2375.0
            dashboard_item = dashboard["indices"][0]
            assert dashboard_item["data_core_projection_scope"] == {
                "official_index": "resolved_data_core",
                "official_breadth": "resolved_data_core",
            }
            assert dashboard_item["official_close_price"] == 44762.32
            assert dashboard_item["breadth"]["total_count"] == 1
        restarted_engine.dispose()
    finally:
        for path in (
            database_path,
            database_path.with_name(f"{database_path.name}-wal"),
            database_path.with_name(f"{database_path.name}-shm"),
        ):
            path.unlink(missing_ok=True)
