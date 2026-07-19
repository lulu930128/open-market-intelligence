from __future__ import annotations

from typing import Any

from app.ai import answer_evidence, answer_question, answer_radar, decision_engine
from app.ai.answer_data_limits import (
    SOURCE_HEALTH_RESOURCE_LABELS_EN,
    SOURCE_HEALTH_RESOURCE_LABELS_JA,
    append_source_health_data_limits,
    apply_confidence_cap,
    confidence_cap_from_evidence,
    filter_soft_data_gap_texts,
    generic_data_limits,
    human_missing_data_limit,
    llm_text_is_soft_data_gap,
    localized_data_limit_warning,
    source_health_data_limits,
    source_health_resource_label,
    warning_is_data_limit,
)
from app.ai.answer_localization import (
    analysis_horizon_label,
    append_unique_texts,
    confidence_label,
    consumer_detail_from_llm_report,
    consumer_text,
    detail_labels,
    pct_text,
    response_is_english,
    response_is_japanese,
    response_locale,
    stance_label,
    target_fallback_label,
    text_labels,
    text_list,
    text_value,
    undecided_label,
)
from app.ai.answer_scenarios import (
    counter_evidence_from_levels,
    position_scenarios_from_decision,
    scenario_plan_from_levels,
)


SUMMARY_LIMIT_DEFAULT = 3
RADAR_BUCKET_LABELS_EN = answer_radar.RADAR_BUCKET_LABELS_EN
RADAR_BUCKET_LABELS_JA = answer_radar.RADAR_BUCKET_LABELS_JA
RADAR_ACTION_LABELS_EN = answer_radar.RADAR_ACTION_LABELS_EN
RADAR_ACTION_LABELS_JA = answer_radar.RADAR_ACTION_LABELS_JA
RADAR_SIGNAL_LABELS_EN = answer_radar.RADAR_SIGNAL_LABELS_EN
RADAR_SIGNAL_LABELS_JA = answer_radar.RADAR_SIGNAL_LABELS_JA
RADAR_SIGNAL_TEXT_EN = answer_radar.RADAR_SIGNAL_TEXT_EN
RADAR_SIGNAL_TEXT_JA = answer_radar.RADAR_SIGNAL_TEXT_JA
RADAR_STANCE_LABELS_EN = answer_radar.RADAR_STANCE_LABELS_EN
RADAR_STANCE_LABELS_JA = answer_radar.RADAR_STANCE_LABELS_JA
radar_bucket_label = answer_radar.radar_bucket_label
radar_action_label = answer_radar.radar_action_label
radar_signal_label = answer_radar.radar_signal_label
radar_stance_label = answer_radar.radar_stance_label

english_revenue_summary = answer_evidence.english_revenue_summary
japanese_revenue_summary = answer_evidence.japanese_revenue_summary
english_volatility_summary = answer_evidence.english_volatility_summary
japanese_volatility_summary = answer_evidence.japanese_volatility_summary
english_indicator_quality_warnings = answer_evidence.english_indicator_quality_warnings
japanese_indicator_quality_warnings = answer_evidence.japanese_indicator_quality_warnings
english_data_limit_text = answer_evidence.english_data_limit_text
japanese_data_limit_text = answer_evidence.japanese_data_limit_text
digest_summary_lines = answer_evidence.digest_summary_lines
technical_level_summary_lines = answer_evidence.technical_level_summary_lines
english_entry_decision_with_levels = answer_evidence.english_entry_decision_with_levels
english_entry_risk_text = answer_evidence.english_entry_risk_text
japanese_entry_decision_with_levels = answer_evidence.japanese_entry_decision_with_levels
english_trend_view_with_levels = answer_evidence.english_trend_view_with_levels
decision_evidence_summary_lines = answer_evidence.decision_evidence_summary_lines
decision_evidence_risk_lines = answer_evidence.decision_evidence_risk_lines
decision_evidence_data_lines = answer_evidence.decision_evidence_data_lines

build_position_decision_consumer_answer = answer_question.build_position_decision_consumer_answer
build_question_aware_consumer_answer = answer_question.build_question_aware_consumer_answer

