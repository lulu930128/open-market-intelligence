from __future__ import annotations

import builtins
from copy import deepcopy
from datetime import date
from email import policy
from email.parser import BytesParser
from io import BytesIO
import json
import traceback
from unittest.mock import Mock

import pytest

from app.dispatch import discord_market_report as report
from app.dispatch import discord_sender as sender
from app.dispatch import market_report_chart as chart
from app.dispatch.market_report_discord import render_compact_content, render_embeds
from app.dispatch.market_report_presentation import build_presentation, with_price_maps
from app.dispatch.market_report_text import render_presentation
from test_discord_market_report import NOW, evidence_preview, event_output, prepared, transport, webhook


def model(preview=None, phase="postclose"):
    return build_presentation(preview or {}, phase=phase, report_date=date(2026, 10, 2))


def multipart(body, content_type):
    return BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body)


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_detached_model_preserves_canonical_values_and_phase(evidence_preview, phase):
    original = deepcopy(evidence_preview)
    result = model(evidence_preview, phase)
    assert evidence_preview == original
    assert result.phase == phase and result.report_date == "2026-10-02"
    assert result.stance == original["metadata"]["stance"]
    assert result.volume == original["metadata"]["volume_state"]
    assert result.strong_sectors == original["metadata"]["top_industries"]
    assert result.chips == original["metadata"]["market_chips"]
    assert result.daily_sample_scope.startswith("前一已完成交易日樣本")
    evidence_preview["metadata"]["breadth"]["advance_count"] = 999
    assert result.breadth["advance_count"] == 60
    assert "999" not in render_presentation(result)


@pytest.mark.parametrize("block", [None, [], "malformed", {}])
def test_missing_model_and_embeds_safe(block):
    result = model({"metadata": block})
    assert result.as_of == "missing" and result.quality == "missing"
    assert result.indices == {} and result.chips == {}
    assert all(not group["promoted"] for group in result.cross_market_groups.values())
    sender.validate_rich_payload(embeds=render_embeds(result))


@pytest.mark.parametrize("status,warnings,missing", [
    ("stale", [], []), ("current", ["partial warning"], ["missing detail"]),
])
def test_canonical_quality_wins_over_warning_count(status, warnings, missing):
    preview = {"metadata": {"freshness": {"status": status}}, "warnings": warnings, "missing": missing}
    original = deepcopy(preview)
    result = model(preview)
    assert result.quality == status and preview == original
    assert result.evidence_axes["freshness"]["status"] == status
    assert result.full_limitations == {"warnings": warnings, "missing": missing}


@pytest.mark.parametrize("status,warnings,expected", [(None, [], "available"), ("", ["detail"], "partial"), ("  ", [], "available")])
def test_quality_fallback_only_when_canonical_status_absent(status, warnings, expected):
    assert model({"metadata": {"freshness": {"status": status}}, "warnings": warnings}).quality == expected


@pytest.mark.parametrize("current,available,label,display", [
    (None, 500_000_000, "可用部分累計成交值", "5.00 億元"),
    (600_000_000, 500_000_000, "累計成交值", "6.00 億元"),
    (0, 500_000_000, "累計成交值", "0 元"),
    (None, None, "累計成交值", "missing"),
])
def test_volume_embed_selects_available_partial_without_inventing_total(current, available, label, display):
    preview = {"metadata": {"volume_state": {
        "current_cumulative_trade_value": current, "available_cumulative_trade_value": available,
        "status": "partial", "as_of": "2026-10-02T13:30:00+08:00",
    }}}
    result = model(preview)
    before = render_presentation(result)
    field = render_embeds(result)[0]["fields"][2]
    assert field["name"] == label and field["value"].startswith(display)
    assert "部分資料" in field["value"]
    assert render_presentation(result) == before
    assert result.volume["current_cumulative_trade_value"] == current
    if current is None and available is not None:
        assert "累計成交值：missing｜可用部分 5.00 億元" in before


