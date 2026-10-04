"""Text projection of dispatch preview evidence; no IO or market calculations."""
from __future__ import annotations

from datetime import date
from app.dispatch.market_report_presentation import (
    MarketReportPresentation, PHASE_LABELS, build_presentation, daily_sample_scope,
    report_limitations, _map, _rows, _text, _number, _stamp, _stock,
)


def _index_lines(indices: dict) -> list[str]:
    rows = _rows(indices.get("items"))
    lines = []
    for identity, label in (("TAIEX", "加權指數"), ("TPEX", "櫃買指數")):
        row = next((item for item in rows if item.get("index_id") == identity), {})
        freshness = _map(row.get("freshness"))
        lines.append(
            f"- {identity} {label}：{_number(row.get('value'))}｜漲跌 {_number(row.get('change'))} / "
            f"{_number(row.get('change_pct'), percent=True)}｜status={_text(freshness.get('status'))}｜"
            f"{_text(row.get('quote_semantics'))}｜{_stamp(row)}"
        )
        if row:
            lines.append(
                f"  定稿={_text(row.get('finalization'))}｜authority={_text(row.get('authority'))}｜"
                f"官方收盤確認={_text(row.get('official_close_confirmed'))}｜"
                f"canonical session 可用={_text(row.get('current_for_requested_session'))}"
            )
            official = _map(row.get("official_close"))
            if official.get("value") is not None:
                lines.append(
                    f"  官方收盤參考：{_number(official.get('value'))}｜"
                    f"{_number(official.get('change_pct'), percent=True)}｜{_stamp(official)}"
                )
    return lines


def _breadth_line(label: str, row: dict) -> str:
    return (
        f"- {label}：上漲 {_number(row.get('advance_count'))} / 下跌 {_number(row.get('decline_count'))} / "
        f"平盤 {_number(row.get('unchanged_count'))}｜上漲占比 {_number(row.get('positive_ratio'), ratio=True)}｜"
        f"總數 {_number(row.get('total_count'))}｜覆蓋 {_number(row.get('coverage_count'))}/"
        f"{_number(row.get('universe_count'))}（{_number(row.get('coverage_ratio'), ratio=True)}）"
    )


def _pace_line(volume: dict, days: int) -> str:
    baseline = _map(volume.get(f"same_time_baseline_{days}d"))
    return (
        f"- {days}d 同時點量速：{_number(baseline.get('pace_ratio'))} 倍｜"
        f"樣本 {_number(baseline.get('sample_days'))}/{days} 日｜"
        f"readiness={_text(baseline.get('readiness_status') or baseline.get('status') or volume.get('baseline_readiness_status'))}｜"
        f"pace_status={_text(baseline.get('pace_ratio_status'))}"
    )


def _industry(row: dict) -> str:
    return (
        f"{_text(row.get('industry'))}｜平均 {_number(row.get('average_change_pct'), percent=True)}｜"
        f"上漲/下跌 {_number(row.get('advance_count'))}/{_number(row.get('decline_count'))}｜"
        f"代表 {_text(row.get('top_stock_id'))} {_text(row.get('top_stock_name'))}"
    )


def _rank_lines(rows: list[dict]) -> list[str]:
    return [
        f"- {_stock(row)}｜{_number(row.get('change_pct'), percent=True)}｜"
        f"收盤 {_number(row.get('close_price') if row.get('close_price') is not None else row.get('close'))}｜"
        f"成交值 {_number(row.get('trade_value'), money=True)}"
        for row in rows[:8]
    ] or ["- missing：本地日線樣本不足"]


