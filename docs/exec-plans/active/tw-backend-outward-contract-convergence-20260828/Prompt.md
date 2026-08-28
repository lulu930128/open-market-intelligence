# 台股 Backend Outward Contract 收斂

## 文件狀態

- 計畫狀態：`planning_awaiting_user_approval`
- 規劃日期：`2026-08-28 Asia/Taipei`
- 執行範圍：`TW only`
- 排除市場：`US / JP / KR`
- Repo：`C:\project\Open Market Intelligence`
- 基準 branch：`codex/tw-etf-provider-normalization`
- 基準 HEAD：`ba1682e5e4545ba5df146c98fad6d738aa2b352e`
- 前置任務：
  - `docs/agent-runs/tw-market-data-platform-convergence-20260825/`
  - `docs/exec-plans/active/tw-final-eod-technical-cleanup-20260827/`
- 本計畫是前述 Data Core 與 EOD lifecycle 的 corrective convergence，不重建第二套平台，也不改寫前置任務的歷史證據。

## 目標

- 將台股 Backend Data Core 的 completed daily、quality、technical、current-session acquisition 與 outward projection 收斂成單一可驗證 truth。
- 阻止 storage 中尚未 release-qualified 的當日日線被 chart、freshness、technical、sector、ranking、AI、MCP 或其他 consumer 當成 finalized official daily。
- 讓 sequence coverage、交易日 continuity、technical sufficiency、measurement unit lineage 與 decision usability 成為 canonical quality 的正式輸入，而不是由「payload 有值」推定完成。
- 補齊台股 intraday bars 的正常 acquisition owner，並讓 stale／delayed current-session evidence 無法維持即時 decision usability。
- 讓 Backend direct API、`omi.decision.v4`、repo MCP、Frontend dashboard 與未來 Kuro consumer 對同一 canonical evidence 投影相同狀態。
- 完成所有 P0／P1 release gate，並對 P2／P3 建立明確修復、compatibility 或關閉結論後，才可宣告台股 Backend outward contract 可封版。

## 非目標

- 不處理 US、JP、KR 市場能力、provider、資料修復或 consumer。
- 不重做 Shared Market Data Foundation、Gateway、Resolver、Dataset Registry、Control Plane 或 `omi.decision.v4`。
- 不新增平行 daily platform、freshness service、technical truth、index status owner 或 consumer-side fallback。
- 不把 `quote.session_close`、current partial bar 或 realtime quote 寫成 official daily OHLCV。
- 不把 `TAIWAN_DAILY_PRICE_RELEASE_TIME` 從 15:15 改成 13:30。
- 不讓 GET／read path fetch、refresh、repair、subscribe、enqueue 或寫入 DB。
- 不為了補齊 canonical history 重新啟用 frontend、MCP、AI 或 service-local legacy provider fallback。
- 不進行全市場無界 intraday subscription、無界 backfill、大量 quota 消耗或自主交易。
- 不在計畫核准前修改 production source、schema、runtime、scheduler 或資料。
- 計畫核准後的 source implementation 不自動包含 runtime restart、production DB migration、外部 refresh、commit、push 或 release；這些仍依各自 gate 取得授權。

## 硬性限制

### Ownership 與 dependency direction

```text
Provider / Integration
  -> Canonical Observation
  -> Transaction / Repository
  -> Gateway / Resolver / Dataset Lifecycle
  -> TW Market Policy
  -> Research / AI / API
  -> Frontend / MCP / Kuro
```

- Backend Data Core 是 release、freshness、coverage、finalization、lineage 與 decision usability 的唯一 truth owner。
- Provider adapter 只處理 bounded IO、raw parsing、provider error normalization 與 canonical conversion；不選 fallback、不 commit、不產生 AI decision。
- Daily completed consumer 只能讀同一個 released completed set，不可直接使用 raw `MAX(market_daily_price.trade_date)` 決定 outward trade date。
- `storage_latest_date` 與 `released_latest_date` 必須分開；row 存在不等於已 release-qualified。
- Release clock 到達不等於 release-qualified ingest 完成。當日 official daily 必須同時通過 calendar release gate、canonical lineage 與可證明的 release-qualified receipt／transaction gate。
- Market session、instrument status、freshness、release、item finalization、authority、coverage、reconciliation 與 usability 保持正交；不得用單一 status 隱式取代。
- 既有 `CapabilityStatus` 六軸模型優先 additive 強化，不新增第二套平行 quality model。
- Unknown 不等於 `0`；No Quote、No Trade、Suspended、Missing、Policy Unsatisfied 與 Not Applicable 不互相等價。

### Data 與 schema 安全

