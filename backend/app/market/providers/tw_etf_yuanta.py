from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import ssl
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

from app.http_client import new_session
from app.market.providers._http import DEFAULT_HEADERS, get, post
from app.market.providers.tw_etf_contracts import (
    TaiwanEtfInavRecord,
    TaiwanEtfPcfComponentRecord,
    TaiwanEtfPcfRecord,
)


YUANTA_ETF_API_URL = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"
YUANTA_PCF_PAGE_URL_TEMPLATE = "https://www.yuantaetfs.com/tradeInfo/pcf/{stock_id}"
YUANTA_INAV_HUB_URL = "https://www.yuantaetfs.com/INav/signalr"
YUANTA_INAV_PAGE_URL_TEMPLATE = (
    "https://www.yuantaetfs.com/tradeInfo/comparison/{stock_id}/realtime"
)
YUANTA_PROVIDER = "yuanta_etfs"
YUANTA_INAV_HTTP_REQUEST_COUNT = 5
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class _IssuerCertificateCompatibilityAdapter(HTTPAdapter):
    """Keep TLS verification while accepting the issuer's CA without an SKI."""

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


def _new_yuanta_session() -> requests.Session:
    session = new_session()
    adapter = _IssuerCertificateCompatibilityAdapter()
    session.mount("https://www.yuantaetfs.com/", adapter)
    session.mount("https://etfapi.yuantaetfs.com/", adapter)
    return session


class TaiwanEtfYuantaProviderError(RuntimeError):
    pass


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized.lower() in {"null", "none", "undefined"}:
        return None
    return normalized


def _decimal(value: object) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", "").replace("%", ""))
    except InvalidOperation as exc:
        raise TaiwanEtfYuantaProviderError(f"Invalid Yuanta ETF numeric value: {text}") from exc


def _integer(value: object) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise TaiwanEtfYuantaProviderError(f"Invalid Yuanta ETF integer value: {value}")
    return int(number)


def _yyyymmdd(value: object, *, required: bool = False) -> date | None:
    text = _text(value)
    if text is None:
        if required:
            raise TaiwanEtfYuantaProviderError("Yuanta ETF payload omitted a required date.")
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise TaiwanEtfYuantaProviderError(f"Invalid Yuanta ETF date: {text}") from exc


