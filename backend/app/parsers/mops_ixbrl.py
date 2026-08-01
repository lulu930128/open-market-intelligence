from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


PARSER_VERSION = "mops-ixbrl-v4"


class MopsIxbrlParseError(ValueError):
    """Raised when an official filing cannot satisfy the bounded parser contract."""


@dataclass(frozen=True, slots=True)
class IxbrlContext:
    context_id: str
    entity_identifier: str | None
    start_date: date | None
    end_date: date | None
    instant_date: date | None
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CanonicalFinancialFact:
    fact_key: str
    concept: str
    context_ref: str
    metric_code: str
    source_label: str
    source_value: Decimal
    source_value_text: str
    source_unit: str
    unit_inference_source: str
    currency: str | None
    statement_type: str
    period_kind: str
    period_scope: str
    period_start: date | None
    period_end: date
    months_covered: int | None
    fiscal_year: int
    fiscal_quarter: int
    consolidation_scope: str
    attribution_scope: str
    eps_kind: str
    presentation_role: str
    source_share_basis_id: str
    source_restated: bool | None
    source_restated_status: str


@dataclass(frozen=True, slots=True)
class ParsedMopsIxbrl:
    stock_id: str
    filing_fiscal_year: int
    filing_fiscal_quarter: int
    report_id: str
    contexts: tuple[IxbrlContext, ...]
    units: tuple[tuple[str, tuple[str, ...]], ...]
    facts: tuple[CanonicalFinancialFact, ...]
    numeric_fact_count: int


_CANONICAL_CONCEPTS: dict[str, tuple[str, str, str, str]] = {
    "BasicEarningsLossPerShare": ("basic_eps", "per_share", "parent", "basic"),
    "DilutedEarningsLossPerShare": (
        "diluted_eps",
        "per_share",
        "parent",
        "diluted",
    ),
    "Revenue": ("revenue", "income", "company", "not_applicable"),
    "GrossProfit": ("gross_profit", "income", "company", "not_applicable"),
    "ProfitLossFromOperatingActivities": (
        "operating_income",
        "income",
        "company",
        "not_applicable",
    ),
    "ProfitLoss": ("net_income", "income", "company", "not_applicable"),
    "ProfitLossAttributableToOwnersOfParent": (
        "net_income_attributable_parent",
        "income",
        "parent",
        "not_applicable",
    ),
    "Assets": ("total_assets", "balance", "company", "not_applicable"),
    "Equity": ("total_equity", "balance", "company", "not_applicable"),
    "EquityAttributableToOwnersOfParent": (
        "parent_equity",
        "balance",
        "parent",
        "not_applicable",
    ),
    "IssuedCapital": (
        "issued_capital",
        "balance",
        "company",
        "not_applicable",
    ),
}
_CHARSET_RE = re.compile(br"charset\s*=\s*[\"']?\s*([a-zA-Z0-9._-]+)", re.I)
_NUMBER_DASHES = frozenset({"", "-", "－", "—", "–", "N/A", "n/a"})


def decode_mops_html(payload: bytes) -> str:
    """Decode MOPS HTML by transport/meta evidence, not the XML declaration.

    Official inline-XBRL pages currently carry a Big5 HTML declaration while an
    embedded XML declaration may claim UTF-8. The HTML declaration is the
    authoritative byte-level signal for this source.
    """

    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig")
    match = _CHARSET_RE.search(payload[:8192])
    declared = match.group(1).decode("ascii", errors="ignore").lower() if match else ""
    encodings = (
        ("cp950", "big5", "big5-hkscs", "utf-8")
        if declared in {"big5", "big-5", "cp950", "ms950"}
        else ("utf-8", "cp950", "big5")
    )
    failures: list[str] = []
    for encoding in encodings:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError as exc:
            failures.append(f"{encoding}:{exc.start}")
    raise MopsIxbrlParseError(
        "official MOPS payload could not be decoded; " + ", ".join(failures)
    )


def _tag_local_name(tag: Tag) -> str:
    return str(tag.name or "").split(":")[-1].lower()


