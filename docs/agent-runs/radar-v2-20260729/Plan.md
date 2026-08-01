# Plan

## 2026-07-29 阻斷修正里程碑

- Status：completed；四個阻斷修正里程碑已實作、套用 migration 並完成 live read-only smoke。

1. Point-in-time 與完整母體
   - Scope：時間欄位、decision cutoff、完整 v2 universe、projection 分離、regime raw evidence。
   - Acceptance：日線樣本不因落庫較晚被誤判 look-ahead；盤中 regime 不讀取 signal
     time 之後資料；coverage denominator 可由 universe observation 重建。
   - Validation：Radar shadow、migration、backtest targeted tests。

2. Event 與 outcome 關聯
   - Scope：universe observation、event unobserved／exit、evaluation-event 與
     outcome-event junction。
   - Acceptance：掉出 Top N 不會遺失觀察；資料缺失不會被誤判 exit；一個 evaluation
     的多個 event 都能被 outcome 與 backtest 追蹤。
   - Validation：model、shadow persistence、outcome idempotency tests。

3. 真正 OOS backtest
   - Scope：per-split metrics、test-fold aggregate、母體 coverage、baseline readiness、
     promotion gate。
   - Acceptance：全樣本 metrics 不得作為 promotion 指標；無 split、無 point-in-time
     universe 或無必要 baseline 時必須 blocked。
   - Validation：backtest regression 與 deterministic rerun。

4. Scoring 與 outcome 精度
   - Scope：signal strength/freshness/timeframe conflict、feature hash、regime evidence、
     overheat summary、corporate action coverage。
   - Acceptance：signal contribution 不再全部固定 strength/freshness=1；不可達 outcome
     state 移除；未覆蓋的公司行動要明示 limitation。
   - Validation：scoring、regime、outcome targeted tests。

## 新增 stop-and-fix 規則

- 若完整母體只能靠 presentation Top N 推估，停止 backtest promotion，不製造 coverage。
- 若來源可用時間只能推估，允許 shadow 落庫，但必須記錄 inference limitation。
- absence、no-data 與 explicit signal exit 必須分開；任何測試若把三者混為一談，先修正契約。
- OOS test fold 為空、baseline unavailable 或 confidence interval 無法計算時，promotion
  必須 blocked。

## Milestones

1. 凍結 v1 與建立工程基線
   - Scope：任務文件、v1 config snapshot、golden cases、現有 API/DB/coverage inventory。
   - Acceptance：v1 規則、輸入、輸出與已知反轉案例可重現；無既有資料寫入。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar.py,backend\tests\test_watchlist_radar_outcome.py`

2. 建立 canonical Radar v2 schema
   - Scope：ORM models、Alembic migration、version/config helpers、feature/evaluation/event/projection/outcome/backtest identities。
   - Acceptance：migration additive；v1 tables/constraints 不變；v2 row identity 可跨 group 去重並容納多 horizon。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_database_migrations.py,backend\tests\test_watchlist_radar_v2_models.py`

3. 實作 Outcome v2
   - Scope：T+1/T+3/T+5、signal-reference、entry-proxy、ATR R、flags、summary state、quality/limitations。
   - Acceptance：方向型與非方向型 outcome 分開；原始 metrics 可重算 summary；日線 path order 不被猜測。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_outcome_v2.py`

4. 建立回測與 coverage contract
   - Scope：point-in-time universe、availability gate、event cluster、purged walk-forward、baseline、統計與 backtest run persistence。
   - Acceptance：Train/validation/test 沒有 horizon overlap leakage；缺 coverage 與排除原因可見；不宣稱全市場。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_backtest_v2.py`

5. 實作 Signal Family v2
   - Scope：event/state/modifier、signal strength、family saturation、direction/evidence/conflict/risk/confidence、固定 normalization。
   - Acceptance：同家族重複訊號飽和；跨家族矛盾可見；absolute grade 不依批次排名。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_scoring_v2.py`

6. 加入 regime 與版本化設定
   - Scope：instrument regime、market regime、regime clarity、實驗 family weights、canonical config hash。
   - Acceptance：instrument/market 語意分開；不明確 regime 降低 confidence；同 config 可重現。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_regime_v2.py`

7. 接上 shadow API 與 frontend
   - Scope：watchlist routes/schemas、scheduler shadow run、feature flag、Radar summary-first UI、outcome path detail、i18n。
   - Acceptance：v1 route/shape 相容；v2 預設 shadow；UI 不重算 backend 邏輯並顯示版本、quality、tags 與限制。
   - Validation：backend API inventory、frontend lint/typecheck、focused Radar E2E。

8. 全面驗證與回滾演練
   - Scope：migration、backend regression、frontend build、API/data smoke、shadow comparison、Progress/Design 文件。
   - Acceptance：所有失敗已修正或明確隔離；active version 可切回 v1；無 unrelated diff。
   - Validation：`.\scripts\run-safe-validation.ps1 -Profile backend`、`.\scripts\run-safe-validation.ps1 -Profile frontend`、`git diff --check`

## Stop-and-fix rules

- 若 v1 golden cases、既有 Radar route 或 snapshot history regression 失敗，先修正相容性再進下一階段。
- 若 migration 需要覆寫、重建或刪除 v1 資料，停止並改為 additive schema。
- 若同一 feature evaluation 仍因 group 重複，先修正 canonical identity，不以查詢時去重掩蓋。
- 若 outcome 需要猜測 corporate action、盤中順序或可成交性，回傳 partial/unevaluable 與 limitation。
- 若 feature 使用的資料在 snapshot 時尚未發布，視為 look-ahead bug，停止後續回測。
- 若本機 coverage 不足，縮小研究 universe 並揭露 coverage，不啟動隱性全市場回補。
- 若分數 normalization 會隨 Watchlist 組成改變，分離 absolute score 與 percentile 後再繼續。
- 若 regime 未能在 walk-forward 顯示穩定增量價值，不接入 active scoring。
- 若 frontend 需要自行推導 bucket、freshness、outcome 或分數，先補 backend contract。
- 若驗證失敗與其他 dirty worktree 變更有關，隔離並記錄，不 revert 使用者變更。

## Decisions

- 2026-07-29：採用使用者 v0.1 草案作為方向基底，但以修正版資料架構與防洩漏規則取代有衝突段落。
- 2026-07-29：Outcome v2 與 canonical event/evaluation schema 優先於技術權重重構。
- 2026-07-29：將 `executable outcome` 改稱 `entry proxy outcome`，避免過度承諾可成交性。
- 2026-07-29：將 `instrument_regime` 與 `market_regime` 分離。
- 2026-07-29：Alert cooldown 與 backtest sampling 分離。
- 2026-07-29：v2 初期 shadow-only；正式切換不以單一 hit rate 決定。
