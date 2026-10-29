"""Pillow drawing of detached presentation fields; no technical calculations."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from math import isfinite

from app.dispatch.market_report_presentation import (
    MarketReportPresentation, _map, _rows, _number, _text, _stock,
    coverage_summary, display_status, index_summary, phase_dashboard_rows,
)


class ChartUnavailable(RuntimeError):
    """Safe, presentation-only failure; callers may omit the PNG."""


FONT_PATHS = (
    "C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/msjhbd.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

# Semantic meaning owns color; list position never does. (foreground, background)
SEMANTIC_COLORS = {
    "strength": ("#ad493d", "#fbe9e4"), "weakness": ("#237766", "#e1f1ed"),
    "flow": ("#326791", "#e5eef8"), "technical": ("#745895", "#eee8f5"),
    "warning": ("#92621d", "#fcf0d6"), "missing": ("#68757c", "#edf0f1"),
}
TAG_SEMANTICS = {
    "成交前列": "flow", "法人淨買": "flow", "法人淨賣": "flow",
    "漲幅前列": "strength", "強族群代表": "strength",
    "跌幅前列": "weakness", "弱族群代表": "weakness",
    "子產業代表": "flow", "技術": "technical", "背離": "warning",
    "警示": "warning", "資料不足": "missing",
}


def semantic_colors(tag: str) -> tuple[str, str]:
    return SEMANTIC_COLORS[TAG_SEMANTICS.get(tag, tag if tag in SEMANTIC_COLORS else "missing")]


def change_color(value) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        return semantic_colors("missing")[0]
    return semantic_colors("strength" if value > 0 else "weakness" if value < 0 else "missing")[0]


def render_market_dashboard_chart(model: MarketReportPresentation) -> bytes:
    return _render_png(model, stock=False)


def render_stock_analysis_chart(model: MarketReportPresentation) -> bytes:
    return _render_png(model, stock=True)


def render_technology_pulse_chart(model: MarketReportPresentation) -> bytes:
    return _render_png(model, stock=False, technology=True)


def _render_png(model: MarketReportPresentation, *, stock: bool, technology: bool = False) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ChartUnavailable("Pillow 未安裝；PNG 已略過。") from None
    fonts = None
    for candidate in FONT_PATHS:
        if not Path(candidate).is_file():
            continue
        try:
            fonts = {size: ImageFont.truetype(candidate, size=size) for size in (18, 20, 22, 24, 28, 32, 38)}
            break
        except OSError:
            continue
    if fonts is None:
        raise ChartUnavailable("找不到可用中文字型；PNG 已略過。")
    dimensions = (1600, 1960 if stock else 1800 if technology else 1200)
    canvas = Image.new("RGB", dimensions, "#f4f3ee")
    draw = ImageDraw.Draw(canvas)

    def text(x, y, value, size=22, width=1504, color="#233c45"):
        value = str(value).replace("\n", " ").replace("\r", " ").replace("missing", "未提供")
        clipped = len(value) > 600
        value = value[:600]
        while value and draw.textlength(value + ("…" if clipped else ""), font=fonts[size]) > width:
            value = value[:-1]
            clipped = True
        draw.text((x, y), value + ("…" if clipped else ""), font=fonts[size], fill=color)

    def line(y):
        draw.line((48, y, 1552, y), fill="#c5d0ce", width=1)

    def zone(x, y, label, row):
        # Prices, bounds and distances are all canonical fields.
        if not row:
            text(x, y, f"{label}｜未提供", 20, 686)
            return
        text(x, y, f"{label}  {_number(row.get('anchor_price'))}"
             f"  [{_number(row.get('lower_bound'))}–{_number(row.get('upper_bound'))}]"
             f"  {_number(row.get('distance_pct'), percent=True)}", 20, 686, semantic_colors("technical")[0])

    def tags(x, y, reasons):
        for slot, reason in enumerate(reasons[:3]):
            bx = x + slot * 220
            foreground, background = semantic_colors(reason)
            draw.rounded_rectangle((bx, y, bx + 210, y + 34), radius=5, fill=background)
            text(bx + 12, y + 3, reason, 20, 186, foreground)

    def sector_context(x, y, context):
        if not context:
            text(x, y, "產業比較｜資料不足", 20, 686, semantic_colors("missing")[0])
            return
        text(x, y, f"{_text(context.get('industry'))} · 樣本 {_text(context.get('trade_date'))}", 20, 686)
        relative = context.get("relative_change_pp")
        delta = f"{relative:+.2f} pp" if isinstance(relative, (int, float)) and isfinite(relative) else "未提供"
        text(x, y + 28, f"個股 {_number(context.get('stock_change_pct'), percent=True)} · 族群均幅 {_number(context.get('average_change_pct'), percent=True)}", 20, 686)
        text(x, y + 56, f"相對族群 {delta}", 20, 686, change_color(relative))

    draw.rectangle((0, 0, 1600, 118), fill="#173e4b")
    text(48, 18, "個股分析板" if stock else "科技股雷達" if technology else "市場＋族群總覽", 38, 450, "#ffffff")
    text(530, 29, model.header, 24, 1022, "#d4e4e7")
    subtitle = model.stance if model.phase_selection and not stock and not technology else model.daily_sample_scope
    text(48, 77, f"資料時間 {model.as_of}｜{subtitle}", 20, 1504, "#d4e4e7")

    if model.phase_selection and not stock and not technology:
        _draw_phase_dashboard(model, draw, text, line)
    elif technology:
        pulse = model.technology_pulse
        text(48, 140, "Technology Pulse｜科技盤勢摘要", 28)
        text(48, 187, f"等權平均 {_number(pulse.get('average_change_pct'), percent=True)}", 32, 690,
             change_color(pulse.get("average_change_pct")))
        text(828, 187, f"樣本成交 {_number(pulse.get('trade_value'), money=True)}", 28, 724, semantic_colors("flow")[0])
        text(48, 239, f"漲 {_number(pulse.get('advance_count'))} / 跌 {_number(pulse.get('decline_count'))} / 平 {_number(pulse.get('unchanged_count'))} · 上漲占比 {_number(pulse.get('positive_ratio'), ratio=True)}", 24, 1504)
        text(48, 282, f"科技樣本 {_number(pulse.get('sample_count'))} 檔 · 有漲跌 {_number(pulse.get('change_count'))} · 有成交值 {_number(pulse.get('trade_value_count'))} · 全市場樣本覆蓋 {display_status(_map(pulse.get('coverage')).get('status'))}", 20, 1504, semantic_colors("warning")[0])
        text(48, 317, pulse.get("universe_label") or "科技範圍證據未提供", 20)
        line(356)
        text(48, 370, "科技子產業｜均幅排序・participation", 28)
        sectors = _rows(pulse.get("sectors"))[:10]
        for index in range(10):
            x, y = 40 + (index % 2) * 780, 419 + (index // 2) * 98
            draw.rounded_rectangle((x, y, x + 740, y + 88), radius=8, fill="#ffffff")
            if index >= len(sectors):
                text(x + 18, y + 25, "無其他可用子產業樣本", 20, 686, semantic_colors("missing")[0])
                continue
            row = sectors[index]
            text(x + 18, y + 8, _text(row.get("industry")), 24, 465)
            text(x + 500, y + 8, _number(row.get("average_change_pct"), percent=True), 24, 210,
                 change_color(row.get("average_change_pct")))
            text(x + 18, y + 49, f"漲 {_number(row.get('advance_count'))} / 跌 {_number(row.get('decline_count'))} · 上漲占比 {_number(row.get('positive_ratio'), ratio=True)} · 樣本 {_number(row.get('sample_count'))}", 20, 686)
        text(48, 925, "科技焦點｜成交・漲跌異動・子產業代表", 28)
        focus = _rows(pulse.get("focus_stocks"))[:6]
        for index in range(6):
            x, y = 40 + (index % 2) * 780, 976 + (index // 2) * 240
            draw.rounded_rectangle((x, y, x + 740, y + 226), radius=10, fill="#ffffff")
            if index >= len(focus):
                text(x + 24, y + 25, "無其他可列示科技焦點", 22, 686, semantic_colors("missing")[0])
                continue
            item = focus[index]
            text(x + 24, y + 12, _stock(item), 28, 686)
            text(x + 24, y + 53, f"{_number(item.get('change_pct'), percent=True)} · 成交 {_number(item.get('trade_value'), money=True)}", 22, 686, change_color(item.get("change_pct")))
            tags(x + 24, y + 88, item.get("reason_tags", []))
            sector_context(x + 24, y + 131, _map(item.get("sector_context")))
        text(48, 1711, "科技統計僅涵蓋本地日線樣本；上漲占比以有漲跌資料個股為分母。", 20)
        text(48, 1745, "相對族群為同日個股減族群均幅（百分點）；非價格預測，不代表技術條件可用。", 20)
    elif stock:
        items = model.stock_analysis
        for index in range(8):
            x = 40 + (index % 2) * 780
            y = 140 + (index // 2) * 440
            draw.rounded_rectangle((x, y, x + 740, y + 432), radius=12, fill="#ffffff")
            if index >= len(items):
                text(x + 24, y + 24, "無其他可列示個股", 22, 686, "#738387")
                continue
            item = items[index]
            text(x + 24, y + 14, _stock(item), 28, 686)
            quote = []
            if item.get("change_pct") is not None:
                quote.append(_number(item["change_pct"], percent=True))
            if item.get("trade_value") is not None:
                quote.append(f"成交 {_number(item['trade_value'], money=True)}")
            text(x + 24, y + 55, "  ·  ".join(quote) if quote else "行情暫未提供", 22, 686,
                 change_color(item.get("change_pct")))
            tags(x + 24, y + 89, item.get("reason_tags", []))
            text(x + 24, y + 132, f"市場角色｜{item.get('market_role') or '入選依據未提供'}", 20, 686)
            sector_context(x + 24, y + 163, _map(item.get("sector_context")))
            if not item.get("technical_available"):
                text(x + 24, y + 258, "技術位置暫不可用", 22, 686, semantic_colors("missing")[0])
                for slot, reason in enumerate(item.get("technical_blockers", [])[:3]):
                    text(x + 24, y + 296 + slot * 36, reason, 18, 686, semantic_colors("warning")[0])
                continue
            reference = _map(item.get("reference"))
            text(x + 24, y + 247, f"參考 {_number(reference.get('price'))} · 已完成日線 {_text(reference.get('trade_date'))}", 20, 686)
            zone(x + 24, y + 279, "最近支撐候選", _map(item.get("support")))
            zone(x + 24, y + 308, "最近壓力候選", _map(item.get("resistance")))
            text(x + 24, y + 341, item.get("headline") or "技術摘要未提供", 22, 686)
            observe = _map(item.get("observe"))
            if observe:
                threshold = observe.get("threshold_price")
                text(x + 24, y + 376, f"觀察｜{observe.get('label') or ''}", 20, 490, "#536d74")
                if threshold is not None:
                    text(x + 532, y + 376, _number(threshold), 20, 178, "#536d74")
                text(x + 24, y + 404, observe.get("result_summary") or "", 18, 686, "#536d74")
            else:
                text(x + 24, y + 381, "觀察條件暫未提供", 20, 686, "#738387")
        text(48, 1901, "依來源順序列示；相對族群為樣本百分點差。支撐／壓力為上游研究候選區，非價格預測。", 20)
    else:
        rows = _rows(model.indices.get("items"))
        for x, identity in ((48, "TAIEX"), (828, "TPEX")):
            row = next((row for row in rows if row.get("index_id") == identity), {})
            text(x, 139, f"{identity}  {index_summary(row)}", 32, 724)
            text(x, 184, f"{display_status(_map(row.get('freshness')).get('status'))} · {_text(row.get('as_of') or row.get('trade_date'))}", 18, 724)
        breadth = model.breadth
        text(48, 225, f"廣度｜漲 {_number(breadth.get('advance_count'))}／跌 {_number(breadth.get('decline_count'))}／平 {_number(breadth.get('unchanged_count'))}", 24, 752)
        value = model.volume.get("current_cumulative_trade_value")
        label = "成交值"
        if value is None and model.volume.get("available_cumulative_trade_value") is not None:
            value = model.volume["available_cumulative_trade_value"]
            label = "可用部分成交值"
        text(828, 225, f"{label}｜{_number(value, money=True)}", 24, 724)
        text(48, 262, f"{display_status(breadth.get('status'))} · {_text(breadth.get('as_of') or breadth.get('trade_date'))}", 18, 752)
        text(828, 262, f"{display_status(model.volume.get('status'))} · {_text(model.volume.get('as_of') or model.volume.get('trade_date'))}", 18, 724)
        line(298)
        official = _map(model.chips.get("official_market_aggregate"))
        for x, identity, ids in ((48, "TWSE", {"TAIEX", "TWSE"}), (828, "TPEX", {"TPEX"})):
            row = next((row for row in _rows(official.get("rows")) if row.get("index_id") in ids), {})
            freshness = next((r for r in _rows(official.get("freshness")) if r.get("index_id") in ids), {})
            text(x, 313, f"官方法人 {identity}｜{_number(row.get('total_institutional_net_value'), money=True)}", 24, 724)
            text(x, 350, f"{_text(row.get('trade_date'))} · {display_status(freshness.get('status'))}", 18, 724)
        block = _map(model.chips.get("institutional_per_stock"))
        text(48, 389, f"個股法人｜{coverage_summary(block)} · {_text(block.get('trade_date'))} · {display_status(block.get('status'))}", 20)
        line(431)
        for column, (key, label, color) in enumerate((
            ("strong", "強勢族群", semantic_colors("strength")[0]),
            ("weak", "弱勢族群", semantic_colors("weakness")[0]),
        )):
            x = 40 + column * 780
            rows = model.sector_radar.get(key, [])
            text(x + 10, 448, label, 28, 500, color)
            text(x + 610, 458, f"{len(rows)} / 6", 20, 120)
            for index in range(6):
                y = 494 + index * 76
                draw.rounded_rectangle((x, y, x + 740, y + 68), radius=8, fill="#ffffff")
                if index >= len(rows):
                    text(x + 16, y + 20, "資料不足", 20, 690, "#738387")
                    continue
                row = rows[index]
                text(x + 16, y + 5, f"{index + 1:02}  {_text(row.get('industry'))}", 24, 384)
                value = row.get("average_change_pct")
                value_color = change_color(value)
                text(x + 420, y + 7, _number(value, percent=True), 24, 140, value_color)
                draw.rounded_rectangle((x + 578, y + 20, x + 720, y + 28), radius=4, fill="#e7edeb")
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                    length = min(abs(value) / 10, 1) * 142
                    if length > 0:
                        draw.rectangle((x + 578, y + 20, x + 578 + length, y + 28), fill=value_color)
                text(x + 18, y + 40, f"漲 {_number(row.get('advance_count'))} / 跌 {_number(row.get('decline_count'))} · 上漲 {_number(row.get('positive_ratio'), ratio=True)}", 18, 420)
                representative = _stock({"stock_id": row.get("top_stock_id"), "stock_name": row.get("top_stock_name")})
                text(x + 452, y + 40, f"代表 {representative}", 18, 268)
        text(48, 955, "日線族群平均漲跌、A/D 與代表股沿用上游；長條滿格為 10%。", 18)
        strip = model.cross_market_strip
        for index, item in enumerate(strip.get("promoted", [])[:4]):
            x = 40 + index * 390
            draw.rounded_rectangle((x, 992, x + 370, 1075), radius=8, fill="#e1e8e7")
            text(x + 14, 1000, _text(item.get("label") or item.get("id")), 20, 342)
            text(x + 14, 1035, f"{_number(item.get('price'))} {_text(item.get('currency'))}  {_number(item.get('change_pct'), percent=True)}", 20, 342)
        if not strip.get("promoted"):
            text(48, 1016, "跨市場｜美國／加密資產暫無可用資料", 22)
        text(48, 1091, " · ".join(f"{g['label']} {g['status']}" for g in strip.get("groups", [])), 20)
        line(1130)
        text(48, 1148, f"品質：{display_status(model.quality).replace('（詳見附件）', '')}｜各項資料日期獨立；本報告僅供研究觀察。", 20)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_phase_dashboard(model, draw, text, line):
    """Structured phase view. All data comes from the detached selected model."""
    selection = model.phase_selection
    sections = _map(selection.get("sections"))
    slots = phase_dashboard_rows(model)
    muted = semantic_colors("missing")[0]
    warning = semantic_colors("warning")[0]

    def status(key):
        return _text(_map(sections.get(key)).get("status"))

    def stamp(row):
        # Price event time must not be replaced by a newer receipt/as_of.
        return _text(row.get("event_time") or row.get("as_of") or row.get("trade_date")
                     or row.get("observed_trade_date"))

    def freshness(row):
        return _text(_map(row.get("freshness")).get("status") or row.get("freshness_status")
                     or row.get("last_trade_recency") or row.get("status"))

    def card(x, y, width, height, fill="#ffffff"):
        draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=fill)

    index_label = {"preopen": "前一完成日官方收盤・歷史",
                   "intraday": "當日實際成交", "postclose": "當日官方收盤"}[model.phase]
    rows = _rows(model.indices.get("items"))
    for x, identity in ((40, "TAIEX"), (820, "TPEX")):
        row = next((item for item in rows if item.get("index_id") == identity), {})
        card(x, 130, 740, 128)
        text(x + 16, 136, f"{identity}｜{index_label}", 22, 708)
        text(x + 16, 165, index_summary(row), 32, 430, change_color(row.get("change_pct")))
        text(x + 465, 175, f"{status('index.' + identity)} / {freshness(row)}", 18, 257, muted)
        text(x + 16, 210, f"{stamp(row)} · authority={_text(row.get('authority'))}", 18, 708)
        text(x + 16, 234, f"{_text(row.get('source'))} · {_text(row.get('finalization'))}", 18, 708, muted)

    breadth, volume = model.breadth, model.volume
    card(40, 270, 740, 144)
    card(820, 270, 740, 144)
    label = "試撮廣度｜provisional・非正式成交" if model.phase == "preopen" else "市場廣度｜當日實際成交"
    if model.phase == "postclose":
        label = "市場廣度｜已完成時段・非官方定稿"
    text(56, 276, label, 22, 708)
    text(56, 306, f"漲 {_number(breadth.get('advance_count'))} / 跌 {_number(breadth.get('decline_count'))} / 平 {_number(breadth.get('unchanged_count'))}", 24, 708)
    text(56, 340, f"{status('breadth')} / {freshness(breadth)} · {stamp(breadth)}", 18, 708, muted)
    if model.phase == "postclose":
        for offset, venue in enumerate(("TWSE", "TPEX")):
            component = _map(model.breadth_by_market.get(venue))
            text(56, 364 + offset * 23,
                 f"{venue} {_text(component.get('finalization'))} · reconciliation={_text(_map(component.get('close_reconciliation')).get('status'))}"
                 f" · 漲 {_number(component.get('advance_count'))} / 跌 {_number(component.get('decline_count'))}", 18, 708, muted)
    else:
        text(56, 364, f"coverage {_number(breadth.get('coverage_count'))} / {_number(breadth.get('universe_count'))} · authority={_text(breadth.get('authority'))}", 18, 708, muted)
        text(56, 387, f"方向未分類 {_number(breadth.get('unknown_count'))}（含確認未成交 {_number(breadth.get('valid_no_trade_count'))}）· {_text(breadth.get('source'))}", 18, 708, muted)
    value = volume.get("current_cumulative_trade_value")
    volume_label = "當日累計成交值"
    if value is None and volume.get("available_cumulative_trade_value") is not None:
        value, volume_label = volume["available_cumulative_trade_value"], "可用部分成交值"
    text(836, 276, "試撮不代表正式成交值" if model.phase == "preopen" else volume_label, 22, 708)
    text(836, 306, _number(value, money=True), 24, 708, semantic_colors("flow")[0])
    text(836, 340, f"{status('volume')} / {freshness(volume)} · {stamp(volume)}", 18, 708, muted)
    text(836, 364, f"authority={_text(volume.get('trade_value_authority_status'))} · coverage={_text(volume.get('trade_value_coverage_status'))}", 18, 708, muted)
    text(836, 387, f"來源 {_text(volume.get('source'))}", 18, 708, muted)

    # Three compact ranking cards replace the generic chips area. Preopen keeps
    # historical leaders separate from indicative candidates and groups.
    candidates = _map(selection.get("candidates"))
    groups = _map(selection.get("groups"))
    daily_date = _text(selection.get("daily_sample_cap"))
    for index in range(3):
        x = 40 + index * 520
        card(x, 426, 500, 110)
        if model.phase == "preopen" and index == 2:
            rows = slots["groups"]
            row = rows[0] if rows else {}
            label = "試撮族群｜provisional"
            detail = f"{_text(row.get('group_name'))}  {_number(row.get('mean_return_pct'), percent=True)}"
            dated = f"{stamp(groups)} · {status('groups')} / {freshness(groups)}"
            note = "非正式成交；依上游選取順序"
        elif model.phase == "intraday" or model.phase == "preopen" and index == 1:
            offset = index if model.phase == "intraday" else 0
            rows = slots["candidates"]
            row = rows[offset] if offset < len(rows) else {}
            label = f"盤中候選 {offset + 1:02}｜actual" if model.phase == "intraday" else "試撮個股｜provisional"
            detail = f"{_stock(row)}  {_number(row.get('current_price'))}  {_number(row.get('change_pct'), percent=True)}"
            dated = f"{stamp(row) if row else stamp(candidates)} · {status('candidates')} / {freshness(candidates)}"
            note = ("非正式成交 · " if model.phase == "preopen" else "來源 ") + _text(_map(row.get("lineage")).get("source"))
        else:
            rows = slots["daily_leaders"]
            row = rows[index] if index < len(rows) else {}
            label = "歷史成交排行｜非即時" if model.phase == "preopen" else f"當日樣本成交排行 {index + 1:02}"
            detail = f"{_stock(row)}  {_number(row.get('change_pct'), percent=True)}"
            dated = f"{daily_date} · {status('daily_rankings')}"
            note = f"成交 {_number(row.get('trade_value'), money=True)} · 非全市場定稿"
        text(x + 14, 430, label, 20, 472)
        text(x + 14, 457, detail, 22, 472, change_color(row.get("mean_return_pct") if model.phase == "preopen" and index == 2 else row.get("change_pct")))
        text(x + 14, 487, dated, 18, 472, muted)
        text(x + 14, 511, note, 18, 472, muted)

    intraday = model.phase == "intraday"
    for column, (key, label) in enumerate((("strong", "強勢族群"), ("weak", "弱勢族群"))):
        x = 40 + column * 780
        rows = slots["sectors"].get(key, [])[:6]
        if intraday:
            label = "盤中族群｜正向／平盤／未定" if key == "strong" else "盤中族群｜負向"
            context = f"{stamp(groups)} · {status('groups')} / {freshness(groups)}"
        else:
            label = ("歷史樣本・" if model.phase == "preopen" else "當日樣本・") + label
            context = f"{daily_date} · {status('daily_rankings')} · {freshness(model.sample_coverage)}；非即時排行"
        text(x + 10, 548, label, 24, 600, semantic_colors("strength" if key == "strong" else "weakness")[0])
        text(x + 650, 554, f"{len(rows)} / 6", 18, 80, muted)
        text(x + 10, 582, context, 18, 720, muted)
        for index in range(6):
            y = 610 + index * 62
            card(x, y, 740, 56)
            if index >= len(rows):
                text(x + 16, y + 14, f"— 無其他已選取族群 · {status('groups' if intraday else 'daily_rankings')}", 18, 708, muted)
                continue
            row = rows[index]
            value = row.get("average_change_pct")
            color = change_color(value)
            text(x + 16, y + 1, f"{row.get('rank', index + 1):02}  {_text(row.get('industry'))}", 22, 375)
            text(x + 410, y + 1, _number(value, percent=True), 22, 140, color)
            # A fixed, zero-centered +/-10% scale; never derive rank or returns.
            draw.rounded_rectangle((x + 574, y + 15, x + 724, y + 23), radius=4, fill="#e7edeb")
            draw.line((x + 649, y + 11, x + 649, y + 27), fill="#a6b4b4", width=1)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                length = min(abs(value) / 10, 1) * 75
                if length:
                    left, right = (649 - length, 649) if value < 0 else (649, 649 + length)
                    draw.rectangle((x + left, y + 15, x + right, y + 23), fill=color)
            detail = f"漲 {_number(row.get('advance_count'))} / 跌 {_number(row.get('decline_count'))} · 上漲 {_number(row.get('positive_ratio'), ratio=True)}"
            text(x + 16, y + 31, detail, 18, 470)
            if intraday:
                note = f"{freshness(row)} · 覆蓋 {_number(row.get('coverage_ratio'), ratio=True)}"
            else:
                note = f"代表 {_stock({'stock_id': row.get('top_stock_id'), 'stock_name': row.get('top_stock_name')})}"
            text(x + 488, y + 31, note, 18, 236, muted)

    text(48, 983, "跨市場｜獨立日期與狀態" + ("・隔夜基準" if model.phase == "preopen" else ""), 18, 600)
    text(660, 983, "族群保留上游順位；按正負分欄，非全市場強弱榜；長條 ±10%。" if intraday else
         "日線樣本強弱榜；非官方全市場定稿；長條 ±10%。", 18, 892, muted)
    promoted = _rows(model.cross_market_strip.get("promoted"))
    # Reserve three US slots and one crypto slot even when evidence is absent.
    us_rows = [row for row in promoted if row.get("group") == "us"]
    cross_slots = [us_rows[index] if index < len(us_rows) else {} for index in range(3)]
    cross_slots.append(next((row for row in promoted if row.get("group") == "crypto"), {}))
    for index, row in enumerate(cross_slots):
        x = 40 + index * 390
        card(x, 1012, 370, 126, "#e1e8e7")
        group = "us" if index < 3 else "crypto"
        label = _text(row.get("label") or row.get("id")) if row else (f"美國 {index + 1}" if group == "us" else "加密資產")
        text(x + 12, 1016, label, 20, 346)
        text(x + 12, 1043, f"{_number(row.get('price'))} {_text(row.get('currency'))}  {_number(row.get('change_pct'), percent=True)}", 20, 346, change_color(row.get("change_pct")))
        text(x + 12, 1071, stamp(row), 18, 346, muted)
        absent = next((item.get("status") for item in model.cross_market_strip.get("groups", []) if item.get("group") == group), "unavailable")
        text(x + 12, 1093, f"{freshness(row) if row else absent} · authority={_text(row.get('authority'))}", 18, 346, muted)
        text(x + 12, 1112, ("末分鐘收盤；非官方／日線修訂待確認"
            if row.get("evidence_kind") == "finalized_regular_interval_close"
            else f"來源 {_text(row.get('source'))}"), 18, 346, muted)
    line(1148)
    text(48, 1151, f"品質 {model.quality} · {len(model.full_limitations.get('warnings', []))} 項提醒 / {len(model.full_limitations.get('missing', []))} 項缺漏；partial 非完整市場，各卡日期獨立。", 18, 1504, warning)
    note = ("盤前預期回顧 unavailable；缺不可變快照。session_final 不等於官方 final，各項發布獨立。" if model.phase == "postclose" else
            "歷史排行與同日試撮分開；試撮非正式成交，隔夜末分鐘收盤另標限制。" if model.phase == "preopen" else
            "盤中只列當日合格 actual evidence；未選取的資料保留 pending，不以昨日日線補位。")
    text(48, 1174, note + " 僅供研究觀察。", 18, 1504, muted)
