from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.config import settings
from app.market.cross_market.snapshot_store import (
    load_latest_cross_market_context_snapshots,
    materialize_cross_market_context_batch,
)
from app.watchlists import radar_service, radar_v2_service
from app.watchlists.radar_regime_v2 import classify_market_regime
from app.watchlists.radar_rule_contract import (
    RADAR_V1_FROZEN_AT,
    RADAR_V1_LIFECYCLE_STATUS,
    RADAR_V1_RULE_VERSION,
    RADAR_V2_ACTIVE_CONTRACT,
    RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
    RADAR_V2_ACTIVE_RULE_VERSION,
    RADAR_V2_RULE_CONFIG_HASH,
    RADAR_V2_RULE_VERSION,
)
from app.watchlists.radar_shadow_v2_service import (
    _effective_at,
    _trade_date,
    evaluate_radar_v2_item,
    latest_market_regime_snapshot,
    persist_radar_v2,
)


def _direction(value: int) -> tuple[str, str]:
    if value > 0:
        return "bullish", "偏多"
    if value < 0:
        return "bearish", "偏空"
    return "neutral", "中性"


def _grade(value: str) -> tuple[str, str, str]:
    if value == "strong":
        return "strong", "強證據", "v2 證據與信心均達強證據門檻。"
    if value == "medium":
        return "medium", "中等證據", "v2 證據與信心達中等門檻。"
    if value == "weak":
        return "watch", "弱證據", "v2 有方向線索，但尚未達中等證據門檻。"
    return "watch", "證據不足", "v2 尚無足夠證據形成可操作方向。"


def _bucket_meta(bucket: str) -> dict[str, str]:
    meta = radar_service.BUCKET_META_BY_KEY.get(bucket)
    if meta is not None:
        return {
            "label": str(meta["label"]),
            "description": str(meta["description"]),
        }
    return {
        "label": bucket.replace("_", " "),
        "description": "Radar v2 分類。",
    }


def _matched_signal_keys(evaluation: Mapping[str, Any]) -> list[str]:
    contributions = [
        contribution
        for contribution in evaluation.get("signal_contributions") or []
        if isinstance(contribution, Mapping)
    ]
    contributions.sort(
        key=lambda contribution: -(
            abs(float(contribution.get("directional_raw") or 0))
            + float(contribution.get("risk_raw") or 0)
        )
    )
    return list(
        dict.fromkeys(
            str(contribution.get("signal_key") or "")
            for contribution in contributions
            if str(contribution.get("signal_key") or "")
        )
    )[:4]


def _action_label(evaluation: Mapping[str, Any]) -> str:
    grade = str(evaluation.get("evidence_grade") or "insufficient")
    direction = int(evaluation.get("direction") or 0)
    urgency = str(evaluation.get("urgency") or "low")
    risk_score = float(evaluation.get("risk_score") or 0)
    if grade == "insufficient":
        return "證據不足，等待確認"
    if direction < 0:
        return (
            "立即檢查失效與風險條件"
            if urgency == "high"
            else "優先檢查風險與支撐"
        )
    if direction > 0:
        return (
            "檢查突破與承接確認"
            if urgency == "high"
            else "等待回測或量價確認"
        )
    if risk_score >= 50:
        return "中性方向，優先管理波動風險"
    return "維持觀察，等待方向形成"


def _reason(evaluation: Mapping[str, Any]) -> str:
    direction = float(evaluation.get("direction_score") or 0)
    evidence = float(evaluation.get("evidence_score") or 0)
    confidence = float(evaluation.get("confidence_score") or 0)
    conflict = float(evaluation.get("conflict_score") or 0)
    risk = float(evaluation.get("risk_score") or 0)
    limitations = evaluation.get("limitations") or []
    limitation_suffix = (
        f"；另有 {len(limitations)} 項資料或模型限制"
        if limitations
        else ""
    )
    return (
        f"v2 方向 {direction:+.1f}、證據 {evidence:.1f}、"
        f"信心 {confidence:.1f}、衝突 {conflict:.1f}、風險 {risk:.1f}"
        f"{limitation_suffix}。"
    )


