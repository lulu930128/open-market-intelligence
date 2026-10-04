"""Pillow drawing of detached presentation fields; no technical calculations."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from math import isfinite

from app.dispatch.market_report_presentation import (
    MarketReportPresentation, _map, _rows, _number, _text, _stock,
    coverage_summary, display_status, index_summary,
)


class ChartUnavailable(RuntimeError):
    """Safe, presentation-only failure; callers may omit the PNG."""


FONT_PATHS = (
    "C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/msjhbd.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def render_market_dashboard_chart(model: MarketReportPresentation) -> bytes:
    return _render_png(model, stock=False)


def render_stock_analysis_chart(model: MarketReportPresentation) -> bytes:
    return _render_png(model, stock=True)


def _render_png(model: MarketReportPresentation, *, stock: bool) -> bytes:
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
    dimensions = (1600, 1600) if stock else (1600, 1200)
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
             f"  {_number(row.get('distance_pct'), percent=True)}", 20, 686)

    draw.rectangle((0, 0, 1600, 118), fill="#173e4b")
    text(48, 18, "個股分析板" if stock else "市場＋族群總覽", 38, 450, "#ffffff")
    text(530, 29, model.header, 24, 1022, "#d4e4e7")
    text(48, 77, f"資料時間 {model.as_of}｜{model.daily_sample_scope}", 20, 1504, "#d4e4e7")

    if stock:
        items = model.stock_analysis
        for index in range(8):
            x = 40 + (index % 2) * 780
            y = 140 + (index // 2) * 350
            draw.rounded_rectangle((x, y, x + 740, y + 332), radius=12, fill="#ffffff")
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
            text(x + 24, y + 55, "  ·  ".join(quote) if quote else "行情暫未提供", 22, 686, "#536d74")
            for slot, reason in enumerate(item.get("reason_tags", [])[:3]):
                bx = x + 24 + slot * 220
                draw.rounded_rectangle((bx, y + 93, bx + 210, y + 125), radius=5, fill="#e8efed")
                text(bx + 12, y + 96, reason, 18, 186)
            if not item.get("technical_available"):
                text(x + 24, y + 153, "技術位置暫不可用", 22, 686, "#738387")
                for slot, reason in enumerate(item.get("technical_blockers", [])[:3]):
                    text(x + 24, y + 194 + slot * 36, reason, 18, 686, "#738387")
                continue
            reference = _map(item.get("reference"))
            text(x + 24, y + 137, f"參考 {_number(reference.get('price'))} · 已完成日線 {_text(reference.get('trade_date'))}", 20, 686)
            zone(x + 24, y + 169, "最近支撐候選", _map(item.get("support")))
            zone(x + 24, y + 198, "最近壓力候選", _map(item.get("resistance")))
            text(x + 24, y + 231, item.get("headline") or "技術摘要未提供", 22, 686)
            observe = _map(item.get("observe"))
            if observe:
                threshold = observe.get("threshold_price")
                text(x + 24, y + 266, f"觀察｜{observe.get('label') or ''}", 20, 490, "#536d74")
                if threshold is not None:
                    text(x + 532, y + 266, _number(threshold), 20, 178, "#536d74")
                text(x + 24, y + 294, observe.get("result_summary") or "", 18, 686, "#536d74")
            else:
                text(x + 24, y + 271, "觀察條件暫未提供", 20, 686, "#738387")
        text(48, 1551, "依來源順序列示；支撐／壓力為上游研究候選區，非價格預測或交易指令。", 20)
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
            ("strong", "強勢族群", "#ad493d"), ("weak", "弱勢族群", "#237766"),
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
                text(x + 420, y + 7, _number(row.get("average_change_pct"), percent=True), 24, 140, color)
                value = row.get("average_change_pct")
                draw.rounded_rectangle((x + 578, y + 20, x + 720, y + 28), radius=4, fill="#e7edeb")
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                    length = min(abs(value) / 10, 1) * 142
                    if length > 0:
                        draw.rectangle((x + 578, y + 20, x + 578 + length, y + 28), fill=color)
                text(x + 18, y + 40, f"漲 {_number(row.get('advance_count'))} / 跌 {_number(row.get('decline_count'))}", 18, 265)
                representative = _stock({"stock_id": row.get("top_stock_id"), "stock_name": row.get("top_stock_name")})
                text(x + 296, y + 40, f"代表 {representative}", 18, 424)
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
