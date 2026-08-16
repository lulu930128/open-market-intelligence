# Plan

## Milestones

1. [completed] 收斂 indicator 計算成本
   - Scope: `backend/app/market/indicator_service.py` 與 targeted tests。
   - Acceptance: 交易日缺口判定不再隨 MA window 數量重複掃描，指標結果保持相同語意。
   - Validation: `test_technical_parameters.py`、2330 read-only benchmark。
2. [completed] 修復 Launcher 執行期 bind failure
   - Scope: `scripts/run-service-logged.ps1`、`scripts/omi-launcher.ps1` 與 runner contract test。
   - Acceptance: bind failure 使用專用 exit code，launcher boundedly 重選 port、同步 proxy environment 並重啟兩端。
   - Validation: PowerShell AST、isolated runner smoke、launcher contract test、正式 runtime adoption。
3. [completed] 收斂 cache-first polling 與 DB contention
   - Scope: regional tape、US ranking preload、US provider/session boundary 與 regression tests。
   - Acceptance: polling / inactive preload 不觸發 provider refresh；provider HTTP 不持有 caller SQLite pool connection。
   - Validation: contention tests、US targeted regression、frontend lint/typecheck。
4. [completed] 整合驗證與 runtime adoption
   - Scope: safe validation、live HTTP probes、launcher reload、browser smoke、post-start log audit。
   - Acceptance: Backend/Frontend ready、proxy 一致、K 線 / Radar / 132 檔清單完成，無斷線 banner、500、console error 或新 runtime error。

## Stop-and-fix rules

- 若 indicator 結果語意或缺口測試回歸，停止 runtime adoption 並先修正。
- 若 bind recovery 形成無界 retry、未更新 proxy 或遺留舊 Frontend owner，停止並修正 lifecycle。
- 若 provider wait 仍可佔滿 pool，必須繼續縮小 session/transaction boundary。
- 若 live runtime URL 與 launcher source/env 不一致，不可只以 source test 宣稱完成。

## Decisions

- 2026-08-16：timeout 不是單一 pool-size 問題；主因是錯誤 port lifecycle、重複 indicator 計算及 polling/provider ownership 混在 read path。
- 2026-08-16：Radar 保留 closed-session snapshot contract，不把快路徑改回 full compute。
- 2026-08-16：非當前市場允許 cache preload，但禁止 stale cache 自動發動 provider refresh。
