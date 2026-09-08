import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest
import requests

from app.config import settings
from app.integrations import atlas_endpoint as endpoint


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "omi_atlas_endpoint_mode", "discovery")
    monkeypatch.setattr(settings, "omi_atlas_endpoint_state_path", str(tmp_path / "endpoint.json"))
    monkeypatch.setattr(settings, "omi_atlas_api_base_url", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "omi_atlas_timeout_seconds", 2.0)
    endpoint._cache.clear()
    servers = []

    def server(instance="first", service="open-intel-atlas"):
        identity = dict(schema_version=1, service=service, status="running", instance_id=instance,
                        installation_id="test-installation", pid=123, started_at="2026-09-07T00:00:00Z")
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = identity if self.path == "/api/v1/runtime" else {"instance": instance}
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args):
                pass
        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        identity["base_url"] = f"http://127.0.0.1:{http.server_port}"
        threading.Thread(target=http.serve_forever, daemon=True).start()
        servers.append(http)
        return identity

    def stop(identity):
        http = next(item for item in servers if identity["base_url"].endswith(f":{item.server_port}"))
        http.shutdown()
        http.server_close()
        servers.remove(http)
    server.stop = stop

    def publish(identity):
        from pathlib import Path
        Path(settings.omi_atlas_endpoint_state_path).write_text(json.dumps(identity), encoding="utf-8")

    yield server, publish
    for http in servers:
        http.shutdown()
        http.server_close()
    endpoint._cache.clear()


def test_discovers_actual_port_and_recovers_once_after_refusal(setup):
    server, publish = setup
    first, second = server(), server("second")
    publish(first)
    assert endpoint.request_json("/news", {}) == (200, {"instance": "first"})
    publish(second)
    calls = []
    def fetch(url, params):
        calls.append(url)
        if url.startswith(first["base_url"]):
            raise requests.ConnectionError("connection refused")
        return endpoint.fetch_json(url, params)
    assert endpoint.request_json("/news", {}, fetch=fetch) == (200, {"instance": "second"})
    assert len(calls) == 2


@pytest.mark.parametrize("error", [requests.ReadTimeout(), requests.ConnectionError("Read timed out")])
def test_read_timeout_is_not_retried(setup, error):
    server, publish = setup
    publish(server())
    fetch = Mock(side_effect=error)
    with pytest.raises(requests.RequestException):
        endpoint.request_json("/news", {}, fetch=fetch)
    assert fetch.call_count == 1


def test_same_endpoint_refusal_not_retried(setup):
    server, publish = setup
    publish(server())
    fetch = Mock(side_effect=requests.ConnectionError())
    with pytest.raises(requests.ConnectionError):
        endpoint.request_json("/news", {}, fetch=fetch)
    assert fetch.call_count == 1


@pytest.mark.parametrize("mutation", [lambda d: d.update(instance_id="old"), lambda d: d.update(installation_id="other"),
                                    lambda d: d.update(status="stopped"), lambda d: d.update(base_url="http://example.test:123")])
def test_stale_or_invalid_state_cannot_authorize_http(setup, mutation):
    server, publish = setup
    data = server()
    stale = dict(data)
    mutation(stale)
    publish(stale)
    fetch = Mock()
    with pytest.raises(endpoint.AtlasEndpointError):
        endpoint.request_json("/news", {}, fetch=fetch)
    fetch.assert_not_called()


def test_unrelated_http_200_rejected(setup):
    server, publish = setup
    publish(server(service="other-app"))
    with pytest.raises(endpoint.AtlasEndpointError):
        endpoint.request_json("/news", {})


@pytest.mark.parametrize("contents", [None, "{bad", "[]", "x" * 9000], ids=["missing", "malformed", "array", "oversized"])
def test_missing_malformed_state_uses_verified_static_fallback(setup, monkeypatch, contents):
    from pathlib import Path
    server, _ = setup
    data = server()
    monkeypatch.setattr(settings, "omi_atlas_api_base_url", data["base_url"])
    if contents is not None:
        Path(settings.omi_atlas_endpoint_state_path).write_text(contents)
    assert endpoint.request_json("/news", {}) == (200, {"instance": "first"})


def test_static_mode_does_not_read_discovery(setup, monkeypatch):
    monkeypatch.setattr(settings, "omi_atlas_endpoint_mode", "static")
    fetch = Mock(return_value=(200, {}))
    assert endpoint.request_json("/news", {}, fetch=fetch) == (200, {})
    assert fetch.call_args.args[0] == "http://127.0.0.1:1/news"


def test_redirect_never_followed(setup, monkeypatch):
    response = Mock(status_code=302)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    monkeypatch.setattr(endpoint.requests, "Session", lambda: session)
    assert endpoint.fetch_json("http://127.0.0.1:1/news", {}) == (302, None)
    assert session.trust_env is False
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_real_closed_listener_recovers_to_successor(setup):
    server, publish = setup
    old = server()
    publish(old)
    assert endpoint.request_json("/news", {})[1]["instance"] == "first"
    server.stop(old)
    publish(server("successor"))
    assert endpoint.request_json("/news", {})[1]["instance"] == "successor"


def test_cache_expires_and_does_not_use_descriptor_timestamp_as_lease(setup, monkeypatch):
    server, publish = setup
    old = server()
    publish(old)
    monkeypatch.setattr(settings, "omi_atlas_endpoint_cache_ttl_seconds", 0.0)
    assert endpoint.request_json("/news", {})[1]["instance"] == "first"
    publish(server("second"))
    assert endpoint.request_json("/news", {})[1]["instance"] == "second"


def test_discovery_lock_wait_obeys_total_budget(setup, monkeypatch):
    import time
    monkeypatch.setattr(settings, "omi_atlas_timeout_seconds", 0.1)
    endpoint._lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(requests.Timeout):
            endpoint.request_json("/news", {})
        assert time.monotonic() - started < 0.5
    finally:
        endpoint._lock.release()
