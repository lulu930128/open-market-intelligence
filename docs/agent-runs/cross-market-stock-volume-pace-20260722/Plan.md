# Plan

## Milestones

1. Establish the shared contract
   - Scope: shared calculation/persistence helper and task evidence.
   - Acceptance: market timezone/session/daily-volume inputs are explicit and no index path is included.
   - Validation: targeted pure and SQLite service tests.

2. Integrate context-market services
   - Scope: US, JP, and KR intraday service façades and schemas.
   - Acceptance: one bounded selected-symbol history fetch, persisted idempotently, with a backward-compatible `volume_pace` field.
   - Validation: `test_us_market_data.py`, `test_jp_market_data.py`, and `test_kr_market_data.py` targeted cases.

3. Update consumers
   - Scope: US, JP, and KR stock-detail `today` technical metrics.
   - Acceptance: frontend displays same-time pace or an explicit accumulating state and does not calculate freshness/business logic.
   - Validation: TypeScript typecheck and relevant build/static checks.

4. Verify real data
   - Scope: one bounded stock probe per market against the configured provider/runtime or an isolated service call.
   - Acceptance: timestamps, sample counts, status, and exclusion behavior are observable.
   - Validation: selected-symbol API/data smoke and diff checks.

## Stop-and-fix rules

- If a market response mixes prior-day points into the `today` chart, fix projection before continuing.
- If provider history does not expose interval volume consistently, keep that market `partial` instead of inventing a ratio.
- If persistence causes route incompatibility or transaction leakage, stop and keep the contract read-only until ownership is explicit.

## Decisions

- 2026-07-22: Individual stocks only; indices and market-wide volume are explicitly excluded.
- 2026-07-22: Reuse the existing `market_intraday_bar` table and preserve market-specific daily tables; no migration is needed.
- 2026-07-22: Bootstrap with bounded `5d / 1m` history and accumulate longer baselines locally rather than adding a second hidden provider request.
