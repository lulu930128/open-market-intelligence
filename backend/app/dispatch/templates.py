from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from app.ai import reports, tools
from app.db.models import utc_now
from app.market.taiwan_industries import normalize_tw_industry_label
from app.us_market import service as us_market_service

MAIL_BG = "#f4f6f8"
MAIL_PANEL = "#ffffff"
MAIL_BORDER = "#d8dee8"
MAIL_TEXT = "#15202b"
MAIL_MUTED = "#627084"
MAIL_ACCENT = "#d6333f"
MAIL_UP = "#c62828"
MAIL_DOWN = "#16834a"
MAIL_WARNING = "#8a5a00"
MAIL_INFO = "#416b96"
MAIL_RISK = "#b42318"
WATCHLIST_DETAIL_HEADERS = ["標的", "漲跌幅", "收盤", "量", "分數", "日期", "雷達", "觀察"]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:
        return None
    return float(value)


def _pct(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def _money(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.1f} 億"
    return f"{number:,.0f}"


def _price(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.2f}"


def _compact_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if abs_number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if abs_number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,.0f}"


def _ratio_pct(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _ratio(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.2f}"


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _display(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _industry_label(value: Any, fallback: str = "-") -> str:
    return normalize_tw_industry_label(value, fallback=fallback)


def _stock_label(row: dict[str, Any]) -> str:
    stock_id = _display(row.get("stock_id") or row.get("symbol"), "")
    name = _display(row.get("stock_name") or row.get("name") or row.get("security_name"), "")
    return " ".join(part for part in (stock_id, name) if part) or "-"


def _line_items(rows: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    items: list[str] = []
    for row in rows[:limit]:
        details = [_pct(row.get("change_pct"))]
        close = row.get("close_price") if row.get("close_price") is not None else row.get("close")
        if close is not None:
            details.append(f"收盤 {_price(close)}")
        if row.get("trade_value") is not None:
            details.append(f"成交值 {_money(row.get('trade_value'))}")
        industry = _industry_label(row.get("industry"), fallback="")
        if industry:
            details.append(f"產業 {industry}")
        items.append(f"- {_stock_label(row)}: {'，'.join(details)}")
    return items


def _style(style: dict[str, str]) -> str:
    return "; ".join(f"{key}: {value}" for key, value in style.items())


def _tone_color(tone: str) -> str:
    if tone == "up":
        return MAIL_UP
    if tone == "down":
        return MAIL_DOWN
    if tone == "warning":
        return MAIL_WARNING
    if tone == "info":
        return MAIL_INFO
    if tone == "risk":
        return MAIL_RISK
    return MAIL_MUTED


def _metric_card(label: str, value: str, *, tone: str = "neutral") -> str:
    return (
        '<td style="padding: 7px; width: 25%;">'
        f'<div style="{_style({"border": f"1px solid {MAIL_BORDER}", "background": "#fafbfc", "padding": "12px"})}">'
        f'<div style="{_style({"font-size": "12px", "color": MAIL_MUTED, "font-weight": "700"})}">{escape(label)}</div>'
        f'<div style="{_style({"font-size": "20px", "line-height": "1.25", "font-weight": "800", "color": _tone_color(tone), "margin-top": "4px"})}">{escape(value)}</div>'
        "</div>"
        "</td>"
    )


def _metrics_table(metrics: list[tuple[str, str, str]]) -> str:
    if not metrics:
        return ""
    cells = [_metric_card(label, value, tone=tone) for label, value, tone in metrics]
    rows = []
    for index in range(0, len(cells), 4):
        rows.append(f"<tr>{''.join(cells[index:index + 4])}</tr>")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="{_style({"border-collapse": "collapse", "margin": "10px 0 18px"})}">'
        f"{''.join(rows)}</table>"
    )


def _cell(value: Any, *, tone: str = "neutral", strong: bool = False) -> str:
    return (
        f'<td style="{_style({"border-top": f"1px solid {MAIL_BORDER}", "padding": "8px 10px", "font-size": "13px", "line-height": "1.45", "vertical-align": "top", "color": _tone_color(tone) if tone != "neutral" else MAIL_TEXT, "font-weight": "700" if strong else "400", "font-variant-numeric": "tabular-nums", "word-break": "break-word"})}">'
        f"{escape(_display(value))}"
        "</td>"
    )


def _table(headers: list[str], rows: list[list[dict[str, Any] | str]], *, empty: str) -> str:
    header_html = "".join(
        f'<th align="left" style="{_style({"background": "#eaf0f6", "border-top": f"1px solid {MAIL_BORDER}", "border-bottom": f"1px solid {MAIL_BORDER}", "padding": "8px 10px", "font-size": "12px", "line-height": "1.35", "font-weight": "800", "color": "#46566c"})}">{escape(header)}</th>'
        for header in headers
    )
    if not rows:
        body_html = (
            "<tr>"
            f'<td colspan="{len(headers)}" style="{_style({"border-top": f"1px solid {MAIL_BORDER}", "padding": "12px 10px", "font-size": "13px", "color": MAIL_MUTED})}">'
            f"{escape(empty)}</td></tr>"
        )
    else:
        rendered_rows = []
        for row in rows:
            cells = []
            for raw_cell in row:
                if isinstance(raw_cell, dict):
                    cells.append(
                        _cell(
                            raw_cell.get("value"),
                            tone=str(raw_cell.get("tone") or "neutral"),
                            strong=bool(raw_cell.get("strong")),
                        )
                    )
                else:
                    cells.append(_cell(raw_cell))
            rendered_rows.append(f"<tr>{''.join(cells)}</tr>")
        body_html = "".join(rendered_rows)

    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="{_style({"border-collapse": "collapse", "margin-top": "8px", "table-layout": "auto"})}">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def _section(title: str, body: str = "") -> str:
    return (
        f'<div style="{_style({"margin-top": "22px"})}">'
        f'<h2 style="{_style({"font-size": "16px", "line-height": "1.35", "margin": "0 0 8px", "color": MAIL_TEXT})}">{escape(title)}</h2>'
        f"{body}"
        "</div>"
    )


def _section_grid(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    rows = []
    for index in range(0, len(items), 2):
        row_items = items[index : index + 2]
        cells = []
        for title, body in row_items:
            padding = "0 8px 0 0" if len(cells) == 0 else "0 0 0 8px"
            cells.append(
                f'<td width="50%" valign="top" style="padding: {padding};">'
                f'<div style="{_style({"margin-top": "22px", "border": f"1px solid {MAIL_BORDER}", "background": "#ffffff", "padding": "14px 14px 16px"})}">'
                f'<h2 style="{_style({"font-size": "16px", "line-height": "1.35", "margin": "0 0 8px", "color": MAIL_TEXT})}">{escape(title)}</h2>'
                f"{body}"
                "</div>"
                "</td>"
            )
        if len(cells) == 1:
            cells.append('<td width="50%" style="padding: 0 0 0 8px;">&nbsp;</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="{_style({"border-collapse": "collapse"})}">'
        f"{''.join(rows)}</table>"
    )


def _paragraphs(lines: list[str]) -> str:
    return "".join(
        f'<p style="{_style({"font-size": "14px", "line-height": "1.65", "margin": "0 0 6px", "color": MAIL_TEXT})}">{escape(line)}</p>'
        for line in lines
        if line.strip()
    )


def _list_html(items: list[str], *, empty: str) -> str:
    values = [item for item in items if item.strip()] or [empty]
    return (
        f'<ul style="{_style({"margin": "8px 0 0 18px", "padding": "0", "color": MAIL_TEXT})}">'
        + "".join(
            f'<li style="{_style({"font-size": "13px", "line-height": "1.6", "margin": "0 0 4px"})}">{escape(item)}</li>'
            for item in values
        )
        + "</ul>"
    )


def _safe_ratio(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return max(0.0, min(number, 1.0))


def _bar_table(rows: list[tuple[str, str, float | None, str]]) -> str:
    if not rows:
        return ""

    rendered_rows = []
    for label, value_label, ratio, tone in rows:
        width = int(round(max(0.0, min(float(ratio or 0), 1.0)) * 100))
        color = _tone_color(tone)
        rendered_rows.append(
            "<tr>"
            f'<td width="28%" style="{_style({"padding": "8px 10px 8px 0", "font-size": "13px", "font-weight": "700", "color": MAIL_TEXT, "vertical-align": "middle"})}">{escape(label)}</td>'
            f'<td width="56%" style="{_style({"padding": "8px 8px", "vertical-align": "middle"})}">'
            f'<div style="{_style({"height": "10px", "background": "#eef2f6", "border": f"1px solid {MAIL_BORDER}"})}">'
            f'<div style="{_style({"height": "10px", "width": f"{width}%", "background": color})}"></div>'
            "</div>"
            "</td>"
            f'<td width="16%" align="right" style="{_style({"padding": "8px 0 8px 8px", "font-size": "13px", "font-weight": "800", "color": color, "vertical-align": "middle"})}">{escape(value_label)}</td>'
            "</tr>"
        )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="{_style({"border-collapse": "collapse", "margin-top": "8px"})}">'
        f"{''.join(rendered_rows)}</table>"
    )


def _signed_bar_table(rows: list[tuple[str, float | None, str]]) -> str:
    finite_values = [abs(value) for _label, value, _detail in rows if value is not None]
    if not finite_values:
        return ""
    max_abs = max(max(finite_values), 0.01)
    rendered_rows = []
    for label, value, detail in rows:
        value_number = float(value or 0)
        width = int(round(min(abs(value_number) / max_abs, 1.0) * 100))
        tone = "up" if value_number > 0 else "down" if value_number < 0 else "neutral"
        color = _tone_color(tone)
        rendered_rows.append(
            "<tr>"
            f'<td width="26%" style="{_style({"padding": "8px 10px 8px 0", "font-size": "13px", "font-weight": "800", "color": MAIL_TEXT, "vertical-align": "middle"})}">{escape(label)}</td>'
            f'<td width="52%" style="{_style({"padding": "8px 8px", "vertical-align": "middle"})}">'
            f'<div style="{_style({"height": "10px", "background": "#eef2f6", "border": f"1px solid {MAIL_BORDER}"})}">'
            f'<div style="{_style({"height": "10px", "width": f"{width}%", "background": color})}"></div>'
            "</div>"
            "</td>"
            f'<td width="22%" align="right" style="{_style({"padding": "8px 0 8px 8px", "font-size": "13px", "font-weight": "800", "color": color, "vertical-align": "middle", "font-variant-numeric": "tabular-nums"})}">{escape(detail)}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="{_style({"border-collapse": "collapse", "margin-top": "8px"})}">'
        f"{''.join(rendered_rows)}</table>"
    )


def _first_nonempty_label(rows: list[dict[str, Any]], *, key: str, fallback: str = "-") -> str:
    for row in rows:
        value = _display(row.get(key), "")
        if value:
            return value
    return fallback


def _first_industry_label(rows: list[dict[str, Any]], *, fallback: str = "-") -> str:
    for row in rows:
        value = _industry_label(row.get("industry"), fallback="")
        if value:
            return value
    return fallback


def _industry_chart_rows(
    top_industries: list[dict[str, Any]],
    weak_industries: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[tuple[str, float | None, str]]:
    chart_rows: list[tuple[str, float | None, str]] = []
    for row in top_industries[: max(limit // 2, 1)]:
        change = _number(row.get("average_change_pct"))
        chart_rows.append(
            (
                f"強 {_industry_label(row.get('industry'))}",
                change,
                f"{_pct(change)} / {row.get('advance_count', 0)}:{row.get('decline_count', 0)}",
            )
        )
    for row in weak_industries[: max(limit // 2, 1)]:
        change = _number(row.get("average_change_pct"))
        chart_rows.append(
            (
                f"弱 {_industry_label(row.get('industry'))}",
                change,
                f"{_pct(change)} / {row.get('advance_count', 0)}:{row.get('decline_count', 0)}",
            )
        )
    return chart_rows


def _report_html(
    *,
    title: str,
    subtitle: str,
    lead: str,
    metrics: list[tuple[str, str, str]],
    sections: list[str],
    generated_at: datetime,
) -> str:
    generated = generated_at.strftime("%Y-%m-%d %H:%M")
    return "\n".join(
        [
            "<!doctype html>",
            "<html>",
            '<body style="margin:0; padding:0; background:#eef2f6; font-family: Arial, Microsoft JhengHei, sans-serif;">',
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#eef2f6;">',
            '<tr><td align="center" style="padding:28px 16px;">',
            f'<table role="presentation" width="1360" cellpadding="0" cellspacing="0" style="{_style({"width": "1360px", "max-width": "100%", "border-collapse": "collapse", "background": MAIL_PANEL, "border": f"1px solid {MAIL_BORDER}"})}">',
            f'<tr><td style="{_style({"padding": "24px 36px", "background": "#fbfcfe", "border-bottom": f"3px solid {MAIL_ACCENT}"})}">',
            f'<div style="{_style({"font-size": "11px", "letter-spacing": "0.18em", "font-weight": "800", "color": MAIL_ACCENT})}">OPEN MARKET INTELLIGENCE</div>',
            f'<h1 style="{_style({"font-size": "24px", "line-height": "1.25", "margin": "8px 0 4px", "color": MAIL_TEXT})}">{escape(title)}</h1>',
            f'<div style="{_style({"font-size": "13px", "color": MAIL_MUTED, "line-height": "1.5"})}">{escape(subtitle)}</div>',
            "</td></tr>",
            f'<tr><td style="{_style({"padding": "24px 36px 34px"})}">',
            f'<p style="{_style({"font-size": "15px", "line-height": "1.7", "margin": "0 0 10px", "font-weight": "700", "color": MAIL_TEXT})}">{escape(lead)}</p>',
            _metrics_table(metrics),
            *sections,
            f'<div style="{_style({"margin-top": "22px", "padding-top": "14px", "border-top": f"1px solid {MAIL_BORDER}", "font-size": "12px", "line-height": "1.6", "color": MAIL_MUTED})}">Generated by OMI at {escape(generated)}. This email is a research briefing, not trading automation.</div>',
            "</td></tr>",
            "</table>",
            "</td></tr>",
            "</table>",
            "</body>",
            "</html>",
        ]
    )


def _html_from_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            lines.append("<br>")
        elif line.startswith("# "):
            lines.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            lines.append(f"<p>{escape(line)}</p>")
        else:
            lines.append(f"<p>{escape(line)}</p>")
    return "\n".join(
        [
            "<!doctype html>",
            '<html><body style="font-family: Arial, sans-serif; line-height: 1.55;">',
            *lines,
            "</body></html>",
        ]
    )


def _preview_payload(
    *,
    template_key: str,
    scope_type: str,
    scope_id: str | None,
    subject: str,
    body_text: str,
    generated_at: datetime,
    as_of: str | None,
    warnings: list[str],
    missing: list[str],
    metadata: dict[str, Any],
    body_html: str | None = None,
) -> dict[str, Any]:
    return {
        "template_key": template_key,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html or _html_from_text(body_text),
        "generated_at": generated_at,
        "as_of": as_of,
        "warnings": warnings,
        "missing": missing,
        "metadata": metadata,
    }


def _market_stance(breadth: dict[str, Any]) -> str:
    advance = _integer(breadth.get("advance_count")) or 0
    decline = _integer(breadth.get("decline_count")) or 0
    total = _integer(breadth.get("total_count")) or 0
    if total <= 0:
        return "資料不足"
    if advance >= max(decline * 1.25, decline + 20):
        return "偏多"
    if decline >= max(advance * 1.25, advance + 20):
        return "轉弱"
    return "震盪"


def _market_rows(rows: list[dict[str, Any]], *, limit: int = 6) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        table_rows.append(
            [
                {"value": _stock_label(row), "strong": True},
                {"value": _pct(row.get("change_pct")), "tone": tone, "strong": True},
                _display(row.get("close_price")),
                _money(row.get("trade_value")),
            ]
        )
    return table_rows


def _value_rows(rows: list[dict[str, Any]], *, limit: int = 8) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        table_rows.append(
            [
                {"value": _stock_label(row), "strong": True},
                {"value": _pct(row.get("change_pct")), "tone": tone, "strong": True},
                _display(row.get("close_price")),
                _money(row.get("trade_value")),
                _industry_label(row.get("industry")),
            ]
        )
    return table_rows


def _industry_rows(rows: list[dict[str, Any]], *, limit: int = 6) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("average_change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        top_label = " ".join(
            part
            for part in (
                _display(row.get("top_stock_id"), ""),
                _display(row.get("top_stock_name"), ""),
            )
            if part
        ) or "-"
        table_rows.append(
            [
                {"value": _industry_label(row.get("industry")), "strong": True},
                {"value": _pct(row.get("average_change_pct")), "tone": tone, "strong": True},
                f"{row.get('advance_count', 0)} / {row.get('decline_count', 0)}",
                _money(row.get("trade_value")),
                top_label,
            ]
        )
    return table_rows


def _structure_rows(breadth: dict[str, Any], distribution: dict[str, Any]) -> list[list[dict[str, Any] | str]]:
    return [
        [
            {"value": "上漲占比", "strong": True},
            _ratio_pct(breadth.get("positive_ratio")),
            "上漲家數 / 有漲跌幅資料家數",
        ],
        [
            {"value": "上跌比", "strong": True},
            _ratio(breadth.get("advance_decline_ratio")),
            "大於 1 代表上漲家數多於下跌家數",
        ],
        [
            {"value": "平均漲跌", "strong": True},
            {
                "value": _pct(breadth.get("average_change_pct")),
                "tone": "up" if (_number(breadth.get("average_change_pct")) or 0) > 0 else "down" if (_number(breadth.get("average_change_pct")) or 0) < 0 else "neutral",
                "strong": True,
            },
            "全市場簡單平均，未依市值加權",
        ],
        [
            {"value": "漲停 / 跌停", "strong": True},
            f"{distribution.get('limit_up_count', 0)} / {distribution.get('limit_down_count', 0)}",
            "以日漲跌幅約 9.5% 判斷",
        ],
        [
            {"value": "大漲 / 大跌", "strong": True},
            f"{distribution.get('strong_up_count', 0)} / {distribution.get('strong_down_count', 0)}",
            "日漲跌幅 5% 到 9.5%",
        ],
        [
            {"value": "成交集中", "strong": True},
            _ratio_pct(breadth.get("top_value_share")),
            "成交值前段占全市場成交值",
        ],
    ]


def _market_focus_lines(
    *,
    stance: str,
    breadth: dict[str, Any],
    distribution: dict[str, Any],
    top_industries: list[dict[str, Any]],
    weak_industries: list[dict[str, Any]],
    value_leaders: list[dict[str, Any]],
) -> list[str]:
    positive_ratio = _number(breadth.get("positive_ratio"))
    average_change = _number(breadth.get("average_change_pct"))
    top_share = _number(breadth.get("top_value_share"))
    top_industry = _first_industry_label(top_industries, fallback="暫無明確強勢產業")
    weak_industry = _first_industry_label(weak_industries, fallback="暫無明確弱勢產業")
    value_focus = _stock_label(value_leaders[0]) if value_leaders else "暫無明確成交值焦點"
    lines = [
        f"市場狀態：{stance}；上漲占比 {_ratio_pct(positive_ratio)}，平均漲跌 {_pct(average_change)}。",
        f"產業輪動：強勢端以 {top_industry} 為代表，弱勢端以 {weak_industry} 為代表。",
        f"成交焦點：成交值前段目前以 {value_focus} 為主要觀察標的。",
    ]
    if top_share is not None:
        lines.append(f"成交集中度：前段成交占比 {_ratio_pct(top_share)}，需要確認是主流集中還是少數權值支撐。")
    if (distribution.get("limit_up_count") or distribution.get("limit_down_count")):
        lines.append(
            f"漲跌停結構：漲停 {distribution.get('limit_up_count', 0)}、跌停 {distribution.get('limit_down_count', 0)}，觀察隔日延續與流動性風險。"
        )
    return lines


def _market_visual_rows(
    breadth: dict[str, Any],
    distribution: dict[str, Any],
) -> list[tuple[str, str, float | None, str]]:
    positive_ratio = _safe_ratio(breadth.get("positive_ratio"))
    top_share = _safe_ratio(breadth.get("top_value_share"))
    strong_up = _integer(distribution.get("strong_up_count")) or 0
    strong_down = _integer(distribution.get("strong_down_count")) or 0
    limit_up = _integer(distribution.get("limit_up_count")) or 0
    limit_down = _integer(distribution.get("limit_down_count")) or 0
    strong_total = strong_up + strong_down
    limit_total = limit_up + limit_down
    strong_ratio = strong_up / strong_total if strong_total else None
    limit_ratio = limit_up / limit_total if limit_total else None
    return [
        (
            "上漲占比",
            _ratio_pct(positive_ratio),
            positive_ratio,
            "up" if (positive_ratio or 0) >= 0.5 else "down",
        ),
        (
            "大漲平衡",
            f"{strong_up} / {strong_down}",
            strong_ratio,
            "up" if strong_ratio is not None and strong_ratio >= 0.5 else "down" if strong_ratio is not None else "neutral",
        ),
        (
            "漲停平衡",
            f"{limit_up} / {limit_down}",
            limit_ratio,
            "up" if limit_ratio is not None and limit_ratio >= 0.5 else "down" if limit_ratio is not None else "neutral",
        ),
        (
            "成交集中",
            _ratio_pct(top_share),
            top_share,
            "warning" if (top_share or 0) >= 0.5 else "neutral",
        ),
    ]


def _market_research_checklist(stance: str, breadth: dict[str, Any]) -> list[str]:
    positive_ratio = _number(breadth.get("positive_ratio")) or 0
    checklist = [
        "先確認大盤廣度是否支撐個股雷達訊號，避免只看單檔強弱。",
        "追價前檢查成交集中度；若只有少數權值支撐，續航力要打折。",
        "把強勢產業與弱勢產業分開看，避免在輪動退潮處追高。",
    ]
    if stance in {"轉弱", "資料不足"} or positive_ratio < 0.45:
        checklist.append("若廣度偏弱，雷達中的突破項目只當觀察，不直接視為進場訊號。")
    else:
        checklist.append("若廣度維持偏多，再看雷達項目的回測區與失效條件。")
    return checklist


def _build_tw_market_overview_preview(
    db: Session,
    *,
    include_radar: bool = False,
    radar_group_id: int | None = None,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = "score",
    sort_order: str = "desc",
    radar_mode: str = "action",
    content_depth: str = "standard",
    radar_limit: int | None = None,
) -> dict[str, Any]:
    envelope = tools.read_market_overview(db=db, limit=8)
    generated_at = utc_now()
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    breadth = data.get("breadth") if isinstance(data.get("breadth"), dict) else {}
    distribution = data.get("distribution") if isinstance(data.get("distribution"), dict) else {}
    as_of = str(envelope.get("as_of") or data.get("latest_trade_date") or "-")
    top_gainers = [row for row in data.get("top_gainers") or [] if isinstance(row, dict)]
    top_losers = [row for row in data.get("top_losers") or [] if isinstance(row, dict)]
    value_leaders = [row for row in data.get("value_leaders") or [] if isinstance(row, dict)]
    top_industries = [row for row in data.get("top_industries") or [] if isinstance(row, dict)]
    weak_industries = [row for row in data.get("weak_industries") or [] if isinstance(row, dict)]
    stance = _market_stance(breadth)
    subject = f"[OMI 派報] 台股大盤總覽 {as_of}"
    lead = (
        f"台股大盤目前判定為{stance}。"
        f"上漲 {breadth.get('advance_count', 0)}、下跌 {breadth.get('decline_count', 0)}、"
        f"平盤 {breadth.get('unchanged_count', 0)}，覆蓋 {breadth.get('total_count', 0)} 檔。"
    )
    focus_lines = _market_focus_lines(
        stance=stance,
        breadth=breadth,
        distribution=distribution,
        top_industries=top_industries,
        weak_industries=weak_industries,
        value_leaders=value_leaders,
    )
    visual_rows = _market_visual_rows(breadth, distribution)
    industry_visual_rows = _industry_chart_rows(top_industries, weak_industries)
    checklist_lines = _market_research_checklist(stance, breadth)
    body_lines = [
        f"# 台股大盤總覽 {as_of}",
        "",
        f"結論：{lead}",
        "",
        "## 今日看點",
        *[f"- {line}" for line in focus_lines],
        "",
        "## 圖表摘要 / 視覺摘要",
        *[
            f"- {label}：{value_label}"
            for label, value_label, _ratio_value, _tone in visual_rows
        ],
        *(
            [
                f"- {label}：{detail}"
                for label, _value, detail in industry_visual_rows
            ]
            if industry_visual_rows
            else []
        ),
        "",
        "## 研究檢查清單",
        *[f"- {line}" for line in checklist_lines],
        "",
        "## 市場廣度",
        f"- 上漲 / 下跌 / 平盤：{breadth.get('advance_count', 0)} / {breadth.get('decline_count', 0)} / {breadth.get('unchanged_count', 0)}",
        f"- 覆蓋檔數：{breadth.get('total_count', 0)}",
        f"- 成交值：{_money(breadth.get('trade_value'))}",
        f"- 上漲占比：{_ratio_pct(breadth.get('positive_ratio'))}",
        f"- 平均漲跌：{_pct(breadth.get('average_change_pct'))}",
        f"- 漲停 / 跌停：{distribution.get('limit_up_count', 0)} / {distribution.get('limit_down_count', 0)}",
        f"- 大漲 / 大跌：{distribution.get('strong_up_count', 0)} / {distribution.get('strong_down_count', 0)}",
        "",
        "## 強勢股",
        *(_line_items(top_gainers) or ["- 暫無可用資料"]),
        "",
        "## 弱勢股",
        *(_line_items(top_losers) or ["- 暫無可用資料"]),
        "",
        "## 成交值焦點",
        *(_line_items(value_leaders, limit=8) or ["- 暫無可用資料"]),
        "",
        "## 強勢產業",
        *(
            [
                f"- {_industry_label(row.get('industry'))}: {_pct(row.get('average_change_pct'))}，上漲/下跌 {row.get('advance_count', 0)}/{row.get('decline_count', 0)}"
                for row in top_industries[:6]
            ]
            or ["- 暫無可用資料"]
        ),
        "",
        "## 弱勢產業",
        *(
            [
                f"- {_industry_label(row.get('industry'))}: {_pct(row.get('average_change_pct'))}，上漲/下跌 {row.get('advance_count', 0)}/{row.get('decline_count', 0)}"
                for row in weak_industries[:6]
            ]
            or ["- 暫無可用資料"]
        ),
    ]
    missing = [str(item) for item in envelope.get("missing") or []]
    warnings = [str(item) for item in envelope.get("warnings") or []]
    radar_block: dict[str, Any] | None = None
    if include_radar and radar_group_id is not None:
        radar_block = _build_watchlist_radar_dispatch_block(
            db,
            group_id=radar_group_id,
            strategy_profile=strategy_profile,
            rank_by=rank_by,
            sort_order=sort_order,
            radar_mode=radar_mode,
            content_depth=content_depth,
            radar_limit=radar_limit,
            title_prefix="總覽雷達",
        )
        body_lines.extend(radar_block["text_lines"])
        warnings.extend(f"radar: {warning}" for warning in radar_block["warnings"])
        missing.extend(f"radar:{item}" for item in radar_block["missing"])

    body_lines.extend(["", "## 資料限制"])
    if missing:
        body_lines.extend(f"- {warning}" for warning in warnings)
        body_lines.extend(f"- missing: {item}" for item in missing)
    elif not warnings:
        body_lines.append("- 未回報重大資料缺口。")
    else:
        body_lines.extend(f"- {warning}" for warning in warnings)

    sections = [
        _section("今日看點", _list_html(focus_lines, empty="暫無市場看點。")),
        _section("圖表摘要 / 視覺摘要", _bar_table(visual_rows)),
        _section("產業強弱圖", _signed_bar_table(industry_visual_rows) or _list_html([], empty="暫無足夠產業資料可繪製。")),
        _section("研究檢查清單", _list_html(checklist_lines, empty="暫無研究檢查項。")),
        _section(
            "市場結構",
            _table(
                ["項目", "數值", "說明"],
                _structure_rows(breadth, distribution),
                empty="暫無可用資料",
            ),
        ),
        _section(
            "成交值焦點",
            _table(
                ["標的", "漲跌幅", "收盤", "成交值", "產業"],
                _value_rows(value_leaders),
                empty="暫無可用資料",
            ),
        ),
        _section_grid(
            [
                (
                    "強勢產業",
                    _table(
                        ["產業", "平均漲跌", "上漲/下跌", "成交值", "代表標的"],
                        _industry_rows(top_industries),
                        empty="本地資料尚無足夠產業分類",
                    ),
                ),
                (
                    "弱勢產業",
                    _table(
                        ["產業", "平均漲跌", "上漲/下跌", "成交值", "代表標的"],
                        _industry_rows(weak_industries),
                        empty="本地資料尚無足夠產業分類",
                    ),
                ),
            ]
        ),
        _section_grid(
            [
                (
                    "強勢股",
                    _table(
                        ["標的", "漲跌幅", "收盤", "成交值"],
                        _market_rows(top_gainers),
                        empty="暫無可用資料",
                    ),
                ),
                (
                    "弱勢股",
                    _table(
                        ["標的", "漲跌幅", "收盤", "成交值"],
                        _market_rows(top_losers),
                        empty="暫無可用資料",
                    ),
                ),
            ]
        ),
    ]
    if radar_block is not None:
        sections.extend(radar_block["html_sections"])
    sections.append(
        _section(
            "資料限制",
            _list_html([*warnings, *[f"missing: {item}" for item in missing]], empty="未回報重大資料缺口。"),
        )
    )

    body_html = _report_html(
        title=f"台股大盤總覽 {as_of}",
        subtitle=(
            "全市場日線廣度、強弱股摘要與自選股雷達"
            if radar_block is not None
            else "全市場日線廣度與強弱股摘要"
        ),
        lead=lead,
        metrics=[
            ("狀態", stance, "warning" if stance in {"資料不足", "震盪"} else "up" if stance == "偏多" else "down"),
            ("上漲", str(breadth.get("advance_count", 0)), "up"),
            ("下跌", str(breadth.get("decline_count", 0)), "down"),
            ("成交值", _money(breadth.get("trade_value")), "neutral"),
            ("上漲占比", _ratio_pct(breadth.get("positive_ratio")), "up" if (_number(breadth.get("positive_ratio")) or 0) >= 0.5 else "down"),
            ("平均漲跌", _pct(breadth.get("average_change_pct")), "up" if (_number(breadth.get("average_change_pct")) or 0) > 0 else "down" if (_number(breadth.get("average_change_pct")) or 0) < 0 else "neutral"),
            ("漲停/跌停", f"{distribution.get('limit_up_count', 0)} / {distribution.get('limit_down_count', 0)}", "neutral"),
            ("成交集中", _ratio_pct(breadth.get("top_value_share")), "neutral"),
        ],
        sections=sections,
        generated_at=generated_at,
    )

    return _preview_payload(
        template_key="market_overview",
        scope_type="market",
        scope_id="tw",
        subject=subject,
        body_text="\n".join(body_lines),
        body_html=body_html,
        generated_at=generated_at,
        as_of=None if as_of == "-" else as_of,
        warnings=warnings,
        missing=missing,
        metadata={
            "kind": envelope.get("kind"),
            "breadth": breadth,
            "distribution": distribution,
            "stance": stance,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
            "source_refs": envelope.get("source_refs") or [],
            "radar": radar_block["metadata"] if radar_block is not None else None,
        },
    )


def _us_sample_stance(
    *,
    advance_count: int,
    decline_count: int,
    total_count: int,
    average_change_pct: float | None,
) -> str:
    if total_count <= 0 or average_change_pct is None:
        return "資料不足"
    advance_ratio = advance_count / total_count
    decline_ratio = decline_count / total_count
    if advance_ratio >= 0.6 and average_change_pct > 0:
        return "偏多"
    if decline_ratio >= 0.6 and average_change_pct < 0:
        return "轉弱"
    return "震盪"


def _latest_us_as_of(rows: list[dict[str, Any]], fallback: Any) -> str:
    values = [
        str(value)
        for row in rows
        for value in (row.get("time") or row.get("trade_date"),)
        if value
    ]
    if values:
        return max(values)
    return _display(fallback)


def _us_source_label(row: dict[str, Any]) -> str:
    if row.get("status") == "intraday":
        source = _display(row.get("source"), "Yahoo")
        return f"盤中 / {source}"
    if row.get("trade_date"):
        return "日線"
    return _display(row.get("status"), "-")


def _us_market_rows(rows: list[dict[str, Any]], *, limit: int = 8) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        table_rows.append(
            [
                {"value": _stock_label(row), "strong": True},
                {"value": _pct(row.get("change_pct")), "tone": tone, "strong": True},
                _price(row.get("close")),
                _compact_number(row.get("volume")),
                _us_source_label(row),
            ]
        )
    return table_rows


def _us_structure_rows(
    breadth: dict[str, Any],
    ranking: dict[str, Any],
) -> list[list[dict[str, Any] | str]]:
    return [
        [
            {"value": "上漲占比", "strong": True},
            _ratio_pct(breadth.get("positive_ratio")),
            "上漲檔數 / 有漲跌幅資料檔數",
        ],
        [
            {"value": "平均漲跌", "strong": True},
            {
                "value": _pct(breadth.get("average_change_pct")),
                "tone": "up" if (_number(breadth.get("average_change_pct")) or 0) > 0 else "down" if (_number(breadth.get("average_change_pct")) or 0) < 0 else "neutral",
                "strong": True,
            },
            "美股自選股池簡單平均",
        ],
        [
            {"value": "盤中覆蓋", "strong": True},
            f"{breadth.get('intraday_count', 0)} / {breadth.get('total_count', 0)}",
            "已取得 Yahoo 盤中 overlay 的檔數",
        ],
        [
            {"value": "日線新鮮度", "strong": True},
            "current" if ranking.get("is_current") else "stale",
            f"target {ranking.get('target_trade_date') or '-'}，latest {ranking.get('trade_date') or '-'}",
        ],
        [
            {"value": "無資料", "strong": True},
            str(ranking.get("no_data_count", 0)),
            "自選股池中沒有日線或盤中價格的檔數",
        ],
    ]


def _build_us_market_overview_preview(db: Session) -> dict[str, Any]:
    ranking = us_market_service.get_us_watchlist_ranking(
        db=db,
        group_id=None,
        include_children=True,
        enabled_only=True,
        rank_by="change_pct",
        sort_order="desc",
        use_intraday=True,
        intraday_limit=30,
    )
    generated_at = utc_now()
    rows = [row for row in ranking.get("results") or [] if isinstance(row, dict)]
    ranked_rows = [row for row in rows if _number(row.get("change_pct")) is not None]
    advance_count = sum(1 for row in ranked_rows if (_number(row.get("change_pct")) or 0) > 0)
    decline_count = sum(1 for row in ranked_rows if (_number(row.get("change_pct")) or 0) < 0)
    unchanged_count = max(len(ranked_rows) - advance_count - decline_count, 0)
    total_count = len(rows)
    intraday_count = sum(1 for row in rows if row.get("status") == "intraday")
    average_change_pct = (
        sum(_number(row.get("change_pct")) or 0 for row in ranked_rows) / len(ranked_rows)
        if ranked_rows
        else None
    )
    positive_ratio = advance_count / len(ranked_rows) if ranked_rows else None
    stance = _us_sample_stance(
        advance_count=advance_count,
        decline_count=decline_count,
        total_count=len(ranked_rows),
        average_change_pct=average_change_pct,
    )
    as_of = _latest_us_as_of(rows, ranking.get("trade_date") or ranking.get("target_trade_date"))
    top_gainers = sorted(
        ranked_rows,
        key=lambda row: _number(row.get("change_pct")) or 0,
        reverse=True,
    )[:8]
    top_losers = sorted(
        ranked_rows,
        key=lambda row: _number(row.get("change_pct")) or 0,
    )[:8]
    volume_leaders = sorted(
        [row for row in rows if _number(row.get("volume")) is not None],
        key=lambda row: _number(row.get("volume")) or 0,
        reverse=True,
    )[:8]
    breadth = {
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "ranked_count": len(ranked_rows),
        "intraday_count": intraday_count,
        "positive_ratio": positive_ratio,
        "average_change_pct": average_change_pct,
    }
    warnings = ["美股總覽目前以美股自選股池計算，不代表全美市場全量廣度。"]
    missing: list[str] = []
    if total_count <= 0:
        missing.append("us_watchlist_items")
    if total_count > 0 and intraday_count <= 0:
        warnings.append("尚未取得盤中 overlay；目前內容可能只反映最新本地日線。")
    elif total_count > intraday_count:
        warnings.append(f"盤中 overlay 覆蓋 {intraday_count}/{total_count} 檔，其餘使用最新本地日線。")
    if not ranking.get("is_current", True):
        warnings.append(
            f"日線資料可能落後：target {ranking.get('target_trade_date') or '-'}，"
            f"latest {ranking.get('trade_date') or '-'}。"
        )

    subject = f"[OMI 派報] 美股自選股即時總覽 {as_of}"
    lead = (
        f"美股自選股池目前判定為{stance}。"
        f"上漲 {advance_count}、下跌 {decline_count}、平盤 {unchanged_count}，"
        f"覆蓋 {total_count} 檔；盤中資料 {intraday_count} 檔。"
    )
    body_lines = [
        f"# 美股自選股即時總覽 {as_of}",
        "",
        f"結論：{lead}",
        "",
        "## 市場範圍",
        "- 範圍：美股自選股池，不代表全美市場。",
        f"- 上漲 / 下跌 / 平盤：{advance_count} / {decline_count} / {unchanged_count}",
        f"- 覆蓋檔數：{total_count}",
        f"- 盤中覆蓋：{intraday_count}",
        f"- 上漲占比：{_ratio_pct(positive_ratio)}",
        f"- 平均漲跌：{_pct(average_change_pct)}",
        "",
        "## 強勢股",
        *(_line_items(top_gainers) or ["- 暫無可用資料"]),
        "",
        "## 弱勢股",
        *(_line_items(top_losers) or ["- 暫無可用資料"]),
        "",
        "## 成交量焦點",
        *(
            [
                f"- {_stock_label(row)}: {_compact_number(row.get('volume'))}，{_pct(row.get('change_pct'))}"
                for row in volume_leaders
            ]
            or ["- 暫無可用資料"]
        ),
        "",
        "## 資料限制",
        *[f"- {warning}" for warning in warnings],
        *[f"- missing: {item}" for item in missing],
    ]

    body_html = _report_html(
        title=f"美股自選股即時總覽 {as_of}",
        subtitle="美股自選股池盤中 overlay 與強弱摘要",
        lead=lead,
        metrics=[
            ("狀態", stance, "warning" if stance in {"資料不足", "震盪"} else "up" if stance == "偏多" else "down"),
            ("上漲", str(advance_count), "up"),
            ("下跌", str(decline_count), "down"),
            ("盤中覆蓋", f"{intraday_count} / {total_count}", "neutral"),
            ("上漲占比", _ratio_pct(positive_ratio), "up" if (positive_ratio or 0) >= 0.5 else "down"),
            ("平均漲跌", _pct(average_change_pct), "up" if (average_change_pct or 0) > 0 else "down" if (average_change_pct or 0) < 0 else "neutral"),
            ("覆蓋檔數", str(total_count), "neutral"),
            ("無資料", str(ranking.get("no_data_count", 0)), "warning" if ranking.get("no_data_count", 0) else "neutral"),
        ],
        sections=[
            _section(
                "即時結構",
                _table(
                    ["項目", "數值", "說明"],
                    _us_structure_rows(breadth, ranking),
                    empty="暫無可用資料",
                ),
            ),
            _section(
                "成交量焦點",
                _table(
                    ["標的", "漲跌幅", "最新", "成交量", "來源"],
                    _us_market_rows(volume_leaders),
                    empty="暫無可用資料",
                ),
            ),
            _section_grid(
                [
                    (
                        "強勢股",
                        _table(
                            ["標的", "漲跌幅", "最新", "成交量", "來源"],
                            _us_market_rows(top_gainers),
                            empty="暫無可用資料",
                        ),
                    ),
                    (
                        "弱勢股",
                        _table(
                            ["標的", "漲跌幅", "最新", "成交量", "來源"],
                            _us_market_rows(top_losers),
                            empty="暫無可用資料",
                        ),
                    ),
                ]
            ),
            _section("資料限制", _list_html([*warnings, *[f"missing: {item}" for item in missing]], empty="未回報重大資料缺口。")),
        ],
        generated_at=generated_at,
    )

    return _preview_payload(
        template_key="market_overview",
        scope_type="market",
        scope_id="us",
        subject=subject,
        body_text="\n".join(body_lines),
        body_html=body_html,
        generated_at=generated_at,
        as_of=None if as_of == "-" else as_of,
        warnings=warnings,
        missing=missing,
        metadata={
            "kind": "dispatch_us_watchlist_market_overview",
            "breadth": breadth,
            "stance": stance,
            "source_refs": ["us_market.watchlists.ranking"],
            "ranking": {
                key: ranking.get(key)
                for key in (
                    "requested_symbol_count",
                    "ranked_count",
                    "no_data_count",
                    "trade_date",
                    "target_trade_date",
                    "is_current",
                    "current_symbol_count",
                    "stale_symbol_count",
                )
            },
        },
    )


def build_market_overview_preview(
    db: Session,
    *,
    market: str = "tw",
    include_radar: bool = False,
    radar_group_id: int | None = None,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = "score",
    sort_order: str = "desc",
    radar_mode: str = "action",
    content_depth: str = "standard",
    radar_limit: int | None = None,
) -> dict[str, Any]:
    normalized_market = str(market or "tw").strip().lower()
    if normalized_market == "us":
        return _build_us_market_overview_preview(db)
    return _build_tw_market_overview_preview(
        db,
        include_radar=include_radar,
        radar_group_id=radar_group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
        content_depth=content_depth,
        radar_limit=radar_limit,
    )


def _watchlist_row_reason(row: dict[str, Any]) -> str:
    return _display(
        row.get("action_label")
        or row.get("reason")
        or row.get("primary_signal_label")
        or row.get("signal_label")
        or row.get("status"),
        "-",
    )


def _watchlist_rows(rows: list[dict[str, Any]], *, limit: int = 6) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        score = _number(row.get("score"))
        table_rows.append(
            [
                {"value": _stock_label(row), "strong": True},
                {"value": _pct(row.get("change_pct")), "tone": tone, "strong": True},
                f"{score:.1f}" if score is not None else "-",
                _watchlist_row_reason(row),
            ]
        )
    return table_rows


def _normalize_content_depth(value: str | None) -> str:
    normalized = str(value or "standard").strip().lower()
    if normalized in {"deep", "full", "detailed"}:
        return "deep"
    return "standard"


def _bounded_radar_limit(value: int | None, *, content_depth: str) -> int:
    default = 16 if content_depth == "deep" else 8
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 24))


def _row_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("stock_id") or row.get("symbol") or row.get("label") or ""),
        str(row.get("time") or row.get("trade_date") or row.get("rank") or ""),
    )


def _unique_watchlist_rows(*sources: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for row in source:
            identity = _row_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _watchlist_signal_text(row: dict[str, Any], *, limit: int = 3) -> str:
    labels = [
        str(label).strip()
        for label in row.get("signal_labels") or []
        if str(label).strip()
    ]
    if not labels and row.get("primary_signal_label"):
        labels.append(str(row["primary_signal_label"]))
    if not labels:
        labels = [
            str(label).strip()
            for label in row.get("matched_signal_keys") or row.get("signal_keys") or []
            if str(label).strip()
        ]
    return "、".join(labels[:limit]) if labels else "-"


def _watchlist_bucket_text(row: dict[str, Any]) -> str:
    return _display(
        row.get("bucket_label")
        or row.get("bucket")
        or row.get("primary_signal_label")
        or row.get("status"),
        "-",
    )


def _watchlist_row_text_blob(row: dict[str, Any]) -> str:
    values = [
        row.get("bucket"),
        row.get("bucket_label"),
        row.get("status"),
        row.get("action_label"),
        row.get("reason"),
        row.get("primary_signal_label"),
        *(row.get("signal_labels") or []),
        *(row.get("matched_signal_keys") or []),
    ]
    return " ".join(str(value).lower() for value in values if value)


def _is_watchlist_risk_row(row: dict[str, Any]) -> bool:
    blob = _watchlist_row_text_blob(row)
    return any(
        token in blob
        for token in (
            "risk",
            "weak",
            "selloff",
            "bearish",
            "support_break",
            "overheat",
            "風險",
            "轉弱",
            "過熱",
            "保守",
            "風控",
            "跌破",
        )
    )


def _is_watchlist_momentum_row(row: dict[str, Any]) -> bool:
    blob = _watchlist_row_text_blob(row)
    return any(
        token in blob
        for token in (
            "breakout",
            "momentum",
            "surge",
            "volume",
            "trend_reclaim",
            "compression",
            "突破",
            "動能",
            "放量",
            "續追",
            "追蹤",
        )
    )


def _watchlist_v2_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    include_signals: bool = False,
) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for row in rows[:limit]:
        change = _number(row.get("change_pct"))
        tone = "up" if change and change > 0 else "down" if change and change < 0 else "neutral"
        score = _number(row.get("score"))
        observation = _watchlist_row_reason(row)
        if include_signals:
            signals = _watchlist_signal_text(row)
            if signals != "-":
                observation = f"{observation} / 訊號：{signals}"
        trade_date = _display(row.get("time") or row.get("trade_date"), "-")
        if row.get("stale"):
            trade_date = f"{trade_date} / stale"
        table_rows.append(
            [
                {"value": _stock_label(row), "strong": True},
                {"value": _pct(row.get("change_pct")), "tone": tone, "strong": True},
                _price(row.get("close") or row.get("close_price")),
                _compact_number(row.get("volume") or row.get("trade_volume")),
                f"{score:.1f}" if score is not None else "-",
                trade_date,
                _watchlist_bucket_text(row),
                observation,
            ]
        )
    return table_rows


def _watchlist_radar_metric_rows(radar: dict[str, Any]) -> list[list[dict[str, Any] | str]]:
    trade_date = _display(radar.get("trade_date") or radar.get("target_trade_date"))
    stale_count = _integer(radar.get("stale_stock_count")) or 0
    return [
        [
            {"value": "雷達模式", "strong": True},
            _display(radar.get("mode"), "-"),
            "本次派報採用的掃描視角",
        ],
        [
            {"value": "命中檔數", "strong": True},
            str(radar.get("matched_count") or radar.get("radar_count") or 0),
            f"最多列出 {radar.get('dispatch_limit') or '-'} 檔",
        ],
        [
            {"value": "資料日期", "strong": True},
            trade_date,
            "雷達項目的交易日或目標交易日",
        ],
        [
            {"value": "資料狀態", "strong": True},
            "current" if radar.get("is_current") is not False and stale_count <= 0 else "stale / partial",
            f"stale {stale_count} 檔",
        ],
    ]


def _watchlist_structure_rows(
    breadth: dict[str, Any],
    radar: dict[str, Any],
) -> list[list[dict[str, Any] | str]]:
    ranked = _integer(breadth.get("ranked_count")) or 0
    requested = _integer(breadth.get("requested_stock_count")) or 0
    up_count = _integer(breadth.get("up_count")) or 0
    down_count = _integer(breadth.get("down_count")) or 0
    no_data = _integer(breadth.get("no_data_count")) or 0
    stale_count = _integer(breadth.get("stale_stock_count")) or 0
    return [
        [
            {"value": "排名覆蓋", "strong": True},
            f"{ranked} / {requested}",
            "本次自選股可用日線/技術資料覆蓋",
        ],
        [
            {"value": "上漲 / 下跌", "strong": True},
            f"{up_count} / {down_count}",
            "以 watchlist ranking 可用漲跌幅計算",
        ],
        [
            {"value": "平均漲跌", "strong": True},
            _display(breadth.get("average_change_pct_text"), _pct(breadth.get("average_change_pct"))),
            "自選股池簡單平均，非市值加權",
        ],
        [
            {"value": "雷達命中", "strong": True},
            str(radar.get("matched_count") or radar.get("radar_count") or 0),
            "符合本次 radar mode 的標的數",
        ],
        [
            {"value": "缺資料 / stale", "strong": True},
            f"{no_data} / {stale_count}",
            "資料缺口會影響排序與雷達解讀",
        ],
    ]


def _watchlist_visual_rows(
    breadth: dict[str, Any],
    radar: dict[str, Any],
    *,
    priority_count: int,
    momentum_count: int,
    risk_count: int,
) -> list[tuple[str, str, float | None, str]]:
    ranked = _integer(breadth.get("ranked_count")) or 0
    requested = _integer(breadth.get("requested_stock_count")) or 0
    radar_count = _integer(radar.get("matched_count")) or _integer(radar.get("radar_count")) or 0
    coverage_ratio = ranked / requested if requested else None
    radar_ratio = radar_count / ranked if ranked else None
    split_total = max(momentum_count + risk_count, 1)
    momentum_ratio = momentum_count / split_total
    risk_ratio = risk_count / split_total
    return [
        (
            "資料覆蓋",
            f"{ranked} / {requested}",
            coverage_ratio,
            "info" if (coverage_ratio or 0) >= 0.8 else "warning",
        ),
        (
            "雷達密度",
            f"{radar_count} / {ranked}",
            radar_ratio,
            "warning" if (radar_ratio or 0) >= 0.5 else "info",
        ),
        (
            "動能比重",
            str(momentum_count),
            momentum_ratio,
            "up",
        ),
        (
            "風險比重",
            str(risk_count),
            risk_ratio,
            "risk" if risk_count else "info",
        ),
    ]


def _watchlist_radar_focus_lines(
    *,
    group_name: str,
    radar: dict[str, Any],
    priority_rows: list[dict[str, Any]],
    momentum_rows: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
) -> list[str]:
    first_priority = _stock_label(priority_rows[0]) if priority_rows else "暫無明確優先名單"
    first_momentum = _stock_label(momentum_rows[0]) if momentum_rows else "暫無明確動能名單"
    first_risk = _stock_label(risk_rows[0]) if risk_rows else "暫無明確風險名單"
    matched = radar.get("matched_count") or radar.get("radar_count") or len(priority_rows)
    return [
        f"{group_name} 本次雷達命中 {matched} 檔，優先從 {first_priority} 開始檢查。",
        f"突破/動能端先看 {first_momentum}，重點是確認延續、回測區與失效條件。",
        f"風險端先看 {first_risk}，重點是破線、過熱、量價轉弱或資料 stale。",
    ]


def _watchlist_research_checklist(
    *,
    priority_rows: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
) -> list[str]:
    checklist = [
        "先用雷達分類決定閱讀順序，不把雷達命中直接當買賣訊號。",
        "對優先名單逐檔檢查支撐/壓力、回測區、成交量延續與失效條件。",
        "若同時存在風險名單，先處理持倉風控，再看突破追蹤。",
    ]
    if priority_rows:
        checklist.append(f"第一順位先看 {_stock_label(priority_rows[0])} 的延續確認。")
    if risk_rows:
        checklist.append(f"風險順位先看 {_stock_label(risk_rows[0])} 是否需要降風險。")
    return checklist


def _watchlist_bucket_lines(radar: dict[str, Any]) -> list[str]:
    buckets = [bucket for bucket in radar.get("buckets") or [] if isinstance(bucket, dict)]
    lines = []
    for bucket in buckets:
        count = _integer(bucket.get("count")) or 0
        if count > 0:
            lines.append(f"{bucket.get('label') or bucket.get('key')}: {count}")
    return lines or ["目前沒有分桶統計。"]


def _watchlist_bucket_rows(radar: dict[str, Any], *, limit: int = 12) -> list[list[dict[str, Any] | str]]:
    table_rows: list[list[dict[str, Any] | str]] = []
    for bucket in [bucket for bucket in radar.get("buckets") or [] if isinstance(bucket, dict)][:limit]:
        count = _integer(bucket.get("count")) or 0
        if count <= 0:
            continue
        label = _display(bucket.get("label") or bucket.get("key"), "-")
        key = _display(bucket.get("key"), "-")
        tone = _bucket_chart_tone(key, label)
        table_rows.append(
            [
                {"value": label, "strong": True},
                {"value": str(count), "tone": tone, "strong": True},
                _display(bucket.get("description"), "-"),
            ]
        )
    return table_rows


def _bucket_chart_tone(key: str, label: str) -> str:
    text = f"{key} {label}".lower()
    if any(token in text for token in ("risk", "weak", "selloff", "support_break", "風險", "轉弱", "跌破", "過熱")):
        return "down"
    if any(token in text for token in ("breakout", "surge", "momentum", "volume", "突破", "急漲", "動能", "放量")):
        return "up"
    return "neutral"


def _watchlist_bucket_chart_rows(radar: dict[str, Any]) -> list[tuple[str, str, float | None, str]]:
    buckets = [
        bucket
        for bucket in radar.get("buckets") or []
        if isinstance(bucket, dict) and (_integer(bucket.get("count")) or 0) > 0
    ]
    if not buckets:
        return []
    max_count = max(_integer(bucket.get("count")) or 0 for bucket in buckets) or 1
    chart_rows: list[tuple[str, str, float | None, str]] = []
    for bucket in buckets[:8]:
        count = _integer(bucket.get("count")) or 0
        label = _display(bucket.get("label") or bucket.get("key"), "-")
        key = _display(bucket.get("key"), "")
        chart_rows.append((label, str(count), count / max_count, _bucket_chart_tone(key, label)))
    return chart_rows


def _watchlist_text_rows(rows: list[dict[str, Any]], *, limit: int, include_signals: bool = False) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        detail = _watchlist_row_reason(row)
        if include_signals:
            signals = _watchlist_signal_text(row)
            if signals != "-":
                detail = f"{detail}；訊號：{signals}"
        score = _number(row.get("score"))
        close = row.get("close") if row.get("close") is not None else row.get("close_price")
        volume = row.get("volume") if row.get("volume") is not None else row.get("trade_volume")
        trade_date = _display(row.get("time") or row.get("trade_date"), "-")
        details = [
            _pct(row.get("change_pct")),
            f"收盤 {_price(close)}",
            f"量 {_compact_number(volume)}",
        ]
        if score is not None:
            details.append(f"分數 {score:.1f}")
        details.extend(
            [
                f"日期 {trade_date}",
                _watchlist_bucket_text(row),
                detail,
            ]
        )
        lines.append(f"- {_stock_label(row)}: {'，'.join(details)}")
    return lines or ["- 暫無明確名單"]


def _build_watchlist_radar_dispatch_block(
    db: Session,
    *,
    group_id: int,
    strategy_profile: str,
    rank_by: str,
    sort_order: str,
    radar_mode: str,
    content_depth: str,
    radar_limit: int | None,
    title_prefix: str = "自選股雷達",
) -> dict[str, Any]:
    normalized_depth = _normalize_content_depth(content_depth)
    normalized_radar_limit = _bounded_radar_limit(
        radar_limit,
        content_depth=normalized_depth,
    )
    envelope = reports.build_watchlist_brief(
        db=db,
        group_id=group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
        radar_limit=normalized_radar_limit,
    )
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    group_name = str(overview.get("group_name") or f"Watchlist #{group_id}")
    radar_rows = [row for row in overview.get("radar_rows") or [] if isinstance(row, dict)]
    follow_rows = [row for row in overview.get("follow_rows") or [] if isinstance(row, dict)]
    pullback_rows = [row for row in overview.get("pullback_rows") or [] if isinstance(row, dict)]
    defensive_rows = [row for row in overview.get("defensive_rows") or [] if isinstance(row, dict)]
    strong_rows = [row for row in overview.get("strong_rows") or [] if isinstance(row, dict)]
    weak_rows = [row for row in overview.get("weak_rows") or [] if isinstance(row, dict)]
    radar = dict(overview.get("radar") if isinstance(overview.get("radar"), dict) else {})
    radar["dispatch_limit"] = normalized_radar_limit

    momentum_rows = _unique_watchlist_rows(
        [row for row in radar_rows if _is_watchlist_momentum_row(row)],
        follow_rows,
        strong_rows,
        limit=normalized_radar_limit,
    )
    risk_rows = _unique_watchlist_rows(
        [row for row in radar_rows if _is_watchlist_risk_row(row)],
        defensive_rows,
        weak_rows,
        limit=normalized_radar_limit,
    )
    priority_rows = _unique_watchlist_rows(
        radar_rows,
        follow_rows,
        strong_rows,
        limit=normalized_radar_limit,
    )
    breadth = overview.get("breadth") if isinstance(overview.get("breadth"), dict) else {}
    focus_lines = _watchlist_radar_focus_lines(
        group_name=group_name,
        radar=radar,
        priority_rows=priority_rows,
        momentum_rows=momentum_rows,
        risk_rows=risk_rows,
    )
    visual_rows = _watchlist_visual_rows(
        breadth,
        radar,
        priority_count=len(priority_rows),
        momentum_count=len(momentum_rows),
        risk_count=len(risk_rows),
    )
    bucket_visual_rows = _watchlist_bucket_chart_rows(radar)
    checklist_lines = _watchlist_research_checklist(
        priority_rows=priority_rows,
        risk_rows=risk_rows,
    )

    text_lines = [
        "",
        f"## {title_prefix}：{group_name}",
        f"- 視角：{radar.get('mode') or radar_mode}",
        f"- 命中：{radar.get('matched_count') or radar.get('radar_count') or len(radar_rows)} 檔",
        f"- 分桶：{'；'.join(_watchlist_bucket_lines(radar))}",
        "",
        "### 雷達判讀",
        *[f"- {line}" for line in focus_lines],
        "",
        "### 圖表摘要 / 視覺摘要",
        *[
            f"- {label}：{value_label}"
            for label, value_label, _ratio_value, _tone in visual_rows
        ],
        *(
            [
                f"- {label}：{value_label}"
                for label, value_label, _ratio_value, _tone in bucket_visual_rows
            ]
            if bucket_visual_rows
            else []
        ),
        "",
        "### 研究檢查清單",
        *[f"- {line}" for line in checklist_lines],
        "",
        "### 雷達優先名單",
        *_watchlist_text_rows(
            priority_rows,
            limit=normalized_radar_limit,
            include_signals=normalized_depth == "deep",
        ),
    ]
    if normalized_depth == "deep":
        text_lines.extend(
            [
                "",
                "### 突破 / 動能",
                *_watchlist_text_rows(momentum_rows, limit=normalized_radar_limit, include_signals=True),
                "",
                "### 風險 / 轉弱 / 過熱",
                *_watchlist_text_rows(risk_rows, limit=normalized_radar_limit, include_signals=True),
            ]
        )

    html_sections = [
        _section(
            f"{title_prefix}：{group_name}",
            _table(
                ["項目", "數值", "說明"],
                _watchlist_radar_metric_rows(radar),
                empty="暫無雷達摘要",
            )
            + _table(
                ["分桶", "檔數", "說明"],
                _watchlist_bucket_rows(radar),
                empty="目前沒有分桶統計。",
            ),
        ),
        _section("雷達判讀", _list_html(focus_lines, empty="暫無雷達判讀。")),
        _section("雷達圖表摘要 / 視覺摘要", _bar_table(visual_rows)),
        _section("雷達分桶圖", _bar_table(bucket_visual_rows) or _list_html([], empty="目前沒有分桶統計。")),
        _section("研究檢查清單", _list_html(checklist_lines, empty="暫無研究檢查項。")),
        _section(
            "雷達優先名單",
            _table(
                WATCHLIST_DETAIL_HEADERS,
                _watchlist_v2_rows(
                    priority_rows,
                    limit=normalized_radar_limit,
                    include_signals=normalized_depth == "deep",
                ),
                empty="暫無可用雷達名單",
            ),
        ),
    ]
    if normalized_depth == "deep":
        html_sections.extend(
            [
                _section(
                    "突破 / 動能",
                    _table(
                        WATCHLIST_DETAIL_HEADERS,
                        _watchlist_v2_rows(momentum_rows, limit=normalized_radar_limit, include_signals=True),
                        empty="暫無明確突破或動能名單",
                    ),
                ),
                _section(
                    "風險 / 轉弱 / 過熱",
                    _table(
                        WATCHLIST_DETAIL_HEADERS,
                        _watchlist_v2_rows(risk_rows, limit=normalized_radar_limit, include_signals=True),
                        empty="暫無明確風險名單",
                    ),
                ),
            ]
        )

    return {
        "text_lines": text_lines,
        "html_sections": html_sections,
        "warnings": [str(item) for item in envelope.get("warnings") or []],
        "missing": [str(item) for item in envelope.get("missing") or []],
        "metadata": {
            "kind": envelope.get("kind"),
            "group_id": group_id,
            "group_name": group_name,
            "dispatch_version": "v2",
            "content_depth": normalized_depth,
            "radar_mode": radar.get("mode") or radar_mode,
            "radar_limit": normalized_radar_limit,
            "radar": radar,
            "breadth": breadth,
            "radar_sections": {
                "priority_count": len(priority_rows),
                "momentum_count": len(momentum_rows),
                "risk_count": len(risk_rows),
            },
        },
    }


def build_watchlist_brief_preview(
    db: Session,
    *,
    group_id: int,
    strategy_profile: str,
    rank_by: str,
    sort_order: str,
    radar_mode: str,
    content_depth: str = "standard",
    radar_limit: int | None = None,
) -> dict[str, Any]:
    normalized_depth = _normalize_content_depth(content_depth)
    normalized_radar_limit = _bounded_radar_limit(
        radar_limit,
        content_depth=normalized_depth,
    )
    envelope = reports.build_watchlist_brief(
        db=db,
        group_id=group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
        radar_limit=normalized_radar_limit,
    )
    generated_at = utc_now()
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    human_answer = overview.get("human_answer") if isinstance(overview.get("human_answer"), dict) else {}
    group_name = str(overview.get("group_name") or f"Watchlist #{group_id}")
    as_of = str(overview.get("as_of") or envelope.get("as_of") or "-")
    breadth = overview.get("breadth") if isinstance(overview.get("breadth"), dict) else {}
    stance = _display(overview.get("stance"), "資料不足")
    confidence = _display(overview.get("confidence"), "-")
    subject = f"[OMI 派報] {group_name} 自選股觀察 {as_of}"
    lead = _display(overview.get("display"), f"{group_name} 暫無摘要。")
    human_lines = [
        str(line)
        for line in human_answer.get("lines") or []
        if str(line).strip()
    ]
    body_lines = [
        f"# {group_name} 自選股觀察 {as_of}",
        "",
        f"結論：{lead}",
        "",
        "## 摘要",
        *(str(human_answer.get("text") or overview.get("display") or "暫無摘要").splitlines()),
    ]
    radar_rows = [row for row in overview.get("radar_rows") or [] if isinstance(row, dict)]
    follow_rows = [row for row in overview.get("follow_rows") or [] if isinstance(row, dict)]
    pullback_rows = [row for row in overview.get("pullback_rows") or [] if isinstance(row, dict)]
    defensive_rows = [row for row in overview.get("defensive_rows") or [] if isinstance(row, dict)]
    strong_rows = [row for row in overview.get("strong_rows") or [] if isinstance(row, dict)]
    weak_rows = [row for row in overview.get("weak_rows") or [] if isinstance(row, dict)]
    radar = dict(overview.get("radar") if isinstance(overview.get("radar"), dict) else {})
    radar["dispatch_limit"] = normalized_radar_limit
    momentum_rows = _unique_watchlist_rows(
        [row for row in radar_rows if _is_watchlist_momentum_row(row)],
        follow_rows,
        strong_rows,
        limit=normalized_radar_limit,
    )
    risk_rows = _unique_watchlist_rows(
        [row for row in radar_rows if _is_watchlist_risk_row(row)],
        defensive_rows,
        weak_rows,
        limit=normalized_radar_limit,
    )
    pullback_follow_rows = _unique_watchlist_rows(
        pullback_rows,
        follow_rows,
        limit=normalized_radar_limit,
    )
    priority_rows = _unique_watchlist_rows(
        radar_rows,
        follow_rows,
        strong_rows,
        limit=normalized_radar_limit,
    )
    focus_lines = _watchlist_radar_focus_lines(
        group_name=group_name,
        radar=radar,
        priority_rows=priority_rows,
        momentum_rows=momentum_rows,
        risk_rows=risk_rows,
    )
    visual_rows = _watchlist_visual_rows(
        breadth,
        radar,
        priority_count=len(priority_rows),
        momentum_count=len(momentum_rows),
        risk_count=len(risk_rows),
    )
    bucket_visual_rows = _watchlist_bucket_chart_rows(radar)
    checklist_lines = _watchlist_research_checklist(
        priority_rows=priority_rows,
        risk_rows=risk_rows,
    )
    include_deep_signals = normalized_depth == "deep"
    body_lines.extend(
        [
            "",
            "## 自選股結構",
            f"- 排名覆蓋：{breadth.get('ranked_count', 0)} / {breadth.get('requested_stock_count', 0)}",
            f"- 上漲 / 下跌：{breadth.get('up_count', 0)} / {breadth.get('down_count', 0)}",
            f"- 平均漲跌：{_display(breadth.get('average_change_pct_text'), _pct(breadth.get('average_change_pct')))}",
            "",
            "## 雷達判讀",
            *[f"- {line}" for line in focus_lines],
            "",
            "## 圖表摘要 / 視覺摘要",
            *[
                f"- {label}：{value_label}"
                for label, value_label, _ratio_value, _tone in visual_rows
            ],
            *(
                [
                    f"- {label}：{value_label}"
                    for label, value_label, _ratio_value, _tone in bucket_visual_rows
                ]
                if bucket_visual_rows
                else []
            ),
            "",
            "## 研究檢查清單",
            *[f"- {line}" for line in checklist_lines],
        ]
    )
    if radar_rows:
        body_lines.extend(
            [
                "",
                "## 雷達總覽",
                f"- 視角：{radar.get('mode') or radar_mode}",
                f"- 命中：{radar.get('matched_count') or radar.get('radar_count') or len(radar_rows)} 檔",
                f"- 分桶：{'；'.join(_watchlist_bucket_lines(radar))}",
                "",
                "## 雷達優先名單",
                *_watchlist_text_rows(
                    radar_rows,
                    limit=normalized_radar_limit,
                    include_signals=normalized_depth == "deep",
                ),
            ]
        )
    if normalized_depth == "deep":
        body_lines.extend(
            [
                "",
                "## 突破 / 動能",
                *_watchlist_text_rows(momentum_rows, limit=normalized_radar_limit, include_signals=True),
                "",
                "## 風險 / 轉弱 / 過熱",
                *_watchlist_text_rows(risk_rows, limit=normalized_radar_limit, include_signals=True),
            ]
        )
    warnings = [str(item) for item in envelope.get("warnings") or []]
    missing = [str(item) for item in envelope.get("missing") or []]
    body_lines.extend(["", "## 資料限制"])
    if warnings or missing:
        body_lines.extend(f"- {item}" for item in [*warnings, *[f"missing: {item}" for item in missing]])
    else:
        body_lines.append("- 未回報重大資料缺口。")
    radar_sections = [
        _section(
            "自選股結構",
            _table(
                ["項目", "數值", "說明"],
                _watchlist_structure_rows(breadth, radar),
                empty="暫無自選股結構摘要",
            ),
        ),
        _section("雷達判讀", _list_html(focus_lines, empty="暫無雷達判讀。")),
        _section("圖表摘要 / 視覺摘要", _bar_table(visual_rows)),
        _section("雷達分桶圖", _bar_table(bucket_visual_rows) or _list_html([], empty="目前沒有分桶統計。")),
        _section("研究檢查清單", _list_html(checklist_lines, empty="暫無研究檢查項。")),
        _section(
            "雷達總覽",
            _table(
                ["項目", "數值", "說明"],
                _watchlist_radar_metric_rows(radar),
                empty="暫無雷達摘要",
            )
            + _table(
                ["分桶", "檔數", "說明"],
                _watchlist_bucket_rows(radar),
                empty="目前沒有分桶統計。",
            ),
        ),
        _section(
            "雷達優先名單",
            _table(
                WATCHLIST_DETAIL_HEADERS,
                _watchlist_v2_rows(
                    priority_rows,
                    limit=normalized_radar_limit,
                    include_signals=include_deep_signals,
                ),
                empty="暫無可用雷達名單",
            ),
        ),
    ]
    if normalized_depth == "deep":
        radar_sections.extend(
            [
                _section(
                    "突破 / 動能",
                    _table(
                        WATCHLIST_DETAIL_HEADERS,
                        _watchlist_v2_rows(
                            momentum_rows,
                            limit=normalized_radar_limit,
                            include_signals=True,
                        ),
                        empty="暫無明確突破或動能名單",
                    ),
                ),
                _section(
                    "風險 / 轉弱 / 過熱",
                    _table(
                        WATCHLIST_DETAIL_HEADERS,
                        _watchlist_v2_rows(
                            risk_rows,
                            limit=normalized_radar_limit,
                            include_signals=True,
                        ),
                        empty="暫無明確風險名單",
                    ),
                ),
                _section(
                    "雷達完整清單",
                    _table(
                        WATCHLIST_DETAIL_HEADERS,
                        _watchlist_v2_rows(
                            radar_rows,
                            limit=normalized_radar_limit,
                            include_signals=True,
                        ),
                        empty="暫無可用雷達名單",
                    ),
                ),
            ]
        )

    body_html = _report_html(
        title=f"{group_name} 自選股觀察",
        subtitle=f"資料日期 {as_of} / 派報 v2 / {normalized_depth}",
        lead=lead,
        metrics=[
            ("狀態", stance, "warning" if stance in {"震盪", "觀望", "資料不足"} else "down" if "弱" in stance else "up"),
            ("信心", confidence, "neutral"),
            ("已排名", f"{breadth.get('ranked_count', 0)} / {breadth.get('requested_stock_count', 0)}", "neutral"),
            ("平均漲跌", _display(breadth.get("average_change_pct_text"), "-"), "up" if (_number(breadth.get("average_change_pct")) or 0) > 0 else "down" if (_number(breadth.get("average_change_pct")) or 0) < 0 else "neutral"),
            ("雷達命中", str(radar.get("matched_count") or radar.get("radar_count") or len(radar_rows)), "warning" if not radar_rows else "up"),
            ("雷達模式", _display(radar.get("mode") or radar_mode), "neutral"),
            ("內容深度", "完整" if normalized_depth == "deep" else "標準", "neutral"),
            ("列出上限", str(normalized_radar_limit), "neutral"),
        ],
        sections=[
            _section("結論", _paragraphs(human_lines or [lead])),
            *radar_sections,
            _section(
                "等回測 / 續追",
                _table(
                    WATCHLIST_DETAIL_HEADERS,
                    _watchlist_v2_rows(
                        pullback_follow_rows,
                        limit=normalized_radar_limit,
                        include_signals=include_deep_signals,
                    ),
                    empty="暫無明確回測或續追名單",
                ),
            ),
            _section(
                "風險與保守名單",
                _table(
                    WATCHLIST_DETAIL_HEADERS,
                    _watchlist_v2_rows(
                        risk_rows,
                        limit=normalized_radar_limit,
                        include_signals=include_deep_signals,
                    ),
                    empty="暫無明確風險名單",
                ),
            ),
            _section("資料限制", _list_html([*warnings, *[f"missing: {item}" for item in missing]], empty="未回報重大資料缺口。")),
        ],
        generated_at=generated_at,
    )

    return _preview_payload(
        template_key="watchlist_brief",
        scope_type="watchlist",
        scope_id=str(group_id),
        subject=subject,
        body_text="\n".join(body_lines),
        body_html=body_html,
        generated_at=generated_at,
        as_of=None if as_of == "-" else as_of,
        warnings=warnings,
        missing=missing,
        metadata={
            "kind": envelope.get("kind"),
            "group_id": group_id,
            "group_name": group_name,
            "stance": overview.get("stance"),
            "confidence": overview.get("confidence"),
            "breadth": overview.get("breadth") or {},
            "dispatch_version": "v2",
            "content_depth": normalized_depth,
            "radar_mode": radar.get("mode") or radar_mode,
            "radar_limit": normalized_radar_limit,
            "radar": radar,
            "radar_sections": {
                "priority_count": len(priority_rows),
                "momentum_count": len(momentum_rows),
                "risk_count": len(risk_rows),
                "pullback_follow_count": len(pullback_follow_rows),
            },
        },
    )
