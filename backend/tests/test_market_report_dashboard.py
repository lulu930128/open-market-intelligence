from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.dispatch import market_report_chart as chart
from app.dispatch import discord_market_report as report
from app.dispatch import discord_sender as sender
from app.dispatch.market_report_presentation import (
    _evidence, build_presentation, sector_radar_rows, stock_radar_items, cross_market_strip, with_price_maps,
)


def test_evidence_serializes_nested_dates_and_preserves_primitive_behavior():
    value = {"nested": [date(2026, 10, 2), {"naive": datetime(2026, 10, 2, 16, 0),
             "aware": datetime(2026, 10, 2, 16, 0, 1, 123456,
                               tzinfo=timezone(timedelta(hours=8)))}],
             "primitives": [None, True, False, 0, -7, 1.25, "plain text"],
             "unsupported": [float("nan"), float("inf"), float("-inf"), object()]}
    assert _evidence(value) == {
        "nested": ["2026-10-02", {"naive": "2026-10-02T16:00:00",
                                    "aware": "2026-10-02T16:00:01.123456+08:00"}],
        "primitives": [None, True, False, 0, -7, 1.25, "plain text"],
        "unsupported": [None, None, None, None],
    }
    assert type(value["nested"][0]) is date


def test_with_price_maps_preserves_canonical_reference_date_as_iso():
    base = presentation(value_leaders=[stock("2409")])
    canonical = price_map(reference={"price": 40.45, "trade_date": date(2026, 10, 2),
                                     "freshness_status": "current"})
    model = with_price_maps(base, {"2409": canonical})
    assert model.stock_analysis[0]["reference"]["trade_date"] == "2026-10-02"
    assert model.evidence()["stock_analysis"][0]["reference"]["trade_date"] == "2026-10-02"
    assert canonical["reference"]["trade_date"] == date(2026, 10, 2)


def price_map(**overrides):
    return {
        "status": "ready", "decision_usable": True,
        "reference": {"price": 40.45, "trade_date": "2026-10-02", "freshness_status": "current"},
        "nearest_downside": {"anchor_price": 39.2, "lower_bound": 39, "upper_bound": 39.5, "distance_pct": -3.1234},
        "nearest_upside": {"anchor_price": 42, "lower_bound": 41.5, "upper_bound": 42.5, "distance_pct": 3.9876},
        "technical": {"headline": "上游原文 headline", "score": 99},
        "decision_changes": [{"decision_usable": True, "label": "上游條件", "threshold_price": 42,
                              "result_summary": "上游結果", "link_status": "unlinked"}],
        **overrides,
    }


def test_price_map_projection_is_detached_verbatim_and_does_not_rerank():
    base = presentation(value_leaders=[stock("2409"), stock("2330")])
    maps = {"2409": price_map(), "2330": price_map(technical={"score": 100000, "headline": "第二檔"})}
    model = with_price_maps(base, maps)
    assert model.stock_radar == base.stock_radar
    assert [row["stock_id"] for row in model.stock_analysis] == ["2409", "2330"]
    item = model.stock_analysis[0]
    assert item["reference"] == maps["2409"]["reference"]
    assert item["support"] == maps["2409"]["nearest_downside"]
    assert item["resistance"] == maps["2409"]["nearest_upside"]
    assert item["headline"] == maps["2409"]["technical"]["headline"]
    assert item["observe"]["result_summary"] == "上游結果"
    maps["2409"]["nearest_downside"]["anchor_price"] = 999
    assert item["support"]["anchor_price"] == 39.2
    assert model.price_maps["2409"]["nearest_downside"]["anchor_price"] == 39.2


@pytest.mark.parametrize("evidence", [{}, price_map(decision_usable=False), price_map(status="stale"),
    price_map(status="missing"), price_map(reference={"freshness_status": "stale"})])
