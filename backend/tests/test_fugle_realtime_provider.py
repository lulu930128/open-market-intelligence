from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    RawFetchResult,
    StockMaster,
    TaiwanCurrentIndexSnapshot,
    TaiwanStockQuoteSnapshot,
)

from app.market.providers.fugle_realtime import (
    FUGLE_TAIEX_SYMBOL,
    FugleRealtimeBuffer,
    FugleSubscriptionAllocator,
    fugle_bar_acquisition,
    fugle_index_acquisition,
    fugle_quote_acquisition,
)
from app.market.providers.fugle_realtime_runtime import (
    FugleCanonicalMaterializer,
    FugleRealtimeRuntime,
)
from app.market.providers.tw_current_market import (
    CurrentIndexAdapter,
    CurrentMarketProviderPayload,
)
from app.market.public_quote_platform import build_taiwan_public_quote_requirement
from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TW_CURRENT_INDEX_DATASET_ID,
    TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,
    current_source_binding,
)
from app.market.tw_current_market_platform import (
    build_taiwan_current_requirement,
    refresh_taiwan_current_index,
)
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    QuantityUnit,
)
from app.market_data.integration_contracts import RequestBounds
from app.market_data.policies import RealtimePolicy


NOW = datetime(
    2026,
    8,
    28,
    10,
    15,
    31,
    tzinfo=timezone(timedelta(hours=8)),
)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _index_message(*, value: float = 35276.44, micros: int = 1787892930000000) -> dict:
    return {
        "event": "data",
        "data": {
            "symbol": FUGLE_TAIEX_SYMBOL,
            "type": "INDEX",
            "exchange": "TWSE",
            "index": value,
            "time": micros,
        },
        "id": "index-channel",
        "channel": "indices",
    }


def _aggregate_message() -> dict:
    return {
        "event": "data",
        "data": {
            "date": "2026-08-28",
            "type": "EQUITY",
            "exchange": "TWSE",
            "market": "TSE",
            "symbol": "2330",
            "previousClose": 1190,
            "openPrice": 1200,
            "highPrice": 1225,
            "lowPrice": 1195,
            "closePrice": 1220,
            "total": {
                "tradeValue": 31019803000,
                "tradeVolume": 54538,
                "transaction": 9530,
                "time": 1787892930000000,
            },
            "lastTrade": {
                "price": 1220,
                "size": 4778,
                "time": 1787892930000000,
                "serial": 6652422,
            },
            "serial": 6652422,
            "lastUpdated": 1787892930000000,
        },
        "id": "aggregate-channel",
        "channel": "aggregates",
    }


def _candle_message() -> dict:
    return {
        "event": "data",
        "data": {
            "symbol": "2330",
            "type": "EQUITY",
            "exchange": "TWSE",
            "market": "TSE",
            "date": "2026-08-28T10:15:00.000+08:00",
            "open": 1215,
            "high": 1225,
            "low": 1210,
            "close": 1220,
            "volume": 4778,
            "average": 1218.5,
        },
        "id": "candle-channel",
        "channel": "candles",
    }


def test_allocator_keeps_one_connection_budget_and_switches_stock_two_phase() -> None:
    allocator = FugleSubscriptionAllocator(maximum=5)
    assert allocator.snapshot()["desired_count"] == 1
    allocator.set_active_stock("2330")
    desired = allocator.desired()
    assert {(item.channel, item.symbol) for item in desired} == {
        ("indices", "IR0001"),
        ("aggregates", "2330"),
        ("candles", "2330"),
    }
    for index, item in enumerate(desired):
        allocator.acknowledge_subscribed(
            channel_id=f"channel-{index}",
            channel=item.channel,
            symbol=item.symbol,
        )
    assert allocator.snapshot()["bound_count"] == 3

    allocator.set_active_stock("2317")
    first = allocator.commands()
    assert len(first.unsubscribe_ids) == 2
    assert first.subscribe == ()
    allocator.acknowledge_unsubscribed(first.unsubscribe_ids)
    second = allocator.commands()
    assert {(item.channel, item.symbol) for item in second.subscribe} == {
        ("aggregates", "2317"),
        ("candles", "2317"),
    }


