# Plan

## Milestones

1. Freeze the additive contract and evidence baseline
   - Scope: task documents、current source/test/runtime inventory。
   - Acceptance: scope、time-skew rule、compatibility and live-acceptance boundary are explicit。
   - Validation: UTF-8 readback and `git diff --check` for the task folder。

2. Make intraday metadata session-scoped
   - Scope: `backend/app/market/intraday.py` and `backend/app/market/schemas.py`。
   - Acceptance: points remain multi-day；bar sum、trade value and VWAP use only latest trade date；window sum is separately labeled。
   - Validation: `backend/tests/test_intraday_history.py` and focused pure-contract tests。

3. Reconcile quote and intraday evidence in backend AI context
   - Scope: `backend/app/ai/market_context/taiwan_stock.py` and `taiwan_projection.py`。
   - Acceptance: aligned MIS becomes canonical；date mismatch、preopen and stale/time-skew paths remain visible and never mutate bars。
   - Validation: `backend/tests/test_intraday_contract_remediation.py` and AI market-context projection tests。

4. Publish the additive capability contract
   - Scope: market schema、AI capability allow/default fields、public snapshot and contract inventory tests。
   - Acceptance: REST/OpenAPI/AI/MCP preserve new fields；legacy fields remain compatible。
   - Validation: capability、outward、API inventory and MCP snapshot tests。

5. Validate and prepare live acceptance
   - Scope: compile、targeted regression、backend safe profile、read-only runtime/schema smoke and task Progress。
   - Acceptance: deterministic checks pass；real opening validation stays pending with exact probe windows and expected fields。
   - Validation: `scripts/run-safe-validation.ps1 -Profile backend` and `git diff --check`。

## Stop-and-fix rules

- If any reconciliation modifies a point's volume, stop and fix before continuing。
- If quote `event_time` is older than the latest bar beyond interval tolerance but still overwrites the compatibility alias, stop and fix。
- If preopen or missing volume is flattened to numeric zero/current, stop and fix。
- If the change requires a DB migration、extra provider request or consumer-side market logic, stop and reassess the backend contract boundary。
- If targeted tests fail, do not proceed to full backend validation。
- If full validation failures overlap unrelated dirty-worktree work, isolate evidence before deciding whether they belong to this task。
- Deterministic/runtime-after-close checks cannot mark the next-session live acceptance complete。

## Decisions

- 2026-08-06: Use a dual-track contract: latest-trade-date interval-bar sum plus MIS session cumulative as-of evidence。
- 2026-08-06: Keep `cumulative_volume_*` additive-compatible, selecting aligned MIS first and explicit bar fallback otherwise。
- 2026-08-06: A same-date quote is insufficient by itself；event-time/freshness alignment is mandatory。
- 2026-08-06: Preserve multi-day chart points and never distribute unallocated volume into bars。
- 2026-08-06: No migration、Frontend recomputation、duplicate provider fetch、commit or push。
