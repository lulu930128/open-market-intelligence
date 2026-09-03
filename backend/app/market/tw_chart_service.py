"""Atomic Taiwan chart application bundle over canonical Bars and Technical."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.market.index_resolution import project_taiwan_index_quote_side
from app.market.indices import get_market_index_summary
from app.market.public_quote_platform import read_taiwan_public_quote_projection
from app.market.technical_parameters import TechnicalAnalysisParameters
from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.tw_bar_service import (
    TaiwanBarService,
    taiwan_current_session_bar_window,
)
from app.market.tw_technical_service import (
    TaiwanTechnicalSeriesRead,
    TaiwanTechnicalService,
)
from app.market_data.contracts import CanonicalModel


class TaiwanChartSessionScope(str, Enum):
    HISTORY = "history"
    CURRENT_SESSION = "current_session"


class TaiwanChartBundleRead(CanonicalModel):
    contract_version: str = "tw.chart.bundle.v1"
    bars: TaiwanBarSeriesRead
    technical: TaiwanTechnicalSeriesRead
    series_fingerprint: str
    lineage_digest: str
    state_digest: str
    series_revision: str
    session_scope: TaiwanChartSessionScope = TaiwanChartSessionScope.HISTORY
    presentation_trade_date: date | None = None
    quote_side: dict[str, Any] | None = None


class TaiwanChartService:
    """Read one Bar revision and calculate Technical from that exact object."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def read(
        self,
        *,
        instrument_id: str,
        interval: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 500,
        include_partial: bool = True,
        parameters: TechnicalAnalysisParameters | None = None,
        expected_series_revision: str | None = None,
        requested_at: datetime | None = None,
        session_scope: TaiwanChartSessionScope = TaiwanChartSessionScope.HISTORY,
    ) -> TaiwanChartBundleRead:
        presentation_trade_date: date | None = None
        bar_service = TaiwanBarService(self._db)
        if session_scope is TaiwanChartSessionScope.CURRENT_SESSION:
            if from_time is not None or to_time is not None:
                raise ValueError(
                    "current_session chart scope cannot be combined with from/to"
                )
            effective_now, presentation_trade_date, _from_time, _to_time = (
                taiwan_current_session_bar_window(requested_at)
            )
            bars = bar_service.read_current_session_bars(
                instrument_id=instrument_id,
                interval=interval,
                limit=limit,
                include_partial=include_partial,
                requested_at=effective_now,
            )
        else:
            effective_now = requested_at
            bars = bar_service.read_bars(
                instrument_id=instrument_id,
                interval=interval,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                include_partial=include_partial,
                requested_at=effective_now,
            )
        technical = TaiwanTechnicalService().calculate(
            bars,
            parameters=parameters,
            expected_series_revision=(
                expected_series_revision or bars.identity.series_revision
            ),
        )
        quote_side: dict[str, Any] | None = None
        if interval in {"1m", "5m", "15m", "30m", "1h", "4h"}:
            instrument = getattr(bars, "instrument", None)
            if instrument is not None and instrument.instrument_type.value == "index":
                normalized_index_id = str(instrument.symbol or "").strip().upper()
                summary = get_market_index_summary(
                    self._db,
                    force_refresh=False,
                    requested_at=effective_now,
                )
                index_item = next(
                    (
                        item
                        for item in summary.get("indices") or []
                        if isinstance(item, dict)
                        and str(item.get("index_id") or "").strip().upper()
                        == normalized_index_id
                    ),
                    None,
                )
                if index_item is None:
                    raise ValueError(
                        "Canonical Taiwan index context is unavailable for "
                        f"{normalized_index_id or instrument_id}"
                    )
                quote_side = project_taiwan_index_quote_side(index_item)
                if quote_side is None:
                    raise ValueError(
                        "Resolved Taiwan index quote context is unavailable for "
                        f"{normalized_index_id or instrument_id}"
                    )
            elif instrument is not None:
                quote = read_taiwan_public_quote_projection(
                    self._db,
                    stock_id=bars.instrument.symbol,
                    refresh=False,
                    requested_at=effective_now,
                )
                last_price = quote.get("last_trade_price")
                quote_time = quote.get("last_trade_time") or quote.get("event_time")
                freshness = quote.get("freshness")
                freshness = freshness if isinstance(freshness, dict) else {}
                limitations = [
                    str(value)
                    for value in quote.get("limitations") or []
                    if value
                ]
                current_observation = (
                    {
                        "value": last_price,
                        "observed_at": quote_time,
                        "confirmed_at": quote.get("received_at")
                        or quote.get("fetched_at"),
                        "price_semantics": (
                            "current_session_last_trade"
                            if quote.get("session_phase")
                            in {"regular", "closing_auction"}
                            else "latest_completed_session"
                        ),
                        "provider": quote.get("provider"),
                        "source": quote.get("source"),
                        "status": freshness.get("status") or "unknown",
                        "is_fallback": bool(quote.get("fallback_used")),
                        "limitations": limitations,
                        "previous_close": quote.get("previous_close"),
                        "freshness_status": freshness.get("status") or "unknown",
                        "decision_usable": bool(
                            quote.get("price_available")
                            and not freshness.get("is_stale")
                        ),
                    }
                    if last_price is not None
                    else None
                )
                quote_side = {
                    "current_observation": current_observation,
                    "previous_close": quote.get("previous_close"),
                    "price_diagnostics": {
                        "history_price_source": None,
                        "latest_history_time": None,
                        "latest_history_price": None,
                        "latest_actual_trade_time": quote_time,
                        "latest_actual_trade_price": last_price,
                        "current_price_source": quote.get("source"),
                        "lag_seconds": freshness.get("age_seconds"),
                        "current_trade_available": bool(
                            quote.get("last_trade_available")
                        ),
                        "current_trade_unavailable_reason": (
                            None
                            if quote.get("last_trade_available")
                            else "canonical_public_quote_unavailable"
                        ),
                        "current_price_applied_to_history": False,
                    },
                    "capabilities": {
                        "supports_volume": quote.get("cumulative_volume_lots")
                        is not None,
                        "supports_vwap": True,
                        "supports_price_limit": True,
                        "supports_quote_depth": bool(quote.get("depth_available")),
                    },
                    "source": quote.get("source"),
                    "trade_date": quote.get("trade_date"),
                    "updated_at": quote_time,
                }
        return TaiwanChartBundleRead(
            bars=bars,
            technical=technical,
            series_fingerprint=bars.identity.series_fingerprint,
            lineage_digest=bars.identity.lineage_digest,
            state_digest=bars.identity.state_digest,
            series_revision=bars.identity.series_revision,
            session_scope=session_scope,
            presentation_trade_date=presentation_trade_date,
            quote_side=quote_side,
        )


__all__ = [
    "TaiwanChartBundleRead",
    "TaiwanChartService",
    "TaiwanChartSessionScope",
]
