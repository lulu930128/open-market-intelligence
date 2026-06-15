from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from app.http_client import get as http_get


NSTOCK_INSTITUTIONAL_URL = "https://www.nstock.tw/stock_info?status=8&stock_id={stock_id}"
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


class InstitutionalHoldingRatioFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstitutionalHoldingRatioPoint:
    trade_date: date
    foreign_investor_ratio: float | None
    investment_trust_ratio: float | None
    dealer_ratio: float | None


@dataclass(frozen=True)
class InstitutionalHoldingRatio:
    stock_id: str
    stock_name: str | None
    trade_date: date | None
    foreign_investor_ratio: float | None
    investment_trust_ratio: float | None
    dealer_ratio: float | None
    source_name: str
    source_url: str
    fetched_at: datetime
    history: list[InstitutionalHoldingRatioPoint]


def _parse_ratio(value: str | None) -> float | None:
    if not value:
        return None

    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", value.replace(",", ""))
    return float(match.group(1)) if match else None


def _next_ratio(lines: list[str], label: str, start: int, stop: int) -> float | None:
    for index in range(start, min(stop, len(lines))):
        if lines[index] != label:
            continue

        for candidate in lines[index + 1 : min(index + 5, len(lines))]:
            ratio = _parse_ratio(candidate)
            if ratio is not None:
                return ratio

    return None


def _parse_value_token(value: str):
    token = value.strip()

    if token in {"null", "undefined", "NaN"}:
        return None

    if token == "true":
        return True

    if token == "false":
        return False

    if token.startswith('"') and token.endswith('"'):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return bytes(token[1:-1], "utf-8").decode("unicode_escape")

    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", token):
        return float(token) if "." in token else int(token)

    return token


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    in_string = False
    escaped = False

    for index, character in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
            continue

        if character in "([{":
            depth += 1
            continue

        if character in ")]}":
            depth -= 1
            continue

        if character == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1

    tail = value[start:].strip()
    if tail:
        parts.append(tail)

    return parts


def _extract_nuxt_expression(html: str) -> str | None:
    match = re.search(r"<script>window\.__NUXT__=(.*?)</script>", html, re.DOTALL)
    return match.group(1) if match else None


def _split_nuxt_expression(expression: str) -> tuple[str, str, str] | None:
    match = re.match(
        r"^\(function\((?P<params>.*?)\)\{.*\}\((?P<args>.*)\)\);?$",
        expression,
        re.DOTALL,
    )
    if not match:
        return None

    body_start = expression.find("){")
    body_end = expression.rfind("}(")
    if body_start < 0 or body_end < 0 or body_end <= body_start:
        return None

    return (
        match.group("params"),
        expression[body_start + 2 : body_end],
        match.group("args"),
    )


def _nuxt_parameter_values(expression: str) -> dict[str, object]:
    parts = _split_nuxt_expression(expression)
    if not parts:
        return {}

    params_text, _, args_text = parts
    params = [item.strip() for item in params_text.split(",")]
    args = [_parse_value_token(item) for item in _split_top_level(args_text)]
    return dict(zip(params, args, strict=False))


def _extract_balanced_array(text: str, marker: str) -> str | None:
    marker_index = text.find(marker)
    if marker_index < 0:
        return None

    start = text.find("[", marker_index)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        character = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
            continue

        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def _parse_date_token(value: str) -> date | None:
    match = re.fullmatch(r"new Date\((\d+)\)", value.strip())
    if not match:
        return None

    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=TAIPEI_TIMEZONE).date()


def _resolve_float(value: str, parameter_values: dict[str, object]) -> float | None:
    resolved = _parse_value_token(value)

    if isinstance(resolved, str) and resolved in parameter_values:
        resolved = parameter_values[resolved]

    if resolved is None:
        return None

    if isinstance(resolved, bool):
        return None

    if isinstance(resolved, (int, float)):
        return float(resolved)

    if isinstance(resolved, str):
        return _parse_ratio(resolved) or _parse_plain_float(resolved)

    return None


def _parse_plain_float(value: str | None) -> float | None:
    if value is None:
        return None

    stripped = value.replace(",", "").strip()
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", stripped):
        return None

    return float(stripped)


