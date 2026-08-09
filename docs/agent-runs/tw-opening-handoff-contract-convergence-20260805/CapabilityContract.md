# Taiwan Opening Handoff Capability Contract

## Product scope

- Market: Taiwan equities, with `2330` as the bounded live/replay canary.
- Purpose: make the 08:00 presentation-day rollover, 08:30 preopen auction, 09:00～09:02 first-trade handoff and 13:25～13:33 closing handoff explicit and verifiable.
- Product boundary: research and data-quality support only; no execution or automatic-trading behavior.

## Target and normalization

- Target type: Taiwan listed／OTC stock identifiers already normalized by `StockMaster.stock_id`.
- Exchange channel remains `tse_<stock_id>.tw` or `otc_<stock_id>.tw`.
- Trading calendar and timezone are canonical Asia/Taipei backend facts.

## Provider and resource

- 08:00 rollover provider: none. It is a backend calendar/presentation-session transition and must not create provider I/O.
- Quote provider: public TWSE MIS `getStockInfo.jsp`, existing bounded one-symbol request and existing timeout/circuit/coalescing contract.
- Raw semantics:
  - `z`: snapshot-local last trade when present.
  - `v`: provider cumulative volume evidence; positive volume can prove trades occurred but cannot supply a missing price.
  - `pz/ps/ts`: auction indicative evidence only.
- Existing provider-event, source-error, cache and fallback visibility remain unchanged.

## Session and freshness

- Presentation session:
  - before 08:00 on a Taiwan trading day: latest completed session reference;
  - from 08:00: today's empty session frame (`today_pending`);
  - from 08:30: observing current session;
  - after the official close-resolution boundary: completed.
- Market calendar phase, instrument phase and observation semantics are separate axes.
- Backend numeric fields remain `null` while unavailable; Frontend renders `"-"`.
- Previous close is a separately dated reference, never today's live price.

## Request bounds and refresh ownership

- `GET /api/market/quote-depth/{stock_id}` retains its existing one-symbol bounded behavior.
- The 08:00 empty-session response returns before provider fetch.
- Existing Frontend polling may schedule one refetch at the backend-provided transition time; it does not decide whether today is a trading day.
- Quote contract capture remains limited by configured canary symbols and fixed slots; additive slots are `09:01`, `09:02`, `13:31`, `13:33`.
- No all-market delayed-open search is allowed.

## Persistence and transaction

- No migration by default.
- `TaiwanStockQuoteSnapshot` remains the raw quote snapshot owner.
- Same-session last-trade retention queries existing rows by stock, trade date, confirmed non-null `last_price` and event-time upper bound.
- `TaiwanQuoteContractSnapshot` remains the fixed-slot public-contract evidence owner.
- Existing service transaction ownership remains; pure resolvers do not receive a DB session.

## Failure and fallback

- Provider failure remains visible through freshness/source-error and may use the existing latest snapshot fallback.
- Normal snapshot-local `z="-"` is not a provider failure.
- With a confirmed earlier same-session `z`, the price may be retained with original `price_as_of` and explicit cached source.
- Without a confirmed price, `v>0` produces trade-occurred/price-missing semantics; OHLC, order book and `pz` are never price substitutes.
- Cached state cannot cross stock or trade date.

## Public and consumer contract

- Additive quote fields:
  - `presentation_trade_date`
  - `presentation_session_state`
  - `presentation_session_transition_at`
  - `market_calendar_phase`
  - `instrument_phase`
  - `actual_trade_occurred`
  - `actual_trade_price_cached`
  - `actual_trade_price_source`
- Existing `session_phase` remains a compatibility projection.
- Replay preserves the captured public payload and adds explicit replay metadata; it must not erase captured indicative evidence.
- AI adds semantic usability axes without silently changing the legacy `decision_usable` field until consumer inventory is complete.
- Frontend/MCP do not parse `z/pz/ps/ts` or reproduce calendar rules.

## Validation

- Pure time and observation resolver cases T00～T19.
- Quote-depth service integration with provider mocks and in-memory SQLite.
- Same-session price retention and cross-day negative cases.
- Replay fidelity and fixed-slot scheduler registration.
- Calendar/API schema and Frontend type/presentation checks.
- AI realtime/capability projection and MCP/public-contract regression after outward changes.
- No external provider smoke until the staged live-acceptance milestone.
