# 美股 Daily Backend Shared Core Source Acceptance

## 結論

- Gate：`US_DAILY_BACKEND_V1_SOURCE_ACCEPTED`
- Source：`accepted`
- Runtime：`adopted`
- Live：`pending`
- Product：`pending`
- Effective rollout：runtime config為`canary`，allowlist=`AAPL`；canonical cache尚未seed。

本artifact只接受source contract、migration definition、deterministic fixtures與isolated/in-memory persistence證據。它不代表production DB已升級、running process已載入、provider entitlement可用或Frontend／MCP已顯示新語意。

## 已接受的source surface

- Shared provider-neutral refresh requirement、cursor/checkpoint、typed dispatcher與postcondition evaluator。
- Yahoo Chart／Alpha Vantage V2 descriptors、bounded acquisition及pure canonical adapters。
- Raw receipt + canonical bar atomic transaction、完整lineage與Alembic `20260829_0073`定義；migration只在isolated SQLite驗證。
- `USDailyOhlcvPlatform` cache-only read與explicit refresh；mandatory persisted reread後才可滿足postcondition。
- TSM stock與`^SOX` index identity／volume applicability vertical slice。
- Priority research與full-market EOD共用platform／transaction／expected-state owner。
- REST chart/history compatibility、previous close、technical／Radar、valuation、AI、regional freshness、overnight impact與ADR／cross-market consumer cutover。
- Point-in-time read的receipt `available_at` cutoff；late backfill不得倒灌歷史decision context。
- Manifest、architecture current truth與US raw consumer negative guard。

## Validation evidence

- M0 baseline：143 passed、4 pre-existing failed；其中outward/OHLC 3項已修正，Foundation historical hash mismatch保留為dirty baseline。
- Shared contract與TW affected regression：M1記錄66 Shared + 41 TW passed。
- M2–M6 acquisition／repository／transaction／platform／vertical slice／lifecycle targeted suites均通過。
- M7 consumer matrix：111 passed；ADR／cross-market point-in-time matrix：28 passed。
- M8 primary matrix：350 passed；dark-boundary收斂後剩餘已知無關failure只有歷史Foundation hash checkpoint mismatch。
- 最終Source acceptance matrix：353 passed、451個既有SQLAlchemy／sqlite3 adapter deprecation warnings；新增history projection與所有改版legacy fixture均納入重跑。
- Architecture checker：PASS，22 actual／22 declared；architecture + US boundary + dark import matrix 25 passed，無undeclared或stale debt。
- `git diff --check`無whitespace error；Windows line-ending warnings不視為diff failure。
- Repo safe-validation wrapper注入隔離`PYTHONPYCACHEPREFIX`後，`compileall backend/app`通過。
- 全量backend pytest跑至100%，但共享dirty baseline仍有本計畫外failure，且pytest session cleanup被既存basetemp ACL拒絕而未產生可信總結；本Source gate因此以明確列舉、全綠的353項相關矩陣為正式證據，不宣稱整個dirty worktree全綠。

## Pending gates

1. 已完成：正式launcher重啟、root／interpreter／8400與3000 listeners、migration `20260829_0073`及direct／proxy readiness readback。
2. 待授權：在合法entitlement／quota下bounded explicit refresh AAPL、TSM、`^SOX`，建立真實raw receipt與canonical lineage。
3. 待驗證：persist/reread、restart readback及provider failure/fallback。
4. 待驗證：REST、AI、MCP、Frontend對expected/latest、selected lineage、freshness與volume applicability一致。
5. 另行取得full-market seed、commit、push與release授權。

上述任一項未完成時，不得把Source acceptance升級成Runtime、Live或Product acceptance。
