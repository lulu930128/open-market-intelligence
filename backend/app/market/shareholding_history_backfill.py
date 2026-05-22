from __future__ import annotations

import hashlib
import time
from datetime import date

import requests
from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, ShareholdingDistributionWeekly, SourceRegistry


TDCC_SHAREHOLDING_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
TDCC_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None

    normalized = value.replace(",", "").strip()
    if not normalized:
        return None

    try:
        return int(normalized)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None

    normalized = value.replace(",", "").replace("%", "").strip()
    if not normalized:
        return None

    try:
        return float(normalized)
    except ValueError:
        return None


def _parse_yyyymmdd(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _get_tdcc_source(db: Session) -> SourceRegistry:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category == "shareholding_distribution")
        .filter(SourceRegistry.parser_type == "tdcc_shareholding_distribution")
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .first()
    )

    if source is None:
        raise ValueError("TDCC shareholding distribution source is not configured.")

    return source


def _existing_level_count(
    db: Session,
    source_id: int,
    stock_id: str,
    data_date: date,
) -> int:
    return (
        db.query(func.count(ShareholdingDistributionWeekly.id))
        .filter(ShareholdingDistributionWeekly.source_id == source_id)
        .filter(ShareholdingDistributionWeekly.stock_id == stock_id)
        .filter(ShareholdingDistributionWeekly.data_date == data_date)
        .scalar()
        or 0
    )


def _create_raw_result(
    db: Session,
    source_id: int,
    raw_text: str,
    status_code: int,
) -> RawFetchResult:
    raw_result = RawFetchResult(
        source_id=source_id,
        url=TDCC_SHAREHOLDING_URL,
        method="POST",
        status_code=status_code,
        content_type="text/html",
        content_hash=hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest(),
        raw_text=raw_text,
        parser_version="tdcc-shareholding-history-v1",
    )
    db.add(raw_result)
    db.flush()
    return raw_result


def _load_query_form(session: requests.Session) -> tuple[list[str], dict[str, str]]:
    response = session.get(TDCC_SHAREHOLDING_URL, headers=TDCC_HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    token = soup.find(id="SYNCHRONIZER_TOKEN")
    fir_date = soup.find(id="firDate")
    date_options = [option.get("value") for option in soup.select("#scaDate option")]
    dates = [item for item in date_options if item]

    if token is None or not token.get("value") or fir_date is None or not fir_date.get("value"):
        raise ValueError("TDCC shareholding query token was not found.")

    if not dates:
        raise ValueError("TDCC shareholding query dates were not found.")

    return dates, {
        "SYNCHRONIZER_TOKEN": token["value"],
        "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
        "method": "submit",
        "firDate": fir_date["value"],
    }


def _fetch_stock_shareholding_html(
    session: requests.Session,
    form_base: dict[str, str],
    stock_id: str,
    date_value: str,
) -> requests.Response:
    payload = {
        **form_base,
        "scaDate": date_value,
        "sqlMethod": "StockNo",
        "stockNo": stock_id,
        "stockName": "",
    }
    response = session.post(
        TDCC_SHAREHOLDING_URL,
        data=payload,
        headers={**TDCC_HEADERS, "Referer": TDCC_SHAREHOLDING_URL},
        timeout=30,
    )
    response.raise_for_status()
    return response


def _refresh_form_base_from_html(form_base: dict[str, str], html: str) -> None:
    soup = BeautifulSoup(html, "lxml")
    token = soup.find(id="SYNCHRONIZER_TOKEN")
    fir_date = soup.find(id="firDate")

    if token is not None and token.get("value"):
        form_base["SYNCHRONIZER_TOKEN"] = token["value"]

    if fir_date is not None and fir_date.get("value"):
        form_base["firDate"] = fir_date["value"]


def _extract_stock_name(soup: BeautifulSoup) -> str | None:
    text = soup.get_text("\n", strip=True)
    marker = "證券名稱："
    if marker not in text:
        return None

    tail = text.split(marker, 1)[1].strip()
    return tail.splitlines()[0].strip() or None


def _parse_shareholding_rows(
    html: str,
    source_id: int,
    raw_result_id: int,
    stock_id: str,
    data_date: date,
) -> list[ShareholdingDistributionWeekly]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")

    if len(tables) < 2:
        return []

    stock_name = _extract_stock_name(soup)
    rows: list[ShareholdingDistributionWeekly] = []

    for table_row in tables[1].find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all(["td", "th"])]
        if len(cells) < 5:
            continue

        level_order = _parse_int(cells[0])
        if level_order is None or level_order < 1 or level_order > 15:
            continue

        rows.append(
            ShareholdingDistributionWeekly(
                source_id=source_id,
                raw_result_id=raw_result_id,
                data_date=data_date,
                stock_id=stock_id,
                stock_name=stock_name,
                holding_level=str(level_order),
                holding_level_order=level_order,
                holder_count=_parse_int(cells[2]),
                share_count=_parse_int(cells[3]),
                share_ratio=_parse_float(cells[4]),
            )
        )

    return rows


