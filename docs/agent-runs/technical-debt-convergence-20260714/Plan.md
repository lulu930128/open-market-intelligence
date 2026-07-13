# Plan

## Milestones

1. Frontend contract 與 regression gate
   - Scope: API payload guard、portfolio panel、Playwright fixture、GitHub Actions。
   - Acceptance: malformed payload 顯示局部錯誤，既有兩條 smoke 與新增 regression 通過。
   - Validation: `npm run lint`、`npm exec tsc -- --noEmit --incremental false`、`npm run test:e2e`。

2. Provider observability 與 source-health age
   - Scope: provider fallback helper、台股 intraday/index fallback、source-health read contract。
   - Acceptance: canonical provider failure 以獨立 transaction 記錄；非 provider 例外只記安全 log；舊 snapshot 明確標記 stale。
   - Validation: targeted provider/intraday/index/source-health tests。

3. Runtime 與 schema ownership
   - Scope: process file lock、runtime coordinator、Alembic startup、migration parity。
   - Acceptance: 只有 background leader 啟動 scheduler/crypto；正常 startup 不再呼叫 `create_all`；migration tables 與 metadata 完全一致。
   - Validation: runtime lock/runtime/database migration tests。

4. Reproducibility 與文件
   - Scope: backend dependency pins、Python CI matrix、README、architecture review。
   - Acceptance: Python 3.11/3.13 contract 明確，CI 有 pip check、typecheck、Playwright，架構基準反映目前狀態。
   - Validation: full safe validation、production build、E2E、`git diff --check`。

## Stop-and-fix rules

- 任一 targeted test 失敗時先修正，不把失敗累積到 full regression。
- 若 runtime lock 造成單程序啟動或 shutdown regression，停止後續工作並先恢復 lifecycle 正確性。
- 若 migration parity 暴露 model/migration 不一致，先補 migration，不以 `create_all` 掩蓋。
- 若 E2E 需要未列出的 API fixture，明確補 fixture；禁止 catch-all 回傳任意成功 payload。

## Decisions

- 2026-07-14：使用 OS file lock，不新增 locking dependency，避免平台 lock 行為依賴未鎖套件。
- 2026-07-14：source-health GET 只揭露 snapshot age，不在 read path 自動重算全市場 health。
- 2026-07-14：只 pin direct Python dependencies，維持跨 Windows/Python minor 的可安裝性；CI 驗證最低與目前主要版本。
