"""Real Pillow regressions through the selected production report path; offline."""
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageDraw
import pytest

from app.dispatch import discord_market_report as report
from app.dispatch import discord_sender as sender
from app.dispatch import market_report_chart as chart
from app.dispatch.market_report_presentation import phase_dashboard_rows
import test_discord_market_report_phases as phase_fixtures


DAY = date(2026, 10, 27)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("offline chart acceptance must not connect or open the production DB")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(report, "SessionLocal", forbidden)
    monkeypatch.setattr(report, "send_discord_rich_report", forbidden)
    monkeypatch.setattr(phase_fixtures, "DAY", DAY)
    previous = report.expected_daily_price_date(now=datetime(2026, 10, 27, 8, 55, tzinfo=report.TAIPEI))
    monkeypatch.setattr(phase_fixtures, "PREVIOUS", previous)


def dashboard_payload(phase):
    payload = phase_fixtures.envelope(phase)
    data = payload["data"]
    data["sample_coverage"] = {"status": "partial", "sample_count": 30, "universe_count": 2000}
    for key, sign in (("top_industries", 1), ("weak_industries", -1)):
        data[key] = [{"industry": f"日線族群{sign:+d}-{i}", "average_change_pct": sign * (i + 1),
                      "advance_count": 5 if sign == 1 else 0, "decline_count": 0 if sign == 1 else 5,
                      "positive_ratio": 1 if sign == 1 else 0, "top_stock_id": "9999",
                      "sample_count": 5} for i in range(6)]
    data["value_leaders"] = [{"stock_id": "9999", "stock_name": "日線焦點", "change_pct": 3,
                              "trade_value": 123000000, "trade_date": data["latest_trade_date"]}]
    current = data["screening"]["intraday"]["rows"][0]
    data["screening"]["intraday"]["rows"] = [
        {**current, "stock_id": str(2330 + i), "stock_name": f"當時候選{i}", "change_pct": i - 1}
        for i in range(3)]
    # Mixed signs, nonmonotone values: the chart must preserve owner rank.
    data["screening"]["hot_groups"]["groups"] = [
        {"group_name": f"當時族群{i}", "mean_return_pct": change, "advance_count": 3,
         "decline_count": 2, "advance_ratio": .6, "last_trade_recency": "current", "coverage_ratio": .5}
        for i, change in enumerate((2, -4, 5, -1, 3, -2, 0, None))]
    for row in data["market"]["indices"]["items"]:
        row["official_close"].update(authority="official_exchange", finalization="final",
                                     freshness={"status": "historical"})
    stamp = data["cross_market"]["markets"]["us"]["assets"][0]["as_of"]
    data["cross_market"]["markets"] = {
        "us": {"status": "current", "assets": [
            {"id": identity, "label": identity, "price": 6000 + i, "currency": "USD",
             "change_pct": i - 1, "status": "current", "as_of": stamp,
             "authority": "provider", "source": "overnight_cache"}
            for i, identity in enumerate(("SPX", "NDX", "DJI"))]},
        "crypto": {"status": "current", "assets": [
            {"id": "BTC", "price": 90000, "currency": "USD", "change_pct": 2,
             "status": "current", "as_of": stamp, "source": "crypto_cache", "authority": "provider"}]},
    }
    return payload


@pytest.fixture
def drawn(monkeypatch):
    """Capture what Pillow actually paints, after clipping, including bounds."""
    texts, rectangles = [], []
    original_text = ImageDraw.ImageDraw.text
    original_rectangle = ImageDraw.ImageDraw.rounded_rectangle

    def capture_text(draw, xy, value, *args, **kwargs):
        box = draw.textbbox(xy, value, font=kwargs["font"])
        assert 0 <= box[0] <= box[2] <= 1600
        assert 0 <= box[1] <= box[3] <= 1200
        texts.append((xy, value, box))
        return original_text(draw, xy, value, *args, **kwargs)

    def capture_rectangle(draw, xy, *args, **kwargs):
        rectangles.append(xy)
        return original_rectangle(draw, xy, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "rounded_rectangle", capture_rectangle)
    return texts, rectangles