def test_unavailable_price_map_keeps_reasons_quote_without_inference(evidence):
    base = presentation(value_leaders=[stock("2409", change_pct=999, trade_value=999, close=99, ma20=88)])
    market = {"change_pct": 10, "trade_value": 100, "close": 99}
    item = with_price_maps(base, {"2409": evidence}, market_facts={"2409": market}).stock_analysis[0]
    assert item["selection"]["reasons"] == ["成交前列"]
    assert item["market"] == market
    assert item["market"]["change_pct"] == item["change_pct"] == 10
    assert item["market"]["trade_value"] == item["trade_value"] == 100
    decision = item["technical_decision"]
    assert decision["usable"] is False and not item["technical_available"]
    assert not decision["support"] and not decision["resistance"]
    assert not decision["headline"] and not decision["observe"]


def test_decision_changes_only_first_usable_meaningful_upstream_condition():
    conditions = [
        {"decision_usable": False, "threshold_price": 50, "label": "blocked"},
        {"decision_usable": True, "threshold_price": None, "label": "empty"},
        {"decision_usable": True, "threshold_price": float("nan"), "label": "invalid"},
        {"decision_usable": True, "threshold_price": 0, "label": "zero"},
        {"decision_usable": True, "threshold_price": 42, "label": "exact", "result_summary": "verbatim"},
        {"decision_usable": True, "threshold_price": 43, "label": "later"},
    ]
    base = presentation(value_leaders=[stock("2409")])
    item = with_price_maps(base, {"2409": price_map(decision_changes=conditions)}).stock_analysis[0]
    assert item["observe"]["label"] == "exact" and item["observe"]["result_summary"] == "verbatim"
    assert item["observe"]["threshold_price"] == 42
    assert with_price_maps(base, {"2409": price_map(decision_changes=[])}).stock_analysis[0]["observe"] is None


def test_stock_chart_long_headline_observe_bounds_and_missing_quote(monkeypatch):
    captured = []
    original = ImageDraw.ImageDraw.text
    def capture(draw, xy, text, *args, **kwargs):
        box = draw.textbbox(xy, text, font=kwargs["font"])
        card_right = 780 if xy[0] < 820 else 1560
        if 140 <= xy[1] < 1530:
            assert box[2] <= card_right and box[3] < 1530
        captured.append(text)
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    long = "很長的上游內容😀\n" * 100
    base = presentation(value_leaders=[stock(str(i), stock_name=long) for i in range(8)])
    evidence = price_map(technical={"headline": long}, decision_changes=[{
        "decision_usable": True, "threshold_price": 42, "label": long, "result_summary": long}])
    png = chart.render_stock_analysis_chart(with_price_maps(base, {str(i): evidence for i in range(8)}))
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1600, 1600)
    assert "行情暫未提供" in captured and "資料不足" not in captured
    assert "42" in captured and any("…" in value for value in captured)


def presentation(**metadata):
    return build_presentation({"metadata": metadata}, phase="postclose", report_date=date(2026, 10, 3))


def stock(identity, **fields):
    return {"stock_id": identity, **fields}


def test_sector_projection_preserves_order_six_rows_counts_and_representative():
    rows = [{"industry": f"族群{i}", "average_change_pct": 7 - i, "advance_count": 0,
             "decline_count": None, "top_stock_id": str(2330 + i), "top_stock_name": f"代表{i}"}
            for i in range(9)]
    original = deepcopy(rows)
    model = presentation(top_industries=rows, weak_industries=list(reversed(rows)))
    result = sector_radar_rows(model)
    assert rows == original
    expected = [{**row, "sample_count": None, "trade_value": None} for row in rows]
    assert result["strong"] == expected[:6] and result["weak"] == list(reversed(expected))[:6]
    rows[0]["advance_count"] = 99
    assert result["strong"][0]["advance_count"] == 0
    assert result["strong"][0]["decline_count"] is None
    assert sector_radar_rows(presentation()) == {"strong": [], "weak": []}


