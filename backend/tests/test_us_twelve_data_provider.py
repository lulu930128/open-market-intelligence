from __future__ import annotations

import pytest

from app.us_market.providers import twelve_data
from app.us_market.providers.errors import USProviderDataError


class _Response:
    url = "https://api.twelvedata.com/quote?symbol=AAPL"

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_twelve_quote_uses_header_auth_without_secret_in_url(monkeypatch) -> None:
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response({"symbol": "AAPL", "close": "230.10"})

    monkeypatch.setattr(twelve_data, "provider_get", fake_get)
    payload, source_url = twelve_data.fetch_twelve_data_quote_payload(
        symbol="AAPL",
        api_key="fixture-twelve-secret",
        timeout_seconds=10,
    )

    assert payload["symbol"] == "AAPL"
    assert captured["headers"]["Authorization"] == "apikey fixture-twelve-secret"
    assert "fixture-twelve-secret" not in source_url
    assert "apikey" not in source_url.lower()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"status": "error", "code": 429, "message": "rate limit"}, "TWELVE_DATA_RATE_LIMITED"),
        ({"status": "error", "code": 401, "message": "bad api key"}, "TWELVE_DATA_AUTH_FAILED"),
        ({"status": "error", "code": 400, "message": "invalid symbol"}, "TWELVE_DATA_INVALID_SYMBOL"),
    ],
)
def test_twelve_payload_errors_are_typed_and_secret_safe(payload, code) -> None:
    with pytest.raises(USProviderDataError) as captured:
        twelve_data._payload_or_raise(payload)
    assert captured.value.code == code
    assert "fixture" not in str(captured.value)
