from copy import deepcopy
from datetime import date
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.ai.market_context.taiwan_market import _daily_report_context
from app.dispatch import discord_market_report as report, market_report_chart as chart
from app.dispatch.market_report_presentation import build_presentation, with_price_maps
from app.market.taiwan_industries import TAIWAN_TECH_INDUSTRY_CODES, canonical_tw_sector_identity
from test_market_report_dashboard import price_map
from test_market_report_enrichment import IDS, preview


def daily_fixture():
    rows = [
        {"stock_id": "A", "stock_name": "半導體成交焦點", "industry": "24", "change_pct": 2, "trade_value": 900_000_000},
        {"stock_id": "B", "stock_name": "半導體下跌異動", "industry": "半導體", "change_pct": -4, "trade_value": 100_000_000},
        {"stock_id": "C", "stock_name": "數位雲端焦點", "industry": "36", "change_pct": 6, "trade_value": 300_000_000},
        {"stock_id": "D", "stock_name": "電子商務觀察", "industry": "34", "change_pct": 0, "trade_value": 0},
        {"stock_id": "E", "stock_name": "光電資料缺漏", "industry": "26", "change_pct": None, "trade_value": None},
        {"stock_id": "F", "stock_name": "網路成交焦點", "industry": "27", "change_pct": 1, "trade_value": 200_000_000},
        {"stock_id": "G", "stock_name": "電腦下跌觀察", "industry": "25", "change_pct": -2, "trade_value": 150_000_000},
        {"stock_id": "H", "stock_name": "金融", "industry": "17", "change_pct": 10, "trade_value": 999_000_000_000},
        {"stock_id": "I", "stock_name": "假科技標籤", "industry": "科技半導體概念", "change_pct": 10, "trade_value": 999_000_000_000},
    ]
    sectors = [
        {"industry": "半導體業", "count": 2, "advance_count": 1, "decline_count": 1,
         "average_change_pct": -1, "trade_value": 1_000_000_000, "top_stock_id": "A", "top_stock_name": "半導體成交焦點"},
        *[{"industry": canonical_tw_sector_identity(r["industry"])["name"], "count": 1,
           "advance_count": int(r["change_pct"] > 0), "decline_count": int(r["change_pct"] < 0),
           "average_change_pct": r["change_pct"], "trade_value": r["trade_value"],
           "top_stock_id": r["stock_id"], "top_stock_name": r["stock_name"]}
          for r in rows[2:] if r["change_pct"] is not None],
    ]
    return rows, sectors


def technology_model():
    rows, sectors = daily_fixture()
    context, pulse = _daily_report_context(ranked=rows, industry_summary=sectors,
        candidate_ids={r["stock_id"] for r in rows}, trade_date="2026-10-02", coverage={"status": "partial"})
    model = build_presentation({"as_of": "2026-10-02 · fixture", "metadata": {
        "latest_trade_date": "2026-10-02", "freshness": {"status": "partial"},
        "value_leaders": rows[:8], "top_gainers": [rows[2]], "top_losers": [rows[1]],
        "top_industries": sectors, "weak_industries": list(reversed(sectors)),
        "stock_sector_context": context, "technology_pulse": pulse}}, phase="postclose", report_date=date(2026, 10, 2))
    return with_price_maps(model, {r["stock_id"]: price_map() for r in rows[:4]},
        market_facts={r["stock_id"]: r for r in rows})


def test_owner_statistics_taxonomy_missing_denominators_and_deterministic_focus():
    rows, sectors = daily_fixture()
    original = deepcopy(rows)
    contexts, pulse = _daily_report_context(ranked=rows, industry_summary=sectors,
        candidate_ids={"A", "H", "I"}, trade_date="2026-10-02", coverage={"status": "partial"})
    assert rows == original
    assert set(contexts) == {"A", "H", "I"}
    assert contexts["A"]["relative_change_pp"] == 3
    assert contexts["A"]["positive_ratio"] == .5
    assert contexts["I"]["relative_change_pp"] is None
    assert pulse["universe_codes"] == sorted(TAIWAN_TECH_INDUSTRY_CODES)
    assert pulse["sample_count"] == 7 and pulse["change_count"] == 6
    assert pulse["missing_change_count"] == 1 and pulse["trade_value_count"] == 6
    assert pulse["average_change_pct"] == .5
    assert (pulse["advance_count"], pulse["decline_count"], pulse["unchanged_count"]) == (3, 2, 1)
    assert pulse["positive_ratio"] == .5 and pulse["trade_value"] == 1_650_000_000
    assert pulse["coverage"]["status"] == "partial"
    focus = pulse["focus_stocks"]
    assert [row["stock_id"] for row in focus] == ["A", "C", "B", "G", "F", "D"]
    assert all(row["reason_tags"] and row["sector_context"]["trade_date"] == "2026-10-02" for row in focus)
    assert "跌幅前列" in focus[2]["reason_tags"]
    assert all(row["stock_id"] not in {"H", "I"} for row in focus)
    _, again = _daily_report_context(ranked=list(reversed(rows)), industry_summary=list(reversed(sectors)),
        candidate_ids=set(), trade_date="2026-10-02", coverage={"status": "partial"})
    assert again == pulse


