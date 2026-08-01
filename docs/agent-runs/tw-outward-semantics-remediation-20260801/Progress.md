# 進度紀錄

## 目前狀態

- 專案狀態：進行中；本輪縮小範圍的 backend-owned 對外語意修正、P0/P1
  invariant 與 Radar v2 public contract 接線已完成，等待正式 runtime reload 複驗。
- 已完成里程碑：0 至 9。
- 里程碑 6：backend API、MCP 與正式 launcher runtime 已驗證；Frontend 實際
  顯示驗收待下一階段。Kuro 已由使用者移出本輪範圍。
- 里程碑 10：regression、MCP contract、frontend typecheck/lint 已完成；正式
  launcher 的最後一筆 source reload 待手動執行 `Restart Services`。
- Branch：`codex/taiwan-data-surface-v1`
- 發布邊界：不 commit、不 push。

## 第一階段已完成

### Session、指數與即時性

- index projection 僅使用所選交易日的 intraday points；current session 不再混入 previous session 的 OHLC、成交值或 official close。
- current/previous session 以 additive 欄位分離，並提供 `session_reconciliation_status` 與 source trade date。
- composite index realtime 在 root 提供 requested/returned/live/current counts、coverage、session phase、event time 與 freshness，不再因 root 缺 metadata 把全數 live children 誤判為 stale。

### 市場廣度、樣本排行與群族

- breadth 明確區分 `universe_count`、`coverage_count`、`classified_count` 與 `unknown_count`；overflow／不一致不再被 clamp 隱藏。
- TWSE/TPEX universe definition 對應實際市場，combined breadth 可對帳。
- 新增 dedicated `market.sample_ranking` projection，明示 `scope=omi_local_daily_sample`、`is_full_market=false`、TWD 與 shares 單位，避免冒充全市場排行。
- 建立 market-owned `tw.market.group_snapshot.v1`，單次全市場讀取後共用 snapshot ID、event time、coverage 與 membership provenance。
- 群族／產業統一提供 mean、median、dispersion、leader concentration 與估算成交值語意；watchlist group 與 exchange industry 不再各自重算不同資料面。

### Fill resolution 與 source lineage

- 每個 selected non-ready capability 都會被分類為 executable、deferred、unfillable 或 already-attempted，不再遺漏成未解釋狀態。
- reconciliation 補上 primary reader、final payload、quality、resolution type 與 unresolved reason。
- scheduler/schema/history 等無直接 refresh tool 的能力會產生明確 no-op／deferred resolution，不會把「呼叫成功但沒有新資料」誤當補齊成功。
- public source refs 補上 owner 與 lineage hints；bounded refresh、trust policy 與 read-path 邊界保持不變。

### 量能、事件、screening 與技術語意

- same-time 5d/20d baseline 提供 `ready`／`warming_up`、required/available/remaining sample days、expected sessions、next fill、authority 與 backfill 狀態。
- 樣本不足時不輸出偽精確 pace ratio；成交值 coverage 與 authority 分開，estimated／mixed 不再標成 official。
- corporate event history 先依 descending 排序再套 limit，並回傳 `total_count`、`returned_count`、`limit`、`offset`、`sort_order`。
- intraday screening 升級為 `tw.screening.intraday.v2`：provider switch 時維持同 session high/low 單調 invariant、canonical stock 去重、5m/15m reference 可追溯、估算成交值與 snapshot metadata 明示。
- 技術分析將 `today_state`、`historical_structure`、`composite_state` 分離；盤中證據不足時明示 fallback，而非把歷史結構寫成「今天」。
- technical levels 明示 `technical_price_basis` 與 `bid_ask_price_used=false`。
- canonical 停損欄位改為 `short_term_stop`，保留 additive `short_stop` deprecated alias。
- depth-only quote 仍維持 `price_available=false`，不把 best ask 當 last trade；既有 acceptance regression 持續覆蓋。

### 公開 contract 與 runtime