def test_cross_market_only_promotes_explicit_usable_nonstale(evidence_preview):
    markets = {
        key: {"status": "partial", "assets": [
            {"id": "CURRENT", "price": 1.25, "status": "current", "as_of": "2026-10-02"},
            {"id": "STALE", "price": 987654321, "status": "stale", "as_of": "2025-01-01"},
            {"id": "UNKNOWN", "price": 876543219, "status": "unknown"},
            {"id": "UNUSABLE", "price": 765432198, "status": "current", "usable": False},
        ]} for key in ("us", "jp", "kr", "resource", "crypto")}
    markets["us"]["assets"].append({"id": "DELAYED", "status": "delayed", "price": 2})
    markets["jp"]["status"] = "stale"
    evidence_preview["metadata"]["cross_market"]["markets"] = markets
    result = model(evidence_preview)
    assert result.cross_market_groups["jp"]["promoted"] == []
    assert [row["id"] for row in result.cross_market_groups["us"]["promoted"]] == ["CURRENT", "DELAYED"]
    embeds = render_embeds(result)
    visible = json.dumps(embeds, ensure_ascii=False)
    assert "987,654,321" not in visible and "876,543,219" not in visible and "765,432,198" not in visible
    cross_fields = {item["name"]: item["value"] for item in embeds[3]["fields"]}
    for name in ("日本", "韓國", "原物料"):
        assert "已過期" in cross_fields[name] and "附件" in cross_fields[name]
    assert "987,654,321" in render_presentation(result)
    assert result.evidence()["cross_market"]["markets"]["kr"]["assets"][1]["price"] == 987654321


def test_embeds_bounded_no_raw_warnings_or_engineering_fields(evidence_preview):
    evidence_preview["warnings"] = ["RAW WARNING " * 1000] * 20
    evidence_preview["metadata"]["top_industries"] *= 30
    evidence_preview["metadata"]["top_industries"][0]["industry"] = "😀" * 3000
    evidence_preview["metadata"]["market_chips"]["institutional_per_stock"]["coverage"] = {
        "universe_class": "ordinary_stock", "eligible_count": 1967, "covered_eligible_count": 1834,
        "coverage_ratio": 0.932384342,
    }
    result = model(evidence_preview)
    embeds = render_embeds(result)
    assert len(embeds) == 4
    sender.validate_rich_payload(embeds=embeds)
    text = []
    for embed in embeds:
        text.extend(embed.get(key, "") for key in ("title", "description"))
        text.append(embed.get("footer", {}).get("text", ""))
        for field in embed.get("fields", []):
            text.extend((field["name"], field["value"]))
    assert sum(len(value.encode("utf-16-le")) // 2 for value in text) <= 6000
    visible = json.dumps(embeds, ensure_ascii=False)
    assert "RAW WARNING" not in visible and "universe_class" not in visible and "ordinary_stock" not in visible
    assert "普通股母體" in visible and "1,834/1,967" in visible
    assert "RAW WARNING" in render_presentation(result)
    assert "ETF、權證或全證券市場" in render_presentation(result)


def test_evidence_excludes_config_and_redacts_webhook(evidence_preview, webhook):
    evidence_preview["config"] = {"webhook": webhook}
    evidence_preview["metadata"]["market_chips"]["config"] = {"token": webhook}
    evidence_preview["warnings"].append(webhook)
    result = model(evidence_preview)
    evidence = json.dumps(result.evidence(), ensure_ascii=False)
    assert webhook not in evidence and webhook.rsplit("/", 1)[1] not in evidence
    assert "config" not in evidence and "[redacted webhook]" in evidence
    assert webhook not in render_presentation(result)


def test_missing_pillow_fallback_runs_without_dependency(monkeypatch):
    real_import = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("synthetic dependency absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pillow)
    rich = report.build_rich_report(model(), mode="audit")
    assert [item.filename for item in rich.attachments] == ["full_report.txt", "evidence.json"]
    assert rich.model.presentation_warnings == ("Pillow 未安裝；PNG 已略過。",)
    assert "image" not in rich.embeds[0]
    evidence = json.loads(rich.attachments[1].data)
    assert evidence["presentation_warnings"]
    sender.encode_rich_payload(embeds=rich.embeds, attachments=rich.attachments)


def test_explicit_font_fallback_retains_all_other_surfaces(monkeypatch):
    monkeypatch.setattr(report, "render_market_dashboard_chart", Mock(side_effect=chart.ChartUnavailable("中文字型不可用")))
    rich = report.build_rich_report(model(), mode="audit")
    assert len(rich.embeds) == 4 and len(rich.attachments) == 2
    assert "中文字型不可用" in rich.attachments[0].data.decode()
    assert "image" not in rich.embeds[0]


def test_unexpected_render_error_propagates(monkeypatch):
    monkeypatch.setattr(report, "render_market_dashboard_chart", Mock(side_effect=RuntimeError("renderer bug")))
    with pytest.raises(RuntimeError, match="renderer bug"):
        report.build_rich_report(model())


def test_actual_png_signature_dimensions_and_missing_safe():
    from PIL import Image
    for result in (model(), model({"metadata": {"top_industries": [{"industry": "長字串" * 300}]}})):
        png = chart.render_market_dashboard_chart(result)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(png)) as image:
            assert image.size == (1600, 1200) and image.format == "PNG"
            image.load()


def test_actual_stock_png_with_backend_technical_blockers():
    from PIL import Image

    result = with_price_maps(
        model({"metadata": {"value_leaders": [{"stock_id": "TEST"}]}}),
        {},
        technical_reports={"TEST": {"data": {"input_quality": {
            "contract_version": "tw.technical.input_quality.v3",
            "decision_usable": False,
            "day_state_blockers": [{
                "trade_date": "2026-09-22",
                "state": "TRADE_ACTIVITY_WITHOUT_PRICE",
                "reasons": ["ALTERNATE_OFFICIAL_PRICE_REQUIRED"],
            }],
        }}}},
    )
    assert not result.stock_analysis[0]["technical_available"]
    assert result.stock_analysis[0]["technical_blockers"]
    png = chart.render_stock_analysis_chart(result)
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1600, 1960) and image.format == "PNG"
        image.load()