def build_llm_consumer_answer(
    *,
    report: dict[str, Any],
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    stance = text_value(report.get("stance"))
    confidence = text_value(report.get("confidence"))
    headline = (
        text_value(report.get("headline"))
        or text_value(analysis_digest.get("selected_title"))
        or text_value(target.get("label"))
        or (
            "OMI analysis is ready"
            if english
            else "OMI分析が完了しました"
            if japanese
            else "OMI 已完成分析"
        )
    )

    backend_data_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    has_backend_missing = bool(text_list(missing))
    raw_observations = text_list(report.get("key_observations"))
    raw_interpretations = text_list(report.get("interpretation"))
    raw_next_checks = text_list(report.get("next_checks"))
    raw_risks = text_list(report.get("risks"))
    raw_missing_data = text_list(report.get("missing_data"))

    observations = filter_soft_data_gap_texts(raw_observations, has_backend_missing=has_backend_missing)
    interpretations = filter_soft_data_gap_texts(raw_interpretations, has_backend_missing=has_backend_missing)
    next_checks = filter_soft_data_gap_texts(raw_next_checks, has_backend_missing=has_backend_missing)
    risks = filter_soft_data_gap_texts(raw_risks, has_backend_missing=has_backend_missing)
    missing_data = raw_missing_data if has_backend_missing else []

    summary: list[str] = []
    append_unique_texts(summary, observations[:2], limit=summary_limit)
    append_unique_texts(summary, interpretations[:2], limit=summary_limit)
    if not summary and analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    follow_up_checks = list(
        dict.fromkeys(next_checks + ([] if has_backend_missing else filter_soft_data_gap_texts(raw_missing_data, has_backend_missing=False)))
    )

    action_plan = [
        {
            "label": "Holding" if english else "保有中" if japanese else "已持有",
            "text": interpretations[0] if interpretations else (
                "Use the current conclusion as context first; do not treat one signal as confirmation."
                if english
                else "現在の結論はまず文脈として扱い、単一シグナルを確認済みとは見なさないでください。"
                if japanese
                else "先依目前結論觀察，不把單一訊號當成確認。"
            ),
        },
        {
            "label": "Entry" if english else "エントリー" if japanese else "想進場",
            "text": follow_up_checks[0] if follow_up_checks else (
                "Wait for the next price, volume, or key moving-average confirmation before deciding."
                if english
                else "次の価格、出来高、または主要移動平均の確認を待ってから判断してください。"
                if japanese
                else "等下一筆價格、量能或關鍵均線確認後再判斷。"
            ),
        },
        {
            "label": "Invalidation" if english else "失効" if japanese else "失效",
            "text": risks[0] if risks else (
                "Downgrade the view if price or volume weakens."
                if english
                else "価格または出来高が弱まる場合、見通しを下方修正してください。"
                if japanese
                else "若價格或量能轉弱，原本結論需要降級。"
            ),
        },
    ]
    data_limits = list(dict.fromkeys(missing_data[:3] + backend_data_limits))[:3] if has_backend_missing else backend_data_limits
    detail_report = dict(report)
    if not has_backend_missing:
        detail_report["missing_data"] = []

    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "llm_report",
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary,
        "action_plan": action_plan,
        "risks": risks[:2],
        "data_limits": data_limits,
        "detail": consumer_detail_from_llm_report(
            detail_report,
            missing_data_label=(
                ("Data limits" if data_limits else "Next checks")
                if english
                else ("データ制約" if data_limits else "次の確認")
                if japanese
                else ("資料限制" if data_limits else "後續確認")
            ),
            response_preferences=response_preferences,
        ),
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


WATCHLIST_RADAR_RISK_BUCKETS = answer_radar.WATCHLIST_RADAR_RISK_BUCKETS
WATCHLIST_RADAR_MOMENTUM_BUCKETS = answer_radar.WATCHLIST_RADAR_MOMENTUM_BUCKETS
watchlist_radar_rows_for_intent = answer_radar.watchlist_radar_rows_for_intent
watchlist_radar_row_text = answer_radar.watchlist_radar_row_text
watchlist_radar_bucket_summary = answer_radar.watchlist_radar_bucket_summary
build_watchlist_radar_consumer_answer = answer_radar.build_watchlist_radar_consumer_answer

def build_watchlist_consumer_answer(
    *,
    human_answer: dict[str, Any],
    overview: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = human_answer.get("sections") if isinstance(human_answer.get("sections"), list) else []
    section_map: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = text_value(section.get("label"))
        text = text_value(section.get("text"))
        if label and text:
            section_map[label] = text

    lines = text_list(human_answer.get("lines")) or text_list(overview.get("answer_outline"))
    headline = section_map.get("結論") or text_value(overview.get("display")) or (lines[0] if lines else "自選股整理完成")
    summary = [
        text
        for key in ("雷達", "追蹤", "等回測", "保守")
        if (text := section_map.get(key))
    ]
    if not summary:
        summary = lines[1 : 1 + summary_limit]

    action_plan = []
    if section_map.get("雷達"):
        action_plan.append({"label": "雷達", "text": section_map["雷達"]})
    action_plan.extend([
        {"label": "優先看", "text": section_map.get("追蹤") or "先看排名與量價最明確的個股。"},
        {"label": "等回測", "text": section_map.get("等回測") or "漲幅過大的標的等回測後再確認。"},
        {"label": "保守", "text": section_map.get("保守") or "弱勢或資料不足標的先降低追蹤權重。"},
    ])
    data_limits = []
    if section_map.get("資料"):
        data_limits.append(section_map["資料"])
    data_limits.extend(
        generic_data_limits(
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )
    )

    confidence = text_value(overview.get("confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "watchlist_overview",
        "headline": headline,
        "stance": text_value(overview.get("stance")),
        "stance_label": text_value(overview.get("stance")) or "未定",
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": text_value(human_answer.get("text")) or "\n".join(lines),
        "source_human_answer": human_answer,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_digest_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    confidence = text_value(analysis_digest.get("selected_confidence"))
    headline = (
        text_value(analysis_digest.get("selected_title"))
        or text_value(analysis_digest.get("display"))
        or text_value(target.get("label"))
        or (
            "OMI data summary is ready"
            if english
            else "OMIデータ整理が完了しました"
            if japanese
            else "OMI 已完成資料整理"
        )
    )
    summary = [
        text
        for text in (
            text_value(analysis_digest.get("display")),
            text_value(analysis_digest.get("selected_summary")),
        )
        if text
    ]
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores:
        score_parts = [
            f"{analysis_horizon_label(key, response_preferences)} {decision_engine.score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            summary.append(
                ("Score: " + ", ".join(score_parts[:4]))
                if english
                else ("スコア：" + "、".join(score_parts[:4]))
                if japanese
                else ("分數：" + "、".join(score_parts[:4]))
            )

    action_plan = [
        {
            "label": "Holding" if english else "保有中" if japanese else "已持有",
            "text": (
                "Observe with the current direction and wait for the next price-volume or indicator confirmation."
                if english
                else "現在の方向を参考にし、次の価格・出来高または指標確認を待ってください。"
                if japanese
                else "先依目前方向觀察，等待下一筆量價或指標確認。"
            ),
        },
        {
            "label": "Entry" if english else "エントリー" if japanese else "想進場",
            "text": (
                "Do not rely on one score; increase weight only after price, volume, and relative market strength align."
                if english
                else "単一スコアだけに頼らず、価格・出来高・相対的な市場強度がそろってから比重を上げてください。"
                if japanese
                else "不要只看單一評分，等價格、量能與市場相對強弱同向再提高權重。"
            ),
        },
        {
            "label": "Invalidation" if english else "失効" if japanese else "失效",
            "text": (
                "Recalculate this brief view if key moving averages or momentum weaken."
                if english
                else "主要移動平均またはモメンタムが弱まる場合、この短評を再計算してください。"
                if japanese
                else "若主要均線或動能轉弱，這份短評需要重新計算。"
            ),
        },
    ]
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "analysis_digest",
        "headline": headline,
        "stance": None,
        "stance_label": undecided_label(response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": list(dict.fromkeys(summary))[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": generic_data_limits(
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        ),
        "detail": text_value(analysis_digest.get("display")) or "",
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def _futures_number(value: Any, *, signed: bool = False, suffix: str = "") -> str | None:
    if not isinstance(value, (int, float)):
        return None
    prefix = "+" if signed and value > 0 else ""
    if float(value).is_integer():
        rendered = f"{int(value):,}"
    else:
        rendered = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return f"{prefix}{rendered}{suffix}"


def build_tw_futures_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    quote = analysis_digest.get("quote") if isinstance(analysis_digest.get("quote"), dict) else {}
    daily_close = analysis_digest.get("daily_close") if isinstance(analysis_digest.get("daily_close"), dict) else {}
    institutional = (
        analysis_digest.get("institutional_position")
        if isinstance(analysis_digest.get("institutional_position"), dict)
        else {}
    )
    options = (
        analysis_digest.get("options_sentiment")
        if isinstance(analysis_digest.get("options_sentiment"), dict)
        else {}
    )
    quote_price = _futures_number(quote.get("last_price") or quote.get("price"))
    quote_time = text_value(quote.get("quote_time"))
    session = text_value(quote.get("session"))
    daily_price = _futures_number(daily_close.get("close_price"))
    daily_date = text_value(daily_close.get("trade_date"))
    foreign_oi = _futures_number(institutional.get("foreign_futures_net_oi"), signed=True)
    foreign_oi_change = _futures_number(
        institutional.get("foreign_futures_net_oi_change"),
        signed=True,
    )
    pcr_volume = _futures_number(options.get("put_call_volume_ratio_pct"), suffix="%")
    pcr_oi = _futures_number(options.get("put_call_open_interest_ratio_pct"), suffix="%")

    if english:
        quote_label = "After-hours last trade" if session == "after_hours" else "Latest session trade"
        quote_line = f"{quote_label}: {quote_price or 'missing'}" + (f" ({quote_time})" if quote_time else "")
        daily_line = f"Daily K close: {daily_price or 'missing'}" + (f" ({daily_date})" if daily_date else "")
        chips_line = (
            f"Official post-close chips: foreign futures net OI {foreign_oi or 'missing'}"
            f", daily change {foreign_oi_change or 'missing'}; PCR volume {pcr_volume or 'missing'}, OI {pcr_oi or 'missing'}."
        )
        post_close_limit = "Foreign OI and Put/Call Ratio are official daily post-close data, not live night-session changes."
    elif japanese:
        quote_label = "夜間最終約定" if session == "after_hours" else "最新セッション約定"
        quote_line = f"{quote_label}：{quote_price or '欠損'}" + (f"（{quote_time}）" if quote_time else "")
        daily_line = f"日足終値：{daily_price or '欠損'}" + (f"（{daily_date}）" if daily_date else "")
        chips_line = (
            f"公式引け後需給：海外投資家先物ネットOI {foreign_oi or '欠損'}"
            f"、前日差 {foreign_oi_change or '欠損'}；PCR出来高 {pcr_volume or '欠損'}、OI {pcr_oi or '欠損'}。"
        )
        post_close_limit = "海外投資家OIとPut/Call Ratioは公式の日次引け後データで、夜間取引中のリアルタイム変化ではありません。"
    else:
        quote_label = "夜盤最後成交" if session == "after_hours" else "最新交易時段成交"
        quote_line = f"{quote_label}：{quote_price or '缺資料'}" + (f"（{quote_time}）" if quote_time else "")
        daily_line = f"日 K 收盤：{daily_price or '缺資料'}" + (f"（{daily_date}）" if daily_date else "")
        chips_line = (
            f"官方盤後籌碼：外資期貨淨未平倉 {foreign_oi or '缺資料'}"
            f"、單日變化 {foreign_oi_change or '缺資料'}；PCR 成交量 {pcr_volume or '缺資料'}、未平倉 {pcr_oi or '缺資料'}。"
        )
        post_close_limit = "外資未平倉與 Put/Call Ratio 是官方每日盤後資料，不代表目前夜盤的即時加空或回補。"

    selected_title = text_value(analysis_digest.get("selected_title"))
    selected_summary = text_value(analysis_digest.get("selected_summary"))
    label = text_value(target.get("label")) or text_value(target.get("id")) or "TXF"
    headline = f"{label}｜{selected_title}" if selected_title else label
    generic_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    data_limits = list(dict.fromkeys([post_close_limit, *generic_limits]))[:4]
    summary = [quote_line, daily_line, chips_line]
    action_plan = [
        {
            "label": "Technical" if english else "テクニカル" if japanese else "技術面",
            "text": selected_summary
            or (
                "Use the daily trend as background and the latest-session quote as the current price axis."
                if english
                else "日足トレンドを背景、最新セッション約定を現在の価格軸として扱います。"
                if japanese
                else "以日 K 趨勢作背景，並以最新交易時段成交作為目前價格軸。"
            ),
        },
        {
            "label": "Positioning" if english else "需給" if japanese else "籌碼",
            "text": chips_line,
        },
        {
            "label": "Invalidation" if english else "失効" if japanese else "失效",
            "text": (
                "Reassess when the latest-session quote and daily technical structure stop confirming each other."
                if english
                else "最新セッション約定と日足テクニカルが一致しなくなった場合は再評価します。"
                if japanese
                else "若最新交易時段成交與日 K 技術結構不再互相確認，需重新評估。"
            ),
        },
    ]
    confidence = text_value(analysis_digest.get("selected_confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "tw_futures_contract",
        "headline": headline,
        "stance": None,
        "stance_label": undecided_label(response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": data_limits,
        "detail": "\n".join(summary),
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_compact_context_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    label = text_value(target.get("label")) or text_value(target.get("id")) or "OMI"
    counts = analysis_digest.get("slot_status_counts") if isinstance(analysis_digest.get("slot_status_counts"), dict) else {}
    ready_slots = text_list(analysis_digest.get("ready_slots"))
    problem_slots = [
        item
        for item in (analysis_digest.get("problem_slots") or [])
        if isinstance(item, dict)
    ]
    key_numbers = analysis_digest.get("key_numbers") if isinstance(analysis_digest.get("key_numbers"), dict) else {}

    status_order = ("ready", "partial", "stale", "missing", "blocked", "failed", "planned")
    status_line = "、".join(
        f"{status} {counts[status]}"
        for status in status_order
        if counts.get(status)
    )
    if english:
        status_summary = f"Slot status: {status_line or 'no declared slots'}."
        ready_summary = "Ready: " + (", ".join(ready_slots[:6]) if ready_slots else "none") + "."
        problem_summary = "Needs attention: " + (
            ", ".join(f"{item.get('key')}={item.get('status')}" for item in problem_slots[:6])
            if problem_slots
            else "none"
        ) + "."
        headline = f"{label} data status"
    elif japanese:
        status_summary = f"スロット状態：{status_line or '宣言済みスロットなし'}。"
        ready_summary = "利用可能：" + ("、".join(ready_slots[:6]) if ready_slots else "なし") + "。"
        problem_summary = "要確認：" + (
            "、".join(f"{item.get('key')}={item.get('status')}" for item in problem_slots[:6])
            if problem_slots
            else "なし"
        ) + "。"
        headline = f"{label} データ状態"
    else:
        status_summary = f"欄位狀態：{status_line or '尚未宣告欄位'}。"
        ready_summary = "可用：" + ("、".join(ready_slots[:6]) if ready_slots else "無") + "。"
        problem_summary = "需處理：" + (
            "、".join(f"{item.get('key')}={item.get('status')}" for item in problem_slots[:6])
            if problem_slots
            else "無"
        ) + "。"
        headline = f"{label} 資料狀態"

    number_parts = [
        f"{key}={value}"
        for key, value in list(key_numbers.items())[:8]
        if value is not None
    ]
    summary = [status_summary, ready_summary, problem_summary]
    if number_parts:
        summary.insert(1, " / ".join(number_parts))
    problem_limit = problem_summary if problem_slots else None
    generic_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    data_limits = list(dict.fromkeys([item for item in [problem_limit, *generic_limits] if item]))[:4]
    next_fill = next(
        (text_value(item.get("next_fill")) for item in problem_slots if text_value(item.get("next_fill"))),
        "",
    )
    if english:
        action_plan = [
            {"label": "Available", "text": ready_summary},
            {"label": "Gaps", "text": problem_summary},
            {"label": "Next", "text": next_fill or "Use the declared refresh/provider path for missing or stale slots."},
        ]
    elif japanese:
        action_plan = [
            {"label": "利用可能", "text": ready_summary},
            {"label": "不足", "text": problem_summary},
            {"label": "次", "text": next_fill or "欠損または遅延スロットは宣言済みのrefresh/provider経路で補完します。"},
        ]
    else:
        action_plan = [
            {"label": "可用", "text": ready_summary},
            {"label": "缺口", "text": problem_summary},
            {"label": "下一步", "text": next_fill or "缺失或過期欄位應走已宣告的 refresh/provider 路徑補齊。"},
        ]
    confidence = text_value(analysis_digest.get("selected_confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "context_status_summary",
        "source": "compact_context_contract",
        "headline": headline,
        "stance": None,
        "stance_label": undecided_label(response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": data_limits,
        "detail": "\n".join(summary),
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_consumer_human_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    position_decision: dict[str, Any] | None = None,
    llm_report: dict[str, Any] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if position_decision:
        answer = build_position_decision_consumer_answer(
            position_decision=position_decision,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if analysis_digest.get("kind") == "tw_futures_digest":
        answer = build_tw_futures_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if analysis_digest.get("kind") == "compact_context_status_digest":
        answer = build_compact_context_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    watchlist_radar_answer = build_watchlist_radar_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    if watchlist_radar_answer and (
        not llm_report
        or question_intent in {"entry_decision", "exit_decision", "risk_check", "trend_view"}
    ):
        return append_source_health_data_limits(
            watchlist_radar_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    question_answer = build_question_aware_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    if question_intent in {"entry_decision", "exit_decision", "trend_view"} and question_answer:
        return append_source_health_data_limits(
            question_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if llm_report:
        answer = build_llm_consumer_answer(
            report=llm_report,
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    human_answer = analysis_digest.get("human_answer") if isinstance(analysis_digest.get("human_answer"), dict) else {}
    if human_answer:
        answer = build_watchlist_consumer_answer(
            human_answer=human_answer,
            overview=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if question_answer:
        return append_source_health_data_limits(
            question_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if analysis_digest:
        answer = build_digest_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    return {}
