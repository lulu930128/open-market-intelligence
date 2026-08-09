from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai import (
    answer_composer,
    agentic_tools,
    ask_execution,
    ask_finalizer,
    ask_policy,
    ask_response_support,
    ask_stages,
    decision_core,
    decision_envelope,
    decision_engine,
    freshness,
    llm,
    orchestrator,
    pipeline_progress,
    query_plan,
    reports,
    scope_resolution,
    tools,
)
from app.ai.schemas import AiAskRequest
from app.portfolio import service as portfolio_service


CONTRACT_VERSION = ask_response_support.CONTRACT_VERSION
VALID_TARGET_TYPES = scope_resolution.VALID_TARGET_TYPES
TAIWAN_INDEX_TARGET_IDS = scope_resolution.TAIWAN_INDEX_TARGET_IDS
TAIWAN_FUTURES_TARGET_IDS = scope_resolution.TAIWAN_FUTURES_TARGET_IDS
INTERNAL_SCOPE_TO_TARGET_TYPE = scope_resolution.INTERNAL_SCOPE_TO_TARGET_TYPE
TARGET_TYPE_TO_INTERNAL_SCOPE = scope_resolution.TARGET_TYPE_TO_INTERNAL_SCOPE
ScopeResolution = scope_resolution.ScopeResolution
VALID_MODES = ask_policy.VALID_MODES
VALID_RANK_BY = ask_policy.VALID_RANK_BY
VALID_SORT_ORDER = ask_policy.VALID_SORT_ORDER
VALID_ANALYSIS_HORIZONS = ask_policy.VALID_ANALYSIS_HORIZONS
AiAskServerPolicy = ask_policy.AiAskServerPolicy
ANALYSIS_HORIZON_LABELS = ask_response_support.ANALYSIS_HORIZON_LABELS
STANCE_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "多空分歧",
    "insufficient_data": "資料不足",
}
CONFIDENCE_LABELS = ask_response_support.CONFIDENCE_LABELS
CONSUMER_SUMMARY_LIMIT = ask_response_support.CONSUMER_SUMMARY_LIMIT


# Runtime aliases keep question understanding centralized in decision_core while
# preserving this module's existing public helper names during the migration.
REPORT_HINTS = decision_core.REPORT_HINTS
ANALYSIS_HINTS = decision_core.ANALYSIS_HINTS
ENTRY_DECISION_HINTS = decision_core.ENTRY_DECISION_HINTS
EXIT_DECISION_HINTS = decision_core.EXIT_DECISION_HINTS
RISK_DECISION_HINTS = decision_core.RISK_DECISION_HINTS
TREND_VIEW_HINTS = decision_core.TREND_VIEW_HINTS
POSITION_CONTEXT_HINTS = decision_core.POSITION_CONTEXT_HINTS
STOP_LOSS_HINTS = decision_core.STOP_LOSS_HINTS
TAKE_PROFIT_HINTS = decision_core.TAKE_PROFIT_HINTS
HOLD_DECISION_HINTS = decision_core.HOLD_DECISION_HINTS
POSITION_ENTRY_PRICE_PATTERNS = decision_core.POSITION_ENTRY_PRICE_PATTERNS
FRESHNESS_HINTS = decision_core.FRESHNESS_HINTS
INTRADAY_HINTS = decision_core.INTRADAY_HINTS
SHORT_HORIZON_HINTS = decision_core.SHORT_HORIZON_HINTS
SWING_HORIZON_HINTS = decision_core.SWING_HORIZON_HINTS
LONG_HORIZON_HINTS = decision_core.LONG_HORIZON_HINTS
WATCHLIST_HINTS = decision_core.WATCHLIST_HINTS
MARKET_HINTS = decision_core.MARKET_HINTS
ADR_HINTS = decision_core.ADR_HINTS
US_SYMBOL_CONTEXT_HINTS = decision_core.US_SYMBOL_CONTEXT_HINTS
STOCK_REFERENCE_HINTS = decision_core.STOCK_REFERENCE_HINTS
TAIWAN_TSMC_ALIASES = decision_core.TAIWAN_TSMC_ALIASES
US_SYMBOL_STOPWORDS = decision_core.US_SYMBOL_STOPWORDS
US_EXCHANGE_SYMBOL_PATTERN = decision_core.US_EXCHANGE_SYMBOL_PATTERN
US_DOLLAR_SYMBOL_PATTERN = decision_core.US_DOLLAR_SYMBOL_PATTERN
US_PLAIN_SYMBOL_PATTERN = decision_core.US_PLAIN_SYMBOL_PATTERN


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    return decision_core.contains_hint(question, hints)


