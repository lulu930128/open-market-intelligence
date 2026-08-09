# Progress

## Status

- Current phase: Milestones 0-11 complete
- Last updated: 2026-08-04 21:28 +08:00
- Overall state: implementation, migration, live cutover, UI verification and one-message SMTP smoke complete
- Runtime state: launcher/backend/frontend active; backend `8400`, frontend `3270`

## Completed

- Completed the productized task definition and milestone plan from the proposed Dispatch Scheduler v2 design.
- Added the additive `20260804_0051` migration and ORM contract for:
  - schedule run ledger and unique scheduled-slot claim;
  - immutable schedule intent/readiness snapshots;
  - next-run, catch-up, misfire, readiness, retry and archive policies;
  - delivery Message-ID and canonical run/delivery/job relationships.
- Added timezone-aware next-run calculation with explicit UTC normalization, IANA timezone handling, DST gap/fold behavior, Taiwan trading-day mode and stable slot keys.
- Added bounded claiming and catch-up behavior:
  - `latest_only` coalescing by default;
  - bounded `all_slots` support;
  - visible misfire skips;
  - DB uniqueness as the final concurrent-claim guard;
  - fail-closed handling for malformed legacy schedules without blocking healthy schedules.
- Added backend-owned readiness contract `omi.dispatch.readiness.v1` with `generic`, `tw_preopen`, `tw_post_close` and `watchlist_radar` profiles, structured reasons, missing data, warnings, deadlines and source references.
- Added atomic delivery/job/run materialization and a reliable run state machine covering claimed, waiting, queued, sending, retry-wait, success, skipped, error and unknown-result outcomes.
- Added safe restart reconciliation:
  - queued work can reuse the same delivery with a new tracked job;
  - an interrupted SMTP `sending` state becomes an explicit unknown result;
  - unknown SMTP results are never automatically retried.
- Preserved the existing manual run response while routing it through v2 with an explicit immediate-readiness override.
- Added additive run history, run detail, manual v2 run and safe retry API routes, with recipient addresses removed from outward run snapshots.
- Extended the Dispatch Settings UI and zh-TW/en-US/ja-JP text with reliability policies, next/queued/sent state, pause/resume, run history, readiness reasons, attempt counters, errors and retry visibility.
- Fixed a browser-discovered narrow-column overflow in the schedule form and history; the final live DOM measured zero section-level horizontal overflow.
- Added `.env.example`, README reliability/recovery documentation and the guarded `scripts/run-dispatch-smtp-smoke.py` live-smoke runner.

## Migration and backup evidence

- Baseline live DB: revision `20260803_0050`, `quick_check=ok`, zero schedules and 16 deliveries.
- The running launcher restarted at `2026-08-04 21:02:04` and applied `0050 -> 0051` before the planned offline copy; this was confirmed from `logs/backend/2026-08-04/backend.log`.
- The runtime was then stopped by exact launcher PID, WAL was checkpointed, and a consistent post-migration/pre-smoke copy was made at:
  - `data/backups/open_market_intelligence-pre-live-smoke-20260804.db`
- Source and backup sizes both equal `13,782,106,112` bytes.
- Source and backup SHA-256 both equal:
  - `FD72FC932C83A2AABB5246232F9A999B24C07B26B2B16CF9DDD444BAD02B52CA`
- Backup read-only verification: `quick_check=ok`, foreign-key violations `0`, revision `20260804_0051`, schedules `0`, runs `0`, deliveries `16`.
- The earlier page-by-page online backup attempt was too slow and timed out; only its invalid `.partial` and `.partial-journal` files were removed after confirming no backup process remained.

## Validation evidence

- Broad backend regression: 67 tests passed in `.tmp/validation/20260804-203626`.
- Final targeted backend regression: compile passed, 42 tests passed, and `git diff --check` passed in `.tmp/validation/20260804-211121`.
- Final frontend checks: lint, TypeScript and `git diff --check` passed in `.tmp/validation/20260804-212500`.
- Final production build passed outside the restricted sandbox after the sandbox-only `spawn EPERM` result:
  - Next.js `16.2.12` compiled, typechecked, generated all six static pages and finalized page optimization.
- Live browser verification on the launcher-selected frontend port `3270`:
  - settings and dispatch panels opened normally;
  - advanced reliability section exposed 10 controls with expected default values;
  - schedule section horizontal overflow measured `0`;
  - browser console had no error or warning entries;
  - live delivery history displayed the smoke subject, one recipient and success.
- Final live runtime/API verification:
  - health `ok`;
  - readiness `ready`;
  - frontend health HTTP `200`;
  - live OpenAPI exposes schedule-run list/create, run detail and retry routes;
  - smoke run remains queryable after the final restart.
- Final live DB read-only verification:
  - revision `20260804_0051`;
  - `quick_check=ok`;
  - foreign-key violations `0`;
  - active schedules `0`, archived smoke schedules `1`, schedule runs `1`, deliveries `17`.

## SMTP smoke evidence

- Exactly one externally delivered smoke attempt was executed; no resend occurred.
- Subject: `[OMI TEST] Dispatch Scheduler v2 run-1`
- Schedule run: id `1`, status `success`, trigger `manual`, delivery attempts `1/1`, retryable `false`.
- Delivery: id `17`, status `success`, recipient count `1`, no error.
- JobRun: id `4776`, status `success`, no error.
- Message-ID: `<178584977864.36992.492215837328608446.omi-dispatch-17@omi.local>`
- The temporary schedule was archived and the temporary recipient group was deleted; the audit run/delivery/job records were preserved.
- The first smoke command returned process exit code `1` only because the runner compared the existing success value against `sent`; the durable run, delivery and job were all already `success`. The runner predicate was corrected without executing SMTP again.
- Provider acceptance and a recorded Message-ID prove transport acceptance, not final inbox placement; inbox/spam placement remains a recipient-side check.

## Decisions made

- Schedule-slot uniqueness and SMTP delivery certainty remain separate guarantees.
- Queue success updates `last_queued_at`; only SMTP success updates sent/success state.
- Readiness polling and delivery retry use separate counters and deadlines.
- Scheduled catch-up defaults to bounded `latest_only` behavior.
- Manual execution remains immediate and does not consume or rewrite the next scheduled slot.
- Archived schedules and deleted recipient groups do not erase run/delivery/job audit history.
- SMTP unknown results are terminal and non-retryable without explicit operator review.
- The user-provided smoke recipient and SMTP credentials are not stored in tracked source, task docs or fixtures.
- No commit, push or publish was performed.

## Remaining risks / observations

- SMTP success does not prove inbox placement; the recipient should confirm the message arrived and check spam if necessary.
- The final backend log also contains an unrelated Alpha Vantage corporate-event refresh error (`CSV contained no valid events`). It did not affect OMI health/readiness or dispatch, but remains visible as an external-provider issue.
- The worktree contains pre-existing unrelated AI/market/breadth changes. Final scope review must keep those changes separate if a later commit is requested.

## Next step

- Recipient confirms inbox placement. If the user later requests publishing, perform a staged-diff/secret audit and commit only the intended dispatch-v2 scope; do not automatically include unrelated dirty-worktree changes.
