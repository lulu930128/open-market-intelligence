from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
import ssl
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

from app.http_client import new_session
from app.market.providers.tw_etf_contracts import TaiwanEtfInavRecord


NOMURA_PROVIDER = "nomura_etfs"
NOMURA_INAV_URL = (
    "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundIntradayNAV"
)
NOMURA_INAV_PAGE_URL = "https://www.nomurafunds.com.tw/ETFWEB/inav"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class _NomuraCertificateCompatibilityAdapter(HTTPAdapter):
    """Retain certificate verification but relax legacy missing-SKI strictness."""

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        context = ssl.create_default_context()
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict_flag:
            context.verify_flags &= ~strict_flag
        return context

    def init_poolmanager(
        self,
        connections: int,
        maxsize: int,
        block: bool = False,
        **pool_kwargs: Any,
    ) -> None:
        pool_kwargs["ssl_context"] = self._ssl_context()
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any):
        proxy_kwargs["ssl_context"] = self._ssl_context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _new_nomura_session() -> requests.Session:
    session = new_session()
    session.mount(
        "https://www.nomurafunds.com.tw/",
        _NomuraCertificateCompatibilityAdapter(),
    )
    return session


class TaiwanEtfNomuraProviderError(RuntimeError):
    pass


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized.casefold() in {"null", "none", "undefined", "-", "--"}:
        return None
    return normalized


def _decimal(value: object) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return Decimal(normalized.replace(",", "").replace("%", ""))
    except InvalidOperation as exc:
        raise TaiwanEtfNomuraProviderError(
            f"Invalid Nomura ETF numeric value: {normalized}"
        ) from exc


def parse_nomura_etf_inav_payload(payload: object, stock_id: str) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    if not isinstance(payload, dict) or payload.get("StatusCode") != 0:
        raise TaiwanEtfNomuraProviderError("Nomura ETF iNAV response was not successful.")
    rows = payload.get("Entries")
    if not isinstance(rows, list):
        raise TaiwanEtfNomuraProviderError("Nomura ETF iNAV Entries was not a list.")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("CStockNo") or row.get("CFundId") or "").strip().upper()
        == normalized_id
    ]
    if len(matches) != 1:
        raise TaiwanEtfNomuraProviderError(
            f"Nomura ETF iNAV returned {len(matches)} exact matches for stock_id={normalized_id}."
        )
    row = matches[0]
    estimated_nav = _decimal(row.get("CEstimateNav"))
    if estimated_nav is None or estimated_nav <= 0:
        raise TaiwanEtfNomuraProviderError(
            f"Nomura ETF iNAV for stock_id={normalized_id} had no valid NAV."
        )
    timestamp = _text(row.get("CDataDt"))
    if timestamp is None:
        raise TaiwanEtfNomuraProviderError("Nomura ETF iNAV omitted its source timestamp.")
    try:
        observed_at = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S").replace(
            tzinfo=TAIWAN_TZ
        )
    except ValueError as exc:
        raise TaiwanEtfNomuraProviderError(
            f"Invalid Nomura ETF iNAV timestamp: {timestamp}"
        ) from exc
    previous_nav = _decimal(row.get("CLastDayNav"))
    market_price = _decimal(row.get("CLatestMarketPrice"))
    previous_price = _decimal(row.get("CLastDayMarketPrice"))
    if market_price is not None and market_price <= 0:
        market_price = None
    return TaiwanEtfInavRecord(
        stock_id=normalized_id,
        fund_short_name=_text(row.get("CFundShortName")),
        investment_area=None,
        estimated_nav=estimated_nav,
        nav_change=(estimated_nav - previous_nav) if previous_nav is not None else None,
        market_price=market_price,
        price_change=(
            market_price - previous_price
            if market_price is not None and previous_price is not None
            else None
        ),
        premium_discount_pct=_decimal(row.get("CDiffPct")),
        observed_at=observed_at,
    )


def fetch_nomura_etf_inav(
    stock_id: str,
    *,
    session_factory: Callable[[], requests.Session] = _new_nomura_session,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    session = session_factory()
    try:
        response = session.request(
            "POST",
            NOMURA_INAV_URL,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Content-Type": "application/json",
                "Referer": NOMURA_INAV_PAGE_URL,
            },
            json={
                "Type": 2,
                "Keyword": normalized_id,
                "FundType": 0,
                "FundNo": "",
                "PageIndex": 1,
                "PageSize": 50,
                "IsPagination": True,
                "SortColName": "",
                "IsDesc": False,
            },
        )
        response.raise_for_status()
        return parse_nomura_etf_inav_payload(response.json(), normalized_id)
    finally:
        session.close()


__all__ = [
    "NOMURA_INAV_PAGE_URL",
    "NOMURA_INAV_URL",
    "NOMURA_PROVIDER",
    "TaiwanEtfNomuraProviderError",
    "fetch_nomura_etf_inav",
    "parse_nomura_etf_inav_payload",
]
