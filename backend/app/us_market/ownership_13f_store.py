from __future__ import annotations

from collections import defaultdict
from datetime import date
import json
from typing import Any
import zipfile

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.db.models import (
    USSec13FFiling,
    USSec13FManager,
    USSec13FOtherManager,
    USSecDatasetRelease,
)
from app.us_market.sec_ownership.form13f import (
    iter_13f_table_rows,
    parse_reported_value,
    reported_value_unit,
    reported_value_usd,
    table_members,
)


_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10 and raw[4:5] == "-":
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    parts = raw.upper().split("-")
    if len(parts) != 3 or parts[1] not in _MONTHS:
        return None
    try:
        return date(int(parts[2]), _MONTHS[parts[1]], int(parts[0]))
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    raw = str(value or "").strip().replace(",", "")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _bool(value: str | None) -> bool | None:
    normalized = str(value or "").strip().upper()
    if normalized in {"Y", "YES", "TRUE", "1"}:
        return True
    if normalized in {"N", "NO", "FALSE", "0"}:
        return False
    return None


def _source_url(cik: str, accession: str) -> str:
    compact = accession.replace("-", "")
    try:
        cik_value = str(int(cik))
    except ValueError:
        cik_value = cik.lstrip("0") or cik
    return f"https://www.sec.gov/Archives/edgar/data/{cik_value}/{compact}/{accession}-index.html"


def _manager(
    db: Session,
    *,
    release: USSecDatasetRelease,
    cik: str,
    cover: dict[str, str],
) -> USSec13FManager:
    normalized_cik = str(cik or "").strip().zfill(10)
    row = db.query(USSec13FManager).filter(USSec13FManager.cik == normalized_cik).first()
    address = {
        "street1": cover.get("FILINGMANAGER_STREET1") or None,
        "street2": cover.get("FILINGMANAGER_STREET2") or None,
        "city": cover.get("FILINGMANAGER_CITY") or None,
        "state_or_country": cover.get("FILINGMANAGER_STATEORCOUNTRY") or None,
        "postal_code": cover.get("FILINGMANAGER_ZIPCODE") or None,
    }
    name = str(cover.get("FILINGMANAGER_NAME") or normalized_cik).strip()
    if row is None:
        row = USSec13FManager(
            cik=normalized_cik,
            name=name,
            form13f_file_number=cover.get("FORM13FFILENUMBER") or None,
            address_json=_json(address),
            first_seen_release_id=release.id,
            last_seen_release_id=release.id,
        )
        db.add(row)
        db.flush()
    else:
        row.name = name
        row.form13f_file_number = cover.get("FORM13FFILENUMBER") or row.form13f_file_number
        row.address_json = _json(address)
        row.last_seen_release_id = release.id
    return row


def _apply_amendment_projection(filings: list[USSec13FFiling]) -> None:
    groups: dict[tuple[int, date], list[USSec13FFiling]] = defaultdict(list)
    for filing in filings:
        groups[(filing.manager_id, filing.report_calendar_or_quarter or filing.period_of_report)].append(filing)
    for rows in groups.values():
        rows.sort(key=lambda item: (item.filing_date, item.amendment_number or 0, item.accession_number))
        effective_base: USSec13FFiling | None = None
        for filing in rows:
            if filing.is_notice_only:
                filing.effective_status = "notice_only"
                continue
            if not filing.is_amendment:
                if effective_base is not None:
                    filing.effective_status = "disputed"
                else:
                    filing.effective_status = "effective_base"
                    effective_base = filing
                continue
            amendment_type = str(filing.amendment_type or "").strip().casefold()
            if "restatement" in amendment_type and effective_base is not None:
                filing.supersedes_accession_number = effective_base.accession_number
                effective_base.effective_status = "superseded"
                filing.effective_status = "effective_base"
                effective_base = filing
            elif "add" in amendment_type and "holding" in amendment_type:
                filing.effective_status = "effective_additive"
            else:
                filing.effective_status = "disputed"


