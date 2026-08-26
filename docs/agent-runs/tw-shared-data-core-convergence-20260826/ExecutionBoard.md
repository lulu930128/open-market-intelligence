# Execution Board

## Program status

- 狀態：`SOURCE_REMEDIATED_RUNTIME_PENDING`
- Current gate：G2/G3 source重新關閉；G4/G5尚未執行。
- Next primary package：`ADOPT-01`（需另行明確授權runtime adoption與user DB migration）
- Runtime adoption：`PENDING`
- Live-session acceptance：`PENDING`
- 最後更新：2026-08-26 Asia/Taipei

## Board

| Package | Status | Evidence | Blocker / note |
|---|---|---|---|
| BASE-01 | SOURCE_COMPLETE | ArchitectureMap、AcceptanceMatrix、audit artifact | runtime未查，符合audit scope |
| BASE-02 | SOURCE_COMPLETE | Plan、WorkPackages、ValidationStrategy、RiskRegister、DecisionLog；V0 pass | 24-package cross-check與25個test path均通過 |
| CORE-01 | SOURCE_COMPLETE | `wp-core-01-source-20260826.json`；70 targeted tests | pure evaluator尚未接production selection |
| CORE-02 | SOURCE_COMPLETE | `wp-core-02-source-20260826.json`；119 targeted tests | production-wired；runtime adoption pending |
| CORE-03 | SOURCE_COMPLETE | `wp-core-03-source-20260826.json`；126 targeted tests | depth/auction typed wiring complete |
| KGI-01 | SOURCE_COMPLETE | `wp-kgi-01-source-20260826.json`；154 targeted tests | production-unwired adapter seam |
| KGI-02 | SOURCE_COMPLETE | `wp-kgi-02-source-20260826.json`；128 targeted tests | KGI quote remains opt-in injected path |
| KGI-03 | SOURCE_COMPLETE | `wp-kgi-03-source-20260826.json`；163 targeted tests | typed schema / transaction / mandatory reread完成；runtime pending |
| KGI-04 | SOURCE_COMPLETE | `wp-kgi-04-source-20260826.json`；179 targeted tests | shared viewer coordinator + opaque owner token；runtime pending |
| KGI-05 | SOURCE_COMPLETE | `wp-kgi-05-source-20260826.json`；185 targeted tests | source cutover完成；runtime/live仍pending |
| BAR-01 | SOURCE_COMPLETE | `wp-bar-01-04-source-20260826.json`；shared descriptors/adapters/planner | runtime provider IO未驗證 |
| BAR-02 | SOURCE_COMPLETE | typed lineage table + 0070 migration + reread tests | user DB migration未執行 |
| BAR-03 | SOURCE_COMPLETE | explicit POST refresh；GET cache-only tests | runtime adoption pending |
| BAR-04 | SOURCE_COMPLETE | `intraday.py`無provider URL/fallback/commit ownership | legacy projection保留相容欄位 |
| IDX-01 | SOURCE_COMPLETE | typed current index table + 0071 migration + Shared Gateway reread | runtime/provider IO未驗證 |
| BRD-01 | SOURCE_COMPLETE | typed breadth counts/coverage/unknown + raw lineage | runtime/provider IO未驗證 |
| IDX-02 | SOURCE_COMPLETE | summary/intraday GET cache-only；explicit POST refresh | legacy provider helper code仍留在`indices.py`供compatibility adapter使用 |
| TAIL-01 | SOURCE_COMPLETE | market-owned company profile reader/projection；AI無direct ORM query | refresh transaction仍為compatibility owner |
| TAIL-02 | SOURCE_COMPLETE | 0072 component raw IDs/source/event/skew/calculation metadata | legacy derived rows無lineage時fail closed |
| TAIL-03 | SOURCE_COMPLETE | `MigrationOrder.md`、catalog counts與anti-debt guards | 長尾fully migration依規格deferred |
| CROSS-01 | SOURCE_COMPLETE | 474 tests + 21 subtests；frontend lint/tsc/build pass | runtime/UI parity未驗證 |
| ADOPT-01 | PENDING | existing listeners只讀檢查 | 未獲named runtime restart/adoption授權；user DB migration未執行 |
| LIVE-01 | PENDING | source fixture semantics only | 需要合法TW session與KGI entitlement |
| CLOSE-01 | IN_PROGRESS | source/docs/catalog/debt recheck與legacy helper physical removal完成 | G4/G5尚未完成 |

## Pre-commit remediation board

| Package | Status | Priority | Dependency | Closure |
|---|---|---|---|---|
| REM-00 | SOURCE_COMPLETE | Gate | user approval | current evidence/ownership frozen |
| REM-01 | SOURCE_COMPLETE | P0 | REM-00 | breadth partition + scope truth |
| REM-02 | SOURCE_COMPLETE | P1 | REM-01 | canonical `intraday.bars` vocabulary |
| REM-03 | SOURCE_COMPLETE | P1 | REM-02 | stream presentation-only contract/guards/UI |
| REM-04 | SOURCE_COMPLETE | P2/MUST | REM-03 | cp0 allowlist equals actual debt |
| REM-05 | SOURCE_COMPLETE | P1 | REM-04 | current provider IO leaves`indices.py` |
| REM-06 | SOURCE_COMPLETE | P2 | REM-05 | quote-depth physical cleanup |
| REM-07 | SOURCE_COMPLETE | Gate | REM-01～06 | final source checkpoint evidence |

本board只證明source remediation；migration、running runtime與official-session live acceptance仍未執行。

## Source convergence handoff

- P0/P1 production source path已接回Shared Core；GET cache-only、explicit refresh/lease、raw receipt、transaction reread與central quality均有tests。
- P2依範圍只完成company profile seam、derived component lineage與migration order，未把所有長尾誤報為platform-owned。
- 下一個不可由source代替的gate是runtime adoption：launcher-selected port、interpreter、migration revision、direct/proxy/API/UI。
- G4通過後才可在相符official session執行G5；缺session或entitlement維持`PENDING`。

## 更新規則

每包完成時：

1. 更新status與evidence link。
2. 在`Progress.md`記錄changed files、validation、known issues與下一包。
3. 將open decision更新為resolved或保留blocker。
4. 更新RiskRegister中被觸發或已緩解的風險。
5. source complete不自動升級runtime/live狀態。
