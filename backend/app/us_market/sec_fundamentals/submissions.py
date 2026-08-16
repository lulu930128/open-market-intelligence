from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Iterable


RELEVANT_SEC_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A"})
SUBMISSIONS_CACHE_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if len(normalized) == 14 and normalized.isdigit():
        try:
            return datetime.strptime(normalized, "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


@dataclass(frozen=True, slots=True)
class SecFiling:
    accession_number: str
    form: str
    filing_date: date | None
    report_date: date | None
    accepted_at: datetime | None
    primary_document: str | None
    is_xbrl: bool | None
    source_url: str


@dataclass(frozen=True, slots=True)
class SecSubmissionsSnapshot:
    cik: str
    filings: tuple[SecFiling, ...]
    fetched_at: datetime
    source_url: str

    @property
    def latest_relevant_filing(self) -> SecFiling | None:
        relevant = [
            filing
            for filing in self.filings
            if filing.form in RELEVANT_SEC_FORMS and filing.is_xbrl is not False
        ]
        return max(
            relevant,
            key=lambda filing: (
                filing.filing_date or date.min,
                filing.accepted_at or datetime.min.replace(tzinfo=timezone.utc),
                filing.accession_number,
            ),
            default=None,
        )


class SecSubmissionsCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, SecSubmissionsSnapshot] = {}

    def get(
        self,
        cik: str,
        *,
        cache_path: Path | None = None,
    ) -> SecSubmissionsSnapshot | None:
        normalized_cik = str(cik).zfill(10)
        with self._lock:
            cached = self._snapshots.get(normalized_cik)
            if cached is not None:
                return cached
            if cache_path is None:
                return None
            persisted = self._read_snapshot(cache_path, normalized_cik)
            if persisted is not None:
                self._snapshots[normalized_cik] = persisted
            return persisted

    def put(
        self,
        snapshot: SecSubmissionsSnapshot,
        *,
        cache_path: Path | None = None,
    ) -> bool:
        with self._lock:
            self._snapshots[snapshot.cik] = snapshot
            if cache_path is None:
                return False
            return self._write_snapshot(cache_path, snapshot)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()

    @staticmethod
    def _read_payload(cache_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {
                "schema_version": SUBMISSIONS_CACHE_SCHEMA_VERSION,
                "snapshots": {},
            }
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SUBMISSIONS_CACHE_SCHEMA_VERSION
            or not isinstance(payload.get("snapshots"), dict)
        ):
            return {
                "schema_version": SUBMISSIONS_CACHE_SCHEMA_VERSION,
                "snapshots": {},
            }
        return payload

    @classmethod
    def _read_snapshot(
        cls,
        cache_path: Path,
        cik: str,
    ) -> SecSubmissionsSnapshot | None:
        raw = cls._read_payload(cache_path).get("snapshots", {}).get(cik)
        if not isinstance(raw, dict):
            return None
        filing_raw = raw.get("latest_relevant_filing")
        if not isinstance(filing_raw, dict):
            return None
        accession_number = str(filing_raw.get("accession_number") or "").strip()
        form = str(filing_raw.get("form") or "").strip()
        fetched_at = _datetime(raw.get("fetched_at"))
        if not accession_number or form not in RELEVANT_SEC_FORMS or fetched_at is None:
            return None
        filing = SecFiling(
            accession_number=accession_number,
            form=form,
            filing_date=_date(filing_raw.get("filing_date")),
            report_date=_date(filing_raw.get("report_date")),
            accepted_at=_datetime(filing_raw.get("accepted_at")),
            primary_document=(
                str(filing_raw.get("primary_document") or "").strip() or None
            ),
            is_xbrl=(
                filing_raw.get("is_xbrl")
                if isinstance(filing_raw.get("is_xbrl"), bool)
                else None
            ),
            source_url=str(raw.get("source_url") or ""),
        )
        return SecSubmissionsSnapshot(
            cik=cik,
            filings=(filing,),
            fetched_at=fetched_at,
            source_url=str(raw.get("source_url") or ""),
        )

    @classmethod
    def _write_snapshot(
        cls,
        cache_path: Path,
        snapshot: SecSubmissionsSnapshot,
    ) -> bool:
        latest = snapshot.latest_relevant_filing
        if latest is None:
            return False
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = cls._read_payload(cache_path)
        snapshots = payload["snapshots"]
        snapshots[snapshot.cik] = {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "source_url": snapshot.source_url,
            "latest_relevant_filing": {
                "accession_number": latest.accession_number,
                "form": latest.form,
                "filing_date": latest.filing_date.isoformat() if latest.filing_date else None,
                "report_date": latest.report_date.isoformat() if latest.report_date else None,
                "accepted_at": latest.accepted_at.isoformat() if latest.accepted_at else None,
                "primary_document": latest.primary_document,
                "is_xbrl": latest.is_xbrl,
            },
        }
        temp_path = cache_path.with_name(
            f".{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temp_path.open(mode="w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, cache_path)
            return True
        except OSError as exc:
            logger.warning(
                "Failed to persist SEC submissions cache path=%s error=%s",
                cache_path,
                exc,
            )
            return False
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def submissions_cache_path_for_session(
    db: Any,
    *,
    configured_path: Path,
) -> Path | None:
    try:
        database = db.get_bind().url.database
    except (AttributeError, RuntimeError):
        return None
    if not database or str(database).strip() == ":memory:":
        return None
    return configured_path


