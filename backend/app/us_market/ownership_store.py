from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import base64
import binascii
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    USSecFilingReportingOwner,
    USSecOwnershipFiling,
    USSecOwnershipFootnote,
    USSecOwnershipPosition,
    USSecOwnershipSyncState,
    USSecOwnershipTransaction,
    USSecReportingOwner,
    utc_now,
)
from app.us_market.sec_ownership import Form4Filing


INSIDER_CONTRACT_VERSION = "omi.sec.insiders.v1"
FORM4_POSITION_LIMITATION = (
    "Form 4 reports changes and row-level post-transaction amounts; without Forms 3 and 5, "
    "this contract does not claim a complete current insider position."
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _json_list(value: tuple[str, ...] | list[str]) -> str | None:
    return _json(list(value)) if value else None


def _row_hash(value: Any) -> str:
    return hashlib.sha256(_json(asdict(value)).encode("utf-8")).hexdigest()


def _owner_ids_for_filing(db: Session, filing_id: int) -> set[int]:
    return {
        row.reporting_owner_id
        for row in db.query(USSecFilingReportingOwner)
        .filter(USSecFilingReportingOwner.filing_id == filing_id)
        .all()
    }


def _resolve_superseded_accession(
    db: Session,
    *,
    filing: USSecOwnershipFiling,
    owner_ids: set[int],
) -> str | None:
    if not filing.is_amendment or filing.original_submission_date is None:
        return None
    candidates = (
        db.query(USSecOwnershipFiling)
        .filter(USSecOwnershipFiling.issuer_cik == filing.issuer_cik)
        .filter(USSecOwnershipFiling.is_amendment.is_(False))
        .filter(USSecOwnershipFiling.filing_date == filing.original_submission_date)
        .filter(USSecOwnershipFiling.period_of_report == filing.period_of_report)
        .all()
    )
    matches = [
        candidate
        for candidate in candidates
        if _owner_ids_for_filing(db, candidate.id) == owner_ids
    ]
    return matches[0].accession_number if len(matches) == 1 else None


def persist_form4_filing(db: Session, filing: Form4Filing) -> dict[str, Any]:
    existing = (
        db.query(USSecOwnershipFiling)
        .filter(USSecOwnershipFiling.accession_number == filing.accession_number)
        .first()
    )
    if existing is not None:
        if existing.source_sha256 != filing.source_sha256:
            raise ValueError(
                "SEC ownership accession content hash changed; refusing to overwrite append-only filing "
                f"{filing.accession_number}."
            )
        return {
            "filing_id": existing.id,
            "inserted": False,
            "owner_count": 0,
            "transaction_count": 0,
            "position_count": 0,
            "footnote_count": 0,
        }

    row = USSecOwnershipFiling(
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        schema_version=filing.schema_version,
        issuer_cik=filing.issuer_cik,
        issuer_name=filing.issuer_name,
        issuer_trading_symbol=filing.issuer_trading_symbol,
        period_of_report=filing.period_of_report,
        original_submission_date=filing.original_submission_date,
        filing_date=filing.filing_date,
        accepted_at=filing.accepted_at,
        is_amendment=filing.is_amendment,
        aff10b5_one=filing.aff10b5_one,
        remarks=filing.remarks,
        source_url=filing.source_url,
        source_sha256=filing.source_sha256,
        parser_version=filing.parser_version,
        issue_codes_json=_json_list(filing.issue_codes),
        fetched_at=utc_now(),
    )
    db.add(row)
    db.flush()

    owner_ids: set[int] = set()
    for owner in filing.owners:
        owner_row = (
            db.query(USSecReportingOwner)
            .filter(USSecReportingOwner.cik == owner.cik)
            .first()
        )
        if owner_row is None:
            owner_row = USSecReportingOwner(cik=owner.cik, name=owner.name)
            db.add(owner_row)
            db.flush()
        else:
            owner_row.name = owner.name
            owner_row.last_seen_at = utc_now()
        owner_ids.add(owner_row.id)
        db.add(
            USSecFilingReportingOwner(
                filing_id=row.id,
                reporting_owner_id=owner_row.id,
                is_director=owner.is_director,
                is_officer=owner.is_officer,
                is_ten_percent_owner=owner.is_ten_percent_owner,
                is_other=owner.is_other,
                officer_title=owner.officer_title,
                other_text=owner.other_text,
            )
        )

    for item in filing.transactions:
        db.add(
            USSecOwnershipTransaction(
                filing_id=row.id,
                row_sequence=item.row_sequence,
                table_type=item.table_type,
                security_title=item.security_title,
                transaction_date=item.transaction_date,
                deemed_execution_date=item.deemed_execution_date,
                transaction_form_type=item.transaction_form_type,
                transaction_code=item.transaction_code,
                equity_swap_involved=item.equity_swap_involved,
                acquired_disposed_code=item.acquired_disposed_code,
                shares_text=item.shares_text,
                price_per_share_text=item.price_per_share_text,
                post_transaction_shares_text=item.post_transaction_shares_text,
                direct_indirect_code=item.direct_indirect_code,
                nature_of_ownership=item.nature_of_ownership,
                conversion_exercise_price_text=item.conversion_exercise_price_text,
                exercise_date=item.exercise_date,
                expiration_date=item.expiration_date,
                underlying_security_title=item.underlying_security_title,
                underlying_shares_text=item.underlying_shares_text,
                footnote_ids_json=_json_list(item.footnote_ids),
                issue_codes_json=_json_list(item.issue_codes),
                raw_row_hash=_row_hash(item),
            )
        )

    for item in filing.positions:
        db.add(
            USSecOwnershipPosition(
                filing_id=row.id,
                row_sequence=item.row_sequence,
                table_type=item.table_type,
                security_title=item.security_title,
                post_transaction_shares_text=item.post_transaction_shares_text,
                direct_indirect_code=item.direct_indirect_code,
                nature_of_ownership=item.nature_of_ownership,
                conversion_exercise_price_text=item.conversion_exercise_price_text,
                exercise_date=item.exercise_date,
                expiration_date=item.expiration_date,
                underlying_security_title=item.underlying_security_title,
                underlying_shares_text=item.underlying_shares_text,
                footnote_ids_json=_json_list(item.footnote_ids),
                issue_codes_json=_json_list(item.issue_codes),
                raw_row_hash=_row_hash(item),
            )
        )

    for footnote in filing.footnotes:
        db.add(
            USSecOwnershipFootnote(
                filing_id=row.id,
                footnote_id=footnote.footnote_id,
                footnote_text=footnote.text,
            )
        )
    db.flush()
    row.supersedes_accession_number = _resolve_superseded_accession(
        db,
        filing=row,
        owner_ids=owner_ids,
    )
    return {
        "filing_id": row.id,
        "inserted": True,
        "owner_count": len(filing.owners),
        "transaction_count": len(filing.transactions),
        "position_count": len(filing.positions),
        "footnote_count": len(filing.footnotes),
    }


def update_form4_sync_state(
    db: Session,
    *,
    symbol: str,
    issuer_cik: str,
    status: str,
    latest_accession_number: str | None,
    latest_filing_date: date | None,
    fetched_count: int,
    errors: list[str],
    source_url: str | None,
    checked_at: datetime | None = None,
) -> USSecOwnershipSyncState:
    now = checked_at or utc_now()
    row = (
        db.query(USSecOwnershipSyncState)
        .filter(USSecOwnershipSyncState.symbol == symbol)
        .first()
    )
    if row is None:
        row = USSecOwnershipSyncState(symbol=symbol, issuer_cik=issuer_cik)
        db.add(row)
    row.issuer_cik = issuer_cik
    row.status = status
    row.latest_accession_number = latest_accession_number
    row.latest_filing_date = latest_filing_date
    row.last_checked_at = now
    if status in {"current", "ready_empty", "partial"}:
        row.last_success_at = now
    row.fetched_count = fetched_count
    row.error_count = len(errors)
    row.warning_json = _json(errors) if errors else None
    row.source_url = source_url
    db.flush()
    return row


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _transaction_category(code: str | None, table_type: str) -> str:
    if table_type == "derivative":
        return "derivative"
    return {
        "P": "open_market_purchase",
        "S": "open_market_sale",
        "F": "tax_withholding",
        "G": "gift",
        "M": "option_exercise",
        "A": "award_or_grant",
        "D": "disposition_to_issuer",
    }.get(str(code or "").upper(), "other")


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _decimal_sum_text(values: list[str | None]) -> str | None:
    parsed = [item for item in (_decimal(value) for value in values) if item is not None]
    if not parsed:
        return None
    return format(sum(parsed, Decimal("0")), "f")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
        )
        offset = int(payload["offset"])
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("Invalid insider transaction cursor.") from exc
    if offset < 0 or offset > 10_000:
        raise ValueError("Insider transaction cursor is outside the supported range.")
    return offset


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(
        _json({"offset": offset}).encode("utf-8")
    ).decode("ascii").rstrip("=")


