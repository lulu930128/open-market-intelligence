# Consumer Inventory

## Inventory status

- Recorded against branch `main` and the 73-entry dirty worktree observed after Gate P approval.
- Existing dirty changes are preserved. Relevant overlap already exists in calendar, AI contract, source-health, tests, Frontend market types and MCP snapshot files.
- Line numbers are inspection evidence only and must be rediscovered before each later milestone.

## Canonical owners

| Responsibility | Current owner | M1 decision |
|---|---|---|
| Taiwan trading day, timezone and market clock | `backend/app/market/trading_calendar.py` and `calendar_status.py` | Add pure 08:00 presentation-session calendar state only; do not parse MIS fields |
| TWSE MIS transport and raw snapshot persistence | `backend/app/market/quote_depth.py` | Preserve existing provider/circuit/transaction behavior |
| Individual-security observation phase | currently request-clock logic in `quote_depth.py` | Extract a pure resolver for provider event and `z/pz/ps/ts/v` evidence |
| Same-session actual price | current snapshot-local `row.last_price` only | Query existing confirmed same-session snapshots without migration |
| Quote replay | `_project_replay_quote_contract()` | Preserve captured fields; do not synthesize or delete evidence |
| Temporal AI classification | `backend/app/ai/realtime_contract.py` | Add semantic usability axes while retaining legacy compatibility |
| Quote component projection | `backend/app/ai/market_context/taiwan_projection.py` | Consume canonical market/instrument fields; do not keep a second alias table |
| Public HTTP schema | `backend/app/market/schemas.py` and market router | Additive fields; route/method unchanged |
| Frontend quote refresh/render | `useTaiwanQuoteDepth.ts`, `QuoteDepthPanel.tsx`, `stockDetailFormatters.ts` | Schedule bounded backend-provided transition refetch; existing formatters already render null as `"-"` |
| Market calendar polling | `marketCalendarStatus.ts`, `useDashboardRuntime.ts` | Consume backend transition time; no Frontend trading-day inference for the new boundary |
| MCP/other consumers | public contract snapshot and backend AI response | Adapter remains thin; update snapshot only after final schema inventory |

## Existing public fields and compatibility

- `session_phase` is read by backend AI, tests and Frontend quote-depth refresh. It remains a compatibility field.
- `trade_date` is the observed quote trade date. It is not repurposed as the empty presentation-frame date.
- `last_price` is the current display price field. It may use a confirmed earlier same-session `z`, but must remain null before current-session trade evidence.
- `previous_close` remains a reference fact and must not be relabeled as current.
- `quote_semantics`, `last_trade_available`, `last_trade_time`, auction fields and freshness remain public and require compatible additive evolution.

## Frontend boundary behavior

- `useTaiwanQuoteDepth.ts` currently polls non-live phases every 60 seconds and passes `refresh=true`.
- `get_taiwan_stock_quote_depth()` already returns before provider I/O during `closed_waiting_preopen`; this is the correct place to create the empty 08:00 session frame.
- To avoid manual reload and minute-scale drift, the quote response should provide the next presentation transition; the hook schedules the smaller of its normal delay and that transition.
- `formatPrice()` and `formatLotUnits()` already render null/undefined as `"-"`; no alternate placeholder logic is needed.
- The quote panel should show `presentation_trade_date` when `quote_time` is absent so the user can see that the workspace has rolled to today.

## AI and MCP consumers

- `realtime_contract.classify_observation()` normalizes Taiwan phases but currently derives `decision_usable` primarily from temporal `state=live`.
- `taiwan_projection._quote_components()` currently determines auction relevance from normalized legacy session phase.
- Additive canonical fields must flow into compact evidence/capability status before any legacy field meaning is changed.
- Public MCP snapshot/digest changes are deferred until the final outward field set is stable.

## Persistence and scheduler consumers

- `TaiwanStockQuoteSnapshot` already stores raw payload, quote time, trade date, last price and cumulative volume.
- `TaiwanQuoteContractSnapshot` stores the complete public payload JSON, so replay can preserve captured indicative fields without migration.
- `taiwan_quote_contract_scheduler.py` iterates the fixed slot tuple with bounded symbols, dedupe, `coalesce=True` and `max_instances=1`; adding four fixed slots does not change ownership.

## Confirmed overlap boundaries

- Do not rewrite existing dirty session aliases, interval-aware realtime behavior, breadth v2, index live/official separation or preopen trade-value quarantine.
- Do not modify dispatch scheduler v2 files while implementing this project.
- Any change to dirty AI files must be a localized additive patch with targeted regression evidence.
