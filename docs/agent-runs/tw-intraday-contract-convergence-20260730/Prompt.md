# 台股盤中資料契約根治與能力收斂

## 目標

- 以 `C:\Users\thoma\Downloads\OMI_台股盤中資料能力驗收與改善工程規格_v1.0.txt`
  與 2026-07-30 盤中實測為驗收基線，根治台股個股與市場盤中資料的價格、
  時間、freshness、usability、coverage、provider health 與部分成功語意。
- 建立 backend-owned、可重放、可由 Frontend、MCP 與 Kuro 共同消費的唯一
  台股盤中資料契約，避免各 consumer 自行推論 current price、日期關係或
  readiness。
- 先完成 P0 correctness 與資料品質，再補 P1 市場盤中能力；P2 只在前述
  契約穩定後分階段導入。
- 維持 `omi.decision.v4`、`evidence.data[capability_id]` 與
  `evidence.capability_status` 的公開契約方向，採 additive、可相容演進，
  不建立第二套 public response 或 readiness 真相來源。

## 規格與既有基線

- 主要規格：
  `C:\Users\thoma\Downloads\OMI_台股盤中資料能力驗收與改善工程規格_v1.0.txt`。
- 既有台股資料面契約：
  `docs/agent-runs/taiwan-data-surface-v1/`。
- Backend 架構契約：
  `docs/architecture/BackendArchitecture.md`。
- 長期產品方向：
  `docs/product/ProductVision.md`、`OperatingModel.md`、`QualityBar.md`、
  `Roadmap.md`。
- Repo：`C:\project\Open Market Intelligence`。
- 建立本任務時的分支：`codex/taiwan-data-surface-v1`。
- 本任務建立時工作樹已有大量 Radar、US、Frontend 與台股契約未提交變更；
  一律視為使用者或其他流程所有，不回復、不重排、不混入無關修改。

## 已確認的問題基線

### 個股盤中鏈路

- 2303 與 8299 的 quote snapshot 可只有即時五檔，`last_price=null`，
  但當日 1 分 K 已有可用 close。
- `ask_finalizer` 的人類可讀摘要已有局部 intraday price fallback，但
  canonical stock context、technical levels 與 decision engine 尚未共享
  同一個 current price resolver。
- `read_stock_context` 在取得 quote depth 與 intraday bars 前就建立
  technical levels，造成盤中技術價位仍以 completed daily close 為錨。
- explicit `require_live` 目前會把符合 provider delay window、序列完整的
  1 分 K 一併標為 blocked，且把已取得 facts 判成不可用。
- 今日盤中 quote 搭配前一完整交易日 daily bar 會被誤判
  `quote_daily_date_mismatch`。
- 五檔 parser 可能讓 `price=0` 且有 size 的 level 成為 best bid／ask。

### 市場聚合與時間語意

- 2026-07-30 實測的分鐘市場狀態只有 TWSE breadth，TPEX 缺失。
- 現有 minute-state writer 在 breadth 缺失時會跳過整個市場 row，使原本
  可保存的 trade value 也一起遺失。
- `market.sectors` 與 sample ranking 可能以 query／assembly 的盤中時間作
  `as_of`，但實際內容來自前一交易日 completed daily sample。
- TPEX 指數單點 snapshot 目前不足以宣稱為真正 1 分 K。
- 現有全市場 screening 主要是前日法人／融資 daily ranking，不是盤中
  price／volume screening。

### Source Health

- 2026-07-30 實測 persisted Taiwan source-health snapshot 仍停在
  2026-07-22。
- 當次 provider request 成功與過期 persisted snapshot 可能同時存在，
  但目前 outward health 無法穩定表達兩者的優先順序與不同用途。
- GET/read path 必須維持 read-only；定期 health sync 應由 scheduler／job
  owner 負責。

## 工作範圍

### P0：正確性與安全

- P0-01：統一 current price resolution，分離 trade price 與 depth status。
- P0-02：拆分 temporal freshness、policy compliance、facts/research usability
  與 execution-grade usability。
- P0-03：建立 session-aware date relation。
- P0-04：讓盤中 technical levels 使用 resolved current price，同時保留
  completed daily 結構指標。
- P0-05：排除非正價格成為 best limit price，保存 raw level 並保守分類。
- P0-06：補齊 TWSE／TPEX breadth 與 universe reconciliation。
- P0-07：分離 observed trade date、event time、computed/generated time 與
  data mode。
- P0-08：分離 request-local、persisted 與 effective source health。

### P1：盤中市場能力

- P1-01：取得真正的 TPEX 1 分 K，或以明確 synthetic contract 呈現定時
  snapshot 聚合結果；單點 snapshot 不得標為 1m。
