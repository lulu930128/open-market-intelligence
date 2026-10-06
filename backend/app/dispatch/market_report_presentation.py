"""Pure presentation of one canonical preview; no acquisition or market calculations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from math import isfinite
from typing import Any
import re

PHASE_LABELS = {"preopen": "盤前", "intraday": "盤中", "postclose": "盤後"}
MARKET_LABELS = {"us": "美國", "jp": "日本", "kr": "韓國", "resource": "原物料", "crypto": "加密資產"}

# Literal explanations of selection evidence, not inferred market signals.
SELECTION_ROLE_LABELS = {
    "成交前列": "成交焦點", "漲幅前列": "上漲異動", "跌幅前列": "下跌異動",
    "法人淨買": "法人買超焦點", "法人淨賣": "法人賣超焦點",
    "強族群代表": "強勢族群代表", "弱族群代表": "弱勢族群代表",
    "子產業代表": "科技子產業代表",
}


def selection_role(reason_tags: list[str]) -> str:
    return "／".join(SELECTION_ROLE_LABELS[tag] for tag in reason_tags if tag in SELECTION_ROLE_LABELS) or "入選依據未提供"

def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value) if value is not None and value != "" else "missing"


def _number(value: Any, *, percent: bool = False, ratio: bool = False, money: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return "missing"
    if ratio:
        return f"{value * 100:.1f}%"
    if percent:
        return f"{value:+.2f}%"
    if money:
        return f"{value / 100_000_000:,.2f} 億元" if abs(value) >= 100_000_000 else f"{value:,.0f} 元"
    return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"


def _stamp(row: dict) -> str:
    return f"trade_date={_text(row.get('trade_date'))}｜as_of={_text(row.get('as_of') or row.get('event_time'))}"


def _stock(row: dict) -> str:
    return " ".join(str(row[key]) for key in ("stock_id", "stock_name") if row.get(key)) or "missing"


def daily_sample_scope(metadata: dict, report_date: date) -> str:
    value = metadata.get("latest_trade_date")
    try:
        sample_date = date.fromisoformat(str(value))
    except ValueError:
        return "日線樣本日期 missing（不可判定為本交易日）"
    if sample_date < report_date:
        return f"前一已完成交易日樣本（{sample_date}）"
    if sample_date == report_date:
        return f"本交易日日線樣本（{sample_date}；非即時排行）"
    return f"日線樣本（{sample_date}；晚於報告日期，不作當時證據）"


def report_limitations(preview: dict) -> tuple[list[str], list[str]]:
    """Keep upstream detail, including nested axes, once in the final section."""
    warnings: list[str] = []
    missing: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, items in value.items():
                if key in {"warnings", "limitations", "missing"} and isinstance(items, list):
                    target = missing if key == "missing" else warnings
                    for item in items:
                        if isinstance(item, str) and item.strip() and item not in target:
                            target.append(item)
                elif isinstance(items, (dict, list)):
                    visit(items)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit({"warnings": preview.get("warnings"), "missing": preview.get("missing"),
           "metadata": preview.get("metadata")})
    return warnings, missing



def _evidence(value: Any) -> Any:
    """Copy JSON evidence, dropping configuration/credential keys defensively."""
    if isinstance(value, dict):
        return {key: _evidence(item) for key, item in value.items()
                if isinstance(key, str) and not any(part in key.lower() for part in
                    ("secret", "token", "password", "webhook", "credential", "config", "api_key", "authorization"))}
    if isinstance(value, (list, tuple)):
        return [_evidence(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"https?://(?:\w+\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/[^\s\"<>]+",
                      "[redacted webhook]", value)
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value if value is None or isinstance(value, (int, float, bool)) else None


@dataclass(frozen=True)
class MarketReportPresentation:
    phase: str
    report_date: str
    header: str
    as_of: str
    session: dict
    quality: str
    stance: str
    indices: dict
    breadth: dict
    breadth_by_market: dict
    volume: dict
    distribution: dict
    daily_sample_scope: str
    sample_coverage: dict
    strong_sectors: list[dict]
    weak_sectors: list[dict]
    value_leaders: list[dict]
    top_gainers: list[dict]
    top_losers: list[dict]
    chips: dict
    cross_market: dict
    cross_market_groups: dict
    compact_limitations: list[str]
    full_limitations: dict
    evidence_axes: dict
    radar: dict = field(default_factory=dict)
    sector_radar: dict = field(default_factory=dict)
    stock_radar: list[dict] = field(default_factory=list)
    cross_market_strip: dict = field(default_factory=dict)
    price_maps: dict = field(default_factory=dict)
    stock_analysis: list[dict] = field(default_factory=list)
    stock_sector_context: dict = field(default_factory=dict)
    technology_pulse: dict = field(default_factory=dict)
    presentation_warnings: tuple[str, ...] = field(default_factory=tuple)

    def evidence(self) -> dict:
        return _evidence(asdict(self))


def build_presentation(preview: dict, *, phase: str, report_date: date) -> MarketReportPresentation:
    if phase not in PHASE_LABELS:
        raise ValueError("Unsupported Discord market report phase.")
    # Select only canonical evidence: never carry body_html, configuration or settings.
    metadata = _map(preview.get("metadata"))
    keys = ("market", "breadth", "breadth_by_market", "volume_state", "distribution",
            "latest_trade_date", "sample_coverage", "top_industries", "weak_industries",
            "value_leaders", "top_gainers", "top_losers", "market_chips", "cross_market",
            "stance", "freshness", "freshness_by_capability", "source_refs", "radar",
            "stock_sector_context", "technology_pulse")
    data = _evidence({key: metadata.get(key) for key in keys})
    warnings, missing = report_limitations(_evidence(preview))
    canonical_quality = _map(data.get("freshness")).get("status")
    quality = (canonical_quality if isinstance(canonical_quality, str) and canonical_quality.strip()
               else "partial" if warnings or missing else "available" if metadata else "missing")
    breadth = _map(data.get("breadth"))
    cross = _map(data.get("cross_market"))
    groups = {}
    for market, label in MARKET_LABELS.items():
        block = _map(_map(cross.get("markets")).get(market))
        assets = _rows(block.get("assets"))
        # Select upstream status only. Never infer freshness from clocks/dates.
        stale = [row for row in assets if row.get("status") == "stale"]
        promoted = [row for row in assets if row.get("status") in {"current", "delayed", "usable"}
                    and row.get("usable") is not False and block.get("status") != "stale"]
        groups[market] = {"label": label, "status": block.get("status"), "promoted": promoted,
                          "stale": stale if block.get("status") != "stale" else assets,
                          "unavailable": [row for row in assets if row not in promoted and row not in stale]}
    compact = [f"{len(warnings)} 項資料提醒／{len(missing)} 項缺漏；完整說明見附件。",
               "各資料日期獨立；日線族群與排行非即時。",
               "過期跨市場資料不作本時段確認；本報告僅供研究觀察。"]
    sectors = build_sector_radar_rows(_rows(data.get("top_industries")), _rows(data.get("weak_industries")))
    stocks = build_stock_radar_items(
        value_leaders=_rows(data.get("value_leaders")), top_gainers=_rows(data.get("top_gainers")),
        top_losers=_rows(data.get("top_losers")), chips=_map(data.get("market_chips")),
        sectors=sectors, radar=_map(data.get("radar")),
    )
    model = MarketReportPresentation(
        phase=phase, report_date=report_date.isoformat(),
        header=f"OMI 台股{PHASE_LABELS[phase]}分析｜{report_date.isoformat()}",
        as_of=_text(_evidence(preview.get("as_of"))),
        session={"market_session": breadth.get("market_session"), "session_semantics": breadth.get("session_semantics")},
        quality=quality, stance=_text(data.get("stance")), indices=_map(_map(data.get("market")).get("indices")),
        breadth=breadth, breadth_by_market=_map(data.get("breadth_by_market")),
        volume=_map(data.get("volume_state")), distribution=_map(data.get("distribution")),
        daily_sample_scope=daily_sample_scope(data, report_date), sample_coverage=_map(data.get("sample_coverage")),
        strong_sectors=_rows(data.get("top_industries")), weak_sectors=_rows(data.get("weak_industries")),
        value_leaders=_rows(data.get("value_leaders")), top_gainers=_rows(data.get("top_gainers")), top_losers=_rows(data.get("top_losers")),
        chips=_map(data.get("market_chips")), cross_market=cross, cross_market_groups=groups,
        compact_limitations=compact, full_limitations={"warnings": warnings, "missing": missing},
        evidence_axes={key: data.get(key) for key in ("freshness", "freshness_by_capability", "source_refs")},
        radar=_map(data.get("radar")),
        sector_radar=sectors, stock_radar=stocks, cross_market_strip=build_cross_market_strip(groups),
        stock_sector_context=_map(data.get("stock_sector_context")),
        technology_pulse=_map(data.get("technology_pulse")),
    )
    return with_price_maps(model, {})


def build_sector_radar_rows(strong: list[dict], weak: list[dict]) -> dict:
    """Preserve canonical ordering/counts/representatives; never derive A/D."""
    return {key: [{field: row.get(field) for field in (
        "industry", "average_change_pct", "advance_count", "decline_count", "top_stock_id", "top_stock_name",
        "sample_count", "trade_value", "positive_ratio",
    )} for row in _rows(rows)[:6]] for key, rows in (("strong", strong), ("weak", weak))}


def build_stock_radar_items(*, value_leaders: list[dict], top_gainers: list[dict],
                           top_losers: list[dict], chips: dict, sectors: dict, radar: dict) -> list[dict]:
    """Stable round-robin source merge; no scoring, sorting or eligibility rules.

    Institutional lists are the Stage1 ordinary-stock rankings. Raw source rows,
    aggregate totals and out-of-universe diagnostics are never candidate sources.
    Later sources may fill the name and add reasons to selected IDs.
    Market and technical fields are attached only after selection is final.
    """
    institutional = _map(chips.get("institutional_per_stock"))
    sources = [
        ("成交前列", _rows(value_leaders)), ("漲幅前列", _rows(top_gainers)),
        ("跌幅前列", _rows(top_losers)),
        ("法人淨買", _rows(institutional.get("top_net_buy"))),
        ("法人淨賣", _rows(institutional.get("top_net_sell"))),
    ]
    for key, label in (("strong", "強族群代表"), ("weak", "弱族群代表")):
        sources.append((label, [{"stock_id": row.get("top_stock_id"), "stock_name": row.get("top_stock_name")}
                                for row in _rows(sectors.get(key))]))
    selected: dict[str, dict] = {}
    # Preserve the first occurrence in each canonical source.
    lists = []
    for reason, rows in sources:
        unique = {}
        for row in rows:
            stock_id = str(row.get("stock_id") or "").strip()
            if stock_id:
                unique.setdefault(stock_id, row)
        lists.append((reason, list(unique.items())))
    # Visit the same depth in each source before advancing to the next depth.
    # Duplicates do not consume slots; there is no score or within-source re-rank.
    for depth in range(max((len(rows) for _, rows in lists), default=0)):
        for _, rows in lists:
            if depth >= len(rows):
                continue
            stock_id, _ = rows[depth]
            if stock_id not in selected:
                selected[stock_id] = {"stock_id": stock_id, "stock_name": None, "reason_tags": []}
            if len(selected) == 8:
                break
        if len(selected) == 8:
            break
    for reason, rows in lists:
        for stock_id, row in rows:
            item = selected.get(stock_id)
            if item is None:
                continue
            for key in ("stock_name",):
                if item[key] is None and row.get(key) is not None:
                    item[key] = row[key]
            if len(item["reason_tags"]) < 3:
                item["reason_tags"].append(reason)
    return list(selected.values())


def build_cross_market_strip(groups: dict) -> dict:
    """A small display projection, with no timestamp-based freshness inference."""
    promoted = []
    statuses = []
    for market, group in groups.items():
        rows = [row for row in _rows(group.get("promoted")) if row.get("status") in {"current", "usable"}]
        limit = {"us": 3, "crypto": 1}.get(market, 0)
        for row in rows[:limit]:
            promoted.append({"group": market, **{key: row.get(key) for key in (
                "id", "label", "price", "currency", "change_pct", "status",
            )}, "availability": {key: "available" if row.get(key) is not None else "missing"
                                  for key in ("price", "change_pct")}})
        if group.get("stale") and not rows:
            statuses.append({"group": market, "label": group["label"], "status": "已過期"})
        elif not rows:
            statuses.append({"group": market, "label": group["label"], "status": "資料不足"})
        elif not limit:
            statuses.append({"group": market, "label": group["label"], "status": "可用"})
    return {"promoted": promoted, "groups": statuses}


def sector_radar_rows(model: MarketReportPresentation) -> dict:
    return _evidence(model.sector_radar)


def with_price_maps(model: MarketReportPresentation, price_maps: dict, *,
                    market_facts: dict | None = None,
                    technical_reports: dict | None = None) -> MarketReportPresentation:
    """Detach canonical evidence and project fields, without technical inference.

    Selection is already final. Canonical observations are copied, never
    recalculated; missing decision maps retain factual evidence and reasons.
    """
    maps = {item["stock_id"]: _evidence(_map(price_maps.get(item["stock_id"])))
            for item in model.stock_radar[:8]}
    analysis = []
    for item in model.stock_radar[:8]:
        evidence = maps[item["stock_id"]]
        reference = _map(evidence.get("reference"))
        market = _evidence(_map((market_facts or {}).get(item["stock_id"])))
        facts = _evidence(_map((technical_reports or {}).get(item["stock_id"])))
        facts.update({"reference": reference, "technical": _map(evidence.get("technical")),
                      "price_map_status": evidence.get("status"),
                      "price_map_missing": evidence.get("missing", [])})
        tags = []
        if model.radar.get("dispatch_version") == "v2":
            for row in _rows(_map(model.radar.get("radar")).get("results")):
                if (str(row.get("stock_id") or "").strip() != item["stock_id"]
                        or row.get("is_current") is False or row.get("status") in {"stale", "missing"}):
                    continue
                keys = row.get("signal_keys")
                for key in keys if isinstance(keys, list) else []:
                    if isinstance(key, str) and key.strip() and key not in tags and len(tags) < 2:
                        tags.append(key)
        facts["signal_keys"] = tags
        usable = (evidence.get("decision_usable") is True
                  and evidence.get("status") not in {"stale", "missing", "unavailable"}
                  and reference.get("freshness_status") not in {"stale", "missing"})
        observe = None
        if usable:
            for change in _rows(evidence.get("decision_changes")):
                threshold = change.get("threshold_price")
                meaningful = (isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
                              and isfinite(threshold) and threshold > 0)
                linked = change.get("link_status") == "linked" and bool(change.get("zone_id"))
                if (change.get("decision_usable") is True and (meaningful or linked)
                        and (change.get("label") or change.get("result_summary"))):
                    observe = {key: change.get(key) for key in (
                        "label", "result_summary", "threshold_price", "relation", "zone_id", "link_status")}
                    break
        institutional = []
        ranking = _map(model.chips.get("institutional_per_stock"))
        for side, key in (("buy", "top_net_buy"), ("sell", "top_net_sell")):
            for rank, row in enumerate(_rows(ranking.get(key)), 1):
                if str(row.get("stock_id")) == item["stock_id"]:
                    institutional.append({**_evidence(row), "trade_date": row.get("trade_date", ranking.get("trade_date")),
                                          "side": side, "rank": row.get("rank", rank)})
        sectors = [{**_evidence(row), "side": side, "representative": True}
                   for side, rows in (("strong", model.strong_sectors), ("weak", model.weak_sectors))
                   for row in rows if str(row.get("top_stock_id")) == item["stock_id"]]
        decision = {"usable": usable, "status": evidence.get("status"),
                    "missing": evidence.get("missing", []), "reasons": evidence.get("reasons", []),
                    "warnings": evidence.get("warnings", []), "limitations": evidence.get("limitations", []),
                    "support": _map(evidence.get("nearest_downside")) if usable else {},
                    "resistance": _map(evidence.get("nearest_upside")) if usable else {},
                    "headline": _map(evidence.get("technical")).get("headline") if usable else None,
                    "observe": observe, "decision_changes": evidence.get("decision_changes", []) if usable else []}
        analysis.append({**_evidence(item),
                         "market_role": selection_role(item["reason_tags"]),
                         "sector_context": _evidence(_map(model.stock_sector_context.get(item["stock_id"]))),
                         "identity": {key: item.get(key) for key in ("stock_id", "stock_name")},
                         "market": market, "selection": {"reasons": _evidence(item["reason_tags"])},
                         "institutional": institutional, "sector": sectors,
                         "technical_facts": facts, "technical_decision": decision,
                         "technical_blockers": technical_blocker_lines(facts),
                         "change_pct": market.get("change_pct"), "trade_value": market.get("trade_value"),
                         "technical_tags": tags, "technical_available": usable,
                         "reference": reference,
                         "support": _map(evidence.get("nearest_downside")) if usable else {},
                         "resistance": _map(evidence.get("nearest_upside")) if usable else {},
                         "headline": _map(evidence.get("technical")).get("headline"),
                         "observe": observe})
    return replace(model, price_maps=maps, stock_analysis=analysis)


def technical_blocker_lines(facts: dict) -> list[str]:
    """Format canonical reasons/dates only; no inference or repair decisions."""
    quality = _map(_map(facts.get("data")).get("input_quality"))
    labels = {
        "ALTERNATE_OFFICIAL_PRICE_REQUIRED": "有成交但缺官方價格",
        "PRICE_BASIS_EVENT_COVERAGE_REQUIRED": "已驗證零成交；價格基準事件覆蓋不足",
        "PRICE_BASIS_CHANGED": "價格基準已變更，禁止沿用前收",
        "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN": "歷史個股交易資格尚無官方證據",
        "OFFICIAL_DAILY_EVIDENCE_REQUIRED": "缺官方日線證據",
        "PRIOR_CANONICAL_CLOSE_MISSING": "缺連續的 canonical 前收",
        "OFFICIAL_EVIDENCE_CONFLICT": "官方證據互相衝突",
        "MARKET_CALENDAR_COVERAGE_UNKNOWN": "交易日曆覆蓋未知",
    }
    grouped: dict[str, list[str]] = {}
    for item in _rows(quality.get("day_state_blockers")):
        for reason in item.get("reasons", []):
            day = str(item.get("trade_date") or "unknown")
            if day not in grouped.setdefault(reason, []):
                grouped[reason].append(day)
    ordered = [key for key in labels if key in grouped] + [key for key in grouped if key not in labels]
    return [f"{labels.get(key, key)}：{'、'.join(grouped[key])}" for key in ordered]


def stock_radar_items(model: MarketReportPresentation, limit: int = 8) -> list[dict]:
    return _evidence(model.stock_analysis[:max(0, min(limit, 8))])


def cross_market_strip(model: MarketReportPresentation) -> dict:
    return _evidence(model.cross_market_strip)


def display_status(value: Any) -> str:
    return {"current": "有效", "delayed": "延遲", "stale": "已過期", "partial": "部分資料",
            "missing": "缺資料", "ready": "可用", "available": "可用", "usable": "可用", "complete": "完整",
            "unreleased": "尚未發布", "ordinary_stock": "普通股母體",
            "regular": "一般交易時段", "closed": "已收盤", "post_close": "盤後",
            "current_session": "本交易時段", "latest_completed_session": "最近完成交易日",
            "official_close": "官方收盤", "completed_session": "已完成交易日",
            "intraday_last_trade": "盤中最新成交"}.get(str(value), "未確認（詳見附件）")


def index_summary(row: dict) -> str:
    return f"{_number(row.get('value'))}  {_number(row.get('change_pct'), percent=True)}"


def coverage_summary(block: dict) -> str:
    coverage = _map(block.get("coverage"))
    return (f"普通股母體 {_number(coverage.get('covered_eligible_count'))}/{_number(coverage.get('eligible_count'))}"
            f"（{_number(coverage.get('coverage_ratio'), ratio=True)}）")