def test_actual_missing_font_and_renderer_bug(monkeypatch):
    import PIL
    monkeypatch.setattr(chart, "FONT_PATHS", ())
    with pytest.raises(chart.ChartUnavailable, match="中文字型"):
        chart.render_market_dashboard_chart(model())
    monkeypatch.setattr(chart.Path, "is_file", Mock(side_effect=RuntimeError("renderer bug")))
    monkeypatch.setattr(chart, "FONT_PATHS", ("synthetic-font.ttf",))
    with pytest.raises(RuntimeError, match="renderer bug"):
        chart.render_market_dashboard_chart(model())


def test_multipart_metadata_reference_and_mentions(webhook, transport):
    # Transport accepts opaque bytes; this is deliberately not a PNG rendering test.
    attachments = [sender.DiscordAttachment("market_dashboard.png", b"opaque-transport-fixture", "image/png"),
                   sender.DiscordAttachment("full_report.txt", "完整文字".encode(), "text/plain; charset=utf-8"),
                   sender.DiscordAttachment("evidence.json", b"{}", "application/json; charset=utf-8")]
    embeds = render_embeds(model(), png_filename="market_dashboard.png")
    result = sender.send_discord_rich_report(webhook, embeds=embeds, attachments=attachments)
    transport.return_value.request.assert_called_once()
    call = transport.return_value.request.call_args
    parts = list(multipart(call.kwargs["body"], call.kwargs["headers"]["Content-Type"]).iter_parts())
    assert parts[0].get_param("name", header="Content-Disposition") == "payload_json"
    payload = json.loads(parts[0].get_payload(decode=True))
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["image"]["url"] == "attachment://market_dashboard.png"
    assert payload["attachments"] == [{"id": index, "filename": item.filename} for index, item in enumerate(attachments)]
    for index, (part, attachment) in enumerate(zip(parts[1:], attachments)):
        assert part.get_param("name", header="Content-Disposition") == f"files[{index}]"
        assert part.get_filename() == attachment.filename and part.get_payload(decode=True) == attachment.data
        assert part.get_content_type() == attachment.content_type.split(";")[0]
    assert result["sent_chunks"] == result["total_chunks"] == 1


