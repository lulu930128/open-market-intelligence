"""Separate runtime transport; never included in AI ask/tool dispatch."""
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import runtime_control as control

router = APIRouter()


def _local(request: Request) -> bool:
    return bool(request.client and request.client.host in {"127.0.0.1", "::1"}
                and not any(h in request.headers for h in
                            ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"))
                and "origin" not in request.headers)


def _reply(body: dict, code: int = 200):
    return JSONResponse(body, status_code=code, headers={"Cache-Control": "no-store"})


def _denied():
    return _reply({"schema": control.SCHEMA, "error": "RUNTIME_CONTROL_FORBIDDEN"}, 403)


def _backend_preflight(request: Request) -> dict | None:
    runtime = getattr(request.app.state, "runtime", None)
    observe = getattr(runtime, "restart_preflight", None)
    return observe() if callable(observe) else None


@router.get("/status")
def status(request: Request):
    if not _local(request):
        return _denied()
    try:
        result = control.launcher_request("Status")
        if result.get("owner_id") is None:
            result = control.unknown_status()
    except (OSError, ValueError):
        result = control.unknown_status()
    disk = control.bundle_id()
    result["source"] = {"build_id_scope": "runtime_control_bundle_only",
                        "disk_build_id": disk,
                        "import_time_build_id": control.LOADED_CONTROL_BUNDLE_ID,
                        "disk_matches_import": disk == control.LOADED_CONTROL_BUNDLE_ID if disk else None,
                        "loaded_release_identity": "UNATTESTED"}
    runtime = getattr(request.app.state, "runtime", None)
    observe_writers = getattr(runtime, "restart_diagnostics", None)
    result["serving_backend"] = {"runtime_started": bool(runtime and getattr(runtime, "started", False)),
                                 "database_readiness": "not_checked",
                                 "readiness": "UNATTESTED",
                                 "writer_preflight": _backend_preflight(request),
                                 "writer_diagnostics": observe_writers() if callable(observe_writers) else None}
    owned_start = getattr(request.app.state, "owned_start", None)
    if owned_start is not None:
        result["serving_backend"]["owned_start"] = dict(owned_start)
    return _reply(result)


@router.post("/restart-backend", openapi_extra={"requestBody": {
    "required": True, "content": {"application/json": {"schema": control.RestartRequest.model_json_schema()}}
}})
async def restart_backend(request: Request):
    # Authenticate before parsing: validation responses never echo credential inputs.
    token = request.headers.get("x-omi-runtime-control-token")
    if not _local(request) or not control.token_authorized(token):
        return _denied()
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 1024:
            return _reply({"schema": control.SCHEMA, "error": "INVALID_REQUEST"}, 422)
    try:
        body = control.RestartRequest.model_validate_json(data)
    except ValueError:
        return _reply({"schema": control.SCHEMA, "error": "INVALID_REQUEST"}, 422)
    # The pipe is bounded but blocking. Keep it off the event loop.
    from starlette.concurrency import run_in_threadpool
    try:
        result = await run_in_threadpool(
            control.launcher_request, "RestartBackend", request_id=str(body.request_id),
            expected_owner_id=str(body.expected_owner_id), token=token,
            backend_preflight=_backend_preflight(request),
        )
    except (OSError, ValueError):
        return _reply(control.unknown_operation(str(body.request_id)), 503)
    if result.get("reason") == "OWNER_MISMATCH":
        return _reply(control.unknown_operation(str(body.request_id), "OWNER_MISMATCH"), 409)
    code = {"accepted": 202, "running": 202, "succeeded": 200,
            "blocked": 409, "failed": 409, "unknown": 503}.get(result.get("state"), 503)
    if result.get("error") == "RUNTIME_CONTROL_FORBIDDEN":
        code = 403
    elif result.get("request_id") != str(body.request_id):
        result = control.unknown_operation(str(body.request_id), "STORE_UNAVAILABLE")
        code = 503
    return _reply(result, code)


@router.get("/operations/{request_id}")
def operation(request_id: UUID, request: Request):
    if not _local(request):
        return _denied()
    try:
        result = control.launcher_request("ReadOperation", request_id=str(request_id))
    except (OSError, ValueError):
        result = control.unknown_operation(str(request_id))
    if result.get("request_id") != str(request_id):
        result = control.unknown_operation(str(request_id), "STORE_UNAVAILABLE")
    return _reply(result)
