# 進度

## 狀態

五個 milestone 已完成；source、targeted regression、前端 v2-only E2E、
正式 launcher runtime 與 browser smoke 均已驗收。

## 已完成

- 建立正式 `radar_v2.0`／`technical_v2.0`／`outcome_v2.0` contract，
  並與 `radar_v2.0-shadow` 使用不同 config hash。
- v2 從完整 `calculation_limit` universe 自主評估、篩選與排序，不再以
  v1 Top-N 作為候選集合。
- urgency、action、reason、setup、timing、risk 與 technical direction
  均由 v2 backend contract 擁有。
- active v2 可獨立保存 snapshot、讀取 latest/history、建立與結算 outcome；
  空結果 scope 也可被正式保存與讀取。
- scheduler 只處理 active v2 persistence 與 outcome reconciliation；
  不再新增 v1 snapshot/outcome，也不再由正式排程新增 shadow run。
- 台股既有 `GET /groups/{id}/radar` 預設回傳 v2；
  `version=v1` 只讀最後一份既有 persisted snapshot。
- 新增 v2 evaluate、snapshot history、outcome latest/history、
  backtest create/latest endpoints。
- AI watchlist context、report projection 與 Frontend 主雷達改讀 active v2；
  Frontend 顯示 active/frozen-v1、完整 universe、validation readiness，
  latest/history/detail outcome 全部改走 v2 read contract。
- Radar v2 outcome 不再直接展開在主雷達內容；Header 在 `Reload` 左側只保留
  `History` 入口，點擊後才載入並顯示 v2 history/detail modal。
- v1 code/schema/data 未刪除，也沒有破壞性 migration。
- v1 snapshot/outcome write route 回 `410 RADAR_V1_FROZEN`。

## 決策

- 採直接切換 operational default、凍結 v1 的方式。
- 不刪除 v1 code/schema/data；v1 降為 read-only history/rollback evidence，
  不再是可執行的 live engine。
- `radar_v2.0-shadow` 與 `radar_v2.0` 使用不同 version/config hash，避免歷史污染。
- 優先沿用現有 point-in-time 資料表，不新增破壞性 migration。
- 回測 readiness 與 operational active 分離。

## 驗證

- 本輪 Backend Radar contract／route／automation／outcome 完整 regression：
  `68 passed`（含最終 limitation normalization 修正）。
- Backend `compileall`：通過。
- Frontend TypeScript `--noEmit`：通過。
- Frontend ESLint：通過。
- Frontend Playwright「Taiwan radar uses v2 outcome history without v1 writes」：`1 passed`。
- Follow-up E2E 同時確認主內容不存在 inline v2 outcome summary，且 Radar Header
  的 button 順序為 `History`、`Reload`。
- `run-safe-validation.ps1 -Profile quick`：compileall、tsc、
  `git diff --check` 全部通過。
- 2026-08-01 正式 launcher 偵測 backend source 已更新並重啟 backend；
  launcher log 最終狀態為 `API OK; UI OK`，實際 backend/frontend port 為
  `8400`／`3000`。
- 正式 API smoke：health `ok`、active engine `radar_v2.0`、
  `legacy_status=frozen`、v2 snapshot 共 8 筆；`version=v1` 只回傳
  `frozen_v1_snapshot`（snapshot date `2026-07-31`）。
- 首次正式 outcome smoke 找到 stored limitation string 與 public dict schema
  不一致造成的 `ResponseValidationError`；已在 service projection 正規化為
  `{code: ...}`，正式重啟後 outcome latest 回傳 `outcome_v2.0`、3 筆 item、
  `status=pending`。
- Browser DOM 與畫面 smoke 已確認台股 Radar 顯示「正式運行」、
  `radar_v2.0／v1 已凍結`，並可開啟 v2 結果歷史 modal；console 無 error/warn。
- 2026-08-01 follow-up Browser smoke 已確認實際桌面版 Header 顯示
  `歷史`、`Reload`，分類統計後直接銜接 v2 雷達清單，不再插入 outcome 摘要。

## 已知風險

- 現行 dirty worktree 包含其他 OMI 工作，修改必須限制在 Radar 相關檔案。
- active v2 已 operational 上線，但 group 3 目前沒有正式 v2 backtest 與
  finalized outcome；readiness 保持 `unverified`，不得宣稱優於 v1。
- 大盤 regime snapshot 在本次 live response 缺資料，UI 正確顯示「大盤資料不足」。
- 本輪不執行會寫入正式 Radar snapshot/backtest 的手動 POST；
  scheduler 後續只累積 v2 outcome。
