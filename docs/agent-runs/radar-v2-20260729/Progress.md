# Progress

## 2026-07-29 實際結構審查後續

- Current phase：completed — 阻斷問題已修正，migration 與新 backend runtime 已驗證。
- 已確認目前 local DB 的 Radar v2 feature/evaluation/event/outcome/backtest 表皆為 0 筆；
  本次可使用 additive migration 修正契約，不需轉換既有 v2 研究樣本。
- 已確認 dirty worktree 同時包含其他台股與美股工作；本階段只修改 Radar v2 任務、
  schema/migration、Radar backend 呼叫邊界與相關 targeted tests。
- 已確認問題：
  - `available_at` 實際寫入 persistence time，且日期字串被解析為午夜。
  - v2 只處理 v1 mode filter 與 Top N 後的 `results`。
  - market regime 沒有 signal-time cutoff。
  - event 缺少完整母體 observation 與多事件 outcome 關聯。
  - walk-forward split 未參與 metrics，coverage 分母只包含已落庫 rows。
  - signal strength/freshness/timeframe conflict 未接線。
  - feature hash 使用 scoring hash，market regime 混入 feature identity。
  - overheat continuation/reversal 不可達，公司行動只查除息。

### 修正結果

- Feature time contract 已拆成 `effective_at`、`source_available_at`、`observed_at` 與
  evaluation `decision_at`。Provider 未提供 availability time 時使用 observation-time
  fallback；事後補算且 decision 不在同一交易日的樣本會被 backtest 排除。
- v2 會在 v1 mode/Top N projection 前評估完整 bounded calculation universe，並以
  `radar_universe_observation` 保存 evaluated/no-data/error/absent coverage。
- Market regime 會套用 signal-time cutoff，evaluation 同時保存原始 market snapshot。
- Event lifecycle 已分開 observed-active、unobserved、observed-inactive；資料缺失或掉出
  universe 不再誤判為 exit。
- Evaluation/outcome 已新增 event junction tables，一個 outcome 可追蹤多個 active events。
- Backtest promotion metrics 只使用 purged walk-forward test folds；全樣本 metrics 僅為
  diagnostic。無完整 universe、無 split、OOS coverage/sample 不足或必要 baseline unavailable
  時會 blocked。
- Signal strength/freshness/timeframe conflict 已接線；無法量測時使用 0.5 並留下 limitation。
- Feature/scoring/rule hash 已分離，market regime 不再污染 feature identity。
- Overheat 使用對稱 outcome state；公司行動只有除息覆蓋時標為 `partial_coverage`，不再假裝
  所有價格調整事件都已檢查清楚。

## Status

- Current phase：completed — corrected v2 shadow live
- Last updated：2026-07-29 Asia/Taipei

## Completed

- 讀取使用者 `OMI_台股Radar_v2技術規則與回測模型_工程草案_v0.1.txt` 全文。
- 對照現行 v1 indicator、signal、bucket、priority、snapshot、outcome 與 frontend contract。
- 對齊 `docs/product/` 與 `docs/architecture/BackendArchitecture.md`。
- 確認現有 outcome 每個 snapshot item 只能保存一筆，無法直接支援多 horizon。
- 確認現有 snapshot/evaluation 以 Watchlist group 為 persistence owner，v2 必須增加 group-independent canonical identity。
- 完成本機 DB 唯讀 coverage 稽核：
  - daily range：2012-04-23 至 2026-07-29。
  - latest daily stock rows：83。
  - 自 2024 年起具至少 250 個交易日且 current 的 stock ids：82。
  - Radar snapshot range：2026-06-18 至 2026-07-29。
  - Radar 歷史不同 stock ids：189。
