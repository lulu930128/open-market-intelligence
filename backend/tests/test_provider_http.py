from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from app.observability import provider_http


class DomainFetchError(Exception):
    pass


def _response(status_code: int, *, retry_after: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://provider.test/data?secret=hidden"
    response._content = b"{}"
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    return response


class ProviderHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = provider_http.ProviderRequestContext(
            market="US",
            provider="Yahoo_Chart",
            resource="daily_price",
            target="AAPL",
        )

    def test_context_normalizes_provider_identity(self) -> None:
        self.assertEqual(self.context.market, "us")
        self.assertEqual(self.context.provider, "yahoo_chart")
        self.assertEqual(self.context.resource, "daily_price")
        self.assertEqual(self.context.target, "AAPL")

    def test_successful_request_enforces_explicit_timeout(self) -> None:
        response = _response(200)
        with patch.object(provider_http.http_client, "request", return_value=response) as request:
            result = provider_http.get(
                self.context,
                "https://provider.test/data",
                timeout_seconds=12,
                params={"symbol": "AAPL"},
            )

        self.assertIs(result, response)
        request.assert_called_once_with(
            "GET",
            "https://provider.test/data",
            timeout=12,
            params={"symbol": "AAPL"},
        )

    def test_request_can_use_a_scoped_session_transport(self) -> None:
        response = _response(200)
        transport = Mock(return_value=response)

        result = provider_http.get(
            self.context,
            "https://provider.test/data",
            timeout_seconds=12,
            request_callable=transport,
            headers={"Accept": "application/json"},
        )

        self.assertIs(result, response)
        transport.assert_called_once_with(
            "GET",
            "https://provider.test/data",
            timeout=12,
            headers={"Accept": "application/json"},
        )

    def test_rate_limit_response_exposes_provider_event_fields(self) -> None:
        response = _response(429, retry_after="45")
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            provider_http.get(
                self.context,
                "https://provider.test/data",
                timeout_seconds=10,
            )

        error = raised.exception
        self.assertEqual(error.status, "rate_limited")
        self.assertEqual(error.http_status_code, 429)
        self.assertTrue(error.rate_limited)
        self.assertEqual(error.retry_after_seconds, 45)
        self.assertEqual(error.source_url, "https://provider.test/data")
        self.assertEqual(error.response, response)
        self.assertIn("HTTP 429", str(error))
        self.assertEqual(
            error.provider_event_fields()["provider"],
            "yahoo_chart",
        )

    def test_timeout_is_classified_without_leaking_request_params(self) -> None:
        with (
            patch.object(
                provider_http.http_client,
                "request",
                side_effect=requests.Timeout("socket timeout"),
            ),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            provider_http.post(
                self.context,
                "https://provider.test/data",
                timeout_seconds=(3, 8),
                params={"api_key": "secret"},
            )

        error = raised.exception
        self.assertEqual(error.status, "timeout")
        self.assertIsNone(error.http_status_code)
        self.assertNotIn("secret", str(error))
        self.assertIs(provider_http.provider_http_failure(error), error.failure)

    def test_nested_provider_error_can_be_classified(self) -> None:
        response = _response(403)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            provider_http.get(
                self.context,
                "https://provider.test/data",
                timeout_seconds=10,
            )

        wrapper = RuntimeError("provider adapter failed")
        wrapper.__cause__ = raised.exception
        failure = provider_http.provider_http_failure(wrapper)

        self.assertIsNotNone(failure)
        self.assertEqual(failure.status, "blocked")
        self.assertEqual(failure.http_status_code, 403)

    def test_service_boundary_translates_transport_error_and_preserves_context(self) -> None:
        response = _response(503)

        @provider_http.translate_provider_http_errors(DomainFetchError)
        def provider_operation() -> None:
            provider_http.get(
                self.context,
                "https://provider.test/data",
                timeout_seconds=10,
            )

        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(DomainFetchError) as raised,
        ):
            provider_operation()

        error = raised.exception
        self.assertIsInstance(error.__cause__, provider_http.ProviderHttpError)
        failure = provider_http.provider_http_failure(error)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.status, "error")
        self.assertEqual(failure.http_status_code, 503)

    def test_service_boundary_does_not_translate_non_transport_error(self) -> None:
        expected = ValueError("invalid provider payload")

        @provider_http.translate_provider_http_errors(DomainFetchError)
        def provider_operation() -> None:
            raise expected

        with self.assertRaises(ValueError) as raised:
            provider_operation()

        self.assertIs(raised.exception, expected)

    def test_retry_after_http_date_is_bounded_to_seconds(self) -> None:
        now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
        result = provider_http.retry_after_seconds(
            "Sat, 11 Jul 2026 04:01:30 GMT",
            now=now,
        )
        self.assertEqual(result, 90)

    def test_non_positive_timeout_is_rejected_before_network_call(self) -> None:
        with (
            patch.object(provider_http.http_client, "request") as request,
            self.assertRaisesRegex(ValueError, "greater than zero"),
        ):
            provider_http.get(
                self.context,
                "https://provider.test/data",
                timeout_seconds=0,
            )
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