def test_stock_stable_source_priority_missing_merge_dedup_and_tag_limits():
    shared = stock("2330", stock_name="台積電", change_pct=0)
    model = presentation(
        value_leaders=[stock("2330"), stock("2330"), stock("2317")],
        top_gainers=[shared, stock("2303", trade_value=0)],
        top_losers=[shared, stock("2345")],
        market_chips={"institutional_per_stock": {
            "top_net_buy": [stock("2330", trade_value=150), stock("2454")],
            "top_net_sell": [stock("2330"), stock("6488")],
            "source_out_of_universe": [stock("0050")],
            "raw_rows": [stock("020001"), stock("030001"), stock("9105")],
        }},
        top_industries=[{"top_stock_id": "2330"}, {"top_stock_id": "2603", "top_stock_name": "長榮"}],
        weak_industries=[{"top_stock_id": "2881"}, {"top_stock_id": "2882"}],
    )
    items = model.stock_radar
    assert [row["stock_id"] for row in items] == ["2330", "2881", "2317", "2303", "2345", "2454", "6488", "2603"]
    assert items[0]["stock_name"] == "台積電"
    assert all("change_pct" not in row and "trade_value" not in row for row in items)
    assert items[0]["reason_tags"] == ["成交前列", "漲幅前列", "跌幅前列"]
    by_id = {row["stock_id"]: row for row in items}
    assert by_id["2454"]["reason_tags"] == ["法人淨買"] and by_id["6488"]["reason_tags"] == ["法人淨賣"]
    assert by_id["2603"]["reason_tags"] == ["強族群代表"] and by_id["2881"]["reason_tags"] == ["弱族群代表"]
    assert len(items[0]["reason_tags"]) == 3
    assert all(len(row["reason_tags"]) <= 3 for row in items)
    assert [row["stock_id"] for row in stock_radar_items(model, 99)] == [row["stock_id"] for row in items]
    assert [row["stock_id"] for row in stock_radar_items(model, 2)] == [row["stock_id"] for row in items[:2]]
    assert stock_radar_items(model, 0) == []
    assert stock_radar_items(presentation()) == []


def test_long_value_ranking_cannot_starve_other_sources():
    model = presentation(
        value_leaders=[stock(f"V{i}") for i in range(20)],
        top_gainers=[stock("G"), stock("V0")], top_losers=[stock("L")],
        market_chips={"institutional_per_stock": {"top_net_buy": [stock("B")], "top_net_sell": [stock("S")]}},
        top_industries=[{"top_stock_id": "STRONG"}, {"top_stock_id": "V0"}],
        weak_industries=[{"top_stock_id": "WEAK"}],
    )
    assert [row["stock_id"] for row in stock_radar_items(model)] == ["V0", "G", "L", "B", "S", "STRONG", "WEAK", "V1"]
    assert stock_radar_items(model) == stock_radar_items(model)
    # Sparse sources fall through without fabricated filler or duplicate IDs.
    sparse = presentation(value_leaders=[stock("V0")] * 10, top_gainers=[stock("V0")] * 10)
    assert [row["stock_id"] for row in stock_radar_items(sparse)] == ["V0"]


def test_technical_tags_only_formal_upstream_exact_identity_no_inference():
    rows = [stock("2330", change_pct=10, trade_value=9999999999, technical_tags=["不要自行推導突破"]), stock("2317")]
    radar = {"dispatch_version": "v2", "radar": {"results": [
        stock("2330", signal_keys=["upstream_a", "upstream_a", "upstream_b", "upstream_c"]),
        stock("2303", signal_keys=["unmatched"]),
        stock("2317", status="stale", signal_keys=["stale_signal"]),
    ]}}
    original = deepcopy(radar)
    items = stock_radar_items(presentation(value_leaders=rows, radar=radar))
    assert items[0]["technical_tags"] == ["upstream_a", "upstream_b"]
    assert items[1]["technical_tags"] == [] and radar == original
    assert stock_radar_items(presentation(value_leaders=rows))[0]["technical_tags"] == []
    radar["dispatch_version"] = "unknown"
    assert stock_radar_items(presentation(value_leaders=rows, radar=radar))[0]["technical_tags"] == []