- 重新產生 `agents/omi_mcp_server/public_contract_snapshot.json`：22 target types、55 capabilities、digest `1c0914ee6a9d4b805b67bb597b315ba5260f164b94822a8c4d81d4b70f13a329`。
- internal tool catalog golden hash 已依確認過的 additive schema 變更更新，工具名稱鎖定仍保留。
- 2026-08-01 13:08 由正式 `omi-launcher.ps1` 偵測 backend source 過舊，停止舊 listener PID 52480 並載入新 backend；正式 listener 為 backend PID 6400、frontend PID 9532，launcher 記錄 `API OK; UI OK`。
- live `/api/ai/ask` 回傳 `omi.decision.v4` 且 projection budget satisfied；實際資料顯示：
  - breadth 為 full market，`universe_count=coverage_count=1948`、balanced、official complete。
  - volume 5d baseline ready（5/5），20d baseline warming up（7/20），authority official。
  - sample ranking 明示 local sample、非 full market。
  - group snapshot 84 groups、registered-universe coverage、trade value estimate、membership 非 LLM 推測。
- 真實 stdio MCP 已完成 `initialize -> tools/list -> omi.ask`：protocol `2025-06-18`、公開工具僅 `omi.ask`／`omi.ask_stream`、`isError=false`，量能 warming/authority 語意與 HTTP 一致。

## 驗證證據

- 跨 market/projection/capability/events/technical/MCP regression：`368 passed, 32 subtests passed`。
- outward/public v4/tool-boundary/quote/screening regression：`78 passed, 46 subtests passed`。
- safe validation wrapper：`148 passed`，並通過 backend compileall；log 在 `.tmp/validation/20260801-131347/`。
- scoped `git diff --check`：通過。
- direct pytest 僅出現 `.pytest_cache` 權限 warning；safe wrapper 使用 `-p no:cacheprovider` 後無此 warning。

## 第二階段：2026-08-01 驗收修正與 Radar v2 接線

### Planner、target 與 projection P0

- explicit capability selection 維持最高優先級，不再被同句 NLP negation 移除，並避免
  explicit locked selection 自動混入未指定 optional capabilities。
- 日期遮罩先於股票代號解析，涵蓋 ISO／斜線／點號日期、中文年月日與 `YYYYQn`，
  不再把日期中的數字誤認為股票代號。
- required Top-N 以 selection limit／pagination cardinality 驗證，compact projection
  不再只保留前三筆卻宣稱完整。
- regulation 問句進入 bounded evidence-only planner；diagnostic capability inventory
  不再因問句中的市場名詞污染成不相容 capability selection。

### P1 數值、availability、freshness 與 index

- 「正式收盤」使用 `quote_only` planner 並明示 `quote.official_close`，不自動載入
  daily chart／technical/general payload。
- public quality、slot 與 freshness aggregate 只由 required capabilities 決定；optional
  stale/missing 改列 `supplemental_context_quality`，不降低本次選取問題的 trust。
- capability status 公開 `trade_date`、`event_time`、`release_at`、`fetched_at`、
  `computed_at`、`served_at`；`is_current` 明示為 selected required capability 語意。
- 融資融券保留原始 `lots`，並提供 `normalized_quantities`（shares）與 `lot_size=1000`；
  法人買賣超維持 shares，consumer 不需猜單位。
- quote 僅在 `last_trade_available=true` 時輸出 `last_trade_price`。
- TAIEX/TPEX intraday 具有 bar contract；13:30 無量點為 official close marker，13:30
  後 snapshot 為 `post_close_summary`／`post_close_confirmation` 且不納入技術指標。
- 台股指數 daily OHLCV 接入 `daily.ohlcv`；cash index 的 `quote.auction` 明示
  `not_applicable`，不偽造 order book。
- Frontend OMI Dock 改用 canonical `freshness_status`，保留舊 `temporal_status` fallback，
  pending release 顯示 partial，不把 stale 誤標 blocked。

### Radar v2 public contract

