from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.crypto_market.assets import SUBSCRIPTION_ALWAYS_ON, get_crypto_asset
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    COINGECKO_PROVIDER,
    COINGLASS_PROVIDER,
    OMI_LOCAL_PROVIDER,
    PERPETUAL,
    SPOT,
    ProviderInstrument,
    normalize_provider,
    normalize_symbol,
    list_provider_instruments,
)
from app.crypto_market.realtime import crypto_realtime_store
from app.crypto_market.ws_runtime import (
    crypto_realtime_collector_status,
    crypto_realtime_enabled_stream_specs,
)
from app.db.models import (
    CryptoCvdHistory,
    CryptoDerivativesMetric,
    CryptoLiquidationEvent,
    CryptoLiquidationHeatmapCell,
    CryptoLongShortRatioHistory,
    CryptoMarketCapSnapshot,
    CryptoOrderBookSnapshot,
    CryptoOhlcvBar,
    CryptoSpreadSnapshot,
    CryptoTickerSnapshot,
)
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.observability.source_health_contract import (
    generated_at as _generated_at,
    summarize_source_health,
)


@dataclass(frozen=True)
class CryptoSourceHealthEntry:
    resource: str
    provider: str
    target: str
    status: str
    ok: bool
    row_count: int
    required: bool = True
    latest_fetched_at: datetime | None = None
    latest_data_key: str | None = None
    data_quality: str = "unknown"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "provider": self.provider,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "required": self.required,
            "latest_fetched_at": self.latest_fetched_at.isoformat() if self.latest_fetched_at else None,
            "latest_data_key": self.latest_data_key,
            "data_quality": self.data_quality,
            "reason": self.reason,
        }


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return max(int((current - observed).total_seconds()), 0)


def _status_for_latest(
    *,
    row_count: int,
    latest_fetched_at: datetime | None,
    now: datetime,
    stale_seconds: int,
) -> tuple[str, bool, str, str]:
    if row_count <= 0:
        return "empty", False, "empty", "No local crypto rows are available for this resource."
    age = _age_seconds(now, latest_fetched_at)
    if age is None:
        return "stale", False, "stale", "Latest crypto row is missing fetched_at."
    if age > stale_seconds:
        return "stale", False, "stale", f"Latest crypto row is {age}s old; threshold is {stale_seconds}s."
    return "live", True, "ok", "Latest crypto row is within the configured freshness threshold."


