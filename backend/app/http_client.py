from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from app.config import settings


TPEX_COMPAT_TLS_PREFIX = "https://www.tpex.org.tw/"


def _verified_compatibility_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", None)
    if strict_flag is not None:
        context.verify_flags &= ~strict_flag
    return context


class _VerifiedCompatibilityTlsAdapter(HTTPAdapter):
    """Keep normal TLS verification while tolerating an older official CA chain."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = _verified_compatibility_tls_context()
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def trust_environment_proxy() -> bool:
    """Return whether outbound HTTP should honor proxy settings from env."""
    return bool(settings.omi_http_trust_env)


def new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_environment_proxy()
    session.mount(TPEX_COMPAT_TLS_PREFIX, _VerifiedCompatibilityTlsAdapter())
    return session


def request(method: str, url: str, **kwargs) -> requests.Response:
    with new_session() as session:
        return session.request(method, url, **kwargs)


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)