def test_rich_without_attachments_uses_json(webhook, transport):
    sender.send_discord_rich_report(webhook, content="😀" * 1000, embeds=[{"title": "研究"}])
    call = transport.return_value.request.call_args
    assert call.kwargs["headers"]["Content-Type"] == "application/json"
    assert json.loads(call.kwargs["body"])["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize("kwargs", [
    {"content": "😀" * 1001}, {"embeds": [{"title": "x"}] * 11},
    {"embeds": [{"title": "x" * 257}]}, {"embeds": [{"description": "x" * 4097}]},
    {"embeds": [{"description": "x" * 3001}] * 2},
    {"embeds": [{"fields": [{"name": "x", "value": "x"}] * 26}]},
    {"embeds": [{"fields": [{"name": "x" * 257, "value": "x"}]}]},
    {"embeds": [{"fields": [{"name": "x", "value": "x" * 1025}]}]},
    {"embeds": [{"footer": {"text": "x" * 2049}}]},
    {"embeds": [{"author": {"name": "x" * 257}}]},
    {"embeds": [{"image": {"url": "attachment://missing.png"}}]},
    {"embeds": [{"title": "\ud800"}]}, {"embeds": [{"unknown": "x"}]},
    {"attachments": [sender.DiscordAttachment("../file.txt", b"x", "text/plain; charset=utf-8")]},
    {"attachments": [sender.DiscordAttachment('bad\r\nname', b"x", "image/png")]},
    {"attachments": [sender.DiscordAttachment("x.png", b"x", "image/png")] * 5},
    {"attachments": [sender.DiscordAttachment("x.png", b"x", "image/png")] * 2},
    {"attachments": [sender.DiscordAttachment("x.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")]},
    {"attachments": [sender.DiscordAttachment(f"{i}.png", b"x" * (2 * 1024 * 1024), "image/png") for i in range(4)]},
])
def test_invalid_rich_payload_never_connects(webhook, transport, kwargs):
    with pytest.raises(sender.DiscordDeliveryError, match="invalid rich payload"):
        sender.send_discord_rich_report(webhook, **kwargs)
    transport.assert_not_called()


@pytest.mark.parametrize("status", [301, 429, 500])
def test_rich_http_failure_never_retries(webhook, transport, status, event_output):
    transport.return_value.getresponse.return_value.status = status
    with pytest.raises(sender.DiscordDeliveryError) as caught:
        sender.send_discord_rich_report(webhook, embeds=render_embeds(model()))
    assert caught.value.outcome == ("unknown" if status >= 500 else "failed")
    assert transport.call_count == 1 and transport.return_value.request.call_count == 1
    transport.return_value.getresponse.return_value.read.assert_not_called()
    logged = event_output.getvalue()
    assert "stage=transport_response" in logged and f"status_code={status}" in logged
    assert "stage=transport_failed" in logged and "stage=transport_sent" not in logged


@pytest.mark.parametrize("operation", ["request", "getresponse", "close"])
def test_rich_network_error_has_no_secret_chain(webhook, transport, caplog, event_output, operation):
    error = OSError(10060, webhook)
    error.winerror = 10060
    getattr(transport.return_value, operation).side_effect = error
    with pytest.raises(sender.DiscordDeliveryError) as caught:
        sender.send_discord_rich_report(webhook, content="報表")
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert caught.value.cause_type == type(error).__name__
    assert caught.value.cause_errno == 10060 and caught.value.cause_winerror == 10060
    logged = event_output.getvalue()
    assert "stage=transport_start" in logged and "stage=transport_failed" in logged
    assert f"exception_type={type(error).__name__} errno=10060 winerror=10060" in logged
    assert "stage=transport_sent" not in logged
    diagnostic = "".join(traceback.format_exception(caught.value)) + caplog.text + logged
    assert webhook not in diagnostic and webhook.rsplit("/", 1)[1] not in diagnostic
    assert transport.call_count == 1


def test_transport_success_events_share_scheduler_context(webhook, transport, event_output):
    from app.dispatch.discord_report_events import report_event_context
    with report_event_context("intraday"):
        sender.send_discord_rich_report(webhook, content="report")
    lines = event_output.getvalue().splitlines()
    assert [line.split("stage=")[1].split()[0] for line in lines] == [
        "transport_start", "transport_response", "transport_sent"]
    assert len({line.split("run_id=")[1].split()[0] for line in lines}) == 1
    assert all("phase=intraday" in line for line in lines)
    assert webhook not in event_output.getvalue()


def test_orchestration_closes_db_before_render_and_network(prepared, monkeypatch):
    def render(detached):
        prepared.sessions.return_value.__exit__.assert_called_once()
        raise chart.ChartUnavailable("無中文字型")

    def send(*args, **kwargs):
        prepared.sessions.return_value.__exit__.assert_called_once()
        assert len(kwargs["embeds"]) == 4 and len(kwargs["attachments"]) == 2
        return {"status": "sent", "sent_chunks": 1, "total_chunks": 1}

    monkeypatch.setattr(report, "render_market_dashboard_chart", render)
    prepared.send.side_effect = send
    result = report.run_discord_market_report("postclose", now=NOW, mode="audit")
    assert result["presentation_warnings"] == ["無中文字型"]
    prepared.preview.assert_called_once()
    prepared.send.assert_called_once()