def parse_sec_submissions(
    payload: dict[str, Any],
    *,
    source_url: str,
    fetched_at: datetime | None = None,
) -> SecSubmissionsSnapshot:
    try:
        cik = f"{int(str(payload.get('cik')).strip()):010d}"
    except (TypeError, ValueError) as exc:
        raise ValueError("SEC submissions payload does not contain a valid CIK.") from exc

    filings_payload = payload.get("filings")
    recent = filings_payload.get("recent") if isinstance(filings_payload, dict) else None
    if not isinstance(recent, dict):
        recent = {}

    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        accessions = []

    def values(name: str) -> list[Any]:
        value = recent.get(name)
        return value if isinstance(value, list) else []

    forms = values("form")
    filing_dates = values("filingDate")
    report_dates = values("reportDate")
    accepted_times = values("acceptanceDateTime")
    primary_documents = values("primaryDocument")
    is_xbrl_values = values("isXBRL")
    filings: list[SecFiling] = []
    for index, accession in enumerate(accessions):
        accession_number = str(accession or "").strip()
        if not accession_number:
            continue

        def at(items: list[Any]) -> Any:
            return items[index] if index < len(items) else None

        filings.append(
            SecFiling(
                accession_number=accession_number,
                form=str(at(forms) or "").strip(),
                filing_date=_date(at(filing_dates)),
                report_date=_date(at(report_dates)),
                accepted_at=_datetime(at(accepted_times)),
                primary_document=(str(at(primary_documents)).strip() or None),
                is_xbrl=(
                    bool(int(at(is_xbrl_values)))
                    if str(at(is_xbrl_values) or "").strip() in {"0", "1"}
                    else None
                ),
                source_url=source_url,
            )
        )

    resolved_fetched_at = fetched_at or datetime.now(timezone.utc)
    if resolved_fetched_at.tzinfo is None:
        resolved_fetched_at = resolved_fetched_at.replace(tzinfo=timezone.utc)
    return SecSubmissionsSnapshot(
        cik=cik,
        filings=tuple(filings),
        fetched_at=resolved_fetched_at,
        source_url=source_url,
    )


SEC_SUBMISSIONS_CACHE = SecSubmissionsCache()


def filing_accessions(filings: Iterable[SecFiling]) -> tuple[str, ...]:
    return tuple(filing.accession_number for filing in filings)


__all__ = [
    "RELEVANT_SEC_FORMS",
    "SUBMISSIONS_CACHE_SCHEMA_VERSION",
    "SEC_SUBMISSIONS_CACHE",
    "SecFiling",
    "SecSubmissionsCache",
    "SecSubmissionsSnapshot",
    "filing_accessions",
    "parse_sec_submissions",
    "submissions_cache_path_for_session",
]
