import logging
import time
import uuid

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import PROJECT_ROOT
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.routers import (
    ai,
    cross_market,
    crypto_market,
    dispatch,
    indicators,
    jp_market,
    kr_market,
    jobs,
    market,
    portfolio,
    raw_results,
    reports,
    resource_market,
    settings as settings_router,
    sources,
    stocks,
    system,
    us_market,
    watchlists,
)
from app.runtime import lifespan
from app.version import PROJECT_VERSION


FAVICON_PATH = PROJECT_ROOT / "frontend" / "src" / "app" / "favicon.ico"
request_logger = logging.getLogger("app.requests")


app = FastAPI(
    title="Open Market Intelligence API",
    description="A public-data-driven market intelligence system.",
    version=PROJECT_VERSION,
    lifespan=lifespan,
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started_at) * 1000
        request_logger.exception(
            "request failed method=%s path=%s duration_ms=%.1f request_id=%s",
            request.method,
            request.url.path,
            duration_ms,
            request_id,
        )
        raise

    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["x-request-id"] = request_id
    request_logger.info(
        "request method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(raw_results.router, prefix="/api/raw-results", tags=["raw-results"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(crypto_market.router, prefix="/api/crypto-market", tags=["crypto-market"])
app.include_router(resource_market.router, prefix="/api/resource-market", tags=["resource-market"])
app.include_router(dispatch.router, prefix="/api/dispatch", tags=["dispatch"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(
    cross_market.router,
    prefix="/api/market/cross-market",
    tags=["cross-market"],
)
app.include_router(indicators.router, prefix="/api/market/indicators", tags=["market-indicators"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(us_market.router, prefix="/api/us-market", tags=["us-market"])
app.include_router(jp_market.router, prefix="/api/jp-market", tags=["jp-market"])
app.include_router(kr_market.router, prefix="/api/kr-market", tags=["kr-market"])
app.include_router(watchlists.router, prefix="/api/watchlists", tags=["watchlists"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if FAVICON_PATH.exists():
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")

    return Response(status_code=204)


@app.get("/")
def root():
    return {
        "name": "Open Market Intelligence",
        "status": "running",
        "docs": "/docs",
    }
