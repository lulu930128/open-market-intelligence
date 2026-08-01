# 台股盤中資料契約根治與能力收斂進度

## 狀態

- 目前階段：M0～M9 已完成；M10 的 source、migration、正式 backend/frontend、
  HTTP API、repo MCP 與 source-health rollout 已完成。
- 最後更新：2026-07-30 20:05（Asia/Taipei）。
- 工作目錄：`C:\project\Open Market Intelligence`。
- 分支：`codex/taiwan-data-surface-v1`。
- 正式 backend：`http://127.0.0.1:8400`。
- 正式 frontend：`http://127.0.0.1:3179`；`3000` 位於 Windows excluded
  range，因此由 launcher 選擇替代 port。
- 正式 DB revision：`20260730_0045`。
- 本輪未 commit、未 push。

## 里程碑狀態

| 里程碑 | 狀態 | 結果 |
| --- | --- | --- |
| M0 | 完成 | CASE-01～CASE-10 已建立可重放 acceptance tests。 |
| M1 | 完成 | 共用 current-price、session-date relation、effective source-health primitive 已建立。 |
| M2 | 完成 | 台股 stock context、technical、decision、finalizer 使用同一 resolved current price。 |
| M3 | 完成 | temporal freshness、policy compliance、facts/research usability 與 execution grade 已分離。 |
| M4 | 完成 | 零價位保留 raw observation，但不再進入 best bid/ask；health 分層完成。 |
| M5 | 完成 | Market-minute field-level partial persistence 與 additive migration 完成。 |
| M6 | 完成 | TWSE/TPEX breadth、成交值語意與 synthetic index minute contract 完成。 |
| M7 | 完成 | Scheduler-owned、cache-only intraday stock state 與 screening capability 完成。 |
| M8 | 完成 | Provenance-aware hot groups 與 Watchlist 名稱解析完成。 |
| M9 | 完成 | Backend、frontend、repo MCP、OperatingModel 與 generated schema 已收斂。 |
| M10 | 部分待實盤 | 正式 backend/frontend/DB/repo MCP 已 rollout；下一交易時段與 standalone live MCP reload 待補。 |

## 已完成實作

### Canonical price、時間與品質

- 新增 `backend/app/ai/taiwan_intraday_contract.py`：
  - `resolve_taiwan_current_price`
  - `classify_taiwan_session_date_relation`
  - `resolve_effective_source_health`
- Current price 優先使用 current-session trade 或 eligible intraday close；
  midpoint 只能是明確 estimate，previous close 只作 reference。
- Technical levels、PnL basis、decision engine、ask finalizer 與 outward evidence
  共用同一 resolved price。
- 今日 quote 搭配前一 completed daily 會標為正常
  `expected_current_session_vs_completed_daily`，不再誤判為一般日期衝突。
- Explicit `require_live` 仍維持嚴格；不符合 live policy 時，既有 facts 可保留，
  但 `execution_grade_usable=false`。
- `evidence.capability_status` 保持 consumer-facing readiness 的 canonical
  authority。

### Quote depth 與 source health

- Raw 零價位仍保留於 observation，但 `price <= 0` 不再成為 best bid/ask，
  也不參與 limit-book imbalance。
- 未取得 provider 明確語意前，不把零價位推論成市價委託或漲跌停。
- Source health 現在可區分 request-local、persisted 與 effective 狀態。
- 新增 scheduler-owned Taiwan source-health sync；GET/read path 不負責全市場
  寫入或昂貴 refresh。
- 正式重啟後，Taiwan source-health 已由舊 snapshot 更新到
  `2026-07-30 11:55:24 UTC`，共 191 筆 Taiwan rows。

### Market-minute persistence 與 migration

- `taiwan_market_minute_state` 新增：
  - `quote_quality_status`
  - `trade_value_quality_status`
  - `trade_value_semantics`
  - `trade_value_confidence`
  - `trade_value_is_estimate`
- Breadth、quote/index 與 trade value 可以獨立保存；缺一欄時整份資料不再被
  丟棄。
- 新增：
  - `taiwan_index_minute_snapshot`
  - `taiwan_intraday_stock_state`
- Migration：
  - `backend/alembic/versions/20260730_0044_tw_intraday_market_state.py`
  - 正式 migration chain 同時包含並行任務既有的
    `20260730_0045_tw_financial_semantic_storage.py`。