def visible(drawn, top=0, bottom=1200):
    return "\n".join(value for xy, value, box in drawn[0] if top <= xy[1] < bottom)


def assert_layout(png, drawn):
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(BytesIO(png)).convert("RGB")
    assert image.size == (1600, 1200)
    # Every slot remains painted, including empty placeholders and the last row.
    boxes = [(x, y, x + width, y + height) for y, width, height, xs in (
        (130, 740, 128, (40, 820)), (270, 740, 144, (40, 820)),
        (426, 500, 110, (40, 560, 1080)), (1012, 370, 126, (40, 430, 820, 1210)),
    ) for x in xs]
    boxes += [(x, 610 + i * 62, x + 740, 666 + i * 62) for x in (40, 820) for i in range(6)]
    for box in boxes:
        assert box in drawn[1]
        crop = image.crop((box[0] + 10, box[1] + 2, box[2] - 10, box[3] - 2))
        colors = crop.getcolors(crop.width * crop.height)
        # Text/graphics occupy >1% of each card, not a blank background block.
        assert 1 - max(count for count, color in colors) / (crop.width * crop.height) > .01
        card_text = [entry for entry in drawn[0] if box[0] <= entry[0][0] < box[2]
                     and box[1] <= entry[0][1] < box[3]]
        assert card_text
        for xy, value, bounds in card_text:
            assert bounds[2] <= box[2] and bounds[3] <= box[3]
    assert "品質" in visible(drawn, 1148)
    return image


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_selected_production_path_real_png_and_discord_attachment(monkeypatch, phase, drawn, tmp_path):
    payload = dashboard_payload(phase)
    original = deepcopy(payload)
    selector = Mock(wraps=report.select_phase_preview)
    presenter = Mock(wraps=report.build_presentation)
    renderer = Mock(wraps=report.render_market_dashboard_chart)
    monkeypatch.setattr(report, "select_phase_preview", selector)
    monkeypatch.setattr(report, "build_presentation", presenter)
    monkeypatch.setattr(report, "render_market_dashboard_chart", renderer)
    selection, reader = phase_fixtures.select(monkeypatch, phase, payload)
    before = selection.model.evidence()
    rich = report.build_rich_report(selection.model)
    assert payload == original and selection.model.evidence() == before
    selector.assert_called_once()
    presenter.assert_called_once()
    renderer.assert_called_once_with(selection.model)
    reader.assert_called_once()
    assert [item.filename for item in rich.attachments] == ["market_dashboard.png"]
    png = rich.attachments[0].data
    image = assert_layout(png, drawn)
    (tmp_path / f"{phase}.png").write_bytes(png)
    text = visible(drawn)
    assert str(DAY) in text and "partial" in text and "authority=" in text
    assert all(identity in visible(drawn, 1012, 1138) for identity in ("SPX", "NDX", "DJI", "BTC"))
    assert "overnight_cache" in text and "-04:00" in text
    sector_pixels = image.crop((40, 610, 1560, 976)).getcolors(1520 * 366)
    colors = {color for count, color in sector_pixels}
    assert (173, 73, 61) in colors and (35, 119, 102) in colors
    # Positive bars grow right of zero; negative bars grow left of zero.
    assert image.getpixel((694, 628)) == (173, 73, 61)
    assert image.getpixel((1465, 628)) == (35, 119, 102)
    if phase == "preopen":
        assert "前一完成日官方收盤・歷史" in text
        assert "provisional" in text and "非正式成交" in text and "歷史成交排行" in text
        assert str(phase_fixtures.PREVIOUS) in visible(drawn, 426, 976)
        assert "historical_reference" in text and "24,000" in text
        assert "123,456" not in text  # actual turnover is not a preopen fact
    elif phase == "intraday":
        assert "當日實際成交" in text and "盤中候選" in text
        assert "日線族群" not in text and "日線焦點" not in text and "9999" not in text
        assert "fugle_indices_stream" in text and "actual" in text
        sectors = phase_dashboard_rows(selection.model)["sectors"]
        assert [row["rank"] for row in sectors["strong"]] == [1, 3, 5, 7, 8]
        assert [row["rank"] for row in sectors["weak"]] == [2, 4, 6]
        assert "08  當時族群7" in text and "未提供" in text
    else:
        assert "當日官方收盤" in text and "daily_sample" in text
        assert "session_final" in text and "reconciliation=partial" in text
        assert "非官方定稿" in text and "estimated" in text and "盤前預期回顧 unavailable" in text
    # Exercise real Discord multipart encoding without constructing a connection.
    body, content_type = sender.encode_rich_payload(content=rich.content, embeds=rich.embeds, attachments=rich.attachments)
    assert content_type.startswith("multipart/form-data;")
    assert b'filename="market_dashboard.png"' in body and png in body


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_missing_phase_png_retains_slots_and_never_resurrects_excluded_evidence(monkeypatch, phase, drawn, tmp_path):
    payload = dashboard_payload(phase)
    data = payload["data"]
    data["market"]["indices"]["items"] = []
    data["breadth"] = {}
    data["breadth_by_market"] = {}
    data["volume_state"] = {}
    data["screening"] = {}
    data["sample_coverage"]["sample_count"] = 0  # contradictory stale arrays must stay excluded
    data["cross_market"]["markets"]["us"]["status"] = "stale"
    data["cross_market"]["markets"]["crypto"]["status"] = "stale"
    selection, _ = phase_fixtures.select(monkeypatch, phase, payload)
    png = chart.render_market_dashboard_chart(selection.model)
    assert_layout(png, drawn)
    (tmp_path / f"{phase}-missing.png").write_bytes(png)
    text = visible(drawn)
    assert ("unavailable" if phase == "preopen" else "pending") in text
    assert "無其他已選取族群" in text and "已過期" in text
    assert "日線族群" not in text and "日線焦點" not in text and "9999" not in text
    assert "漲 未提供 / 跌 未提供 / 平 未提供" in text
    assert "+0.00%" not in text and "0 元" not in text and "90,000" not in text


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_phase_chart_long_labels_stay_inside_cards(monkeypatch, phase, drawn):
    payload = dashboard_payload(phase)
    long = "長名稱與邊界😀\n" * 100
    data = payload["data"]
    for row in data["top_industries"] + data["weak_industries"]:
        row["industry"] = row["top_stock_name"] = long
    for row in data["screening"]["hot_groups"]["groups"]:
        row["group_name"] = long
    for row in data["screening"]["intraday"]["rows"] + data["value_leaders"]:
        row["stock_name"] = long
    for block in data["cross_market"]["markets"].values():
        for row in block["assets"]:
            row["label"] = long
    selection, _ = phase_fixtures.select(monkeypatch, phase, payload)
    assert_layout(chart.render_market_dashboard_chart(selection.model), drawn)
    assert "…" in visible(drawn)


