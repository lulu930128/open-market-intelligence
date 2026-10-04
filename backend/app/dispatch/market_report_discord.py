"""Bounded Discord projection of the presentation model; no market reads."""
from __future__ import annotations

from app.dispatch.market_report_presentation import (
    MarketReportPresentation, _map, _rows, _number, _text, _stock,
    coverage_summary, display_status, index_summary,
)


def _clip(value: str, units: int) -> str:
    # UTF-16 is conservative for Discord, including supplementary characters.
    if len(value.encode("utf-16-le")) // 2 <= units:
        return value
    return value.encode("utf-16-le")[:(units - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def _field(name: str, value: str) -> dict:
    return {"name": _clip(name, 80), "value": _clip(value or "資料不足", 650), "inline": False}


def _dated(row: dict) -> str:
    return _text(row.get("as_of") or row.get("trade_date"))


def _sectors(rows: list[dict]) -> str:
    return "\n".join(f"{_clip(_text(row.get('industry')), 40)}  {_number(row.get('average_change_pct'), percent=True)}"
                     for row in rows[:3]) or "資料不足"


def render_compact_content(model: MarketReportPresentation) -> str:
    """Reader summary only; detailed diagnostics remain available in audit mode."""
    rows = _rows(model.indices.get("items"))
    lines = [f"**{model.header}**"]
    for identity in ("TAIEX", "TPEX"):
        row = next((item for item in rows if item.get("index_id") == identity), {})
        status = display_status(_map(row.get("freshness")).get("status")).replace("（詳見附件）", "")
        lines.append(f"{identity}  {index_summary(row)} · {status}")
    breadth = model.breadth
    lines.append(f"廣度｜漲 {_number(breadth.get('advance_count'))}／跌 {_number(breadth.get('decline_count'))}"
                 f"／平 {_number(breadth.get('unchanged_count'))}")
    value = model.volume.get("current_cumulative_trade_value")
    label = "成交值"
    if value is None and model.volume.get("available_cumulative_trade_value") is not None:
        value = model.volume["available_cumulative_trade_value"]
        label = "可用部分成交值"
    lines.append(f"{label}｜{_number(value, money=True)}")
    official = _rows(_map(model.chips.get("official_market_aggregate")).get("rows"))
    amounts = []
    for identity in ("TWSE", "TPEX"):
        identities = {"TWSE", "TAIEX"} if identity == "TWSE" else {"TPEX"}
        row = next((item for item in official if item.get("index_id") in identities), {})
        # Dates are meaningful here: institutional releases can lag price evidence.
        stamp = f"（{_clip(str(row['trade_date']), 10)}）" if row.get("trade_date") else ""
        amounts.append(f"{identity} {_number(row.get('total_institutional_net_value'), money=True)}{stamp}")
    lines.append("官方法人淨額｜" + "／".join(amounts))
    quality = display_status(model.quality).replace("（詳見附件）", "")
    limits = "；部分資料缺漏或受限" if any(model.full_limitations.values()) else ""
    lines.append(f"品質｜{quality}{limits}；日線族群非即時，各項資料日期獨立。")
    return _clip("\n".join(lines).replace("missing", "資料不足"), 1900)


def render_embeds(model: MarketReportPresentation, *, png_filename: str | None = None) -> list[dict]:
    indices = _rows(model.indices.get("items"))
    index_lines = []
    for identity in ("TAIEX", "TPEX"):
        row = next((row for row in indices if row.get("index_id") == identity), {})
        index_lines.append(f"{identity}  {index_summary(row)}\n"
                           f"{display_status(_map(row.get('freshness')).get('status'))} · {_dated(row)}")
    breadth = model.breadth
    volume = model.volume
    volume_label = "累計成交值"
    volume_value = volume.get("current_cumulative_trade_value")
    if volume_value is None and volume.get("available_cumulative_trade_value") is not None:
        volume_label = "可用部分累計成交值"
        volume_value = volume["available_cumulative_trade_value"]
    summary = {
        "title": _clip(model.header, 200),
        "description": _clip(f"資料時間 {model.as_of}\n{display_status(model.session.get('market_session'))} / "
                             f"{display_status(model.session.get('session_semantics'))}｜{model.stance}", 400),
        "color": 0x226B80,
        "fields": [_field("指數", "\n".join(index_lines)),
                   _field("市場廣度", f"上漲 {_number(breadth.get('advance_count'))} / 下跌 {_number(breadth.get('decline_count'))} / "
                          f"平盤 {_number(breadth.get('unchanged_count'))}\n"
                          f"覆蓋 {_number(breadth.get('coverage_ratio'), ratio=True)} · {display_status(breadth.get('status'))} · {_dated(breadth)}"),
                   _field(volume_label, f"{_number(volume_value, money=True)}\n"
                          f"{display_status(volume.get('status'))} · {_dated(volume)}")],
    }
    if png_filename:
        summary["image"] = {"url": f"attachment://{png_filename}"}
    focus = {
        "title": "族群／成交焦點", "color": 0x226B80,
        "description": _clip(model.daily_sample_scope, 160),
        "fields": [_field("強勢族群", _sectors(model.strong_sectors)),
                   _field("弱勢族群", _sectors(model.weak_sectors)),
                   _field("成交值前列", "\n".join(
                       f"{_clip(_stock(row), 60)}  {_number(row.get('change_pct'), percent=True)} · {_number(row.get('trade_value'), money=True)}"
                       for row in model.value_leaders[:3]))],
    }
    official = _map(model.chips.get("official_market_aggregate"))
    official_lines = []
    for row in _rows(official.get("rows"))[:2]:
        freshness = next((item for item in _rows(official.get("freshness")) if item.get("index_id") == row.get("index_id")), {})
        official_lines.append(f"{_text(row.get('index_id'))}  {_number(row.get('total_institutional_net_value'), money=True)}\n"
                              f"{_dated(row)} · {display_status(freshness.get('status'))}")
    chips_fields = [_field("官方三大法人淨額", "\n".join(official_lines) or "資料不足")]
    for key, label in (("institutional_per_stock", "個股法人"), ("margin_per_stock", "融資融券")):
        block = _map(model.chips.get(key))
        lines = [coverage_summary(block), f"{_dated(block)} · {display_status(block.get('status'))}"]
        if key == "margin_per_stock":
            aggregate = _map(block.get("aggregate"))
            lines.append(f"融資增減 {_number(aggregate.get('margin_balance_change'))}；融券增減 {_number(aggregate.get('short_balance_change'))}")
        else:
            for ranking, name in (("top_net_buy", "淨買"), ("top_net_sell", "淨賣")):
                lines.extend(f"{name} {_clip(_stock(row), 60)}：{_number(row.get('total_institutional_net'))} 股"
                             for row in _rows(block.get(ranking))[:1])
        chips_fields.append(_field(label, "\n".join(lines)))
    chips = {"title": "籌碼", "description": "各項資料獨立發布；普通股覆蓋不代表全市場。", "color": 0x226B80, "fields": chips_fields}
    cross_fields = []
    for group in model.cross_market_groups.values():
        label = group["label"]
        cross_lines = []
        if group["stale"]:
            cross_lines.append("已過期資料詳見附件")
        for row in group["promoted"][:1]:
            cross_lines.append(f"{_clip(_text(row.get('label') or row.get('id')), 30)} "
                               f"{_number(row.get('price'))} {_text(row.get('currency'))} {_number(row.get('change_pct'), percent=True)}\n"
                               f"{_dated(row)} · {display_status(row.get('status'))}")
        if not group["promoted"] and not group["stale"]:
            cross_lines.append("資料不足，詳見附件")
        cross_fields.append(_field(label, "\n".join(cross_lines)))
    quality = {"title": "跨市場／資料品質", "color": 0x226B80,
               "fields": [*cross_fields, _field("資料限制", "\n".join(model.compact_limitations)),
                          _field("呈現狀態", "\n".join(model.presentation_warnings) or "完整文字與證據見附件")],
               "footer": {"text": f"資料品質：{display_status(model.quality)}｜各市場使用自己的資料時間"}}
    embeds = [summary, focus, chips, quality]
    # A per-embed budget guarantees <= 5,800 aggregate units, even for hostile
    # labels. Truncated detail remains in the complete TXT / evidence attachments.
    for embed in embeds:
        budget = 1450
        for key in ("title", "description"):
            if key in embed:
                embed[key] = _clip(embed[key], min(400 if key == "description" else 200, budget))
                budget -= len(embed[key].encode("utf-16-le")) // 2
        footer = embed.get("footer", {}).get("text", "")
        budget -= len(footer.encode("utf-16-le")) // 2
        fields = embed.get("fields", [])
        for index, field in enumerate(fields):
            budget -= len(field["name"].encode("utf-16-le")) // 2
            # Reserve space for remaining names and values.
            limit = max(1, (budget - 80 * (len(fields) - index - 1)) // (len(fields) - index))
            field["value"] = _clip(field["value"], min(650, limit))
            budget -= len(field["value"].encode("utf-16-le")) // 2
    return embeds
