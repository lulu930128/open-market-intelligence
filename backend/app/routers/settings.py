import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.crypto_market.auto_refresh import reload_crypto_auto_refresh
from app.crypto_market.ws_runtime import reload_crypto_realtime_collectors
from app.db.session import get_db
from app.settings.refresh_execution import (
    get_refresh_execution_settings,
    update_refresh_execution_settings,
)
from app.settings.market_data_subscription import (
    get_market_data_subscription_settings,
    update_market_data_subscription_settings,
)
from app.settings.schemas import (
    MarketDataSubscriptionSettingsRead,
    MarketDataSubscriptionSettingsWrite,
    RefreshExecutionSettingsRead,
    RefreshExecutionSettingsWrite,
    TechnicalAnalysisSettingsRead,
    TechnicalAnalysisSettingsWrite,
)
from app.settings.service import (
    get_technical_analysis_settings,
    update_technical_analysis_settings,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/technical-analysis", response_model=TechnicalAnalysisSettingsRead)
def get_technical_analysis_settings_endpoint(db: Session = Depends(get_db)):
    try:
        return get_technical_analysis_settings(db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Technical analysis settings are invalid: {exc}",
        ) from exc


@router.put("/technical-analysis", response_model=TechnicalAnalysisSettingsRead)
def update_technical_analysis_settings_endpoint(
    payload: TechnicalAnalysisSettingsWrite,
    db: Session = Depends(get_db),
):
    try:
        return update_technical_analysis_settings(db=db, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Technical analysis settings are invalid: {exc}",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Technical analysis settings could not be saved.",
        ) from exc


@router.get("/refresh-execution", response_model=RefreshExecutionSettingsRead)
def get_refresh_execution_settings_endpoint(db: Session = Depends(get_db)):
    try:
        return get_refresh_execution_settings(db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Refresh execution settings are invalid: {exc}",
        ) from exc


@router.put("/refresh-execution", response_model=RefreshExecutionSettingsRead)
def update_refresh_execution_settings_endpoint(
    payload: RefreshExecutionSettingsWrite,
    db: Session = Depends(get_db),
):
    try:
        return update_refresh_execution_settings(db=db, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refresh execution settings are invalid: {exc}",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Refresh execution settings could not be saved.",
        ) from exc


@router.get(
    "/market-data-subscriptions",
    response_model=MarketDataSubscriptionSettingsRead,
)
def get_market_data_subscription_settings_endpoint(db: Session = Depends(get_db)):
    try:
        return get_market_data_subscription_settings(db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Market data subscription settings are invalid: {exc}",
        ) from exc


@router.put(
    "/market-data-subscriptions",
    response_model=MarketDataSubscriptionSettingsRead,
)
async def update_market_data_subscription_settings_endpoint(
    payload: MarketDataSubscriptionSettingsWrite,
    db: Session = Depends(get_db),
):
    try:
        response = update_market_data_subscription_settings(db=db, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Market data subscription settings are invalid: {exc}",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Market data subscription settings could not be saved.",
        ) from exc

    runtime: dict[str, object] = {}
    try:
        reload_status = await reload_crypto_realtime_collectors(
            reason="market_data_subscription_settings_updated"
        )
        runtime["crypto_realtime_reload"] = {
            "status": "success",
            "enabled": reload_status.get("enabled"),
            "running": reload_status.get("running"),
            "enabled_stream_count": len(reload_status.get("enabled_streams") or []),
            "reload_count": reload_status.get("reload_count"),
            "last_reload_at": reload_status.get("last_reload_at"),
        }
    except Exception as exc:
        logger.exception("Failed to reload crypto realtime collectors after subscription settings update.")
        runtime["crypto_realtime_reload"] = {
            "status": "error",
            "message": str(exc),
        }

    try:
        auto_refresh_status = await reload_crypto_auto_refresh(
            reason="market_data_subscription_settings_updated"
        )
        runtime["crypto_auto_refresh_reload"] = {
            "status": "success",
            "enabled": auto_refresh_status.get("enabled"),
            "running": auto_refresh_status.get("running"),
            "active_resource_count": auto_refresh_status.get("active_resource_count"),
            "reload_count": auto_refresh_status.get("reload_count"),
            "last_reload_at": auto_refresh_status.get("last_reload_at"),
        }
    except Exception as exc:
        logger.exception("Failed to reload crypto auto-refresh after subscription settings update.")
        runtime["crypto_auto_refresh_reload"] = {
            "status": "error",
            "message": str(exc),
        }

    return response.model_copy(update={"runtime": runtime})