def test_postclose_pending_index_is_independent_and_daily_rankings_cannot_fall_back(monkeypatch, drawn):
    payload = dashboard_payload("postclose")
    data = payload["data"]
    data["market"]["indices"]["items"][0]["official_close_confirmed"] = False
    data["latest_trade_date"] = str(phase_fixtures.PREVIOUS)
    selection, _ = phase_fixtures.select(monkeypatch, "postclose", payload)
    assert_layout(chart.render_market_dashboard_chart(selection.model), drawn)
    left = "\n".join(value for xy, value, box in drawn[0] if xy[0] < 800 and 130 <= xy[1] < 258)
    right = "\n".join(value for xy, value, box in drawn[0] if xy[0] >= 800 and 130 <= xy[1] < 258)
    assert "pending" in left and "25,000" not in left
    assert "selected" in right and "25,000" in right and "final" in right
    assert "日線焦點" not in visible(drawn) and "日線族群" not in visible(drawn)


def test_price_event_time_is_visible_even_when_receipt_is_later(monkeypatch, drawn):
    payload = dashboard_payload("intraday")
    for row in payload["data"]["market"]["indices"]["items"]:
        row["event_time"] = f"{DAY}T10:00:00+08:00"
        row["as_of"] = f"{DAY}T10:01:00+08:00"
    selection, _ = phase_fixtures.select(monkeypatch, "intraday", payload)
    chart.render_market_dashboard_chart(selection.model)
    assert "10:00:00+08:00" in visible(drawn, 130, 258)
    assert "10:01" not in visible(drawn, 130, 258)
    assert "fugle_indices_stream" in visible(drawn, 130, 258)