def _parse_origin_ratio_history(html: str) -> list[InstitutionalHoldingRatioPoint]:
    expression = _extract_nuxt_expression(html)
    if not expression:
        return []

    origin_array = _extract_balanced_array(expression, "originThreeInstitutionData:")
    if not origin_array:
        return []

    parameter_values = _nuxt_parameter_values(expression)
    rows: list[InstitutionalHoldingRatioPoint] = []

    for row_text in _split_top_level(origin_array[1:-1]):
        row_text = row_text.strip()
        if not row_text.startswith("[") or not row_text.endswith("]"):
            continue

        values = _split_top_level(row_text[1:-1])
        if len(values) < 7:
            continue

        trade_date = _parse_date_token(values[0])
        if trade_date is None:
            continue

        rows.append(
            InstitutionalHoldingRatioPoint(
                trade_date=trade_date,
                foreign_investor_ratio=_resolve_float(values[2], parameter_values),
                investment_trust_ratio=_resolve_float(values[4], parameter_values),
                dealer_ratio=_resolve_float(values[6], parameter_values),
            )
        )

    return sorted(rows, key=lambda row: row.trade_date)


def _row_from_tokens(
    values: list[str],
    parameter_values: dict[str, object],
) -> InstitutionalHoldingRatioPoint | None:
    if len(values) < 7:
        return None

    trade_date = _parse_date_token(values[0])
    if trade_date is None:
        return None

    return InstitutionalHoldingRatioPoint(
        trade_date=trade_date,
        foreign_investor_ratio=_resolve_float(values[2], parameter_values),
        investment_trust_ratio=_resolve_float(values[4], parameter_values),
        dealer_ratio=_resolve_float(values[6], parameter_values),
    )