def _attribute(tag: Tag, local_name: str) -> str | None:
    expected = local_name.lower()
    for name, value in tag.attrs.items():
        if str(name).split(":")[-1].lower() != expected:
            continue
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value)
    return None


def _find_descendant(tag: Tag, local_name: str) -> Tag | None:
    expected = local_name.lower()
    return tag.find(
        lambda item: isinstance(item, Tag) and _tag_local_name(item) == expected
    )


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise MopsIxbrlParseError(f"invalid XBRL date: {value!r}") from exc


def _parse_context(tag: Tag) -> IxbrlContext:
    context_id = str(_attribute(tag, "id") or "").strip()
    if not context_id:
        raise MopsIxbrlParseError("XBRL context is missing id")
    identifier = _find_descendant(tag, "identifier")
    start = _find_descendant(tag, "startdate")
    end = _find_descendant(tag, "enddate")
    instant = _find_descendant(tag, "instant")
    dimensions: list[tuple[str, str]] = []
    for member in tag.find_all(
        lambda item: isinstance(item, Tag)
        and _tag_local_name(item) in {"explicitmember", "typedmember"}
    ):
        dimensions.append(
            (
                str(_attribute(member, "dimension") or "").strip(),
                member.get_text(" ", strip=True),
            )
        )
    return IxbrlContext(
        context_id=context_id,
        entity_identifier=identifier.get_text(strip=True) if identifier else None,
        start_date=_parse_iso_date(start.get_text(strip=True) if start else None),
        end_date=_parse_iso_date(end.get_text(strip=True) if end else None),
        instant_date=_parse_iso_date(instant.get_text(strip=True) if instant else None),
        dimensions=tuple(dimensions),
    )


def _parse_decimal(text: str, sign: str | None) -> Decimal | None:
    normalized = text.strip().replace(",", "").replace("\u00a0", "")
    if normalized in _NUMBER_DASHES:
        return None
    negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
    if negative_parentheses:
        normalized = normalized[1:-1].strip()
    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise MopsIxbrlParseError(f"invalid numeric XBRL fact: {text!r}") from exc
    if negative_parentheses or sign == "-":
        value = -abs(value)
    return value


def _quarter_end(fiscal_year: int, fiscal_quarter: int) -> date:
    return {
        1: date(fiscal_year, 3, 31),
        2: date(fiscal_year, 6, 30),
        3: date(fiscal_year, 9, 30),
        4: date(fiscal_year, 12, 31),
    }[fiscal_quarter]


def _quarter_for_date(value: date) -> int | None:
    return {3: 1, 6: 2, 9: 3, 12: 4}.get(value.month)


