# Plan

## Milestones

1. 凍結 contract 與 baseline
   - Scope: 任務文件、相關 source/test/runtime 證據、dirty-worktree overlap。
   - Acceptance: 四個 issue 的 confirmed／not observed、non-goal、相容性與 live acceptance 邊界明確。
   - Validation: UTF-8 readback、task folder `git diff --check`。

2. 收斂 current actual-trade contract
   - Scope: `backend/app/market/twse_mis_observation.py`、`intraday.py`、`schemas.py` 與 focused tests。
   - Acceptance: actual-trade price、history price、各自 event time/source、lag 與 unavailable reason additive 可見；`pz`、bid/ask 與無 `z` 累計量不會成為成交價。
   - Validation: `test_twse_mis_observation.py`、`test_intraday_trend.py`、`test_intraday_contract_remediation.py`、`test_taiwan_stock_quote_depth.py`。

3. 收斂 Today 與 Technical frontend surface
   - Scope: market types、stock-detail hooks/components、TPEX Today mapping、responsive layout 與 E2E fixture。
   - Acceptance: frontend 只呈現 backend contract；TPEX session semantics 與 null volume 保留；Technical 在中寬 viewport 可發現且不強制過窄雙欄。
   - Validation: ESLint、TypeScript、production build、focused Playwright／browser viewport check。

4. 以 coverage 驅動真實試撮 replay
   - Scope: replay client type/hook、Quote Depth mode control、missing/coverage state 與 E2E fixture。
   - Acceptance: 有 capture 才能顯示真實試撮快照；coverage `0`／missing slot 可見；debug preview 不進入正式 mode control。
   - Validation: backend replay regression、frontend lint/typecheck/build、focused E2E。

5. 整體驗證與 live checklist
   - Scope: safe validation、read-only API/runtime smoke、task Progress。
   - Acceptance: deterministic/source checks 通過；formal runtime adoption 與真實交易時段結果分開記錄。
   - Validation: `scripts/run-safe-validation.ps1` 的最小足夠 profiles、`git diff --check`、下一交易時段 probe checklist。

6. 完成 Index Today canonical projection
   - Scope: index intraday public projection、shared schema/capabilities、Today header/indicator/volume rendering 與 2330／TAIEX／TPEX E2E。
   - Acceptance: 5 秒 raw count 保留於 metadata，public points 為 1 分鐘；TPEX closing summary 投影為 13:30 official close；13:33 只留 observation；前端無 index symbol-specific Today 分支。
   - Validation: focused index/intraday backend regression、frontend lint/typecheck/build、production Playwright、既有 runtime raw fixture 的唯讀 source projection。

## Stop-and-fix rules

- 若任何路徑把 `pz`、bid、ask、OHLC 或只有正累計量的 observation 當成 actual-trade price，立即停止並修正。
- 若 current-price convergence 需要 frontend 自行合併兩個行情 payload，停止並回到 backend contract。
- 若 TPEX UI 統一遺失 `bar_type`／`indicator_eligible` 或把 null volume 顯示成零，停止並修正。
- 若 responsive 修改造成圖表寬度不足、水平 overflow 或 Technical 再次不可發現，先修正版面再進下一階段。
- 若 replay UI 顯示 synthetic preview 或在 coverage `0` 時假裝有試撮資料，停止並修正。
- 若 targeted tests 失敗，不進入 broader validation。
- 若失敗與 dirty worktree 的其他任務重疊，先隔離證據；不得 revert 使用者既有變更。
- 未在真實交易時段觀察的條件一律維持 `not_observed`。

## Decisions

- 2026-08-07：本任務獨立於盤中成交量雙軌契約，但必須保留並重用其 session/time-alignment semantics。
- 2026-08-07：將 current actual trade 建模為 backend observation metadata，不讓 frontend 把 Quote Depth 與 intraday 自行拼接。
- 2026-08-07：不把 `xl` 直接改成 `lg`；採內容寬度／可展開互動保護圖表可讀性。
- 2026-08-07：TPEX 可以共用 Today surface，但市場特有 bar semantics 仍由 backend payload 決定。
- 2026-08-07：正式試撮檢視只使用保存的 replay；既有 URL preview 保留為明確 debug-only 路徑，不作產品資料來源。
- 2026-08-08：保留 `_fetch_twse_index_5s_intraday()` raw parser 與 `_fetch_twse_index_5s_ohlc()` daily path；新增 pure public projection，避免 Today 修正改動日／週／月 K。
- 2026-08-08：新增 `display_eligible`，將主圖可見性與 `indicator_eligible` 分離；13:25–13:29 indicative auction 可見但不進 EMA／RSI／MACD，13:30 official close 可進指標。
- 2026-08-08：Today UI capability-driven；`isIndexProduct` 只保留頁面組成用途，不再決定 Today 圖表資料語意。
