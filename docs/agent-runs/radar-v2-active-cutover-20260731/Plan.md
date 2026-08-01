# 實作計畫

## Milestone 1：契約與獨立投影

### 工作

- 保留 `radar_v2.0-shadow` 歷史 contract。
- 新增 `radar_v2.0`、`technical_v2.0`、`outcome_v2.0` active contract。
- 將 v2 item evaluation 參數化，使 shadow 與 active 版本可並存。
- active urgency 由 v2 evidence、risk、event actionability 與 direction strength 推導。
- active mode filter、排序、bucket/action/reason/limitations 由 v2 產生。

### 驗收

- 完整 universe 均被評估。
- 公開 Top-N 由 v2 priority 排序。
- v1 urgency、context score 與 Top-N 不參與 active v2 排名。

### 驗證

- `backend/tests/test_watchlist_radar_scoring_v2.py`
- `backend/tests/test_watchlist_radar_shadow_v2.py`
- 新增 active projection targeted tests。

## Milestone 2：持久化、讀取與結果追蹤

### 工作

- 將 feature/evaluation/event/universe/projection persistence 改為 contract-aware。
- active projection 保存完整公開 item 與 scope metadata。
- 提供 latest/history read model。
- 提供 v2 outcome latest/history summary。
- pending reconciliation 依 rule/outcome contract 篩選，採 oldest-first bounded 執行。
- 暴露 backtest/outcome readiness，不把缺乏證據視為成功。

### 驗收

- v2 read path 不需 v1 snapshot。
- 舊 shadow rows 可繼續讀取與評估，不與 active identity 衝突。
- 可重新評估已有日線資料的 pending outcome。

### 驗證

- `backend/tests/test_watchlist_radar_outcome_v2.py`
- `backend/tests/test_watchlist_radar_backtest_v2.py`
- 新增 persistence/read/reconciliation tests。

## Milestone 3：切換 consumers

### 工作

- `/radar` 預設 v2，`version=v1` 限制為 frozen snapshot read。
- scheduler 收斂為 active v2 persistence/outcome reconciliation，不再寫入 v1 或 shadow。
- AI watchlist context 使用 v2 public projection。
- Frontend 主頁、history、outcome 全面改用 v2 active/readiness contract，
  移除 v1 outcome evaluate 與把 v2 稱為 shadow 的主畫面文案。

### 驗收

- API、Frontend、AI 使用同一 top-level v2 projection。
- v1 frozen history 不需資料轉換，既有資料完整保留。
- US/JP/KR shared schema 不受破壞。

### 驗證

- Radar router/automation/AI projection targeted tests。
- Frontend lint、typecheck；必要時 build。
- live backend `/radar` 與 frontend DOM/screenshot smoke。

## Milestone 4：v1 凍結與 frontend v2-only

### 工作

- 定義 `radar_v1.0` lifecycle 為 `frozen`，保留既有 rule config hash。
- v1 snapshot/outcome POST 回傳 `410 RADAR_V1_FROZEN`。
- `version=v1` 只讀 persisted snapshot，不套用 current-date gate、不做 live compute。
- frontend hook 明確傳 `version=v2`，latest/history/detail 只讀 v2 outcome endpoint。
- history modal 直接呈現 backend `summary_state`、return、MFE、MAE、quality 與 limitations。

### 驗收

- 排程執行前後 v1 snapshot/outcome row 不增加。
- v1 write route 不會進入 service transaction。
- frontend E2E 若發出任何 v1 outcome request 立即失敗。
- v2 operational active 與 validation readiness 仍分開呈現。

## Stop-and-fix 規則

- 若 v2 GET 產生寫入，停止切換並修正 transaction boundary。
- 若 v2 遺失 freshness/limitations，停止切換並補齊契約。
- 若 active persistence 會覆寫 shadow/v1 identity，停止並改為 additive identity。
- 若 frontend 或 AI 重算 direction/action，停止並移回 backend。
- 若驗證顯示 v2 只有 v1 Top-N universe，停止並修正輸入/投影分界。
