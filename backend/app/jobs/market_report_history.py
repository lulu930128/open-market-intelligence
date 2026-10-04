"""Discord preparation: frozen selection -> common readiness -> receipt."""
from datetime import date, datetime

from app.dispatch.discord_market_report import build_report_selection
from app.jobs.tw_technical_input_readiness import prepare_taiwan_technical_inputs


def prepare_discord_market_report_history(
    db, phase: str, local_now: datetime, evidence_time_mode: str = "live", bars: int = 90,
) -> dict:
    if bars != 90:
        raise ValueError("Discord report history preparation requires bars=90.")
    selection = build_report_selection(db, phase=phase, local_now=local_now,
                                       evidence_time_mode=evidence_time_mode)
    selected = [item["stock_id"] for item in selection.model.stock_radar[:8]]
    cap = selection.model.evidence_axes.get("daily_sample_cap")
    to_date = date.fromisoformat(cap) if cap else selection.local_now.date()
    receipt = prepare_taiwan_technical_inputs(db, stock_ids=selected, to_date=to_date, bars=bars) if selected else {
        "status": "ready", "selected": [], "attempted": [], "repaired": [], "unresolved": [], "results": []}
    return {**receipt, "selection": selection}
