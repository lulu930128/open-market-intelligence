from __future__ import annotations

import requests

from app.config import settings


def trust_environment_proxy() -> bool:
    """Return whether outbound HTTP should honor proxy settings from env."""
    return bool(settings.omi_http_trust_env)


def new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_environment_proxy()
    return session


def request(method: str, url: str, **kwargs) -> requests.Response:
    with new_session() as session:
        return session.request(method, url, **kwargs)


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)
