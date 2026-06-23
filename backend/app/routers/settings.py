from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.settings.refresh_execution import (
    get_refresh_execution_settings,
    update_refresh_execution_settings,
)
from app.settings.schemas import (
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