def test_cross_strip_status_only_limits_and_stale_values_absent():
    assets = [{"id": f"INDEX{i}", "status": "current", "price": i, "as_of": "1990-01-01"} for i in range(5)]
    markets = {"us": {"assets": assets}, "crypto": {"assets": assets}}
    markets["us"]["assets"] = [
        {"id": "DELAYED", "status": "delayed", "price": 998877},
        {"id": "UNUSABLE", "status": "current", "usable": False, "price": 998877},
        *assets,
    ]
    for key in ("jp", "kr", "resource"):
        markets[key] = {"status": "stale", "assets": [{"id": key, "price": 987654321, "status": "current"}]}
    result = cross_market_strip(presentation(cross_market={"markets": markets}))
    assert [row["id"] for row in result["promoted"]] == ["INDEX0", "INDEX1", "INDEX2", "INDEX0"]
    assert [row["status"] for row in result["groups"]] == ["已過期"] * 3
    assert "987654321" not in str(result) and "998877" not in str(result)


@pytest.mark.parametrize("renderer", [chart.render_market_dashboard_chart, chart.render_stock_analysis_chart])
@pytest.mark.parametrize("missing", [True, False])
def test_all_pngs_signature_dimensions_safe_truncation_no_stale_price(renderer, missing, monkeypatch):
    captured = []
    real_text = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        assert "\n" not in text and "\r" not in text
        assert draw.textlength(text, font=kwargs["font"]) + xy[0] <= 1600
        captured.append(text)
        return real_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    long = "很長的名稱😀\n" * 500
    model = presentation() if missing else presentation(
        top_industries=[{"industry": long, "average_change_pct": 2, "advance_count": 7,
                         "decline_count": 0, "top_stock_name": long, "top_stock_id": "2330"}] * 6,
        weak_industries=[{"industry": long, "average_change_pct": -1}] * 6,
        value_leaders=[stock(str(2330 + i), stock_name=long, change_pct=i, trade_value=100000000) for i in range(8)],
        cross_market={"markets": {"jp": {"status": "stale", "assets": [{"price": 987654321}]}}},
    )
    png = renderer(model)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1600, 1600 if renderer is chart.render_stock_analysis_chart else 1200) and image.format == "PNG"
        image.load()
    visible = "\n".join(captured)
    assert "987654321" not in visible and "missing" not in visible
    if not missing:
        assert "…" in visible
    if renderer is chart.render_market_dashboard_chart and not missing:
        assert "漲 7 / 跌 0" in visible and "代表 2330" in visible


@pytest.mark.parametrize("entry", ["render_market_dashboard_chart", "render_stock_analysis_chart"])
def test_late_font_failure_discards_partial_compact_images(entry, monkeypatch):
    def unavailable(model):
        raise chart.ChartUnavailable("中文字型不可用")
    monkeypatch.setattr(report, entry, unavailable)
    rich = report.build_rich_report(presentation())
    assert rich.content and rich.embeds == [] and rich.attachments == []


def test_five_attachments_and_exact_byte_bounds():
    files = [sender.DiscordAttachment(f"{i}.png", b"x", "image/png") for i in range(5)]
    sender.validate_rich_payload(attachments=files)
    with pytest.raises(sender.DiscordDeliveryError):
        sender.validate_rich_payload(attachments=files + [sender.DiscordAttachment("5.png", b"x", "image/png")])
    limit = 2 * 1024 * 1024
    files = [sender.DiscordAttachment(f"{i}.png", b"x" * limit, "image/png") for i in range(3)]
    sender.validate_rich_payload(attachments=files)
    with pytest.raises(sender.DiscordDeliveryError):
        sender.validate_rich_payload(attachments=files + [sender.DiscordAttachment("3.png", b"x", "image/png")])
