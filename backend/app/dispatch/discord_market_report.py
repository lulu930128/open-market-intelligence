"""TW market-overview delivery orchestration; market semantics stay in owners."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from time import perf_counter
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.dispatch import templates
from app.dispatch.market_report_text import render_presentation
from app.dispatch.market_report_presentation import MarketReportPresentation, PHASE_LABELS, _evidence, build_presentation, with_price_maps
from app.dispatch.market_report_discord import render_compact_content, render_embeds
from app.dispatch.market_report_chart import ChartUnavailable, render_market_dashboard_chart, render_stock_analysis_chart
from app.dispatch.discord_sender import (
    DiscordAttachment, DiscordDeliveryError, send_discord_rich_report, validate_rich_payload,
)
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.stock_price_map import build_tw_stock_price_map
from app.market.service import list_stock_ohlc_chart_data
from app.market.daily_ohlcv_platform import read_taiwan_latest_daily_evidence
from app.market.technical_report import build_stock_technical_report
from app.market.taiwan_rules import expected_daily_price_date


ReportPhase = Literal["preopen", "intraday", "postclose"]
ReportMode = Literal["compact", "audit"]
EvidenceTimeMode = Literal["live", "replay"]
TAIPEI = ZoneInfo("Asia/Taipei")


def _evidence_time_semantics(mode: EvidenceTimeMode) -> str:
    if mode not in ("live", "replay"):
        raise ValueError("Unsupported evidence time mode.")
    return "current_cache_bounded_report_date" if mode == "replay" else "strict_availability"


def render_market_report(preview: dict[str, Any], *, phase: ReportPhase, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    return render_presentation(build_presentation(preview, phase=phase, report_date=now.astimezone(TAIPEI).date()))


@dataclass(frozen=True, repr=False)
class RichMarketReport:
    model: MarketReportPresentation
    embeds: list[dict]
    attachments: list[DiscordAttachment]
    content: str
    mode: ReportMode


def build_rich_report(model: MarketReportPresentation, *, mode: ReportMode = "compact") -> RichMarketReport:
    """Project a detached model once, without DB/config/network access."""
    if mode not in ("compact", "audit"):
        raise ValueError("Unsupported Discord market report mode.")
    attachments = []
    png_filename = None
    try:
        # Build the complete set before attaching; missing Pillow/font yields
        # summary-only compact, never a partial image set or audit fallback.
        images = [("market_dashboard.png", render_market_dashboard_chart(model)),
                  ("stock_analysis.png", render_stock_analysis_chart(model))]
    except ChartUnavailable as error:
        model = replace(model, presentation_warnings=(*model.presentation_warnings, str(error)))
    else:
        png_filename = "market_dashboard.png"
        attachments.extend(DiscordAttachment(name, png, "image/png") for name, png in images)
    if mode == "audit":
        attachments.extend([
        DiscordAttachment("full_report.txt", render_presentation(model).encode("utf-8"), "text/plain; charset=utf-8"),
        DiscordAttachment("evidence.json", json.dumps(model.evidence(), ensure_ascii=False, allow_nan=False,
                                                     indent=2).encode("utf-8"), "application/json; charset=utf-8"),
        ])
    content = render_compact_content(model) if mode == "compact" else ""
    embeds = render_embeds(model, png_filename=png_filename) if mode == "audit" else []
    validate_rich_payload(content=content, embeds=embeds, attachments=attachments)
    return RichMarketReport(model, embeds, attachments, content, mode)


def read_stock_analysis_facts(
    db, *, stock_id: str, local_now: datetime, evidence_time_mode: EvidenceTimeMode = "live",
) -> tuple[dict, dict]:
    """Bounded cache-only reads through the dashboard's daily/technical owners."""
    _evidence_time_semantics(evidence_time_mode)
    daily_cap = (expected_daily_price_date(now=local_now)
                 if evidence_time_mode == "replay" else local_now.date())
    chart = list_stock_ohlc_chart_data(
        db=db, stock_id=stock_id, timeframe="daily", bars=90,
        ensure_history=False, include_intraday=False, to_date=daily_cap)
    daily_evidence = read_taiwan_latest_daily_evidence(
        db, stock_id, to_date=daily_cap,
        requested_at=local_now if evidence_time_mode == "live" else None)
    report = build_stock_technical_report(
        db=db, stock_id=stock_id, timeframe="daily", include_intraday=False,
        include_volume_pace=False, to_date=daily_cap)
    indicator = (report.get("data") or {}).get("daily_indicator") or {}
    row = daily_evidence.daily
    trade_value = row.trade_value if row else None
    if trade_value is not None:
        if not trade_value.is_finite() or trade_value != trade_value.to_integral_value():
            raise ValueError("Canonical daily trade_value must be an integral TWD amount.")
        trade_value = int(trade_value)
    # A technical observation can be older than the market row. Never attach
    # that observation's change to a different trading date.
    same_date = row is not None and _evidence(indicator.get("time")) == row.trade_date.isoformat()
    market = {
        "trade_date": row.trade_date if row else None,
        "close": float(row.close_price) if row else None,
        "price_change": float(row.price_change) if row and row.price_change is not None else None,
        "change_pct": indicator.get("change_pct") if same_date else None,
        "trade_value": trade_value,
        "volume": row.trade_volume if row else None,
        "authority": None,
        "finalization": None,
        "freshness_status": chart.get("freshness_status"),
        "expected_data_date": chart.get("expected_data_date"),
        "source_capability": "tw.daily.ohlcv",
        "selected_provider": row.provider if row else None,
        "selected_source": row.source if row else None,
        "event_at": row.event_at if row else None,
        "resolved_health": daily_evidence.resolved_health.model_dump(mode="json"),
        "dataset_health": (daily_evidence.dataset_health.model_dump(mode="json")
                           if daily_evidence.dataset_health is not None else None),
        "limitations": daily_evidence.limitations,
        "volume_unit": chart.get("volume_unit"),
        "trade_value_unit": chart.get("trade_value_unit"),
        "volume_semantics": chart.get("volume_semantics"),
        "data_quality": chart.get("data_quality"), "warnings": chart.get("warnings", []),
    }
    facts = {key: report.get(key) for key in (
        "status", "phase", "confidence", "title", "summary", "rows", "data", "missing", "warnings",
        "source_refs", "evidence_passport")}
    facts.update({"available_bars": chart.get("available_bar_count"),
                  "required_bars": chart.get("expected_minimum_bar_count"),
                  "coverage_status": chart.get("coverage_status"),
                  "coverage_limitations": chart.get("limitations", [])})
    return _evidence(market), _evidence(facts)