def _source_datetime(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        local_value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TaiwanEtfYuantaProviderError(
            f"Invalid Yuanta ETF source timestamp: {text}"
        ) from exc
    if local_value.tzinfo is None:
        local_value = local_value.replace(tzinfo=TAIWAN_TZ)
    return local_value.astimezone(timezone.utc)


def _yn(value: object) -> bool | None:
    text = (_text(value) or "").upper()
    if text == "Y":
        return True
    if text == "N":
        return False
    return None


def _component_rows(payload: object, path: tuple[str, ...]) -> list[dict[str, Any]]:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if current in (None, ""):
        return []
    if not isinstance(current, list):
        raise TaiwanEtfYuantaProviderError(
            f"Yuanta ETF PCF field {'.'.join(path)} was not a list."
        )
    rows: list[dict[str, Any]] = []
    for row in current:
        if not isinstance(row, dict):
            raise TaiwanEtfYuantaProviderError(
                f"Yuanta ETF PCF field {'.'.join(path)} contained a malformed row."
            )
        rows.append(row)
    return rows


def parse_yuanta_etf_pcf_payload(payload: object, stock_id: str) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    if not isinstance(payload, dict):
        raise TaiwanEtfYuantaProviderError("Yuanta ETF PCF payload was not an object.")
    pcf = payload.get("PCF")
    if not isinstance(pcf, dict) or not pcf:
        raise TaiwanEtfYuantaProviderError(
            f"Yuanta ETF PCF payload did not contain data for stock_id={normalized_id}."
        )
    payload_id = (_text(pcf.get("markcd")) or "").upper()
    if payload_id != normalized_id:
        raise TaiwanEtfYuantaProviderError(
            f"Yuanta ETF PCF payload returned stock_id={payload_id or 'missing'} "
            f"for requested stock_id={normalized_id}."
        )

    components: list[TaiwanEtfPcfComponentRecord] = []

    def append_rows(
        rows: list[dict[str, Any]],
        *,
        source_section: str,
        asset_type: str,
    ) -> None:
        for row in rows:
            symbol = (_text(row.get("stkcd")) or _text(row.get("code")) or "").upper()
            if not symbol:
                raise TaiwanEtfYuantaProviderError(
                    f"Yuanta ETF PCF {source_section} row omitted its symbol."
                )
            components.append(
                TaiwanEtfPcfComponentRecord(
                    source_section=source_section,
                    asset_type=asset_type,
                    symbol=symbol,
                    name=_text(row.get("name")),
                    name_en=_text(row.get("ename")),
                    contract_month=_text(row.get("ym")),
                    quantity=_decimal(row.get("qty")),
                    weight_pct=_decimal(row.get("weights")),
                    cash_in_lieu=_text(row.get("cashinlieu")),
                    minimum_creation=_yn(row.get("minimum")),
                    order_index=len(components),
                )
            )

    in_kind_rows = _component_rows(payload, ("InKind", "FundComposition"))
    append_rows(
        in_kind_rows,
        source_section="in_kind",
        asset_type="stock",
    )
    if not in_kind_rows:
        weighted_sections = (
            ("StockWeights", "stock"),
            ("FutureWeights", "future"),
            ("ETFWeights", "etf"),
            ("BondWeights", "bond"),
        )
        for section_name, asset_type in weighted_sections:
            append_rows(
                _component_rows(payload, ("FundWeights", section_name)),
                source_section="fund_weights",
                asset_type=asset_type,
            )

    redemption_method = (
        "in_kind"
        if in_kind_rows
        else "cash"
        if components
        else "unknown"
    )
    return TaiwanEtfPcfRecord(
        stock_id=normalized_id,
        fund_id=_text(pcf.get("fundid")),
        fund_name=_text(pcf.get("fundname")),
        full_name=_text(pcf.get("fullname")),
        name_en=_text(pcf.get("ename")),
        reference_date=_yyyymmdd(pcf.get("trandate")),
        effective_date=_yyyymmdd(pcf.get("anndate"), required=True),
        total_net_assets=_decimal(pcf.get("totalav")),
        issued_units=_integer(pcf.get("osunit")),
        unit_nav=_decimal(pcf.get("nav")),
        creation_unit=_integer(pcf.get("baseunit")),
        estimated_creation_value=_decimal(pcf.get("estcvalue")),
        estimated_cash_component=_decimal(pcf.get("estdvalue")),
        unit_change=_integer(pcf.get("issuesdiff")),
        actual_cash_component=_decimal(pcf.get("cashdiff")),
        redemption_method=redemption_method,
        source_updated_at=_source_datetime(pcf.get("upddate")),
        components=tuple(components),
    )


def fetch_yuanta_etf_pcf(
    stock_id: str,
    *,
    target_date: date | None = None,
    session_factory: Callable[[], requests.Session] = _new_yuanta_session,
) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    session = session_factory()
    try:
        payload = _response_json(
            get(
                YUANTA_ETF_API_URL,
                provider=YUANTA_PROVIDER,
                resource="etf_pcf",
                target=normalized_id,
                timeout_seconds=20,
                request_callable=session.request,
                headers={
                    **DEFAULT_HEADERS,
                    "Referer": YUANTA_PCF_PAGE_URL_TEMPLATE.format(stock_id=normalized_id),
                },
                params={
                    "APIType": "ETFAPI",
                    "CompanyName": "YUANTAFUNDS",
                    "PageName": f"/tradeInfo/pcf/{normalized_id}",
                    "DeviceId": "null",
                    "FuncId": "PCF/Daily",
                    "AppName": "ETF",
                    "Device": "3",
                    "Platform": "ETF",
                    "ticker": normalized_id,
                    "ndate": target_date.strftime("%Y%m%d") if target_date else "",
                },
            ),
            "PCF",
        )
    finally:
        session.close()
    return parse_yuanta_etf_pcf_payload(payload, normalized_id)


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise TaiwanEtfYuantaProviderError(
            f"Yuanta ETF iNAV {operation} response was not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise TaiwanEtfYuantaProviderError(
            f"Yuanta ETF iNAV {operation} response was not an object."
        )
    return payload


def _inav_observed_at(etf_set: dict[str, Any]) -> datetime:
    source_time = _source_datetime(etf_set.get("updateT"))
    if source_time is not None:
        return source_time
    epoch_ms = _integer(etf_set.get("UTC_updateT"))
    if epoch_ms is None:
        raise TaiwanEtfYuantaProviderError("Yuanta ETF iNAV omitted its source timestamp.")
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


def parse_yuanta_etf_inav_payload(payload: object, stock_id: str) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    if not isinstance(payload, dict):
        raise TaiwanEtfYuantaProviderError("Yuanta ETF iNAV payload was not an object.")

    raw_records: list[dict[str, Any]] = []
    messages = payload.get("M")
    if not isinstance(messages, list):
        raise TaiwanEtfYuantaProviderError("Yuanta ETF iNAV payload omitted SignalR messages.")
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("H") or "").lower() != "comparehub":
            continue
        if str(message.get("M") or "").lower() != "comparedata":
            continue
        arguments = message.get("A")
        if not isinstance(arguments, list):
            continue
        for argument in arguments:
            if isinstance(argument, list):
                raw_records.extend(row for row in argument if isinstance(row, dict))

    for row in raw_records:
        if str(row.get("etfId") or "").strip().upper() != normalized_id:
            continue
        etf_set = row.get("ETFSet")
        if not isinstance(etf_set, dict):
            raise TaiwanEtfYuantaProviderError(
                f"Yuanta ETF iNAV record for stock_id={normalized_id} omitted ETFSet."
            )
        estimated_nav = _decimal(etf_set.get("nowNav"))
        if estimated_nav is None or estimated_nav <= 0:
            raise TaiwanEtfYuantaProviderError(
                f"Yuanta ETF iNAV record for stock_id={normalized_id} had no valid NAV."
            )
        market_price = _decimal(etf_set.get("nowPrice"))
        if market_price is not None and market_price <= 0:
            market_price = None
        premium_discount_pct = (
            ((market_price - estimated_nav) / estimated_nav) * Decimal("100")
            if market_price is not None
            else None
        )
        return TaiwanEtfInavRecord(
            stock_id=normalized_id,
            fund_short_name=_text(row.get("FUND_SH_NAME")),
            investment_area=_text(etf_set.get("invArea")),
            estimated_nav=estimated_nav,
            nav_change=_decimal(etf_set.get("navFluct")),
            market_price=market_price,
            price_change=_decimal(etf_set.get("priceFluct")),
            premium_discount_pct=premium_discount_pct,
            observed_at=_inav_observed_at(etf_set),
        )
    raise TaiwanEtfYuantaProviderError(
        f"Yuanta ETF iNAV payload did not contain stock_id={normalized_id}."
    )