- P1-02：建立 TWSE／TPEX 累積成交金額、5／20 日同分鐘基準與部分成功保存。
- P1-03：建立 scheduler-owned、cache-read 的全市場盤中 screening。
- P1-04：建立具 membership provenance 的盤中熱門產業／題材群組。
- P1-05：支援 Watchlist group ID 與名稱解析，歧義時回傳 candidates。
- P1-06：沿用 `evidence.capability_status` 進行 query-scoped readiness，
  不新增第二套 readiness matrix。

### P2：契約穩定後的品質提升

- 盤中 breadth／trade value／volume pace 趨勢與歷史比較。
- 更完整的盤中 group metrics、相對指數強弱與離散度。
- Replay、provider drift fixture、SLO／telemetry 與長期監控。
- 只有在 P0/P1 資料可追溯、可部分成功且公開契約穩定後才排入實作。

## 不在本任務範圍

- 自動下單、交易執行、代替使用者做不可逆交易決策。
- 為修台股盤中資料而重寫 US、JP、KR、HK 或 Crypto 市場。
- 在 Frontend、MCP 或 Kuro 複製 current price、freshness、provider fallback、
  market session 或 readiness 邏輯。
- 將 GET/read path 改成隱性全市場 refresh、昂貴 backfill 或報告／記憶寫入。
- 在 provider 官方語意未確認前，把所有零價位直接命名為市價委託或漲跌停
  排隊量。
- 把 previous close、bid/ask midpoint 或單點 index snapshot 偽裝成即時成交。
- 無關 dependency upgrade、格式化-only diff、大型 module rewrite。
- 未經使用者明確要求的 commit、push、publish 或正式資料破壞性操作。

## 硬性限制

- 台股是核心市場；其他市場只作 regression surface，不因本任務改變產品定位。
- Backend AI／market service 是價格、時間、freshness、quality、provider、
  fallback、readiness 與公開 answer contract 的唯一 owner。
- `evidence.capability_status` 是 consumer-facing capability 狀態唯一權威。
- `compact.*`、legacy slots 與既有 specialized routes 可暫時保留，但只能由
  canonical result 衍生，不得各自重新判斷。
- 原始 provider observation 必須可追溯；resolved value 不得覆寫 raw value。
- `event_time`、`observed_trade_date`、`computed_at`、`generated_at` 必須明確
  分離。
- Freshness、policy、semantic usability、execution grade、coverage 與
  completeness 必須為正交維度，不壓成單一布林值。
- `require_live` 保留嚴格語意。當其不滿足時可以保留
  `facts_usable=true`／`intraday_research_usable=true`，但整體
  live-required decision readiness 仍可 blocked，且
  `execution_grade_usable=false`。
- Previous close 永遠只作 reference；bid/ask midpoint 只能是有清楚標記的
  estimate，不能默認成 technical/PnL 的高信心 current price。
- Provider adapter／parser 保持 IO 或純 payload conversion；不得讀寫 DB。
- Transaction、upsert、scheduler 與 snapshot persistence 由 service/job
  owner 負責；router 不直接 commit／rollback。
- GET/read path 只揭露資料與 snapshot age，不隱性同步全市場 health。
- DB schema 變更只走 Alembic additive migration；不得重建或覆蓋
  `data/open_market_intelligence.db`。
- 全市場 collector 必須 bounded：明確 universe、批次大小、timeout、重試、
  quota、leader ownership、dedupe、coverage 與失敗回報。
- 所有 outward contract 改動保持 additive/versioned；若必須 breaking，
  先更新本文件並取得使用者確認。

## 信任邊界與責任分配

### Backend market/provider layer

- 保存 raw observation、provider identity、event time、source URL 與 failure。
- 執行 bounded refresh、fallback、normalization、upsert 與部分成功保存。
- 不產生 AI human answer。

### Backend AI contract layer

- 擁有 current price resolution、date relation、freshness/usability、
  capability status、technical interpretation 與 outward evidence。
- 統一產生 structured answer 與 human-readable limitations/warnings。

### Scheduler/job layer

- 擁有 source-health sync、market-minute persistence、全市場 rolling state 與
  collector lifecycle。
- 只允許 leader 執行背景工作；重跑必須 idempotent。

### Frontend、MCP、Kuro

- 只呈現 backend contract。
- 不讀寫 OMI DB、不直接呼叫 provider、不重算 fallback/freshness/readiness。

## 核心資料契約方向

### Current price

```json
{
  "value": 1570.0,
  "source_kind": "intraday_bar_latest",
  "semantics": "delayed_last_trade",
  "event_time": "2026-07-30T10:48:00+08:00",
  "age_seconds": 34,
  "confidence": "high",
  "is_estimate": false,
  "fallback_reason": "quote_last_trade_unavailable"
}
```