def ensure_stock_shareholding_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    lookback_weeks: int = 52,
    sleep_seconds: float = 0.1,
    skip_existing: bool = True,
) -> dict:
    source = _get_tdcc_source(db)
    session = requests.Session()
    dates, form_base = _load_query_form(session)
    selected_dates = []

    for date_value in dates:
        current_date = _parse_yyyymmdd(date_value)

        if from_date is not None and current_date < from_date:
            continue

        if to_date is not None and current_date > to_date:
            continue

        selected_dates.append((date_value, current_date))

    selected_dates = selected_dates[:lookback_weeks]
    results: list[dict] = []
    fetched_count = 0
    skipped_existing_count = 0
    inserted_count = 0
    error_count = 0

    for date_value, current_date in selected_dates:
        existing_count = _existing_level_count(
            db=db,
            source_id=source.id,
            stock_id=stock_id,
            data_date=current_date,
        )

        if skip_existing and existing_count >= 15:
            skipped_existing_count += 1
            results.append(
                {
                    "date": current_date.isoformat(),
                    "status": "skipped_existing",
                    "inserted_count": 0,
                    "existing_row_count": existing_count,
                    "error_message": None,
                }
            )
            continue

        try:
            response = _fetch_stock_shareholding_html(
                session=session,
                form_base=form_base,
                stock_id=stock_id,
                date_value=date_value,
            )
            _refresh_form_base_from_html(form_base=form_base, html=response.text)
            fetched_count += 1
            raw_result = _create_raw_result(
                db=db,
                source_id=source.id,
                raw_text=response.text,
                status_code=response.status_code,
            )
            parsed_rows = _parse_shareholding_rows(
                html=response.text,
                source_id=source.id,
                raw_result_id=raw_result.id,
                stock_id=stock_id,
                data_date=current_date,
            )
            date_inserted_count = 0

            for row in parsed_rows:
                exists = (
                    db.query(ShareholdingDistributionWeekly.id)
                    .filter(ShareholdingDistributionWeekly.source_id == row.source_id)
                    .filter(ShareholdingDistributionWeekly.stock_id == row.stock_id)
                    .filter(ShareholdingDistributionWeekly.data_date == row.data_date)
                    .filter(ShareholdingDistributionWeekly.holding_level == row.holding_level)
                    .first()
                )

                if exists:
                    continue

                db.add(row)
                date_inserted_count += 1

            db.commit()
            inserted_count += date_inserted_count
            results.append(
                {
                    "date": current_date.isoformat(),
                    "status": "success",
                    "inserted_count": date_inserted_count,
                    "existing_row_count": existing_count,
                    "raw_result_id": raw_result.id,
                    "error_message": None,
                }
            )
        except Exception as exc:
            db.rollback()
            error_count += 1
            results.append(
                {
                    "date": current_date.isoformat(),
                    "status": "error",
                    "inserted_count": 0,
                    "existing_row_count": existing_count,
                    "error_message": str(exc),
                }
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    status = "success"
    if error_count:
        status = "partial_success" if inserted_count or skipped_existing_count else "error"

    return {
        "status": status,
        "stock_id": stock_id,
        "available_date_count": len(dates),
        "requested_date_count": len(selected_dates),
        "fetched_count": fetched_count,
        "skipped_existing_count": skipped_existing_count,
        "inserted_count": inserted_count,
        "error_count": error_count,
        "results": results,
    }


__all__ = ["ensure_stock_shareholding_history"]