def _parse_number_token(value: str | None) -> float | None:
    return decision_core.parse_number_token(value)


def _extract_position_entry_price(question: str) -> tuple[float | None, str | None]:
    return decision_core.extract_position_entry_price(question)


def _infer_position_context(question: str) -> dict[str, Any]:
    return decision_core.infer_position_context(question).as_dict()


def _infer_question_intent(question: str) -> str:
    return decision_core.infer_question_intent(question)


def _normalize_analysis_horizon(value: str | None) -> str:
    return decision_core.normalize_analysis_horizon(value)


def _infer_analysis_horizon(payload: AiAskRequest) -> str:
    horizon, _ = decision_core.infer_analysis_horizon(
        question=payload.question,
        requested_horizon=payload.analysis_horizon,
        strategy_profile=payload.strategy_profile,
    )
    return horizon


def _include_tw_intraday(
    payload: AiAskRequest,
    *,
    policy: dict[str, Any] | None = None,
    allow_persisted_cache: bool = True,
) -> bool:
    return ask_execution._include_tw_intraday(
        payload,
        policy=policy,
        allow_persisted_cache=allow_persisted_cache,
    )


_normalize_text = scope_resolution._normalize_text
_string_from_dict = scope_resolution._string_from_dict
_request_target = scope_resolution._request_target
_request_target_type = scope_resolution._request_target_type
_request_target_id = scope_resolution._request_target_id
_target_dict = scope_resolution._target_dict
_resolution_target = scope_resolution._resolution_target
_looks_like_stock_id = scope_resolution._looks_like_stock_id
_looks_like_us_symbol = scope_resolution._looks_like_us_symbol
_looks_like_jp_symbol = scope_resolution._looks_like_jp_symbol
_resolution_candidate = scope_resolution._resolution_candidate
_scope_resolution_dict = scope_resolution._scope_resolution_dict
_clarification_dict = scope_resolution._clarification_dict
_first_stock_id_in_text = scope_resolution._first_stock_id_in_text
_first_watchlist_group_id_in_text = scope_resolution._first_watchlist_group_id_in_text
_stock_display_name = scope_resolution._stock_display_name
_us_stock_display_name = scope_resolution._us_stock_display_name
_get_us_stock = scope_resolution._get_us_stock
_us_stock_label = scope_resolution._us_stock_label
_resolve_us_stock_symbol = scope_resolution._resolve_us_stock_symbol
_question_has_us_symbol_context = scope_resolution._question_has_us_symbol_context
_iter_us_symbol_mentions = scope_resolution._iter_us_symbol_mentions
_resolve_us_stock_symbol_from_question = scope_resolution._resolve_us_stock_symbol_from_question
_jp_stock_display_name = scope_resolution._jp_stock_display_name
_get_jp_stock = scope_resolution._get_jp_stock
_jp_stock_label = scope_resolution._jp_stock_label
_resolve_jp_stock_symbol = scope_resolution._resolve_jp_stock_symbol
_question_has_jp_context = scope_resolution._question_has_jp_context
_resolve_jp_stock_symbol_from_question = scope_resolution._resolve_jp_stock_symbol_from_question
_target_from_candidate = scope_resolution._target_from_candidate
_last_omi_resolution = scope_resolution._last_omi_resolution
_last_resolution_us_candidate = scope_resolution._last_resolution_us_candidate
_resolve_stock_name_from_db = scope_resolution._resolve_stock_name_from_db
_resolve_tsmc_alias = scope_resolution._resolve_tsmc_alias
_resolve_watchlist_group_name_from_db = scope_resolution._resolve_watchlist_group_name_from_db
_clarify_scope = scope_resolution._clarify_scope
_resolve_scope = scope_resolution._resolve_scope


