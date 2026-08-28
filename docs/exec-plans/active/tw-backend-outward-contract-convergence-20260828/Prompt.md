# 台股 Backend Outward Contract 收斂

## 文件狀態

- 計畫狀態：`consumer_convergence_source_implemented_runtime_live_product_pending`
- 規劃日期：`2026-08-28 Asia/Taipei`
- 執行範圍：`TW only`
- 排除市場：`US / JP / KR`
- Repo：`C:\project\Open Market Intelligence`
- 基準 branch：`codex/tw-etf-provider-normalization`
- 基準 HEAD：`4936d4631bef18bb5ec26c1f50799e91a2a8b3be`
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
- 不新增另一套 MCP business contract、capability truth、freshness 判斷或 status resolver。平行 MCP 工作已結束，本次可修改 `agents/omi_mcp_server/**` 與其 lifecycle／registration，但只能修 transport、schema sync、runtime adoption 與 thin-adapter parity。
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

### 2026-08-28 closeout residual baseline

- Running Backend contract digest 已採用 `17a6096163d3ec52b9d483c02c04253facbf11ed08d2d65d71cb31cda4ea98d0`；舊版 runtime baseline 已過期，但 Source、Runtime、Live、Product gate仍分開記錄。
- 3711、2330 的 TWSE OpenAPI storage 已有長期 release-qualified history；outward 只回 2 根的主因是較高優先 RWD series 被當成整段 canonical series，並非單純 storage/backfill 缺口。
- 3711 technical insufficiency 已能把正式 `selected_score` 變成 null，但 primary outward payload仍洩漏 `selected_summary=+7`、偏多 `composite_state` 與 entry/risk levels。
- `technical.indicators` nested completed observations仍缺 measurement-level `volume_unit`，quality會回 `volume_unit_missing`。
- `market_chip_daily` 與 persisted intraday dataset目前已為 current；前者移出 open blocker，後者只保留 scheduler lifecycle／下一交易日 live acceptance。
- Quote scheduler目前為 active/empty，但 `required=false`、`canonical_scope=false`；需決定修復或正式退役，不將其直接冒充 required canonical product blocker。

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

### 2026-08-28 Backend Health Audit reopen baseline

- Fixed-slot quote scheduler 的 17 個 job 均有執行，但在 persistence 前因 `Decimal` 無法序列化而失敗；目前 failure path 也未留下 failed capture row，因此 health 只看見 `captured=0 / failed=0 / missing=17`。既有「scheduler active」證據不能視為 capture 成功。
- `quote.session_close` 因沒有可用 capture candidate 而 unavailable；同一 outward capability 可同時出現 payload `available=false`，但 quality 卻標 `availability_status=available / coverage=complete / release=released`，六軸 status 仍有矛盾。
- Intraday scheduler source owner 已存在且 Backend runtime 已採用較新 source，但目前 target scope 仍可能只涵蓋 configured symbols；2330 persisted intraday bar 與 27 檔 ETF watchlist current state 仍缺資料，table-wide health 不能證明 selected universe coverage。
- TAIEX／TPEX official daily value 已存在，但缺 `source_id/raw_result_id` lineage，canonical official reader拒絕；同時 13:30 provisional intraday point 仍可能被時間 heuristic 標成 official/finalized，且數值與正式 close 不同。
- Existing index capture rows保留先前 `TAIWAN_TZ` failure；source path修正與一次 direct endpoint成功不能回填已失敗的 capture，也不能取代下一次正式 capture acceptance。
- Full-market EOD約為`1944 current / 27 stale / 2 missing`（universe 1973），但目前缺逐 instrument eligibility、halt/suspension與reason分類；breadth unknown也缺完整per-symbol taxonomy。
- 27檔ETF watchlist目前均為`unknown/state_missing/unavailable`，不能由全表intraday current aggregate掩蓋。
- Source health仍可能把舊`target=all` quote snapshot視為active lifecycle；required operational count雖已分離，optional zombie row仍會污染較高層 freshness/readiness。
- Technical corporate-action evidence需要`checked_through_date`與absence證據；沒有事件row不等於已完整檢查。
- `source_health`的nested `missing_symbol_slots`在persisted JSON與direct builder正確，但經`omi.decision.v4` bounded projection後可變成null；此為Backend projection depth/budget bug，不是MCP adapter語意問題。
- Repo local stdio adapter實際只宣告`omi.ask`、`omi.ask_stream`、`omi.read_refresh_status`三個public tools，但目前Codex host仍顯示舊internal tool集合，呼叫`omi.ask`會得到`Unknown tool`。Local adapter readiness、OMI_search lifecycle與host session/schema adoption必須分層驗收。

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
- Quote fixed-slot capture的quantity-safe serialization、failed-capture persistence與`quote.session_close` reconciliation/status修復。
- Index official daily lineage transaction、provisional/official finalization去heuristic與跨surface canonical parity。
- Selected-universe intraday coverage、ETF/watchlist state與per-target health，而非table-wide row count代替coverage。
- Source-health scope generation／supersession、nested bounded projection完整性與corporate-action checked-through evidence。
- Repo MCP三工具public surface、Backend schema sync、OMI_search runtime與Codex host registration/adoption evidence。
- TW ETF／futures／options等typed lineage缺口的public-claim盤點；required/public能力要修復，否則明確partial/deferred且不得宣稱complete。
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
- Quote capture可序列化`Decimal`／typed quantity，單一symbol失敗有durable failed row且不阻斷其他symbol；下一交易日17個fixed slots有可稽核結果。
- `quote.session_close`沒有candidate時必須available/coverage/release/usability一致降級；有candidate時仍需通過official-close reconciliation才可升級。
- Official index缺lineage時不得被選為authoritative；13:30 provisional observation不得僅因時間到達而標official/finalized。
- Intraday health對selected target universe揭露eligible、selected、persisted、stale、missing與skipped reason；2330與代表ETF fixture不得被全表aggregate假裝covered。
- Nested source-health欄位經Backend bounded projection後保持值或帶明確truncation metadata，不得靜默變null。
- Repo MCP `tools/list`只暴露三個public tools，local stdio、OMI_search runtime與Codex host均可用相同`omi.ask`名稱呼叫，且canonical envelope與direct HTTP deep-equal（只排除transport metadata）。

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
   - 使用者已授權TW Backend consumer convergence source實作、tests與isolated migration驗證。
   - Runtime restart、production migration／scheduler enable、external refresh、commit、push、release仍需在對應milestone另行確認。

