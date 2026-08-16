from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.config import settings
from app.us_market.errors import USMarketDataFetchError
from app.us_market.providers import sec as sec_provider


MANIFEST_CONTRACT_VERSION = "omi.sec.13f.manifest.v1"
_DATASET_PATH_MARKER = "/files/structureddata/data/form-13f-data-sets/"
_RANGE_RE = re.compile(
    r"(?P<start_day>\d{2})(?P<start_month>[a-z]{3})(?P<start_year>\d{4})-"
    r"(?P<end_day>\d{2})(?P<end_month>[a-z]{3})(?P<end_year>\d{4})_form13f\.zip$",
    re.IGNORECASE,
)
_LEGACY_RE = re.compile(r"(?P<year>\d{4})q(?P<quarter>[1-4])_form13f\.zip$", re.IGNORECASE)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class Form13FManifestEntry:
    period_key: str
    source_url: str
    label: str
    source_window_start: str
    source_window_end: str | None


class _DatasetLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and _DATASET_PATH_MARKER in href and href.lower().endswith("_form13f.zip"):
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append((self._href, " ".join("".join(self._parts).split())))
        self._href = None
        self._parts = []


def _range_identity(filename: str) -> tuple[str, date, date] | None:
    match = _RANGE_RE.search(filename)
    if match is None:
        return None
    start_month = _MONTHS.get(match.group("start_month").lower())
    end_month = _MONTHS.get(match.group("end_month").lower())
    if start_month is None or end_month is None:
        return None
    start = date(
        int(match.group("start_year")),
        start_month,
        int(match.group("start_day")),
    )
    end = date(
        int(match.group("end_year")),
        end_month,
        int(match.group("end_day")),
    )
    if start == date(2024, 1, 1) and end == date(2024, 2, 29):
        return "2024JANFEB", start, end
    quarter_by_end_month = {2: 4, 5: 1, 8: 2, 11: 3}
    quarter = quarter_by_end_month.get(end.month)
    if quarter is None:
        return None
    report_year = end.year - 1 if end.month == 2 else end.year
    return f"{report_year}Q{quarter}", start, end


def _legacy_identity(filename: str) -> tuple[str, date, None] | None:
    match = _LEGACY_RE.search(filename)
    if match is None:
        return None
    year = int(match.group("year"))
    quarter = int(match.group("quarter"))
    return f"{year}Q{quarter}", date(year, (quarter - 1) * 3 + 1, 1), None


def _entry(href: str, label: str, *, base_url: str) -> Form13FManifestEntry:
    source_url = urljoin(base_url, href)
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.sec.gov", "sec.gov"}
        or _DATASET_PATH_MARKER not in parsed.path
    ):
        raise USMarketDataFetchError(f"Invalid SEC Form 13F manifest URL: {source_url}")
    filename = Path(parsed.path).name
    identity = _range_identity(filename) or _legacy_identity(filename)
    if identity is None:
        raise USMarketDataFetchError(f"Unsupported SEC Form 13F data-set filename: {filename}")
    period_key, source_start, source_end = identity
    return Form13FManifestEntry(
        period_key=period_key,
        source_url=source_url,
        label=label or filename,
        source_window_start=source_start.isoformat(),
        source_window_end=source_end.isoformat() if source_end else None,
    )


def parse_13f_manifest_html(html: str, *, base_url: str) -> list[Form13FManifestEntry]:
    parser = _DatasetLinkParser()
    parser.feed(str(html or ""))
    entries = [_entry(href, label, base_url=base_url) for href, label in parser.links]
    by_url = {entry.source_url: entry for entry in entries}
    if not by_url:
        raise USMarketDataFetchError("SEC Form 13F manifest contained no data-set archives.")
    period_keys = [entry.period_key for entry in by_url.values()]
    if len(set(period_keys)) != len(period_keys):
        duplicates = sorted({key for key in period_keys if period_keys.count(key) > 1})
        raise USMarketDataFetchError(
            "SEC Form 13F manifest produced duplicate period keys: " + ", ".join(duplicates)
        )
    return sorted(by_url.values(), key=lambda entry: entry.source_window_start, reverse=True)


def _cache_path() -> Path:
    return Path(settings.us_sec_ownership_cache_path) / "archives" / "form-13f" / "manifest.json"


def _payload(entries: list[Form13FManifestEntry], *, source_url: str) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    body = {
        "contract_version": MANIFEST_CONTRACT_VERSION,
        "source_url": source_url,
        "checked_at": checked_at,
        "entry_count": len(entries),
        "entries": [asdict(entry) for entry in entries],
    }
    body["manifest_sha256"] = sha256(
        json.dumps(body["entries"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return body


def refresh_13f_manifest() -> dict[str, Any]:
    html, source_url = sec_provider.fetch_sec_13f_dataset_manifest_html(
        sec_user_agent=_sec_user_agent(),
        timeout_seconds=max(int(settings.us_market_http_timeout_seconds), 1),
    )
    entries = parse_13f_manifest_html(html, base_url=source_url)
    body = _payload(entries, source_url=source_url)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    incoming = path.with_name("manifest.incoming.json")
    incoming.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    incoming.replace(path)
    return body


def load_cached_13f_manifest() -> dict[str, Any] | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise USMarketDataFetchError(f"SEC Form 13F manifest cache is invalid: {exc}") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if payload.get("contract_version") != MANIFEST_CONTRACT_VERSION or not isinstance(entries, list):
        raise USMarketDataFetchError("SEC Form 13F manifest cache has an unsupported contract.")
    parsed_entries = [
        Form13FManifestEntry(
            period_key=str(item["period_key"]),
            source_url=str(item["source_url"]),
            label=str(item["label"]),
            source_window_start=str(item["source_window_start"]),
            source_window_end=(str(item["source_window_end"]) if item.get("source_window_end") else None),
        )
        for item in entries
        if isinstance(item, dict)
    ]
    if len(parsed_entries) != len(entries):
        raise USMarketDataFetchError("SEC Form 13F manifest cache contains malformed entries.")
    return _payload(parsed_entries, source_url=str(payload.get("source_url") or "")) | {
        "checked_at": payload.get("checked_at"),
        "manifest_sha256": payload.get("manifest_sha256"),
    }


def _sec_user_agent() -> str:
    value = str(settings.us_sec_user_agent or "").strip().strip('"').strip("'")
    if not value or "set US_SEC_USER_AGENT" in value:
        raise USMarketDataFetchError(
            "US_SEC_USER_AGENT is not configured for SEC Form 13F manifest discovery."
        )
    return value


__all__ = [
    "Form13FManifestEntry",
    "MANIFEST_CONTRACT_VERSION",
    "load_cached_13f_manifest",
    "parse_13f_manifest_html",
    "refresh_13f_manifest",
]