- `watchlist.radar` 升級至 `omi.watchlist.radar.v2`，公開 active engine、cache/snapshot、
  universe、`radar_v2_summary.readiness` 與 data limitations；不納入基本面 factor。
- public capability registry 升至 v3；MCP offline snapshot 為 22 targets、55
  capabilities、digest `9d7e453c49c4c209c8247239738c2b00942f3c73ca12090370ee218d51ec7a82`。
- Radar payload 明示 `is_current` 時可作為缺少獨立 freshness row 的 bounded fallback，
  避免 Radar v2 本身 current 卻被 aggregate `data.freshness` 誤判 blocked。
- Freshness resolution 的優先序固定為 capability → domain → payload 明示狀態 →
  generic slot；不再把 Radar validation slot 的 partial 誤當成時間 freshness。

### 本階段驗證

- backend targeted regression：`287 passed, 86 subtests passed`。
- 最新 Radar freshness 優先序修正後 regression：`186 passed, 50 subtests passed`；
  使用實際本機 DB 直接呼叫最新 source 為 quality ready、trust high、freshness current。
- frontend：`eslint src/components/OmiAskDock.tsx` 與
  `tsc --noEmit --incremental false` 通過。
- backend compileall 與 scoped `git diff --check` 通過；pytest 僅有既有
  `.pytest_cache` 權限 warning。
- 正式 launcher 8400/3000 health 與 UI health 正常；live 正式收盤問句只選
  quote capabilities，quality ready。
- 17:16 正式 launcher 已由 PID 56016 啟動；launcher 比對 source timestamp 後停止舊 backend
  port owner，並於 17:16:43 回報 `API OK; UI OK`。這證明驗證的是新 source，不只是 health 200。
- live `omi.decision.v4` Radar 回傳 active `radar_v2.0`、完整 universe 15 檔、
  operational active、validation unverified、aggregate freshness current、quality ready、
  trust high，且 `blocked_required_capabilities=[]`。walk-forward/backtest 尚未驗證的限制仍公開保留。

## 下一階段

- 基本面／EPS／TTM／PE 與 Radar fundamental factor 維持 deferred；等基礎契約更完整
  後另開一批對照接線。
- Frontend OMI dock：以實際 UI 驗證 `warming_up`、sample scope、coverage/authority、today vs historical 與 deprecated alias 不會被隱藏或誤標。
- 觀察 20 日同時點基線隨交易日累積；確認 20/20 後由 `warming_up` 自動轉為 `ready`，且不需人工補 DB。
- 將施工地圖剩餘 P1/P2 項目轉成獨立小批次，避免與目前大量在途 worktree 互相覆蓋。

## 決策紀錄

- 2026-08-01：先修錯誤數值外流，再建立群族共用 snapshot 與 fill/volume 契約。
- 2026-08-01：保持 `omi.decision.v4` additive compatibility；Frontend/MCP/Kuro 只消費 backend contract。
- 2026-08-01：不做 DB rebuild、不觸發外部大量 refresh、不搬移大型模組。
- 2026-08-01：正式 runtime 驗證必須比較 source timestamp 與 backend start time；health 200 本身不是新程式已載入的證據。
- 2026-08-01：使用者確認本輪不處理 Kuro，也不把基本面接入 Radar；Radar
  範圍只包含既有 active v2 的公開輸出接線與一致性驗證。

## 已知風險

- worktree 仍包含其他大型未提交工作；本階段沒有 commit、push，也沒有清理或回退他人變更。
- live `market.sample_ranking` 目前 canonical freshness row 缺失，因此 quality 正確顯示 missing；這是資料／freshness 後續項，不應用 UI 隱藏。
- 20d baseline 目前只有 7 個 session，`warming_up` 是預期狀態，不是測試失敗。
- Frontend/Kuro 的實際視覺與文字呈現尚未完成本階段驗收，不能把 backend/MCP 通過等同於所有 consumer UI 已驗證。