@dataclass(frozen=True)
class ReadonlyReportSelection:
    phase: ReportPhase
    local_now: datetime
    evidence_time_mode: EvidenceTimeMode
    model: MarketReportPresentation
    preview: dict[str, Any]


def build_report_selection(
    db, *, phase: ReportPhase, local_now: datetime, evidence_time_mode: EvidenceTimeMode = "live",
) -> ReadonlyReportSelection:
    """Select once through the canonical preview/projection, without acquisition."""
    semantics = _evidence_time_semantics(evidence_time_mode)
    if local_now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    local_now = local_now.astimezone(TAIPEI)
    replay = evidence_time_mode == "replay"
    daily_cap = expected_daily_price_date(now=local_now) if replay else None
    preview = templates.build_market_overview_preview(
        db, market="tw", **({"trade_date": daily_cap} if replay else {}))
    model = build_presentation(preview, phase=phase, report_date=local_now.date())
    model = replace(model, evidence_axes={**model.evidence_axes,
        "evidence_time_mode": evidence_time_mode, "semantics": semantics,
        **({"daily_sample_cap": daily_cap.isoformat()} if replay else {})})
    if replay:
        warning = (
            "Replay uses current_cache_bounded_report_date; it is not an immutable historical snapshot. "
            f"Taiwan daily, technical, price-map and daily rankings/sectors are bounded by {daily_cap} "
            "using the canonical daily release boundary. "
            "Current-only auxiliary evidence (indices, breadth, chips, cross-market, volume and corporate events) "
            "retains its own as_of/status and is not historical replay evidence."
        )
        model = replace(model, presentation_warnings=(*model.presentation_warnings, warning),
            compact_limitations=[*model.compact_limitations, warning],
            full_limitations={**model.full_limitations,
                "warnings": [*model.full_limitations.get("warnings", []), warning]})
    return ReadonlyReportSelection(phase, local_now, evidence_time_mode, model, preview)