def test_orchestration_transport_failure_never_falls_back(prepared, monkeypatch):
    plain = Mock()
    monkeypatch.setattr(sender, "send_discord_report", plain)
    prepared.send.side_effect = sender.DiscordDeliveryError("transport failure", outcome="unknown")
    with pytest.raises(sender.DiscordDeliveryError):
        report.run_discord_market_report("postclose", now=NOW)
    prepared.send.assert_called_once()
    prepared.preview.assert_called_once()
    plain.assert_not_called()


@pytest.mark.parametrize("mode", ["compact", "audit"])
def test_report_modes_actual_pngs_and_single_request(evidence_preview, webhook, transport, mode):
    from PIL import Image

    rich = report.build_rich_report(model(evidence_preview), mode=mode)
    assert rich.mode == mode
    names = [item.filename for item in rich.attachments]
    assert names[:3] == ["market_dashboard.png", "stock_analysis.png", "technology_pulse.png"]
    assert names[3:] == (["full_report.txt", "evidence.json"] if mode == "audit" else [])
    for item in rich.attachments[:3]:
        assert item.data.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(item.data)) as png:
            assert png.size == (1600, 1960 if item.filename == "stock_analysis.png" else 1800 if item.filename == "technology_pulse.png" else 1200) and png.format == "PNG"
            png.load()
    assert len(rich.embeds) == (4 if mode == "audit" else 0)
    assert bool(rich.content) == (mode == "compact")
    sender.send_discord_rich_report(webhook, content=rich.content, embeds=rich.embeds, attachments=rich.attachments)
    transport.return_value.request.assert_called_once()
    call = transport.return_value.request.call_args
    parts = list(multipart(call.kwargs["body"], call.kwargs["headers"]["Content-Type"]).iter_parts())
    payload = json.loads(parts[0].get_payload(decode=True))
    assert payload["allowed_mentions"] == {"parse": []}
    if mode == "compact":
        assert payload["embeds"] == [] and "attachment://" not in json.dumps(payload)
    else:
        assert payload["embeds"][0]["image"]["url"] == "attachment://market_dashboard.png"
        assert json.loads(rich.attachments[-1].data)["chips"] == rich.model.chips


@pytest.mark.parametrize("current,available,expected", [
    (None, 500_000_000, "可用部分成交值｜5.00 億元"),
    (600_000_000, 500_000_000, "成交值｜6.00 億元"),
    (0, 500_000_000, "成交值｜0 元"), (None, None, "成交值｜資料不足"),
])
def test_compact_summary_reader_fields_and_partial_value(evidence_preview, current, available, expected):
    metadata = evidence_preview["metadata"]
    metadata["volume_state"].update(current_cumulative_trade_value=current, available_cumulative_trade_value=available)
    for key in ("top_industries", "weak_industries"):
        metadata[key] = [{"industry": f"族群{i}", "average_change_pct": i} for i in range(5)]
    evidence_preview["warnings"] = ["RAW canonical universe_class as_of WARNING"]
    content = render_compact_content(model(evidence_preview))
    for term in ("OMI 台股盤後分析", "TAIEX", "TPEX", "廣度", "官方法人", "TWSE 1.00 億元", "品質", expected):
        assert term in content
    for forbidden in ("RAW", "canonical", "universe_class", "as_of", "強勢｜", "弱勢｜", "族群0", "族群3", "族群4", "TXT", "JSON", "missing"):
        assert forbidden not in content
    assert "已過期" in content  # Do not erase canonical index freshness.
    assert len(content.encode("utf-16-le")) // 2 < 1900


def test_compact_hostile_labels_remain_bounded(evidence_preview):
    evidence_preview["metadata"]["top_industries"] = [{"industry": "😀" * 3000}] * 5
    content = render_compact_content(model(evidence_preview))
    sender.validate_rich_payload(content=content, embeds=[])
    assert "官方法人" in content and "品質" in content