def test_buffer_rejects_duplicate_out_of_order_and_malformed_messages() -> None:
    buffer = FugleRealtimeBuffer()
    message = _index_message()
    assert buffer.ingest(message, received_at=NOW)
    assert not buffer.ingest(json.dumps(message), received_at=NOW)
    assert not buffer.ingest(
        _index_message(value=35000, micros=1787892929000000),
        received_at=NOW,
    )
    assert not buffer.ingest({"event": "data", "channel": "indices", "data": {}}, received_at=NOW)
    assert buffer.metrics() == {
        "latest_count": 1,
        "accepted_count": 1,
        "duplicate_count": 1,
        "out_of_order_count": 1,
        "malformed_count": 1,
    }


def test_official_examples_convert_to_existing_canonical_contracts() -> None:
    buffer = FugleRealtimeBuffer()
    for message in (_index_message(), _aggregate_message(), _candle_message()):
        assert buffer.ingest(message, received_at=NOW)

    index_requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_INDEX_DATASET_ID,
        capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        scope_key="TAIEX",
        requested_at=NOW,
        policy=RealtimePolicy.PREFER_LIVE,
        acquiring=True,
    )
    index = fugle_index_acquisition(
        buffer.latest("indices", "IR0001"),  # type: ignore[arg-type]
        index_requirement,
        previous_close=Decimal("35000"),
    )
    assert index.observations[0].close_value == Decimal("35276.44")
    assert index.observations[0].price_change == Decimal("276.44")
    assert index.observations[0].trade_volume is None
    assert index.receipts[0].method == "WEBSOCKET"

    quote_requirement = build_taiwan_public_quote_requirement(
        instrument=_instrument(),
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=NOW,
        bounds=RequestBounds(
            max_provider_attempts=0,
            max_external_calls=0,
            max_subscriptions=1,
            timeout_seconds=30,
            max_candidates=3,
            max_rows=1,
        ),
    )
    quote = fugle_quote_acquisition(
        buffer.latest("aggregates", "2330"),  # type: ignore[arg-type]
        quote_requirement,
    ).observations[0]
    assert quote.last_trade_price == Decimal("1220")
    assert quote.last_trade_quantity is not None
    assert quote.last_trade_quantity.value == Decimal("4778000")
    assert quote.last_trade_quantity.original_unit is QuantityUnit.BOARD_LOT
    assert quote.cumulative_quantity is not None
    assert quote.cumulative_quantity.value == Decimal("54538000")

    bar_requirement = build_taiwan_intraday_requirement(
        instrument=_instrument(),
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=NOW,
        acquiring=True,
    )
    bar = fugle_bar_acquisition(
        buffer.latest("candles", "2330"),  # type: ignore[arg-type]
        bar_requirement,
    ).observations[0]
    assert bar.volume is not None
    assert bar.volume.value == Decimal("4778000")
    assert bar.volume.original_value == Decimal("4778")
    assert bar.volume.original_unit is QuantityUnit.BOARD_LOT
    assert bar.end_at - bar.start_at == __import__("datetime").timedelta(minutes=1)


