from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timezone
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    SourceRegistry,
    StockMaster,
    TaiwanEtfInavSnapshot,
    TaiwanEtfNavDaily,
    TaiwanEtfPcfComponent,
    TaiwanEtfPcfSnapshot,
    TaiwanEtfProfile,
)
from app.market.providers.tw_etf import (
    MOPS_ETF_NAV_URL,
    TWSE_ETF_PROFILE_URL,
    TaiwanEtfNavRecord,
    TaiwanEtfProfileRecord,
    fetch_mops_etf_nav_daily,
    fetch_twse_etf_profile,
    find_etf_nav_record,
)
from app.market.financial_valuation import resolve_latest_completed_daily_close
from app.market.providers.tw_etf_contracts import (
    TaiwanEtfInavRecord,
    TaiwanEtfInstrumentIdentity,
    TaiwanEtfPcfRecord,
)
from app.market.providers.tw_etf_issuers import canonicalize_taiwan_etf_identity
from app.market.providers.tw_etf_registry import (
    DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY,
    TaiwanEtfProviderRegistry,
)
from app.market.trading_calendar import (
    is_taiwan_trading_day,
    latest_released_trading_day,
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
    taiwan_market_session_phase,
    taiwan_now,
)
from app.market.tw_etf_resources import (
    build_taiwan_etf_resource_states,
    classify_taiwan_etf_strategy,
)
from app.market.tw_etf_valuation import (
    TaiwanEtfValuationMetric,
    compose_taiwan_etf_valuation,
    missing_valuation_metric,
    valuation_metric,
)
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.stocks.instruments import is_taiwan_etf, normalize_taiwan_instrument_type


logger = logging.getLogger(__name__)
ETF_NAV_RELEASE_TIME = time(hour=21)
ETF_INAV_CURRENT_MAX_AGE_SECONDS = 90
ETF_INAV_DELAYED_MAX_AGE_SECONDS = 15 * 60
ETF_INAV_RETENTION_PER_STOCK = 1200


class TaiwanEtfNotFoundError(Exception):
    pass


class TaiwanEtfNotApplicableError(Exception):
    pass


def _get_etf_master(db: Session, stock_id: str) -> StockMaster:
    normalized_id = stock_id.strip().upper()
    stock = db.query(StockMaster).filter(StockMaster.stock_id == normalized_id).first()
    if stock is None:
        raise TaiwanEtfNotFoundError(f"Taiwan security stock_id={normalized_id} was not found.")
    if not is_taiwan_etf(stock.instrument_type, stock_id=stock.stock_id):
        raise TaiwanEtfNotApplicableError(
            f"Taiwan security stock_id={normalized_id} is not registered as an ETF."
        )
    return stock


def _latest_nav(db: Session, stock_id: str) -> TaiwanEtfNavDaily | None:
    return (
        db.query(TaiwanEtfNavDaily)
        .filter(TaiwanEtfNavDaily.stock_id == stock_id)
        .order_by(TaiwanEtfNavDaily.nav_date.desc(), TaiwanEtfNavDaily.id.desc())
        .first()
    )


def _latest_pcf(db: Session, stock_id: str) -> TaiwanEtfPcfSnapshot | None:
    return (
        db.query(TaiwanEtfPcfSnapshot)
        .filter(TaiwanEtfPcfSnapshot.stock_id == stock_id)
        .order_by(
            TaiwanEtfPcfSnapshot.effective_date.desc(),
            TaiwanEtfPcfSnapshot.id.desc(),
        )
        .first()
    )


