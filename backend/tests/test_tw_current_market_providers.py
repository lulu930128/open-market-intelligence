from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.market.providers import (
    twse_mis_current_breadth,
    twse_mis_current_index,
    yahoo_current_index,
)


TAIPEI = timezone(timedelta(hours=8))


def test_twse_mis_current_index_provider_parses_snapshot(monkeypatch) -> None:
    calls: list[tuple] = []

    def fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "d": "20260826",
            "t": "10:15:30",
            "z": "24100.5",
            "y": "24000",
            "o": "24020",
            "h": "24120",
            "l": "23980",
        }

    monkeypatch.setattr(
        twse_mis_current_index.twse_mis,
        "fetch_index_message",
        fetch,
    )
    result = twse_mis_current_index.read_twse_mis_current_index("TAIEX", 7)

    assert result.status == "available"
    assert result.payload is not None
    assert result.payload["provider"] == "twse_mis"
    assert result.payload["trade_date"] == "2026-08-26"
    assert result.payload["points"][0]["price"] == 24_100.5
    assert calls[0][0] == ("tse_t00.tw",)
    assert calls[0][1]["timeout_seconds"] == 7


def test_yahoo_current_index_provider_parses_chart(monkeypatch) -> None:
    observed = datetime(2026, 8, 26, 10, 15, tzinfo=TAIPEI)

    def fetch(**kwargs):
        assert kwargs["symbol"] == "^TWOII"
        assert kwargs["range_value"] == "1d"
        assert kwargs["interval"] == "1m"
        assert kwargs["timeout_seconds"] == 9
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "gmtoffset": 28800,
                            "chartPreviousClose": 300.0,
                        },
                        "timestamp": [int(observed.timestamp())],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [301.0],
                                    "high": [303.0],
                                    "low": [300.5],
                                    "close": [302.5],
                                    "volume": [123],
                                }
                            ]
                        },
                    }
                ]
            }
        }

    monkeypatch.setattr(
        yahoo_current_index.yahoo,
        "fetch_index_chart_payload",
        fetch,
    )
    result = yahoo_current_index.read_yahoo_current_index("TPEX", 9)

    assert result.status == "available"
    assert result.payload is not None
    assert result.payload["provider"] == "yahoo_chart"
    assert result.payload["previous_close"] == 300.0
    assert result.payload["points"][0]["price"] == 302.5


def test_twse_mis_current_breadth_keeps_partition_disjoint(monkeypatch) -> None:
    twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()
    codes = [f"{1000 + index:04d}" for index in range(1, 502)]
    messages = [
        {
            "c": code,
            "d": "20260826",
            "t": "10:15:00",
            "y": "100",
            "z": "101" if index < 450 else "-",
            "v": "1" if index < 450 else "0",
        }
        for index, code in enumerate(codes[:475])
    ]
    monkeypatch.setattr(
        twse_mis_current_breadth,
        "_fetch_messages",
        lambda *_args: (messages, 0),
    )

    result = twse_mis_current_breadth.read_twse_mis_current_breadth(
        "TWSE",
        8,
        universe_reader=lambda _market: codes,
    )

    assert result.status == "available"
    assert result.payload is not None
    payload = result.payload
    assert payload["classified_count"] == 450
    assert payload["received_unclassified_count"] == 25
    assert payload["not_received_count"] == 26
    assert payload["unknown_count"] == 51
    assert (
        payload["classified_count"]
        + payload["received_unclassified_count"]
        + payload["not_received_count"]
        == payload["universe_count"]
    )
    assert payload["decision_usable"] is False
    assert payload["scope"] == "full_market_registered_stock_universe"
    twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()
