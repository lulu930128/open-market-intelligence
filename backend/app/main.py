from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import init_db
from app.routers import reports, sources, system


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
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])


@app.get("/")
def root():
    return {
        "name": "Open Market Intelligence",
        "status": "running",
        "docs": "/docs",
    }