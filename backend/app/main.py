from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import init_db
from app.routers import indicators, market, raw_results, reports, sources, stocks, system, watchlists


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Open Market Intelligence API",
    description="A public-data-driven market intelligence system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(raw_results.router, prefix="/api/raw-results", tags=["raw-results"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(indicators.router, prefix="/api/market/indicators", tags=["market-indicators"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(watchlists.router, prefix="/api/watchlists", tags=["watchlists"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])

@app.get("/")
def root():
    return {
        "name": "Open Market Intelligence",
        "status": "running",
        "docs": "/docs",
    }