# Acceptance Matrix

## Current evidence status

- `deterministic_passed`: fixed-time resolver, service, AI projection, replay, fallback, non-decision, freshness and source-health contracts are covered by passing tests.
- `isolated_runtime_passed`: current-source REST/OpenAPI/calendar/quote-empty-frame and repo MCP transport were verified on port `18400` with a separate SQLite database and disabled background work.
- `formal_runtime_passed`: official tray restart passed runtime identity, DB revision/integrity, REST/OpenAPI, frontend health/proxy and repo MCP protocol checks on launcher-selected ports `8400/3270`.
- `live_session_passed`: not claimed for exact 07:59-08:01, opening-handoff or closing-handoff outward windows. These remain surface-specific `not_observed` until captured live.

## Status vocabulary

- `deterministic_passed`：fixed-time fixture / pure contract / unit or integration test passed.
- `isolated_runtime_passed`：separate port, separate SQLite and disabled schedulers passed.
- `formal_runtime_passed`：official launcher runtime and representative public REST/repo MCP passed.
- `live_session_passed`：captured during the actual exchange time window with raw/persisted/public evidence.
- `not_observed`：the condition did not naturally occur or the required outward surface was not captured.
- `provider_limitation`：upstream did not expose a required fact; OMI returned explicit unavailable/partial semantics.

Passing a narrower status never implies a broader status. In particular, deterministic and persisted replay evidence do not by themselves prove AI/MCP behavior during a live session.

## Market-time state matrix

| Case | Request time | Provider evidence | Expected market clock | Expected instrument phase | Price / auction contract | Required status |
|---|---|---|---|---|---|---|
| T00 | Non-trading day | Any previous snapshot | `market_closed` | `closed` | Latest completed reference only; no live claim | deterministic |
| T01 | Trading day 07:59:59 | Previous completed session | `preopen_pending` | `closed` / waiting day rollover | Previous-session reference may remain separately dated; no current-session price claim | deterministic + live outward |
| T02 | Trading day 08:00:00 | No current-session observation | `preopen_pending` | `awaiting_preopen` | Presentation session date becomes today; backend current-session numeric facts null; UI price/volume/change displays `"-"`; no provider call solely for rollover | deterministic + live outward |
| T03 | Trading day 08:01～08:29 | No current-session observation | `preopen_pending` | `awaiting_preopen` | Same as T02; previous close, if shown, remains explicitly previous-session | deterministic + live outward |
| T04 | 08:30 | Provider event still 07:50 | `preopen` | `preopen_auction` | Explicit stale/unavailable; receipt time cannot make event live | deterministic + live replay |
| T05 | 08:50 | `ts=1,pz,ps,z=-,v=0` | `preopen` | `preopen_auction` | Indicative current; actual trade null; execution-grade false | deterministic + live replay |
| T06 | 08:59 | `ts=1,pz,ps,z=-,v=0` | `preopen` | `preopen_auction` | Same as T05; no previous daily trade value fallback | deterministic + live replay |
| T07 | 09:00 request, 08:59:55 event | `ts=1,pz,ps,z=-,v=0` | `regular` | `preopen_auction` or `opening_auction_delayed` | Auction remains applicable; event is not relabeled actual trade | deterministic + live replay |
| T08 | 09:01 | `ts=1,pz,ps,z=-,v=0` | `regular` | `opening_auction_delayed` | Indicative only; `last_trade_available=false` | deterministic; live if naturally observed |
| T09 | 09:02 | `z>0,v>0,ts=0` | `regular` | `regular_traded` | Actual trade becomes authoritative; auction N/A | deterministic; live transition required when observed |
| T10 | 09:02+ | `ts=0,z=-,v=0`, no actual-trade cache | `regular` | `awaiting_first_trade` | Depth may be current; last trade remains unavailable | deterministic |
| T11 | 09:05 | `ts=0,z=-,v>0,OHL present`, no known price | `regular` | `regular_traded` or actual-trade-occurred/price-missing | Do not infer price from `pz`, depth or OHLC | deterministic + live replay |
| T12 | 09:05 | same as T11 plus same-session confirmed cached `z` | `regular` | `regular_traded` | Return cached actual price with original `price_as_of` and cache source | deterministic |
| T13 | 09:05～09:20 | current 1m bar | `regular` | `regular_traded` where evidence exists | Partial/current interval bar can satisfy live window; missing bar stays missing | deterministic + live outward |
| T14 | 13:24 | `z=-,v>0`, same-session price may exist | `regular` | `regular_traded` | Same last-trade retention rules as T11/T12 | deterministic + live replay |
| T15 | 13:28 | `ts=1,pz,ps,z=-` | `closing_auction` | `closing_auction` | Indicative separate; last trade before auction separately identified | deterministic + live replay |
| T16 | 13:30 | provider parse failure, cached 13:28 | `post_close` | closing pending / provider fallback | Cached status and source error visible; no official-close claim | deterministic + live replay |
| T17 | 13:31～13:33 | trial/delayed-close provider state | `post_close` | `closing_auction_delayed` | Auction may remain applicable; official close pending | deterministic; live if naturally observed |
| T18 | 13:32 | current-day `z`, before official deadline | `post_close` | closing pending | Actual close candidate can exist but official confirmation remains pending | deterministic + live replay |
| T19 | 13:34 | current-day confirmed close | `post_close` | `closed` | Official close available with current trade date and event time | deterministic + live replay |