def _cross_market_context(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    snapshot = item.get("context_snapshot")
    value = snapshot.get("cross_market") if isinstance(snapshot, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _display_context_alignment(item: Mapping[str, Any]) -> float:
    stance_scores = {
        "confirm": 1.0,
        "contradict": -1.0,
        "risk": -0.5,
        "info": 0.0,
    }
    observed = [
        stance_scores.get(str(signal.get("stance") or ""), 0.0)
        for signal in item.get("context_signals") or []
        if isinstance(signal, Mapping)
    ]
    if not observed:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * sum(observed) / len(observed)))


def _cross_market_signal(
    *,
    item: Mapping[str, Any],
    technical_direction: int,
) -> dict[str, Any] | None:
    context = _cross_market_context(item)
    if context is None:
        return None
    summary = context.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    status = str(context.get("status") or "unknown")
    context_stance = str(summary.get("stance") or "unknown")
    score = summary.get("score")
    value_label = (
        f"{float(score):+.2f}%"
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else None
    )
    decision_usable = bool(context.get("decision_usable")) and status == "ready"
    if not decision_usable:
        return {
            "key": "cross_market_context",
            "source": "跨市場",
            "label": "外部脈絡受限",
            "tone": "warning",
            "stance": "info",
            "value_label": value_label,
            "description": f"跨市場 context 狀態為 {status}，不納入對齊分數。",
            "context_status": status,
            "snapshot_id": context.get("snapshot_id"),
            "methodology_version": context.get("methodology_version"),
            "relation_snapshot_version": context.get("relation_snapshot_version"),
            "coverage": context.get("coverage") or {},
            "limitations": list(context.get("limitations") or []),
            "decision_usable": False,
        }

    external_direction = {
        "supportive": 1,
        "adverse": -1,
        "neutral": 0,
    }.get(context_stance, 0)
    if technical_direction == 0 or external_direction == 0:
        stance = "info"
        label = "跨市場中性"
        tone = "neutral"
    elif technical_direction == external_direction:
        stance = "confirm"
        label = "外部順風" if technical_direction > 0 else "外部弱勢確認"
        tone = "positive" if technical_direction > 0 else "negative"
    else:
        stance = "contradict"
        label = "外部逆風"
        tone = "warning"
    return {
        "key": "cross_market_context",
        "source": "跨市場",
        "label": label,
        "tone": tone,
        "stance": stance,
        "value_label": value_label,
        "description": str(summary.get("title") or "跨市場直接映射脈絡。"),
        "context_status": status,
        "context_stance": context_stance,
        "snapshot_id": context.get("snapshot_id"),
        "methodology_version": context.get("methodology_version"),
        "relation_snapshot_version": context.get("relation_snapshot_version"),
        "coverage": context.get("coverage") or {},
        "limitations": list(context.get("limitations") or []),
        "decision_usable": True,
    }


def _cross_market_summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    contexts = [
        context
        for item in items
        if (context := _cross_market_context(item)) is not None
    ]
    statuses = Counter(str(context.get("status") or "unknown") for context in contexts)
    return {
        "enabled": bool(settings.cross_market_radar_display_enabled),
        "mode": "display_only",
        "snapshot_count": len(contexts),
        "decision_usable_count": sum(
            bool(context.get("decision_usable")) for context in contexts
        ),
        "status_counts": dict(statuses),
        "snapshot_ids": list(
            dict.fromkeys(
                str(context.get("snapshot_id"))
                for context in contexts
                if context.get("snapshot_id")
            )
        ),
        "methodology_versions": list(
            dict.fromkeys(
                str(context.get("methodology_version"))
                for context in contexts
                if context.get("methodology_version")
            )
        ),
        "relation_snapshot_versions": list(
            dict.fromkeys(
                str(context.get("relation_snapshot_version"))
                for context in contexts
                if context.get("relation_snapshot_version")
            )
        ),
        "ranking_effect": "none",
        "missing_count": max(0, len(items) - len(contexts)),
    }


