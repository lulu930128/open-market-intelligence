from __future__ import annotations

from typing import Any


SOURCE_REPORTED_EPS_WARNING = "source_reported_eps_not_additive"
SHARE_BASIS_WARNING = "share_basis_unverified"
SINGLE_QUARTER_WARNING = "single_quarter_eps_unavailable"
TTM_WARNING = "ttm_eps_unavailable"
ROE_COMPARABILITY_WARNING = "source_roe_not_period_comparable"


def _source_value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def infer_financial_period_scope(quarter: int | None) -> tuple[str, int | None]:
    if quarter in {1, 2, 3}:
        return "ytd", quarter * 3
    if quarter == 4:
        return "annual", 12
    return "unknown", None


def source_reported_financial_semantics(source: Any) -> dict[str, Any]:
    raw_quarter = _source_value(source, "quarter")
    try:
        quarter = int(raw_quarter) if raw_quarter is not None else None
    except (TypeError, ValueError):
        quarter = None

    period_scope, months_covered = infer_financial_period_scope(quarter)
    raw_eps = _source_value(source, "raw_eps")
    if raw_eps is None:
        raw_eps = _source_value(source, "eps")

    warnings = [SOURCE_REPORTED_EPS_WARNING, SHARE_BASIS_WARNING, TTM_WARNING]
    single_quarter_eps = raw_eps if quarter == 1 else None
    if quarter != 1:
        warnings.append(SINGLE_QUARTER_WARNING)
    if _source_value(source, "roe") is not None or _source_value(source, "roa") is not None:
        warnings.append(ROE_COMPARABILITY_WARNING)
    if period_scope == "unknown":
        warnings.append("period_scope_unknown")
    source_dates = (
        _source_value(source, "report_date"),
        _source_value(source, "released_at"),
        _source_value(source, "filed_at"),
    )
    date_semantics_status = "missing"
    if any(value is not None for value in source_dates):
        date_semantics_status = "unverified_legacy"
        warnings.append("release_date_semantics_unverified")

    scope_suffix = period_scope if period_scope != "unknown" else "unknown_period"
    return {
        "period_scope": period_scope,
        "months_covered": months_covered,
        "flow_semantics": f"source_reported_{scope_suffix}",
        "eps_semantics": f"source_reported_{scope_suffix}",
        "raw_eps": raw_eps,
        "single_quarter_eps": single_quarter_eps,
        "adjusted_eps_ytd": None,
        "ttm_eps": None,
        "source_restated_status": "unknown",
        "share_basis_status": "unverified",
        "date_semantics_status": date_semantics_status,
        "normalization_status": "raw_only",
        "valuation_status": "blocked",
        "decision_usable": False,
        "normalization_warnings": list(dict.fromkeys(warnings)),
    }


def financial_period_scope_label(period_scope: str, months_covered: int | None) -> str:
    if period_scope == "annual":
        return "全年"
    if period_scope == "ytd" and months_covered is not None:
        return f"年初至今 {months_covered} 個月"
    return "期間語意未確認"