def _chips_lines(chips: dict) -> list[str]:
    official = _map(chips.get("official_market_aggregate"))
    lines = [f"- 籌碼整體 status={_text(chips.get('status'))}；各資料各自發布，日期不可合併。",
             f"- 官方市場彙總：status={_text(official.get('status'))}｜scope={_text(official.get('scope'))}"]
    for row in _rows(official.get("rows"))[:2]:
        freshness = next((item for item in _rows(official.get("freshness"))
                          if item.get("index_id") == row.get("index_id")), {})
        lines.append(
            f"  {_text(row.get('index_id'))}｜{_stamp(row)}｜來源等級={_text(row.get('source_grade'))}｜"
            f"status={_text(freshness.get('status'))}｜發布={_text(freshness.get('release_status'))}｜"
            f"三大法人淨額 {_number(row.get('total_institutional_net_value'), money=True)}｜"
            f"外資 {_number(row.get('foreign_investor_net_value'), money=True)}｜"
            f"投信 {_number(row.get('investment_trust_net_value'), money=True)}｜"
            f"自營商 {_number(row.get('dealer_net_value'), money=True)}"
        )
    for key, label, fields in (
        ("institutional_per_stock", "個股法人", (("foreign_investor_net", "外資淨股數"),
          ("investment_trust_net", "投信淨股數"), ("total_institutional_net", "法人合計淨股數"))),
        ("margin_per_stock", "融資融券", (("margin_balance", "融資餘額"),
          ("margin_balance_change", "融資增減"), ("short_balance_change", "融券增減"))),
    ):
        block = _map(chips.get(key))
        aggregate = _map(block.get("aggregate"))
        coverage = _map(block.get("coverage"))
        lines.append(f"- {label}：status={_text(block.get('status'))}｜{_stamp(block)}｜"
                     f"普通股 canonical coverage {_number(coverage.get('covered_eligible_count'))}/"
                     f"{_number(coverage.get('eligible_count'))} "
                     f"（{_number(coverage.get('coverage_ratio'), ratio=True)}；非全市場保證）｜"
                     f"母體類別 universe_class={_text(coverage.get('universe_class'))}｜"
                     f"母體外來源代碼 {_number(coverage.get('out_of_universe_source_count'))} 檔")
        facts = [f"{name} {_number(aggregate[field])}" for field, name in fields if aggregate.get(field) is not None]
        if facts:
            lines.append("  " + "｜".join(facts))
        if key == "institutional_per_stock":
            for ranking, title in (("top_net_buy", "淨買前列"), ("top_net_sell", "淨賣前列")):
                for row in _rows(block.get(ranking))[:2]:
                    lines.append(f"  {title}：{_stock(row)}｜法人淨股數 {_number(row.get('total_institutional_net'))}")
    lines.append("- missing / partial / unreleased 代表資料缺口或發布未齊；不可視為零或當日完整籌碼。")
    return lines


def _cross_lines(context: dict) -> list[str]:
    lines = [f"- 輔助背景｜status={_text(context.get('status'))}；只讀既有快取，各資產依自己的 as_of。"]
    markets = _map(context.get("markets"))
    for market, label in (("us", "美國"), ("jp", "日本"), ("kr", "韓國"),
                          ("resource", "原物料"), ("crypto", "加密資產")):
        block = _map(markets.get(market))
        lines.append(f"- {label}：status={_text(block.get('status'))}")
        for row in _rows(block.get("assets"))[:3]:
            lines.append(f"  {_text(row.get('label') or row.get('id'))}｜{_number(row.get('price'))} "
                         f"{_text(row.get('currency'))}｜{_number(row.get('change_pct'), percent=True)}｜"
                         f"as_of={_text(row.get('as_of'))}｜status={_text(row.get('status'))}")
    return lines


def render_sections(preview: dict, *, phase: str, report_date: date) -> str:
    return render_model_sections(build_presentation(preview, phase=phase, report_date=report_date))


