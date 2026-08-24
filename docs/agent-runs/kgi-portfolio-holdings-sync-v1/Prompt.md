# KGI portfolio holdings sync v1

## Goal

Add an explicit, read-only KGI SuperPy sync path for Taiwan and US portfolio holdings. A successful sync makes KGI the authoritative quantity/cost source for the selected market and replaces the corresponding OMI `portfolio_holding` rows without touching other markets.

## Scope

- Read Taiwan holdings from KGI Account inventory APIs.
- Read US holdings from KGI SubAccount position APIs.
- Normalize the provider response in the isolated KGI bridge without exposing account identifiers.
- Replace one selected market in a single database transaction.
- Add a sync control to the existing portfolio holdings panel.
- Preserve user-authored metadata for symbols that remain held.
- Surface missing cost basis honestly when KGI does not provide it.

## Non-goals

- Orders, order queries, cash balances, realized P/L, or automatic trading.
- Watchlist replacement.
- Scheduled or GET-triggered broker synchronization.
- Changes to JP/KR holdings.

## Hard constraints

- Provider failure or malformed/partial payload must not clear existing holdings.
- The bridge command allowlist remains read-only.
- Account and credential values must never appear in API payloads, logs, or UI.
- A successful empty provider result is allowed to clear only the explicitly selected market.
- US cost basis remains null when the provider does not supply it.

## Done criteria

- Targeted provider/parser, transaction replacement, API, and frontend tests pass.
- Migration supports nullable cost and source metadata.
- Frontend build/type validation succeeds.
- A bounded live smoke can report status/counts without printing private holdings or account identifiers.