def fetch_yuanta_etf_inav(
    stock_id: str,
    *,
    session_factory: Callable[[], requests.Session] = _new_yuanta_session,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    connection_data = json.dumps([{"name": "comparehub"}], separators=(",", ":"))
    headers = {
        **DEFAULT_HEADERS,
        "Referer": YUANTA_INAV_PAGE_URL_TEMPLATE.format(stock_id=normalized_id),
    }
    common_params = {
        "clientProtocol": "2.1",
        "connectionData": connection_data,
    }
    session = session_factory()
    try:
        request_callable = session.request
        negotiate = _response_json(
            get(
                f"{YUANTA_INAV_HUB_URL}/negotiate",
                provider=YUANTA_PROVIDER,
                resource="etf_intraday_estimated_nav",
                target=normalized_id,
                timeout_seconds=10,
                request_callable=request_callable,
                headers=headers,
                params=common_params,
            ),
            "negotiate",
        )
        connection_token = _text(negotiate.get("ConnectionToken"))
        if connection_token is None:
            raise TaiwanEtfYuantaProviderError(
                "Yuanta ETF iNAV negotiate response omitted ConnectionToken."
            )
        transport_params = {
            **common_params,
            "transport": "longPolling",
            "connectionToken": connection_token,
        }
        connect = _response_json(
            get(
                f"{YUANTA_INAV_HUB_URL}/connect",
                provider=YUANTA_PROVIDER,
                resource="etf_intraday_estimated_nav",
                target=normalized_id,
                timeout_seconds=10,
                request_callable=request_callable,
                headers=headers,
                params=transport_params,
            ),
            "connect",
        )
        message_id = _text(connect.get("C"))
        if message_id is None:
            raise TaiwanEtfYuantaProviderError(
                "Yuanta ETF iNAV connect response omitted its message id."
            )
        start = _response_json(
            get(
                f"{YUANTA_INAV_HUB_URL}/start",
                provider=YUANTA_PROVIDER,
                resource="etf_intraday_estimated_nav",
                target=normalized_id,
                timeout_seconds=10,
                request_callable=request_callable,
                headers=headers,
                params=transport_params,
            ),
            "start",
        )
        if str(start.get("Response") or "").lower() != "started":
            raise TaiwanEtfYuantaProviderError("Yuanta ETF iNAV SignalR session did not start.")
        invocation = json.dumps(
            {"H": "compareHub", "M": "RetrieveCompare", "A": [], "I": 0},
            separators=(",", ":"),
        )
        _response_json(
            post(
                f"{YUANTA_INAV_HUB_URL}/send",
                provider=YUANTA_PROVIDER,
                resource="etf_intraday_estimated_nav",
                target=normalized_id,
                timeout_seconds=10,
                request_callable=request_callable,
                headers=headers,
                params=transport_params,
                data={"data": invocation},
            ),
            "send",
        )
        poll_payload = _response_json(
            get(
                f"{YUANTA_INAV_HUB_URL}/poll",
                provider=YUANTA_PROVIDER,
                resource="etf_intraday_estimated_nav",
                target=normalized_id,
                timeout_seconds=10,
                request_callable=request_callable,
                headers=headers,
                params={**transport_params, "messageId": message_id},
            ),
            "poll",
        )
    finally:
        session.close()
    return parse_yuanta_etf_inav_payload(poll_payload, normalized_id)


__all__ = [
    "TaiwanEtfInavRecord",
    "TaiwanEtfPcfComponentRecord",
    "TaiwanEtfPcfRecord",
    "TaiwanEtfYuantaProviderError",
    "YUANTA_ETF_API_URL",
    "YUANTA_INAV_HTTP_REQUEST_COUNT",
    "YUANTA_INAV_HUB_URL",
    "YUANTA_PROVIDER",
    "fetch_yuanta_etf_inav",
    "fetch_yuanta_etf_pcf",
    "parse_yuanta_etf_inav_payload",
    "parse_yuanta_etf_pcf_payload",
]
