from __future__ import annotations

import os
import ssl
import unittest
from unittest.mock import patch

import requests

from app import http_client


def _response(url: str) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response._content = b"{}"
    return response


class HttpClientTests(unittest.TestCase):
    def test_tpex_adapter_keeps_certificate_and_hostname_verification(self) -> None:
        with http_client.new_session() as session:
            adapter = session.get_adapter(
                "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
            )
            context = adapter.poolmanager.connection_pool_kw["ssl_context"]

        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", None)
        if strict_flag is not None:
            self.assertEqual(context.verify_flags & strict_flag, 0)

    def test_default_session_ignores_environment_proxy(self) -> None:
        observed_trust_env: list[bool] = []

        def fake_request(
            session: requests.Session,
            method: str,
            url: str,
            **kwargs,
        ) -> requests.Response:
            observed_trust_env.append(session.trust_env)
            return _response(url)

        with (
            patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": "http://127.0.0.1:9",
                    "HTTPS_PROXY": "http://127.0.0.1:9",
                },
                clear=False,
            ),
            patch.object(http_client.settings, "omi_http_trust_env", False),
            patch.object(requests.Session, "request", fake_request),
        ):
            response = http_client.get("https://example.test/data", timeout=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observed_trust_env, [False])

    def test_session_can_opt_in_to_environment_proxy(self) -> None:
        observed_trust_env: list[bool] = []

        def fake_request(
            session: requests.Session,
            method: str,
            url: str,
            **kwargs,
        ) -> requests.Response:
            observed_trust_env.append(session.trust_env)
            return _response(url)

        with (
            patch.object(http_client.settings, "omi_http_trust_env", True),
            patch.object(requests.Session, "request", fake_request),
        ):
            response = http_client.post("https://example.test/data", json={}, timeout=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observed_trust_env, [True])
