from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from app.ai import reports, tools
from app.db.models import utc_now
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


def _stock_label(row: dict[str, Any]) -> str:
    stock_id = _display(row.get("stock_id") or row.get("symbol"), "")
    name = _display(row.get("stock_name") or row.get("name") or row.get("security_name"), "")
    return " ".join(part for part in (stock_id, name) if part) or "-"


def _line_items(rows: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    items: list[str] = []
    for row in rows[:limit]:
        items.append(f"- {_stock_label(row)}: {_pct(row.get('change_pct'))}")
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
        f'<td style="{_style({"border-top": f"1px solid {MAIL_BORDER}", "padding": "9px 10px", "font-size": "13px", "vertical-align": "top", "color": _tone_color(tone) if tone != "neutral" else MAIL_TEXT, "font-weight": "700" if strong else "400"})}">'
        f"{escape(_display(value))}"
        "</td>"
    )


def _table(headers: list[str], rows: list[list[dict[str, Any] | str]], *, empty: str) -> str:
    header_html = "".join(
        f'<th align="left" style="{_style({"background": "#eef2f6", "border-top": f"1px solid {MAIL_BORDER}", "border-bottom": f"1px solid {MAIL_BORDER}", "padding": "8px 10px", "font-size": "12px", "color": MAIL_MUTED})}">{escape(header)}</th>'
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
        f'style="{_style({"border-collapse": "collapse", "margin-top": "8px"})}">'
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
            cells.append(
                '<td width="50%" valign="top" style="padding: 0 8px 0 0;">'
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
            '<body style="margin:0; padding:0; background:#eef2f6;">',
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#eef2f6;">',
            '<tr><td align="center" style="padding:28px 18px;">',
            f'<table role="presentation" width="1080" cellpadding="0" cellspacing="0" style="{_style({"width": "1080px", "max-width": "100%", "border-collapse": "collapse", "background": MAIL_PANEL, "border": f"1px solid {MAIL_BORDER}"})}">',
            f'<tr><td style="{_style({"padding": "26px 34px", "border-bottom": f"3px solid {MAIL_ACCENT}"})}">',
            f'<div style="{_style({"font-size": "11px", "letter-spacing": "0.18em", "font-weight": "800", "color": MAIL_ACCENT})}">OPEN MARKET INTELLIGENCE</div>',
            f'<h1 style="{_style({"font-size": "24px", "line-height": "1.25", "margin": "8px 0 4px", "color": MAIL_TEXT})}">{escape(title)}</h1>',
            f'<div style="{_style({"font-size": "13px", "color": MAIL_MUTED, "line-height": "1.5"})}">{escape(subtitle)}</div>',
            "</td></tr>",
            f'<tr><td style="{_style({"padding": "22px 34px 30px"})}">',
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
                _display(row.get("industry")),
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
                {"value": row.get("industry"), "strong": True},
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


def _build_tw_market_overview_preview(db: Session) -> dict[str, Any]:
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
    body_lines = [
        f"# 台股大盤總覽 {as_of}",
        "",
        f"結論：{lead}",
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
                f"- {row.get('industry')}: {_pct(row.get('average_change_pct'))}，上漲/下跌 {row.get('advance_count', 0)}/{row.get('decline_count', 0)}"
                for row in top_industries[:6]
            ]
            or ["- 暫無可用資料"]
        ),
        "",
        "## 弱勢產業",
        *(
            [
                f"- {row.get('industry')}: {_pct(row.get('average_change_pct'))}，上漲/下跌 {row.get('advance_count', 0)}/{row.get('decline_count', 0)}"
                for row in weak_industries[:6]
            ]
            or ["- 暫無可用資料"]
        ),
        "",
        "## 資料限制",
        *[f"- {warning}" for warning in envelope.get("warnings") or []],
    ]
    missing = [str(item) for item in envelope.get("missing") or []]
    warnings = [str(item) for item in envelope.get("warnings") or []]
    if missing:
        body_lines.extend(f"- missing: {item}" for item in missing)
    elif not warnings:
        body_lines.append("- 未回報重大資料缺口。")

    body_html = _report_html(
        title=f"台股大盤總覽 {as_of}",
        subtitle="全市場日線廣度與強弱股摘要",
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
        sections=[
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
            _section("資料限制", _list_html([*warnings, *[f"missing: {item}" for item in missing]], empty="未回報重大資料缺口。")),
        ],
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


def build_market_overview_preview(db: Session, *, market: str = "tw") -> dict[str, Any]:
    normalized_market = str(market or "tw").strip().lower()
    if normalized_market == "us":
        return _build_us_market_overview_preview(db)
    return _build_tw_market_overview_preview(db)


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


def build_watchlist_brief_preview(
    db: Session,
    *,
    group_id: int,
    strategy_profile: str,
    rank_by: str,
    sort_order: str,
    radar_mode: str,
) -> dict[str, Any]:
    envelope = reports.build_watchlist_brief(
        db=db,
        group_id=group_id,
        strategy_profile=strategy_profile,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
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
    if radar_rows:
        body_lines.extend(
            [
                "",
                "## 雷達名單",
                *[
                    f"- {row.get('stock_id', '-') } {row.get('stock_name') or ''}: {row.get('action_label') or row.get('reason') or '-'}"
                    for row in radar_rows[:6]
                ],
            ]
        )
    warnings = [str(item) for item in envelope.get("warnings") or []]
    missing = [str(item) for item in envelope.get("missing") or []]
    body_lines.extend(["", "## 資料限制"])
    if warnings or missing:
        body_lines.extend(f"- {item}" for item in [*warnings, *[f"missing: {item}" for item in missing]])
    else:
        body_lines.append("- 未回報重大資料缺口。")
    priority_rows = radar_rows or follow_rows or strong_rows
    body_html = _report_html(
        title=f"{group_name} 自選股觀察",
        subtitle=f"資料日期 {as_of} / 固定模板派報",
        lead=lead,
        metrics=[
            ("狀態", stance, "warning" if stance in {"震盪", "觀望", "資料不足"} else "down" if "弱" in stance else "up"),
            ("信心", confidence, "neutral"),
            ("已排名", f"{breadth.get('ranked_count', 0)} / {breadth.get('requested_stock_count', 0)}", "neutral"),
            ("平均漲跌", _display(breadth.get("average_change_pct_text"), "-"), "up" if (_number(breadth.get("average_change_pct")) or 0) > 0 else "down" if (_number(breadth.get("average_change_pct")) or 0) < 0 else "neutral"),
        ],
        sections=[
            _section("結論", _paragraphs(human_lines or [lead])),
            _section(
                "優先觀察",
                _table(
                    ["標的", "漲跌幅", "分數", "觀察"],
                    _watchlist_rows(priority_rows),
                    empty="暫無可用雷達名單",
                ),
            ),
            _section_grid(
                [
                    (
                        "等回測 / 續追",
                        _table(
                            ["標的", "漲跌幅", "分數", "觀察"],
                            _watchlist_rows(pullback_rows or follow_rows),
                            empty="暫無明確回測或續追名單",
                        ),
                    ),
                    (
                        "風險與保守名單",
                        _table(
                            ["標的", "漲跌幅", "分數", "觀察"],
                            _watchlist_rows(defensive_rows or weak_rows),
                            empty="暫無明確風險名單",
                        ),
                    ),
                ]
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
            "radar": overview.get("radar") or {},
        },
    )
