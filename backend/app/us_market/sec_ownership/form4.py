from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any
from xml.etree import ElementTree

from .contracts import (
    Form4Filing,
    Form4Footnote,
    Form4Owner,
    Form4Position,
    Form4SubmissionEntry,
    Form4Transaction,
)


FORM4_PARSER_VERSION = "omi.sec.form4.parser.v1"
SUPPORTED_FORM_TYPES = {"4", "4/A"}


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_cik(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    try:
        return f"{int(text.replace(',', '')):010d}"
    except ValueError:
        return ""


def _date(value: Any) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if len(normalized) == 14 and normalized.isdigit():
        try:
            return datetime.strptime(normalized, "%Y%m%d%H%M%S")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _bool(value: Any) -> bool | None:
    text = (_clean_text(value) or "").lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _decimal_text(value: Any) -> tuple[str | None, tuple[str, ...]]:
    text = _clean_text(value)
    if text is None:
        return None, ()
    normalized = text.replace(",", "")
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        return None, ("USO001_invalid_decimal",)
    if not parsed.is_finite():
        return None, ("USO001_invalid_decimal",)
    return format(parsed, "f"), ()


def _find(element: ElementTree.Element, path: str) -> ElementTree.Element | None:
    current: ElementTree.Element | None = element
    for part in path.split("/"):
        if current is None:
            return None
        current = current.find(f"{{*}}{part}")
    return current


def _findall(element: ElementTree.Element, path: str) -> list[ElementTree.Element]:
    parts = path.split("/")
    current = [element]
    for part in parts:
        next_items: list[ElementTree.Element] = []
        for item in current:
            next_items.extend(item.findall(f"{{*}}{part}"))
        current = next_items
    return current


def _value(element: ElementTree.Element, path: str) -> str | None:
    found = _find(element, path)
    return _clean_text(found.text if found is not None else None)


def _footnote_ids(element: ElementTree.Element) -> tuple[str, ...]:
    values = {
        str(item.attrib.get("id") or "").strip()
        for item in element.iter()
        if item.tag.rsplit("}", 1)[-1] == "footnoteId"
    }
    return tuple(sorted(value for value in values if value))


def _transaction(
    element: ElementTree.Element,
    *,
    row_sequence: int,
    table_type: str,
) -> Form4Transaction:
    shares, shares_issues = _decimal_text(_value(element, "transactionAmounts/transactionShares/value"))
    price, price_issues = _decimal_text(
        _value(element, "transactionAmounts/transactionPricePerShare/value")
    )
    post_shares, post_issues = _decimal_text(
        _value(element, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
    )
    conversion_price, conversion_issues = _decimal_text(
        _value(element, "conversionOrExercisePrice/value")
    )
    underlying_shares, underlying_issues = _decimal_text(
        _value(element, "underlyingSecurity/underlyingSecurityShares/value")
    )
    issue_codes = tuple(
        sorted(
            {
                *shares_issues,
                *price_issues,
                *post_issues,
                *conversion_issues,
                *underlying_issues,
            }
        )
    )
    return Form4Transaction(
        row_sequence=row_sequence,
        table_type=table_type,
        security_title=_value(element, "securityTitle/value"),
        transaction_date=_date(_value(element, "transactionDate/value")),
        deemed_execution_date=_date(_value(element, "deemedExecutionDate/value")),
        transaction_form_type=_value(element, "transactionCoding/transactionFormType"),
        transaction_code=_value(element, "transactionCoding/transactionCode"),
        equity_swap_involved=_bool(_value(element, "transactionCoding/equitySwapInvolved")),
        acquired_disposed_code=_value(
            element,
            "transactionAmounts/transactionAcquiredDisposedCode/value",
        ),
        shares_text=shares,
        price_per_share_text=price,
        post_transaction_shares_text=post_shares,
        direct_indirect_code=_value(
            element,
            "ownershipNature/directOrIndirectOwnership/value",
        ),
        nature_of_ownership=_value(element, "ownershipNature/natureOfOwnership/value"),
        conversion_exercise_price_text=conversion_price,
        exercise_date=_date(_value(element, "exerciseDate/value")),
        expiration_date=_date(_value(element, "expirationDate/value")),
        underlying_security_title=_value(
            element,
            "underlyingSecurity/underlyingSecurityTitle/value",
        ),
        underlying_shares_text=underlying_shares,
        footnote_ids=_footnote_ids(element),
        issue_codes=issue_codes,
    )


def _position(
    element: ElementTree.Element,
    *,
    row_sequence: int,
    table_type: str,
) -> Form4Position:
    post_shares, post_issues = _decimal_text(
        _value(element, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
    )
    conversion_price, conversion_issues = _decimal_text(
        _value(element, "conversionOrExercisePrice/value")
    )
    underlying_shares, underlying_issues = _decimal_text(
        _value(element, "underlyingSecurity/underlyingSecurityShares/value")
    )
    return Form4Position(
        row_sequence=row_sequence,
        table_type=table_type,
        security_title=_value(element, "securityTitle/value"),
        post_transaction_shares_text=post_shares,
        direct_indirect_code=_value(
            element,
            "ownershipNature/directOrIndirectOwnership/value",
        ),
        nature_of_ownership=_value(element, "ownershipNature/natureOfOwnership/value"),
        conversion_exercise_price_text=conversion_price,
        exercise_date=_date(_value(element, "exerciseDate/value")),
        expiration_date=_date(_value(element, "expirationDate/value")),
        underlying_security_title=_value(
            element,
            "underlyingSecurity/underlyingSecurityTitle/value",
        ),
        underlying_shares_text=underlying_shares,
        footnote_ids=_footnote_ids(element),
        issue_codes=tuple(
            sorted({*post_issues, *conversion_issues, *underlying_issues})
        ),
    )


def parse_form4_xml(
    payload: str | bytes,
    *,
    accession_number: str,
    source_url: str,
    filing_date: date | None = None,
    accepted_at: datetime | None = None,
) -> Form4Filing:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ValueError("SEC ownership XML is malformed.") from exc

    form_type = (_value(root, "documentType") or "").upper()
    if form_type not in SUPPORTED_FORM_TYPES:
        raise ValueError(f"Unsupported SEC ownership form type: {form_type or '<missing>'}")
    issuer_cik = _normalize_cik(_value(root, "issuer/issuerCik"))
    issuer_name = _value(root, "issuer/issuerName") or ""
    if not accession_number.strip() or not issuer_cik or not issuer_name:
        raise ValueError("SEC ownership XML is missing accession or issuer identity.")

    owners: list[Form4Owner] = []
    for element in _findall(root, "reportingOwner"):
        owner_cik = _normalize_cik(_value(element, "reportingOwnerId/rptOwnerCik"))
        owner_name = _value(element, "reportingOwnerId/rptOwnerName") or ""
        if not owner_cik or not owner_name:
            raise ValueError("SEC ownership XML contains an owner without identity.")
        owners.append(
            Form4Owner(
                cik=owner_cik,
                name=owner_name,
                is_director=bool(_bool(_value(element, "reportingOwnerRelationship/isDirector"))),
                is_officer=bool(_bool(_value(element, "reportingOwnerRelationship/isOfficer"))),
                is_ten_percent_owner=bool(
                    _bool(_value(element, "reportingOwnerRelationship/isTenPercentOwner"))
                ),
                is_other=bool(_bool(_value(element, "reportingOwnerRelationship/isOther"))),
                officer_title=_value(element, "reportingOwnerRelationship/officerTitle"),
                other_text=_value(element, "reportingOwnerRelationship/otherText"),
            )
        )
    if not owners:
        raise ValueError("SEC ownership XML does not contain a reporting owner.")

    transactions: list[Form4Transaction] = []
    for table_type, path in (
        ("non_derivative", "nonDerivativeTable/nonDerivativeTransaction"),
        ("derivative", "derivativeTable/derivativeTransaction"),
    ):
        for element in _findall(root, path):
            transactions.append(
                _transaction(
                    element,
                    row_sequence=len(transactions) + 1,
                    table_type=table_type,
                )
            )

    positions: list[Form4Position] = []
    for table_type, path in (
        ("non_derivative", "nonDerivativeTable/nonDerivativeHolding"),
        ("derivative", "derivativeTable/derivativeHolding"),
    ):
        for element in _findall(root, path):
            positions.append(
                _position(
                    element,
                    row_sequence=len(positions) + 1,
                    table_type=table_type,
                )
            )

    footnotes = tuple(
        Form4Footnote(
            footnote_id=str(element.attrib.get("id") or "").strip(),
            text=" ".join("".join(element.itertext()).split()),
        )
        for element in _findall(root, "footnotes/footnote")
        if str(element.attrib.get("id") or "").strip()
    )
    issue_codes = tuple(
        sorted(
            {
                code
                for item in (*transactions, *positions)
                for code in item.issue_codes
            }
        )
    )
    return Form4Filing(
        accession_number=accession_number.strip(),
        form_type=form_type,
        schema_version=_value(root, "schemaVersion"),
        period_of_report=_date(_value(root, "periodOfReport")),
        original_submission_date=_date(_value(root, "dateOfOriginalSubmission")),
        filing_date=filing_date,
        accepted_at=accepted_at,
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        issuer_trading_symbol=_value(root, "issuer/issuerTradingSymbol"),
        is_amendment=form_type.endswith("/A"),
        aff10b5_one=_bool(_value(root, "aff10b5One")),
        remarks=_value(root, "remarks"),
        owners=tuple(owners),
        transactions=tuple(transactions),
        positions=tuple(positions),
        footnotes=footnotes,
        source_url=source_url,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        parser_version=FORM4_PARSER_VERSION,
        issue_codes=issue_codes,
    )


def parse_form4_submission_entries(
    payload: dict[str, Any],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
) -> tuple[Form4SubmissionEntry, ...]:
    if limit < 1 or limit > 500:
        raise ValueError("Form 4 submission limit must be between 1 and 500.")
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        raise ValueError("SEC submissions payload is missing filings.recent.")
    forms = recent.get("form", [])
    if not isinstance(forms, list):
        raise ValueError("SEC submissions recent.form must be a list.")

    entries: list[Form4SubmissionEntry] = []
    for index, raw_form in enumerate(forms):
        form_type = str(raw_form or "").strip().upper()
        if form_type not in SUPPORTED_FORM_TYPES:
            continue

        def column(name: str) -> Any:
            values = recent.get(name, [])
            return values[index] if isinstance(values, list) and index < len(values) else None

        accession = _clean_text(column("accessionNumber"))
        filing_date = _date(column("filingDate"))
        primary_document = _clean_text(column("primaryDocument"))
        if not accession or filing_date is None or not primary_document:
            raise ValueError("SEC submissions contains an incomplete Form 4 entry.")
        if from_date and filing_date < from_date:
            continue
        if to_date and filing_date > to_date:
            continue
        entries.append(
            Form4SubmissionEntry(
                accession_number=accession,
                form_type=form_type,
                filing_date=filing_date,
                report_date=_date(column("reportDate")),
                accepted_at=_datetime(column("acceptanceDateTime")),
                primary_document=primary_document,
            )
        )
        if len(entries) >= limit:
            break
    return tuple(entries)


__all__ = [
    "FORM4_PARSER_VERSION",
    "parse_form4_submission_entries",
    "parse_form4_xml",
]