def _normalize_base(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized or None


def _target_matches_base(target: str, base: str | None) -> bool:
    if base is None or target == "all":
        return True
    return normalize_symbol(target).split("-", maxsplit=1)[0] == base


def _entry_matches_base(entry: dict[str, Any], base: str | None) -> bool:
    if base is None:
        return True
    return _target_matches_base(str(entry.get("target") or ""), base)


def _filter_instruments(
    instruments: list[ProviderInstrument],
    *,
    base: str | None,
    required_only: bool,
) -> list[ProviderInstrument]:
    rows: list[ProviderInstrument] = []
    for instrument in instruments:
        if base is not None and instrument.base_asset != base:
            continue
        if required_only and not _instrument_required(instrument):
            continue
        rows.append(instrument)
    return rows


def _latest_query_entry(
    db: Session,
    *,
    model,
    resource: str,
    provider: str,
    target: str,
    now: datetime,
    stale_seconds: int,
    instrument_type: str | None = None,
    required: bool = True,
) -> CryptoSourceHealthEntry:
    query = db.query(model)
    if hasattr(model, "provider"):
        query = query.filter(model.provider == provider)
    if target != "all" and hasattr(model, "symbol"):
        query = query.filter(model.symbol == target)
    if instrument_type is not None and hasattr(model, "instrument_type"):
        query = query.filter(model.instrument_type == instrument_type)
    row_count = query.count()
    latest = query.order_by(model.fetched_at.desc(), model.id.desc()).first()
    latest_fetched_at = getattr(latest, "fetched_at", None) if latest else None
    latest_data_key = getattr(latest, "provider_symbol", None) if latest else None
    status, ok, data_quality, reason = _status_for_latest(
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        now=now,
        stale_seconds=stale_seconds,
    )
    return CryptoSourceHealthEntry(
        resource=resource,
        provider=provider,
        target=target,
        status=status,
        ok=ok,
        row_count=row_count,
        required=required,
        latest_fetched_at=latest_fetched_at,
        latest_data_key=latest_data_key,
        data_quality=data_quality,
        reason=reason,
    )


def _market_cap_entry(
    db: Session,
    *,
    base: str | None,
    now: datetime,
    stale_seconds: int,
) -> CryptoSourceHealthEntry:
    query = db.query(CryptoMarketCapSnapshot).filter(CryptoMarketCapSnapshot.provider == COINGECKO_PROVIDER)
    target = base or "all"
    if base:
        asset = get_crypto_asset(base)
        if asset and asset.coin_id:
            query = query.filter(CryptoMarketCapSnapshot.coin_id == asset.coin_id)
        else:
            query = query.filter(CryptoMarketCapSnapshot.symbol == base)
    row_count = query.count()
    latest = query.order_by(CryptoMarketCapSnapshot.fetched_at.desc(), CryptoMarketCapSnapshot.id.desc()).first()
    latest_fetched_at = latest.fetched_at if latest else None
    status, ok, data_quality, reason = _status_for_latest(
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        now=now,
        stale_seconds=max(stale_seconds, 3600),
    )
    return CryptoSourceHealthEntry(
        resource="crypto_market_cap",
        provider=COINGECKO_PROVIDER,
        target=target,
        status=status,
        ok=ok,
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        latest_data_key=latest.coin_id if latest else None,
        data_quality=data_quality,
        reason=reason,
    )


def _spread_entry(db: Session, *, base: str | None, now: datetime, stale_seconds: int) -> CryptoSourceHealthEntry:
    target = base.strip().upper() if base else "all"
    query = db.query(CryptoSpreadSnapshot)
    if base:
        query = query.filter(CryptoSpreadSnapshot.base_asset == target)
    row_count = query.count()
    latest = query.order_by(CryptoSpreadSnapshot.observed_at.desc(), CryptoSpreadSnapshot.id.desc()).first()
    latest_observed = latest.observed_at if latest else None
    status, ok, data_quality, reason = _status_for_latest(
        row_count=row_count,
        latest_fetched_at=latest_observed,
        now=now,
        stale_seconds=stale_seconds,
    )
    return CryptoSourceHealthEntry(
        resource="crypto_spread",
        provider="all",
        target=target,
        status=status,
        ok=ok,
        row_count=row_count,
        latest_fetched_at=latest_observed,
        latest_data_key=latest.global_provider if latest else None,
        data_quality=data_quality,
        reason=reason,
    )


def _entry_value(entry: CryptoSourceHealthEntry | dict[str, Any], key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key)


def _summary(entries: list[CryptoSourceHealthEntry | dict[str, Any]]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "error", "disabled"),
    )


def _instrument_required(instrument: ProviderInstrument) -> bool:
    asset = get_crypto_asset(instrument.base_asset)
    if asset is None:
        return True
    return asset.default_subscription_mode == SUBSCRIPTION_ALWAYS_ON


def _base_required(base: str) -> bool:
    asset = get_crypto_asset(base)
    if asset is None:
        return True
    return asset.default_subscription_mode == SUBSCRIPTION_ALWAYS_ON


