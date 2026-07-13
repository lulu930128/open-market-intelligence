from __future__ import annotations

from typing import Any

from app.ai import decision_engine
from app.ai.answer_localization import response_is_english, response_is_japanese


SUMMARY_LIMIT_DEFAULT = 3


def scenario_plan_from_levels(
    *,
    question_intent: str,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    score: float | None,
    weak_evidence: bool,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if not fields or weak_evidence:
        return []
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    latest = fields.get("latest")
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")
    chase = fields.get("chase")
    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    price_position = decision_engine.entry_price_position(numbers)
    score_bullish = score is not None and score >= 2
    scenarios: list[dict[str, str]] = []
    if preferred:
        if english:
            if question_intent == "entry_decision":
                text = f"Treat a retest of {preferred} as watchable only if price stabilizes and volume does not expand into weakness."
            elif question_intent == "risk_check":
                text = f"If a retest of {preferred} fails, raise the risk level and reduce exposure or wait for a reclaim."
            else:
                text = f"During a retest of {preferred}, watch whether volume contracts and momentum holds; support matters only if it holds."
            scenarios.append({"label": "Support retest", "text": text})
        elif japanese:
            if question_intent == "entry_decision":
                text = f"{preferred} への押し目は、価格が安定し出来高が弱さ方向に膨らまない場合だけ監視対象にしてください。"
            elif question_intent == "risk_check":
                text = f"{preferred} の押し目が守れない場合はリスクを上げ、先にポジションを落とすか回復を待ってください。"
            else:
                text = f"{preferred} の押し目では、出来高が落ち着きモメンタムが維持されるかを確認してください。守れて初めてサポートとして扱えます。"
            scenarios.append({"label": "押し目確認", "text": text})
        else:
            if question_intent == "entry_decision":
                text = f"回測 {preferred} 且止跌、量能沒有放大轉弱，才把它視為買點觀察；沒有守住就不低接。"
            elif question_intent == "risk_check":
                text = f"若回測 {preferred} 無法守住，風險等級要上調，先降低部位或等待收復。"
            else:
                text = f"回測 {preferred} 時看量能是否收斂、動能是否守住；守住才代表支撐有效。"
            scenarios.append({"label": "回測支撐", "text": text})
    elif latest:
        scenarios.append(
            {
                "label": "Range watch" if english else "レンジ監視" if japanese else "盤整觀察",
                "text": (
                    f"Use latest {latest} as a reference, but do not treat one close as support; wait for volume and momentum confirmation."
                    if english
                    else f"最新値 {latest} を基準にしますが、1本の終値だけをサポート扱いせず、出来高とモメンタムの確認を待ってください。"
                    if japanese
                    else f"以現價 {latest} 當觀察基準，但不把單一收盤價當支撐；要等量能與動能同步確認。"
                ),
            }
        )
    if breakout:
        if english:
            if question_intent == "entry_decision":
                text = f"After a break and hold above {breakout}, entry logic shifts from buying a pullback to buying a successful retest."
            else:
                text = f"A break and hold above {breakout} supports swing extension; a fast drop back below it is a false breakout."
            scenarios.append({"label": "Breakout extension", "text": text})
        elif japanese:
            if question_intent == "entry_decision":
                text = f"{breakout} を突破して維持した後は、押し目買いではなく突破後の再テスト成功を買う形に切り替えます。"
            else:
                text = f"{breakout} を突破して維持できればスイング延長を支持します。すぐ下に戻る場合はダマシです。"
            scenarios.append({"label": "ブレイク継続", "text": text})
        else:
            if question_intent == "entry_decision":
                text = f"突破 {breakout} 並站穩後，買點邏輯要從低接改成突破後回測不破。"
            else:
                text = f"突破 {breakout} 並站穩，才代表波段延伸；若突破後快速跌回，視為假突破。"
            scenarios.append({"label": "突破延伸", "text": text})
    elif chase:
        scenarios.append(
            {
                "label": "Extended zone" if english else "過熱圏" if japanese else "偏熱延伸",
                "text": (
                    f"Near or above {chase}, treat the move as extended; do not treat the chase zone as new support."
                    if english
                    else f"{chase} 付近または上では上げ過ぎとして扱い、追いかけ買いの価格帯を新しいサポートとは見なしません。"
                    if japanese
                    else f"接近或高於 {chase} 時，先視為偏熱區；不要把追價區當新的支撐。"
                ),
            }
        )
    guardrail = invalidation or stop
    if guardrail:
        if english:
            text = (
                f"Below {guardrail}, downgrade the bullish thesis and defend first before recalculating."
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"If price cannot reclaim {guardrail}, the weak thesis remains active; do not assume a rebound."
            )
            scenarios.append({"label": "Invalidation defense", "text": text})
        elif japanese:
            text = (
                f"{guardrail} を下回る場合、強気シナリオを下方修正し、再計算の前に防御を優先してください。"
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"{guardrail} を回復できない場合、弱いシナリオが継続します。反発を前提にしないでください。"
            )
            scenarios.append({"label": "失効防御", "text": text})
        else:
            text = (
                f"跌破 {guardrail} 後，原本偏多假設降級，先防守再重新計算。"
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"若仍站不回 {guardrail}，弱勢假設延續，不用急著預設反彈。"
            )
            scenarios.append({"label": "失效防守", "text": text})
    return scenarios[:summary_limit]


def counter_evidence_from_levels(
    *,
    question_intent: str,
    fields: dict[str, str],
    score: float | None,
    weak_evidence: bool,
    evidence_risks: list[str],
    summary_limit: int = 2,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    lines: list[str] = []
    if weak_evidence:
        lines.append(
            "When data or confidence is insufficient, do not treat the current conclusion as an executable signal."
            if english
            else "データまたは信頼度が不足している場合、現在の結論を実行可能なシグナルとして扱わないでください。"
            if japanese
            else "資料或信心不足時，不把目前結論當成可執行訊號。"
        )
    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")
    if invalidation:
        lines.append(
            f"A close below {invalidation} downgrades the original swing thesis."
            if english
            else f"{invalidation} を終値で下回る場合、元のスイングシナリオは下方修正です。"
            if japanese
            else f"收盤跌破 {invalidation}，原本波段假設需要降級。"
        )
    elif stop:
        lines.append(
            f"Below {stop}, treat the short-term structure as weakening first."
            if english
            else f"{stop} を下回る場合、短期構造はまず弱含みとして扱います。"
            if japanese
            else f"跌破 {stop}，短線結構先視為轉弱。"
        )
    if question_intent in {"entry_decision", "trend_view"} and preferred:
        lines.append(
            f"If a retest of {preferred} comes with expanding volume but price cannot hold, support absorption has failed."
            if english
            else f"{preferred} の押し目で出来高が増えたのに価格が維持できなければ、サポートの買い支えは失敗です。"
            if japanese
            else f"回測 {preferred} 量能放大但價格守不住，代表支撐承接失敗。"
        )
    if breakout:
        lines.append(
            f"If price breaks {breakout} but cannot hold and quickly falls back, breakout extension has failed."
            if english
            else f"{breakout} を突破しても維持できずすぐ戻る場合、ブレイク継続は失敗です。"
            if japanese
            else f"突破 {breakout} 後無法站穩並快速跌回，代表突破延伸失敗。"
        )
    if score is not None and score <= -2:
        lines.append(
            "When the multi-timeframe score weakens, do not keep a bullish thesis only because price looks cheaper."
            if english
            else "複数時間軸のスコアが弱い場合、価格が安く見えるだけで強気シナリオを維持しないでください。"
            if japanese
            else "多週期分數轉弱時，不應只因價格便宜就維持偏多假設。"
        )
    lines.extend(evidence_risks)
    return list(dict.fromkeys(lines))[:summary_limit]


def position_scenarios_from_decision(
    position_decision: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(position_decision, dict):
        return [], []
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    entry_price = decision_engine.numeric_data_value(position_decision.get("entry_price"))
    latest_price = decision_engine.numeric_data_value(position_decision.get("latest_price"))
    levels = position_decision.get("levels") if isinstance(position_decision.get("levels"), dict) else {}
    support_text = decision_engine.level_text(levels)
    return_pct = decision_engine.numeric_data_value(position_decision.get("unrealized_return_pct"))
    scenarios: list[dict[str, str]] = []
    if entry_price is not None and latest_price is not None:
        scenarios.append(
            {
                "label": "Near cost" if english else "コスト付近" if japanese else "成本附近",
                "text": (
                    f"Cost {decision_engine.format_price(entry_price)}, latest {decision_engine.format_price(latest_price)}; if price is still near cost, use position size and technical lines instead of one price move to decide hold or exit."
                    if english
                    else f"取得単価 {decision_engine.format_price(entry_price)}、最新 {decision_engine.format_price(latest_price)}。価格がまだコスト付近なら、1回の値動きではなくポジションサイズとテクニカルラインで保有・撤退を判断してください。"
                    if japanese
                    else f"成本 {decision_engine.format_price(entry_price)}、最新 {decision_engine.format_price(latest_price)}；若價格仍在成本附近震盪，先用部位大小與技術線決定，不用單一漲跌判斷去留。"
                ),
            }
        )
    if support_text:
        scenarios.append(
            {
                "label": "Technical defense" if english else "テクニカル防御" if japanese else "技術防守",
                "text": (
                    f"If price breaks {support_text} and momentum weakens, downgrade the position thesis and trim or execute the stop rule."
                    if english
                    else f"{support_text} を割り込みモメンタムも弱まる場合、保有シナリオを下方修正し、減らすか損切りルールを実行してください。"
                    if japanese
                    else f"若跌破 {support_text} 且動能轉弱，持倉假設要降級，先減碼或執行停損規則。"
                ),
            }
        )
    scenarios.append(
        {
            "label": "Hold condition" if english else "保有条件" if japanese else "續抱條件",
            "text": (
                "Treat it as holdable only if the retest holds, volume contracts, and price strengthens again; do not add if the rebound has no volume or cannot clear resistance."
                if english
                else "押し目を守り、出来高が落ち着き、価格が再び強まる場合だけ保有継続と見ます。出来高のない反発や抵抗線を超えられない反発では追加しないでください。"
                if japanese
                else "若回測不破、量能收斂且重新轉強，才把它視為續抱；反彈無量或站不上壓力就不要加碼。"
            ),
        }
    )
    counter: list[str] = []
    if return_pct is not None and return_pct <= -5:
        counter.append(
            "If your fixed stop rule is -5%, it has already triggered; do not use a bullish swing view to delay the stop."
            if english
            else "固定の損切りルールが -5% ならすでに発動しています。強気のスイング見通しを損切り先送りの理由にしないでください。"
            if japanese
            else "若你的固定停損規則是 -5%，目前已觸發，不應再用波段偏多作為延後停損理由。"
        )
    if support_text:
        counter.append(
            f"Breaking {support_text} and failing to reclaim it quickly means the technical stop condition is active."
            if english
            else f"{support_text} を割ってすぐ回復できなければ、テクニカル上の損切り条件が有効です。"
            if japanese
            else f"跌破 {support_text} 且無法快速收復，代表技術停損條件成立。"
        )
    counter.append(
        "If position size is too large or loss tolerance is insufficient, reduce risk even before the technical setup fully fails."
        if english
        else "ポジションが大きすぎる、または許容損失が不足している場合、テクニカル形状が完全に崩れる前でもリスクを下げてください。"
        if japanese
        else "若部位過大或可承受虧損不足，即使技術尚未失效，也要先降低風險。"
    )
    return scenarios[:summary_limit], list(dict.fromkeys(counter))[:2]


__all__ = [
    "counter_evidence_from_levels",
    "position_scenarios_from_decision",
    "scenario_plan_from_levels",
]
