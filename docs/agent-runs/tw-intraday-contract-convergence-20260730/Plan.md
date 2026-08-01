# 台股盤中資料契約根治與能力收斂計畫

## 執行原則

- 依賴順序是「可重現證據 → 共用語意 → 個股鏈路 → 市場聚合 →
  新盤中能力 → consumer → 正式 runtime」，不是按規格編號逐條打補丁。
- 每個里程碑先做最小、局部修改，完成 acceptance 與 focused regression
  後才進下一階段。
- P0 correctness 未完成前，不實作 P1-03／P1-04 等新功能。
- 每完成一個里程碑即更新 `Progress.md`，記錄修改面、驗證、決策與剩餘風險。
- 所有正式 runtime、migration、外部 provider 與全市場 collector 驗證均採
  bounded、可停止、可回復方式。

## 里程碑依賴

```text
M0 Fixtures / Contract baseline
  -> M1 Shared semantic primitives
    -> M2 Stock current-price and technical pipeline
      -> M3 Realtime quality and session-date reconciliation
        -> M4 Quote-depth and source-health correctness
          -> M5 Market-minute partial persistence
            -> M6 TWSE/TPEX breadth, trade value and index intraday
              -> M7 Intraday screening state
                -> M8 Group/theme and Watchlist resolution
                  -> M9 Consumer and docs convergence
                    -> M10 Production rollout and acceptance
```

## 里程碑

### M0：契約基線與可重放驗收案例

- 範圍：
  - 新增專用 acceptance fixture/test surface，不先改 production behavior。
  - 固定 2026-07-30 的 2303、8299、TWSE、TPEX、ranking、market minute
    state 與 source-health 案例。
  - 建立 CASE-01～CASE-10 對照表與預期 outward contract。
- 預計修改：
  - `backend/tests/fixtures/` 內最接近既有 Taiwan fixture pattern 的位置。
  - 新增或擴充 `backend/tests/test_tw_intraday_contract_acceptance.py`。
  - 必要時擴充既有 `test_taiwan_stock_quote_depth.py`、
    `test_intraday_contract_remediation.py`、
    `test_ai_decision_envelope.py`、
    `test_taiwan_market_state.py`。
- 驗收：
  - CASE-01～CASE-10 都能在無外網、固定時間下重現。
  - 測試可明確指出目前錯誤，不把既有錯誤輸出當成新 expected behavior。
  - Fixture 不含 secrets、私人憑證或不可提交的大型原始 payload。
- 驗證：
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_tw_intraday_contract_acceptance.py -q`
  - 行為修正前允許新 acceptance tests 以明確已知原因失敗；不得以 skip／xfail
    永久掩蓋。
- 停止條件：
  - 若 fixture 無法區分 raw provider observation 與 resolved value，先修訂
    fixture schema，不進 M1。

### M1：共用價格、時間與品質語意

- 範圍：
  - 建立 pure、typed 的 current price resolver。
  - 建立 temporal freshness、policy、facts/research usability、
    execution grade、coverage 與 completeness 的正交狀態。
  - 建立 session-aware date relation primitive。
- 預計修改：
  - 優先放在 `backend/app/ai/` 既有 realtime/data-quality pure contract
    邊界；若需新 module，保持單一責任並由現有 façade 匯入。
  - `backend/app/ai/realtime_contract.py`
  - `backend/app/ai/data_quality_contract.py`
- 驗收：
  - Resolver 不做 IO、不讀 DB、不改寫 raw observation。
  - Current price 優先序為有效 current-session trade、finalized 1m close、
    partial 1m close；midpoint 只能明確標 estimate；previous close 只作
    reference。
  - `require_live` 不滿足時可保留 facts/research usability，但
    execution-grade 一定為 false。
  - 今日盤中與前一 completed daily 得到
    `expected_current_session_vs_completed_daily`。
- 驗證：
  - Pure resolver/date/quality unit tests。
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_intraday_contract_remediation.py backend\tests\test_ai_decision_envelope.py -q`
- 停止條件：
  - 若新增欄位與 `evidence.capability_status` 形成第二套狀態權威，先收斂
    canonical projection，不進 M2。