def test_partial_volume_and_known_zero_are_not_missing_or_official(monkeypatch, drawn):
    payload = dashboard_payload("intraday")
    payload["data"]["volume_state"].update(current_cumulative_trade_value=None,
                                           available_cumulative_trade_value=456789)
    payload["data"]["breadth"].update(advance_count=0, decline_count=None, unchanged_count=None)
    selection, _ = phase_fixtures.select(monkeypatch, "intraday", payload)
    chart.render_market_dashboard_chart(selection.model)
    assert "可用部分成交值" in visible(drawn) and "456,789 元" in visible(drawn)
    assert "authority=estimated" in visible(drawn)
    assert "漲 0 / 跌 未提供 / 平 未提供" in visible(drawn)


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_excluded_evidence_cannot_change_png_bytes(monkeypatch, phase):
    selection, _ = phase_fixtures.select(monkeypatch, phase, dashboard_payload(phase))
    before = chart.render_market_dashboard_chart(selection.model)
    selection.model.phase_selection["excluded_evidence"] = {"market": {"indices": {"items": [
        {"index_id": "TAIEX", "value": 99999999}]}}, "top_industries": [
        {"industry": "excluded only", "average_change_pct": 99}], "screening": dashboard_payload(phase)["data"]["screening"]}
    assert chart.render_market_dashboard_chart(selection.model) == before


def test_production_dry_run_uses_real_selection_render_and_attachment_without_send(monkeypatch, drawn, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    payload = dashboard_payload("intraday")
    monkeypatch.setattr(report.templates.tools, "read_market_overview", Mock(return_value=payload))
    monkeypatch.setattr(report, "settings", SimpleNamespace(discord_market_report_webhook_url="offline-dry-run"))
    engine = create_engine("sqlite://")
    monkeypatch.setattr(report, "SessionLocal", lambda: Session(engine))
    captured = {}

    def attachment_sink(target, **kwargs):
        assert target == "offline-dry-run"
        captured.update(kwargs)
        captured["encoded"] = sender.encode_rich_payload(**kwargs)
        return {"status": "dry_run", "sent": False, "sent_chunks": 0}

    monkeypatch.setattr(report, "send_discord_rich_report", attachment_sink)
    try:
        result = report.run_discord_market_report("intraday", now=datetime(2026, 10, 27, 10, 0, tzinfo=report.TAIPEI))
    finally:
        engine.dispose()
    assert result["status"] == "dry_run" and result["sent"] is False and result["sent_chunks"] == 0
    assert [item.filename for item in captured["attachments"]] == ["market_dashboard.png"]
    png = captured["attachments"][0].data
    assert_layout(png, drawn)
    (tmp_path / "production-dry-run.png").write_bytes(png)
    (tmp_path / "production-dry-run.json").write_text(json.dumps({
        "result": result, "input": "offline canonical reader fixture", "database": "in-memory sqlite",
        "transport": "local attachment sink; real multipart encoder; no connection",
        "attachments": [{"filename": item.filename, "bytes": len(item.data)} for item in captured["attachments"]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    assert png in captured["encoded"][0]