def _months_covered(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _quarter_start(fiscal_year: int, fiscal_quarter: int) -> date:
    return {
        1: date(fiscal_year, 1, 1),
        2: date(fiscal_year, 4, 1),
        3: date(fiscal_year, 7, 1),
        4: date(fiscal_year, 10, 1),
    }[fiscal_quarter]


def _period_contract(
    *,
    context: IxbrlContext,
    filing_fiscal_year: int,
    filing_fiscal_quarter: int,
) -> tuple[str, str, str, date | None, date, int | None, int, int] | None:
    filing_end = _quarter_end(filing_fiscal_year, filing_fiscal_quarter)
    comparative_end = filing_end.replace(year=filing_end.year - 1)
    period_end = context.instant_date or context.end_date
    if period_end not in {filing_end, comparative_end}:
        return None
    role = "current_period" if period_end == filing_end else "comparative_period"
    fiscal_quarter = _quarter_for_date(period_end)
    if fiscal_quarter is None:
        return None
    if context.instant_date is not None:
        return (
            role,
            "instant",
            "instant_period_end",
            None,
            context.instant_date,
            None,
            context.instant_date.year,
            fiscal_quarter,
        )
    if context.start_date is None or context.end_date is None:
        return None
    months = _months_covered(context.start_date, context.end_date)
    fiscal_year = context.end_date.year
    ytd_start = date(fiscal_year, 1, 1)
    if (
        context.start_date == ytd_start
        and months == fiscal_quarter * 3
    ):
        period_scope = {
            1: "ytd_3m",
            2: "ytd_6m",
            3: "ytd_9m",
            4: "annual_12m",
        }[fiscal_quarter]
    elif (
        fiscal_quarter in {2, 3, 4}
        and context.start_date == _quarter_start(fiscal_year, fiscal_quarter)
        and months == 3
    ):
        period_scope = "discrete_3m"
    else:
        return None
    return (
        role,
        "duration",
        period_scope,
        context.start_date,
        context.end_date,
        months,
        fiscal_year,
        fiscal_quarter,
    )


def _unit_contract(
    *,
    metric_code: str,
    unit_ref: str,
    units: dict[str, tuple[str, ...]],
    scale: int,
    raw_value: Decimal,
) -> tuple[Decimal, str, str | None]:
    measures = units.get(unit_ref)
    if not measures:
        raise MopsIxbrlParseError(f"XBRL fact references unknown unit: {unit_ref!r}")
    lowered = " ".join(measures).lower()
    if metric_code in {"basic_eps", "diluted_eps"}:
        if "twd" not in lowered or "shares" not in lowered:
            raise MopsIxbrlParseError(
                f"EPS fact uses unexpected unit {unit_ref!r}: {measures!r}"
            )
        return raw_value * (Decimal(10) ** scale), "TWD_per_share", "TWD"
    if "twd" not in lowered:
        raise MopsIxbrlParseError(
            f"monetary fact uses unexpected unit {unit_ref!r}: {measures!r}"
        )
    value_thousands = raw_value * (Decimal(10) ** (scale - 3))
    return value_thousands, "TWD_thousand", "TWD"


def parse_mops_ixbrl(
    payload: bytes | str,
    *,
    stock_id: str,
    fiscal_year: int,
    fiscal_quarter: int,
    report_id: str,
    source_share_basis_id: str,
) -> ParsedMopsIxbrl:
    if fiscal_quarter not in {1, 2, 3, 4}:
        raise ValueError("fiscal_quarter must be between 1 and 4")
    text = decode_mops_html(payload) if isinstance(payload, bytes) else payload
    # Inline XBRL is namespace- and attribute-case-sensitive. Parsing it as
    # generic HTML can silently discard valid facts in some regulated-industry
    # MOPS tables, notably interim bank EPS rows. The recovery XML parser keeps
    # the semantic XBRL nodes while tolerating the surrounding filing markup.
    soup = BeautifulSoup(text, "lxml-xml")

    contexts: dict[str, IxbrlContext] = {}
    for tag in soup.find_all(
        lambda item: isinstance(item, Tag) and _tag_local_name(item) == "context"
    ):
        context = _parse_context(tag)
        contexts[context.context_id] = context
    if not contexts:
        raise MopsIxbrlParseError("official filing contains no XBRL contexts")

    units: dict[str, tuple[str, ...]] = {}
    for tag in soup.find_all(
        lambda item: isinstance(item, Tag) and _tag_local_name(item) == "unit"
    ):
        unit_id = str(_attribute(tag, "id") or "").strip()
        measures = tuple(
            measure.get_text(" ", strip=True)
            for measure in tag.find_all(
                lambda item: isinstance(item, Tag)
                and _tag_local_name(item) == "measure"
            )
        )
        if unit_id:
            units[unit_id] = measures
    if not units:
        raise MopsIxbrlParseError("official filing contains no XBRL units")

    facts_by_key: dict[str, CanonicalFinancialFact] = {}
    numeric_fact_count = 0
    for tag in soup.find_all(
        lambda item: isinstance(item, Tag)
        and _tag_local_name(item) == "nonfraction"
    ):
        numeric_fact_count += 1
        concept = str(_attribute(tag, "name") or "").strip()
        local_concept = concept.split(":")[-1]
        contract = _CANONICAL_CONCEPTS.get(local_concept)
        if contract is None:
            continue
        context_ref = str(_attribute(tag, "contextref") or "").strip()
        context = contexts.get(context_ref)
        if context is None:
            raise MopsIxbrlParseError(
                f"canonical fact {concept!r} references unknown context {context_ref!r}"
            )
        if context.entity_identifier not in {None, stock_id} or context.dimensions:
            continue
        period = _period_contract(
            context=context,
            filing_fiscal_year=fiscal_year,
            filing_fiscal_quarter=fiscal_quarter,
        )
        if period is None:
            continue
        source_text = tag.get_text(" ", strip=True)
        raw_value = _parse_decimal(
            source_text,
            str(_attribute(tag, "sign") or "") or None,
        )
        if (
            raw_value is None
            or str(_attribute(tag, "nil") or "").lower() == "true"
        ):
            continue
        try:
            scale = int(str(_attribute(tag, "scale") or "0"))
        except ValueError as exc:
            raise MopsIxbrlParseError(
                f"canonical fact {concept!r} has invalid scale"
            ) from exc
        unit_ref = str(_attribute(tag, "unitref") or "").strip()
        metric_code, statement_type, attribution_scope, eps_kind = contract
        source_value, source_unit, currency = _unit_contract(
            metric_code=metric_code,
            unit_ref=unit_ref,
            units=units,
            scale=scale,
            raw_value=raw_value,
        )
        (
            presentation_role,
            period_kind,
            period_scope,
            period_start,
            period_end,
            months_covered,
            fact_fiscal_year,
            fact_fiscal_quarter,
        ) = period
        fact_key = f"{concept}|{context_ref}|{presentation_role}"
        metadata: dict[str, Any] = {
            "parser_version": PARSER_VERSION,
            "concept": concept,
            "context_ref": context_ref,
            "unit_ref": unit_ref,
            "unit_measures": list(units[unit_ref]),
            "xbrl_scale": scale,
            "xbrl_decimals": _attribute(tag, "decimals"),
            "xbrl_format": _attribute(tag, "format"),
            "stored_unit": source_unit,
        }
        fact = CanonicalFinancialFact(
            fact_key=fact_key,
            concept=concept,
            context_ref=context_ref,
            metric_code=metric_code,
            source_label=local_concept,
            source_value=source_value,
            source_value_text=source_text,
            source_unit=source_unit,
            unit_inference_source=json.dumps(
                metadata,
                ensure_ascii=False,
                sort_keys=True,
            ),
            currency=currency,
            statement_type=statement_type,
            period_kind=period_kind,
            period_scope=period_scope,
            period_start=period_start,
            period_end=period_end,
            months_covered=months_covered,
            fiscal_year=fact_fiscal_year,
            fiscal_quarter=fact_fiscal_quarter,
            consolidation_scope=(
                "consolidated" if report_id.upper() == "C" else "individual"
            ),
            attribution_scope=attribution_scope,
            eps_kind=eps_kind,
            presentation_role=presentation_role,
            source_share_basis_id=source_share_basis_id,
            source_restated=False if presentation_role == "current_period" else None,
            source_restated_status=(
                "not_restated"
                if presentation_role == "current_period"
                else "unknown"
            ),
        )
        existing = facts_by_key.get(fact_key)
        if existing is not None and existing != fact:
            raise MopsIxbrlParseError(
                f"conflicting duplicate canonical fact: {fact_key}"
            )
        facts_by_key[fact_key] = fact
    if not facts_by_key:
        raise MopsIxbrlParseError(
            "official filing contains no canonical financial facts for target period"
        )
    return ParsedMopsIxbrl(
        stock_id=stock_id,
        filing_fiscal_year=fiscal_year,
        filing_fiscal_quarter=fiscal_quarter,
        report_id=report_id,
        contexts=tuple(contexts.values()),
        units=tuple(sorted(units.items())),
        facts=tuple(
            sorted(
                facts_by_key.values(),
                key=lambda item: (
                    item.period_end,
                    item.presentation_role,
                    item.metric_code,
                    item.fact_key,
                ),
            )
        ),
        numeric_fact_count=numeric_fact_count,
    )


__all__ = [
    "CanonicalFinancialFact",
    "IxbrlContext",
    "MopsIxbrlParseError",
    "PARSER_VERSION",
    "ParsedMopsIxbrl",
    "decode_mops_html",
    "parse_mops_ixbrl",
]