- 確立修正版 v2 路線：canonical schema、Outcome v2、回測 contract、Signal Family、雙 regime、shadow API/UI。
- 新增 `radar_rule_contract.py`，凍結 v1 rule/feature/outcome version、技術權重、priority base 與 outcome thresholds。
- 將 v1 Radar 與 Outcome service 接到凍結契約，未改變既有判定語意。
- 新增 v1 golden contract tests，涵蓋：
  - 大跌 bucket 優先於支撐跌破。
  - 支撐跌破優先於過熱。
  - priority 公式固定案例。
  - 3260 類「盤中風險觸發、收盤強勢反轉」仍為 v1 hit。
  - v1 momentum 先判 hit 的雙向掃價語意。
  - 結構觀察 bucket 的振幅命中。
- 新增七個 group-independent Radar v2 persistence models：
  - `radar_rule_config`
  - `radar_feature_snapshot`
  - `radar_rule_evaluation`
  - `radar_signal_event`
  - `radar_watchlist_projection`
  - `radar_outcome_path`
  - `radar_backtest_run`
- 新增 additive Alembic revision `20260729_0041`；未修改 v1 tables。
- 新增 model contract tests，證明同一 feature 可保存 v1/v2 evaluation，且同一 evaluation 可保存 T+1/T+3/T+5。
- 新增 Outcome v2：
  - T+1/T+3/T+5 交易日 horizon。
  - signal-reference 與 T+1 open entry-proxy。
  - close_R、MFE_R、MAE_R。
  - intraday-triggered、close-confirmed、adverse-triggered、reversed、whipsaw、invalidated。
  - compression/volatility/overheat 非方向 summary。
  - daily OHLC path-order 與 entry-proxy limitation。
  - corporate-action checked/detected/unavailable quality。
- 3260 類案例在 v2 會顯示 `adverse_only`，不再以單一 generic hit 掩蓋收盤反轉。
- 新增 bounded backtest v2 骨架：
  - point-in-time local price coverage。
  - feature availability look-ahead gate。
  - event/evaluation sample identity。
  - purged walk-forward 與 embargo。
  - coverage/sample gate。
  - direction accuracy Wilson interval 與 R/return mean confidence interval。
  - baseline 未具備時明確回傳 unavailable。
- 完成 Signal Family v2：
  - event/state/modifier 與六個 signal families。
  - family saturation、fixed normalization、within-family/cross-family conflict。
  - direction、evidence、risk、confidence、context alignment 分離。
  - absolute evidence grade 不受同批 Watchlist 組成影響。
- 完成雙層 regime：
  - instrument regime 與 high-volatility overlay。
  - market regime 僅接受同分鐘 TWSE/TPEX breadth。
  - 非 ready/full-market 時保留 insufficient/partial limitation。
  - regime-adjusted multiplier 納入 versioned experimental config。
- 完成 shadow API 與 persistence：
  - GET 保留 v1 排序並附加 optional v2 shadow contract。
  - explicit POST 建立 canonical feature/evaluation/event/projection。
  - scheduler 在 v1 snapshot 成功後隔離執行 v2 persistence 與 pending outcomes。
  - `OMI_RADAR_V2_SHADOW_ENABLED=false` 為 hard rollback。
- 完成 Radar summary-first frontend：
  - 顯示 active/shadow version、evaluated/conflict/direction-changed counts 與 market regime。
  - 每筆顯示 v2 direction/evidence grade，detail 顯示 confidence/conflict/risk。
  - frontend 不重算 backend 評分與 regime。
- 新增 `docs/architecture/RadarV2.md`，記錄 canonical contract、回測邊界、runtime 與正式切換條件。
- 完成 local runtime 重載：
  - DB migration revision/head 同為 `20260729_0043`；Radar v2 revisions `0041`、`0043`
    與既有 `0042` 已套用。
  - live GET 顯示 active `radar_v1.0`、shadow `radar_v2.0-shadow`。
  - live `readyz` 顯示 runtime/database 均為 `ok`。
  - `include_shadow_v2=false` 可完整移除 shadow payload。
- 驗證 Radar GET 前後 v2 canonical table counts 不變，read path 無隱性 persistence。

## Validation evidence