- 原始 quote 另保留 `quote_semantics=live_depth_only` 與
  `quote_depth_status`，不得因 resolved price 存在而改寫 provider 的真實語意。

### Observation quality

```json
{
  "temporal_freshness": "delayed",
  "policy_satisfied": false,
  "facts_usable": true,
  "intraday_research_usable": true,
  "execution_grade_usable": false,
  "coverage_status": "complete",
  "completeness_status": "complete"
}
```

### Time identity

```json
{
  "observed_trade_date": "2026-07-29",
  "event_time": "2026-07-29T13:30:00+08:00",
  "computed_at": "2026-07-30T10:48:40+08:00",
  "data_mode": "previous_completed_session",
  "is_intraday": false
}
```

### Source health

```json
{
  "request_health": {
    "status": "success",
    "checked_at": "2026-07-30T10:48:20+08:00"
  },
  "persisted_health": {
    "status": "expired",
    "checked_at": "2026-07-22T12:00:00+08:00"
  },
  "effective_health": {
    "status": "request_succeeded",
    "warnings": ["persisted_health_snapshot_expired"]
  }
}
```

## 交付項目

- 可重放的 CASE-01～CASE-10 fixtures 與 acceptance tests。
- Backend-owned current price、observation quality、session date relation 與
  effective source-health primitives。
- 個股 context、technical levels、PnL、answer finalization 與
  `omi.decision.v4` 的端到端一致投影。
- Quote-depth 零價位與 empty-side 的保守語意。
- Field-level partial Taiwan market-minute persistence；若需 schema 變更，包含
  Alembic migration、dry-run 與 DB integrity 證據。
- TWSE／TPEX breadth、trade value、volume pace 與 index intraday 的來源、
  coverage、synthetic/finalized 與 reconciliation 契約。
- Scheduler-owned intraday screening snapshot、group metrics 與 Watchlist resolver。
- Frontend、MCP、Kuro 相容性調整與操作文件。
- Safe validation、隔離 runtime、正式 launcher-selected HTTP/MCP 與實際交易
  時段驗收證據。

## 完成定義

- CASE-01～CASE-10 全部通過，且沒有用 mock 掩蓋 canonical resolver 路徑。
- 2303 與 8299 在 quote last trade 缺失但 1 分 K 可用時，current price、
  technical levels、PnL、human answer 與 structured evidence 一致。
- 今日盤中 observation 搭配前一 completed daily 不再被誤判日期衝突。
- 非正價格不會成為 best bid／ask；未證實語意保持 raw/unknown。
- `require_live` 不滿足時，policy 與 research facts 可用性分離且不誤稱
  execution grade。
- TWSE、TPEX coverage 個別揭露；缺一市場時 combined 只能 partial。
- 有 trade value、無 breadth 時仍保存可用欄位，不再整列遺失。
- Previous-session ranking 明確揭露 observed date，不再包裝成盤中排行。
- 當次 provider 成功優先反映於 effective health，同時保留 persisted snapshot
  過期警告。
- TPEX 單點 snapshot 不再偽裝成 1m；synthetic bars 必須可辨識且具來源與
  point-count 證據。
- Query-scoped readiness 只由 canonical capability status 衍生。
- Frontend、Backend API、repo MCP、standalone OMI_search 與 Kuro-facing
  projection 不重做市場語意。
- DB migration（如有）可重跑、通過 integrity check，且沒有資料遺失。
- Targeted regression、backend safe profile、必要的 frontend
  lint/typecheck/build、隔離 runtime 及正式 runtime smoke 全部通過。
- 正式 runtime 的 registry/schema digest 與預期 source 一致，並完成盤中、
  收盤後與休市／非交易時段至少一輪 session-aware 驗收。

## 開放問題與預設假設

- 零價位的 provider 官方語意尚未證實；預設先排除 best price 並保留 raw，
  不直接映射為 market-order quantity。
- TPEX index 若無官方分鐘 OHLC，預設採 scheduler snapshot aggregation 並標
  `synthetic=true`；不能為追求表面完整而合成假成交。
- Market-minute schema 預設採 additive、field-level quality 設計；實作前先
  以現有 model/index/query pattern 評估新增欄位或拆表的最小安全方案。
- 熱門題材 membership 預設需要具版本與 provenance 的資料來源；LLM 不得
  臨時創造 membership。
- 實際盤中驗收需配合交易時段；無法於同一輪完成時，先以固定 fixture 與
  replay 證明，再在下一個可用 session 補正式 runtime 證據。
