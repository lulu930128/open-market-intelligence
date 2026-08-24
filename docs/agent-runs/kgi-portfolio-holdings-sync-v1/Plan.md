# Plan

1. Extend the KGI isolated bridge with explicit Taiwan/US portfolio read actions and safe account selection.
2. Add normalized provider contracts and unit coverage for malformed, short, empty, and missing-cost rows.
3. Add portfolio source metadata and nullable cost basis through Alembic.
4. Implement a one-market transactional replacement service and explicit POST API.
5. Add the sync action and truthful source/cost state to the existing holdings panel.
6. Run targeted backend/frontend validation, then a privacy-preserving live provider smoke and guarded database sync.

## Stop-and-fix rules

- Do not mutate holdings when login, permission, account selection, parsing, or completeness validation fails.
- Do not use a provider market price as acquisition cost.
- Do not continue to live database replacement until a backup succeeds.
- Do not expose raw broker rows outside the isolated bridge.