@pytest.mark.parametrize("unavailable", ["pillow", "font"])
def test_compact_unavailable_images_content_only_once(prepared, monkeypatch, unavailable):
    if unavailable == "font":
        monkeypatch.setattr(chart, "FONT_PATHS", ())
    else:
        real_import = builtins.__import__

        def without_pillow(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("synthetic dependency absence")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", without_pillow)
    result = report.run_discord_market_report("postclose", now=NOW)
    assert result["mode"] == "compact" and result["presentation_warnings"]
    prepared.send.assert_called_once()
    kwargs = prepared.send.call_args.kwargs
    assert kwargs["content"] and kwargs["embeds"] == [] and kwargs["attachments"] == []
    assert "PNG" not in kwargs["content"] and "Pillow" not in kwargs["content"]
    sender.validate_rich_payload(**kwargs)


def test_default_orchestration_compact_and_invalid_mode(prepared):
    with pytest.raises(ValueError, match="mode"):
        report.run_discord_market_report("postclose", now=NOW, mode="invalid")
    prepared.preview.assert_not_called()
    result = report.run_discord_market_report("postclose", now=NOW)
    prepared.send.assert_called_once()
    kwargs = prepared.send.call_args.kwargs
    assert result["mode"] == "compact" and kwargs["embeds"] == []
    assert [a.filename for a in kwargs["attachments"]] == ["market_dashboard.png", "stock_analysis.png", "technology_pulse.png"]


def test_radar_deduplicates_and_preserves_canonical_coverage(evidence_preview, monkeypatch):
    from PIL import ImageDraw
    from app.dispatch.market_report_presentation import stock_radar_items, sector_radar_rows

    stock = {"stock_id": "2330", "stock_name": "台積電", "trade_value": 100_000_000, "change_pct": 1.25}
    evidence_preview["metadata"]["value_leaders"] = [stock, stock]
    evidence_preview["metadata"]["top_gainers"] = [stock, {**stock, "stock_id": "2317", "stock_name": "鴻海"}]
    # Isolate buy/sell reasons here; the dashboard priority test covers a stock
    # present in all three daily rankings and the resulting three-reason cap.
    evidence_preview["metadata"]["top_losers"] = []
    block = evidence_preview["metadata"]["market_chips"]["institutional_per_stock"]
    block.update(coverage={"eligible_count": 1967, "covered_eligible_count": 1834, "coverage_ratio": 1834 / 1967,
                           "source_out_of_universe_count": 999},
                 top_net_buy=[{**stock, "total_institutional_net": 10000}] * 5,
                 top_net_sell=[{"stock_id": "2303", "stock_name": "聯電", "total_institutional_net": -3000}] * 4,
                 source_out_of_universe=[{"stock_id": "ETF999", "stock_name": "排除商品"}])
    detached = model(evidence_preview)
    items = stock_radar_items(detached)
    ids = [item["stock_id"] for item in items]
    assert ids.count("2330") == 1 and ids.count("2317") == 1 and ids.count("2303") == 1
    assert len(items) <= 8 and all(len(item["reason_tags"]) <= 3 for item in items)
    assert next(item for item in items if item["stock_id"] == "2330")["reason_tags"] == ["成交前列", "漲幅前列", "法人淨買"]
    assert next(item for item in items if item["stock_id"] == "2303")["reason_tags"] == ["法人淨賣"]
    assert all(len(rows) <= 6 for rows in sector_radar_rows(detached).values())
    captured = []
    real_text = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        captured.append(text)
        return real_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    chart.render_market_dashboard_chart(detached)
    chart.render_stock_analysis_chart(detached)
    visible = "\n".join(captured)
    for term in ("強勢族群", "弱勢族群", "成交前列", "漲幅前列", "法人淨買", "法人淨賣", "普通股母體 1,834/1,967", "93.2%"):
        assert term in visible
    for term in ("ETF999", "排除商品", "canonical", "universe_class", "技術分析位置", "breakout", "support", "技術證據未提供"):
        assert term not in visible
    assert detached.radar == {}


def test_radar_missing_safe_and_optional_evidence(monkeypatch, webhook):
    from PIL import Image, ImageDraw

    captured = []
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", lambda self, xy, text, **kwargs: captured.append(text))
    png = chart.render_market_dashboard_chart(model())
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1600, 1200)
    assert "資料不足" in captured
    assert "missing" not in " ".join(captured)
    radar = {"status": "missing", "warnings": [webhook], "config": {"token": webhook}}
    preview = {"metadata": {"radar": radar}}
    detached = model(preview)
    radar["status"] = "current"
    assert detached.radar["status"] == "missing"
    assert "config" not in detached.evidence()["radar"]
    assert webhook not in json.dumps(detached.evidence())