- `data/open_market_intelligence.db` 不得刪除、重建或覆蓋。
- 若既有 `raw_fetch_result.fetched_at`、source lineage 與 transaction evidence足以重建 release qualification，優先不改 schema。
- 只有 contract test 證明現有 lineage 無法穩定重建 release-qualified state，才提出 additive migration；migration 必須有 upgrade、downgrade／rollback 說明與 isolated DB 驗證。
- 所有寫入需有明確 transaction owner、idempotency key、bounded scope 與 postcondition。
- Full-market coverage 不足時保留 partial／sample-only；不得以 transport success 或少量 sample 假裝 full-market complete。

### Compatibility

- `omi.decision.v4` 維持唯一 public decision contract。
- Public field 變更優先 additive；既有 `bars` int/list 語意碰撞需先盤點 consumers，再以 schema metadata、compatibility namespace與 negative tests 漸進移除歧義。
- `breadth`、`resolved_breadth` 等 compatibility seam 必須有 canonical reference、deprecation 狀態、禁止 AI/MCP 掃描 legacy path 的測試與 removal gate。
- Backend registry 與 MCP selectable capability 必須維持 parity；已通過的 `quote.session_close` 不重複另建 capability。

### 工作樹與驗證

- 目前 worktree 有大量既有 TW／US／architecture 變更；實作時只改本計畫明列的 TW owner 與測試，不 reset、clean、revert 或覆寫其他工作。
- Source、Runtime、Live、Product acceptance 分開記錄；source tests 全綠不能取代 runtime adoption 或 live outward convergence。
- 任一 milestone 的 negative acceptance 失敗，先 stop-and-fix，不以 warning、legacy fallback 或 consumer 特判繼續下一階段。

## 已驗證背景

### P0 completed daily temporal leak

- 2026-08-28 14:59，3711 daily direct API 回傳：
  - `latest_data_date=2026-08-28`
  - `expected_data_date=2026-08-27`
  - `freshness_status=future`
  - `data_quality=ok`
  - `volume_semantics=finalized_traded_shares`
- 明確傳入 `to_date=2026-08-28` 時，caller 使 `expected_data_date` 也變成 2026-08-28，結果直接標 current。
- DB lineage 顯示該 row 的 `raw_result_id=113461`，`raw_fetched_at=2026-08-28 14:01:28 Asia/Taipei`，早於 15:15 release。
- 2026-08-28 15:15:27，同一筆 14:01 receipt 未重新 ingest，卻因 clock boundary 到達而變成 `current / ok / finalized_traded_shares`。
- 因此只做 `to_date <= expected_daily_price_date()` clamp 仍不足；必須另有 release-qualified receipt／transaction gate。

### Quality 與 technical

- 2330 request 20 daily bars、return 1，仍得到 daily quality `current / ready / decision_usable=true`，continuity 為 `not_applicable`。
- 同一筆 1-bar evidence 的 technical 仍輸出 `selected_score=+7`、`波段偏多`，technical quality 為 ready／decision usable。
- Current factor model跳過缺失 factor 後，依剩餘權重重新 normalize 到 `±7`；沒有 bar count、factor count、timeframe coverage 或 continuity sufficiency gate。
- Technical normalization保留裸 `volume` numeric，沒有完整繼承 `volume_unit` 與 source capability lineage。

### Market aggregate 與 outward divergence

- `market.sectors` 的 observed trade date被 raw latest row推到 2026-08-28，sample只有 `1/1973`。
- Current source已正確標示 `partial / sample_only / is_full_market=false / decision_usable=false`；本計畫保留該 gate，但修正其 completed trade-date owner。
- 同一個 13:30 index observation：Dashboard為 `stale / provisional / decision_usable=false`；AI `market.indices` 為 `ready / complete / decision_usable=true`，nested payload同時又是 `official_close_status=pending / finalization=provisional`。
- Dashboard仍同時保留 authoritative與legacy index／breadth sibling fields；目前 headline指向resolved，但 compatibility seam尚未完成隔離與removal gate。

### Current session

- Intraday screening live sample存在 stale／delayed rows仍 `decision_usable=true`。
- 3711 `tw.intraday.bars` 為 `persisted_miss`、`CACHE_ONLY_NO_ELIGIBLE_CANDIDATE`；Registry有owner與explicit refresh operation，但沒有正常 materialization scheduler。
- TAIEX／TPEX intraday endpoint均回502；exact traceback為 `backend/app/market/tw_current_market_platform.py:108` 使用未 import 的 `TAIWAN_TZ`。

### Planner、applicability 與 schema

- 3711 `data_only + explicit selection` 仍可因saved position context得到 `decision_required=true`。
- 一般 daily／technical explicit selection仍落到 `reader_profile=standard`，response會帶回未選的 cross-market、breadth、source-health noise。
- 0050 `fundamentals.revenue` 最終為 not applicable，但reader仍建立payload並帶出不相關的margin、broker、quote、breadth與US overnight health。
- `daily.ohlcv.bars` 在live payload是int count，實際序列固定在 `points`；其他projector又可能把`bars`視為list alias。
- `/api/ai/tools`與repo MCP schema目前都包含`quote.session_close`；targeted parity test通過，P2-01目前是adoption verification，不是預設source change。