def _public_item(
    *,
    source_item: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    item = deepcopy(dict(source_item))
    bucket = str(evaluation.get("primary_bucket") or "watch")
    bucket_meta = _bucket_meta(bucket)
    direction, direction_label = _direction(
        int(evaluation.get("direction") or 0)
    )
    grade, grade_label, grade_description = _grade(
        str(evaluation.get("evidence_grade") or "insufficient")
    )
    family_scores = evaluation.get("family_scores") or {}
    factor_scores = {
        str(family): float(values.get("direction_score") or 0)
        for family, values in family_scores.items()
        if isinstance(values, Mapping)
    }
    matched_signal_keys = _matched_signal_keys(evaluation)
    risk_score = float(evaluation.get("risk_score") or 0)
    urgency = str(evaluation.get("urgency") or "low")
    item.update(
        {
            "rank": 0,
            "bucket": bucket,
            "bucket_label": bucket_meta["label"],
            "urgency": urgency,
            "priority_score": float(
                evaluation.get("priority_score") or 0
            ),
            "technical_evidence_score": float(
                evaluation.get("evidence_score") or 0
            ),
            "technical_score": abs(
                float(evaluation.get("direction_score") or 0)
            ),
            "technical_grade": grade,
            "technical_grade_label": grade_label,
            "technical_grade_description": grade_description,
            "direction": direction,
            "direction_label": direction_label,
            "setup_label": bucket_meta["label"],
            "timing_label": (
                "立即檢查"
                if urgency == "high"
                else "本交易時段追蹤"
                if urgency == "medium"
                else "持續觀察"
            ),
            "risk_label": (
                "高風險"
                if risk_score >= 65
                else "中等風險"
                if risk_score >= 35
                else "一般風險"
            ),
            "factor_scores": factor_scores,
            "technical_notes": list(
                dict.fromkeys(
                    [
                        *[
                            str(value)
                            for value in evaluation.get("state_tags") or []
                        ],
                        *[
                            str(value)
                            for value in evaluation.get("risk_tags") or []
                        ],
                        *[
                            str(limitation.get("code"))
                            for limitation in evaluation.get("limitations")
                            or []
                            if isinstance(limitation, Mapping)
                            and limitation.get("code")
                        ],
                    ]
                )
            )[:6],
            "action_label": _action_label(evaluation),
            "reason": _reason(evaluation),
            "score": int(
                round(float(evaluation.get("direction_score") or 0))
            ),
            "matched_signal_keys": matched_signal_keys,
            "matched_signal_labels": [
                radar_service.SIGNAL_LABELS.get(key, key)
                for key in matched_signal_keys
            ],
            "context_score": round(
                float(evaluation.get("context_alignment_score") or 0)
                / 25.0,
                4,
            ),
            "radar_v2": dict(evaluation),
        }
    )
    return item


def _bucket_summary(items: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("bucket") or "") for item in items)
    return [
        {
            "key": str(bucket["key"]),
            "label": str(bucket["label"]),
            "description": str(bucket["description"]),
            "count": counts.get(str(bucket["key"]), 0),
        }
        for bucket in radar_service.BUCKET_META
        if radar_service._mode_accepts_bucket(
            mode,
            str(bucket["key"]),
        )
    ]


def _default_readiness() -> dict[str, Any]:
    return {
        "operational_status": "active",
        "validation_status": "unverified",
        "backtest_status": "missing",
        "completed_backtest_count": 0,
        "outcome_count": 0,
        "finalized_outcome_count": 0,
        "pending_outcome_count": 0,
        "limitations": [
            {
                "code": "walk_forward_incremental_value_not_verified",
            }
        ],
    }


