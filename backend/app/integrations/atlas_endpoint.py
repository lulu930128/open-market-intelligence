"""Local Atlas endpoint discovery and bounded read-only transport.

Runtime files are hints, not leases. Only a matching live identity is accepted.
Static mode is explicit and preserves isolated runtimes / older Atlas servers.
"""
from __future__ import annotations

import json
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import settings

MAX_BYTES = 768 * 1024
_deadline: ContextVar[float | None] = ContextVar("atlas_deadline", default=None)
_lock = threading.Lock()
_cache: dict = {}


class AtlasEndpointError(requests.RequestException):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def local_base_url(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        valid = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
                 and parsed.port is not None and 0 < parsed.port < 65536
                 and not parsed.username and not parsed.password
                 and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except (ValueError, TypeError):
        return None
    return value.rstrip("/") if valid else None


def _remaining() -> float:
    end = _deadline.get()
    remaining = settings.omi_atlas_timeout_seconds if end is None else end - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("Atlas total request budget exhausted")
    return remaining


def fetch_json(url: str, params: dict, *, max_bytes: int = MAX_BYTES, timeout: float | None = None):
    remaining = min(_remaining(), timeout or _remaining())
    with requests.Session() as session:
        session.trust_env = False
        # Windows may silently time out a closed local port instead of refusing it.
        # Reserve budget for discovery and the successor request after that timeout.
        timeout_budget = requests.adapters.TimeoutSauce(
            total=remaining, connect=min(settings.omi_atlas_endpoint_health_timeout_seconds, remaining / 3),
            read=remaining,
        )
        with session.get(url, params=params, timeout=timeout_budget, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                return response.status_code, None
            chunks, size = [], 0
            for chunk in response.iter_content(4096):
                _remaining()
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("atlas_response_too_large")
                chunks.append(chunk)
            return 200, json.loads(b"".join(chunks))


def _identity(base: str, expected: dict | None = None) -> dict:
    try:
        code, data = fetch_json(base + "/api/v1/runtime", {}, max_bytes=8192,
                                timeout=settings.omi_atlas_endpoint_health_timeout_seconds)
    except (requests.RequestException, ValueError, UnicodeError, RecursionError) as exc:
        raise AtlasEndpointError("atlas_endpoint_health_failed") from exc
    if code != 200 or not isinstance(data, dict):
        raise AtlasEndpointError("atlas_endpoint_health_failed")
    if (data.get("schema_version") != 1 or data.get("service") != "open-intel-atlas"
            or data.get("status") != "running" or data.get("base_url") != base
            or not isinstance(data.get("instance_id"), str) or not data["instance_id"]
            or not isinstance(data.get("installation_id"), str) or not data["installation_id"]):
        raise AtlasEndpointError("atlas_endpoint_identity_mismatch")
    if expected and any(data.get(key) != expected.get(key) for key in ("instance_id", "installation_id", "pid", "started_at")):
        raise AtlasEndpointError("atlas_endpoint_identity_mismatch")
    return data


def _discover(static: str) -> str:
    path = Path(settings.omi_atlas_endpoint_state_path)
    # No UNC/network filesystem discovery on the HTTP read path.
    if str(path).startswith(("\\\\", "//")) or not path.is_absolute():
        raise AtlasEndpointError("atlas_runtime_state_invalid")
    try:
        with path.open("rb") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized state")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("invalid schema")
        base = local_base_url(data.get("base_url"))
        if not base or data.get("status") != "running":
            raise ValueError("invalid endpoint")
    except (OSError, ValueError, TypeError, RecursionError):
        # Only a live Atlas identity can authorize the configured fallback.
        _identity(static)
        return static
    try:
        _identity(base, data)
        return base
    except AtlasEndpointError:
        if base == static:
            raise
        # Do not silently connect another Atlas installation at the static port.
        fallback = _identity(static)
        if fallback.get("installation_id") != data.get("installation_id"):
            raise AtlasEndpointError("atlas_endpoint_identity_mismatch")
        return static


def resolve_endpoint(*, force: bool = False) -> str:
    static = local_base_url(settings.omi_atlas_api_base_url)
    if not static:
        raise AtlasEndpointError("atlas_base_url_not_loopback")
    if settings.omi_atlas_endpoint_mode == "static":
        return static
    key = (static, settings.omi_atlas_endpoint_state_path,
           settings.omi_atlas_endpoint_health_timeout_seconds, settings.omi_atlas_endpoint_cache_ttl_seconds)
    if not _lock.acquire(timeout=_remaining()):
        raise requests.Timeout("Atlas discovery lock budget exhausted")
    try:
        now = time.monotonic()
        if not force and _cache.get("key") == key and _cache.get("expires", 0) > now:
            if _cache.get("error"):
                raise AtlasEndpointError(_cache["error"])
            return _cache["base"]
        _cache.clear()
        try:
            base = _discover(static)
        except AtlasEndpointError as exc:
            _cache.update(key=key, error=exc.reason, expires=now + min(1.0, settings.omi_atlas_endpoint_cache_ttl_seconds))
            raise
        _cache.update(key=key, base=base, expires=time.monotonic() + settings.omi_atlas_endpoint_cache_ttl_seconds)
        return base
    finally:
        _lock.release()


def request_json(path: str, params: dict, *, fetch=None):
    token = _deadline.set(time.monotonic() + settings.omi_atlas_timeout_seconds)
    try:
        base = resolve_endpoint()
        try:
            return (fetch or fetch_json)(base + path, params)
        except (requests.ConnectTimeout, requests.ConnectionError) as exc:
            # Streaming read timeouts can be wrapped as ConnectionError by requests.
            if "Read timed out" in str(exc) or settings.omi_atlas_endpoint_mode == "static":
                raise
            updated = resolve_endpoint(force=True)
            if updated == base:
                raise exc
            _remaining()
            return (fetch or fetch_json)(updated + path, params)
    finally:
        _deadline.reset(token)
