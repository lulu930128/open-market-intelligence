# Portfolio Holdings V1

## Goal

Add a first-class "持股中" entry to the country stock sidebars so the user can record held symbols, total cost amount, and quantity, then let OMI use that position context when answering stock risk/holding questions.

## Scope

- Markets: Taiwan, US, Japan, Korea stock sidebars.
- Backend: persist holdings in an explicit portfolio table and expose bounded CRUD APIs.
- AI: enrich stock ask requests with saved position context when the selected target has an active holding.
- Frontend: show a fixed "持股中" sidebar section with compact add/delete/select behavior.

## Non-Goals

- No crypto holdings in this version.
- No broker import, tax lots, realized P/L, cash accounting, or order execution.
- No automatic trading or order placement behavior.
- No frontend-only portfolio logic.

## Done Criteria

- A migration creates the holding table without touching local SQLite data directly.
- The backend can create/list/update/delete holdings for TW/US/JP/KR.
- The AI ask pipeline can receive or auto-attach holding context and produce position-aware analysis for stock targets.
- The country sidebars show and manage "持股中" without duplicating detail-header controls.
- Targeted backend and frontend checks are run or clearly reported if blocked.