def persist_13f_release_metadata(
    db: Session,
    *,
    release: USSecDatasetRelease,
    archive_path,
) -> dict[str, Any]:
    existing = (
        db.query(USSec13FFiling)
        .filter(USSec13FFiling.dataset_release_id == release.id)
        .count()
    )
    if existing:
        try:
            prior_source_counts = json.loads(release.source_row_counts_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            prior_source_counts = {}
        prior_source_counts.pop("INFOTABLE", None)
        return {
            "inserted": False,
            "filing_count": existing,
            "manager_count": db.query(USSec13FFiling.manager_id)
            .filter(USSec13FFiling.dataset_release_id == release.id)
            .distinct()
            .count(),
            "other_manager_count": db.query(USSec13FOtherManager)
            .join(USSec13FFiling, USSec13FFiling.id == USSec13FOtherManager.filing_id)
            .filter(USSec13FFiling.dataset_release_id == release.id)
            .count(),
            "table_counts": prior_source_counts,
        }

    with zipfile.ZipFile(archive_path) as archive:
        members = table_members(archive)
        submissions = {
            row["ACCESSION_NUMBER"]: row
            for row in iter_13f_table_rows(archive, members["SUBMISSION"])
        }
        covers = {
            row["ACCESSION_NUMBER"]: row
            for row in iter_13f_table_rows(archive, members["COVERPAGE"])
        }
        summaries = {
            row["ACCESSION_NUMBER"]: row
            for row in iter_13f_table_rows(archive, members["SUMMARYPAGE"])
        }
        other_table = "OTHERMANAGER2" if "OTHERMANAGER2" in members else "OTHERMANAGER"
        other_rows = (
            list(iter_13f_table_rows(archive, members[other_table]))
            if other_table in members
            else []
        )

    filings: list[USSec13FFiling] = []
    filing_by_accession: dict[str, USSec13FFiling] = {}
    skipped_missing_identity = 0
    for accession, submission in submissions.items():
        cover = covers.get(accession, {})
        summary = summaries.get(accession, {})
        filing_date = _date(submission.get("FILING_DATE"))
        period_of_report = _date(submission.get("PERIODOFREPORT"))
        cik = str(submission.get("CIK") or "").strip()
        if filing_date is None or period_of_report is None or not cik:
            skipped_missing_identity += 1
            continue
        manager = _manager(db, release=release, cik=cik, cover=cover)
        submission_type = str(submission.get("SUBMISSIONTYPE") or "").strip().upper()
        table_value_raw = summary.get("TABLEVALUETOTAL") or None
        parsed_table_value = (
            parse_reported_value({"VALUE": table_value_raw}) if table_value_raw else None
        )
        filing = USSec13FFiling(
            dataset_release_id=release.id,
            manager_id=manager.id,
            accession_number=accession,
            submission_type=submission_type,
            filing_date=filing_date,
            period_of_report=period_of_report,
            report_calendar_or_quarter=_date(cover.get("REPORTCALENDARORQUARTER")),
            is_amendment=submission_type.endswith("/A") or bool(_bool(cover.get("ISAMENDMENT"))),
            amendment_number=_int(cover.get("AMENDMENTNO")),
            amendment_type=cover.get("AMENDMENTTYPE") or None,
            report_type=cover.get("REPORTTYPE") or None,
            form13f_file_number=cover.get("FORM13FFILENUMBER") or None,
            other_included_managers_count=_int(summary.get("OTHERINCLUDEDMANAGERSCOUNT")),
            table_entry_total=_int(summary.get("TABLEENTRYTOTAL")),
            table_value_total_raw_text=table_value_raw,
            table_value_unit=reported_value_unit(filing_date),
            table_value_total_usd_text=(
                str(reported_value_usd(parsed_table_value, filing_date))
                if parsed_table_value is not None
                else None
            ),
            is_confidential_omitted=_bool(summary.get("ISCONFIDENTIALOMITTED")),
            is_notice_only=submission_type.startswith("13F-NT"),
            effective_status="as_filed",
            source_url=_source_url(manager.cik, accession),
        )
        db.add(filing)
        filings.append(filing)
        filing_by_accession[accession] = filing
    db.flush()
    affected_groups = {
        (item.manager_id, item.report_calendar_or_quarter or item.period_of_report)
        for item in filings
    }
    if affected_groups:
        projected_filings = (
            db.query(USSec13FFiling)
            .filter(
                tuple_(
                    USSec13FFiling.manager_id,
                    USSec13FFiling.report_calendar_or_quarter,
                ).in_(affected_groups)
                | tuple_(
                    USSec13FFiling.manager_id,
                    USSec13FFiling.period_of_report,
                ).in_(affected_groups)
            )
            .all()
        )
        _apply_amendment_projection(projected_filings)

    other_manager_count = 0
    for source_row_sequence, item in enumerate(other_rows, start=1):
        filing = filing_by_accession.get(item.get("ACCESSION_NUMBER", ""))
        if filing is None:
            continue
        sequence = (
            _int(item.get("SEQUENCENUMBER") or item.get("OTHERMANAGER_SK"))
            or source_row_sequence
        )
        db.add(
            USSec13FOtherManager(
                filing_id=filing.id,
                source_row_sequence=source_row_sequence,
                sequence_number=sequence,
                cik=(item.get("CIK") or None),
                form13f_file_number=(item.get("FORM13FFILENUMBER") or None),
                name=str(item.get("NAME") or "Unknown manager"),
            )
        )
        other_manager_count += 1
    db.flush()
    return {
        "inserted": True,
        "filing_count": len(filings),
        "manager_count": len({item.manager_id for item in filings}),
        "other_manager_count": other_manager_count,
        "skipped_missing_identity": skipped_missing_identity,
        "table_counts": {
            "SUBMISSION": len(submissions),
            "COVERPAGE": len(covers),
            "SUMMARYPAGE": len(summaries),
            other_table: len(other_rows),
        },
    }


__all__ = ["persist_13f_release_metadata"]