@pytest.mark.parametrize("change,value", [(None, None), (float("nan"), float("inf")), (0, 0)])
def test_missing_and_zero_are_distinct(change, value):
    _, pulse = _daily_report_context(ranked=[{"stock_id": "A", "industry": "24", "change_pct": change, "trade_value": value}],
        industry_summary=[], candidate_ids=set(), trade_date="2026-10-02", coverage={})
    assert pulse["average_change_pct"] == (0 if change == 0 else None)
    assert pulse["positive_ratio"] == (0 if change == 0 else None)
    assert pulse["trade_value"] == (0 if value == 0 else None)
    _, empty = _daily_report_context(ranked=[], industry_summary=[], candidate_ids=set(), trade_date="2026-10-02", coverage={})
    assert empty["focus_stocks"] == [] and empty["advance_count"] is None


def test_enrichment_preserves_exact_eight_order_and_does_not_relax_gate():
    source = preview()
    base = build_presentation(source, phase="postclose", report_date=date(2026, 10, 2))
    context = {"industry": "半導體業", "average_change_pct": 99, "relative_change_pp": -999,
               "stock_change_pct": -900, "trade_date": "2026-09-30", "positive_ratio": .75}
    source["metadata"].update(stock_sector_context={identity: context for identity in IDS},
                               technology_pulse={"focus_stocks": [{"stock_id": "NOT_IN_EIGHT"}]})
    enriched = build_presentation(source, phase="postclose", report_date=date(2026, 10, 2))
    assert enriched.stock_radar == base.stock_radar
    expected_order = ["2327", "2409", "2324", "1727", "6902", "1459", "4154", "2330"]
    assert [row["stock_id"] for row in enriched.stock_analysis] == expected_order
    enriched = with_price_maps(enriched, {identity: price_map(decision_usable=False) for identity in IDS},
                              market_facts={identity: {"change_pct": 50, "trade_date": "2026-10-02"} for identity in IDS})
    for item in enriched.stock_analysis:
        assert item["market_role"] and item["sector_context"] == context
        assert item["change_pct"] == 50  # Comparison is explicitly a different dated sample.
        assert not item["technical_available"] and not item["support"] and not item["observe"]
    context["relative_change_pp"] = 12345
    assert enriched.stock_analysis[0]["sector_context"]["relative_change_pp"] == -999


def test_template_preserves_owner_fields_without_recalculation(monkeypatch):
    upstream = technology_model()
    canonical = {"technology_pulse": upstream.technology_pulse, "stock_sector_context": upstream.stock_sector_context}
    monkeypatch.setattr(report.templates.tools, "read_market_overview", lambda **kw: {"data": canonical})
    result = report.templates.build_market_overview_preview(None, market="tw")
    assert all(result["metadata"][key] == value for key, value in canonical.items())


def test_semantic_colors_use_meaning_including_unknown_and_technical():
    assert len(set(chart.SEMANTIC_COLORS.values())) == 6
    assert chart.semantic_colors("漲幅前列") == chart.semantic_colors("強族群代表")
    assert chart.semantic_colors("跌幅前列") != chart.semantic_colors("漲幅前列")
    assert chart.semantic_colors("法人淨買") == chart.semantic_colors("法人淨賣") == chart.semantic_colors("flow")
    assert chart.semantic_colors("new unknown tag") == chart.semantic_colors("missing")
    assert chart.semantic_colors("背離") == chart.semantic_colors("warning")
    assert chart.change_color(-2) == chart.semantic_colors("weakness")[0]
    assert chart.change_color(2) == chart.semantic_colors("strength")[0]
    assert chart.change_color(None) == chart.semantic_colors("missing")[0]


def test_technology_png_long_labels_card_bounds_and_verbatim_evidence(monkeypatch):
    model = technology_model()
    pulse = model.technology_pulse
    pulse["sectors"] = pulse["sectors"] * 2  # Exercise all ten visible sector slots.
    pulse["focus_stocks"][0]["stock_name"] = "長名稱😀\n" * 100
    pulse["focus_stocks"][0]["sector_context"]["relative_change_pp"] = 77.77
    pulse["sectors"][0]["industry"] = "長產業😀\n" * 100
    captured = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, value, *args, **kwargs):
        box = draw.textbbox(xy, value, font=kwargs["font"])
        assert box[2] <= 1560 and box[3] < 1800
        if 419 <= xy[1] < 909 or 976 <= xy[1] < 1682:
            assert box[2] <= (780 if xy[0] < 820 else 1560)
        if 976 <= xy[1] < 1682:
            card_bottom = 976 + ((xy[1] - 976) // 240) * 240 + 226
            assert box[3] <= card_bottom
        captured.append(value)
        return original(draw, xy, value, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    png = chart.render_technology_pulse_chart(model)
    with Image.open(BytesIO(png)) as image:
        image.load()
        assert image.size == (1600, 1800)
    assert "相對族群 +77.77 pp" in captured  # Renderer copies, never subtracts again.
    assert any("…" in value for value in captured)
    assert all("missing" not in value and "\n" not in value for value in captured)
