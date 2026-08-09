# Issue Map

## Priority order

1. P0-T：opening/closing handoff truth and actual-trade semantics.
2. P0-E：replay/capture evidence integrity.
3. P0-R：formal runtime follow-up packages A/B.
4. P1：diagnostics and canonical freshness packages C/D.
5. P2：source-health historical-event clarification package E.

## Issues

| ID | Status at planning | Evidence | Canonical owner | Planned remediation | Acceptance | Priority |
|---|---|---|---|---|---|---|
| OMI-TW-HO-007 | User-requested design requirement; current 08:00 boundary not yet observed | OMI should change to today's trading workspace at 08:00 while all not-yet-available current-session price facts display `"-"` | `trading_calendar.py` trading-day clock plus backend market-session projection; Frontend presentation/refetch only | Separate presentation-session date from market observation; on trading days roll to today at 08:00 with null current-session facts, independently labeled previous close, and no provider fetch solely for rollover | 07:59→08:00 already-open UI changes date automatically; backend numeric fields stay null, UI shows `"-"`; weekend/holiday does not roll | P0-T |
| OMI-TW-HO-001 | Confirmed runtime defect | 2026-08-05 09:00 request projected provider event `08:59:55 ts=1 pz=2385 z=-` as `regular_live + live_depth_only` | shared TWSE MIS observation resolver; `market/quote_depth.py` | Separate market clock from instrument phase; retain auction when provider observation remains trial/indicative | 09:00 clock alone never removes `quote.auction`; no `pz` becomes last trade | P0-T |
| OMI-TW-HO-002 | Confirmed runtime defect | 09:05 `z=-, v=3141` and 13:24 `z=-, v=27545` caused `last_trade_available=false` | quote state service / existing persisted snapshot owner | Retain previously confirmed same-session actual trade; otherwise expose occurred-with-price-missing without guessing | Cached price keeps original `price_as_of`; no cache means price null and explicit status | P0-T |
| OMI-TW-HO-003 | Confirmed public replay defect | Persisted 08:50/08:59/13:28 indicative fields are true, replay API clears them while keeping indicative semantics | `quote_depth._project_replay_quote_contract` | Preserve captured public fields; add captured/current contract metadata only where required | Replay and persisted public snapshot agree on indicative availability/value/source | P0-E |
| OMI-TW-HO-004 | Confirmed acceptance gap | Fixed slots have 09:00 and 09:05 but no 09:01/09:02; closing has 13:30/13:32/13:34 but not exact delayed-close boundary | quote capture schedule / snapshot contract | Add bounded canary slots `09:01`, `09:02`, and closing equivalents `13:31`, `13:33` unless a lower-cost equivalent is proven | Replay can show transition sequence; request count remains bounded and documented | P0-E |
| OMI-TW-HO-005 | Confirmed code-level semantic risk | `realtime_contract` derives execution/decision usability primarily from temporal `state=live`; preopen test expects `decision_usable=true` | `ai/realtime_contract.py` and capability projection | Make temporal live independent from fact/research/execution/price decision usability | Fresh auction facts can be usable; execution-grade and actual-price decision usability remain false | P0-T |
| OMI-TW-HO-006 | Confirmed symmetric design gap | Clock changes quote phase after 13:30 although official delayed close may continue to 13:33 | shared observation resolver / quote depth | Apply the same market-clock versus instrument-phase model at close | Delayed closing trial evidence remains auction indicative; official close only after confirmed evidence | P0-T |
| OMI-TW-RT-001 | Confirmed source defect from formal runtime follow-up | `ask_execution._include_tw_intraday()` disables reader when external fetch is denied even if persisted fallback is allowed | `ai/ask_execution.py`, `ai/market_context/taiwan_stock.py`, `market/intraday.py` | Separate requested reader, provider-refresh permission and persisted-cache permission | `prefer_live + external false + fallback true` returns persisted hit; provider not called | P0-R |
| OMI-TW-RT-002 | Confirmed outward projection defect | Non-decision quote/data-only response can copy technical levels into `decision.price_levels` | `ai/decision_envelope.py` with v4 projection compatibility | Gate actionable decision payload by `decision_required`; preserve technical evidence | Data-only decision container is non-actionable; entry/risk decisions remain unchanged | P0-R |
| OMI-TW-RT-003 | Confirmed diagnostics inconsistency | Primary intent is negation-aware but `matched_hints` still lists negated risk/exit hints | `ai/decision_core.py` | Reuse the negation-aware matcher or expose raw/effective/negated hints separately | Intent and effective diagnostics agree; raw debug remains explicit if retained | P1 |
| OMI-TW-RT-004 | Confirmed aggregate risk | Raw `data.freshness` may look current when a required capability is blocked/unavailable | `ai/data_quality_contract.py`, Taiwan market projection | Aggregate temporal freshness, capability availability, completeness and decision usability as separate axes | Raw freshness, by-capability and canonical status agree on blocked required cases | P1 |
| OMI-TW-RT-005 | Confirmed presentation ambiguity | Current source-health row may carry historical `latest_event_status=stale` and be mistaken for row freshness | `ai/market_context/source_health_context.py`, `market/source_health.py`, provider health projection | Rename or qualify historical event fields without hiding them | Consumer can distinguish row lifecycle from latest historical provider event | P2 |

