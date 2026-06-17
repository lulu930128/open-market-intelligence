from __future__ import annotations

from typing import Any


SUMMARY_LIMIT_DEFAULT = 3


def numeric_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:
        return None
    return float(value)


def score_display(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{int(round(value))}"


def stance_from_score(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 2:
        return "bullish"
    if score <= -2:
        return "bearish"
    if score != 0:
        return "mixed"
    return "neutral"


def text_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def numeric_data_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number:
        return None
    return number


def format_price(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def format_signed_price(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{format_price(value)}"


def format_pct_value(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _append_unique_texts(target: list[str], values: list[str], *, limit: int) -> None:
    for value in values:
        if value in target:
            continue
        target.append(value)
        if len(target) >= limit:
            return


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def level_price_text(level: Any) -> str | None:
    if not isinstance(level, dict):
        return None
    return format_price(numeric_data_value(level.get("price")))


def zone_text(zone: Any) -> str | None:
    if not isinstance(zone, dict):
        return None
    low = numeric_data_value(zone.get("low"))
    high = numeric_data_value(zone.get("high"))
    if low is not None and high is not None:
        return f"{format_price(low)}-{format_price(high)}"
    if low is not None:
        return format_price(low)
    if high is not None:
        return format_price(high)
    return None


def zone_bounds(zone: Any) -> tuple[float | None, float | None]:
    if not isinstance(zone, dict):
        return None, None
    low = numeric_data_value(zone.get("low"))
    high = numeric_data_value(zone.get("high"))
    if low is not None and high is not None and low > high:
        return high, low
    return low, high


def technical_level_fields(levels: dict[str, Any]) -> dict[str, str]:
    if not isinstance(levels, dict) or levels.get("kind") != "technical_price_levels":
        return {}
    entry = _dict_value(levels.get("entry"))
    risk = _dict_value(levels.get("risk"))
    return {
        key: value
        for key, value in {
            "latest": format_price(numeric_data_value(levels.get("latest_price"))),
            "preferred": zone_text(entry.get("preferred_zone")),
            "aggressive": zone_text(entry.get("aggressive_zone")),
            "conservative": zone_text(entry.get("conservative_zone")),
            "chase": level_price_text(entry.get("do_not_chase_above")),
            "breakout": level_price_text(entry.get("breakout_confirm_above")),
            "stop": level_price_text(risk.get("short_stop")),
            "invalidation": level_price_text(risk.get("technical_invalidation")),
        }.items()
        if value and value != "-"
    }


def technical_level_numbers(levels: dict[str, Any]) -> dict[str, float | None]:
    if not isinstance(levels, dict) or levels.get("kind") != "technical_price_levels":
        return {}
    entry = _dict_value(levels.get("entry"))
    risk = _dict_value(levels.get("risk"))
    preferred_low, preferred_high = zone_bounds(entry.get("preferred_zone"))
    aggressive_low, aggressive_high = zone_bounds(entry.get("aggressive_zone"))
    conservative_low, conservative_high = zone_bounds(entry.get("conservative_zone"))
    chase = _dict_value(entry.get("do_not_chase_above"))
    breakout = _dict_value(entry.get("breakout_confirm_above"))
    short_stop = _dict_value(risk.get("short_stop"))
    invalidation = _dict_value(risk.get("technical_invalidation"))
    return {
        "latest": numeric_data_value(levels.get("latest_price")),
        "preferred_low": preferred_low,
        "preferred_high": preferred_high,
        "aggressive_low": aggressive_low,
        "aggressive_high": aggressive_high,
        "conservative_low": conservative_low,
        "conservative_high": conservative_high,
        "chase": numeric_data_value(chase.get("price")),
        "breakout": numeric_data_value(breakout.get("price")),
        "stop": numeric_data_value(short_stop.get("price")),
        "invalidation": numeric_data_value(invalidation.get("price")),
    }


def entry_price_position(numbers: dict[str, float | None]) -> str:
    latest = numbers.get("latest")
    if latest is None:
        return "unknown"

    invalidation = numbers.get("invalidation")
    if invalidation is not None and latest < invalidation:
        return "below_invalidation"

    stop = numbers.get("stop")
    if stop is not None and latest < stop:
        return "below_stop"

    breakout = numbers.get("breakout")
    if breakout is not None and latest >= breakout:
        return "breakout_confirmed"

    preferred_low = numbers.get("preferred_low")
    preferred_high = numbers.get("preferred_high")
    if preferred_low is not None and latest < preferred_low:
        return "below_preferred"
    if (
        preferred_low is not None
        and preferred_high is not None
        and preferred_low <= latest <= preferred_high
    ):
        return "in_preferred"
    if preferred_low is not None and preferred_high is None and latest >= preferred_low:
        return "in_preferred"
    if preferred_high is not None and preferred_low is None and latest <= preferred_high:
        return "in_preferred"

    chase = numbers.get("chase")
    if chase is not None and latest > chase:
        return "above_chase"
    if preferred_high is not None and latest > preferred_high:
        return "above_preferred"
    if chase is not None and latest <= chase:
        return "below_chase"
    return "unknown"


def entry_risk_text(fields: dict[str, str]) -> str:
    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"跌破 {fields['stop']} 先停止低接")
    if fields.get("invalidation"):
        risk_parts.append(f"跌破 {fields['invalidation']} 波段假設失效")
    return "；".join(risk_parts) + "。" if risk_parts else "若量能放大轉弱或跌回關鍵均線下方，買進假設要降級。"


def entry_confirmation_text(
    fields: dict[str, str],
    numbers: dict[str, float | None],
) -> str | None:
    latest = numbers.get("latest")
    conservative_low = numbers.get("conservative_low")
    confirmation_parts = []
    if (
        fields.get("conservative")
        and latest is not None
        and conservative_low is not None
        and conservative_low > latest
    ):
        confirmation_parts.append(f"{fields['conservative']} 視為重新轉強確認區，不是現在的低接買點")
    if fields.get("breakout"):
        confirmation_parts.append(f"突破確認 {fields['breakout']} 是趨勢轉強訊號，不是現價附近買點")
    if not confirmation_parts:
        return None
    return "；".join(confirmation_parts) + "。"


def entry_decision_summary_lines(
    fields: dict[str, str],
    numbers: dict[str, float | None],
    price_position: str,
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> list[str]:
    latest = fields.get("latest")
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    lines: list[str] = []

    if price_position == "in_preferred" and latest and preferred:
        lines.append(
            f"現價 {latest} 已落在 {preferred} 回檔觀察區；這是可觀察位置，但要等守穩與量能轉強，不是自動買點。"
        )
    elif price_position == "above_chase" and latest and chase:
        breakout = fields.get("breakout")
        next_check = f"除非有效突破 {breakout}" if breakout else "除非重新轉強"
        lines.append(f"現價 {latest} 高於追價上限 {chase}；{next_check}，否則不適合追。")
    elif price_position == "breakout_confirmed" and latest:
        breakout = fields.get("breakout")
        lines.append(
            f"現價 {latest} 已到突破確認區"
            + (f" {breakout}" if breakout else "")
            + "；買點要改看突破後是否站穩。"
        )
    elif price_position == "below_preferred" and latest and preferred:
        lines.append(f"現價 {latest} 尚未進入偏好回檔區 {preferred}；等更接近區間並止跌再評估。")
    elif price_position == "above_preferred" and latest and preferred:
        chase_text = f"、仍低於追價上限 {chase}" if chase else ""
        lines.append(f"現價 {latest} 已高於回檔觀察區 {preferred}{chase_text}；可觀察但不是低接買點。")
    elif price_position in {"below_stop", "below_invalidation"} and latest:
        lines.append(f"現價 {latest} 已跌到風控區下方；先不要把低價當成便宜。")
    elif latest:
        lines.append(f"現價 {latest}；買點需要搭配價格位置、量能與動能確認。")

    risk_text = entry_risk_text(fields)
    if risk_text:
        lines.append(risk_text)

    confirmation_text = entry_confirmation_text(fields, numbers)
    if confirmation_text:
        lines.append(confirmation_text)

    return lines[:summary_limit]


def entry_decision_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> tuple[str, list[str], list[dict[str, str]]]:
    price_position = entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    conservative = fields.get("conservative")
    score_bearish = score is not None and score <= -1
    score_bullish = score is not None and score >= 2

    if weak_evidence:
        headline = f"{target_label} 先不要直接買，資料或信心還不足"
    elif price_position == "in_preferred" and preferred:
        if score_bearish:
            headline = f"{target_label} 已在回檔觀察區，但短線偏弱，現在不是好買點"
        elif score_bullish:
            headline = f"{target_label} 已回到可觀察買點區，但仍要等守穩與量能確認"
        else:
            headline = f"{target_label} 已在回檔觀察區，先等守穩再分批評估"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} 已高於追價上限 {chase}，不建議追價"
    elif price_position == "breakout_confirmed" and fields.get("breakout"):
        headline = f"{target_label} 已到突破確認區，買點要改看突破後是否站穩"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} 還沒回到偏好買點區，先等回檔與止跌訊號"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} 已高於回檔觀察區，等回測 {preferred} 或突破確認，不建議直接追價"
    elif price_position in {"below_stop", "below_invalidation"}:
        headline = f"{target_label} 已跌到風控區，先不要低接"
    elif score_bullish:
        headline = f"{target_label} 可以列入偏多觀察，但不建議直接追價"
    elif score_bearish:
        headline = f"{target_label} 目前不建議直接買，先等價位與動能轉強"
    else:
        headline = f"{target_label} 先觀望，等方向與價位確認"

    if price_position == "in_preferred" and preferred:
        now_text = (
            f"現價 {latest} 已在 {preferred} 內，可以觀察，但短線分數偏弱，先不要直接買。"
            if score_bearish
            else f"現價 {latest} 已在 {preferred} 內，可列入買點觀察，但仍要等守穩。"
        )
        condition_parts = [f"{preferred} 守住", "量能或動能轉強"]
        if chase:
            condition_parts.append(f"若價格接近或高於 {chase}，視為追價，部位要降")
        if conservative and numbers.get("conservative_low") and numbers.get("latest"):
            if numbers["conservative_low"] > numbers["latest"]:
                condition_parts.append(f"{conservative} 改視為重新轉強確認區")
        entry_text = "；".join(condition_parts) + "。"
    elif price_position == "above_chase" and preferred:
        now_text = f"現價 {latest} 已偏離理想買點，不要把追高當成進場。"
        entry_text = (
            f"等回到 {preferred} 並止跌，或有效突破 {fields['breakout']} 後再重新評估。"
            if fields.get("breakout")
            else f"等回到 {preferred} 並止跌後再重新評估。"
        )
    elif price_position == "below_preferred" and preferred:
        now_text = f"現價 {latest} 還沒到偏好回檔區，先不用急著買。"
        entry_text = f"等價格接近 {preferred} 並出現止跌或量能回穩，再提高進場權重。"
    elif price_position == "above_preferred" and preferred:
        now_text = f"現價 {latest} 已離開 {preferred}，不要把它當低接買點。"
        entry_text = (
            f"等回測 {preferred} 守住，或有效突破 {fields['breakout']} 後再重新評估。"
            if fields.get("breakout")
            else f"等回測 {preferred} 守住後再重新評估。"
        )
        if chase:
            entry_text = entry_text.rstrip("。") + f"；若價格接近或高於 {chase}，視為追價，部位要降。"
    elif price_position in {"below_stop", "below_invalidation"}:
        now_text = f"現價 {latest} 已進風控區，低接風險高。"
        entry_text = "先等價格重新站回風控線上方，並確認量能沒有放大轉弱。"
    elif price_position == "breakout_confirmed":
        now_text = f"現價 {latest} 已接近或突破確認區，不是低接買點。"
        entry_text = "若要做，只能用突破後站穩與回測不破作條件，不能用回檔買點邏輯。"
    else:
        now_text = f"現價 {latest}；先不要只用單一分數做買進決策。"
        entry_text = "等價格、量能與主要均線或動能同向轉強後，再把進場權重提高。"

    action_plan = [
        {"label": "現在", "text": now_text},
        {"label": "進場條件", "text": entry_text},
        {"label": "風控", "text": entry_risk_text(fields)},
    ]
    summary = entry_decision_summary_lines(
        fields,
        numbers,
        price_position,
        summary_limit=summary_limit,
    )
    return headline, summary, action_plan


def trend_view_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> tuple[str, list[str], list[dict[str, str]], list[str]]:
    price_position = entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")
    chase = fields.get("chase")
    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    score_bullish = score is not None and score >= 2
    score_bearish = score is not None and score <= -2

    if weak_evidence:
        headline = f"{target_label} 方向先保留，等資料與下一筆價量確認"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} 波段偏多，但現價 {latest} 已接近追價上限 {chase}"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} 波段偏多，但現價 {latest} 已離開支撐區 {preferred}"
    elif price_position == "in_preferred" and preferred:
        headline = f"{target_label} 回到支撐觀察區，接下來看 {preferred} 能否守穩"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} 已跌破首道支撐區，先看 {preferred} 能否收回"
    elif price_position == "breakout_confirmed" and breakout:
        headline = f"{target_label} 已到突破確認區，重點看 {breakout} 之上能否站穩"
    elif price_position in {"below_stop", "below_invalidation"}:
        guardrail = invalidation or stop or "-"
        headline = f"{target_label} 已跌近風控區 {guardrail}，波段結構要重新確認"
    elif score_bullish:
        headline = f"{target_label} 波段偏多，先看支撐承接與突破延續"
    elif score_bearish:
        headline = f"{target_label} 波段偏弱，先看支撐是否失守"
    else:
        headline = f"{target_label} 多空拉扯，先看支撐壓力哪邊先表態"

    summary: list[str] = []
    if price_position == "above_chase" and chase:
        summary.append(
            f"現價 {latest} 已接近追價上限 {chase}；現價附近屬偏熱延伸，不把 {latest} 當成新的支撐。"
        )
    elif price_position == "above_preferred" and preferred:
        summary.append(
            f"現價 {latest} 仍高於支撐觀察區 {preferred}；重點是回測能否守住，不是盯著現價數字本身。"
        )
    elif price_position == "in_preferred" and preferred:
        summary.append(f"現價 {latest} 已回到支撐觀察區 {preferred}；先看是否止跌守穩。")
    elif price_position == "below_preferred" and preferred:
        summary.append(f"現價 {latest} 已跌破支撐觀察區 {preferred}；若無法快速收回，波段結構要降級。")
    elif price_position == "breakout_confirmed" and breakout:
        summary.append(
            f"現價 {latest} 已來到突破確認 {breakout} 附近；重點看站穩後是否有量能延續。"
        )
    elif price_position in {"below_stop", "below_invalidation"}:
        summary.append(f"現價 {latest} 已落入風控區；先看失效線能否收復。")
    elif latest:
        summary.append(f"現價 {latest}；趨勢判讀仍要配合支撐壓力、量能與動能一起看。")

    support_parts = []
    if preferred:
        support_parts.append(f"下方支撐先看 {preferred}")
    if breakout:
        support_parts.append(f"上方壓力 / 突破確認看 {breakout}")
    elif chase:
        support_parts.append(f"{chase} 以上屬偏熱延伸")
    if support_parts:
        summary.append("；".join(support_parts) + "。")

    risk_parts = []
    if invalidation:
        risk_parts.append(f"跌破 {invalidation} 視為波段假設失效")
    elif stop:
        risk_parts.append(f"跌破 {stop} 後短線結構會明顯轉弱")
    if risk_parts:
        summary.append("；".join(risk_parts) + "。")

    if weak_evidence:
        trend_text = "先把這次解讀當方向參考，不把單一分數或單日收盤價當成最後結論。"
    elif price_position == "above_chase" and chase:
        trend_text = f"方向仍偏多，但現價 {latest} 已在偏熱區，追價報酬比不佳。"
    elif price_position == "above_preferred" and preferred:
        trend_text = f"方向仍偏多，結構重點從追價轉成回測 {preferred} 是否守住。"
    elif price_position == "in_preferred" and preferred:
        trend_text = f"方向關鍵從追價轉成支撐承接；{preferred} 守住，波段才有續強空間。"
    elif price_position == "below_preferred" and preferred:
        trend_text = f"方向開始轉弱；若無法收回 {preferred}，原本偏多結構要先降級。"
    elif price_position == "breakout_confirmed" and breakout:
        trend_text = f"方向重點從支撐承接轉成突破延續；看 {breakout} 之上是否站穩。"
    else:
        trend_text = (
            "先用多週期分數判斷大方向，再用支撐壓力與量能確認延續性。"
            if score_bullish
            else "先看價格、量能與主要均線是否同向，避免只用單一價位下結論。"
        )

    support_text_parts = []
    if preferred:
        support_text_parts.append(f"支撐先看 {preferred}")
    if breakout:
        support_text_parts.append(f"上方先看 {breakout} 是否突破站穩")
    if chase:
        support_text_parts.append(f"接近或高於 {chase} 時視為偏熱延伸")
    if invalidation:
        support_text_parts.append(f"跌破 {invalidation} 視為波段失效")
    support_text = (
        "；".join(support_text_parts) + "。"
        if support_text_parts
        else "先看關鍵均線、前低與量能是否同向確認。"
    )

    if price_position == "above_chase" and preferred:
        observation_text = (
            f"優先等回測 {preferred} 是否守住；若直接上攻，至少要突破 {breakout} 並站穩，"
            "不要把現價區當成新的支撐。"
            if breakout
            else f"優先等回測 {preferred} 是否守住，不要把現價區當成新的支撐。"
        )
    elif price_position == "above_preferred" and preferred:
        observation_text = (
            f"觀察回測 {preferred} 時量能是否收斂、動能是否守住；若回測不破，波段延續機率較高。"
        )
    elif price_position == "in_preferred" and preferred:
        observation_text = f"觀察 {preferred} 是否止跌守穩，且量能與動能是否同步回升。"
    elif price_position == "below_preferred" and preferred:
        observation_text = f"先看能否快速收回 {preferred}；若反彈站不回去，先視為波段轉弱。"
    elif price_position == "breakout_confirmed" and breakout:
        observation_text = f"觀察突破 {breakout} 後 1-2 根 K 是否站穩，避免假突破後回到原區間。"
    elif price_position in {"below_stop", "below_invalidation"}:
        guardrail = invalidation or stop or "-"
        observation_text = f"先看價格能否收回 {guardrail} 之上，否則趨勢判斷先降級。"
    else:
        observation_text = "觀察價格、量能、均線與相對市場是否持續同向，不把單一收盤價當條件。"

    action_plan = [
        {"label": "趨勢", "text": trend_text},
        {"label": "支撐壓力", "text": support_text},
        {"label": "觀察", "text": observation_text},
    ]

    risks: list[str] = []
    if chase:
        if price_position == "above_chase":
            risks.append(f"現價已靠近或高於追價上限 {chase}，短線容易從偏熱區快速回吐。")
        else:
            risks.append(f"若續漲接近 {chase} 以上，代表偏熱延伸，不把現價區當新支撐。")
    if invalidation:
        risks.append(f"跌破 {invalidation} 後，原本波段偏多假設要降級。")
    elif stop:
        risks.append(f"跌破 {stop} 後，短線結構會明顯轉弱。")

    return headline, summary[:summary_limit], action_plan, risks[:2]


def technical_level_summary_lines(
    levels: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> list[str]:
    fields = technical_level_fields(levels)
    if not fields:
        return []

    lines: list[str] = []
    entry_parts = []
    if fields.get("latest"):
        entry_parts.append(f"現價 {fields['latest']}")
    if fields.get("preferred"):
        entry_parts.append(f"偏好回檔區 {fields['preferred']}")
    if fields.get("chase"):
        entry_parts.append(f"追價上限 {fields['chase']}")
    if fields.get("breakout"):
        entry_parts.append(f"突破確認 {fields['breakout']}")
    if entry_parts:
        lines.append("；".join(entry_parts) + "。")

    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"短線停損 {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(f"波段/技術失效 {fields['invalidation']}")
    if risk_parts:
        lines.append("；".join(risk_parts) + "。")

    context = _dict_value(levels.get("context"))
    if context.get("extended"):
        lines.append("目前位置偏熱，適合等回檔或突破確認，不把現價當成最佳買點。")
    return lines[:summary_limit]


def result_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return data


def latest_price_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    data = result_data(result)
    latest_daily = data.get("latest_daily") if isinstance(data.get("latest_daily"), dict) else {}
    for key in ("close_price", "close", "last_price", "settlement_price"):
        value = numeric_data_value(latest_daily.get(key))
        if value is not None:
            return {
                "value": value,
                "source": f"data.latest_daily.{key}",
                "as_of": latest_daily.get("trade_date"),
            }

    technical_reports = data.get("technical_reports") if isinstance(data.get("technical_reports"), dict) else {}
    for timeframe in ("today", "daily", "weekly"):
        report = technical_reports.get(timeframe) if isinstance(technical_reports.get(timeframe), dict) else {}
        value = numeric_data_value(report.get("latest_close"))
        if value is not None:
            return {
                "value": value,
                "source": f"data.technical_reports.{timeframe}.latest_close",
                "as_of": report.get("as_of"),
            }

    for chart_key in ("chart", "daily_chart"):
        chart = data.get(chart_key) if isinstance(data.get(chart_key), dict) else {}
        points = chart.get("points") if isinstance(chart.get("points"), list) else []
        for point in reversed(points):
            if not isinstance(point, dict):
                continue
            value = numeric_data_value(point.get("close") or point.get("close_price") or point.get("last_price"))
            if value is not None:
                return {
                    "value": value,
                    "source": f"data.{chart_key}.points[-1].close",
                    "as_of": point.get("time") or point.get("trade_date"),
                }

    return {}


def chart_points(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result_data(result)
    for chart_key in ("chart", "daily_chart"):
        chart = data.get(chart_key) if isinstance(data.get(chart_key), dict) else {}
        points = chart.get("points") if isinstance(chart.get("points"), list) else []
        if points:
            return [point for point in points if isinstance(point, dict)]
    return []


def position_support_levels(result: dict[str, Any]) -> dict[str, Any]:
    data = result_data(result)
    levels: dict[str, Any] = {}
    technical_reports = data.get("technical_reports") if isinstance(data.get("technical_reports"), dict) else {}
    daily_report = technical_reports.get("daily") if isinstance(technical_reports.get("daily"), dict) else {}
    for key in ("ma5", "ma20", "ma60"):
        value = numeric_data_value(daily_report.get(key))
        if value is not None:
            levels[key] = value

    lows: list[float] = []
    highs: list[float] = []
    for point in chart_points(result)[-20:]:
        low = numeric_data_value(point.get("low") or point.get("low_price") or point.get("close"))
        high = numeric_data_value(point.get("high") or point.get("high_price") or point.get("close"))
        if low is not None:
            lows.append(low)
        if high is not None:
            highs.append(high)
    if lows:
        levels["recent_low_20"] = min(lows)
    if highs:
        levels["recent_high_20"] = max(highs)
    return levels


def level_text(levels: dict[str, Any]) -> str:
    ordered = (
        ("ma20", "MA20"),
        ("recent_low_20", "20日低點"),
        ("ma60", "MA60"),
    )
    parts = [
        f"{label} {format_price(numeric_data_value(levels.get(key)))}"
        for key, label in ordered
        if numeric_data_value(levels.get(key)) is not None
    ]
    return "、".join(parts) if parts else "主要均線或前低"


def build_position_decision(
    *,
    question: str,
    position_context: dict[str, Any],
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    supplemental_data_limits: list[str] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    if not position_context.get("has_position_context"):
        return {}

    entry_price = numeric_data_value(position_context.get("entry_price"))
    latest_snapshot = latest_price_snapshot(result)
    latest_price = numeric_data_value(latest_snapshot.get("value"))
    pnl_pct = ((latest_price - entry_price) / entry_price) * 100 if entry_price and latest_price else None
    pnl_points = latest_price - entry_price if entry_price and latest_price else None
    score = numeric_score(analysis_digest.get("selected_score"))
    confidence = text_value(analysis_digest.get("selected_confidence"))
    stance = stance_from_score(score)
    score_text = score_display(score)
    target_label = text_value(target.get("label")) or text_value(target.get("id")) or "目前標的"
    topic = str(position_context.get("decision_topic") or "position")
    levels = position_support_levels(result)
    technical_level_text = level_text(levels)

    if pnl_pct is None:
        headline = f"{target_label} 可以討論停損，但目前缺少成本價或最新價格，不能直接判斷"
        direct_answer = "先不要把一般波段模板當作停損結論；請先補齊成本價、最新價與可承受虧損。"
    elif topic == "stop_loss":
        if pnl_pct <= -5:
            headline = (
                f"{target_label} 成本 {format_price(entry_price)} 目前約 {format_pct_value(pnl_pct)}，"
                "若你的停損規則是 -5% 已經觸發"
            )
            direct_answer = (
                "如果你的交易規則是固定百分比停損，現在應執行或至少減碼；"
                f"如果你採技術停損，則不要只看成本，改以 {technical_level_text} 是否失守作為條件。"
            )
        elif pnl_pct < 0:
            headline = (
                f"{target_label} 低於成本 {format_price(entry_price)}，但尚未到常見 -5% 停損線"
            )
            direct_answer = (
                "目前比較適合設定明確失效條件，而不是因為單一浮虧就立刻全出；"
                f"若跌破 {technical_level_text} 或你的最大虧損線，才把停損升級成執行。"
            )
        else:
            headline = (
                f"{target_label} 仍高於成本 {format_price(entry_price)}，停損題先轉成移動停利/防守條件"
            )
            direct_answer = (
                "目前不是成本停損情境，重點是把保護線上移；"
                f"若跌破 {technical_level_text}，再重新評估是否退出。"
            )
    elif topic in {"exit", "hold"}:
        headline = f"{target_label} 去留要分成部位風險與技術失效兩層判斷"
        direct_answer = (
            f"先看成本 {format_price(entry_price)} 與最新價 {format_price(latest_price)} 的距離，"
            f"再用 {technical_level_text} 當作技術失效線。"
        )
    else:
        headline = f"{target_label} 已辨識持倉問題，先用成本距離與技術分數分層判斷"
        direct_answer = (
            "不要直接套用一般多空模板；先確認你的成本、可承受虧損與技術失效條件。"
        )

    summary: list[str] = []
    if entry_price is not None and latest_price is not None:
        summary.append(
            f"成本 {format_price(entry_price)} / 最新 {format_price(latest_price)}，"
            f"價差 {format_signed_price(pnl_points)}，浮動約 {format_pct_value(pnl_pct)}。"
        )
    elif entry_price is not None:
        summary.append(f"已讀到成本 {format_price(entry_price)}，但最新價不足。")
    else:
        summary.append("問題有持倉/停損意圖，但未解析到明確成本價。")

    if analysis_digest:
        technical_line = text_value(analysis_digest.get("display"))
        if technical_line:
            summary.append(f"技術摘要：{technical_line}。")
    summary.append(f"停損判斷：{direct_answer}")

    action_plan = [
        {
            "label": "成本停損",
            "text": (
                f"若你的原始規則是 -5%，目前 {format_pct_value(pnl_pct)} 已到需要執行或減碼的區間。"
                if pnl_pct is not None and pnl_pct <= -5
                else "先寫下可承受最大虧損百分比，達到就執行，不再用盤中情緒改規則。"
            ),
        },
        {
            "label": "技術停損",
            "text": f"若你採技術停損，觀察 {technical_level_text}；跌破且動能轉弱時，部位假設要降級。",
        },
        {
            "label": "現在",
            "text": "先不要只看波段評分；把部位大小、可承受虧損與是否跌破技術失效線一起判斷。",
        },
    ]

    data_limits = [
        "缺少你的部位大小、原始停損規則、可承受虧損與預計持有時間。",
    ]
    _append_unique_texts(data_limits, supplemental_data_limits or [], limit=summary_limit)

    evidence_used = [
        "user_question.entry_price" if entry_price is not None else "user_question.position_intent",
        latest_snapshot.get("source") or "latest_price.missing",
        "result.data.analysis" if analysis_digest else "analysis.missing",
    ]

    return {
        "kind": "position_decision",
        "intent": "position_risk_decision",
        "question": question,
        "topic": topic,
        "target_label": target_label,
        "entry_price": entry_price,
        "latest_price": latest_price,
        "latest_price_source": latest_snapshot.get("source"),
        "latest_price_as_of": latest_snapshot.get("as_of"),
        "unrealized_return_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
        "unrealized_points": round(pnl_points, 4) if pnl_points is not None else None,
        "score": score,
        "score_display": score_text,
        "stance": stance,
        "confidence": confidence,
        "levels": levels,
        "headline": headline,
        "direct_answer": direct_answer,
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": data_limits[:2],
        "data_limits": data_limits,
        "evidence_used": evidence_used,
        "llm_status": "not_requested",
    }