def build_crypto_source_health(
    db: Session,
    *,
    provider: str | None = None,
    symbol: str | None = None,
    base: str | None = None,
    required_only: bool = False,
    include_events: bool = False,
    max_entries: int | None = None,
    now: datetime | None = None,
    sync_snapshots: bool = False,
) -> dict[str, Any]:
    generated_at = now or _generated_at()
    stale_seconds = max(int(settings.crypto_market_ticker_stale_seconds), 1)
    normalized_provider = normalize_provider(provider) if provider else None
    normalized_symbol = normalize_symbol(symbol) if symbol else None
    normalized_base = _normalize_base(base)
    entries: list[CryptoSourceHealthEntry] = []
    spot_instruments = _filter_instruments(
        list_provider_instruments(
            provider=normalized_provider,
            symbol=normalized_symbol,
            instrument_type=SPOT,
            resource="ticker",
        ),
        base=normalized_base,
        required_only=required_only,
    )
    for instrument in spot_instruments:
        required = _instrument_required(instrument)
        entries.append(
            _latest_query_entry(
                db,
                model=CryptoTickerSnapshot,
                resource="crypto_ticker",
                provider=instrument.provider,
                target=instrument.symbol,
                now=generated_at,
                stale_seconds=stale_seconds,
                instrument_type=SPOT,
                required=required,
            )
        )
        entries.append(
            _latest_query_entry(
                db,
                model=CryptoOrderBookSnapshot,
                resource="crypto_order_book",
                provider=instrument.provider,
                target=instrument.symbol,
                now=generated_at,
                stale_seconds=stale_seconds,
                instrument_type=SPOT,
                required=required,
            )
        )
        entries.append(
            _latest_query_entry(
                db,
                model=CryptoOhlcvBar,
                resource="crypto_ohlcv",
                provider=instrument.provider,
                target=instrument.symbol,
                now=generated_at,
                stale_seconds=max(stale_seconds, 300),
                instrument_type=SPOT,
                required=required,
            )
        )
        if instrument.provider == BINANCE_PROVIDER:
            entries.append(
                _latest_query_entry(
                    db,
                    model=CryptoCvdHistory,
                    resource="crypto_cvd_spot",
                    provider=instrument.provider,
                    target=instrument.symbol,
                    now=generated_at,
                    stale_seconds=max(stale_seconds, 300),
                    instrument_type=SPOT,
                    required=False,
                )
            )

    derivative_instruments = _filter_instruments(
        list_provider_instruments(
            provider=normalized_provider,
            symbol=normalized_symbol,
            instrument_type=PERPETUAL,
            resource="derivatives",
        ),
        base=normalized_base,
        required_only=required_only,
    )
    for instrument in derivative_instruments:
        entries.append(
            _latest_query_entry(
                db,
                model=CryptoDerivativesMetric,
                resource="crypto_derivatives",
                provider=instrument.provider,
                target=instrument.symbol,
                now=generated_at,
                stale_seconds=max(stale_seconds, 300),
                instrument_type=PERPETUAL,
                required=_instrument_required(instrument),
            )
        )
        if "liquidation_event" in instrument.resources:
            entries.append(
                _latest_query_entry(
                    db,
                    model=CryptoLiquidationEvent,
                    resource="crypto_liquidation_event",
                    provider=instrument.provider,
                    target=instrument.symbol,
                    now=generated_at,
                    stale_seconds=max(stale_seconds, 300),
                    instrument_type=PERPETUAL,
                    required=False,
                )
            )
            for heatmap_provider in (COINGLASS_PROVIDER, OMI_LOCAL_PROVIDER):
                entries.append(
                    _latest_query_entry(
                        db,
                        model=CryptoLiquidationHeatmapCell,
                        resource="crypto_liquidation_heatmap",
                        provider=heatmap_provider,
                        target=instrument.symbol,
                        now=generated_at,
                        stale_seconds=max(stale_seconds, 300),
                        instrument_type=PERPETUAL,
                        required=False,
                    )
                )
        if instrument.provider == BINANCE_PROVIDER:
            entries.append(
                _latest_query_entry(
                    db,
                    model=CryptoCvdHistory,
                    resource="crypto_cvd_perpetual",
                    provider=instrument.provider,
                    target=instrument.symbol,
                    now=generated_at,
                    stale_seconds=max(stale_seconds, 300),
                    instrument_type=PERPETUAL,
                    required=False,
                )
            )
        if "long_short_ratio" in instrument.resources:
            entries.append(
                _latest_query_entry(
                    db,
                    model=CryptoLongShortRatioHistory,
                    resource="crypto_long_short_ratio",
                    provider=instrument.provider,
                    target=instrument.symbol,
                    now=generated_at,
                    stale_seconds=max(stale_seconds, 300),
                    instrument_type=PERPETUAL,
                    required=False,
                )
            )
    if not required_only or normalized_base is None or _base_required(normalized_base):
        asset_definition = get_crypto_asset(normalized_base) if normalized_base else None
        if asset_definition is None or asset_definition.market_cap:
            entries.append(
                _market_cap_entry(
                    db,
                    base=normalized_base,
                    now=generated_at,
                    stale_seconds=stale_seconds,
                )
            )
        if asset_definition is None or asset_definition.taiwan_spread:
            entries.append(
                _spread_entry(
                    db,
                    base=normalized_base,
                    now=generated_at,
                    stale_seconds=stale_seconds,
                )
            )
    collector_status = crypto_realtime_collector_status()
    entry_payloads = [entry.to_dict() for entry in entries]
    realtime_entries = crypto_realtime_store.health_entries(
        stream_specs=crypto_realtime_enabled_stream_specs(),
        now=generated_at,
        stale_seconds=max(stale_seconds, settings.crypto_market_ws_message_stale_seconds),
        collector_enabled=bool(collector_status.get("enabled")),
        provider=normalized_provider,
        symbol=normalized_symbol,
    )
    if normalized_base is not None and normalized_symbol is None:
        realtime_entries = [
            entry
            for entry in realtime_entries
            if entry.get("resource") == "crypto_realtime_collector" or _entry_matches_base(entry, normalized_base)
        ]
    if required_only:
        realtime_entries = [
            entry
            for entry in realtime_entries
            if bool(entry.get("required")) or entry.get("resource") == "crypto_realtime_collector"
        ]
    entry_payloads.extend(realtime_entries)
    persistence_status = collector_status.get("persistence")
    if isinstance(persistence_status, dict):
        persistence_enabled = bool(persistence_status.get("enabled"))
        persistence_state = str(persistence_status.get("status") or "unknown")
        pending_count = int(persistence_status.get("pending_count") or 0)
        persisted_count = int(persistence_status.get("persisted_count") or 0)
        dropped_count = int(persistence_status.get("dropped_count") or 0)
        error_count = int(persistence_status.get("error_count") or 0)
        if not persistence_enabled:
            data_quality = "disabled"
            reason = "Realtime persistence is disabled by configuration."
        elif persistence_status.get("last_error"):
            data_quality = "error"
            reason = f"Realtime persistence error: {persistence_status.get('last_error')}"
        elif dropped_count > 0:
            data_quality = "partial"
            reason = f"Realtime persistence is running but dropped {dropped_count} queued update(s)."
        elif error_count > 0:
            data_quality = "partial"
            reason = f"Realtime persistence is running with {error_count} update error(s)."
        elif persistence_status.get("running"):
            data_quality = "ok"
            reason = "Realtime persistence bridge is running."
        else:
            data_quality = "stopped"
            reason = "Realtime persistence bridge is not running."
        entry_payloads.append(
            {
                "resource": "crypto_realtime_persistence",
                "provider": "all",
                "target": "all",
                "status": persistence_state,
                "ok": bool(persistence_status.get("ok")),
                "row_count": persisted_count,
                "required": bool(collector_status.get("enabled")),
                "latest_fetched_at": persistence_status.get("last_flush_completed_at"),
                "latest_data_key": f"pending={pending_count}",
                "data_quality": data_quality,
                "reason": reason,
            }
        )
    if normalized_base is not None and normalized_symbol is None:
        entry_payloads = [
            entry
            for entry in entry_payloads
            if entry.get("resource") in {"crypto_realtime_collector", "crypto_realtime_persistence"}
            or _entry_matches_base(entry, normalized_base)
        ]
    if required_only:
        entry_payloads = [
            entry
            for entry in entry_payloads
            if bool(entry.get("required", True))
            or entry.get("resource") in {"crypto_realtime_collector", "crypto_realtime_persistence"}
        ]
    if max_entries is not None:
        entry_payloads = entry_payloads[: max(1, int(max_entries))]
    if sync_snapshots or include_events:
        entry_dicts = enrich_source_health_entries(
            db,
            market="crypto",
            entries=entry_payloads,
        )
    else:
        entry_dicts = entry_payloads
    if sync_snapshots:
        sync_source_health_snapshots(
            db,
            market="crypto",
            entries=entry_dicts,
            checked_at=generated_at,
        )
    return {
        "kind": "crypto_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "provider": normalized_provider,
            "symbol": normalized_symbol,
            "base": normalized_base,
            "required_only": required_only,
            "include_events": include_events,
        },
        "summary": _summary(entry_payloads),
        "entries": entry_dicts,
    }