### M2：個股 current price 與技術分析端到端收斂

- 範圍：
  - 重排 `read_stock_context` 的 daily、quote、intraday、resolver、
    technical structure 與 projection 順序。
  - 讓 technical levels、PnL、decision engine、ask finalizer 與 outward
    evidence 使用同一 resolved current price。
  - 保留 daily structure 與 intraday overlay 的不同基礎。
- 預計修改：
  - `backend/app/ai/market_context/taiwan_stock.py`
  - `backend/app/ai/market_context/taiwan_projection.py`
  - `backend/app/ai/technical_analysis.py`
  - `backend/app/ai/decision_engine.py`
  - `backend/app/ai/ask_finalizer.py`
  - 必要時 `backend/app/market/technical_report.py`
- 驗收：
  - CASE-01、CASE-08 通過。
  - 2303／8299 quote last trade 缺失時使用 latest eligible 1m close。
  - `technical_levels.latest_price`、PnL basis、human answer 與
    `evidence.data` 一致。
  - MA／ATR／Donchian 仍使用 completed daily，且回傳 basis date/timeframe。
  - Previous close 不會再被投影為 current price。
- 驗證：
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_ai_market_context_projection.py backend\tests\test_technical_report.py backend\tests\test_ai_decision_envelope.py backend\tests\test_tw_intraday_contract_acceptance.py -q`
- 停止條件：
  - 任一 consumer path 出現不同 current price，先追到共用 resolver，不在
    consumer 加局部 fallback。

### M3：Realtime quality 與 session-date reconciliation

- 範圍：
  - 將 explicit live policy 與事實可用性分開。
  - 修正 quote／intraday／completed daily 的預期日期關係。
  - 將 canonical quality 與 `evidence.capability_status` 對齊。
- 預計修改：
  - `backend/app/ai/realtime_contract.py`
  - `backend/app/ai/data_quality_contract.py`
  - `backend/app/ai/decision_envelope_v4.py`
  - 相關 public v4 projection/tests。
- 驗收：
  - CASE-02、CASE-03 通過。
  - `prefer_live` 研究查詢可使用符合 provider delay window 的完整序列。
  - explicit `require_live` 可 blocked，但已取得 facts 不被抹除。
  - 跨交易日、休市與 completed daily 判定使用 Taiwan calendar/session。
  - 既有 US/JP/KR 共享 realtime contract 行為不退化。
- 驗證：
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_intraday_contract_remediation.py backend\tests\test_ai_decision_envelope.py backend\tests\test_ai_public_v4_contract.py -q`
  - 補跑受共享 contract 影響的跨市場 regression。
- 停止條件：
  - 若同一 capability 在 manifest、quality、freshness 與
    `evidence.capability_status` 出現不同 readiness，先完成 reconciliation。

### M4：Quote depth 與 Source Health 正確性

- 範圍：
  - 排除 `price <= 0` 成為 best limit price，保留 raw level。
  - 在 provider semantics 未確認前以 `unknown/non_price` 保守分類。
  - 建立 request-local、persisted 與 effective health。
  - 建立 scheduler-owned、session-aware、bounded Taiwan health sync。
- 預計修改：
  - `backend/app/market/quote_depth.py`
  - `backend/app/market/source_health.py`
  - `backend/app/observability/provider_health.py`
  - `backend/app/ai/market_context/source_health_context.py`
  - `backend/app/jobs/scheduler.py`
  - 必要的 scheduler/runtime ownership tests。
- 驗收：
  - CASE-04、CASE-10 通過。
  - Best bid/ask 永遠是正價格或 null。
  - Empty ask/bid 與 raw zero level 可觀測，但不做無證據的漲跌停結論。
  - 當次 request success 優先反映 effective health；persisted expiry 仍可見。
  - GET source-health 不寫 DB、不觸發全市場同步。
  - 背景 sync 只有 leader 執行，具 timeout、dedupe 與交易時段 policy。
