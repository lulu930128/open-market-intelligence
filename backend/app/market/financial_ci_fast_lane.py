from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.db.models import (
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_evidence_package import (
    TaiwanFinancialEvidencePackage,
    evidence_package_hash,
)
from app.market.financial_parse_runs import (
    canonical_fact_output_hash,
    get_canonical_parse_run,
)


CI_FAST_LANE_CONTRACT_VERSION = "omi.tw-financial-ci-fast-lane.v1"
CI_FAST_LANE_PERIODS = (
    (2025, 1),
    (2025, 2),
    (2025, 3),
    (2025, 4),
    (2026, 1),
)
CI_FAST_LANE_NORMALIZATION_VERSION = (
    "tw-financial-normalization-v1+mops-ci-fast-lane-v1"
)
OFFICIAL_FILING_KIND = "mops_ixbrl_financial_report"
PARSER_VERSION = "mops-ixbrl-v4"
_STOCK_ID_RE = re.compile(r"^[0-9A-Z]{2,20}$")
_REQUIRED_SCOPE = {
    1: "ytd_3m",
    2: "ytd_6m",
    3: "ytd_9m",
    4: "annual_12m",
}


def _period_label(period: tuple[int, int]) -> str:
    return f"{period[0]}Q{period[1]}"


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _report_id(filing: TaiwanFinancialFiling) -> str:
    if filing.source_document_url:
        value = parse_qs(urlparse(filing.source_document_url).query).get(
            "REPORT_ID",
            [],
        )
        if value and value[0] in {"A", "C"}:
            return value[0]
    document_id = filing.source_document_id.upper()
    if "_AI1." in document_id:
        return "C"
    if "_AI2." in document_id:
        return "A"
    raise ValueError(
        "official filing report scope is not identifiable: "
        f"{filing.source_document_id}"
    )


def _canonical_filing_run(
    db: Session,
    *,
    stock_id: str,
    period: tuple[int, int],
) -> tuple[TaiwanFinancialFiling, TaiwanFinancialParseRun, tuple[TaiwanFinancialStatementFact, ...]]:
    filings = (
        db.query(TaiwanFinancialFiling)
        .filter(
            TaiwanFinancialFiling.stock_id == stock_id,
            TaiwanFinancialFiling.filing_kind == OFFICIAL_FILING_KIND,
            TaiwanFinancialFiling.fiscal_year == period[0],
            TaiwanFinancialFiling.fiscal_quarter == period[1],
        )
        .order_by(TaiwanFinancialFiling.id)
        .all()
    )
    approved: list[tuple[TaiwanFinancialFiling, TaiwanFinancialParseRun]] = []
    for filing in filings:
        run = get_canonical_parse_run(db, filing_id=filing.id)
        if run is not None:
            approved.append((filing, run))
    if not approved:
        raise ValueError(
            f"no approved official parser output for {stock_id} {_period_label(period)}"
        )
    content_hashes = {filing.content_hash for filing, _ in approved}
    if len(content_hashes) != 1:
        raise ValueError(
            "approved filing version conflict: "
            f"{stock_id} {_period_label(period)} hashes={sorted(content_hashes)}"
        )
    filing, run = max(approved, key=lambda item: item[1].id)
    if run.parser_version != PARSER_VERSION:
        raise ValueError(
            f"fast lane requires {PARSER_VERSION}: run={run.id} "
            f"actual={run.parser_version}"
        )
    facts = tuple(
        db.query(TaiwanFinancialStatementFact)
        .filter(TaiwanFinancialStatementFact.parse_run_id == run.id)
        .order_by(TaiwanFinancialStatementFact.fact_key)
        .all()
    )
    if len(facts) != run.fact_count:
        raise ValueError(
            "parse run fact count mismatch: "
            f"run={run.id} declared={run.fact_count} actual={len(facts)}"
        )
    if run.output_hash is None or canonical_fact_output_hash(facts) != run.output_hash:
        raise ValueError(f"immutable parse output hash mismatch: run={run.id}")
    return filing, run, facts


def _one_fact(
    facts: Sequence[TaiwanFinancialStatementFact],
    *,
    stock_id: str,
    label: str,
    metric_code: str,
    fiscal_year: int,
    fiscal_quarter: int,
    period_scope: str,
    presentation_role: str,
) -> TaiwanFinancialStatementFact:
    matches = [
        fact
        for fact in facts
        if fact.metric_code == metric_code
        and fact.fiscal_year == fiscal_year
        and fact.fiscal_quarter == fiscal_quarter
        and fact.period_scope == period_scope
        and fact.presentation_role == presentation_role
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{label} must resolve exactly one fact: "
            f"stock_id={stock_id} matched={len(matches)}"
        )
    return matches[0]


def _validate_eps_fact(
    fact: TaiwanFinancialStatementFact,
    *,
    label: str,
) -> None:
    if fact.eps_kind != "basic" or fact.source_unit != "TWD_per_share":
        raise ValueError(
            f"{label} has invalid EPS semantics: "
            f"eps_kind={fact.eps_kind} unit={fact.source_unit}"
        )
    if not fact.source_share_basis_id:
        raise ValueError(f"{label} is missing source_share_basis_id")
    if fact.source_restated_status == "confirmed":
        raise ValueError(f"{label} requires explicit restatement review")


def build_ci_fast_lane_package(
    db: Session,
    *,
    stock_id: str,
    reviewer: str,
    reviewed_at: datetime,
    package_id: str | None = None,
    periods: Sequence[tuple[int, int]] = CI_FAST_LANE_PERIODS,
) -> tuple[TaiwanFinancialEvidencePackage, dict[str, Any]]:
    """Build one reviewed clone-only factor-1 package from approved filings.

    This function performs no network request and no database write. It refuses
    capital changes, report-scope mixing, restated facts, missing official
    discrete EPS, and cross-filing comparative mismatches.
    """

    normalized_stock_id = stock_id.strip().upper()
    if not _STOCK_ID_RE.fullmatch(normalized_stock_id):
        raise ValueError(f"invalid stock_id: {stock_id!r}")
    normalized_reviewer = reviewer.strip()
    if not normalized_reviewer:
        raise ValueError("reviewer is required")
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include timezone evidence")
    reviewed_at = reviewed_at.astimezone(timezone.utc)
    normalized_periods = tuple(periods)
    if normalized_periods != CI_FAST_LANE_PERIODS:
        raise ValueError(
            "M8 fast lane requires the fixed 2025Q1-2026Q1 acceptance window"
        )

    period_rows = {
        period: _canonical_filing_run(
            db,
            stock_id=normalized_stock_id,
            period=period,
        )
        for period in normalized_periods
    }
    report_ids = {row[0].id: _report_id(row[0]) for row in period_rows.values()}
    distinct_report_ids = set(report_ids.values())
    if len(distinct_report_ids) != 1:
        raise ValueError(
            "fast lane refuses mixed report scopes: "
            f"stock_id={normalized_stock_id} report_ids={sorted(distinct_report_ids)}"
        )
    report_id = next(iter(distinct_report_ids))
    expected_consolidation = "consolidated" if report_id == "C" else "individual"

    sources = {
        row[0].source_id: db.get(SourceRegistry, row[0].source_id)
        for row in period_rows.values()
    }
    if len(sources) != 1 or next(iter(sources.values())) is None:
        raise ValueError("fast lane requires one registered filing source")
    source = next(iter(sources.values()))
    assert source is not None
    if source.reliability_level != "official":
        raise ValueError(
            "fast lane requires an official source: "
            f"{source.source_name} ({source.reliability_level})"
        )

    current_eps: dict[tuple[int, int, str], TaiwanFinancialStatementFact] = {}
    capital_values: dict[str, Decimal] = {}
    for period, (filing, _run, facts) in period_rows.items():
        required_scope = _REQUIRED_SCOPE[period[1]]
        required = _one_fact(
            facts,
            stock_id=normalized_stock_id,
            label=f"{_period_label(period)} current basic EPS",
            metric_code="basic_eps",
            fiscal_year=period[0],
            fiscal_quarter=period[1],
            period_scope=required_scope,
            presentation_role="current_period",
        )
        _validate_eps_fact(required, label=f"{_period_label(period)} {required_scope}")
        if required.consolidation_scope != expected_consolidation:
            raise ValueError(
                "report ID and fact consolidation scope disagree: "
                f"{filing.source_document_id} report_id={report_id} "
                f"fact_scope={required.consolidation_scope}"
            )
        current_eps[(period[0], period[1], required_scope)] = required
        if period[1] in {2, 3}:
            discrete = _one_fact(
                facts,
                stock_id=normalized_stock_id,
                label=f"{_period_label(period)} official discrete EPS",
                metric_code="basic_eps",
                fiscal_year=period[0],
                fiscal_quarter=period[1],
                period_scope="discrete_3m",
                presentation_role="current_period",
            )
            _validate_eps_fact(
                discrete,
                label=f"{_period_label(period)} discrete_3m",
            )
            current_eps[(period[0], period[1], "discrete_3m")] = discrete

        capital = _one_fact(
            facts,
            stock_id=normalized_stock_id,
            label=f"{_period_label(period)} current issued capital",
            metric_code="issued_capital",
            fiscal_year=period[0],
            fiscal_quarter=period[1],
            period_scope="instant_period_end",
            presentation_role="current_period",
        )
        if (
            capital.source_unit != "TWD_thousand"
            or capital.period_kind != "instant"
        ):
            raise ValueError(
                f"{_period_label(period)} has invalid issued-capital semantics"
            )
        capital_values[_period_label(period)] = capital.source_value

    if len(set(capital_values.values())) != 1:
        raise ValueError(
            "issued capital changed across the fast-lane window: "
            f"stock_id={normalized_stock_id} values="
            f"{ {key: _decimal_text(value) for key, value in capital_values.items()} }"
        )

    latest_facts = period_rows[(2026, 1)][2]
    comparative_q1 = _one_fact(
        latest_facts,
        stock_id=normalized_stock_id,
        label="2026Q1 comparative 2025Q1 basic EPS",
        metric_code="basic_eps",
        fiscal_year=2025,
        fiscal_quarter=1,
        period_scope="ytd_3m",
        presentation_role="comparative_period",
    )
    _validate_eps_fact(comparative_q1, label="2026Q1 comparative 2025Q1")
    original_q1 = current_eps[(2025, 1, "ytd_3m")]
    if comparative_q1.source_value != original_q1.source_value:
        raise ValueError(
            "cross-filing comparative EPS mismatch: "
            f"stock_id={normalized_stock_id} original={original_q1.source_value} "
            f"comparative={comparative_q1.source_value}"
        )

    document_ids = {
        period: row[0].source_document_id for period, row in period_rows.items()
    }
    documents = []
    for period, (filing, _run, _facts) in period_rows.items():
        if not filing.source_document_url:
            raise ValueError(
                f"official filing is missing its source URL: {filing.source_document_id}"
            )
        documents.append(
            {
                "document_id": filing.source_document_id,
                "url": filing.source_document_url,
                "description": (
                    f"MOPS official {normalized_stock_id} {_period_label(period)} "
                    f"{'consolidated' if report_id == 'C' else 'individual'} "
                    "Inline XBRL filing used by the M8 factor-1 fast lane."
                ),
                "content_hash": filing.content_hash,
                "content_hash_status": "verified_source_bytes",
            }
        )

    fact_specs = (
        ((2025, 1, "ytd_3m"), ((2025, 1), (2026, 1))),
        ((2025, 2, "discrete_3m"), ((2025, 2),)),
        ((2025, 2, "ytd_6m"), ((2025, 1), (2025, 2))),
        ((2025, 3, "discrete_3m"), ((2025, 3),)),
        ((2025, 3, "ytd_9m"), ((2025, 2), (2025, 3))),
        (
            (2025, 4, "annual_12m"),
            ((2025, 1), (2025, 2), (2025, 3), (2025, 4)),
        ),
        ((2026, 1, "ytd_3m"), ((2026, 1),)),
    )
    adjudications = []
    for fact_identity, evidence_periods in fact_specs:
        fact = current_eps[fact_identity]
        filing = period_rows[(fact_identity[0], fact_identity[1])][0]
        adjudications.append(
            {
                "source_name": source.source_name,
                "fiscal_year": fact.fiscal_year,
                "fiscal_quarter": fact.fiscal_quarter,
                "metric_code": "basic_eps",
                "expected_source_value": fact.source_value,
                "source_share_basis_id": fact.source_share_basis_id,
                "source_restated_status": "not_restated",
                "expected_normalized_value": fact.source_value,
                "evidence_document_ids": [
                    document_ids[period] for period in evidence_periods
                ],
                "source_document_id": filing.source_document_id,
                "presentation_role": "current_period",
                "fact_key": fact.fact_key,
                "period_scope": fact.period_scope,
            }
        )

    capital_value = next(iter(capital_values.values()))
    report_scope = "consolidated" if report_id == "C" else "individual"
    package_payload = {
        "package_version": "omi.tw-financial-evidence.v1",
        "package_id": package_id
        or (
            f"{normalized_stock_id}-mops-ci-fast-lane-{report_scope}-"
            "period-scope-2026q1-v1"
        ),
        "approval_scope": "clone_only",
        "review_status": "approved",
        "reviewer": normalized_reviewer,
        "reviewed_at": reviewed_at,
        "stock_id": normalized_stock_id,
        "mode": "current_comparable",
        "comparison_basis_id": (
            f"{normalized_stock_id}-official-{report_scope}-"
            "presentation-basis-through-2026Q1"
        ),
        "target_basis_date": period_rows[(2026, 1)][0].period_end,
        "normalization_version": CI_FAST_LANE_NORMALIZATION_VERSION,
        "evidence_source_name": source.source_name,
        "sources": [
            {
                "source_name": source.source_name,
                "source_type": source.source_type,
                "category": source.category,
                "endpoint_url": source.endpoint_url,
                "priority": source.priority,
                "reliability_level": source.reliability_level,
            }
        ],
        "documents": documents,
        "actions": [],
        "share_basis_assessment": {
            "status": "verified_unchanged",
            "verification_method": "cross_filing_comparative_reconciliation",
            "rationale": (
                f"All five official {report_scope} filings report current-period "
                f"issued capital of TWD {_decimal_text(capital_value)} thousand. "
                "The 2026Q1 filing presents comparative 2025Q1 basic EPS "
                f"{_decimal_text(comparative_q1.source_value)}, "
                "exactly matching the 2025Q1 current-period filing. Official Q2 "
                "and Q3 discrete EPS contexts are retained directly; YTD arithmetic "
                "is diagnostic only because duration contexts can use different "
                "weighted-average shares. Factor 1 is approved only through 2026Q1."
            ),
            "evidence_document_ids": [
                document_ids[period] for period in normalized_periods
            ],
        },
        "facts": adjudications,
    }
    package = TaiwanFinancialEvidencePackage.model_validate(package_payload)
    audit = {
        "contract_version": CI_FAST_LANE_CONTRACT_VERSION,
        "stock_id": normalized_stock_id,
        "status": "eligible",
        "report_id": report_id,
        "report_scope": report_scope,
        "source_name": source.source_name,
        "periods": [_period_label(period) for period in normalized_periods],
        "filing_ids": {
            _period_label(period): row[0].id for period, row in period_rows.items()
        },
        "parse_runs": {
            _period_label(period): {
                "parse_run_id": row[1].id,
                "output_hash": row[1].output_hash,
                "fact_count": row[1].fact_count,
            }
            for period, row in period_rows.items()
        },
        "issued_capital_twd_thousand": _decimal_text(capital_value),
        "q1_cross_filing_value": _decimal_text(original_q1.source_value),
        "package_id": package.package_id,
        "package_hash": evidence_package_hash(package),
        "boundaries": [
            "clone_only_package_requires_separate_production_promotion",
            "official_discrete_eps_is_authoritative",
            "capital_change_or_restatement_exits_the_fast_lane",
            "package_build_performs_no_network_or_database_write",
        ],
    }
    return package, audit


__all__ = [
    "CI_FAST_LANE_CONTRACT_VERSION",
    "CI_FAST_LANE_NORMALIZATION_VERSION",
    "CI_FAST_LANE_PERIODS",
    "build_ci_fast_lane_package",
]
