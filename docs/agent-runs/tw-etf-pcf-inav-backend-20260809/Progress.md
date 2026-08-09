# Progress

## Status

- Current phase: backend runtime adoption and frontend connection verified
- Last updated: 2026-08-09 Asia/Taipei

## Completed

- Connected Yuanta's official `PCF/Daily` JSON API and parsed in-kind, cash, stock, future, ETF, and bond component sections.
- Connected Yuanta's iNAV SignalR `compareHub/RetrieveCompare` one-shot flow with a hard bound of five HTTP requests.
- Added an issuer-specific TLS compatibility session that clears only `VERIFY_X509_STRICT`; CA and hostname verification remain enabled and `verify=False` is not used.
- Added PCF snapshot/component and iNAV snapshot models plus Alembic migration `20260809_0055`.
- Added idempotent PCF/iNAV upserts and a bounded 1,200-row iNAV retention policy per ETF.
- Extended the cache-only overview and explicit refresh backend contract without changing the existing route paths or the default profile/daily-NAV refresh behavior.
- Exposed `pcf` and `component_exposure` capabilities for supported Yuanta ETFs while keeping `holdings=false`, because PCF is not a complete holdings disclosure.
- Kept the work bounded to backend market data; frontend, AI decision, MCP, and Kuro-facing contracts were not changed.

## Validation evidence

- Safe backend validation passed: compileall, 34 targeted pytest cases, and `git diff --check`.
- Validation logs: `.tmp/validation/20260809-171202`.
- Migration head: `20260809_0055`.
- Live provider smoke for `0050` succeeded:
  - PCF effective date `2026-08-10`, reference date `2026-08-07`, 50 parsed components.
  - iNAV observed at `2026-08-07T05:31:00+00:00`, estimated NAV `102.76`, market price `102.85`, computed premium/discount `0.0875827%`.
- Because 2026-08-09 is Sunday, that live iNAV sample is a prior-session observation and the overview reports it as `closed`, not `current`.

## Runtime adoption and frontend follow-up

- The user restarted OMI at 2026-08-09 17:20 Asia/Taipei. Live port 8400 exposes the new refresh fields and the SQLite migration is active.
- A bounded live refresh for `0050` completed with six provider requests, 50 PCF components, and a prior-session iNAV snapshot classified as `closed`.
- The frontend refresh now requests supported PCF/iNAV resources and renders backend-owned freshness, iNAV metrics, and the PCF component basket.
- Frontend safe validation passed: lint, TypeScript, and `git diff --check`. Logs: `.tmp/validation/20260809-173244`.
- Focused Playwright verification passed by reusing the existing port 3000 dev runtime: `1 passed`.

## Remaining limitations

- No scheduler or continuous intraday collector was added; iNAV remains an explicit bounded refresh operation.
- Issuer-specific PCF/iNAV coverage currently supports Yuanta ETFs. Unsupported issuers remain explicit.