- 驗證：
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_taiwan_stock_quote_depth.py backend\tests\test_provider_health.py backend\tests\test_market_source_health.py backend\tests\test_runtime.py backend\tests\test_runtime_lock.py backend\tests\test_tw_intraday_contract_acceptance.py -q`
- 停止條件：
  - 若 scheduler 會在 follower 重複執行、GET 產生寫入或 provider health
    telemetry 影響市場 transaction，先修 ownership boundary。

### M5：Market-minute field-level partial persistence

- 範圍：
  - 解開 breadth、trade value、quote/index 與 volume pace 的 all-or-nothing
    寫入。
  - 評估 additive 欄位或穩定責任拆表；不得建立第二個 ORM Base。
  - 建立 migration、backfill 與讀寫相容層。
- 預計修改：
  - `backend/app/market/taiwan_market_state.py`
  - `backend/app/db/models.py`
  - `backend/alembic/versions/` 的新 revision。
  - `backend/app/jobs/scheduler.py`
  - `backend/tests/test_taiwan_market_state.py`
  - `backend/tests/test_database_migrations.py`
- 驗收：
  - CASE-09 通過。
  - 無 breadth、有 trade value 時仍保存該欄位與獨立 quality。
  - Reader 組合結果為 partial，不是整份 null。
  - Migration 可在資料庫副本重跑並通過 integrity、row-count 與 index 檢查。
  - 舊 API/ORM query 保持相容或有明確 additive fallback。
- 驗證：
  - 先複製 DB 到 `.tmp` 後執行 migration dry-run；不得對唯一 production DB
    做未驗證 migration。
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_taiwan_market_state.py backend\tests\test_database_migrations.py backend\tests\test_market_transaction_contracts.py backend\tests\test_tw_intraday_contract_acceptance.py -q`
- 停止條件：
  - Integrity、row count、downgrade/compatibility 或 idempotency 任一不明確，
    不部署 migration。

### M6：TWSE／TPEX breadth、成交值、量能與 index intraday

- 範圍：
  - TWSE universe reconciliation 與分類 breakdown。
  - TPEX current breadth。
  - TWSE/TPEX 累積成交金額、5／20 日同分鐘基準。
  - TPEX 官方 1m 或明確 synthetic snapshot aggregation。
- 預計修改：
  - `backend/app/market/indices.py`
  - `backend/app/market/taiwan_market_state.py`
  - 相關 provider adapter/parser。
  - `backend/app/ai/market_context/taiwan_market.py`
  - scheduler/jobs 與 market aggregate tests。
- 驗收：
  - CASE-05、CASE-06 通過。
  - TWSE/TPEX 各自回傳 target、observed、excluded、unknown、duplicate count
    與 instrument policy。
  - 缺一市場時 combined 只能 partial。
  - Coverage overflow 不會被 ratio clamp 掩蓋。
  - Volume state 揭露 sample days、estimate method、confidence 與來源時間。
  - 單點 snapshot 不標為 1m；synthetic bar 有 point count、source interval、
    finalized/partial 與 indicator eligibility。
- 驗證：
  - Provider fixture tests。
  - `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_tw_market_aggregates.py backend\tests\test_taiwan_market_state.py backend\tests\test_ai_market_context_projection.py backend\tests\test_tw_intraday_contract_acceptance.py -q`
  - 外部 API 只做 bounded symbol/market spot check，記錄 provider event。
- 停止條件：
  - 若無法證明 TPEX minute source 語意，保持 snapshot capability，不合成
    假 1m。

### M7：Scheduler-owned 全市場盤中 Screening

- 範圍：
  - 建立 bounded full-market rolling state。
  - 新增或擴充 canonical `screening.intraday` capability。
  - 支援 change、trade value、5/15m move、high/low rebound、VWAP deviation、
    volume pace 與 relative strength 等可追溯 metrics。
- 預計修改：
  - Taiwan market collector/job/service。
  - AI registry、selection parameters、projection 與 capability tests。
  - Screening cache/read path；不在 AI request 中抓全市場。