def build_readonly_presentation(
    db, *, phase: ReportPhase, local_now: datetime, evidence_time_mode: EvidenceTimeMode = "live",
    selection: ReadonlyReportSelection | None = None,
):
    """Enrich the finalized selection within the caller's read-only transaction."""
    _evidence_time_semantics(evidence_time_mode)
    if local_now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    local_now = local_now.astimezone(TAIPEI)
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("PRAGMA query_only=ON"))
    if selection is None:
        selection = build_report_selection(
            db, phase=phase, local_now=local_now, evidence_time_mode=evidence_time_mode)
    else:
        if (selection.phase, selection.local_now, selection.evidence_time_mode) != (
                phase, local_now, evidence_time_mode):
            raise ValueError("Report selection context mismatch.")
    model, preview = selection.model, selection.preview
    replay = evidence_time_mode == "replay"
    daily_cap = expected_daily_price_date(now=local_now) if replay else None
    started = perf_counter()
    maps = {}
    market_facts = {}
    technical_reports = {}
    for item in model.stock_radar[:8]:
        stock_id = item["stock_id"]
        market_facts[stock_id], technical_reports[stock_id] = read_stock_analysis_facts(
            db, stock_id=stock_id, local_now=local_now, evidence_time_mode=evidence_time_mode)
        try:
            maps[stock_id] = build_tw_stock_price_map(
                db=db, stock_id=stock_id, timeframe="daily", candidate_close=None, now=local_now,
                **({"as_of_date": daily_cap} if replay else {}))
        except ValueError:
            maps[stock_id] = {"status": "missing", "decision_usable": False}
    elapsed = perf_counter() - started
    return with_price_maps(model, maps, market_facts=market_facts,
                           technical_reports=technical_reports), preview, elapsed


def run_discord_market_report(
    phase: ReportPhase, *, now: datetime | None = None, mode: ReportMode = "compact",
    evidence_time_mode: EvidenceTimeMode = "live",
    selection: ReadonlyReportSelection | None = None,
) -> dict[str, Any]:
    semantics = _evidence_time_semantics(evidence_time_mode)
    if phase not in PHASE_LABELS:
        raise ValueError("Unsupported Discord market report phase.")
    if mode not in ("compact", "audit"):
        raise ValueError("Unsupported Discord market report mode.")
    if now is not None and now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    webhook_url = settings.discord_market_report_webhook_url
    if not webhook_url or not webhook_url.strip():
        raise DiscordDeliveryError("secret not configured")
    calendar = build_taiwan_calendar_status(now=local_now)
    if calendar.get("is_trading_day") is not True or calendar.get("calendar_limit"):
        return {
            "status": "skipped", "phase": phase, "mode": mode,
            "evidence_time_mode": evidence_time_mode, "semantics": semantics,
            "reason": "non_trading_day" if calendar.get("is_trading_day") is False else "calendar_unverified",
            "report_date": local_now.date().isoformat(), "sent_chunks": 0,
        }
    with SessionLocal() as db:
        model, preview, price_map_elapsed = build_readonly_presentation(
            db, phase=phase, local_now=local_now, evidence_time_mode=evidence_time_mode,
            **({"selection": selection} if selection is not None else {}))
    # Release the DB connection before transport. No SMTP model or persistence.
    rich = build_rich_report(model, mode=mode)
    result = send_discord_rich_report(webhook_url, content=rich.content, embeds=rich.embeds, attachments=rich.attachments)
    return {
        **result, "phase": phase, "mode": mode, "report_date": local_now.date().isoformat(),
        "evidence_time_mode": evidence_time_mode, "semantics": semantics,
        "as_of": model.as_of,
        "price_map_elapsed_seconds": round(price_map_elapsed, 4),
        "enrichment_elapsed_seconds": round(price_map_elapsed, 4),
        "presentation_warnings": list(rich.model.presentation_warnings),
        "warning_count": len(preview.get("warnings") or []),
        "missing_count": len(preview.get("missing") or []),
    }