## Cross-surface assertions

Each deterministic time case must be checked, where applicable, across:

1. Pure observation resolver.
2. `get_taiwan_stock_quote_depth()` service projection.
3. Router response model serialization.
4. Persisted quote-contract snapshot and replay API.
5. AI Taiwan compact quote projection.
6. `quote.snapshot` and `quote.auction` capability status.
7. `realtime_contract` temporal and semantic usability axes.
8. `omi.decision.v4` evidence/readiness/decision payload.
9. Repo MCP `omi.ask` projection.
10. Frontend automatic 07:59→08:00 session-date refresh and null-to-`"-"` rendering for T01～T03; other types/rendering only if outward fields change.

## Invariant assertions

### 08:00 trading-day rollover

- The boundary uses Asia/Taipei exchange time and an authoritative Taiwan trading-day result.
- At 07:59:59, the latest completed session may remain the presentation reference; at 08:00:00 on a trading day, the presentation session date becomes today.
- The rollover creates an empty current-session frame, not a market observation: price, volume, change, `price_as_of` and current-session source remain null/unavailable.
- Frontend renders unavailable current-session numeric fields as `"-"`; backend schemas retain `null` and explicit status/reason.
- Previous close may remain visible only in a separately labeled previous-session field with its original trade date.
- A screen opened before 08:00 refreshes at the boundary without a full manual reload.
- The boundary alone does not call TWSE MIS, create a provider event, set auction/live status or make cached prior-session data current.
- Weekend and holiday behavior remains `market_closed`; there is no false today-session rollover.

### Auction versus actual trade

- `pz` never populates `last_trade_price`, `latest actual price`, actual-trade breadth or entry/exit price levels.
- `auction_indicative_available=true` implies `auction.decision_usable=false`.
- Preopen auction may be temporally `live` and `facts_usable=true` while `execution_grade_usable=false`.
- `quote.auction` applicability follows canonical instrument/provider evidence, not request clock alone.
- A current order book without actual trade yields `live_depth_only`, not `live_trade_only`.

### Actual-trade cache

- Only a confirmed same-trade-date actual price may enter cache.
- Cache does not cross trading day, market or stock identity.
- Cache retains original `price_as_of`; `served_at` and `snapshot_time` remain separate.
- Cache age/freshness remains visible.
- If `v>0` but no confirmed price exists, expose occurred/price-missing rather than substituting OHLC, bid, ask or `pz`.
- Provider fetch failure and normal snapshot-local `z="-"` are distinct reasons.