## 2026-08-28 Consumer convergence extension

### Goal

- 移除所有已辨識的Taiwan production consumer對`MarketDailyPrice`、`TaiwanStockQuoteSnapshot`、`MarketIndexDailyStat`與`MarketIntradayBar`的market-truth selection旁路。
- Daily、current-price與official-index consumer統一從既有Taiwan market-owned repository、`MarketDataGateway`與Resolver取得canonical evidence。
- Architecture Guard v2機械阻擋新增raw canonical-storage consumer與consumer-owned provider selection。

### Non-goals

- 不建立第二套Taiwan Resolver或provider-priority policy。
- 不做provider acquisition、production DB mutation、schema migration、scheduler enable、runtime restart、commit、push或release。
- 不把已登錄的`market_data/eod_coverage.py`遷移、dark control-plane retirement或`quote_depth.py`compatibility cleanup綁進本輪cutover。

### Additional done criteria

- `market.indices`的primary value/change/date/source欄位來自同一selected candidate。
- Explicit Taiwan trade-date與future requested/effective-date語意完整穿透daily與technical outward projection。
- Market overview以單次bounded batch candidate read保證每個instrument只有一個completed daily result，不做全市場N+1 Gateway read。
- Valuation、next-session、ADR、volume pace、Radar outcome、market chips、technical relative strength、derivatives與legacy public daily routes不再擁有provider selection。
- ETF `not_applicable`優先於semantic quality override；所有含daily trade value的canonical projection帶`TWD` unit metadata。
- Architecture guard能偵測protected-model direct access與consumer使用`SourceRegistry.priority`；只允許精確登錄且具closure gate的既有debt。

## 2026-08-29 Final cleanup extension

### Goal

- 讓 explicit Taiwan `trade_date` 成為 technical report、advanced evidence、benchmark與corporate-action analysis window的共同 observation cutoff。
- 讓sector與sample ranking從同一次canonical stock-only daily snapshot取得rows、universe denominator與by-market coverage，不再由AI層重查第二份universe。
- 讓`market.sample_ranking`在v4 quality中固定如實投影為`sample_only`，並同步Backend registry與repo MCP離線schema digest。

### Non-goals

- 不改provider acquisition、release calendar、production DB、scheduler或runtime lifecycle。
- 不把ETF從既有public `/api/market/daily` compatibility route移除；stock-only scope只適用於completed-session stock aggregate。
- 不在MCP adapter補coverage、cutoff或universe語意。

### Additional done criteria

- Historical request的daily／weekly／monthly technical observation、TAIEX benchmark與corporate-action `relevant_analysis_end`均不得晚於requested `trade_date`；不得組today/current-partial report。
- Canonical stock snapshot同時回傳selected rows、stock universe count與TWSE/TPEX counts；ETF row不進sector/ranking，coverage numerator與denominator同源。
- Sector `covered_stock_count`使用`covered_universe_count`；sample ranking canonical quality為`sample_only`且`decision_usable=false`。

## 2026-08-29 Precommit final polish extension

### Goal

- Explicit `daily.ohlcv` field selection包含`points`時，由Backend selection contract自動保留measurement companion metadata，避免projection後quality誤報`volume_unit_missing`。
- Sector sample coverage沿用canonical stock snapshot的`canonical_active_stock_universe` scope，warning明確描述ordinary active stocks，不再殘留`active_stock_master`舊語意。

### Non-goals

- 不在quality resolver硬編unit、不改成quality-before-projection，也不由MCP adapter補欄位。
- 不把daily legacy `bars` count當成points array；未指定fields的default selection維持不變。
- 不改compatibility missing keys、sample-only usability gate、provider、DB、scheduler或runtime lifecycle。

### Additional done criteria

- Requested fields順序保持不變，`volume_unit`、`trade_value_unit`、`currency`依固定順序只補一次；未知欄位仍拒絕。
- Effective selection、projected payload與manifest使用相同fields；points含volume/trade value時quality不再出現假性unit missing。
- Sector coverage scope固定來自canonical snapshot；partial warning明示`ordinary active stocks`，但status仍為partial/sample-only且decision unusable。
- Source seal完成後仍保留Runtime、Live、Product、commit、push與release為待授權gate。
