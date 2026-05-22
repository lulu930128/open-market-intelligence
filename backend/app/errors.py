import logging
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _payload(
    *,
    request: Request,
    code: str,
    message: str,
    detail: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }

    if detail is not None:
        error["detail"] = jsonable_encoder(detail)

    return {"error": error}


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed."
    code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"

    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(
            request=request,
            code=code,
            message=message,
            detail=None if isinstance(detail, str) else detail,
        ),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_payload(
            request=request,
            code="validation_error",
            message="Request validation failed.",
            detail=exc.errors(),
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled API error request_id=%s path=%s",
        _request_id(request),
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content=_payload(
            request=request,
            code="internal_server_error",
            message="Internal server error.",
        ),
    )
