from __future__ import annotations

from datetime import datetime, timezone

from app.us_market.providers import alpaca


class _Response:
    url = (
        "https://data.alpaca.markets/v2/stocks/AAPL/bars?"
        "timeframe=1Day&feed=sip&adjustment=raw"
    )

    def json(self):
        return {"bars": [], "symbol": "AAPL", "next_page_token": None}


def test_alpaca_historical_client_uses_header_auth_and_bounded_params(monkeypatch) -> None:
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(alpaca, "provider_get", fake_get)
    payload, source_url = alpaca.fetch_alpaca_stock_bars_payload(
        symbol="AAPL",
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        timeframe="1Day",
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 8, 28, 20, tzinfo=timezone.utc),
        limit=500,
        feed="sip",
        adjustment="raw",
        sort="asc",
        timeout_seconds=12,
    )

    assert payload["symbol"] == "AAPL"
    assert captured["params"]["feed"] == "sip"
    assert captured["params"]["limit"] == "500"
    assert captured["headers"]["APCA-API-KEY-ID"] == "fixture-key-id"
    assert captured["headers"]["APCA-API-SECRET-KEY"] == "fixture-secret"
    assert "fixture-key-id" not in source_url
    assert "fixture-secret" not in source_url


def test_alpaca_client_rejects_unbounded_or_adjusted_requests() -> None:
    common = dict(
        symbol="AAPL",
        api_key_id="key",
        api_secret_key="secret",
        timeframe="1Day",
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 8, 28, 20, tzinfo=timezone.utc),
        feed="sip",
        sort="asc",
        timeout_seconds=12,
    )
    try:
        alpaca.fetch_alpaca_stock_bars_payload(
            **common,
            limit=10_001,
            adjustment="raw",
        )
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("unbounded Alpaca limit must fail")

    try:
        alpaca.fetch_alpaca_stock_bars_payload(
            **common,
            limit=100,
            adjustment="all",
        )
    except ValueError as exc:
        assert "adjustment=raw" in str(exc)
    else:
        raise AssertionError("adjusted Alpaca bars must fail")
