# 台股資料可靠性與自癒機制根除長專案

## Goal

- 根除台股市場指數、資料新鮮度、來源健康、排程補洞與 AI response budget 之間互相矛盾的真相來源，讓 direct API、AI `market.indices`、Frontend、MCP 與 Kuro 消費同一份 backend-owned canonical semantics。
- 將「服務可用」、「資料品質」、「決策可用性」與「provider 狀態」拆成可機器判讀且對外可見的 additive contract，不再用單一 health/status 掩蓋 stale、partial、missing 或錯誤日期。
- 讓台股交易日資料缺口能被正確偵測、限量修復、驗證結果並留下可稽核紀錄；job 只有在 required dataset 真正到達 expected trade date 時才能成功。
- 保持 OMI local-first、台股核心、backend 真相來源、thin consumer 與 bounded external IO 的產品邊界。

## Non-goals

- 不把 OMI 改成自動下單、猜漲跌或無條件追求「綠燈」的系統。
- 不用隱藏 stale、partial、missing、historical 或 provider failure 的方式讓 health 看似正常。
- 不讓 Frontend、MCP、Kuro 或 scheduler 各自重算市場日期、指數真值、freshness 或 readiness。
- 不在 GET/read path 隱性啟動 provider refresh、全市場 backfill、DB migration、LLM 或其他昂貴 side effect。
- 不做無界 retry、無界全市場抓取、付費／稀缺 quota 消耗或無來源紀錄的修補。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`；若未來確實需要 schema migration，必須另有明確 migration、備份與回滾說明。
- 不藉此專案進行無關重構、dependency upgrade、格式化或消化目前 133 筆既有 dirty worktree 變更。
- 未經使用者明確授權，不 commit、不 push、不建立 PR，也不重啟正式 launcher、backend、frontend 或 MCP runtime。

## Hard constraints

- Backend 是市場資料、交易日、provider/source health、freshness、AI evidence 與 outward readiness 的唯一真相來源；consumer 只呈現或轉送。
- 台股仍是核心市場；其他市場不因共用 status 欄位而被提升成同等核心，也不得被本次台股修補誤改。
- Public contract 採 additive/versioned 演進。既有 `omi.decision.v4`、`status`、`evidence.capability_status`、`problem_count`、route、query alias 與 MCP tool shape 不得被無聲重新定義。
- 每個 freshness 判斷必須能指出 dataset/resource、logical scope、target/universe、expected trade/session date、observed date/time、source/provider、collection mode、coverage 與 limitation。
- Canonical index resolution 必須分成 bounded candidate acquisition 與 pure resolution；`cache_only` 不得做 external IO，read path 不得暗中 refresh。
- 昨日正式收盤、過期 cache 或 TPEX 盤後 5 秒資料不得被包裝成今日 live observation；official close 與 current observation 必須分欄。
- Index resolution 的 exact selected output 必須可持久化及重放，並有 `resolution_id`、provenance、as-of/session、quality 與 fallback reason；不得讓 direct route、summary 與 AI 各自二次選源。
- Response budget 必須區分 caller explicit hard limit 與 payload default adaptive ceiling。不得用 `min(global_max, required_size + margin)` 讓 compact request 靜默膨脹到 1 MiB。
- Source health 必須區分 operational canonical generation 與 historical/provider-generation records。`target=all` 若仍是目前 canonical scope，即使過期也要保留為 operational problem，不能只因 expired 就降為 historical。
- Quote freshness 必須拆成 request-live、scheduler-contract、provider-availability 三軸。Scheduler `target=all` 只有在明確 universe、symbol digest 與 coverage 支撐時才成立。
- 排程成功必須依 expected trade date 的 required dataset postcondition 判定，不能只依 task 沒丟例外或 stale table 的 latest date 判定。
- 自癒 loop 必須 bounded、deduplicated、具 backoff/max-attempt、circuit/provider awareness、startup reconciliation 與 repair ledger；錯誤與放棄原因對 source health 可見。
- 所有日期判斷須 session/trading-calendar aware，處理休市、盤中、收盤後官方資料尚未發布與跨日邊界。
- 實作必須保留目前 branch `codex/tw-etf-provider-normalization` 上既有修改；先建立重疊檔案 baseline，再做 minimal、localized patch。
- 每個 milestone 失敗時先 stop-and-fix；source test 通過但 runtime outward behavior 未採用，不算完成。

## Context

- Repo：`C:\project\Open Market Intelligence`
- 原始工程書：`C:\Users\thoma\Downloads\OMI_台股資料可靠性與自癒機制根除工程書_20260814.txt`
- 建立日期：2026-08-14（Asia/Taipei）
- Integration base：branch `codex/tw-etf-provider-normalization`、HEAD `46c37b3eb031e05792f0706e7437e6d46079528d`
- Related systems：backend market services、AI decision envelope、source health、SQLite、scheduler/jobs、Frontend data status、MCP public contract、launcher/runtime。
- Product alignment：`docs/product/ProductVision.md`、`OperatingModel.md`、`QualityBar.md`、`Roadmap.md` 與 `docs/architecture/BackendArchitecture.md`。

### 已確認的根因證據

1. **Index truth 分裂**
   - `backend/app/market/indices.py` 的 direct intraday route 與 `_market_index_summary()` 走不同 provider/cache/fallback 路徑。
   - `backend/app/ai/market_context/taiwan_market.py` 的 `market.indices` 又混用 summary 與 persisted minute snapshot。
   - 結果是同一市場、同一時間可出現不同日期、不同價格與不同 provider lineage。

2. **Response budget 自我拒絕**
   - `backend/app/ai/capability_contract.py` 有 payload-level default limits，但 selection 沒有完整保留 caller explicitness provenance。
   - `backend/app/ai/decision_envelope_v4.py` 在組合 required core 後可能因預設 budget 拒絕自己；修復必須量 final serialized envelope，並保持 explicit limit 為 hard limit。

3. **Unified source health 被歷史殭屍污染**
   - `provider_health.py` 以 `(market, resource, target, provider)` upsert，但不會讓已退出 active generation 的舊 provider/target 自動退役。
   - `source_health_context.py` 目前 lifecycle 規則也可能把仍屬 canonical 的過期 `target=all` 誤降為 historical。
   - 2026-08-14 唯讀 DB 審查看到 201 筆 TW snapshot，含 current、available、stale、empty、partial、pending 與舊 target/provider generations。

4. **Quote snapshot freshness 的 collection mode／scope 不真實**
   - 無 stock id 的 quote source-health 可能從整張表任取 latest observation，卻標成 `target=all`。
   - Fixed-slot scheduler 實際只抓 configured／active-watchlist bounded universe（最多 20），不能代表全市場。

5. **Daily refresh 是 outcome false-success，不是完全沒有 scheduler**
   - `scheduler.py` 已有 startup catch-up，但計算出的 `expected_trade_date` 沒有完整傳入 worker。
   - `daily_metrics_backfill.py` 又從可能已 stale 的 `MarketDailyPrice` 推導 latest trade date。
   - 唯讀 job evidence 顯示四個 `scheduler.market_daily_refresh` 以 2026-08-13 為 target 並標 success，實際 result 卻只到 2026-08-12、`fetched_count=0`。

6. **Service、data 與 decision 狀態混用**
   - HTTP 可用、cache 有值或 job 未丟例外，不代表資料達到 expected date，也不代表 AI decision 可用。
   - 需要 additive 的 `service_status`、`data_quality`、`decision_readiness`、`provider_status`，並由 backend 統一映射。

### Runtime 與工作樹現況

- 規劃時 `git status --short` 有 133 筆既有變更；indices、AI contract、config、jobs、schemas、tests 與 MCP adapter 均可能有重疊。
- 2026-08-14 審查期間對 `127.0.0.1:8400` 的 probe 無法連線；最後 launcher log 只能證明先前曾選到 backend 8400/frontend 3000，不能當成目前採用證據。
- 本階段只有文件規劃，不修改 production source、不寫 DB、不 refresh provider、不重啟 runtime。

## Deliverables

- 一個 canonical Taiwan index resolver contract：candidate acquisition、pure resolution、selection policy、persistence、provenance、quality 與 cross-consumer projection。
- Response budget provenance 與 payload-level adaptive ceiling，含 default/explicit、final serialization measurement、continuation/slimming policy 與 regression fixtures。
- Operational/historical source-health lifecycle，含 active logical scope/generation、相容的 legacy counts 與 additive operational/historical counts/query。
- 三軸 quote freshness contract，含 scheduler universe、symbol-set digest、requested/captured/failed counts、coverage ratio、required slot 與 missing symbols/slots。
- Expected-date-aware daily metrics refresh 與 strict outcome postcondition；之後再建立 bounded repair loop、repair ledger、dedupe/backoff/circuit/startup reconciliation。
- Additive status taxonomy 與 backend-owned mapping；必要的 Frontend/MCP/Kuro-facing schema/type sync，但 consumer 不重算。
- Targeted unit/contract/integration tests、public contract snapshot parity、safe validation 與代表性 DB/API/MCP/runtime adoption 證據。
- 持續更新本目錄 `Progress.md`，記錄每個 milestone、實際檔案、測試、決策、known issues 與下一步。
- 依功能邊界整理可審查的 patch/commit candidates；除非使用者另行授權，不執行 commit 或 push。

## Done criteria

- 同一 request/session 下，direct index API、summary、AI `market.indices` 與 persisted snapshot 使用同一 `resolution_id` 或可證明等價的 canonical output、trade date、provider lineage 與 quality。
- `cache_only` resolver 測試證明零 external IO；`prefer_live`／`require_live` 的 bounded provider policy、timeout、fallback 與 failure reason 可驗證。
- 昨日 official close 不再被標為今日 live；official close、current observation、series completeness 與 provisional/finalized 狀態可機器判讀。
- 代表性 market-overview 預設請求不會因 required core 自我拒絕；caller explicit limit 仍嚴格生效，且任何縮減／continuation 都在 envelope 中可見。
- Source health 預設 operational view 不再被退出 active scope/provider generation 的歷史資料污染；canonical stale `target=all` 仍被正確列為 operational problem。
- Legacy `problem_count` 相容性有測試；新的 operational/historical entry/problem counts 與 `include_historical`/scope 行為有版本化 contract。
- Quote scheduler freshness 不再用單一任意 latest row 代表 `all`；每個 contract snapshot 都有明確 universe、digest、coverage 與 missing detail。
- Daily refresh worker 使用 release-aware expected trade date；required dataset 未達該日期時 job 必須 failed/partial，而非 success。
- Bounded repair loop 能在缺口出現、provider 恢復與 startup reconciliation 情境中自動補洞；重複觸發不產生重複 job，超限/circuit/open/provider unavailable 均可見。
- `service_status`、`data_quality`、`decision_readiness`、`provider_status` 的 backend mapping、優先序與 limitation 一致，Frontend/MCP 不自行推導。
- 相關 targeted regressions、backend safe validation、contract snapshot parity 與必要 consumer checks 全部通過。
- 若使用者核准 formal runtime adoption，必須證明 launcher-selected URL、exact owner/path/start time、listener、health、`/api/ai/tools`、代表性 API、frontend proxy（若適用）與 session-preserving MCP `initialize -> tools/list -> tools/call` 都採用新版本。
- 沒有刪除／重建 DB、沒有無界 external refresh、沒有未授權 runtime restart、沒有遺失既有 dirty work、沒有未授權 commit/push。

## Open questions / assumptions

- 預設先以 read-time／existing-table metadata 解決 logical generation；只有證明無法可靠表達時才提 migration，不能直接假設要改 DB schema。
- Active provider/scope registry 的最終存放位置要在 Milestone 0 依現有 config/provider registry 決定，避免建立第二份設定真相。
- Canonical index 是否需要新 public endpoint 不預設；優先保留既有 route 並在內部收斂 resolver。
- Response budget 欄位名稱與 continuation 形式以現有 `omi.decision.v4` pattern 為準，但 caller explicitness 與 effective ceiling 必須可觀測。
- Frontend 只有在新增 status 需要呈現時才修改；不先建立 UI banner，錯誤應進既有「更新狀態」資料狀態流程。
- 正式 runtime restart/adoption、跨 repo Kuro 實測、commit 與 push 都是獨立授權 gate；source 實作完成不自動授權這些動作。

## Authorization state

- 2026-08-14：使用者授權先建立長專案規劃。
- Production implementation：尚未於本階段開始；等待使用者下一步明確指示後，依 `Plan.md` 連續執行。
- Formal runtime restart/adoption：未授權。
- Commit/push/PR：未授權。