_validate_request = ask_policy._validate_request
_infer_scope_type = ask_policy._infer_scope_type
_policy = ask_policy._policy
_refresh_before_answer_enabled = ask_policy._refresh_before_answer_enabled
_infer_mode = ask_policy._infer_mode
_effective_mode = ask_policy._effective_mode
_require_scope_id = ask_policy._require_scope_id
_require_group_id = ask_policy._require_group_id


_read_data_only = ask_execution._read_data_only
_build_brief = ask_execution._build_brief
_generate_report = ask_execution._generate_report
_generate_analysis = ask_execution._generate_analysis


_extract_list = ask_response_support._extract_list
_result_as_of = ask_response_support._result_as_of
_score_display = ask_response_support._score_display
_text_value = ask_response_support._text_value
_text_list = ask_response_support._text_list
_append_unique_texts = ask_response_support._append_unique_texts
_llm_report_from_result = ask_response_support._llm_report_from_result
_consumer_detail_from_llm_report = ask_response_support._consumer_detail_from_llm_report
_consumer_text = ask_response_support._consumer_text
_generic_data_limits = ask_response_support._generic_data_limits
_numeric_score = ask_response_support._numeric_score
_stance_from_score = ask_response_support._stance_from_score
_numeric_data_value = ask_response_support._numeric_data_value
_format_price = ask_response_support._format_price
_format_signed_price = ask_response_support._format_signed_price
_format_pct_value = ask_response_support._format_pct_value
_level_price_text = ask_response_support._level_price_text
_zone_text = ask_response_support._zone_text
_zone_bounds = ask_response_support._zone_bounds
_technical_level_fields = ask_response_support._technical_level_fields
_technical_level_numbers = ask_response_support._technical_level_numbers
_entry_price_position = ask_response_support._entry_price_position
_entry_risk_text = ask_response_support._entry_risk_text
_entry_confirmation_text = ask_response_support._entry_confirmation_text
_entry_decision_summary_lines = ask_response_support._entry_decision_summary_lines
_entry_decision_with_levels = ask_response_support._entry_decision_with_levels
_technical_level_summary_lines = ask_response_support._technical_level_summary_lines
_result_data = ask_response_support._result_data
_latest_price_snapshot = ask_response_support._latest_price_snapshot
_chart_points = ask_response_support._chart_points
_position_support_levels = ask_response_support._position_support_levels
_level_text = ask_response_support._level_text
_build_position_decision = ask_response_support._build_position_decision
_try_attach_position_decision_llm = ask_response_support._try_attach_position_decision_llm
_build_position_decision_consumer_answer = ask_response_support._build_position_decision_consumer_answer
QUESTION_INTENT_STAGE_LABELS = ask_response_support.QUESTION_INTENT_STAGE_LABELS
_build_reasoning_steps = ask_response_support._build_reasoning_steps
_digest_summary_lines = ask_response_support._digest_summary_lines
_decision_evidence_summary_lines = ask_response_support._decision_evidence_summary_lines
_decision_evidence_risk_lines = ask_response_support._decision_evidence_risk_lines
_decision_evidence_data_lines = ask_response_support._decision_evidence_data_lines
_build_question_aware_consumer_answer = ask_response_support._build_question_aware_consumer_answer
_build_llm_consumer_answer = ask_response_support._build_llm_consumer_answer
_build_watchlist_consumer_answer = ask_response_support._build_watchlist_consumer_answer
_build_digest_consumer_answer = ask_response_support._build_digest_consumer_answer
_build_consumer_human_answer = ask_response_support._build_consumer_human_answer
_extract_analysis_digest = ask_response_support._extract_analysis_digest
_check_freshness = ask_execution._check_freshness
_report_level = ask_response_support._report_level
_build_next_actions = ask_response_support._build_next_actions
_clarification_response = ask_response_support._clarification_response
_target_error_response = ask_response_support._target_error_response