### Replay

- Captured `indicative_match_available/value/volume/source` survives replay.
- Replay does not create a field that was unavailable at capture time.
- `quote_semantics` agrees with availability flags.
- `capture_status=captured_degraded` preserves error and fallback evidence.
- GET replay remains read-only and reports `read_path_side_effects=false`.
- Contract-version projection, if needed, exposes both captured and projected version/digest rather than silently deleting evidence.

### Intraday cache fallback

- `prefer_live + allow_external_fetch=false + fallback_to_cached=true` enables local reader.
- `get_market_intraday_history(refresh=False)` is used.
- Provider mock is not called; no provider event is created.
- Cache hit exposes `persisted_hit` and a policy/cache reason distinct from remote-refresh-failure fallback.
- `fallback_to_cached=false` keeps reader disabled when external fetch is forbidden.

### Data-only and diagnostics

- `decision_required=false` yields empty action plan, scenarios, price levels and position container.
- Technical evidence remains available outside the actionable decision container.
- Negated risk/exit hints do not appear as effective matched hints.
- If raw hints are retained, `raw_matched_hints` and `negated_hints` are explicitly separate from effective hints.

### Freshness and source health

- Required blocked/unavailable capability prevents aggregate readiness from appearing fully current/ready.
- Temporal freshness, availability, completeness and decision usability remain separate axes.
- Current row status and historical latest provider-event status have separate names and timestamps.
- Old historical stale events do not make a current healthy row look stale; current row freshness does not hide historical errors.

## Fixed-slot capture plan

Current canary slots:

```text
08:30 08:50 08:55 08:58 08:59 09:00 09:05 11:00
13:24 13:28 13:30 13:32 13:34
```

Proposed additive slots:

```text
09:01 09:02 13:31 13:33
```

Presentation-session boundary probes（not MIS quote capture slots）:

```text
07:59:59 08:00:00 08:01:00
```

Constraints:

- Apply only to the existing bounded canary contract, initially `2330`.
- The 08:00 probes exercise calendar/session API and Frontend refresh only; they must not add provider calls merely to produce placeholder state.
- Do not scan all stocks looking for delayed open/close.
- Preserve `max_instances=1`, dedupe and current transaction ownership.
- Capture delay, provider event time, request time and persisted time separately.
- If provider or scheduler cost changes materially, stop and report before enabling.

## Live acceptance record template

For each time window, record:

```text
trade_date:
window:
stock_id:
request_time:
provider_event_time:
raw z/pz/ps/ts/v/tv:
market_calendar_phase:
instrument_phase:
quote_semantics:
last_trade_available / price / price_as_of / source:
auction applicability / indicative price / volume:
freshness / age / source error:
REST result:
AI capability result:
repo MCP result:
replay result:
status: live_session_passed | not_observed | provider_limitation | failed
stop-and-fix owner:
```

## Stop conditions during live acceptance

- 08:00 on a Taiwan trading day still shows yesterday as the active session, or populates today's live fields with yesterday's values or zero.
- The 08:00 rollover triggers provider I/O solely to create the empty today-session frame, or a weekend/holiday rolls into a false trading session.
- Any outward surface promotes `pz` to actual trade.
- 09:00 request time alone removes an 08:59:55 trial observation.
- Cached last trade crosses trade date or loses original `price_as_of`.
- Replay contradicts persisted public payload.
- `allow_external_fetch=false` produces provider I/O.
- A required capability is blocked while canonical aggregate says fully ready/current.
- Formal runtime digest/path/port differs from the validated artifact.
- A provider failure is hidden behind HTTP 200 or normal zero.
- A live-session P0 failure occurs; stop further closeout and fix the canonical owner before continuing.
