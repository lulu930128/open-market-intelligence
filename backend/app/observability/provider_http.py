from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

import requests

from app import http_client


DEFAULT_TARGET = "all"
P = ParamSpec("P")
R = TypeVar("R")


def _normalized_key(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    return text or default


@dataclass(frozen=True)
class ProviderRequestContext:
    market: str
    provider: str
    resource: str
    target: str = DEFAULT_TARGET

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", _normalized_key(self.market, default="unknown").lower())
        object.__setattr__(self, "provider", _normalized_key(self.provider, default="unknown").lower())
        object.__setattr__(self, "resource", _normalized_key(self.resource, default="unknown"))
        object.__setattr__(self, "target", _normalized_key(self.target, default=DEFAULT_TARGET))


@dataclass(frozen=True)
class ProviderHttpFailure:
    context: ProviderRequestContext
    status: str
    source_url: str
    http_status_code: int | None = None
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    error_message: str | None = None
    exception_type: str | None = None
    timeout_stage: str | None = None
    response_content_type: str | None = None
    retry_count: int = 0

    def provider_event_fields(self) -> dict[str, Any]:
        return {
            "market": self.context.market,
            "provider": self.context.provider,
            "resource": self.context.resource,
            "target": self.context.target,
            "status": self.status,
            "http_status_code": self.http_status_code,
            "rate_limited": self.rate_limited,
            "retry_after_seconds": self.retry_after_seconds,
            "source_url": self.source_url,
            "error_message": self.error_message,
        }

    def diagnostic_fields(self) -> dict[str, Any]:
        return {
            **self.provider_event_fields(),
            "exception_type": self.exception_type,
            "timeout_stage": self.timeout_stage,
            "response_content_type": self.response_content_type,
            "retry_count": self.retry_count,
        }


class ProviderHttpError(requests.HTTPError):
    def __init__(
        self,
        message: str,
        *,
        failure: ProviderHttpFailure,
        response: requests.Response | None = None,
    ) -> None:
        super().__init__(message, response=response)
        self.failure = failure

    @property
    def context(self) -> ProviderRequestContext:
        return self.failure.context

    @property
    def status(self) -> str:
        return self.failure.status

    @property
    def source_url(self) -> str:
        return self.failure.source_url

    @property
    def http_status_code(self) -> int | None:
        return self.failure.http_status_code

    @property
    def rate_limited(self) -> bool:
        return self.failure.rate_limited

    @property
    def retry_after_seconds(self) -> int | None:
        return self.failure.retry_after_seconds

    def provider_event_fields(self) -> dict[str, Any]:
        return self.failure.provider_event_fields()


def provider_status_for_http_code(status_code: int) -> str:
    if status_code == 429:
        return "rate_limited"
    if status_code in {401, 403}:
        return "blocked"
    if status_code >= 500:
        return "error"
    return "failed"


def retry_after_seconds(
    value: str | None,
    *,
    now: datetime | None = None,
) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        return max(int(text), 0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(math.ceil((retry_at - current).total_seconds()), 0)


def _timeout_label(timeout_seconds: float | tuple[float, float]) -> str:
    if isinstance(timeout_seconds, tuple):
        return "/".join(f"{value:g}" for value in timeout_seconds)
    return f"{timeout_seconds:g}"


def _validate_timeout(timeout_seconds: float | tuple[float, float]) -> None:
    values = timeout_seconds if isinstance(timeout_seconds, tuple) else (timeout_seconds,)
    if not values or any(float(value) <= 0 for value in values):
        raise ValueError("Provider HTTP timeout must be greater than zero.")


def _error_message(
    *,
    method: str,
    context: ProviderRequestContext,
    status: str,
    status_code: int | None = None,
    timeout_seconds: float | tuple[float, float] | None = None,
) -> str:
    operation = (
        f"{method} provider request for {context.market}/{context.provider}/"
        f"{context.resource}/{context.target}"
    )
    if status_code is not None:
        return f"{operation} failed: HTTP {status_code}."
    if status == "timeout" and timeout_seconds is not None:
        return f"{operation} timed out after {_timeout_label(timeout_seconds)}s."
    return f"{operation} failed before receiving a valid HTTP response."


def request(
    context: ProviderRequestContext,
    method: str,
    url: str,
    *,
    timeout_seconds: float | tuple[float, float],
    request_callable: Callable[..., requests.Response] | None = None,
    **kwargs: Any,
) -> requests.Response:
    _validate_timeout(timeout_seconds)
    if "timeout" in kwargs:
        raise TypeError("Use timeout_seconds for provider HTTP requests.")

    normalized_method = str(method or "GET").strip().upper() or "GET"
    source_url = str(url)
    transport = request_callable or http_client.request
    try:
        response = transport(
            normalized_method,
            source_url,
            timeout=timeout_seconds,
            **kwargs,
        )
    except requests.Timeout as exc:
        message = _error_message(
            method=normalized_method,
            context=context,
            status="timeout",
            timeout_seconds=timeout_seconds,
        )
        failure = ProviderHttpFailure(
            context=context,
            status="timeout",
            source_url=source_url,
            error_message=message,
            exception_type=type(exc).__name__,
            timeout_stage=(
                "connect"
                if isinstance(exc, requests.ConnectTimeout)
                else "read"
                if isinstance(exc, requests.ReadTimeout)
                else "request"
            ),
        )
        raise ProviderHttpError(message, failure=failure) from exc
    except requests.RequestException as exc:
        message = _error_message(
            method=normalized_method,
            context=context,
            status="error",
        )
        failure = ProviderHttpFailure(
            context=context,
            status="error",
            source_url=source_url,
            error_message=message,
            exception_type=type(exc).__name__,
        )
        raise ProviderHttpError(message, failure=failure) from exc

    if response.status_code >= 400:
        status = provider_status_for_http_code(response.status_code)
        message = _error_message(
            method=normalized_method,
            context=context,
            status=status,
            status_code=response.status_code,
        )
        failure = ProviderHttpFailure(
            context=context,
            status=status,
            source_url=source_url,
            http_status_code=response.status_code,
            rate_limited=response.status_code == 429,
            retry_after_seconds=retry_after_seconds(response.headers.get("Retry-After")),
            error_message=message,
            exception_type="HTTPError",
            response_content_type=response.headers.get("Content-Type"),
        )
        raise ProviderHttpError(message, failure=failure, response=response)

    return response


def get(
    context: ProviderRequestContext,
    url: str,
    *,
    timeout_seconds: float | tuple[float, float],
    request_callable: Callable[..., requests.Response] | None = None,
    **kwargs: Any,
) -> requests.Response:
    return request(
        context,
        "GET",
        url,
        timeout_seconds=timeout_seconds,
        request_callable=request_callable,
        **kwargs,
    )


def post(
    context: ProviderRequestContext,
    url: str,
    *,
    timeout_seconds: float | tuple[float, float],
    request_callable: Callable[..., requests.Response] | None = None,
    **kwargs: Any,
) -> requests.Response:
    return request(
        context,
        "POST",
        url,
        timeout_seconds=timeout_seconds,
        request_callable=request_callable,
        **kwargs,
    )


def provider_http_failure(exc: BaseException) -> ProviderHttpFailure | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ProviderHttpError):
            return current.failure
        current = current.__cause__ or current.__context__
    return None


def translate_provider_http_errors(
    error_type: type[Exception],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Translate transport failures at a service boundary without losing context."""

    def decorator(operation: Callable[P, R]) -> Callable[P, R]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return operation(*args, **kwargs)
            except requests.RequestException as exc:
                raise error_type(str(exc)) from exc

        return wrapped

    return decorator


__all__ = [
    "ProviderHttpError",
    "ProviderHttpFailure",
    "ProviderRequestContext",
    "get",
    "post",
    "provider_http_failure",
    "provider_status_for_http_code",
    "request",
    "retry_after_seconds",
    "translate_provider_http_errors",
]