def build_radar_v2_active_projection(
    *,
    radar: Mapping[str, Any],
    universe_items: list[Mapping[str, Any]],
    market_snapshot: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mode = str(radar.get("mode") or "action").lower().strip()
    if mode not in radar_service.ALLOWED_RADAR_MODES:
        raise ValueError(
            f"Unsupported mode='{mode}'. "
            f"Allowed values: {', '.join(sorted(radar_service.ALLOWED_RADAR_MODES))}."
        )
    max_results = max(1, min(int(radar.get("max_results") or 30), 200))
    market_regime = classify_market_regime(
        market_snapshot=market_snapshot,
        config=RADAR_V2_ACTIVE_CONTRACT["rule_config"]["regime"],
    )
    evaluated_universe: list[dict[str, Any]] = []
    valid_items: list[dict[str, Any]] = []
    insufficient_count = 0
    conflict_count = 0
    for raw_item in universe_items:
        if not isinstance(raw_item, Mapping):
            continue
        source_item = deepcopy(dict(raw_item))
        if str(source_item.get("status") or "") in {"error", "no_data"}:
            evaluated_universe.append(source_item)
            continue
        evaluation = evaluate_radar_v2_item(
            item=source_item,
            market_regime=market_regime,
            contract=RADAR_V2_ACTIVE_CONTRACT,
        )
        if settings.cross_market_radar_display_enabled:
            cross_market_signal = _cross_market_signal(
                item=source_item,
                technical_direction=int(evaluation.get("direction") or 0),
            )
            if cross_market_signal is not None:
                source_item["context_signals"] = [
                    *[
                        dict(signal)
                        for signal in source_item.get("context_signals") or []
                        if isinstance(signal, Mapping)
                        and str(signal.get("key") or "") != "cross_market_context"
                    ],
                    cross_market_signal,
                ]
                evaluation["context_alignment_score"] = _display_context_alignment(
                    source_item
                )
        evaluation["market_snapshot"] = dict(market_snapshot or {})
        public_item = _public_item(
            source_item=source_item,
            evaluation=evaluation,
        )
        evaluated_universe.append(public_item)
        valid_items.append(public_item)
        insufficient_count += int(
            evaluation["evidence_grade"] == "insufficient"
        )
        conflict_count += int(float(evaluation["conflict_score"]) >= 30)

    matched_items = [
        item
        for item in valid_items
        if radar_service._mode_accepts_bucket(
            mode,
            str(item.get("bucket") or ""),
        )
    ]
    matched_items.sort(
        key=lambda item: (
            -float(item.get("priority_score") or 0),
            -float(
                (item.get("radar_v2") or {}).get(
                    "data_quality_score",
                    0,
                )
            ),
            str(item.get("stock_id") or ""),
        )
    )
    results = matched_items[:max_results]
    for index, item in enumerate(results, start=1):
        item["rank"] = index

    payload = {
        key: deepcopy(value)
        for key, value in dict(radar).items()
        if key not in {"results", "buckets", "radar_engine", "radar_v2_summary"}
    }
    payload.update(
        {
            "matched_count": len(matched_items),
            "radar_count": len(results),
            "buckets": _bucket_summary(matched_items, mode),
            "results": results,
            "radar_engine": {
                "active_version": RADAR_V2_ACTIVE_RULE_VERSION,
                "active_config_hash": RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
                "shadow_version": RADAR_V2_RULE_VERSION,
                "shadow_config_hash": RADAR_V2_RULE_CONFIG_HASH,
                "mode": "active",
                "rollback_version": RADAR_V1_RULE_VERSION,
                "technical_direction_owner": "backend",
                "cross_market_context_mode": (
                    "display_only"
                    if settings.cross_market_radar_display_enabled
                    else "disabled"
                ),
                "legacy_status": RADAR_V1_LIFECYCLE_STATUS,
                "legacy_frozen_at": RADAR_V1_FROZEN_AT,
            },
            "radar_v2_summary": {
                "evaluated_count": len(results),
                "universe_evaluated_count": len(valid_items),
                "universe_scope": "complete_calculation_universe",
                "direction_changed_count": 0,
                "bucket_changed_count": 0,
                "conflict_count": conflict_count,
                "insufficient_count": insufficient_count,
                "market_regime": market_regime["market_regime"],
                "market_regime_clarity": market_regime[
                    "market_regime_clarity"
                ],
                "market_limitations": market_regime["limitations"],
                "market_snapshot": dict(market_snapshot or {}),
                "readiness": dict(readiness or _default_readiness()),
                "cross_market_context": _cross_market_summary(valid_items),
            },
            "_radar_v2_universe": evaluated_universe,
        }
    )
    return payload


def build_radar_v2_active_projection_from_db(
    *,
    db: Session,
    radar: Mapping[str, Any],
    universe_items: list[Mapping[str, Any]],
    materialize_cross_market_snapshots: bool = False,
) -> dict[str, Any]:
    signal_trade_date = _trade_date(
        radar.get("trade_date") or radar.get("target_trade_date")
    )
    effective_times = [
        _effective_at(item, signal_trade_date)
        for item in universe_items
        if isinstance(item, Mapping) and signal_trade_date is not None
    ]
    as_of_at = min(effective_times) if effective_times else None
    market_snapshot = latest_market_regime_snapshot(
        db=db,
        signal_trade_date=signal_trade_date,
        as_of_at=as_of_at,
    )
    if (
        market_snapshot is not None
        and signal_trade_date is not None
        and market_snapshot.get("trade_date") != signal_trade_date.isoformat()
    ):
        market_snapshot = {
            **market_snapshot,
            "quality_status": "stale",
        }
    readiness = radar_v2_service.get_radar_v2_validation_readiness(
        db=db,
        group_id=int(radar.get("group_id") or 0),
        mode=str(radar.get("mode") or "action"),
    )
    projected_universe = [deepcopy(dict(item)) for item in universe_items]
    if (
        settings.cross_market_radar_display_enabled
        and as_of_at is not None
    ):
        stock_ids = [
            str(item.get("stock_id") or "").strip()
            for item in projected_universe
            if str(item.get("stock_id") or "").strip()
        ]
        if (
            materialize_cross_market_snapshots
            and settings.cross_market_radar_materialize_enabled
        ):
            materialize_cross_market_context_batch(
                db,
                stock_ids,
                decision_at=as_of_at,
                materialized_by="watchlist.radar_v2",
            )
        contexts = load_latest_cross_market_context_snapshots(
            db,
            stock_ids,
            as_of_at=as_of_at,
        )
        for item in projected_universe:
            stock_id = str(item.get("stock_id") or "").strip()
            context = contexts.get(stock_id)
            if context is None:
                continue
            snapshot = item.get("context_snapshot")
            next_snapshot = dict(snapshot) if isinstance(snapshot, Mapping) else {}
            next_snapshot["cross_market"] = context.model_dump(mode="json")
            item["context_snapshot"] = next_snapshot
    return build_radar_v2_active_projection(
        radar=radar,
        universe_items=projected_universe,
        market_snapshot=market_snapshot,
        readiness=readiness,
    )


def persist_radar_v2_active(
    *,
    db: Session,
    radar: Mapping[str, Any],
    group_id: int,
    mode: str,
    snapshot_run_id: int | None = None,
) -> dict[str, Any]:
    return persist_radar_v2(
        db=db,
        radar=radar,
        group_id=group_id,
        mode=mode,
        snapshot_run_id=snapshot_run_id,
        contract=RADAR_V2_ACTIVE_CONTRACT,
    )


__all__ = [
    "build_radar_v2_active_projection",
    "build_radar_v2_active_projection_from_db",
    "persist_radar_v2_active",
]
