from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from app.market.providers._http import get, post
from app.parsers.mops_ixbrl import (
    PARSER_VERSION,
    ParsedMopsIxbrl,
    decode_mops_html,
    parse_mops_ixbrl,
)


MOPS_PROVIDER = "mops_official_filing"
MOPS_RESOURCE = "financial_filing_ixbrl"
MOPS_SOURCE_NAME = "MOPS Official Filing iXBRL"
MOPS_IXBRL_URL = "https://mopsov.twse.com.tw/server-java/t164sb01"
MOPS_DOCUMENT_INDEX_URL = "https://doc.twse.com.tw/server-java/t57sb01"
HTML_HEADERS = {
    "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}
_UPLOAD_RE = re.compile(
    r"(?P<year>\d{3})/(?P<month>\d{2})/(?P<day>\d{2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
)


@dataclass(frozen=True, slots=True)
class MopsDocumentRecord:
    stock_id: str
    fiscal_year: int
    fiscal_quarter: int
    filename: str
    uploaded_at: datetime
    file_size_bytes: int | None
    correction_status: str | None
    registry_url: str


@dataclass(frozen=True, slots=True)
class FetchedMopsFinancialFiling:
    stock_id: str
    fiscal_year: int
    fiscal_quarter: int
    report_id: str
    ixbrl_url: str
    raw_bytes: bytes
    decoded_text: str
    content_type: str | None
    content_hash: str
    fetched_at: datetime
    document: MopsDocumentRecord
    parsed: ParsedMopsIxbrl


@dataclass(frozen=True, slots=True)
class MopsFinancialFetchBatch:
    filings: tuple[FetchedMopsFinancialFiling, ...]
    request_count: int
    request_limit: int | None = None
    selected_report_id: str | None = None


def build_ixbrl_url(
    *,
    stock_id: str,
    fiscal_year: int,
    fiscal_quarter: int,
    report_id: str = "C",
) -> str:
    return (
        f"{MOPS_IXBRL_URL}?step=1&CO_ID={stock_id}&SYEAR={fiscal_year}"
        f"&SSEASON={fiscal_quarter}&REPORT_ID={report_id}"
    )


def build_document_index_url(*, stock_id: str, fiscal_year: int) -> str:
    roc_year = fiscal_year - 1911
    return (
        f"{MOPS_DOCUMENT_INDEX_URL}?step=1&colorchg=1&co_id={stock_id}"
        f"&year={roc_year}&mtype=A"
    )


def _parse_upload_timestamp(value: str) -> datetime | None:
    match = _UPLOAD_RE.search(value)
    if match is None:
        return None
    parts = {key: int(raw) for key, raw in match.groupdict().items()}
    return datetime(
        parts["year"] + 1911,
        parts["month"],
        parts["day"],
        parts["hour"],
        parts["minute"],
        parts["second"],
        tzinfo=ZoneInfo("Asia/Taipei"),
    )


def parse_document_index(
    payload: bytes | str,
    *,
    stock_id: str,
    fiscal_year: int,
    registry_url: str,
    report_id: str = "C",
) -> tuple[MopsDocumentRecord, ...]:
    text = decode_mops_html(payload) if isinstance(payload, bytes) else payload
    soup = BeautifulSoup(text, "lxml")
    normalized_report_id = report_id.strip().upper()
    document_suffix = {
        "A": "AI2",
        "C": "AI1",
    }.get(normalized_report_id)
    if document_suffix is None:
        raise ValueError(
            "official document mapping is not defined for "
            f"REPORT_ID={report_id!r}"
        )
    records: list[MopsDocumentRecord] = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        anchor = row.find("a")
        if not cells or anchor is None:
            continue
        filename = anchor.get_text(" ", strip=True)
        match = re.fullmatch(
            rf"(?P<year>\d{{4}})(?P<quarter>0[1-4])_"
            rf"{re.escape(stock_id)}_{document_suffix}\.pdf",
            filename,
            flags=re.IGNORECASE,
        )
        if match is None:
            continue
        row_texts = [cell.get_text(" ", strip=True) for cell in cells]
        uploaded_at = next(
            (
                parsed
                for value in row_texts
                if (parsed := _parse_upload_timestamp(value)) is not None
            ),
            None,
        )
        if uploaded_at is None:
            raise ValueError(f"official document row lacks upload time: {filename}")
        row_year = int(match.group("year"))
        quarter = int(match.group("quarter"))
        if row_year != fiscal_year:
            continue
        upload_index = next(
            index
            for index, value in enumerate(row_texts)
            if _parse_upload_timestamp(value) is not None
        )
        file_size = None
        if upload_index > 0:
            size_text = row_texts[upload_index - 1].replace(",", "").strip()
            if size_text.isdigit():
                file_size = int(size_text)
        correction_status = (
            row_texts[upload_index + 1].strip()
            if upload_index + 1 < len(row_texts)
            else None
        )
        records.append(
            MopsDocumentRecord(
                stock_id=stock_id,
                fiscal_year=fiscal_year,
                fiscal_quarter=quarter,
                filename=filename,
                uploaded_at=uploaded_at,
                file_size_bytes=file_size,
                correction_status=correction_status or None,
                registry_url=registry_url,
            )
        )
    return tuple(sorted(records, key=lambda item: item.fiscal_quarter))


def _financial_holding_followup_payload(
    payload: bytes,
    *,
    stock_id: str,
    fiscal_year: int,
) -> dict[str, str] | None:
    text = decode_mops_html(payload)
    soup = BeautifulSoup(text, "lxml")
    marker = soup.find(
        "input",
        attrs={"name": "check2858", "value": re.compile(r"^Y$", re.I)},
    )
    if marker is None:
        return None
    return {
        "check2858": "Y",
        "co_id": stock_id,
        "colorchg": "1",
        "year": str(fiscal_year - 1911),
        "step": "1",
        "mtype": "A",
    }


def _request(
    request: Callable[..., requests.Response],
    url: str,
    *,
    stock_id: str,
    resource: str,
    timeout_seconds: int,
    **request_kwargs: object,
) -> requests.Response:
    response = request(
        url,
        provider=MOPS_PROVIDER,
        resource=resource,
        target=stock_id,
        timeout_seconds=timeout_seconds,
        headers=HTML_HEADERS,
        **request_kwargs,
    )
    response.raise_for_status()
    return response


def fetch_mops_financial_filings(
    *,
    stock_id: str,
    periods: Sequence[tuple[int, int]],
    report_id: str = "C",
    timeout_seconds: int = 30,
    request_get: Callable[..., requests.Response] = get,
    request_post: Callable[..., requests.Response] = post,
) -> MopsFinancialFetchBatch:
    normalized_periods = tuple(sorted(set(periods)))
    if not normalized_periods:
        raise ValueError("at least one filing period is required")
    if len(normalized_periods) > 8:
        raise ValueError("a filing fetch is bounded to at most 8 periods")
    if any(quarter not in {1, 2, 3, 4} for _, quarter in normalized_periods):
        raise ValueError("filing quarters must be between 1 and 4")
    normalized_report_id = report_id.strip().upper()
    if normalized_report_id not in {"A", "C", "AUTO"}:
        raise ValueError("report_id must be A, C, or AUTO")

    records_by_report_period: dict[
        str,
        dict[tuple[int, int], MopsDocumentRecord],
    ] = {"A": {}, "C": {}}
    request_count = 0
    request_limit = len(normalized_periods) + len(
        {year for year, _ in normalized_periods}
    )
    for fiscal_year in sorted({year for year, _ in normalized_periods}):
        registry_url = build_document_index_url(
            stock_id=stock_id,
            fiscal_year=fiscal_year,
        )
        response = _request(
            request_get,
            registry_url,
            stock_id=stock_id,
            resource="financial_filing_document_index",
            timeout_seconds=timeout_seconds,
        )
        request_count += 1
        registry_payload = response.content
        report_ids_to_parse = (
            ("C", "A") if normalized_report_id == "AUTO" else (normalized_report_id,)
        )
        records_by_report = {
            candidate_report_id: parse_document_index(
                registry_payload,
                stock_id=stock_id,
                fiscal_year=fiscal_year,
                registry_url=registry_url,
                report_id=candidate_report_id,
            )
            for candidate_report_id in report_ids_to_parse
        }
        if not any(records_by_report.values()):
            followup_payload = _financial_holding_followup_payload(
                registry_payload,
                stock_id=stock_id,
                fiscal_year=fiscal_year,
            )
            if followup_payload is not None:
                request_limit += 1
                response = _request(
                    request_post,
                    MOPS_DOCUMENT_INDEX_URL,
                    stock_id=stock_id,
                    resource="financial_filing_document_index",
                    timeout_seconds=timeout_seconds,
                    data=followup_payload,
                )
                request_count += 1
                records_by_report = {
                    candidate_report_id: parse_document_index(
                        response.content,
                        stock_id=stock_id,
                        fiscal_year=fiscal_year,
                        registry_url=registry_url,
                        report_id=candidate_report_id,
                    )
                    for candidate_report_id in report_ids_to_parse
                }
        for candidate_report_id, records in records_by_report.items():
            for record in records:
                records_by_report_period[candidate_report_id][
                    (fiscal_year, record.fiscal_quarter)
                ] = record

    target_periods = set(normalized_periods)
    if normalized_report_id == "AUTO":
        complete_report_ids = [
            candidate_report_id
            for candidate_report_id in ("C", "A")
            if target_periods.issubset(
                records_by_report_period[candidate_report_id]
            )
        ]
        if not complete_report_ids:
            coverage = {
                candidate_report_id: sorted(
                    f"{year}Q{quarter}"
                    for year, quarter in (
                        set(records_by_report_period[candidate_report_id])
                        & target_periods
                    )
                )
                for candidate_report_id in ("C", "A")
            }
            raise ValueError(
                "no single official report scope covers every requested period: "
                f"stock_id={stock_id} coverage={coverage}"
            )
        selected_report_id = complete_report_ids[0]
    else:
        selected_report_id = normalized_report_id
    records_by_period = records_by_report_period[selected_report_id]

    fetched: list[FetchedMopsFinancialFiling] = []
    for fiscal_year, fiscal_quarter in normalized_periods:
        document = records_by_period.get((fiscal_year, fiscal_quarter))
        if document is None:
            raise ValueError(
                f"official filing document not found: "
                f"{stock_id} {fiscal_year}Q{fiscal_quarter}"
            )
        ixbrl_url = build_ixbrl_url(
            stock_id=stock_id,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            report_id=selected_report_id,
        )
        response = _request(
            request_get,
            ixbrl_url,
            stock_id=stock_id,
            resource=MOPS_RESOURCE,
            timeout_seconds=timeout_seconds,
        )
        request_count += 1
        raw_bytes = response.content
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        decoded = decode_mops_html(raw_bytes)
        source_share_basis_id = (
            f"{stock_id}:{fiscal_year}Q{fiscal_quarter}:"
            f"{content_hash[:16]}:presentation"
        )
        parsed = parse_mops_ixbrl(
            decoded,
            stock_id=stock_id,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            report_id=selected_report_id,
            source_share_basis_id=source_share_basis_id,
        )
        fetched.append(
            FetchedMopsFinancialFiling(
                stock_id=stock_id,
                fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter,
                report_id=selected_report_id,
                ixbrl_url=ixbrl_url,
                raw_bytes=raw_bytes,
                decoded_text=decoded,
                content_type=response.headers.get("Content-Type"),
                content_hash=content_hash,
                fetched_at=datetime.now(timezone.utc),
                document=document,
                parsed=parsed,
            )
        )
    return MopsFinancialFetchBatch(
        filings=tuple(fetched),
        request_count=request_count,
        request_limit=request_limit,
        selected_report_id=selected_report_id,
    )


__all__ = [
    "FetchedMopsFinancialFiling",
    "MOPS_DOCUMENT_INDEX_URL",
    "MOPS_IXBRL_URL",
    "MOPS_PROVIDER",
    "MOPS_SOURCE_NAME",
    "MopsDocumentRecord",
    "MopsFinancialFetchBatch",
    "build_document_index_url",
    "build_ixbrl_url",
    "fetch_mops_financial_filings",
    "parse_document_index",
]
