from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SecFilingFreshness:
    status: str
    decision_usable: bool
    basis: str
    local_accession_number: str | None
    expected_accession_number: str | None
    latest_filing_date: date | None
    latest_fetched_at: datetime | None
    last_checked_at: datetime | None
    issue_codes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "decision_usable": self.decision_usable,
            "basis": self.basis,
            "local_accession_number": self.local_accession_number,
            "expected_accession_number": self.expected_accession_number,
            "latest_filing_date": (
                self.latest_filing_date.isoformat() if self.latest_filing_date else None
            ),
            "latest_fetched_at": (
                _utc(self.latest_fetched_at).isoformat() if self.latest_fetched_at else None
            ),
            "last_checked_at": (
                _utc(self.last_checked_at).isoformat() if self.last_checked_at else None
            ),
            "issue_codes": list(self.issue_codes),
        }


def evaluate_sec_filing_freshness(
    *,
    local_accession_number: str | None,
    local_filing_date: date | None,
    local_fetched_at: datetime | None,
    expected_accession_number: str | None = None,
    expected_filing_date: date | None = None,
    last_checked_at: datetime | None = None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(hours=24),
) -> SecFilingFreshness:
    current = _utc(now) or datetime.now(timezone.utc)
    fetched_at = _utc(local_fetched_at)
    checked_at = _utc(last_checked_at)

    if not local_accession_number or fetched_at is None:
        return SecFilingFreshness(
            status="missing",
            decision_usable=False,
            basis="local_companyfacts",
            local_accession_number=local_accession_number,
            expected_accession_number=expected_accession_number,
            latest_filing_date=expected_filing_date or local_filing_date,
            latest_fetched_at=fetched_at,
            last_checked_at=checked_at,
            issue_codes=("sec_facts_missing",),
        )

    if expected_accession_number:
        if expected_accession_number != local_accession_number:
            return SecFilingFreshness(
                status="stale",
                decision_usable=False,
                basis="submissions_accession",
                local_accession_number=local_accession_number,
                expected_accession_number=expected_accession_number,
                latest_filing_date=expected_filing_date or local_filing_date,
                latest_fetched_at=fetched_at,
                last_checked_at=checked_at,
                issue_codes=("newer_sec_filing_available",),
            )
        if checked_at is not None and current - checked_at <= stale_after:
            return SecFilingFreshness(
                status="current",
                decision_usable=True,
                basis="submissions_accession",
                local_accession_number=local_accession_number,
                expected_accession_number=expected_accession_number,
                latest_filing_date=expected_filing_date or local_filing_date,
                latest_fetched_at=fetched_at,
                last_checked_at=checked_at,
                issue_codes=(),
            )

    age = current - fetched_at
    if age <= stale_after:
        return SecFilingFreshness(
            status="current",
            decision_usable=True,
            basis="companyfacts_fetch_age",
            local_accession_number=local_accession_number,
            expected_accession_number=expected_accession_number,
            latest_filing_date=expected_filing_date or local_filing_date,
            latest_fetched_at=fetched_at,
            last_checked_at=checked_at,
            issue_codes=("submissions_check_unavailable",) if not checked_at else (),
        )

    return SecFilingFreshness(
        status="stale",
        decision_usable=False,
        basis="companyfacts_fetch_age",
        local_accession_number=local_accession_number,
        expected_accession_number=expected_accession_number,
        latest_filing_date=expected_filing_date or local_filing_date,
        latest_fetched_at=fetched_at,
        last_checked_at=checked_at,
        issue_codes=("sec_facts_refresh_overdue",),
    )
