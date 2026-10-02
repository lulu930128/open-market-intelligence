"""TW market-overview delivery orchestration; market semantics stay in owners."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.dispatch import templates
from app.dispatch.market_report_text import render_sections, report_limitations
from app.dispatch.discord_sender import DiscordDeliveryError, send_discord_report
from app.market.calendar_status import build_taiwan_calendar_status


ReportPhase = Literal["preopen", "intraday", "postclose"]
PHASE_LABELS = {"preopen": "盤前", "intraday": "盤中", "postclose": "盤後"}
TAIPEI = ZoneInfo("Asia/Taipei")


def render_market_report(preview: dict[str, Any], *, phase: ReportPhase, now: datetime) -> str:
    if phase not in PHASE_LABELS:
        raise ValueError("Unsupported Discord market report phase.")
    label = PHASE_LABELS[phase]
    if now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    warnings, missing = report_limitations(preview)
    metadata = preview.get("metadata") if isinstance(preview.get("metadata"), dict) else {}
    breadth = metadata.get("breadth") if isinstance(metadata.get("breadth"), dict) else {}
    quality = "partial" if warnings or missing else "available" if metadata else "missing"
    lines = [
        f"# OMI 台股{label}分析｜{now.astimezone(TAIPEI):%Y-%m-%d}",
        f"派報時段：{label}（{phase}）｜Asia/Taipei",
        f"as_of：{preview.get('as_of') or 'missing（資料時間不足）'}",
        f"證據 session：{breadth.get('market_session') or 'missing'} / "
        f"{breadth.get('session_semantics') or 'missing'}",
        f"資料品質：{quality}｜{len(warnings)} warnings｜{len(missing)} missing",
    ]
    lines.extend(["", render_sections(preview, phase=phase, report_date=now.astimezone(TAIPEI).date())])
    return "\n".join(lines)


def run_discord_market_report(
    phase: ReportPhase, *, now: datetime | None = None,
) -> dict[str, Any]:
    if phase not in PHASE_LABELS:
        raise ValueError("Unsupported Discord market report phase.")
    if now is not None and now.tzinfo is None:
        raise ValueError("Discord report time must be timezone-aware.")
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    webhook_url = settings.discord_market_report_webhook_url
    if not webhook_url or not webhook_url.strip():
        raise DiscordDeliveryError("secret not configured")
    calendar = build_taiwan_calendar_status(now=local_now)
    if calendar.get("is_trading_day") is not True or calendar.get("calendar_limit"):
        return {
            "status": "skipped", "phase": phase,
            "reason": "non_trading_day" if calendar.get("is_trading_day") is False else "calendar_unverified",
            "report_date": local_now.date().isoformat(), "sent_chunks": 0,
        }
    with SessionLocal() as db:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("PRAGMA query_only=ON"))
        preview = templates.build_market_overview_preview(db, market="tw")
        content = render_market_report(preview, phase=phase, now=local_now)
    # Release the DB connection before transport. No SMTP model or persistence.
    result = send_discord_report(webhook_url, content)
    return {
        **result, "phase": phase, "report_date": local_now.date().isoformat(),
        "as_of": preview.get("as_of"),
        "warning_count": len(preview.get("warnings") or []),
        "missing_count": len(preview.get("missing") or []),
    }
