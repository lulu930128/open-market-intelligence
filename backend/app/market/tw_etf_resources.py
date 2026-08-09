from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def classify_taiwan_etf_strategy(
    *,
    stock_name: str | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = profile or {}
    candidates = " ".join(
        value
        for value in (
            _text(stock_name),
            _text(profile.get("fund_short_name")),
            _text(profile.get("fund_name")),
            _text(profile.get("fund_type")),
        )
        if value
    )
    if "主動" in candidates:
        management_style = "active"
        benchmark_role = "performance_benchmark"
        benchmark_name = _text(
            profile.get("performance_benchmark_name")
            or profile.get("benchmark_name")
        ) or None
    elif profile and (
        profile.get("benchmark_name")
        or "指數" in _text(profile.get("fund_type"))
    ):
        management_style = "passive"
        benchmark_role = "tracked_index"
        benchmark_name = _text(profile.get("benchmark_name")) or None
    else:
        management_style = "unknown"
        benchmark_role = "unknown"
        benchmark_name = None
    return {
        "management_style": management_style,
        "benchmark_role": benchmark_role,
        "benchmark_name": benchmark_name,
    }


def _resource_state(
    *,
    applicable: bool | None,
    connector_supported: bool,
    status: str,
    reason_code: str | None = None,
    as_of_date: date | None = None,
    observed_at: datetime | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    return {
        "applicable": applicable,
        "connector_supported": connector_supported,
        "status": status,
        "reason_code": reason_code,
        "as_of_date": as_of_date,
        "observed_at": observed_at,
        "source": source,
    }


def _metric_resource_state(metric: dict[str, Any]) -> dict[str, Any]:
    return _resource_state(
        applicable=True,
        connector_supported=True,
        status=_text(metric.get("status")) or "missing",
        reason_code=(
            _text((metric.get("issue_codes") or [None])[0]) or None
        ),
        as_of_date=metric.get("as_of_date"),
        observed_at=metric.get("observed_at"),
        source=_text(metric.get("source")) or None,
    )


def build_taiwan_etf_resource_states(
    *,
    strategy: dict[str, Any],
    profile: dict[str, Any] | None,
    valuation: dict[str, Any],
    pcf: dict[str, Any] | None,
    pcf_status: str,
    pcf_supported: bool,
    component_exposure_supported: bool,
    intraday_nav: dict[str, Any] | None,
    inav_status: str,
    inav_supported: bool,
) -> dict[str, dict[str, Any]]:
    profile = profile or {}
    states: dict[str, dict[str, Any]] = {
        "market_price": _metric_resource_state(valuation["market_price"]),
        "daily_nav": _metric_resource_state(valuation["nav"]),
    }

    if inav_supported:
        states["intraday_nav"] = _resource_state(
            applicable=True,
            connector_supported=True,
            status=inav_status,
            reason_code=(
                "intraday_nav_cache_missing"
                if intraday_nav is None
                else None
            ),
            observed_at=(
                intraday_nav.get("observed_at") if intraday_nav else None
            ),
            source=_text(intraday_nav.get("source")) if intraday_nav else None,
        )
    else:
        states["intraday_nav"] = _resource_state(
            applicable=True,
            connector_supported=False,
            status="provider_not_connected",
            reason_code="intraday_nav_provider_not_connected",
        )

    if pcf_supported:
        states["pcf_summary"] = _resource_state(
            applicable=True,
            connector_supported=True,
            status=pcf_status,
            reason_code="pcf_cache_missing" if pcf is None else None,
            as_of_date=pcf.get("effective_date") if pcf else None,
            observed_at=pcf.get("source_updated_at") if pcf else None,
            source=_text(pcf.get("source")) if pcf else None,
        )
    else:
        states["pcf_summary"] = _resource_state(
            applicable=True,
            connector_supported=False,
            status="provider_not_connected",
            reason_code="pcf_provider_not_connected",
        )

    redemption_method = _text(pcf.get("redemption_method")) if pcf else ""
    if redemption_method == "cash":
        states["pcf_component_basket"] = _resource_state(
            applicable=False,
            connector_supported=component_exposure_supported,
            status="not_applicable",
            reason_code="cash_redemption_has_no_in_kind_basket",
            as_of_date=pcf.get("effective_date") if pcf else None,
            source=_text(pcf.get("source")) if pcf else None,
        )
    elif component_exposure_supported:
        component_count = int(pcf.get("component_count") or 0) if pcf else 0
        states["pcf_component_basket"] = _resource_state(
            applicable=True,
            connector_supported=True,
            status=(
                pcf_status
                if pcf is not None and component_count > 0
                else "missing"
            ),
            reason_code=(
                None
                if pcf is not None and component_count > 0
                else "pcf_component_basket_missing"
            ),
            as_of_date=pcf.get("effective_date") if pcf else None,
            source=_text(pcf.get("source")) if pcf else None,
        )
    else:
        states["pcf_component_basket"] = _resource_state(
            applicable=None,
            connector_supported=False,
            status="provider_not_connected",
            reason_code="pcf_component_basket_provider_not_connected",
        )

    management_style = strategy["management_style"]
    benchmark_name = strategy["benchmark_name"]
    if management_style == "active":
        states["tracked_index"] = _resource_state(
            applicable=False,
            connector_supported=True,
            status="not_applicable",
            reason_code="active_etf_has_no_tracked_index",
        )
        states["performance_benchmark"] = _resource_state(
            applicable=True,
            connector_supported=True,
            status="current" if benchmark_name else "missing",
            reason_code=None if benchmark_name else "performance_benchmark_missing",
            as_of_date=profile.get("report_date"),
            source=_text(profile.get("source")) or None,
        )
        states["index_constituents"] = _resource_state(
            applicable=False,
            connector_supported=False,
            status="not_applicable",
            reason_code="active_etf_has_no_tracked_index_constituents",
        )
    elif management_style == "passive":
        states["tracked_index"] = _resource_state(
            applicable=True,
            connector_supported=True,
            status="current" if benchmark_name else "missing",
            reason_code=None if benchmark_name else "tracked_index_missing",
            as_of_date=profile.get("report_date"),
            source=_text(profile.get("source")) or None,
        )
        states["performance_benchmark"] = _resource_state(
            applicable=False,
            connector_supported=True,
            status="not_applicable",
            reason_code="passive_etf_uses_tracked_index",
        )
        states["index_constituents"] = _resource_state(
            applicable=True,
            connector_supported=False,
            status="provider_not_connected",
            reason_code="index_constituents_provider_not_connected",
        )
    else:
        for resource in ("tracked_index", "performance_benchmark", "index_constituents"):
            states[resource] = _resource_state(
                applicable=None,
                connector_supported=False,
                status="missing",
                reason_code="etf_management_style_unknown",
            )

    states["fund_holdings"] = _resource_state(
        applicable=True,
        connector_supported=False,
        status="provider_not_connected",
        reason_code="fund_holdings_provider_not_connected",
    )
    return states


__all__ = [
    "build_taiwan_etf_resource_states",
    "classify_taiwan_etf_strategy",
]
