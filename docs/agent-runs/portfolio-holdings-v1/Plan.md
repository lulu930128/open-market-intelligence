# Portfolio Holdings V1 Plan

## Milestones

1. Add portfolio persistence and API contract.
   - Acceptance: `portfolio_holding` has market, symbol, name, quantity, total cost, currency, metadata, timestamps, and active flag.
   - Acceptance: CRUD functions validate supported markets and symbol existence through existing master tables.

2. Connect AI position context.
   - Acceptance: explicit request context and saved portfolio context both map to the existing `position_context` contract.
   - Acceptance: saved context promotes general/risk/trend questions for held stocks into position-risk analysis without implying automatic action.

3. Add sidebar UI.
   - Acceptance: TW/US/JP/KR sidebars show a fixed "持股中" section, allow adding symbol/amount/quantity, selecting a holding, and deleting mistaken entries.
   - Acceptance: layout stays compact and does not replace the existing watchlist groups.

4. Validate.
   - Acceptance: run targeted backend tests for portfolio/migration/AI stage behavior.
   - Acceptance: run frontend type/lint checks for the new component and sidebar wiring where feasible.

## Stop-and-Fix Rules

- If migration tests fail, fix the migration before UI work.
- If existing dirty files produce unrelated validation failures, isolate and report them instead of rewriting unrelated code.
- If portfolio data could imply order execution, keep the wording as research and decision support only.