- Migration 保持 additive；未刪除、重建或覆蓋正式 DB。

### TWSE/TPEX market surface

- `twse_mis.fetch_stock_messages` 支援 `tse` 與 `otc` channel。
- TWSE/TPEX breadth 以 registered stock universe 為分母，回傳 target、
  observed、excluded、unknown、duplicate 與 instrument policy。
- Combined breadth 缺一市場時只能是 partial。
- Coverage overflow 不再用 ratio clamp 隱藏。
- Trade value 明確揭露 official/estimated、semantics、confidence 與來源時間。
- TPEX 沒有經證明的官方 1m OHLC 時，使用 snapshot-derived synthetic minute：
  - `source_interval=snapshot`
  - `synthetic=true`
  - `indicator_eligible=false`
  - 保留 point count 與 partial/finalized 語意

### Screening、熱門群組與 Watchlist

- 新增 scheduler-owned rolling `taiwan_intraday_stock_state`。
- 新增 canonical capabilities：
  - `screening.intraday`
  - `market.hot_groups`
- Screening read path 是 cache-only，不在 AI request 中做全市場 provider
  refresh。
- Hot group membership 只來自：
  - `stock_master.industry`
  - `watchlist_group + watchlist_item`
- Outward contract 固定 `inferred_by_llm=false`。
- Watchlist 支援 numeric ID、exact normalized name、`default` alias 與
  ambiguous candidates。
- 正式 API 已以 `target.id=ETF` 解析成
  `tw_watchlist id=16, label=ETF`。

### Consumer 與公開契約

- Capability registry 現為：
  - 22 targets
  - 55 capabilities
  - digest
    `5f3335200e38c83ead9808c8e159333003f2267a5ea3e39bc9301abf9158f2bf`
- Repo MCP snapshot 與 `agents/omi_mcp_server/server.py` 已加入新 capability。
- Frontend `OmiAskDock` 優先呈現 backend-owned
  `evidence.capability_status`；legacy slots 僅作相容 fallback。
- zh-TW、en-US、ja-JP 已加入新 capability labels。
- `docs/product/OperatingModel.md` 已改成以 `answer`、`evidence.data`、
  `evidence.capability_status` 為 canonical contract。
- Standalone `C:\GPT_MCPtool\OMI_search\public_contract_snapshot.json`
  已同步到相同 digest；舊 snapshot 備份位於
  `.tmp/contract-backups/OMI_search-public-contract-snapshot-pre-tw-intraday.json`。

## 測試與驗證證據

### Targeted 與 regression

- CASE-01～CASE-10 acceptance tests：通過。
- Taiwan intraday capability focused tests：`9 passed`。
- Contract/MCP/migration focused batch：`34 passed`。
- 修正 full regression 揭露的五項問題後，focused recheck：`14 passed`。
- 正式 backend safe validation：
  - 命令：`.\scripts\run-safe-validation.ps1 -Profile backend`
  - log：`.tmp/validation/20260730-193446`
  - compileall：通過
  - pytest：`1296 passed in 123.57s`
  - `git diff --check`：通過
- Frontend：
  - `npm run lint`：通過
  - `npm exec tsc -- --noEmit --incremental false`：通過
- Standalone OMI_search：
  - `python -m unittest tests.test_server`
  - `27 tests`：通過

### 正式 DB 安全證據

- 正式 DB：
  - `data/open_market_intelligence.db`
  - pre-migration size：`12,688,158,720` bytes
  - pre-migration revision：`20260729_0043`
- 停止 OMI process tree 後執行：
  - `PRAGMA wal_checkpoint(TRUNCATE)` → `0|0|0`
  - 完整靜態備份與原 DB 尺寸一致
- Pre-migration backup：
  - `.tmp/db-backups/open-market-intelligence-pre-tw-intraday-20260730.db`
- Migration dry-run copy：
  - `.tmp/db-backups/open-market-intelligence-migration-dry-run-20260730.db`
  - `0043 → 0044 → 0045` 成功
  - 六張預期新表存在
  - `PRAGMA quick_check` → `ok`
- 正式 launcher 啟動後：
  - backend log 顯示正式 DB 依序執行 `0044`、`0045`
  - 正式 `alembic_version=20260730_0045`
  - `taiwan_index_minute_snapshot` 與 `taiwan_intraday_stock_state` 已存在