def ask(
    db: Session,
    payload: AiAskRequest,
    *,
    server_policy: AiAskServerPolicy | None = None,
    progress_callback: pipeline_progress.ProgressCallback | None = None,
) -> dict[str, Any]:
    progress = pipeline_progress.OmiPipelineProgress(progress_callback)
    _validate_request(payload)

    resolution = _resolve_scope(db=db, payload=payload)
    scope_type = resolution.selected_scope_type
    payload = ask_stages.normalize_payload_for_resolution(
        payload=payload,
        resolution=resolution,
        request_target_id=_request_target_id,
        request_target_type=_request_target_type,
        resolution_target=_resolution_target,
    )
    if resolution.error_code:
        policy = _policy(payload, server_policy or AiAskServerPolicy())
        progress.clarification_required()
        response = _target_error_response(
            payload=payload,
            resolution=resolution,
            requested_mode=payload.mode,
            policy=policy,
        )
        progress.evidence_passport(response["evidence_passport"])
        progress.answer_ready(answer_ready=False, report_level="blocked")
        return decision_envelope.for_requested_contract(
            response,
            requested_contract_version=payload.contract_version,
        )
    warnings: list[str] = []
    if not payload.position_context:
        try:
            saved_position_context = portfolio_service.get_position_context_for_scope(
                db,
                scope_type=scope_type,
                scope_id=resolution.selected_scope_id,
            )
        except portfolio_service.PortfolioError as exc:
            saved_position_context = {}
            warnings.append(f"Portfolio position context skipped: {exc}")
        if saved_position_context:
            payload = payload.model_copy(update={"position_context": saved_position_context})
    question_stage = ask_stages.build_question_stage(
        payload=payload,
        scope_type=scope_type,
        server_policy=server_policy or AiAskServerPolicy(),
        progress=progress,
        build_policy=_policy,
        infer_mode=_infer_mode,
        normalize_analysis_horizon=_normalize_analysis_horizon,
    )
    payload = question_stage.payload
    policy = question_stage.policy
    position_context = question_stage.position_context
    question_intent = question_stage.question_intent
    auto_mode_requested = question_stage.auto_mode_requested
    requested_mode = question_stage.requested_mode
    question_understanding = question_stage.question_understanding
    if resolution.clarification_required:
        progress.clarification_required()
        response = _clarification_response(
            payload=payload,
            resolution=resolution,
            requested_mode=requested_mode,
            policy=policy,
        )
        return decision_envelope.for_requested_contract(
            response,
            requested_contract_version=payload.contract_version,
        )

    effective_mode = _effective_mode(requested_mode, scope_type, policy, warnings)
    execution_plan = query_plan.build_query_plan(
        payload=payload,
        scope_type=scope_type,
        target_market=resolution.selected_market,
        question_intent=question_intent,
        effective_mode=effective_mode,
    )
    original_market_data_params = (
        payload.market_data_params
        if isinstance(payload.market_data_params, dict)
        else {}
    )
    explicit_domain_selection = bool(
        payload.selection
        or execution_plan.matched_positive_terms
        or execution_plan.matched_negative_terms
        or any(
            key in original_market_data_params
            for key in ("refresh_domains", "requested_domains", "excluded_domains")
        )
    )
    payload = payload.model_copy(
        update={
            "market_data_params": {
                **payload.market_data_params,
                "payload_level": execution_plan.payload_level,
                "reader_profile": execution_plan.reader_profile,
                "explicit_domain_selection": explicit_domain_selection,
                "requested_domains": list(execution_plan.requested_domains),
                "excluded_domains": list(execution_plan.excluded_domains),
                "requested_capabilities": [
                    *execution_plan.selected_capabilities,
                    *execution_plan.optional_selected_capabilities,
                ],
                "capability_limits": dict(execution_plan.selection.get("limits") or {}),
                "capability_parameters": dict(
                    execution_plan.selection.get("parameters") or {}
                ),
                "external_fetch_allowed": bool(policy.get("can_external_fetch")),
                "tool_budget": dict(policy.get("tool_budget") or {}),
            }
        }
    )
    query_plan_payload = execution_plan.as_dict()
    policy["query_plan"] = query_plan_payload
    freshness_result = progress.run_freshness_check(
        scope_type=scope_type,
        operation=lambda: _check_freshness(
            db,
            payload,
            scope_type,
            question_intent=question_intent,
        ),
    )
    tool_stage = ask_stages.execute_tool_stages(
        scope_type=scope_type,
        payload=payload,
        resolution=resolution,
        policy=policy,
        query_plan=query_plan_payload,
        freshness_result=freshness_result,
        progress=progress,
        progress_callback=progress_callback,
        resolution_target=_resolution_target,
        require_scope_id=_require_scope_id,
        require_group_id=_require_group_id,
        refresh_before_answer_enabled=_refresh_before_answer_enabled,
        run_us_stock_tool_session=lambda **kwargs: agentic_tools.run_us_stock_tool_session(
            db=db,
            **kwargs,
        ),
        run_tw_stock_tool_session=lambda **kwargs: agentic_tools.run_tw_stock_tool_session(
            db=db,
            **kwargs,
        ),
        run_tw_watchlist_tool_session=lambda **kwargs: agentic_tools.run_tw_watchlist_tool_session(
            db=db,
            **kwargs,
        ),
        run_crypto_asset_tool_session=lambda **kwargs: agentic_tools.run_crypto_asset_tool_session(
            db=db,
            **kwargs,
        ),
        run_regional_market_tool_session=lambda **kwargs: agentic_tools.run_regional_market_tool_session(
            db=db,
            **kwargs,
        ),
    )
    tool_plan = tool_stage.tool_plan
    tool_runs = tool_stage.tool_runs
    freshness_result = tool_stage.freshness_result
    warnings.extend(tool_stage.warnings)
    ask_stages.apply_freshness_guard(policy=policy, freshness_result=freshness_result)

    effective_mode = ask_stages.effective_mode_after_freshness(
        effective_mode=effective_mode,
        freshness_result=freshness_result,
        scope_type=scope_type,
        warnings=warnings,
    )
    mode_result = ask_stages.execute_mode_stage(
        db=db,
        payload=payload,
        scope_type=scope_type,
        effective_mode=effective_mode,
        auto_mode_requested=auto_mode_requested,
        question_intent=question_intent,
        tool_runs=tool_runs,
        warnings=warnings,
        policy=policy,
        progress=progress,
        read_data_only=_read_data_only,
        build_brief=_build_brief,
        generate_analysis=_generate_analysis,
        generate_report=_generate_report,
    )
    effective_mode = mode_result.effective_mode
    action = mode_result.action
    result = mode_result.result
    warnings = mode_result.warnings

    response_target = _resolution_target(resolution)
    assembled = ask_stages.assemble_response_analysis(
        result=result,
        freshness_result=freshness_result,
        warnings=warnings,
        resolution=resolution,
        effective_mode=effective_mode,
        policy=policy,
        requested_mode=requested_mode,
        question_understanding=question_understanding,
        question_intent=question_intent,
        position_context=position_context,
        scope_type=scope_type,
        response_target=response_target,
        progress=progress,
        extract_list=_extract_list,
        extract_analysis_digest=_extract_analysis_digest,
        clarification_dict=_clarification_dict,
        build_next_actions=_build_next_actions,
        build_position_decision=_build_position_decision,
        try_attach_position_decision_llm=_try_attach_position_decision_llm,
        build_consumer_human_answer=_build_consumer_human_answer,
        build_reasoning_steps=_build_reasoning_steps,
        payload=payload,
        query_plan=query_plan_payload,
    )

    response = ask_finalizer.finalize_ask_response(
        payload=payload,
        resolution=resolution,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        action=action,
        result=result,
        response_target=response_target,
        assembled=assembled,
        policy=policy,
        tool_plan=tool_plan,
        tool_runs=tool_runs,
        freshness_result=freshness_result,
        progress=progress,
        query_plan=query_plan_payload,
    )
    return decision_envelope.for_requested_contract(
        response,
        requested_contract_version=payload.contract_version,
        canonical_result=result,
    )
