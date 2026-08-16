from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path
import re
from typing import Iterator, Mapping
import zipfile


REQUIRED_13F_TABLES = {"SUBMISSION", "COVERPAGE", "SUMMARYPAGE", "INFOTABLE"}
FORM13F_PARSER_VERSION = "omi.sec.form13f.parser.v1"
FORM13F_USD_VALUE_EFFECTIVE_DATE = date(2023, 1, 3)
_CUSIP_RE = re.compile(r"^[0-9A-Z*@#]{9}$")


@dataclass(frozen=True)
class Section13FSecurity:
    cusip: str
    option_indicator: bool
    issuer_name: str
    issuer_description: str
    status: str | None


def normalize_cusip(value: object) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    return normalized if _CUSIP_RE.fullmatch(normalized) else None


def parse_section_13f_list(payload: bytes | str) -> dict[str, Section13FSecurity]:
    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) else payload
    securities: dict[str, Section13FSecurity] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if len(line) < 10:
            continue
        cusip = normalize_cusip(line[0:9])
        if cusip is None:
            continue
        status_raw = line[67:70].strip() if len(line) >= 70 else ""
        securities[cusip] = Section13FSecurity(
            cusip=cusip,
            option_indicator=line[9:10] == "*",
            issuer_name=line[10:40].strip(),
            issuer_description=line[40:67].strip(),
            status={"*A*": "added", "*D*": "deleted"}.get(status_raw),
        )
    if not securities:
        raise ValueError("Official Section 13(f) list did not contain any valid CUSIPs.")
    return securities


def _table_name(member_name: str) -> str | None:
    stem = Path(member_name).stem.upper()
    aliases = {"SIGNATUREBLOCK": "SIGNATURE", "OTHERMANAGER2": "OTHERMANAGER2"}
    canonical = aliases.get(stem, stem)
    return canonical if canonical in {
        "SUBMISSION",
        "COVERPAGE",
        "OTHERMANAGER",
        "SIGNATURE",
        "SUMMARYPAGE",
        "OTHERMANAGER2",
        "INFOTABLE",
    } else None


def table_members(archive: zipfile.ZipFile) -> dict[str, str]:
    members: dict[str, str] = {}
    for info in archive.infolist():
        table = _table_name(info.filename)
        if table is not None:
            if table in members:
                raise ValueError(f"Duplicate {table} table in Form 13F archive.")
            members[table] = info.filename
    missing = sorted(REQUIRED_13F_TABLES - set(members))
    if missing:
        raise ValueError(f"Form 13F archive is missing required tables: {', '.join(missing)}")
    return members


def iter_13f_table_rows(
    archive: zipfile.ZipFile,
    member_name: str,
) -> Iterator[dict[str, str]]:
    with archive.open(member_name) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline="") as text:
            reader = csv.DictReader(text, delimiter="\t")
            if not reader.fieldnames:
                raise ValueError(f"Form 13F table {member_name} has no header.")
            for row in reader:
                yield {str(key or "").strip().upper(): str(value or "").strip() for key, value in row.items()}


def parse_reported_value(row: Mapping[str, str]) -> Decimal | None:
    raw = str(row.get("VALUE") or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def reported_value_unit(filing_date: date) -> str:
    return "usd" if filing_date >= FORM13F_USD_VALUE_EFFECTIVE_DATE else "usd_thousands"


def reported_value_usd(raw_value: Decimal, filing_date: date) -> Decimal:
    return raw_value if reported_value_unit(filing_date) == "usd" else raw_value * Decimal(1000)


__all__ = [
    "FORM13F_PARSER_VERSION",
    "FORM13F_USD_VALUE_EFFECTIVE_DATE",
    "Section13FSecurity",
    "iter_13f_table_rows",
    "normalize_cusip",
    "parse_reported_value",
    "parse_section_13f_list",
    "reported_value_unit",
    "reported_value_usd",
    "table_members",
]