### 正式 runtime 與 outward proof

- Launcher log：
  - `repo_root=C:\project\Open Market Intelligence`
  - backend selected `http://127.0.0.1:8400`
  - frontend selected `http://127.0.0.1:3179`
  - `Status changed: API OK; UI OK`
- Backend listener：
  - PID `58220`
  - command 使用
    `C:\project\Open Market Intelligence\.venv\Scripts\python.exe`
  - `uvicorn app.main:app --host 127.0.0.1 --port 8400`
- Frontend listener：
  - PID `48188`
  - Node path `C:\Program Files\nodejs\node.exe`
  - Next server 來自本 repo `frontend\node_modules\next`
- `/api/system/health`：`status=ok`，project root、backend dir、
  Python executable 正確。
- `/api/system/readyz`：runtime/database 均 `ok`。
- Frontend `/omi-ui-health`：HTTP 200。
- Frontend `/omi-data/system/health` proxy：回傳正確 backend health。
- Live `/api/ai/tools`：
  - digest 為 `5f333...`
  - 22 target records
  - 55 capability records
  - 含 `screening.intraday`、`market.hot_groups`
- Live `/api/ai/ask`：
  - 2303：回傳 `omi.decision.v4`，收盤後 quote facts 可用，但
    `execution_grade_usable=false`。
  - Taiwan market：新 capability 可選取；因新 rolling table 是收盤後建立，
    `screening.intraday` 與 `market.hot_groups` 正確回
    `freshness_status=missing`、`facts_usable=false`，沒有假裝成今日盤中資料。
  - ETF Watchlist 名稱解析成功。
- Repo MCP stdio：
  - `initialize`：成功
  - `tools/list`：含新 capabilities 與 `5f333...` digest
  - `tools/call omi.ask`：成功、`isError=false`
  - canonical result 保留 missing/partial 狀態

## 已知限制與待完成驗收

### 下一個台股交易時段

- 正式新表目前 row count 均為 0，原因是 migration 在 2026-07-30 收盤後部署。
- 下一交易時段需補：
  - TWSE/TPEX 實際 full-market batch 數量、duration、provider calls、failure
    count 與 DB writes。
  - `taiwan_intraday_stock_state` rolling samples 與 5/15m metrics。
  - `screening.intraday` current-session ranking。
  - `market.hot_groups` group coverage、median、dispersion 與 leader
    concentration。
  - TPEX synthetic minute point count、event time、partial/finalized。
  - 2303、8299 live current-price resolver 與 delayed/live policy。
- 未取得這些 session evidence 前，不把 fixture 或收盤後 cache smoke 冒充
  live proof。

### Standalone OMI_search live reload

- `C:\GPT_MCPtool\OMI_search\public_contract_snapshot.json` 已更新且 27 tests
  通過。
- 目前 `127.0.0.1:8797` 的既有 process 尚未重載，因此 live `tools/list`
  仍回舊 digest `8ad8...`，但 `tools/call` 已轉送新 backend 並回 canonical
  `omi.decision.v4`。
- 完整 tray `-AutoStartTunnel -ReplaceExisting` 重啟會重新建立外部 tunnel；
  安全審查要求使用者明確授權後才能執行。
- 不直接以缺少 tray-injected token/security context 的手動 Python process
  取代 server，避免把 tunnel 後端變成錯誤的未授權狀態。

### Worktree 與 rollout scope

- Worktree 同時包含 Radar v2、US corporate events、Taiwan financial semantics
  等並行修改。
- 本輪沒有回復或覆寫這些修改；正式 rollout 前完整 backend regression 已
  全綠。
- 正式 migration head 包含並行任務的 `0045`；已在完整 DB 副本驗證後才部署。
- 未 commit、未 push、未公開發布 source。

## 下一步

1. 取得使用者明確授權後，使用 OMI_search 正式 tray 流程重啟 MCP server
   與既有 tunnel，重跑 session-preserving MCP smoke，確認 live digest
   `5f333...`。
2. 下一個台股交易時段執行 bounded live acceptance，補齊 M10 盤中證據。
3. 盤後再次驗證 finalized/session-close 語意，確認不把 previous-session
   ranking、daily close 或 synthetic minute 誤標成 live。

