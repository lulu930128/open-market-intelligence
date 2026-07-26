# Progress

## Status

- Current phase: implementation, consumer migration, validation and runtime rollout completed
- Last updated: 2026-07-23 Asia/Taipei

## Completed

- Read and applied `productized-project-workflow` and `omi-evolve-ai-decision-contract`.
- Re-read OMI product direction, backend architecture and current dirty worktrees; unrelated changes were preserved.
- Reproduced the pre-change outward-contract defects:
  - v2 decision readiness could be true while Evidence Passport was blocked or partial.
  - JP market context could execute Taiwan market evidence.
  - SSE final business failure could be followed by `done.ok=true`.
  - Slots could appear ready while their freshness domain was stale.
- Defined and implemented `omi.decision.v3` as the single canonical AI decision envelope.
- Preserved `omi.ai.ask.v2` as an explicit compatibility response.
- Centralized readiness, domain freshness, slot reconciliation, business status, continuation and error semantics in the backend AI layer.
- Kept the data and operations APIs intact; only the AI decision plane was consolidated.
- Corrected default regional targets for TW, US, JP, KR and crypto market questions.
- Migrated the frontend OMI Ask Dock, repo MCP, OMI_search and Kuro market preflight to request and consume v3.
- Kept adapters thin: they forward the canonical envelope and do not reconstruct market meaning.
- Added the durable architecture contract at `docs/architecture/OmiDecisionContract.md`.
- Restarted the actual OMI launcher and OMI_search tray so the running services load the new contract.

## Validation evidence

- Targeted backend contract suite:
  - `125 passed, 4 subtests passed`
- Full safe backend profile:
  - compileall passed
  - `917 passed`
  - `git diff --check` passed
  - log directory: `.tmp/validation/20260723-231827`
- Frontend:
  - TypeScript typecheck passed
  - lint passed
  - production build passed
  - targeted OMI Dock v3 Playwright smoke passed
- Repo MCP:
  - unit coverage included in the targeted backend suite
  - live stdio `initialize`, `tools/list` and `tools/call` returned the v3 canonical envelope
- OMI_search:
  - `24 tests OK`
  - live stdio call forwarded v3 without adapter-side re-summarization
  - running 8797 server and tunnel were replaced by the official tray flow
- Kuro:
  - `14 tests OK`
  - non-writing Python syntax check passed
  - tool catalog JSON parse passed
- Live OMI runtime:
  - launcher restarted the stale 8400 backend because source was newer than the process
  - `/api/ai/tools` now defaults to `omi.decision.v3` and still advertises `omi.ai.ask.v2`
  - real TW, US, JP and KR requests resolved to their intended market targets
  - HTTP success and business error responses both used v3
  - SSE emitted consistent `final` and `done` business/transport status
  - a real 2330 response set `decision_ready=false` when chips and fundamentals were stale, and canonical slots were blocked consistently
- Paid API bounded probe:
  - trusted loopback analysis call succeeded through the existing policy
  - LLM output did not override partial or blocked evidence readiness

## Decisions made

- One semantic exit does not require one transport; HTTP, SSE and MCP carry the same final envelope.
- Backend is the only owner of market routing, evidence, freshness, readiness and answer semantics.
- Consumers choose presentation only; they do not independently infer readiness or rebuild answers.
- Paid providers may enrich evidence or analysis but cannot bypass trust, freshness or decision-readiness rules.
- Business success and transport completion are separate fields and must remain consistent across transports.

## Known issues / risks

- The OMI and Kuro worktrees contain many pre-existing unrelated edits; no commit or reset was performed.
- One existing Playwright path for Taiwan/Korea index selection still fails in `IndexDetailDataPanel` because `status` is read from an undefined value. The targeted OMI Dock v3 smoke passes, and this failure is outside the changed decision-contract path.
- Kuro's AI runtime was not listening during rollout. Its source and tests are updated; it will load v3 on the next normal start.
- `omi.ai.ask.v2` remains available for migration safety and should be removed only after all external callers have been observed on v3.

## Next step

- Observe v2 usage during normal operation, then schedule a separate compatibility-removal change once no callers depend on it.