## Existing owners that should remain stable

- `backend/app/market/trading_calendar.py`
  - Owns trading day, market clock and alias normalization.
  - Must not parse `z/pz/ps/ts` or determine individual-security actual-trade state.
- `backend/app/market/taiwan_market_state.py:_eligible_session_trade_value()`
  - The 2026-08-05 DB confirms preopen cumulative trade value remains null.
  - Do not rewrite unless a regression is reproduced.
- `backend/app/market/indices.py` and `tw_market_breadth_contract.py`
  - Existing actual-versus-indicative breadth separation is directionally correct.
  - Shared resolver extraction must preserve coverage, scope, unknown count and `decision_usable=false` for auction breadth.
- `backend/app/ai/data_quality_contract.py` continuity logic
  - Existing overnight/closing gap handling remains; only touch exact new session state cases with targeted regressions.
- `backend/app/ai/market_context/taiwan_market.py`
  - Preserve `official_close` versus `live_snapshot`, trade date, as-of and `current_for_requested_session` semantics.
- `backend/app/ai/capability_contract.py`
  - Preserve bounded refresh permission and explicit attempt telemetry; never force provider I/O just to set `attempted=true`.

## Consumer inventory before outward field changes

Search and record all reads of the following before changing schema or meaning:

```powershell
rg -n "trade_date|session_date|session_phase|canonical_session_phase|market_status|quote_semantics|last_trade_available|decision_usable|execution_grade_usable|quote\.auction|indicative_match" backend frontend agents
```

Minimum surfaces:

- `TaiwanStockQuoteDepthRead` and market router response models.
- AI compact quote projection and `quote.snapshot` / `quote.auction` capability projections.
- `realtime_contract.annotate_selected_data()`.
- `data_quality_contract` and v4 evidence/readiness projection.
- OMI answer composer data-limit messages.
- `agents/omi_mcp_server/public_contract_snapshot.json` and digest tests.
- Frontend market types, date selection, automatic refresh/polling boundary, and null-to-`"-"` display of quote/volume/change fields.
- Repo MCP `omi.ask` slim projection.

## Default implementation boundary

Prefer a pure market-layer resolver such as a new `backend/app/market/twse_mis_observation.py`, or a carefully generalized existing pure contract, with an input/output shape similar to:

```python
resolve_twse_mis_observation(
    request_now=...,
    provider_event_time=...,
    trade_date=...,
    last_trade_price=...,
    cumulative_volume_lots=...,
    open_price=...,
    high_price=...,
    low_price=...,
    indicative_price=...,
    indicative_volume_lots=...,
    indicative_status=...,
    cached_actual_trade=...,
)
```

The pure result should expose:

```text
market_calendar_phase
instrument_phase
observation_semantics
actual_trade_occurred
actual_trade_available
last_trade_price
price_as_of
price_source
auction_indicative_available
auction_indicative_price
auction_indicative_volume
facts_usable
intraday_research_usable
execution_grade_usable
warnings / reason_code
```

Do not commit to a new public object until M1 consumer inventory proves it is needed. Internal canonicalization plus compatible projection is preferred when it fully expresses the semantics.