def test_materializer_persists_each_stream_hash_once_and_rereads() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
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
    try:
        binding = current_source_binding(
            provider="twse_mis",
            source="twse_mis_index_snapshot",
            capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        )
        assert binding is not None
        seed = CurrentIndexAdapter(
            binding,
            lambda _scope, _timeout: CurrentMarketProviderPayload(
                payload={
                    "as_of": NOW.isoformat(),
                    "trade_date": NOW.date().isoformat(),
                    "close": 35_000,
                    "previous_close": 34_900,
                    "volume": 1,
                    "trade_value": 1,
                    "transaction_count": 1,
                },
                status="available",
                url="https://example.test/mis-index",
            ),
            clock=lambda: NOW,
        )
        refresh_taiwan_current_index(
            db,
            index_id="TAIEX",
            requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,),
            acquisition=TaiwanCurrentIndexAcquisitionExecutor((seed,)),
        )

        stream_time = int(NOW.astimezone(timezone.utc).timestamp() * 1_000_000)
        buffer = FugleRealtimeBuffer()
        assert buffer.ingest(_index_message(micros=stream_time), received_at=NOW)
        aggregate = _aggregate_message()
        aggregate["data"]["lastTrade"]["time"] = stream_time
        aggregate["data"]["total"]["time"] = stream_time
        aggregate["data"]["lastUpdated"] = stream_time
        assert buffer.ingest(aggregate, received_at=NOW)
        assert buffer.ingest(_candle_message(), received_at=NOW)

        materializer = FugleCanonicalMaterializer(buffer)
        first = materializer.materialize(db, active_stock="2330")
        assert set(first) == {"index", "quote", "bars"}
        assert first["index"]["selected_provider"] == "fugle_marketdata", first
        assert first["quote"]["selected_provider"] == "fugle_marketdata"
        assert first["bars"]["selected_provider"] == "fugle_marketdata"
        assert db.query(TaiwanCurrentIndexSnapshot).count() == 2
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
        assert db.query(MarketIntradayBar).count() == 1
        assert db.query(RawFetchResult).count() == 4

        second = materializer.materialize(db, active_stock="2330")
        assert second == {}
        assert db.query(RawFetchResult).count() == 4
    finally:
        db.close()
        engine.dispose()


def test_index_materialization_retries_same_hash_when_seed_is_missing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        buffer = FugleRealtimeBuffer()
        assert buffer.ingest(_index_message(), received_at=NOW)
        materializer = FugleCanonicalMaterializer(buffer)

        first = materializer.materialize(db, active_stock=None)
        second = materializer.materialize(db, active_stock=None)

        expected = {
            "index": {
                "status": "pending",
                "limitation": "FUGLE_INDEX_PREVIOUS_CLOSE_SEED_MISSING",
            }
        }
        assert first == expected
        assert second == expected
        assert db.query(RawFetchResult).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_runtime_reconciliation_does_not_duplicate_pending_subscriptions() -> None:
    class Socket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send(self, message: str) -> None:
            self.sent.append(json.loads(message))

    async def scenario() -> None:
        runtime = FugleRealtimeRuntime(
            api_key="test",
            active_stock="2330",
        )
        socket = Socket()
        await runtime._send_commands(socket)  # noqa: SLF001 - lifecycle contract test
        await runtime._send_commands(socket)  # noqa: SLF001
        assert len(socket.sent) == 3
        assert all(item["event"] == "subscribe" for item in socket.sent)
        for index, item in enumerate(socket.sent):
            runtime._handle_control(  # noqa: SLF001
                {
                    "event": "subscribed",
                    "data": {
                        "id": f"channel-{index}",
                        **item["data"],
                    },
                }
            )

        runtime.set_active_stock("2317")
        await runtime._send_commands(socket)  # noqa: SLF001
        await runtime._send_commands(socket)  # noqa: SLF001
        unsubscribe = socket.sent[-1]
        assert unsubscribe["event"] == "unsubscribe"
        assert len(unsubscribe["data"]["ids"]) == 2
        assert len(socket.sent) == 4

        runtime._handle_control(  # noqa: SLF001
            {
                "event": "unsubscribed",
                "data": [
                    {"id": channel_id}
                    for channel_id in unsubscribe["data"]["ids"]
                ],
            }
        )
        await runtime._send_commands(socket)  # noqa: SLF001
        new_subscriptions = socket.sent[-2:]
        assert {
            (item["data"]["channel"], item["data"]["symbol"])
            for item in new_subscriptions
        } == {("aggregates", "2317"), ("candles", "2317")}

    asyncio.run(scenario())