def render_model_sections(model: MarketReportPresentation) -> str:
    phase = model.phase
    breadth = model.breadth
    distribution = model.distribution
    volume = model.volume
    sample = model.daily_sample_scope
    coverage = model.sample_coverage
    strong = model.strong_sectors
    weak = model.weak_sectors
    leaders = model.value_leaders
    indices = _index_lines(model.indices)
    volume_head = (f"- 累計成交值：{_number(volume.get('current_cumulative_trade_value'), money=True)}｜"
                   f"可用部分 {_number(volume.get('available_cumulative_trade_value'), money=True)}｜"
                   f"as_of={_text(volume.get('as_of'))}｜status={_text(volume.get('status'))}")
    distribution_head = (f"- 漲停/跌停門檻樣本 {_number(distribution.get('limit_up_count'))}/{_number(distribution.get('limit_down_count'))}｜"
                         f"大漲/大跌 {_number(distribution.get('strong_up_count'))}/{_number(distribution.get('strong_down_count'))}")
    lines = ["## 一眼看盤", f"- 市場 stance：{model.stance}（依廣度證據）｜"
             f"as_of={_text(breadth.get('as_of') or breadth.get('trade_date'))}｜status={_text(breadth.get('status'))}",
             *[line for line in indices if line.startswith('- ')], _breadth_line("市場廣度", breadth),
             volume_head, _pace_line(volume, 5), _pace_line(volume, 20),
             f"{distribution_head}｜{sample}",
             f"- 族群（日線）：強勢端 {_industry(strong[0]) if strong else 'missing'}；"
             f"弱勢端 {_industry(weak[0]) if weak else 'missing'}｜{sample}",
             f"- 成交焦點：{_stock(leaders[0]) if leaders else 'missing'}｜{sample}",
             "", "## 指數與盤勢", *indices,
             "- official_close / latest_completed_session 為已完成交易日；delayed / stale 不代表即時。",
             "", "## 量能與成交", volume_head,
             f"- 比較分鐘 {_text(volume.get('comparison_minute'))}｜1 分鐘成交增量 {_number(volume.get('one_minute_trade_value_change'), money=True)}｜{_stamp(volume)}",
             _pace_line(volume, 5), _pace_line(volume, 20),
             f"- authority={_text(volume.get('trade_value_authority_status'))}｜coverage={_text(volume.get('trade_value_coverage_status'))}｜"
             f"semantics={_text(volume.get('current_trade_value_semantics'))}",
             f"- 估算部分 {_number(volume.get('estimated_cumulative_trade_value'), money=True)}｜"
             f"估算方法={_text(volume.get('trade_value_estimate_method'))}；available 部分不可當完整合計。",
             f"- 成交值排行見「焦點股與成交值」：{sample}。",
             "", "## 市場廣度與漲跌結構", _breadth_line("合計", breadth),
             f"- {_stamp(breadth)}｜status={_text(breadth.get('status'))}｜scope={_text(breadth.get('scope'))}｜"
             f"session={_text(breadth.get('market_session'))} / {_text(breadth.get('session_semantics'))}"]
    for market in ("TWSE", "TPEX"):
        row = _map(model.breadth_by_market.get(market))
        lines.extend([_breadth_line(str(market), row), f"  {_stamp(row)}｜status={_text(row.get('status'))}"])
    lines.extend([f"- 漲跌分布：{sample}（日漲跌幅門檻樣本，非全市場即時法定漲跌停統計）", distribution_head,
                  f"- 小漲/平盤/小跌 {_number(distribution.get('mild_up_count'))}/{_number(distribution.get('flat_count'))}/{_number(distribution.get('mild_down_count'))}",
                  "", "## 族群輪動", f"- {sample}；非盤中族群排行。"])
    for label, rows in (("強勢端", strong), ("弱勢端", weak)):
        lines.extend([f"- {label}：{_industry(row)}" for row in rows[:6]] or [f"- {label}：missing"])
    lines.extend(["", "## 焦點股與成交值", f"- {sample}。",
                  f"- 日線樣本覆蓋 {_number(coverage.get('sample_count'))}/{_number(coverage.get('universe_count'))}｜"
                  f"{_number(coverage.get('coverage_ratio'), ratio=True)}｜status={_text(coverage.get('status'))}",
                  "- 本派報未納入當日盤中個股排行；以下僅為已取得的日線樣本。"])
    for key, title in (("top_gainers", "漲幅前列"), ("top_losers", "跌幅前列"), ("value_leaders", "成交值前列")):
        lines.extend([f"### {title}｜{sample}", *_rank_lines(getattr(model, key))])
    lines.extend(["", "## 籌碼", *_chips_lines(model.chips),
                  "", "## 跨市場背景", *_cross_lines(model.cross_market),
                  "", "## 本時段觀察 / 下一時段觀察"])
    observations = {
        "preopen": [f"盤前先看隔夜跨市場背景的各自日期；族群與個股依 {sample}，不能當作開盤後表現。",
                    "09:00 後確認指數是否已有本交易日證據，再核對廣度與同時點量速；尚未更新者維持 missing / stale。"],
        "intraday": ["盤中交叉確認指數漲跌、廣度與 5d/20d 量速是否一致；不同日期、partial 或 warming_up 不足以判定同向。",
                     f"族群方向仍取自 {sample}；須待同時段證據才能確認是否延續或分歧。",
                     "下一次檢查廣度是否持續、量速基準是否可用、成交焦點是否有當日證據；日線前列只作待確認名單。"],
        "postclose": ["盤後並列核對官方收盤確認、廣度、樣本漲跌分布、族群與成交前列；各自日期與定稿狀態仍以所在區塊為準。",
                      "下一交易時段先確認廣度是否支撐焦點股，再檢查成交是否集中於少數標的，並分開觀察強弱族群。",
                      "若籌碼尚未發布或日期未齊，待既有資料更新後再檢查；不把未發布當作沒有變化。"],
    }
    lines.extend(f"- {line}" for line in observations[phase])
    for item in model.stock_analysis:
        blockers = item.get("technical_blockers", [])
        if blockers:
            lines.extend([f"### {_stock(item)}｜技術輸入限制", *[f"- {reason}" for reason in blockers]])
    warnings, missing = model.full_limitations["warnings"], model.full_limitations["missing"]
    lines.extend(["", "## 資料品質與限制",
                  "- 廣度依 canonical 市場證據；排行、族群與漲跌分布依本地日線樣本；跨市場僅為輔助背景，不共用單一資料時鐘。",
                  "- 跨市場 stale / missing 不可當作本時段確認；個股籌碼使用 canonical 普通股母體，不代表 ETF、權證或全證券市場。",
                  "- 派報 phase 是觸發時段，不代表底層證據已更新、即時或定稿；本報告為觀察清單，無價格預測或買賣建議。"])
    # A detail present on both axes remains visible once, with both labels.
    lines.extend(f"- {'warning / missing' if item in missing else 'warning'}: {item}" for item in warnings)
    lines.extend(f"- missing: {item}" for item in missing if item not in warnings)
    if not warnings and not missing:
        lines.append("- canonical preview 未回報額外 warnings / missing；欄位缺值仍標為 missing。")
    return "\n".join(lines)


def render_presentation(model: MarketReportPresentation) -> str:
    warnings, missing = model.full_limitations["warnings"], model.full_limitations["missing"]
    lines = [f"# {model.header}",
             f"派報時段：{PHASE_LABELS[model.phase]}（{model.phase}）｜Asia/Taipei",
             f"as_of：{model.as_of}",
             f"證據 session：{_text(model.session.get('market_session'))} / {_text(model.session.get('session_semantics'))}",
             f"資料品質：{model.quality}｜{len(warnings)} warnings｜{len(missing)} missing",
             "", render_model_sections(model)]
    lines.extend(f"- 呈現提醒：{warning}" for warning in model.presentation_warnings)
    return "\n".join(lines)