- 驗收：
  - 同一 snapshot 重複查詢 deterministic。
  - 每次結果有 snapshot identity、event time、universe、coverage、
    excluded reasons、metric unit/semantics。
  - Provider 部分失敗時保留上一份資料並標 stale/partial。
  - Query path cache-only，沒有隱性 refresh。
  - Collector 具 batch、timeout、quota、leader ownership、dedupe 與
    observability。
- 驗證：
  - Screening unit/integration tests。
  - Bounded load smoke，記錄 symbol count、duration、provider calls、failure
    count 與 DB writes。
  - `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_tw_screening.py`
- 停止條件：
  - 未先量測 provider call budget、單輪時間或 DB 寫入量，不啟用全市場排程。

### M8：熱門群組、題材與 Watchlist 名稱解析

- 範圍：
  - 建立 versioned/provenance-aware industry/theme membership。
  - 建立 `market.group_intraday` 或與 registry 命名一致的 capability。
  - Watchlist exact normalized name resolver 與 ambiguous candidates。
- 預計修改：
  - Backend group/membership service。
  - Watchlist scope resolution 與 ask policy。
  - Capability registry/projection/tests。
  - 如 membership 需持久化，另提 additive migration 設計與人工審核邊界。
- 驗收：
  - Group metrics 揭露 member coverage、median、dispersion、leader
    concentration 與 relative benchmark。
  - LLM 不創造 membership；所有 membership 有 source/version/effective date。
  - Group ID 與 exact name 可解析；模糊或重名回 candidates，不自動選錯。
  - 不新增只為動作命名的 target；優先使用既有 target + capability。
- 驗證：
  - Scope resolution、registry、projection、Watchlist/Radar targeted tests。
  - Representative explicit ID、exact name、ambiguous name API smoke。
- 停止條件：
  - Membership provenance 或更新 ownership 不明確時，不發布「熱門題材」
    判斷。

### M9：Consumer、文件與相容性收斂

- 範圍：
  - Frontend 顯示 price source/age、delayed、partial、previous session、
    source-health layers 與 market coverage。
  - Repo MCP、standalone OMI_search、Kuro-facing projection 保持 thin。
  - 修正 `OperatingModel.md` 仍提到 `result.data.slots` 的契約漂移。
  - 保留必要 legacy alias，但所有狀態由 canonical result 衍生。
- 預計修改：
  - `frontend/` 相關台股工作台元件與型別。
  - `agents/` repo MCP。
  - `C:\GPT_MCPtool\OMI_search` 僅在獨立授權與 path-scoped 工作下處理。
  - Product/API/consumer 文件。
- 驗收：
  - UI 不把 delayed 顯示成 live，不把 previous-session ranking 顯示成今日。
  - MCP schema/digest 與 backend 一致，無 adapter-side市場邏輯。
  - `omi.ask`、read shortcuts 與 Kuro projection 使用同一 v4 evidence/status。
  - Accessibility、responsive layout、文字溢出與 loading/error 狀態可用。
- 驗證：
  - Backend/MCP contract tests。
  - `npm run lint`
  - `npm exec tsc -- --noEmit --incremental false`
  - 依實際 UI 風險決定 `npm run build` 與 browser screenshot。
  - MCP：`initialize` → 保留 `Mcp-Session-Id` → `tools/list` →
    representative `tools/call`。
- 停止條件：
  - Consumer 若需自行比較日期、選 fallback price 或重算 readiness，表示
    backend contract 尚未完成，先退回修 backend。

### M10：完整 regression、正式部署與實際交易時段驗收

- 範圍：
  - 完整 backend safe validation。
  - 隔離 runtime outward proof。
  - 正式 launcher-selected backend/frontend/MCP restart 與 smoke。
  - 盤中、收盤後與非交易時段驗收。
- 驗收：
  - CASE-01～CASE-10 全部通過。
  - Prompt.md 完成定義全部有證據或明確標為需要下一交易時段補驗。
  - DB migration（如有）先在副本通過，再由正式 launcher 啟動 migration。
  - Registry/schema digest、source、runtime owner/path 與 selected ports 一致。
  - 2303、8299、TW market、TPEX、screening、group、Watchlist 與 source-health
    representative calls 成功。
  - Frontend proxy、repo MCP、standalone OMI_search 與 Kuro-facing contract
    不漂移。
