from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.us_market.providers import massive
from app.us_market.providers.errors import USProviderDataError


class _Response:
    def __init__(self, payload, *, url: str, status_code: int = 200) -> None:
        self._payload = payload
        self.url = url
        self.status_code = status_code

    def json(self):
        return self._payload


def test_massive_snapshot_uses_header_auth_and_provider_symbol(monkeypatch) -> None:
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(
            {
                "status": "OK",
                "results": [{"ticker": "I:COMP", "value": 22000}],
            },
            url="https://api.massive.com/v3/snapshot/indices?ticker.any_of=I%3ACOMP",
        )

    monkeypatch.setattr(massive, "provider_get", fake_get)
    payload, source_url = massive.fetch_massive_index_snapshot_payload(
        symbol="^IXIC",
        api_key="fixture-massive-secret",
        timeout_seconds=10,
    )

    assert payload["results"][0]["ticker"] == "I:COMP"
    assert captured["params"] == {"ticker.any_of": "I:COMP"}
    assert captured["headers"]["Authorization"] == "Bearer fixture-massive-secret"
    assert "fixture-massive-secret" not in source_url
    assert "apiKey" not in source_url


def test_massive_aggregates_encode_index_namespace_and_bound_range(monkeypatch) -> None:
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(
            {"status": "OK", "ticker": "I:SOX", "results": []},
            url=url,
        )

    monkeypatch.setattr(massive, "provider_get", fake_get)
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    payload, _ = massive.fetch_massive_index_aggregates_payload(
        symbol="^SOX",
        api_key="fixture-key",
        interval="1m",
        start_at=start,
        end_at=start + timedelta(minutes=30),
        limit=30,
        timeout_seconds=10,
    )

    assert payload["ticker"] == "I:SOX"
    assert "/ticker/I%3ASOX/range/1/minute/" in captured["url"]
    assert captured["params"]["limit"] == "30"
    assert captured["params"]["sort"] == "asc"


@pytest.mark.parametrize(
    ("payload", "status_code", "code", "category"),
    [
        ({"status": "ERROR", "error": "NOT_ENTITLED"}, 200, "MASSIVE_NOT_ENTITLED", "entitlement"),
        ({"status": "ERROR", "error": "NOT_FOUND"}, 200, "MASSIVE_TICKER_NOT_FOUND", "invalid_symbol"),
        ({"status": "ERROR", "error": "too many requests"}, 200, "MASSIVE_RATE_LIMITED", "rate_limit"),
        ({"status": "OK"}, 401, "MASSIVE_AUTH_FAILED", "auth"),
        ({"status": "OK"}, 403, "MASSIVE_NOT_ENTITLED", "entitlement"),
        ({"status": "OK"}, 429, "MASSIVE_RATE_LIMITED", "rate_limit"),
    ],
)
def test_massive_failures_are_typed_and_secret_safe(
    payload,
    status_code: int,
    code: str,
    category: str,
) -> None:
    with pytest.raises(USProviderDataError) as captured:
        massive._payload_or_raise(payload, status_code=status_code)
    assert captured.value.code == code
    assert captured.value.category == category
    assert "fixture" not in str(captured.value)


@pytest.mark.parametrize("symbol", ["AAPL", "SPY", "QQQ"])
def test_massive_index_client_rejects_non_index_aliases_before_io(symbol: str) -> None:
    with pytest.raises(ValueError, match="unsupported Massive US index symbol"):
        massive.fetch_massive_index_snapshot_payload(
            symbol=symbol,
            api_key="fixture-key",
            timeout_seconds=10,
        )
