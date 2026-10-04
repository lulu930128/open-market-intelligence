"""Official instrument lifecycle adapter; persistence belongs to corporate events."""
from datetime import date, datetime, time, timezone
from dataclasses import dataclass
from hashlib import sha256
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import (
    AuthorityClass, InstrumentTradability, SourceLineage, TradingStatusObservation,
)

@dataclass(frozen=True)
class OfficialSuspensionInterval:
    first_date: date
    last_date: date
    evidence_url: str
    observation: TradingStatusObservation

TWSE_ANNOUNCEMENTS_URL = "https://www.twse.com.tw/en/announcement/announcement/list.html"


def parse_twse_instrument_announcements(*, text, url, instrument, fetched_at, receipt_id):
    """Parse each announcement separately. Unrelated/margin notices confer no status.

    A list response is positive evidence only, never complete negative coverage.
    Unsupported wording/corrections stay unresolved instead of guessing intervals.
    """
    if urlparse(url).hostname not in {"www.twse.com.tw", "wwwc.twse.com.tw"}:
        raise ValueError("HISTORICAL_STATUS_UNTRUSTED_OR_UNSUPPORTED_SOURCE")
    soup = BeautifulSoup(text, "html.parser")
    rows = soup.select("tr") or [soup]
    events = []
    limitations = []
    for row in rows:
        plain = " ".join(row.get_text(" ", strip=True).split())
        if not re.search(r"\bcode\s*[:：]\s*" + re.escape(instrument.symbol) + r"\b", plain, re.I):
            continue
        if not re.search(r"Trading of the old (?:stocks|shares) will be suspended", plain, re.I):
            continue
        try:
            interval = parse_twse_suspension_notice(text=str(row), url=url, instrument=instrument,
                fetched_at=fetched_at, receipt_id=receipt_id)
        except ValueError as error:
            limitations.append(str(error))
            continue
        # The lineage hashes the full official response, not an unpersisted fragment.
        lineage = interval.observation.lineage.model_copy(update={
            "content_hash": sha256(text.encode("utf-8")).hexdigest()})
        base = {"stock_id": instrument.symbol, "market": instrument.venue,
                "source_url": url, "lineage": lineage.model_dump(mode="json")}
        events.append({**base, "event_id": f"{receipt_id}:{instrument.symbol}:suspension:{interval.first_date}",
            "event_type": "suspension", "start_date": interval.first_date.isoformat(),
            "end_date": interval.last_date.isoformat(), "status": "suspended"})
        resumes = re.findall(r"new shares will be listed and available for exchange on "
            r"([A-Za-z]+\s+\d{1,2},\s*\d{4})", plain, re.I)
        if len(resumes) == 1:
            resume = datetime.strptime(re.sub(r",\s*", ", ", resumes[0]), "%B %d, %Y").date()
            if resume <= interval.last_date:
                limitations.append("INSTRUMENT_RESUME_DATE_CONFLICT")
                continue
            events.append({**base, "event_id": f"{receipt_id}:{instrument.symbol}:resume:{resume}",
                "event_type": "resume", "start_date": resume.isoformat(), "end_date": resume.isoformat(),
                "status": "tradable"})
            events.append({**base, "event_id": f"{receipt_id}:{instrument.symbol}:basis:{resume}",
                "event_type": "capital_reduction" if re.search(r"capital reduction", plain, re.I)
                              else "price_basis_change",
                "start_date": resume.isoformat(), "end_date": resume.isoformat()})
    return events, tuple(dict.fromkeys(limitations))


def fetch_taiwan_instrument_events(*, instrument, start_date, end_date, timeout_seconds=20):
    """One verified official page, bounded positive evidence, no guessed endpoint."""
    if instrument.venue != "TWSE":
        return {"status": "unresolved", "reason": "OFFICIAL_INSTRUMENT_HISTORY_ACQUISITION_UNAVAILABLE",
                "entries": [], "raw_receipts": [], "evidence_windows": [], "request_count": 0}
    from app.market.providers._http import get
    response = get(TWSE_ANNOUNCEMENTS_URL, provider="twse_openapi",
        resource="tw_corporate_events", target=instrument.symbol, timeout_seconds=timeout_seconds)
    response.raise_for_status()
    response.encoding = "utf-8"
    raw_text = response.text
    fetched_at = datetime.now(timezone.utc)
    digest = sha256(raw_text.encode("utf-8")).hexdigest()
    receipt_id = f"tw.instrument_event:{digest}"
    entries, limitations = parse_twse_instrument_announcements(text=raw_text, url=response.url,
        instrument=instrument, fetched_at=fetched_at, receipt_id=receipt_id)
    entries = [item for item in entries if item["start_date"] <= end_date.isoformat()
               and item["end_date"] >= start_date.isoformat()]
    return {"status": "success" if entries else "unresolved", "entries": entries,
        "reason": None if entries else "OFFICIAL_INSTRUMENT_HISTORY_NOT_IN_RESPONSE",
        "limitations": limitations, "request_count": 1, "evidence_windows": [],
        "raw_receipts": [{"receipt_id": receipt_id, "url": response.url, "raw_text": raw_text,
            "content_hash": digest, "fetched_at": fetched_at.isoformat()}]}


def parse_twse_suspension_notice(*, text, url, instrument, fetched_at, receipt_id):
    if instrument.venue != "TWSE" or urlparse(url).hostname not in {"www.twse.com.tw", "wwwc.twse.com.tw"}:
        raise ValueError("HISTORICAL_STATUS_UNTRUSTED_OR_UNSUPPORTED_SOURCE")
    plain = " ".join(BeautifulSoup(text, "html.parser").get_text(" ", strip=True).split())
    codes = re.findall(r"\bcode\s*[:：]\s*([A-Za-z0-9]+)", plain, flags=re.I)
    if codes != [instrument.symbol]:
        raise ValueError("HISTORICAL_STATUS_AMBIGUOUS_INSTRUMENT")
    spans = re.findall(
        r"Trading of the old (?:stocks|shares) will be suspended during the period of "
        r"([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+to\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\.",
        plain, flags=re.I)
    if len(spans) != 1 or re.search(r"\b(?:cancelled|canceled|revoked|correction|amendment)\b", plain, re.I):
        raise ValueError("HISTORICAL_STATUS_EXPLICIT_INTERVAL_REQUIRED")
    first, last = [datetime.strptime(re.sub(r",\s*", ", ", token), "%B %d, %Y").date() for token in spans[0]]
    if not 0 <= (last - first).days <= 366:
        raise ValueError("HISTORICAL_STATUS_INTERVAL_INVALID")
    return OfficialSuspensionInterval(
        first_date=first, last_date=last, evidence_url=url,
        observation=TradingStatusObservation(
            instrument=instrument, official=True, status=InstrumentTradability.SUSPENDED,
            effective_at=datetime.combine(first, time.min, tzinfo=TAIWAN_TZ),
            reason="Official full-session old-share trading suspension",
            lineage=SourceLineage(provider="twse", source="official_suspension_notice",
                authority=AuthorityClass.EXCHANGE, fetched_at=fetched_at,
                event_at=datetime.combine(first, time.min, tzinfo=TAIWAN_TZ),
                content_hash=sha256(text.encode("utf-8")).hexdigest(), raw_receipt_id=receipt_id)))
