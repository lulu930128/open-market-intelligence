"""Read-only JSON-lines bridge for the optional KGI SuperPy runtime.

This module deliberately uses only the Python standard library before importing
``kgisuperpy``.  It is executed by the isolated ``.venv-kgi`` interpreter and
exposes a very small command allowlist: subscribe, unsubscribe, status,
bounded market-data ``data_get``, normalized portfolio ``portfolio_get`` and
shutdown. Trading commands are never accepted by this process.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
import re
import sys
from threading import RLock, Thread
import time
from typing import Any


PROTOCOL_VERSION = "kgi-superpy-quote-v1"
REQUIRED_PYTHON_VERSION = (3, 12)
_PROTOCOL_STDOUT = sys.stdout
_WRITE_LOCK = RLock()
_STATE_LOCK = RLock()
_API: Any = None
_QUOTE_READY = False
_ACCOUNT_SECRETS: set[str] = set()
_ACTIVE_SYMBOLS: set[str] = set()
_RECONNECTING = False

_DATA_RESOURCE_TABLES = {
    "market_snapshot": "批次取得個股盤中行情-含興櫃(tick含試搓)",
    "today_trades": "取得今日即時成交明細(含五檔報價)",
    "minute_kbars": "取得歷史分K(指定日期前)",
    "price_volume": "取得指定日期前幾天的分價量歷史資料",
}
_DATA_TIMEFRAMES = {1, 3, 5, 15, 30, 60}
_DATA_MAX_ROWS = 500
_DATA_MAX_PRICE_VOLUME_DAYS = 5


def _runtime_compatibility_error(
    version: tuple[int, int] | None = None,
    pointer_bits: int | None = None,
) -> str | None:
    selected_version = version or sys.version_info[:2]
    selected_bits = pointer_bits or (64 if sys.maxsize > 2**32 else 32)
    if selected_version != REQUIRED_PYTHON_VERSION:
        return (
            "KGI SuperPy quote bridge requires Python 3.12 because Python 3.13 "
            "strict X.509 validation is incompatible with the current KGI "
            "certificate chain. Rebuild .venv-kgi with "
            "scripts/setup-kgi-superpy.ps1 -Recreate."
        )
    if selected_bits != 64:
        return "KGI SuperPy quote bridge requires 64-bit Python 3.12."
    return None


def _emit(message: dict[str, Any]) -> None:
    with _WRITE_LOCK:
        _PROTOCOL_STDOUT.write(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        _PROTOCOL_STDOUT.flush()


def _secret(value: str | None) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _safe_error(exc: BaseException) -> str:
    message = str(exc) or type(exc).__name__
    for value in (
        _secret(os.environ.get("KGI_SUPERPY_PERSON_ID")),
        _secret(os.environ.get("KGI_SUPERPY_PASSWORD")),
        _secret(os.environ.get("KGI_SUPERPY_TW_ACCOUNT")),
        _secret(os.environ.get("KGI_SUPERPY_US_ACCOUNT")),
        *_ACCOUNT_SECRETS,
    ):
        if value:
            message = message.replace(value, "[redacted]")
    return message[:1000]


def _safe_text(value: Any) -> str:
    return _safe_error(RuntimeError(str(value or "")))


def _as_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    scalar = getattr(value, "item", None)
    if callable(scalar):
        return _as_json_value(scalar())
    if isinstance(value, (list, tuple)):
        return [_as_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_json_value(item) for key, item in value.items()}
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return _as_json_value(enum_value)
    return str(value)


def _quote_payload(data: Any) -> dict[str, Any]:
    fields = (
        "exchange",
        "symbol",
        "delay_time",
        "odd_lot",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_volume",
        "bid_prices",
        "bid_volumes",
        "ask_prices",
        "ask_volumes",
        "amount",
        "chg_type",
        "price_chg",
        "pct_chg",
        "diff_bid_vol",
        "diff_ask_vol",
        "simtrade",
        "suspend",
    )
    payload = {
        field: _as_json_value(getattr(data, field, None))
        for field in fields
    }
    payload["received_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def _kbar_payload(data: Any) -> dict[str, Any]:
    fields = (
        "exchange",
        "symbol",
        "datetime",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "avg_price",
        "total_amount",
    )
    payload = {
        field: _as_json_value(getattr(data, field, None))
        for field in fields
    }
    payload["received_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def _event_payload(event: Any) -> dict[str, Any]:
    raw_info = getattr(event, "info", None)
    safe_info = (
        {
            str(key): _as_json_value(value)
            for key, value in raw_info.items()
            if str(key) in {"market", "sub_id", "symbol", "quote_type"}
        }
        if isinstance(raw_info, dict)
        else {}
    )
    return {
        "api_id": _as_json_value(getattr(event, "api_id", None)),
        "event_code": _as_json_value(getattr(event, "event_code", None)),
        "respond_code": _as_json_value(getattr(event, "respond_code", None)),
        "info": safe_info,
        "event_msg": _safe_text(getattr(event, "event_msg", None)),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _on_quote(data):
    _emit({"type": "quote", "protocol": PROTOCOL_VERSION, "data": _quote_payload(data)})


def _on_kbar(data):
    _emit({"type": "kbar", "protocol": PROTOCOL_VERSION, "data": _kbar_payload(data)})


def _subscribe_symbol(api: Any, symbol: str) -> str | None:
    api.Quote.subscribe_all(symbol, odd_lot=False)
    try:
        api.Quote.subscribe_kbar(symbol, minute=1)
    except Exception as exc:
        return _safe_error(exc)
    return None


def _resubscribe_after_disconnect() -> None:
    global _RECONNECTING
    try:
        for attempt in range(1, 4):
            time.sleep(min(attempt * 2, 5))
            with _STATE_LOCK:
                api = _API
                symbols = sorted(_ACTIVE_SYMBOLS)
            if api is None or not symbols:
                return
            try:
                kbar_warnings: dict[str, str] = {}
                for symbol in symbols:
                    warning = _subscribe_symbol(api, symbol)
                    if warning:
                        kbar_warnings[symbol] = warning
                _emit(
                    {
                        "type": "status",
                        "protocol": PROTOCOL_VERSION,
                        "status": "resubscribe_requested",
                        "symbols": symbols,
                        "attempt": attempt,
                        "kbar_warnings": kbar_warnings,
                    }
                )
                return
            except Exception as exc:
                _emit(
                    {
                        "type": "status",
                        "protocol": PROTOCOL_VERSION,
                        "status": "reconnect_failed",
                        "attempt": attempt,
                        "error": _safe_error(exc),
                    }
                )
    finally:
        with _STATE_LOCK:
            _RECONNECTING = False


def _on_event(event):
    global _RECONNECTING
    payload = _event_payload(event)
    _emit({"type": "event", "protocol": PROTOCOL_VERSION, "data": payload})
    if payload.get("event_code") != "EVENT_DISCONNECTED":
        return
    with _STATE_LOCK:
        if _RECONNECTING or not _ACTIVE_SYMBOLS:
            return
        _RECONNECTING = True
    Thread(target=_resubscribe_after_disconnect, daemon=True).start()


def _close_login(api: Any) -> None:
    if api is None:
        return
    logout = getattr(api, "logout", None)
    if callable(logout):
        logout()
        return
    order = getattr(api, "_ObjOrder", None)
    raw_logout = getattr(order, "Logout", None)
    if callable(raw_logout):
        raw_logout()


def _ensure_api_login() -> Any:
    global _API
    with _STATE_LOCK:
        if _API is not None:
            return _API

        person_id = _secret(os.environ.get("KGI_SUPERPY_PERSON_ID"))
        password = _secret(os.environ.get("KGI_SUPERPY_PASSWORD"))
        if not person_id or not password:
            raise RuntimeError("KGI SuperPy credentials are not configured.")

        simulation = _secret(os.environ.get("KGI_SUPERPY_SIMULATION")).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        import kgisuperpy as kgi

        api = kgi.login(person_id, password, simulation)
        _API = api
        return api


def _ensure_login() -> Any:
    global _API, _QUOTE_READY
    with _STATE_LOCK:
        if _API is not None and _QUOTE_READY:
            return _API

        api = _ensure_api_login()
        quote = getattr(api, "Quote", None)
        if quote is None:
            order = getattr(api, "_ObjOrder", None)
            url = getattr(order, "_URL", None)
            logged_in = bool(getattr(order, "FIsLogon", False))
            quote_token_ready = bool(getattr(url, "token", None))
            try:
                _API = None
                _QUOTE_READY = False
                _close_login(api)
            finally:
                if not logged_in:
                    raise RuntimeError(
                        "KGI SuperPy login did not initialize the quote service; "
                        "verify the Windows CA component/certificate, API "
                        "qualification, and credentials."
                    )
                if not quote_token_ready:
                    raise RuntimeError(
                        "KGI SuperPy login completed without a quote token; "
                        "verify market-data permission and API qualification."
                    )
                raise RuntimeError(
                    "KGI SuperPy login completed but the Quote facade is unavailable."
                )
        try:
            quote.set_cb_all(_on_quote)
            quote.set_cb_kbar(_on_kbar)
            quote.set_cb_event(_on_event)
        except Exception:
            _API = None
            _QUOTE_READY = False
            _close_login(api)
            raise
        _QUOTE_READY = True
        return api


def _ensure_account_login() -> Any:
    global _API
    api = _ensure_api_login()
    if callable(getattr(api, "show_account", None)):
        return api

    order = getattr(api, "_ObjOrder", None)
    logged_in = bool(getattr(order, "FIsLogon", False))
    with _STATE_LOCK:
        quote_ready = _QUOTE_READY
        if not quote_ready and _API is api:
            _API = None
    cleanup_error: str | None = None
    if not quote_ready:
        try:
            _close_login(api)
        except Exception as exc:
            cleanup_error = _safe_error(exc)
    cleanup_note = f" Cleanup also failed: {cleanup_error}" if cleanup_error else ""
    if not logged_in:
        raise RuntimeError(
            "KGI SuperPy login did not initialize the account service; verify "
            "the Windows CA component/certificate, API qualification, and credentials."
            + cleanup_note
        )
    raise RuntimeError(
        "KGI SuperPy login completed but account discovery is unavailable."
        + cleanup_note
    )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _frame_records(frame: Any, *, required_columns: set[str]) -> list[dict[str, Any]]:
    if frame is None or not hasattr(frame, "to_dict") or not hasattr(frame, "columns"):
        raise RuntimeError("KGI portfolio query returned an unsupported payload type.")
    columns = {str(column) for column in frame.columns}
    missing = sorted(required_columns - columns)
    if missing:
        raise RuntimeError(
            "KGI portfolio query is missing required fields: " + ", ".join(missing)
        )
    return [dict(row) for row in frame.to_dict(orient="records")]


def _normalize_portfolio_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.$/\-]{0,31}", symbol):
        raise RuntimeError("KGI portfolio query returned an invalid symbol.")
    return symbol


def _tw_portfolio_records(frame: Any) -> tuple[list[dict[str, Any]], list[str]]:
    rows = _frame_records(
        frame,
        required_columns={
            "Symbol",
            "NETQTY9",
            "NETQTY0",
            "NETQTY3",
            "NETQTY4",
            "AVG_PRICE0",
            "AVG_PRICE3",
        },
    )
    aggregated: dict[str, dict[str, Any]] = {}
    short_symbols: set[str] = set()
    missing_cost_symbols: set[str] = set()

    for row in rows:
        quantities: dict[str, float] = {}
        for field in ("NETQTY9", "NETQTY0", "NETQTY3", "NETQTY4"):
            parsed = _number(row.get(field))
            if parsed is None and str(row.get(field) or "").strip():
                raise RuntimeError(f"KGI Taiwan holding field {field} is malformed.")
            quantities[field] = parsed or 0.0

        if quantities["NETQTY4"] > 0:
            raw_symbol = str(row.get("Symbol") or "").strip()
            if raw_symbol:
                short_symbols.add(_normalize_portfolio_symbol(raw_symbol))

        cash_quantity = max(quantities["NETQTY9"], 0) + max(quantities["NETQTY0"], 0)
        margin_quantity = max(quantities["NETQTY3"], 0)
        quantity = cash_quantity + margin_quantity
        if quantity <= 0:
            continue

        symbol = _normalize_portfolio_symbol(row.get("Symbol"))
        cash_price = _number(row.get("AVG_PRICE0"))
        margin_price = _number(row.get("AVG_PRICE3"))
        cost_known = not (
            (cash_quantity > 0 and (cash_price is None or cash_price <= 0))
            or (margin_quantity > 0 and (margin_price is None or margin_price <= 0))
        )
        row_cost = (
            cash_quantity * (cash_price or 0)
            + margin_quantity * (margin_price or 0)
            if cost_known
            else None
        )
        current = aggregated.setdefault(
            symbol,
            {
                "symbol": symbol,
                "symbol_name": str(row.get("SymbolName") or "").strip() or None,
                "quantity": 0.0,
                "cost_amount": 0.0,
                "currency": (
                    "TWD"
                    if str(row.get("CURRENCY") or "TWD").strip().upper() == "NTD"
                    else str(row.get("CURRENCY") or "TWD").strip().upper() or "TWD"
                ),
                "cost_known": True,
            },
        )
        current["quantity"] += quantity
        if row_cost is None:
            current["cost_known"] = False
            missing_cost_symbols.add(symbol)
        else:
            current["cost_amount"] += row_cost
        if not current.get("symbol_name"):
            current["symbol_name"] = str(row.get("SymbolName") or "").strip() or None

    records: list[dict[str, Any]] = []
    for symbol in sorted(aggregated):
        item = aggregated[symbol]
        records.append(
            {
                "symbol": item["symbol"],
                "symbol_name": item["symbol_name"],
                "quantity": item["quantity"],
                "cost_amount": item["cost_amount"] if item["cost_known"] else None,
                "currency": item["currency"],
            }
        )

    warnings: list[str] = []
    if short_symbols:
        warnings.append(f"excluded_short_positions:{len(short_symbols)}")
    if missing_cost_symbols:
        warnings.append(f"missing_cost_basis:{len(missing_cost_symbols)}")
    return records, warnings


def _us_portfolio_records(frame: Any) -> tuple[list[dict[str, Any]], list[str]]:
    rows = _frame_records(frame, required_columns={"symbol", "Qty", "currency"})
    aggregated: dict[str, dict[str, Any]] = {}
    short_symbols: set[str] = set()
    for row in rows:
        market = str(row.get("market") or "US").strip().upper()
        if market and market != "US":
            continue
        quantity = _number(row.get("Qty"))
        if quantity is None:
            if str(row.get("symbol") or "").strip():
                raise RuntimeError("KGI US holding quantity is malformed.")
            continue
        if quantity < 0:
            short_symbols.add(_normalize_portfolio_symbol(row.get("symbol")))
            continue
        if quantity == 0:
            continue
        symbol = _normalize_portfolio_symbol(row.get("symbol"))
        current = aggregated.setdefault(
            symbol,
            {
                "symbol": symbol,
                "symbol_name": str(row.get("symbol_name") or "").strip() or None,
                "quantity": 0.0,
                "cost_amount": None,
                "currency": str(row.get("currency") or "USD").strip().upper() or "USD",
            },
        )
        current["quantity"] += quantity
        if not current.get("symbol_name"):
            current["symbol_name"] = str(row.get("symbol_name") or "").strip() or None

    records = [aggregated[symbol] for symbol in sorted(aggregated)]
    warnings: list[str] = []
    if short_symbols:
        warnings.append(f"excluded_short_positions:{len(short_symbols)}")
    if records:
        warnings.append(f"missing_cost_basis:{len(records)}")
    return records, warnings


def _select_account(api: Any, market: str) -> str:
    show_account = getattr(api, "show_account", None)
    if not callable(show_account):
        raise RuntimeError("KGI account discovery is unavailable after login.")
    accounts = show_account()
    if not isinstance(accounts, list):
        raise RuntimeError("KGI account discovery returned an invalid payload.")

    account_flag = "證券" if market == "tw" else "複委託"
    env_name = "KGI_SUPERPY_TW_ACCOUNT" if market == "tw" else "KGI_SUPERPY_US_ACCOUNT"
    configured = _secret(os.environ.get(env_name))
    candidates = [
        str(item.get("account") or "").strip()
        for item in accounts
        if isinstance(item, dict)
        and account_flag in str(item.get("account_flag") or "")
        and str(item.get("account") or "").strip()
    ]
    candidates = list(dict.fromkeys(candidates))
    with _STATE_LOCK:
        _ACCOUNT_SECRETS.update(candidates)
    if configured:
        if configured not in candidates:
            raise RuntimeError(f"Configured {env_name} is not available for this login.")
        return configured
    if not candidates:
        raise RuntimeError(f"No KGI {account_flag} account is available for this login.")
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple KGI {account_flag} accounts are available; configure {env_name}."
        )
    return candidates[0]


def _portfolio_get(message: dict[str, Any]) -> dict[str, Any]:
    market = str(message.get("market") or "").strip().lower()
    if market not in {"tw", "us"}:
        raise ValueError("KGI portfolio market must be tw or us.")

    api = _ensure_account_login()
    account = _select_account(api, market)
    if market == "tw":
        setter = getattr(api, "set_Account", None)
        if not callable(setter):
            raise RuntimeError("KGI Taiwan account initialization is unavailable.")
        setter(account)
        facade = getattr(api, "Account", None)
        query = getattr(facade, "InventorySum", None)
        if not callable(query):
            raise RuntimeError("KGI Taiwan inventory query is unavailable.")
        records, warnings = _tw_portfolio_records(query("B"))
        source_api = "Account.InventorySum"
    else:
        setter = getattr(api, "set_SubAccount", None)
        if not callable(setter):
            raise RuntimeError("KGI US account initialization is unavailable.")
        setter(account)
        facade = getattr(api, "SubAccount", None)
        query = getattr(facade, "StockPositionReport", None)
        if not callable(query):
            raise RuntimeError("KGI US position query is unavailable.")
        records, warnings = _us_portfolio_records(query())
        source_api = "SubAccount.StockPositionReport"

    return {
        "market": market,
        "source": "kgi_superpy",
        "source_api": source_api,
        "holding_count": len(records),
        "records": records,
        "warnings": warnings,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip()
    if not symbol or not symbol.isalnum() or len(symbol) > 16:
        raise ValueError("A valid Taiwan stock symbol is required.")
    return symbol


def _normalize_data_date(value: Any) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", normalized):
        raise ValueError("trade_date must use YYYYMMDD.")
    datetime.strptime(normalized, "%Y%m%d")
    return normalized


def _data_get(message: dict[str, Any]) -> dict[str, Any]:
    resource = str(message.get("resource") or "").strip().lower()
    table = _DATA_RESOURCE_TABLES.get(resource)
    if table is None:
        raise ValueError(f"Unsupported KGI Data resource: {resource or '<empty>'}")

    symbol = _normalize_symbol(message.get("symbol"))
    limit = int(message.get("limit") or 200)
    if limit < 1 or limit > _DATA_MAX_ROWS:
        raise ValueError(f"limit must be between 1 and {_DATA_MAX_ROWS}.")

    args: tuple[Any, ...]
    parameters: dict[str, Any] = {"symbol": symbol, "limit": limit}
    if resource == "market_snapshot":
        args = ([symbol],)
    elif resource == "today_trades":
        args = (symbol,)
    elif resource == "minute_kbars":
        trade_date = _normalize_data_date(message.get("trade_date"))
        timeframe = int(message.get("timeframe_minutes") or 1)
        if timeframe not in _DATA_TIMEFRAMES:
            raise ValueError("timeframe_minutes must be one of 1, 3, 5, 15, 30, 60.")
        parameters.update(
            {"trade_date": trade_date, "timeframe_minutes": timeframe}
        )
        args = (symbol, trade_date, timeframe)
    else:
        trade_date = _normalize_data_date(message.get("trade_date"))
        days = int(message.get("days") or 1)
        if days < 1 or days > _DATA_MAX_PRICE_VOLUME_DAYS:
            raise ValueError(
                f"days must be between 1 and {_DATA_MAX_PRICE_VOLUME_DAYS}."
            )
        parameters.update({"trade_date": trade_date, "days": days})
        args = (symbol, trade_date, days)

    api = _ensure_login()
    data_facade = getattr(api, "Data", None)
    if data_facade is None or not callable(getattr(data_facade, "get", None)):
        raise RuntimeError("KGI Data facade is unavailable after login.")
    frame = data_facade.get(table, *args)
    if not hasattr(frame, "to_dict") or not hasattr(frame, "columns"):
        raise RuntimeError("KGI Data returned an unsupported payload type.")

    total_rows = int(len(frame))
    selected = frame.tail(limit)
    records = [
        {str(key): _as_json_value(value) for key, value in row.items()}
        for row in selected.to_dict(orient="records")
    ]
    return {
        "resource": resource,
        "table": table,
        "parameters": parameters,
        "row_count": total_rows,
        "returned_count": len(records),
        "truncated": total_rows > len(records),
        "columns": [str(column) for column in frame.columns],
        "records": records,
    }


def _subscribe(symbol: str) -> dict[str, Any]:
    api = _ensure_login()
    with _STATE_LOCK:
        if symbol in _ACTIVE_SYMBOLS:
            return {"status": "already_subscribed", "symbol": symbol}
        _ACTIVE_SYMBOLS.add(symbol)
    try:
        kbar_warning = _subscribe_symbol(api, symbol)
    except Exception:
        with _STATE_LOCK:
            _ACTIVE_SYMBOLS.discard(symbol)
        raise
    return {
        "status": "subscription_requested",
        "symbol": symbol,
        "kbar_status": "unavailable" if kbar_warning else "subscription_requested",
        "kbar_warning": kbar_warning,
    }


def _unsubscribe(symbol: str) -> dict[str, Any]:
    with _STATE_LOCK:
        api = _API
        _ACTIVE_SYMBOLS.discard(symbol)
    if api is None:
        return {"status": "not_connected", "symbol": symbol}

    labels = list(api.Quote.get_subscriptions() or [])
    matching = [
        str(label)
        for label in labels
        if ("qtAll" in str(label) or "qtKBar" in str(label))
        and symbol in str(label).split(".")
    ]
    for label in matching:
        api.Quote.unsubscribe(label)
    return {
        "status": "unsubscribed" if matching else "not_subscribed",
        "symbol": symbol,
        "subscription_ids": matching,
    }


def _status() -> dict[str, Any]:
    with _STATE_LOCK:
        return {
            "status": "connected" if _API is not None else "ready",
            "active_symbols": sorted(_ACTIVE_SYMBOLS),
        }


def _shutdown() -> dict[str, Any]:
    global _API, _QUOTE_READY
    with _STATE_LOCK:
        api = _API
        _API = None
        _QUOTE_READY = False
        _ACTIVE_SYMBOLS.clear()
    if api is not None:
        try:
            quote = getattr(api, "Quote", None)
            if quote is not None:
                quote.unsubscribe_all()
        finally:
            _close_login(api)
    return {"status": "stopped"}


def _handle(message: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    action = str(message.get("action") or "").strip().lower()
    if action == "subscribe":
        return _subscribe(_normalize_symbol(message.get("symbol"))), False
    if action == "unsubscribe":
        return _unsubscribe(_normalize_symbol(message.get("symbol"))), False
    if action == "status":
        return _status(), False
    if action == "data_get":
        return _data_get(message), False
    if action == "portfolio_get":
        return _portfolio_get(message), False
    if action == "shutdown":
        return _shutdown(), True
    raise ValueError(f"Unsupported quote bridge action: {action or '<empty>'}")


def main() -> int:
    # Keep SDK login/account diagnostics out of the machine-readable protocol and
    # out of OMI logs. Protocol replies continue through the original stdout.
    devnull = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = devnull
    sys.stderr = devnull
    runtime_error = _runtime_compatibility_error()
    if runtime_error:
        _emit(
            {
                "type": "fatal",
                "protocol": PROTOCOL_VERSION,
                "error": runtime_error,
            }
        )
        return 2
    try:
        sdk_version = importlib.metadata.version("kgisuperpy")
    except importlib.metadata.PackageNotFoundError:
        _emit(
            {
                "type": "fatal",
                "protocol": PROTOCOL_VERSION,
                "error": "kgisuperpy is not installed in the configured interpreter.",
            }
        )
        return 2

    _emit(
        {
            "type": "ready",
            "protocol": PROTOCOL_VERSION,
            "sdk_version": sdk_version,
            "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        }
    )

    for line in sys.stdin:
        request_id: str | None = None
        stop = False
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Bridge command must be a JSON object.")
            request_id = str(message.get("id") or "") or None
            result, stop = _handle(message)
            _emit(
                {
                    "type": "response",
                    "protocol": PROTOCOL_VERSION,
                    "id": request_id,
                    "ok": True,
                    "result": result,
                }
            )
        except Exception as exc:
            _emit(
                {
                    "type": "response",
                    "protocol": PROTOCOL_VERSION,
                    "id": request_id,
                    "ok": False,
                    "error": _safe_error(exc),
                    "error_type": type(exc).__name__,
                }
            )
        if stop:
            return 0

    try:
        _shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