def get_insider_transactions_contract(
    db: Session,
    *,
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    codes: tuple[str, ...] = (),
    include_derivatives: bool = True,
    limit: int = 100,
    cursor: str | None = None,
    observation_hours: int = 24,
    now: datetime | None = None,
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise ValueError("Insider transaction limit must be between 1 and 200.")
    offset = _cursor_offset(cursor)
    normalized = symbol.strip().upper()
    filing_query = db.query(USSecOwnershipFiling).filter(
        USSecOwnershipFiling.issuer_trading_symbol == normalized
    )
    filings = filing_query.order_by(
        USSecOwnershipFiling.filing_date.desc(),
        USSecOwnershipFiling.accepted_at.desc(),
        USSecOwnershipFiling.id.desc(),
    ).all()
    current_filings = filings
    filing_by_id = {item.id: item for item in current_filings}
    filing_ids = tuple(filing_by_id)

    transactions: list[USSecOwnershipTransaction] = []
    if filing_ids:
        query = db.query(USSecOwnershipTransaction).filter(
            USSecOwnershipTransaction.filing_id.in_(filing_ids)
        )
        if from_date is not None:
            query = query.filter(USSecOwnershipTransaction.transaction_date >= from_date)
        if to_date is not None:
            query = query.filter(USSecOwnershipTransaction.transaction_date <= to_date)
        normalized_codes = tuple(sorted({code.strip().upper() for code in codes if code.strip()}))
        if normalized_codes:
            query = query.filter(USSecOwnershipTransaction.transaction_code.in_(normalized_codes))
        if not include_derivatives:
            query = query.filter(USSecOwnershipTransaction.table_type == "non_derivative")
        transactions = query.order_by(
            USSecOwnershipTransaction.transaction_date.desc(),
            USSecOwnershipTransaction.id.desc(),
        ).limit(min((offset + limit + 1) * 3, 30_603)).all()

    amendment_warnings: list[str] = []
    excluded_transaction_ids: set[int] = set()
    filing_by_accession = {filing.accession_number: filing for filing in filings}

    def merge_key(item: USSecOwnershipTransaction) -> tuple[Any, ...]:
        return (
            item.table_type,
            str(item.security_title or "").strip().casefold(),
            item.transaction_date,
            str(item.transaction_code or "").upper(),
            str(item.acquired_disposed_code or "").upper(),
            str(item.direct_indirect_code or "").upper(),
        )

    transactions_by_filing: dict[int, list[USSecOwnershipTransaction]] = {}
    for item in transactions:
        transactions_by_filing.setdefault(item.filing_id, []).append(item)
    for amendment in filings:
        if not amendment.supersedes_accession_number:
            continue
        original = filing_by_accession.get(amendment.supersedes_accession_number)
        if original is None:
            amendment_warnings.append(
                f"USO004_amendment_base_missing:{amendment.accession_number}"
            )
            continue
        original_by_key: dict[tuple[Any, ...], list[USSecOwnershipTransaction]] = {}
        amendment_by_key: dict[tuple[Any, ...], list[USSecOwnershipTransaction]] = {}
        for item in transactions_by_filing.get(original.id, []):
            original_by_key.setdefault(merge_key(item), []).append(item)
        for item in transactions_by_filing.get(amendment.id, []):
            amendment_by_key.setdefault(merge_key(item), []).append(item)
        for key, amendment_items in amendment_by_key.items():
            original_items = original_by_key.get(key, [])
            if len(original_items) == 1 and len(amendment_items) == 1:
                excluded_transaction_ids.add(original_items[0].id)
            elif original_items:
                amendment_warnings.append(
                    f"USO004_amendment_merge_ambiguous:{amendment.accession_number}"
                )
    merged_transactions = [
        item for item in transactions if item.id not in excluded_transaction_ids
    ]
    has_more = len(merged_transactions) > offset + limit
    transactions = merged_transactions[offset : offset + limit]

    owners_by_filing: dict[int, list[dict[str, Any]]] = {}
    footnotes_by_filing: dict[int, dict[str, str]] = {}
    if filing_ids:
        owner_rows = (
            db.query(USSecFilingReportingOwner, USSecReportingOwner)
            .join(
                USSecReportingOwner,
                USSecReportingOwner.id == USSecFilingReportingOwner.reporting_owner_id,
            )
            .filter(USSecFilingReportingOwner.filing_id.in_(filing_ids))
            .all()
        )
        for link, owner in owner_rows:
            owners_by_filing.setdefault(link.filing_id, []).append(
                {
                    "cik": owner.cik,
                    "name": owner.name,
                    "is_director": link.is_director,
                    "is_officer": link.is_officer,
                    "is_ten_percent_owner": link.is_ten_percent_owner,
                    "is_other": link.is_other,
                    "officer_title": link.officer_title,
                    "other_text": link.other_text,
                }
            )
        for footnote in db.query(USSecOwnershipFootnote).filter(
            USSecOwnershipFootnote.filing_id.in_(filing_ids)
        ).all():
            footnotes_by_filing.setdefault(footnote.filing_id, {})[
                footnote.footnote_id
            ] = footnote.footnote_text

    rows: list[dict[str, Any]] = []
    all_issue_codes: set[str] = set()
    for item in transactions:
        filing = filing_by_id[item.filing_id]
        footnote_ids = _loads_list(item.footnote_ids_json)
        issue_codes = _loads_list(item.issue_codes_json)
        all_issue_codes.update(issue_codes)
        rows.append(
            {
                "transaction_id": f"{filing.accession_number}:{item.row_sequence}",
                "accession_number": filing.accession_number,
                "form_type": filing.form_type,
                "filing_date": _iso(filing.filing_date),
                "accepted_at": _iso(filing.accepted_at),
                "period_of_report": _iso(filing.period_of_report),
                "transaction_date": _iso(item.transaction_date),
                "table_type": item.table_type,
                "category": _transaction_category(item.transaction_code, item.table_type),
                "transaction_code": item.transaction_code,
                "acquired_disposed_code": item.acquired_disposed_code,
                "security_title": item.security_title,
                "shares": item.shares_text,
                "price_per_share": item.price_per_share_text,
                "post_transaction_shares": item.post_transaction_shares_text,
                "direct_indirect_code": item.direct_indirect_code,
                "nature_of_ownership": item.nature_of_ownership,
                "conversion_exercise_price": item.conversion_exercise_price_text,
                "exercise_date": _iso(item.exercise_date),
                "expiration_date": _iso(item.expiration_date),
                "underlying_security_title": item.underlying_security_title,
                "underlying_shares": item.underlying_shares_text,
                "equity_swap_involved": item.equity_swap_involved,
                "aff10b5_one": filing.aff10b5_one,
                "is_amendment": filing.is_amendment,
                "owners": sorted(owners_by_filing.get(item.filing_id, []), key=lambda value: value["cik"]),
                "footnotes": [
                    {"id": footnote_id, "text": footnotes_by_filing.get(item.filing_id, {}).get(footnote_id)}
                    for footnote_id in footnote_ids
                ],
                "issue_codes": issue_codes,
                "source_url": filing.source_url,
            }
        )

    state = (
        db.query(USSecOwnershipSyncState)
        .filter(USSecOwnershipSyncState.symbol == normalized)
        .first()
    )
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if state is None or state.last_checked_at is None:
        status = "missing"
    else:
        checked_at = state.last_checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if current_time - checked_at > timedelta(hours=max(observation_hours, 1)):
            status = "stale"
        else:
            status = state.status

    categories = [row["category"] for row in rows]
    purchase_shares = _decimal_sum_text(
        [row["shares"] for row in rows if row["category"] == "open_market_purchase"]
    )
    sale_shares = _decimal_sum_text(
        [row["shares"] for row in rows if row["category"] == "open_market_sale"]
    )
    warnings = _loads_list(state.warning_json) if state else []
    warnings.extend(amendment_warnings)
    if all_issue_codes and status in {"current", "ready_empty"}:
        status = "partial"
    return {
        "contract_version": INSIDER_CONTRACT_VERSION,
        "symbol": normalized,
        "cik": state.issuer_cik if state else (current_filings[0].issuer_cik if current_filings else None),
        "status": status,
        "as_of": _iso(state.last_checked_at) if state else None,
        "freshness": {
            "status": status,
            "last_checked_at": _iso(state.last_checked_at) if state else None,
            "last_success_at": _iso(state.last_success_at) if state else None,
            "latest_filing_date": _iso(state.latest_filing_date) if state else None,
            "latest_accession_number": state.latest_accession_number if state else None,
            "basis": "sec_ownership_filing_observation",
            "observation_window_hours": max(observation_hours, 1),
        },
        "summary": {
            "filing_count": len(current_filings),
            "amendment_count": sum(1 for filing in current_filings if filing.is_amendment),
            "transaction_count": len(rows),
            "open_market_purchase_count": categories.count("open_market_purchase"),
            "open_market_sale_count": categories.count("open_market_sale"),
            "open_market_purchase_shares": purchase_shares,
            "open_market_sale_shares": sale_shares,
            "other_transaction_count": len(rows)
            - categories.count("open_market_purchase")
            - categories.count("open_market_sale"),
            "latest_transaction_date": max(
                (row["transaction_date"] for row in rows if row["transaction_date"]),
                default=None,
            ),
        },
        "transactions": rows,
        "quality": {
            "issue_codes": sorted(all_issue_codes),
            "warnings": warnings,
            "limitations": [FORM4_POSITION_LIMITATION],
        },
        "source_refs": [
            {
                "provider": "sec_edgar",
                "accession_number": filing.accession_number,
                "form_type": filing.form_type,
                "filing_date": _iso(filing.filing_date),
                "source_url": filing.source_url,
            }
            for filing in current_filings[: min(len(current_filings), 20)]
        ],
        "pagination": {
            "limit": limit,
            "returned_count": len(rows),
            "next_cursor": _encode_cursor(offset + len(rows)) if has_more else None,
        },
    }


__all__ = [
    "FORM4_POSITION_LIMITATION",
    "INSIDER_CONTRACT_VERSION",
    "get_insider_transactions_contract",
    "persist_form4_filing",
    "update_form4_sync_state",
]