- 驗證：
  - `.\scripts\run-safe-validation.ps1 -Profile backend`
  - 依實際 frontend 修改執行
    `.\scripts\run-safe-validation.ps1 -Profile frontend`
  - 隔離 runtime health、`/api/ai/tools`、`/api/ai/ask`。
  - 正式 launcher log 的 `selected=`、process owner/path、health、frontend
    proxy 與 session-preserving MCP smoke。
- 停止條件：
  - 正式 worktree 仍有未穩定並行變更、runtime digest 不一致、migration
    未驗證或固定敏感 port owner 不明時，不進正式 restart。

## CASE 對應里程碑

| CASE | 問題 | 主要里程碑 |
| --- | --- | --- |
| CASE-01 | Live depth only + intraday current price | M1、M2 |
| CASE-02 | Delayed 30 秒完整 K | M1、M3 |
| CASE-03 | 今日 quote + 昨日 completed daily | M1、M3 |
| CASE-04 | 五檔零價位 | M4 |
| CASE-05 | TPEX breadth 缺失 | M6 |
| CASE-06 | TWSE universe overflow | M6 |
| CASE-07 | Previous-session ranking | M3、M6、M9 |
| CASE-08 | Intraday technical levels | M2 |
| CASE-09 | Market-minute partial persistence | M5 |
| CASE-10 | Request-local health success | M4 |

## 全域 Stop-and-fix 規則

- 任一里程碑 focused regression 失敗，先修正或證明為隔離的既有失敗，不以
  新增 skip、放寬 assertion 或改 expected value 掩蓋。
- Source、DB、API、MCP、Frontend 對同一 capability 的價格、時間、quality
  或 readiness 不一致時，停止下游工作並回到 canonical owner 修正。
- 發現 read path 產生昂貴副作用、全市場隱性 refresh、付費 quota、報告／
  memory 寫入或無界 provider call，立即停止並更新 `Prompt.md`。
- 發現 migration 需要重建／覆蓋 DB、無法保證 idempotency 或資料保留，
  暫停並提出 additive 替代方案。
- 發現 provider payload 語意無官方或 fixture 證據，不以猜測填入 outward
  contract；保留 raw/unknown 與 limitation。
- 發現 Frontend、MCP、Kuro 必須重做 backend 市場邏輯，停止 consumer
  實作並回補 backend contract。
- 發現工作樹的 Radar、US 或其他並行修改與本任務重疊，不回復對方修改；
  先理解差異並更新 `Progress.md`，必要時請使用者協調 checkpoint。
- 未經使用者明確要求，不 commit、push、publish、force restart 或操作
  production-like DB。

## 決策紀錄

- 2026-07-30：新建
  `docs/agent-runs/tw-intraday-contract-convergence-20260730/`，不覆寫
  `taiwan-data-surface-v1` 歷史；前者負責 2026-07-30 盤中實測後的根治工程。
- 2026-07-30：不按 P0/P1 編號直接逐項修補；先建共用 semantic kernel，
  再修 consumer-visible pipeline。
- 2026-07-30：`evidence.capability_status` 維持唯一 consumer-facing
  readiness authority；P1-06 只擴充既有 query-scoped readiness。
- 2026-07-30：explicit `require_live` 維持嚴格；facts/research usability
  與 execution-grade usability 分離。
- 2026-07-30：零價位先排除 best price 並保留 raw；沒有 provider 證據前
  不一律命名為市價單。
- 2026-07-30：previous close 只作 reference，midpoint 只作明確 estimate；
  technical/PnL 預設不使用未標示估值。
- 2026-07-30：市場分鐘狀態採 field-level partial persistence；migration
  必須 additive、可 dry-run、可重跑。
- 2026-07-30：全市場盤中狀態由 scheduler/job owner 建立，AI/API read path
  只讀 snapshot。
- 2026-07-30：正式 launcher restart 放在 source、migration、targeted
  regression 與隔離 runtime 都穩定後，且需避開混合 dirty worktree 的
  半成品狀態。