- 阻斷修正首輪 safety wrapper 因 `BackendPytestArgs` 逗號清單被 PowerShell 視為單一路徑，
  compileall 通過但 pytest 未執行；改用 string array 後重新驗證。
- `.\\scripts\\run-safe-validation.ps1 -Profile backend`（Radar v2 focused string array）：
  - backend compileall passed。
  - 60 tests passed。
  - `git diff --check` passed。
  - log：`.tmp\\validation\\20260729-223504`。
- 既有 automation regression 首輪有 4 個 fixture 仍 mock 舊的單一 Radar service；production
  已改用 `(public_radar, full_universe)` bundle。同步 fixture 後，既有 Radar/outcome/
  automation/OpenAPI 40 tests 全部通過。
- 最終 backend focused safety wrapper：
  - backend compileall passed。
  - 新舊 Radar、automation、OpenAPI、migration/model 共 100 tests passed。
  - `git diff --check` passed。
  - log：`.tmp\\validation\\20260729-224209`。
- Additive migration 已套用至 local DB：
  - revision/head：`20260729_0043`。
  - 新增 point-in-time 欄位與三個 junction/universe tables。
  - migration 後所有 v2 feature/evaluation/event/outcome/backtest tables 仍為 0 筆。
- Backend child 由 PID 59024 重啟為 PID 62960；`/api/system/health` 為 `ok`，
  `/api/system/readyz` 的 runtime/database 均為 `ok`。
- Live computed Radar GET：
  - public Top 5 保持 v1 active，shadow 為 `radar_v2.0-shadow`。
  - v2 `universe_scope=complete_calculation_universe`，本次評估 83 檔。
  - feature config hash 與 rule config hash 已分離。
  - GET 前後 v2 feature/evaluation/event/universe counts 都維持 0，證明 read path 無寫入。
  - OpenAPI 仍暴露 explicit v2 shadow POST。

- 以 UTF-8 strict read 完成使用者草案讀取，無 replacement character。
- `sqlite3 -readonly data\open_market_intelligence.db ...`：完成 local coverage 與 Radar history 唯讀查詢。
- `git status --short --branch`：確認 worktree 既有多項 unrelated changes；Radar v2 將維持隔離修改。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_v1_contract.py,backend\tests\test_watchlist_radar.py,backend\tests\test_watchlist_radar_outcome.py`：
  - backend compileall passed。
  - targeted pytest passed。
  - `git diff --check` passed。
  - log：`.tmp\validation\20260729-195354`。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_v2_models.py,backend\tests\test_database_model_contract.py,backend\tests\test_database_migrations.py`：
  - backend compileall passed。
  - model/migration pytest passed。
  - `git diff --check` passed。
  - log：`.tmp\validation\20260729-195747`。
- Outcome v2 首輪 validation 發現 fixture OHLC 不可能（close 低於 low）；保留 production validation，修正 fixture 後重跑。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_outcome_v2.py,backend\tests\test_watchlist_radar_v1_contract.py,backend\tests\test_watchlist_radar_outcome.py`：
  - 28 tests passed。
  - backend compileall 與 `git diff --check` passed。
  - log：`.tmp\validation\20260729-200426`。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_backtest_v2.py,backend\tests\test_watchlist_radar_outcome_v2.py,backend\tests\test_watchlist_radar_v2_models.py`：
  - backend compileall、targeted pytest、`git diff --check` passed。
  - log：`.tmp\validation\20260729-200808`。
- Signal Family v2 targeted validation passed；log：`.tmp\validation\20260729-201327`。
- Instrument/market regime targeted validation passed；log：`.tmp\validation\20260729-201620`。
- Shadow persistence/API schema 與既有 Radar automation/outcome regression passed；logs：
  - `.tmp\validation\20260729-202332`
  - `.tmp\validation\20260729-202525`