## 交付物

- Release-qualified completed daily read policy與唯一 repository/platform seam。
- Storage state與released canonical state的typed projection與reason codes。
- Chart、freshness、market aggregate、technical與AI/MCP改用同一released completed set。
- Sequence coverage evaluator與TW trading-calendar-aware daily continuity gate。
- Existing canonical quality resolver的applicability、availability、freshness、release、coverage、usability輸入修正。
- Technical sufficiency gate、factor minimum、timeframe coverage與measurement lineage。
- Intraday state的session-aware age gate與bounded normal acquisition scheduler owner。
- Index／breadth canonical status convergence、legacy compatibility isolation與removal gate。
- Explicit selection execution dependency graph、data-only intent lock與early instrument applicability gate。
- Budget-aware source-health preview與daily bars schema去歧義。
- P0–P3 issue-to-milestone traceability、targeted regression、architecture guard、runtime/live/product acceptance evidence。
- 必要時同步更新 `docs/architecture/BackendArchitecture.md`、`MarketTemporalContract.md`、`OmiDecisionContract.md`、constraints/debt與`CurrentImplementationState.md`；只有真實 contract 或owner改變時才更新。

## 完成條件

### Source acceptance

- Pre-release storage中即使存在today row，所有completed daily consumer仍只看見上一個release-qualified trade date。
- 15:15 clock到達但沒有post-release qualified ingest時，today仍不得自動升格為released/current/finalized。
- Post-release official acquisition成功、transaction persist與repository reread後，today才可成為released completed daily。
- Daily request count、available count、returned count與continuity會正確決定coverage；20→19／1不可complete。
- Technical在不足bar、factor、timeframe或continuity時不輸出正式normalized score，`decision_usable=false`。
- Stale／delayed regular-session screening evidence不具即時decision usability。
- Normal intraday scheduler有明確bounded target scope、job ownership、idempotency、backoff、health與startup catch-up；read path保持cache-only。
- Index／breadth同timestamp跨Backend API、AI與Frontend projection的canonical status一致。
- Data-only explicit selection不被position context升級為decision，且只執行selected capabilities與hard dependencies。
- ETF not-applicable capability在reader dispatch前停止，不產生refresh action或無關source noise。
- MCP selectable capability與Backend public registry parity保持全綠。

### Runtime acceptance

- 只透過既有OMI launcher lifecycle採用source；驗證project root、interpreter、selected port、migration、loaded source與health/ready。
- Runtime API、Frontend proxy與MCP實際載入新contract；不能只以source tests宣告adopted。
- Scheduler若啟用，必須能證明owner PID/job、bounds、target scope、provider calls與DB writes符合計畫。

### Live acceptance

- 交易日15:15前與15:15後分別捕捉direct API、AI、MCP、Dashboard的相同evidence，驗證release lifecycle。
- 15:15後provider尚未refresh與已完成qualified refresh兩種狀態必須分開。
- Intraday current／delayed／stale與missing bar情境均有真實或可重現evidence。
- External provider failure、partial coverage與policy-unsatisfied狀態不被consumer升級。

### Product acceptance

- P0、P1 required rows全為passed。
- P2每一列都有passed、closed-as-currently-resolved或explicitly-deferred且不阻塞封版的理由；不可只留模糊warning。
- P3 compatibility與budget行為有明確contract、deprecation與negative test。
- Source、Runtime、Live、Product四層證據均完成後，才可更新台股Backend outward contract為product accepted。

## 待確認決策與預設方案

1. Release qualification storage：
   - 預設：先用existing `raw_fetch_result.fetched_at`、source lineage與transaction reread建立derived qualification。
   - Gate：若cold read無法穩定判定post-release qualification，才做最小additive migration，不新建平行daily table。
2. Intraday scheduler v1 target scope：
   - 預設：`watchlist + holdings + actively viewed/leased`的bounded union，具hard cap、per-run call budget、backoff與去重。
   - 排除：full-market 2,000檔常駐抓取；market movers只能在已有canonical candidate list時作optional tier。
3. Compatibility window：
   - 預設：`bars`、legacy breadth/index不做無預警breaking removal；先加canonical ref、deprecated metadata、consumer inventory與negative routing test，再依release window移出primary namespace。
4. 計畫核准的授權範圍：
   - 預設：使用者核准本計畫後，可開始source、tests與isolated migration驗證。
   - Runtime restart、production migration／scheduler enable、external refresh、commit、push、release仍需在對應milestone另行確認。