def _latest_inav(db: Session, stock_id: str) -> TaiwanEtfInavSnapshot | None:
    return (
        db.query(TaiwanEtfInavSnapshot)
        .filter(TaiwanEtfInavSnapshot.stock_id == stock_id)
        .order_by(
            TaiwanEtfInavSnapshot.observed_at.desc(),
            TaiwanEtfInavSnapshot.id.desc(),
        )
        .first()
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _etf_provider_identity(
    stock: StockMaster,
    profile: TaiwanEtfProfile | None,
) -> TaiwanEtfInstrumentIdentity:
    return canonicalize_taiwan_etf_identity(
        TaiwanEtfInstrumentIdentity(
            stock_id=stock.stock_id,
            market=stock.market,
            issuer_name=profile.issuer_name if profile else None,
            stock_name=stock.stock_name,
            fund_short_name=profile.fund_short_name if profile else None,
            fund_name=profile.fund_name if profile else None,
            fund_name_en=profile.fund_name_en if profile else None,
        )
    )


def _expected_inav_date(checked_at: datetime, session_phase: str) -> date:
    if is_taiwan_trading_day(checked_at.date()) and session_phase in {
        "regular",
        "closing_auction",
        "post_close",
    }:
        return checked_at.date()
    return previous_taiwan_trading_day(checked_at.date(), include_value=False)


def _expected_pcf_date(checked_at: datetime) -> date:
    if is_taiwan_trading_day(checked_at.date()):
        return checked_at.date()
    return next_taiwan_trading_day(checked_at.date(), include_value=False)


def _inav_freshness(
    inav: TaiwanEtfInavSnapshot | None,
    *,
    checked_at: datetime,
    session_phase: str,
    expected_date: date,
) -> tuple[str, int | None]:
    if inav is None:
        return "missing", None
    observed_at = _as_utc(inav.observed_at)
    checked_utc = _as_utc(checked_at)
    age_seconds = max(int((checked_utc - observed_at).total_seconds()), 0)
    observed_date = observed_at.astimezone(checked_at.tzinfo).date()
    if observed_date < expected_date:
        return "stale", age_seconds
    if session_phase in {"regular", "closing_auction"}:
        if age_seconds <= ETF_INAV_CURRENT_MAX_AGE_SECONDS:
            return "current", age_seconds
        if age_seconds <= ETF_INAV_DELAYED_MAX_AGE_SECONDS:
            return "delayed", age_seconds
        return "stale", age_seconds
    return "closed", age_seconds


def _profile_dict(profile: TaiwanEtfProfile) -> dict[str, Any]:
    return {
        "report_date": profile.report_date,
        "fund_short_name": profile.fund_short_name,
        "fund_name": profile.fund_name,
        "fund_name_en": profile.fund_name_en,
        "fund_type": profile.fund_type,
        "benchmark_name": profile.benchmark_name,
        "is_customized_index": profile.is_customized_index,
        "investment_scope": profile.investment_scope,
        "has_performance_benchmark": profile.has_performance_benchmark,
        "performance_benchmark_name": profile.performance_benchmark_name,
        "has_foreign_components": profile.has_foreign_components,
        "tax_id": profile.tax_id,
        "established_date": profile.established_date,
        "listed_date": profile.listed_date,
        "fund_manager": profile.fund_manager,
        "issued_units": profile.issued_units,
        "custodian": profile.custodian,
        "issuer_name": profile.issuer_name,
        "source": profile.source,
        "source_url": profile.source_url,
        "fetched_at": profile.fetched_at,
    }


def _nav_dict(nav: TaiwanEtfNavDaily) -> dict[str, Any]:
    return {
        "nav_date": nav.nav_date,
        "issuer_name": nav.issuer_name,
        "fund_name": nav.fund_name,
        "nav": nav.nav,
        "previous_nav": nav.previous_nav,
        "nav_change": nav.nav_change,
        "nav_change_pct": nav.nav_change_pct,
        "close_price": nav.close_price,
        "premium_discount_pct": nav.premium_discount_pct,
        "benchmark_name": nav.benchmark_name,
        "benchmark_date": nav.benchmark_date,
        "benchmark_close": nav.benchmark_close,
        "benchmark_previous_close": nav.benchmark_previous_close,
        "benchmark_change": nav.benchmark_change,
        "benchmark_change_pct": nav.benchmark_change_pct,
        "source": nav.source,
        "source_url": nav.source_url,
        "fetched_at": nav.fetched_at,
    }


def _pcf_dict(
    db: Session,
    pcf: TaiwanEtfPcfSnapshot,
) -> dict[str, Any]:
    components = (
        db.query(TaiwanEtfPcfComponent)
        .filter(TaiwanEtfPcfComponent.snapshot_id == pcf.id)
        .order_by(TaiwanEtfPcfComponent.order_index.asc())
        .all()
    )
    return {
        "effective_date": pcf.effective_date,
        "reference_date": pcf.reference_date,
        "fund_id": pcf.fund_id,
        "fund_name": pcf.fund_name,
        "full_name": pcf.full_name,
        "name_en": pcf.name_en,
        "total_net_assets": pcf.total_net_assets,
        "issued_units": pcf.issued_units,
        "unit_nav": pcf.unit_nav,
        "creation_unit": pcf.creation_unit,
        "estimated_creation_value": pcf.estimated_creation_value,
        "estimated_cash_component": pcf.estimated_cash_component,
        "unit_change": pcf.unit_change,
        "actual_cash_component": pcf.actual_cash_component,
        "redemption_method": pcf.redemption_method,
        "component_count": len(components),
        "components": [
            {
                "source_section": component.source_section,
                "asset_type": component.asset_type,
                "symbol": component.symbol,
                "name": component.name,
                "name_en": component.name_en,
                "contract_month": component.contract_month,
                "quantity": component.quantity,
                "weight_pct": component.weight_pct,
                "cash_in_lieu": component.cash_in_lieu,
                "minimum_creation": component.minimum_creation,
                "order_index": component.order_index,
            }
            for component in components
        ],
        "source_updated_at": pcf.source_updated_at,
        "source": pcf.source,
        "source_url": pcf.source_url,
        "fetched_at": pcf.fetched_at,
    }


def _inav_dict(inav: TaiwanEtfInavSnapshot) -> dict[str, Any]:
    return {
        "observed_at": inav.observed_at,
        "fund_short_name": inav.fund_short_name,
        "investment_area": inav.investment_area,
        "estimated_nav": inav.estimated_nav,
        "nav_change": inav.nav_change,
        "market_price": inav.market_price,
        "price_change": inav.price_change,
        "premium_discount_pct": inav.premium_discount_pct,
        "source": inav.source,
        "source_url": inav.source_url,
        "fetched_at": inav.fetched_at,
    }


def _date_status(value_date: date, expected_date: date) -> str:
    if value_date == expected_date:
        return "current"
    if value_date < expected_date:
        return "stale"
    return "invalid"


def _daily_market_price_metric(
    db: Session,
    *,
    stock_id: str,
    nav: TaiwanEtfNavDaily | None,
    checked_at: datetime,
    expected_nav_date: date,
) -> TaiwanEtfValuationMetric:
    resolution = resolve_latest_completed_daily_close(
        db,
        stock_id=stock_id,
        as_of=checked_at,
    )
    if resolution.status == "ready" and resolution.price is not None:
        source = (
            db.get(SourceRegistry, resolution.source_id)
            if resolution.source_id is not None
            else None
        )
        return valuation_metric(
            value=resolution.price,
            as_of_date=resolution.trade_date,
            observed_at=resolution.price_as_of,
            fetched_at=None,
            source=resolution.source_name,
            source_url=source.endpoint_url if source is not None else None,
            basis=resolution.price_basis,
            status="current",
            issue_codes=resolution.issue_codes,
        )

    if (
        nav is not None
        and nav.close_price is not None
        and nav.nav_date <= expected_nav_date
    ):
        return valuation_metric(
            value=nav.close_price,
            as_of_date=nav.nav_date,
            observed_at=None,
            fetched_at=nav.fetched_at,
            source=nav.source,
            source_url=nav.source_url,
            basis="mops_daily_nav_close",
            status=_date_status(nav.nav_date, expected_nav_date),
            issue_codes=resolution.issue_codes,
        )

    return missing_valuation_metric(
        basis=resolution.price_basis,
        status=resolution.status,
        issue_codes=resolution.issue_codes,
    )


def _daily_nav_metric(
    *,
    nav: TaiwanEtfNavDaily | None,
    pcf: TaiwanEtfPcfSnapshot | None,
    pcf_unit_nav_is_daily_nav: bool,
    expected_nav_date: date,
) -> TaiwanEtfValuationMetric:
    candidates: list[tuple[int, TaiwanEtfValuationMetric]] = []
    if nav is not None and nav.nav is not None and nav.nav_date <= expected_nav_date:
        candidates.append(
            (
                0,
                valuation_metric(
                    value=nav.nav,
                    as_of_date=nav.nav_date,
                    observed_at=None,
                    fetched_at=nav.fetched_at,
                    source=nav.source,
                    source_url=nav.source_url,
                    basis="mops_daily_nav",
                    status=_date_status(nav.nav_date, expected_nav_date),
                ),
            )
        )
    if (
        pcf_unit_nav_is_daily_nav
        and pcf is not None
        and pcf.unit_nav is not None
        and pcf.reference_date is not None
        and pcf.reference_date <= expected_nav_date
    ):
        candidates.append(
            (
                1,
                valuation_metric(
                    value=pcf.unit_nav,
                    as_of_date=pcf.reference_date,
                    observed_at=pcf.source_updated_at,
                    fetched_at=pcf.fetched_at,
                    source=pcf.source,
                    source_url=pcf.source_url,
                    basis="pcf_unit_nav",
                    status=_date_status(pcf.reference_date, expected_nav_date),
                ),
            )
        )
    usable_candidates = [
        candidate
        for candidate in candidates
        if candidate[1].value is not None
    ]
    if usable_candidates:
        return max(
            usable_candidates,
            key=lambda candidate: (
                candidate[1].as_of_date == expected_nav_date,
                candidate[1].as_of_date or date.min,
                -candidate[0],
            ),
        )[1]

    issue_codes = ["valuation_daily_nav_missing"]
    if pcf is not None and pcf.unit_nav is not None:
        if not pcf_unit_nav_is_daily_nav:
            issue_codes.append("valuation_pcf_unit_nav_not_eligible")
        elif pcf.reference_date is None:
            issue_codes.append("valuation_pcf_unit_nav_reference_date_missing")
        elif pcf.reference_date > expected_nav_date:
            issue_codes.append("valuation_pcf_unit_nav_future_dated")
    return missing_valuation_metric(
        basis="daily_nav",
        issue_codes=tuple(issue_codes),
    )


def _intraday_valuation_metrics(
    inav: TaiwanEtfInavSnapshot | None,
    *,
    checked_at: datetime,
    inav_status: str,
) -> tuple[TaiwanEtfValuationMetric, TaiwanEtfValuationMetric]:
    if inav is None:
        return (
            missing_valuation_metric(
                basis="issuer_intraday_market_price",
                status=inav_status,
                issue_codes=("valuation_intraday_market_price_missing",),
            ),
            missing_valuation_metric(
                basis="issuer_intraday_estimated_nav",
                status=inav_status,
                issue_codes=("valuation_intraday_nav_missing",),
            ),
        )
    observed_at = _as_utc(inav.observed_at)
    observed_date = observed_at.astimezone(checked_at.tzinfo).date()
    market_price = valuation_metric(
        value=inav.market_price,
        as_of_date=observed_date,
        observed_at=observed_at,
        fetched_at=inav.fetched_at,
        source=inav.source,
        source_url=inav.source_url,
        basis="issuer_intraday_market_price",
        status=inav_status,
        issue_codes=(
            ()
            if inav.market_price is not None
            else ("valuation_intraday_market_price_missing",)
        ),
    )
    estimated_nav = valuation_metric(
        value=inav.estimated_nav,
        as_of_date=observed_date,
        observed_at=observed_at,
        fetched_at=inav.fetched_at,
        source=inav.source,
        source_url=inav.source_url,
        basis="issuer_intraday_estimated_nav",
        status=inav_status,
    )
    return market_price, estimated_nav


def get_taiwan_etf_overview(
    db: Session,
    stock_id: str,
    *,
    now: datetime | None = None,
    refresh_result: dict[str, Any] | None = None,
    provider_registry: TaiwanEtfProviderRegistry = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY,
) -> dict[str, Any]:
    stock = _get_etf_master(db, stock_id)
    checked_at = taiwan_now(now)
    expected_nav_date = latest_released_trading_day(
        release_time=ETF_NAV_RELEASE_TIME,
        now=checked_at,
    )
    profile = (
        db.query(TaiwanEtfProfile)
        .filter(TaiwanEtfProfile.stock_id == stock.stock_id)
        .first()
    )
    nav = _latest_nav(db, stock.stock_id)
    pcf = _latest_pcf(db, stock.stock_id)
    inav = _latest_inav(db, stock.stock_id)
    nav_is_current = bool(nav and nav.nav_date >= expected_nav_date)
    provider_binding = provider_registry.resolve(_etf_provider_identity(stock, profile))
    pcf_provider = provider_binding.pcf if provider_binding else None
    inav_provider = provider_binding.intraday_nav if provider_binding else None
    pcf_source_url = (
        pcf_provider.source_url_for(stock.stock_id) if pcf_provider else ""
    )
    inav_source_url = (
        inav_provider.source_url_for(stock.stock_id) if inav_provider else ""
    )
    pcf_supported = pcf_provider is not None
    inav_supported = inav_provider is not None
    session_phase = taiwan_market_session_phase(checked_at)
    expected_pcf_date = _expected_pcf_date(checked_at)
    pcf_status = (
        "not_supported"
        if not pcf_supported
        else "missing"
        if pcf is None
        else "current"
        if pcf.effective_date >= expected_pcf_date
        else "stale"
    )
    expected_inav_date = _expected_inav_date(checked_at, session_phase)
    if inav_supported:
        inav_status, inav_age_seconds = _inav_freshness(
            inav,
            checked_at=checked_at,
            session_phase=session_phase,
            expected_date=expected_inav_date,
        )
    else:
        inav_status, inav_age_seconds = "not_supported", None

    daily_market_price = _daily_market_price_metric(
        db,
        stock_id=stock.stock_id,
        nav=nav,
        checked_at=checked_at,
        expected_nav_date=expected_nav_date,
    )
    canonical_daily_nav = _daily_nav_metric(
        nav=nav,
        pcf=pcf,
        pcf_unit_nav_is_daily_nav=bool(
            pcf_provider and pcf_provider.unit_nav_is_daily_nav
        ),
        expected_nav_date=expected_nav_date,
    )
    intraday_market_price, canonical_intraday_nav = _intraday_valuation_metrics(
        inav,
        checked_at=checked_at,
        inav_status=inav_status,
    )
    valuation = compose_taiwan_etf_valuation(
        expected_nav_date=expected_nav_date,
        session_phase=session_phase,
        inav_status=inav_status,
        daily_market_price=daily_market_price,
        daily_nav=canonical_daily_nav,
        intraday_market_price=intraday_market_price,
        intraday_nav=canonical_intraday_nav,
    )
    profile_payload = _profile_dict(profile) if profile else None
    pcf_payload = _pcf_dict(db, pcf) if pcf else None
    inav_payload = _inav_dict(inav) if inav else None
    strategy = classify_taiwan_etf_strategy(
        stock_name=stock.stock_name,
        profile=profile_payload,
    )
    resource_states = build_taiwan_etf_resource_states(
        strategy=strategy,
        profile=profile_payload,
        valuation=valuation,
        pcf=pcf_payload,
        pcf_status=pcf_status,
        pcf_supported=pcf_supported,
        component_exposure_supported=bool(
            pcf_provider and pcf_provider.includes_component_exposure
        ),
        intraday_nav=inav_payload,
        inav_status=inav_status,
        inav_supported=inav_supported,
    )

    if profile is not None and nav_is_current:
        overview_status = "current"
    elif profile is None and nav is None:
        overview_status = "missing"
    elif nav is not None and not nav_is_current:
        overview_status = "stale"
    else:
        overview_status = "partial"

    warnings: list[str] = []
    if profile is None:
        warnings.append("尚無 ETF 基本資料 cache。")
    if nav is None:
        warnings.append("尚無 ETF 盤後日淨值 cache。")
    elif not nav_is_current:
        warnings.append(
            f"ETF 盤後日淨值停留在 {nav.nav_date.isoformat()}，"
            f"目前預期交易日為 {expected_nav_date.isoformat()}。"
        )
    if stock.market.upper() != "TWSE":
        warnings.append("第一版官方 ETF profile／NAV provider coverage 僅涵蓋 TWSE 上市 ETF。")
    if pcf_supported:
        if pcf is None:
            warnings.append("尚無 ETF PCF／成分曝險 cache。")
        elif pcf_status == "stale":
            warnings.append(
                f"ETF PCF 生效日停留在 {pcf.effective_date.isoformat()}，"
                f"目前預期日期為 {expected_pcf_date.isoformat()}。"
            )
    else:
        warnings.append("ETF provider_not_connected：此發行商尚未接入 PCF／成分曝險。")
    if inav_supported:
        if inav is None:
            warnings.append("尚無 ETF 盤中估計淨值 cache。")
        elif inav_status in {"delayed", "stale"}:
            warnings.append(
                f"ETF 盤中估計淨值狀態為 {inav_status}，"
                f"來源時間為 {_as_utc(inav.observed_at).isoformat()}。"
            )
    else:
        warnings.append("ETF provider_not_connected：此發行商尚未接入盤中 iNAV。")
    if refresh_result:
        warnings.extend(
            f"{resource} 更新失敗：{message}"
            for resource, message in refresh_result.get("errors", {}).items()
        )

    sources = [
        {
            "resource": "profile",
            "provider": "twse_openapi",
            "source_url": TWSE_ETF_PROFILE_URL,
            "status": "current" if profile is not None else "missing",
            "observed_date": profile.report_date if profile else None,
            "fetched_at": profile.fetched_at if profile else None,
        },
        {
            "resource": "daily_close_nav",
            "provider": "mops",
            "source_url": MOPS_ETF_NAV_URL,
            "status": "current" if nav_is_current else ("stale" if nav else "missing"),
            "observed_date": nav.nav_date if nav else None,
            "fetched_at": nav.fetched_at if nav else None,
        },
        {
            "resource": "pcf",
            "provider": (
                pcf.source
                if pcf is not None
                else provider_binding.provider
                if pcf_provider is not None and provider_binding is not None
                else "not_connected"
            ),
            "source_url": (
                pcf.source_url
                if pcf is not None and pcf.source_url
                else pcf_source_url
                if pcf_provider is not None
                else ""
            ),
            "status": pcf_status,
            "observed_date": pcf.effective_date if pcf else None,
            "fetched_at": pcf.fetched_at if pcf else None,
        },
        {
            "resource": "intraday_estimated_nav",
            "provider": (
                inav.source
                if inav is not None
                else provider_binding.provider
                if inav_provider is not None and provider_binding is not None
                else "not_connected"
            ),
            "source_url": (
                inav.source_url
                if inav is not None and inav.source_url
                else inav_source_url
                if inav_provider is not None
                else ""
            ),
            "status": inav_status,
            "observed_date": (
                _as_utc(inav.observed_at).astimezone(checked_at.tzinfo).date()
                if inav
                else None
            ),
            "fetched_at": inav.fetched_at if inav else None,
        },
    ]
    return {
        "stock_id": stock.stock_id,
        "stock_name": stock.stock_name,
        "market": stock.market,
        "instrument_type": normalize_taiwan_instrument_type(stock.instrument_type),
        "status": overview_status,
        "capabilities": {
            "price_chart": True,
            "technical_analysis": True,
            "quote_depth": True,
            "institutional_flow": True,
            "broker_branch": True,
            "etf_profile": True,
            "daily_close_nav": True,
            "intraday_estimated_nav": inav_supported,
            "pcf": pcf_supported,
            "component_exposure": bool(
                pcf_provider and pcf_provider.includes_component_exposure
            ),
            "holdings": False,
            "company_revenue": False,
            "company_financials": False,
        },
        "profile": profile_payload,
        "daily_nav": _nav_dict(nav) if nav else None,
        "pcf": pcf_payload,
        "intraday_nav": inav_payload,
        "valuation": valuation,
        "strategy": strategy,
        "resource_states": resource_states,
        "freshness": {
            "status": "current" if nav_is_current else ("stale" if nav else "missing"),
            "timezone": "Asia/Taipei",
            "nav_release_time": ETF_NAV_RELEASE_TIME.strftime("%H:%M"),
            "expected_nav_date": expected_nav_date,
            "latest_nav_date": nav.nav_date if nav else None,
            "nav_is_current": nav_is_current,
            "profile_report_date": profile.report_date if profile else None,
            "expected_pcf_date": expected_pcf_date if pcf_supported else None,
            "latest_pcf_date": pcf.effective_date if pcf else None,
            "pcf_status": pcf_status,
            "expected_inav_date": expected_inav_date if inav_supported else None,
            "latest_inav_at": inav.observed_at if inav else None,
            "inav_status": inav_status,
            "inav_age_seconds": inav_age_seconds,
            "session_phase": session_phase,
            "refresh_recommended": (
                profile is None
                or not nav_is_current
                or (pcf_supported and pcf_status in {"missing", "stale"})
                or (
                    inav_supported
                    and session_phase in {"regular", "closing_auction"}
                    and inav_status in {"missing", "delayed", "stale"}
                )
            ),
            "checked_at": checked_at,
        },
        "sources": sources,
        "warnings": warnings,
        "refresh": refresh_result,
    }


def _upsert_profile(
    db: Session,
    stock: StockMaster,
    record: TaiwanEtfProfileRecord,
    fetched_at: datetime,
) -> TaiwanEtfProfile:
    profile = (
        db.query(TaiwanEtfProfile)
        .filter(TaiwanEtfProfile.stock_id == stock.stock_id)
        .first()
    )
    if profile is None:
        profile = TaiwanEtfProfile(stock_id=stock.stock_id)
        db.add(profile)
    for field in (
        "report_date",
        "fund_short_name",
        "fund_name",
        "fund_name_en",
        "fund_type",
        "benchmark_name",
        "is_customized_index",
        "investment_scope",
        "has_performance_benchmark",
        "performance_benchmark_name",
        "has_foreign_components",
        "tax_id",
        "established_date",
        "listed_date",
        "fund_manager",
        "issued_units",
        "custodian",
    ):
        setattr(profile, field, getattr(record, field))
    profile.market = stock.market
    profile.source = "twse_openapi"
    profile.source_url = TWSE_ETF_PROFILE_URL
    profile.fetched_at = fetched_at
    stock.stock_name = stock.stock_name or record.fund_short_name
    return profile


def _upsert_nav(
    db: Session,
    record: TaiwanEtfNavRecord,
    fetched_at: datetime,
) -> TaiwanEtfNavDaily:
    nav = (
        db.query(TaiwanEtfNavDaily)
        .filter(TaiwanEtfNavDaily.stock_id == record.stock_id)
        .filter(TaiwanEtfNavDaily.nav_date == record.nav_date)
        .first()
    )
    if nav is None:
        nav = TaiwanEtfNavDaily(stock_id=record.stock_id, nav_date=record.nav_date)
        db.add(nav)
    for field in (
        "issuer_name",
        "fund_name",
        "nav",
        "previous_nav",
        "nav_change",
        "nav_change_pct",
        "close_price",
        "premium_discount_pct",
        "benchmark_name",
        "benchmark_date",
        "benchmark_close",
        "benchmark_previous_close",
        "benchmark_change",
        "benchmark_change_pct",
    ):
        setattr(nav, field, getattr(record, field))
    nav.source = "mops"
    nav.source_url = MOPS_ETF_NAV_URL
    nav.fetched_at = fetched_at
    return nav


def _upsert_pcf(
    db: Session,
    record: TaiwanEtfPcfRecord,
    fetched_at: datetime,
    *,
    provider: str,
    source_url: str,
) -> TaiwanEtfPcfSnapshot:
    snapshot = (
        db.query(TaiwanEtfPcfSnapshot)
        .filter(TaiwanEtfPcfSnapshot.stock_id == record.stock_id)
        .filter(TaiwanEtfPcfSnapshot.effective_date == record.effective_date)
        .first()
    )
    if snapshot is None:
        snapshot = TaiwanEtfPcfSnapshot(
            stock_id=record.stock_id,
            effective_date=record.effective_date,
        )
        db.add(snapshot)
    for field in (
        "reference_date",
        "fund_id",
        "fund_name",
        "full_name",
        "name_en",
        "total_net_assets",
        "issued_units",
        "unit_nav",
        "creation_unit",
        "estimated_creation_value",
        "estimated_cash_component",
        "unit_change",
        "actual_cash_component",
        "redemption_method",
        "source_updated_at",
    ):
        setattr(snapshot, field, getattr(record, field))
    snapshot.source = provider
    snapshot.source_url = source_url
    snapshot.fetched_at = fetched_at
    db.flush()
    (
        db.query(TaiwanEtfPcfComponent)
        .filter(TaiwanEtfPcfComponent.snapshot_id == snapshot.id)
        .delete(synchronize_session=False)
    )
    for component in record.components:
        db.add(
            TaiwanEtfPcfComponent(
                snapshot_id=snapshot.id,
                source_section=component.source_section,
                asset_type=component.asset_type,
                symbol=component.symbol,
                name=component.name,
                name_en=component.name_en,
                contract_month=component.contract_month,
                quantity=component.quantity,
                weight_pct=component.weight_pct,
                cash_in_lieu=component.cash_in_lieu,
                minimum_creation=component.minimum_creation,
                order_index=component.order_index,
            )
        )
    return snapshot


def _upsert_inav(
    db: Session,
    record: TaiwanEtfInavRecord,
    fetched_at: datetime,
    *,
    provider: str,
    source_url: str,
) -> TaiwanEtfInavSnapshot:
    observed_at = _as_utc(record.observed_at)
    snapshot = (
        db.query(TaiwanEtfInavSnapshot)
        .filter(TaiwanEtfInavSnapshot.stock_id == record.stock_id)
        .filter(TaiwanEtfInavSnapshot.observed_at == observed_at)
        .first()
    )
    if snapshot is None:
        snapshot = TaiwanEtfInavSnapshot(
            stock_id=record.stock_id,
            observed_at=observed_at,
        )
        db.add(snapshot)
    for field in (
        "fund_short_name",
        "investment_area",
        "estimated_nav",
        "nav_change",
        "market_price",
        "price_change",
        "premium_discount_pct",
    ):
        setattr(snapshot, field, getattr(record, field))
    snapshot.source = provider
    snapshot.source_url = source_url
    snapshot.fetched_at = fetched_at
    db.flush()
    expired_ids = [
        row_id
        for (row_id,) in (
            db.query(TaiwanEtfInavSnapshot.id)
            .filter(TaiwanEtfInavSnapshot.stock_id == record.stock_id)
            .order_by(
                TaiwanEtfInavSnapshot.observed_at.desc(),
                TaiwanEtfInavSnapshot.id.desc(),
            )
            .offset(ETF_INAV_RETENTION_PER_STOCK)
            .limit(ETF_INAV_RETENTION_PER_STOCK)
            .all()
        )
    ]
    if expired_ids:
        (
            db.query(TaiwanEtfInavSnapshot)
            .filter(TaiwanEtfInavSnapshot.id.in_(expired_ids))
            .delete(synchronize_session=False)
        )
    return snapshot


def _record_refresh_event(
    db: Session,
    *,
    provider: str,
    resource: str,
    target: str,
    source_url: str,
    error: BaseException | None,
) -> None:
    failure = provider_http_failure(error) if error else None
    try:
        record_provider_event(
            db,
            market="tw",
            provider=provider,
            resource=resource,
            target=target,
            status=failure.status if failure else ("error" if error else "success"),
            event_type="etf_refresh",
            http_status_code=failure.http_status_code if failure else None,
            rate_limited=failure.rate_limited if failure else False,
            retry_after_seconds=failure.retry_after_seconds if failure else None,
            source_url=failure.source_url if failure else source_url,
            message=f"Taiwan ETF {resource} refresh {'failed' if error else 'succeeded'}.",
            error_message=str(error) if error else None,
        )
    except Exception:
        db.rollback()
        logger.warning("Failed to record Taiwan ETF provider event.", exc_info=True)


def refresh_taiwan_etf(
    db: Session,
    stock_id: str,
    *,
    refresh_profile: bool = True,
    refresh_nav: bool = True,
    refresh_pcf: bool = False,
    refresh_inav: bool = False,
    target_nav_date: date | None = None,
    target_pcf_date: date | None = None,
    now: datetime | None = None,
    fetch_profile: Callable[[str], TaiwanEtfProfileRecord] = fetch_twse_etf_profile,
    fetch_nav: Callable[[date], tuple[TaiwanEtfNavRecord, ...]] = fetch_mops_etf_nav_daily,
    fetch_pcf: Callable[..., TaiwanEtfPcfRecord] | None = None,
    fetch_inav: Callable[[str], TaiwanEtfInavRecord] | None = None,
    provider_registry: TaiwanEtfProviderRegistry = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY,
) -> dict[str, Any]:
    stock = _get_etf_master(db, stock_id)
    if not any((refresh_profile, refresh_nav, refresh_pcf, refresh_inav)):
        raise ValueError("At least one ETF resource must be selected for refresh.")

    local_now = taiwan_now(now)
    expected_nav_date = latest_released_trading_day(
        release_time=ETF_NAV_RELEASE_TIME,
        now=local_now,
    )
    resolved_nav_date = target_nav_date or expected_nav_date
    if resolved_nav_date > expected_nav_date:
        raise ValueError("ETF NAV target date cannot be later than the latest released trading day.")
    if refresh_nav and not is_taiwan_trading_day(resolved_nav_date):
        raise ValueError("ETF NAV target date must be a Taiwan trading day.")
    if target_pcf_date is not None:
        if not is_taiwan_trading_day(target_pcf_date):
            raise ValueError("ETF PCF target date must be a Taiwan trading day.")
        latest_allowed_pcf_date = next_taiwan_trading_day(
            local_now.date(),
            include_value=False,
        )
        if target_pcf_date > latest_allowed_pcf_date:
            raise ValueError("ETF PCF target date cannot exceed the next Taiwan trading day.")

    requested_resources = [
        resource
        for resource, enabled in (
            ("profile", refresh_profile),
            ("daily_close_nav", refresh_nav),
            ("pcf", refresh_pcf),
            ("intraday_estimated_nav", refresh_inav),
        )
        if enabled
    ]
    refreshed_resources: list[str] = []
    errors: dict[str, str] = {}
    attempts: list[tuple[str, str, str, BaseException | None]] = []
    request_count = 0
    refreshed_pcf_date: date | None = None
    refreshed_inav_at: datetime | None = None

    if stock.market.upper() != "TWSE":
        errors.update(
            {
                resource: "第一版 provider coverage 僅涵蓋 TWSE 上市 ETF。"
                for resource in requested_resources
            }
        )
    else:
        fetched_at = datetime.now(timezone.utc)
        if refresh_profile:
            request_count += 1
            try:
                record = fetch_profile(stock.stock_id)
                _upsert_profile(db, stock, record, fetched_at)
                refreshed_resources.append("profile")
                attempts.append(("twse_openapi", "etf_profile", TWSE_ETF_PROFILE_URL, None))
            except Exception as exc:
                errors["profile"] = str(exc)
                attempts.append(("twse_openapi", "etf_profile", TWSE_ETF_PROFILE_URL, exc))

        if refresh_nav:
            request_count += 1
            try:
                nav_record = find_etf_nav_record(fetch_nav(resolved_nav_date), stock.stock_id)
                nav = _upsert_nav(db, nav_record, fetched_at)
                profile = (
                    db.query(TaiwanEtfProfile)
                    .filter(TaiwanEtfProfile.stock_id == stock.stock_id)
                    .first()
                )
                if profile is not None and nav.issuer_name:
                    profile.issuer_name = nav.issuer_name
                refreshed_resources.append("daily_close_nav")
                attempts.append(("mops", "etf_daily_nav", MOPS_ETF_NAV_URL, None))
            except Exception as exc:
                errors["daily_close_nav"] = str(exc)
                attempts.append(("mops", "etf_daily_nav", MOPS_ETF_NAV_URL, exc))

        profile = (
            db.query(TaiwanEtfProfile)
            .filter(TaiwanEtfProfile.stock_id == stock.stock_id)
            .first()
        )
        provider_binding = provider_registry.resolve(_etf_provider_identity(stock, profile))
        pcf_provider = provider_binding.pcf if provider_binding else None
        inav_provider = provider_binding.intraday_nav if provider_binding else None
        pcf_source_url = (
            pcf_provider.source_url_for(stock.stock_id) if pcf_provider else ""
        )
        inav_source_url = (
            inav_provider.source_url_for(stock.stock_id) if inav_provider else ""
        )
        if refresh_pcf:
            if pcf_provider is None or provider_binding is None:
                errors["pcf"] = (
                    "ETF provider_not_connected：此發行商尚未接入 PCF／成分曝險。"
                )
            else:
                request_count += pcf_provider.request_count
                try:
                    pcf_fetcher = fetch_pcf or pcf_provider.fetch
                    pcf_record = pcf_fetcher(
                        stock.stock_id,
                        target_date=target_pcf_date,
                    )
                    _upsert_pcf(
                        db,
                        pcf_record,
                        fetched_at,
                        provider=provider_binding.provider,
                        source_url=pcf_source_url,
                    )
                    refreshed_pcf_date = pcf_record.effective_date
                    refreshed_resources.append("pcf")
                    attempts.append(
                        (
                            provider_binding.provider,
                            "etf_pcf",
                            pcf_source_url,
                            None,
                        )
                    )
                except Exception as exc:
                    errors["pcf"] = str(exc)
                    attempts.append(
                        (
                            provider_binding.provider,
                            "etf_pcf",
                            pcf_source_url,
                            exc,
                        )
                    )

        if refresh_inav:
            if inav_provider is None or provider_binding is None:
                errors["intraday_estimated_nav"] = (
                    "ETF provider_not_connected：此發行商尚未接入盤中 iNAV。"
                )
            else:
                request_count += inav_provider.request_count
                try:
                    inav_fetcher = fetch_inav or inav_provider.fetch
                    inav_record = inav_fetcher(stock.stock_id)
                    _upsert_inav(
                        db,
                        inav_record,
                        fetched_at,
                        provider=provider_binding.provider,
                        source_url=inav_source_url,
                    )
                    refreshed_inav_at = inav_record.observed_at
                    refreshed_resources.append("intraday_estimated_nav")
                    attempts.append(
                        (
                            provider_binding.provider,
                            "etf_intraday_estimated_nav",
                            inav_source_url,
                            None,
                        )
                    )
                except Exception as exc:
                    errors["intraday_estimated_nav"] = str(exc)
                    attempts.append(
                        (
                            provider_binding.provider,
                            "etf_intraday_estimated_nav",
                            inav_source_url,
                            exc,
                        )
                    )

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    for provider, resource, source_url, error in attempts:
        _record_refresh_event(
            db,
            provider=provider,
            resource=resource,
            target=stock.stock_id,
            source_url=source_url,
            error=error,
        )

    refresh_result = {
        "requested_resources": requested_resources,
        "refreshed_resources": refreshed_resources,
        "request_count": request_count,
        "target_nav_date": resolved_nav_date if refresh_nav else None,
        "target_pcf_date": refreshed_pcf_date or target_pcf_date,
        "inav_observed_at": refreshed_inav_at,
        "errors": errors,
    }
    return get_taiwan_etf_overview(
        db,
        stock.stock_id,
        now=local_now,
        refresh_result=refresh_result,
        provider_registry=provider_registry,
    )
