# 台股正式市場廣度與試撮語義根治

## 目標

- 根治 TWSE MIS `pz` 試撮參考價被當成正式成交價，進而污染漲跌家數、
  漲跌停、盤中 screening、熱門群組、Radar 與 AI 回答的問題。
- 在既有 `tw.intraday_stock_state.v1` 與 `omi.decision.v4` 上採 additive 演進，
  建立 backend-owned、session-aware、可追溯價格事件時間的 canonical v2 state。
- 讓正式市場廣度、試撮狀態、coverage、freshness、scope 與 decision usability
  在 REST、AI、MCP、Frontend 與 Radar 間維持一致。
- 完成至 M10 的 source、migration、regression 與本機正式 runtime rollout；
  下一個交易日上午的盤前／開盤實際數據由使用者接續驗收。

## 非目標

- 不做自動交易、下單或保證漲跌的市場判斷。
- 不重寫既有 TWSE／TPEX registered-universe 定義。
- 不在 Frontend、MCP 或 Radar 重做市場 session、價格或 freshness 邏輯。
- 不刪除、重建或猜測性改寫既有 SQLite 歷史列。
- 不在 GET/read path 增加全市場 refresh、回補或其他昂貴 side effect。
- 不藉機升級 dependency、格式化無關檔案或重寫整個 `indices.py`。
- 不 commit、push 或 publish，除非使用者另行明確要求。

## 硬性限制

- `z` 是正式最後成交價候選；`pz` 只能是 `auction_indicative`，不得進入
  正式 advance／decline／unchanged、limit-up／limit-down 或 trade value。
- 正式價格 cache 只能沿用同一市場、股票、交易日中已確認的 actual trade；
  cache 命中不得把新的 provider snapshot time 寫成舊價格的 `price_as_of`。
- `unknown` 不得折入 `unchanged`；coverage 與 universe invariant 必須可驗證。
- 盤前正式 breadth 必須是 `pending_regular_session`；若提供試撮資訊，必須
  以獨立、provisional、不可供正式決策的 contract 呈現。
- Backend market/AI layer 是價格、session、freshness、quality 與 outward
  answer contract 的唯一 owner；consumer 只能呈現。
- DB schema 只走 additive Alembic migration，舊列保留為 legacy/untrusted。
- `evidence.capability_status` 是 consumer-facing readiness 的唯一權威。
- `decision_usable=false`、partial、pending 或 mixed scope 不得輸出無保留的
  高信心整體市場多空結論。
- 正式 rollout 發生問題時只能降級為 pending／partial／unavailable，不得
  回退到已知錯誤的 `pz` 正式廣度。

## 背景與現況

- Repo：`C:\project\Open Market Intelligence`。
- 規格／缺陷整理：
  `C:\Users\thoma\Downloads\OMI_v4_盤前開盤市場廣度工程缺陷整理_2026-08-03.txt`。
- 建立任務時 branch：`main`，HEAD `2d0476d`，worktree clean。
- 既有盤中契約任務：
  `docs/agent-runs/tw-intraday-contract-convergence-20260730/`。
- 既有 canonical state：`taiwan_intraday_stock_state`，version
  `tw.intraday_stock_state.v1`。
- 已確認 P0 根因位於 `backend/app/market/indices.py`：
  `latest_price = _as_float(message.get("z")) or _as_float(message.get("pz"))`。
- 既有 cache 只檢查 `trade_date`，沒有 price semantics/source，且命中後會以
  新 MIS message time 覆寫價格事件時間。
- `o/h/l` fallback 在沒有正式成交證據時仍可能分類方向。
- `reset_twse_mis_breadth_guard()` 未清除 `_TWSE_MIS_STOCK_STATE`。
- 08:55 scheduler 已可能把盤前試撮污染後的 breadth 寫入
  `taiwan_market_minute_state`。
- AI evidence 已能揭露 partial/mixed/decision unusable，但 human answer composer
  仍可能輸出高信心偏多結論。

## Contract Canvas

| 項目 | 契約 |
| --- | --- |
| Product scope | 台股核心市場的正式廣度可信度與盤前研究狀態。 |
| Target | TWSE、TPEX 中既有 active stock registered universe；不改 membership policy。 |
| Provider | TWSE MIS stock messages；不新增付費來源或額外 quota。 |
| Resource | 正式 last trade、試撮 indicative match、previous close、累計量與 breadth aggregate。 |
| Freshness | Asia/Taipei、台股交易日、preopen／regular／closing auction／post-close session。 |
| Request bounds | 沿用既有 universe batching、timeout、circuit breaker 與 refresh job。 |
| Persistence | 升級既有 intraday stock state；additive migration、upsert、legacy quarantine。 |
| Failure | pending、partial、missing、stale、provider failure 與 unknown 必須可見。 |
| Transaction | persistence service／scheduler 擁有 commit/rollback；parser 與 router 不持有 transaction。 |
| Public API | 保留既有 path/method；欄位 additive，GET 維持 cache-read-only。 |
| AI contract | 沿用 `market.breadth` 與 `omi.decision.v4`；availability 限制必須限制 confidence。 |
| Consumer | Frontend、MCP、Radar 只使用 backend canonical contract。 |

## 交付項目

- 可重放的盤前、第一筆正式成交、session cache、跨日與 reset regression tests。
- 正式成交／試撮／reference／unavailable 價格語義與時間 provenance。
- `taiwan_intraday_stock_state` additive v2 migration、model 與 persistence contract。
- 正式 breadth 的 pending／regular／post-close 狀態與可選試撮摘要。
- REST schema、source health、AI answer、MCP、Frontend 與 Radar 收斂。
- Targeted、migration、backend/frontend regression 與正式 runtime smoke 證據。
- 隔日盤前／開盤實測 checklist。

## 完成定義

- `pz`、previous close、無正式成交的 `o/h/l` 不再進入正式市場廣度。
- 同交易日正式成交 cache 可安全沿用，且 `price_as_of` 不會漂移。
- 盤前正式 breadth 為 pending，正式成交後 coverage 才逐步建立。
- 所有 downstream consumer 使用同一份 v2 canonical state 或明確拒絕 legacy state。
- REST／AI／MCP／Frontend 對 status、scope、coverage、unknown、session 與
  decision usability 一致。
- Radar 不使用 pending、auction-indicative、legacy/untrusted breadth。
- Migration copy dry-run、integrity、targeted/backend/frontend regression 通過。
- 正式本機 runtime 證明 process/path/port/build/schema 與 source checkout 一致。
- 隔日實測前沒有已知 P0/P1 correctness 缺口；尚未取得的真實開盤數據明確列為
  M10 後的 scheduled live acceptance，不冒充已驗證。

## 開放問題與預設假設

- 既有 registered-universe 定義維持不變；若實盤顯示 universe 本身錯誤，另開
  bounded decision，不在 parser 修復中偷偷更改。
- 試撮 breadth 若無足夠可靠資料，只揭露 availability/coverage，不輸出正式
  limit counts 或 decision-usable stance。
- 舊 DB row 不推測回填 `actual_trade`；預設標記 legacy/untrusted 並由 reader
  排除。若需要歷史重建，另開獨立 backfill 任務。
- 下一交易日上午的 provider 真實 session evidence 由使用者接續驗收；本輪以
  deterministic fixtures、隔離 runtime 與正式 runtime non-trading smoke 完成 M10。