## 2026-07-30 補強：試撮參考價量與隔日驗收

### 已確認根因

- TWSE 官方交易制度與 MIS「最佳五檔」頁面在 08:30–09:00、13:25–13:30
  會揭露模擬成交價、模擬成交張數與最佳五檔申報價量。
- MIS JSON 的試撮契約為：
  - `ts`：是否為試算狀態；`0` 時官方頁面不顯示試算價量。
  - `pz`：試算參考成交價。
  - `ps`：試算參考成交量，單位為交易單位／張。
- 原 OMI 只解析 `z`、`tv`、`v`，並固定宣告試撮價量
  `not_provided`；因此上游有資料，但 OMI public contract 與 UI 都沒有接出。
- `tv` 是最近一次實際撮合量，不能在開盤前冒充 `ps`；`v` 是正規盤累計，
  也不能取代試撮參考量。

### 已完成修正

- `quote_depth.py` 依 `ts` gate 解析 `pz`、`ps`，投影到
  `indicative_match_price`、`indicative_match_volume_lots` 與來源欄位。
- 開盤前 `last_trade_volume_lots`、`cumulative_volume_lots` 對外遮蔽，
  避免前一交易日或 provider 保留值被誤標成當日實際成交。
- `QuoteDepthPanel` 新增「開盤試撮／收盤試撮」區塊，將試算參考價量和
  未成交五檔委託張數、實際成交量分開；開盤前不再顯示「最近一筆」
  成交量摘要。
- AI compact quote 與 `components.auction` 保留試撮參考價量，模型可辨識
  `indicative_match`，不把它當成 actual trade。

### 2026-07-31 交易時段驗收

1. 08:30–09:00 選一檔上市股與一檔上櫃股，確認：
   - `session_phase=preopen_auction`
   - `ts != 0` 時 `indicative_match_available=true`
   - UI 顯示 `pz` 試算參考價與 `ps` 試算參考量
   - UI 不顯示 `tv` 為「最近一筆」，不顯示 `v` 為當日累計成交
   - 上下五檔張數仍顯示，且明示為未成交委託量
2. 09:00 第一筆正式撮合後確認：
   - `session_phase=regular_live`
   - `tv` 才成為最近一筆實際撮合量
   - `v` 成為當日正規盤累計量
   - 試撮摘要消失
3. 13:25–13:30 確認收盤試撮：
   - `pz`、`ps` 顯示為收盤試算參考價量
   - `tv`、`v` 保留為試撮前已完成的實際成交契約
   - 不把 `pz` 冒充已確認收盤價
4. 13:30 後確認 `ts=0` 時不沿用快照內殘留的 `pz`、`ps`。

### 補強驗證

- Taiwan quote-depth 與 US dated-close focused：`26 passed, 10 subtests passed`。
- AI/public quote、volume、calendar regression：`48 passed, 6 subtests passed`。
- AI market-context projection：`24 passed`。
- Frontend ESLint：通過。
- Frontend TypeScript `--noEmit --incremental false`：通過。
- Python 無落地 compile：5 個異動檔通過。
- `git diff --check`：通過；只有既有 LF/CRLF 提示。

### 正式 runtime 與畫面 smoke

- 2026-07-30 22:38 由正式隱藏式 launcher 重新啟動：
  - launcher PID `33712`
  - backend listener PID `46440`
  - backend 啟動時間 `2026-07-30T22:39:02+08:00`
  - launcher log 明確記錄 `reason=backend source changed`
  - `8400 /api/system/health` 與 `3179 /omi-ui-health` 均為 `status=ok`
- 實際 `2330 /api/market/quote-depth/2330?refresh=true`：
  - `session_phase=post_close_snapshot`
  - `last_trade_volume_lots=5494`
  - `cumulative_volume_lots=44328`
  - `auction_indicative_available=false`
  - `indicative_match_available=false`
  - `quote_semantics=official_close`
- `quote_depth_preview=preopen` browser DOM smoke：
  - 「開盤試撮摘要」唯一出現
  - `試算參考價 pz` 與 `試算參考量 ps` 均顯示
  - 「最近一筆」與「正規盤累計」均未出現在試撮預覽
  - 畫面明示試算價量不是實際成交、上下五檔是未成交委託量
