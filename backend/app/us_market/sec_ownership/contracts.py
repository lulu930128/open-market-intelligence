from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Form4SubmissionEntry:
    accession_number: str
    form_type: str
    filing_date: date
    report_date: date | None
    accepted_at: datetime | None
    primary_document: str


@dataclass(frozen=True)
class Form4Owner:
    cik: str
    name: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    officer_title: str | None
    other_text: str | None


@dataclass(frozen=True)
class Form4Transaction:
    row_sequence: int
    table_type: str
    security_title: str | None
    transaction_date: date | None
    deemed_execution_date: date | None
    transaction_form_type: str | None
    transaction_code: str | None
    equity_swap_involved: bool | None
    acquired_disposed_code: str | None
    shares_text: str | None
    price_per_share_text: str | None
    post_transaction_shares_text: str | None
    direct_indirect_code: str | None
    nature_of_ownership: str | None
    conversion_exercise_price_text: str | None
    exercise_date: date | None
    expiration_date: date | None
    underlying_security_title: str | None
    underlying_shares_text: str | None
    footnote_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]

@dataclass(frozen=True)
class Form4Position:
    row_sequence: int
    table_type: str
    security_title: str | None
    post_transaction_shares_text: str | None
    direct_indirect_code: str | None
    nature_of_ownership: str | None
    conversion_exercise_price_text: str | None
    exercise_date: date | None
    expiration_date: date | None
    underlying_security_title: str | None
    underlying_shares_text: str | None
    footnote_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class Form4Footnote:
    footnote_id: str
    text: str


@dataclass(frozen=True)
class Form4Filing:
    accession_number: str
    form_type: str
    schema_version: str | None
    period_of_report: date | None
    original_submission_date: date | None
    filing_date: date | None
    accepted_at: datetime | None
    issuer_cik: str
    issuer_name: str
    issuer_trading_symbol: str | None
    is_amendment: bool
    aff10b5_one: bool | None
    remarks: str | None
    owners: tuple[Form4Owner, ...]
    transactions: tuple[Form4Transaction, ...]
    positions: tuple[Form4Position, ...]
    footnotes: tuple[Form4Footnote, ...]
    source_url: str
    source_sha256: str
    parser_version: str
    issue_codes: tuple[str, ...]
