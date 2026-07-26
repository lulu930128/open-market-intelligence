# Crypto 工作區資料成熟度計畫

## Milestone 1：盤點與 contract 定義

- 核對 registry、provider instruments、watchlist 預設、自動刷新與 DB 實際 coverage。
- 定義 asset maturity、slot status、applicability 與 summary counts。

驗收：contract 能明確說明 registry 9 與 watchlist 8 的差異，不把 provider pending 或非適用資源算成資料故障。

## Milestone 2：Backend 聚合

- 新增 read-only workspace summary builder 與 schema。
- 新增 GET endpoint。
- 修正 market-cap identity 與 spread applicability。
- 補 asset rollup / edge-case tests。

驗收：in-memory regression 可覆蓋 ready、partial、missing、not_applicable、event_quiet / provider_pending。

## Milestone 3：Frontend 呈現

- 加入 workspace summary types 與 fetch。
- 在既有 Crypto 側欄節奏內顯示 registry 與資料成熟度，不改動商品／貨幣架構。
- 加入繁中、英文、日文文案與必要 smoke fixture。

驗收：側欄數字語意清楚、字級一致、失敗時保留 watchlist 可用性並顯示 partial load。

## Milestone 4：驗證

- 跑 targeted backend tests 與 compile check。
- 跑 frontend lint、typecheck、build。
- 有實際 UI 風險時執行 bounded browser smoke / screenshot。
- 更新 Progress.md 的證據與已知限制。

停止規則：任何驗證失敗先修正；若失敗屬於既有 dirty worktree，需隔離並記錄證據，不得用 reset 或覆寫處理。

## Milestone 5：台股式自動更新體驗

- 對照台股、Crypto auto-refresh、resource on-select / stale-repair 與背景 quote polling。
- 將貨幣 subscription 預設及既有 resource manual policy 升級為 `on_select`。
- 移除 Crypto header、K 線、商品／貨幣圖表與 Crypto sidebar 的 Reload／更新報價控制。
- 補 smoke assertion，確認貨幣選取會自動 POST bounded snapshot refresh，且主要畫面沒有手動刷新按鈕。

驗收：使用者只需選取資產；程式依 subscription policy 自動補資料，畫面仍顯示 freshness、partial 與 provider failure。