- Frontend lint 與 TypeScript typecheck passed；log：`.tmp\validation\20260729-202833`。
- Browser 首輪 smoke 證明舊 runtime 仍正常顯示 20 筆 v1 Radar，且沒有 console error；因 backend `reload=False`，尚未載入最後 v2 route contract。
- Hard rollback 與同分鐘 breadth 對齊 targeted tests passed；log：`.tmp\validation\20260729-203344`。
- Radar、migration 與 model focused regression 共 84 tests passed；log：`.tmp\validation\20260729-203808`。
- Frontend lint/typecheck passed；production build 在 sandbox 內因 Next.js worker `spawn EPERM` 中止，依規則在允許環境重跑 `npm run build` 後 passed。
- OpenAPI inventory targeted validation passed；log：`.tmp\validation\20260729-204244`。
- 最終完整 backend suite：
  - 1,231 tests passed。
  - backend compileall 與 `git diff --check` passed。
  - log：`.tmp\validation\20260729-204825`。
- Live API/data smoke：
  - 20 筆 Radar item 均有 v2 evaluation。
  - active/shadow/rollback 分別為 `radar_v1.0` / `radar_v2.0-shadow` / `radar_v1.0`。
  - market regime 為當下 evidence 推導的 `risk_off`。
  - OpenAPI 暴露 explicit v2 POST。
  - GET 前後 feature/evaluation/event/projection counts 均為 0。
- Live browser smoke：
  - summary-first v2 strip、每筆 badge 與 expanded v2 evidence detail 均可見。
  - Radar panel、v2 summary 與首筆結果 `scrollWidth == clientWidth`，無水平溢出。
  - 無 runtime console error；僅有開發模式 Fast Refresh 訊息。

## Decisions made

- 保留 direction/evidence/conflict/risk 分離、event/state/modifier、state/risk tags、T+1/T+3/T+5 與 v1/v2 shadow。
- 不直接核准 state factor、family cap、ATR 門檻、regime weights、context ±15 或三日 cooldown；這些是可版本化實驗參數。
- `entry proxy` 與真實 execution simulation 分離。
- Cross-family conflict 與 time-frame conflict 納入正式 contract。
- Point-in-time universe、corporate action、availability time、purge/embargo 是回測必要條件，不是後續補強項。
- v2 核心 evaluation 與 Watchlist group 解耦，避免同股票跨 group 重複污染統計。
- `OMI_RADAR_V2_SHADOW_ENABLED=false` 是 hard rollback；query 參數與 explicit POST 都不得繞過。
- Market regime 不混用不同分鐘的 TWSE/TPEX snapshot；若沒有 aligned minute，只能使用單一分鐘的 partial evidence。

## Known issues / risks

- 本機長期日線 coverage 目前集中在約 82 檔 current stocks，暫不足以支持全市場結論。
- 現有台股 daily OHLC 本身沒有 adjusted price 欄位；corporate action return basis 尚需正式 contract。
- 日線 OHLC 能計算 MFE/MAE 幅度，但不能判斷盤中有利與不利極值的先後。
- 目前 branch `codex/taiwan-data-surface-v1` 有大量其他進行中變更，本任務不可混入或覆寫。
- Frontend Radar 與 AI/public contract 可能同時被其他工作修改；接線前需重新檢查 diff 與 ownership。
- v2 目前刻意為 shadow-only；未累積足夠 outcome 與 walk-forward 證據前，不取代 v1 排序。
- Point-in-time market/sector baseline 尚未配置；預設 promotion gate 會保持 blocked。
- 台股 corporate-action provider 目前只能確認除息；要求 full-clear 的 backtest 會排除
  `partial_coverage` outcome，直到 adjusted price／完整事件 provider 補齊。
- Local DB 已套用 Radar v2 additive migration `0043`；未建立任何 v2 evaluation row，
  需由 scheduler 或 explicit POST 才會開始累積。

## Next step

- 讓 scheduler 累積完整 universe 的 T+1/T+3/T+5 shadow outcomes，日常監測
  no-data/error/absent、event lifecycle 與 outcome coverage；baseline 與 corporate-action
  coverage 未補齊前，維持 v1 active 且不做 promotion 聲明。