def _parse_recent_ratio_history(html: str) -> list[InstitutionalHoldingRatioPoint]:
    expression = _extract_nuxt_expression(html)
    if not expression:
        return []

    parts = _split_nuxt_expression(expression)
    if not parts:
        return []

    _, body, _ = parts
    parameter_values = _nuxt_parameter_values(expression)
    data_array = _extract_balanced_array(expression, "threeInstitutionData:")
    if not data_array:
        return []

    assignments: dict[str, dict[int, str]] = {}
    for match in re.finditer(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\[(\d+)\]=([^;]+);", body):
        row_name = match.group(1)
        assignments.setdefault(row_name, {})[int(match.group(2))] = match.group(3).strip()

    rows: list[InstitutionalHoldingRatioPoint] = []
    for token in _split_top_level(data_array[1:-1]):
        row_name = token.strip()
        row_assignments = assignments.get(row_name)
        if not row_assignments:
            continue

        values = [row_assignments.get(index, "null") for index in range(max(row_assignments) + 1)]
        row = _row_from_tokens(values, parameter_values)
        if row is not None:
            rows.append(row)

    return sorted(rows, key=lambda row: row.trade_date)


def _parse_compact_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None

    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", value)
    if not match:
        return None

    return date(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )


def _parse_show_detail_ratio_history(html: str) -> list[InstitutionalHoldingRatioPoint]:
    expression = _extract_nuxt_expression(html)
    if not expression:
        return []

    data_array = _extract_balanced_array(expression, "threeInstitutionShowDetail:")
    if not data_array:
        return []

    parameter_values = _nuxt_parameter_values(expression)
    rows: list[InstitutionalHoldingRatioPoint] = []

    for object_text in _split_top_level(data_array[1:-1]):
        object_text = object_text.strip()
        if not object_text.startswith("{") or not object_text.endswith("}"):
            continue

        fields: dict[str, str] = {}
        for pair in _split_top_level(object_text[1:-1]):
            key, separator, value = pair.partition(":")
            if not separator:
                continue

            parsed_key = _parse_value_token(key.strip())
            if isinstance(parsed_key, str):
                fields[parsed_key] = value.strip()

        trade_date = _parse_compact_date(_parse_value_token(fields.get("日期", "")))
        if trade_date is None:
            continue

        rows.append(
            InstitutionalHoldingRatioPoint(
                trade_date=trade_date,
                foreign_investor_ratio=_resolve_float(
                    fields.get("外資持股比率(%)", "null"),
                    parameter_values,
                ),
                investment_trust_ratio=_resolve_float(
                    fields.get("投信持股比率(%)", "null"),
                    parameter_values,
                ),
                dealer_ratio=_resolve_float(
                    fields.get("自營商持股比率(%)", "null"),
                    parameter_values,
                ),
            )
        )

    return sorted(rows, key=lambda row: row.trade_date)


def _merge_ratio_history(
    *histories: list[InstitutionalHoldingRatioPoint],
) -> list[InstitutionalHoldingRatioPoint]:
    rows_by_date: dict[date, InstitutionalHoldingRatioPoint] = {}

    for history in histories:
        for row in history:
            rows_by_date[row.trade_date] = row

    return [rows_by_date[key] for key in sorted(rows_by_date)]


def _parse_trade_date(lines: list[str]) -> date | None:
    for index, line in enumerate(lines):
        if line != "更新時間：":
            continue

        for candidate in lines[index + 1 : min(index + 4, len(lines))]:
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", candidate)
            if match:
                return date(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )

    return None


def _parse_stock_name(lines: list[str], stock_id: str, title: str | None = None) -> str | None:
    if title:
        title_match = re.search(rf"(.+?)\({re.escape(stock_id)}\)", title)
        if title_match:
            return title_match.group(1).strip() or None

    for line in lines:
        if stock_id not in line:
            continue

        name = line.replace(stock_id, "").strip()
        return name or None

    return None


def parse_nstock_institutional_holding_ratios(
    html: str,
    *,
    stock_id: str,
    source_url: str,
) -> InstitutionalHoldingRatio:
    soup = BeautifulSoup(html, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    try:
        marker_index = lines.index("三大法人持股比例")
    except ValueError as exc:
        raise InstitutionalHoldingRatioFetchError("Institutional holding ratio block was not found.") from exc

    search_stop = marker_index + 20
    foreign_ratio = _next_ratio(lines, "外資", marker_index + 1, search_stop)
    investment_trust_ratio = _next_ratio(lines, "投信", marker_index + 1, search_stop)
    dealer_ratio = _next_ratio(lines, "自營商", marker_index + 1, search_stop)

    if foreign_ratio is None and investment_trust_ratio is None and dealer_ratio is None:
        raise InstitutionalHoldingRatioFetchError("Institutional holding ratios were not found.")

    history = _merge_ratio_history(
        _parse_origin_ratio_history(html),
        _parse_recent_ratio_history(html),
        _parse_show_detail_ratio_history(html),
    )
    if history:
        latest = history[-1]
        trade_date = latest.trade_date
        foreign_ratio = latest.foreign_investor_ratio
        investment_trust_ratio = latest.investment_trust_ratio
        dealer_ratio = latest.dealer_ratio
    else:
        trade_date = _parse_trade_date(lines)
        if trade_date is not None:
            history = [
                InstitutionalHoldingRatioPoint(
                    trade_date=trade_date,
                    foreign_investor_ratio=foreign_ratio,
                    investment_trust_ratio=investment_trust_ratio,
                    dealer_ratio=dealer_ratio,
                )
            ]

    return InstitutionalHoldingRatio(
        stock_id=stock_id,
        stock_name=_parse_stock_name(lines, stock_id, title),
        trade_date=trade_date,
        foreign_investor_ratio=foreign_ratio,
        investment_trust_ratio=investment_trust_ratio,
        dealer_ratio=dealer_ratio,
        source_name="nStock",
        source_url=source_url,
        fetched_at=datetime.now(timezone.utc),
        history=history,
    )


def fetch_institutional_holding_ratios(stock_id: str) -> InstitutionalHoldingRatio:
    source_url = NSTOCK_INSTITUTIONAL_URL.format(stock_id=stock_id)

    try:
        response = http_get(
            source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InstitutionalHoldingRatioFetchError(
            f"Failed to fetch institutional holding ratios for stock_id='{stock_id}'."
        ) from exc

    response.encoding = "utf-8"
    return parse_nstock_institutional_holding_ratios(
        response.text,
        stock_id=stock_id,
        source_url=source_url,
    )
