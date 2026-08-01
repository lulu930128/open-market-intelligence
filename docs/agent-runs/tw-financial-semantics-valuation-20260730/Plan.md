# 計畫

## 里程碑

## 執行狀態

- M0：完成。
- M1：完成。
- M2：完成。
- M3：完成 P0 正規化核心。
- M4：完成 clone migration、bounded backfill、idempotency、production raw semantic backfill 與月營收連續性修復。
- M5：完成，API／AI／MCP／frontend 契約及 clone／formal runtime 已驗證。
- M6：完成安全 rollout；production raw facts 已可稽核，未通過正式來源治理的 normalized／derived facts 持續 blocked。
- M7：代表標的 reconciliation gate、2327 v3 re-audit、backend-owned daily-close valuation resolver 與 point-in-time canonical review history 已完成。2327、2330、2801、2855 reviewed packages 與 2881、2867、2207 blocked assessments 已於 2026-08-01 完成 production promotion；immutable `filing -> parse_run -> facts -> review_event` schema、parser v2/v3、canonical approval、normalized evidence、precision-aware contract 與 migrations `20260731_0048`／`20260731_0049` 均已驗證。
- M7 production promotion 已於 2026-08-01 完成；2327、2330、2801、2855 reviewed packages 與 2881、2867、2207 blocked assessments 已進 production，正式 launcher／API／AI／MCP／browser 已驗證。
- M8：完成。已完成 1,928 檔 `ci` universe 的 query-only terminal-stage manifest、固定 seed 20 檔分層架構驗收、bounded ingestion、MOPS 節流、`AUTO` 報表範圍一致性、parser v4 `issued_capital` evidence、append-only review，以及 2324／3528／5902 的 reviewed production canary。三檔 normalized／derived contract 均 ready，TTM EPS 分別為 1.33／3.11／2.16；價格落後 expected close 時 PE 一律 unavailable。正式 launcher、API、AI、MCP、frontend 與 DB integrity 已驗證。M8 不宣告其餘 1,923 檔 normalized；它們在 final manifest 中明確維持 `missing_official_filings`，後續只能沿同一 bounded gate 分批處理。

### M8：一般產業 ci 全市場營運化

- 範圍：
  - 從已保存 official bundle 建立 `ci` universe 與 read-only coverage planner。
  - 對指定 periods 輸出 filing、parse review、EPS scope、normalized、公司行動與 basis 狀態。
  - 建立 bounded symbol batch；先 clone pilot，再逐批 ingestion／review／candidate package。
  - 將公司行動、重編、會計基礎與 filing conflict 留在例外佇列。
- 驗收：
  - Planner 全市場統計可重現、query-only、income／balance coverage mismatch 可見。
  - 每檔只有一個可操作 stage／next action；不得把 missing 或 blocked 當 ready。
  - Batch 有 symbols、periods、offset／limit、timeout、provider-call ceiling 與單檔失敗隔離。
  - 只有通過 parse、share-basis、reconciliation 與 reviewed package gate 的標的可 production promotion。
- 驗證：
  - `backend/tests/test_financial_ci_rollout.py`
  - Planner 對 production DB 的 read-only full-universe smoke。
  - Clone pilot 的重跑 idempotency、row count、hash、integrity 與 representative contract。
  - Production rollout 後 API／AI／MCP／launcher runtime proof。

### M0：基準、來源語意與 golden dataset

- 範圍：
  - 建立 current schema、parser、service、API、AI、frontend、runtime 的完整 inventory。
  - 對 MOPS／TWSE financial variants、日期欄位、期間範圍、單位與版本語意建立 source matrix。
  - 建立國巨、台積電、金融業、保險業及缺期案例的人工 reconciliation fixtures。
  - 將目前規格中的假設值與正式文件逐一比對。
- 驗收：
  - 每個 golden fact 都有 source document、period scope、unit、known-at time 與人工公式。
  - 無法確認的值標為 unresolved，不作為實作常數。
  - 國巨候選 TTM 若與正式文件語意不符，更新規格與 golden truth，保留差異理由。
- 驗證：
  - Read-only DB queries。
  - Bounded official-source probes。
  - Fixture reconciliation tests。

### M1：立即安全止血

- 範圍：
  - Backend 對未知 period scope、混合股本基準、缺期或不完整 lineage 輸出 structured warnings。
  - AI fundamentals 對不可用估值改為 partial／blocked。
  - Frontend 停止將 YTD／annual EPS 當單季相加；改為顯示 source-reported scope。
  - 將既有 quote／daily date fusion guard 套用至所有 decision-facing public routes。
- 驗收：
  - 現有錯誤數值不再被 UI 或 AI 表示為可信的單季／年度／TTM／PE。
  - Legacy API shape 維持相容，新增語意欄位與 warnings。
  - Frontend 不新增任何財務正規化公式。
- 驗證：
  - Targeted backend contract tests。
  - Frontend unit／typecheck／lint。
  - 2327 API、AI context 與 browser smoke。

### M2：財務事實與公司行動資料模型

- 範圍：
  - 設計 raw statement fact、filing version、corporate action、normalization lineage。
  - 明確區分 duration／instant、日期語意、basic／diluted、currency／unit、consolidation scope。
  - 建立 Alembic migration，不破壞既有 production rows。
- 驗收：
  - Migration upgrade、downgrade 或明確可逆策略完成。
  - ORM metadata、constraint、index、unique key 與 source lineage 有 contract tests。
  - 現有 `financial_metric_quarterly` 保留相容，不被靜默重新定義。
- 驗證：
  - `test_database_migrations.py`
  - `test_database_model_contract.py`
  - SQLite clone upgrade／integrity check。

### M3：正規化與衍生引擎

- 範圍：
  - Period classifier、source precedence、corporate-action adjustment chain。
  - Single-quarter、TTM、annual reconciliation、ROE／ROA 與 valuation snapshot。
  - Point-in-time 與 current-comparable 模式。
  - Normalization version、issue codes、decision usability。
- 驗收：
  - 所有衍生值均能列出 input fact IDs、action IDs、公式版本與 as-of。
  - 前置條件不成立時不輸出數值，改為 blocked／not_applicable。
  - 國巨、台積電、金融／保險 fixtures 全部符合 golden truth。
- 驗證：
  - Pure normalization tests。
  - Property／invariant tests。
  - Annual-to-quarter reconciliation。
  - Point-in-time no-lookahead tests。

### M4：Backfill、連續性與 reconciliation

- 範圍：
  - 對 DB 副本執行 bounded backfill。
  - 檢查重複來源、缺月／缺季、版本衝突及公式不一致。
  - 產出輸入、輸出、跳過、blocked、disputed 與差異摘要。
- 驗收：
  - 重跑結果 deterministic、idempotent。
  - 內部缺期不因 latest key current 而被隱藏。
  - Production DB 寫入前有明確 dry-run 報告與安全門檻。
- 驗證：
  - Clone DB dry-run。
  - Row-count／checksum／integrity checks。
  - Representative-symbol reconciliation。

### M5：Public API、AI、MCP 與 frontend 契約

- 範圍：
  - Versioned financial envelope：as_reported、normalized、derived、quality、source_refs。
  - AI fundamentals slots 與 decision contract。
  - Thin MCP／Kuro projection。
  - Frontend source-period、adjusted-basis、warnings 與 unavailable states。
- 驗收：
  - 同一 symbol／as-of 在 backend API、AI v4、MCP、Kuro projection 與 frontend 具有一致語意。
  - Payload bounded，missing／partial／blocked／disputed 可見。
  - Legacy consumers 有相容測試與 deprecation path。
- 驗證：
  - API inventory／schema tests。
  - AI projection／public v4 contract tests。
  - MCP initialize、tools/list、representative tool call。
  - Frontend lint、typecheck、build 及必要 browser smoke。

### M6：正式 runtime 驗證與 rollout

- 範圍：
  - 透過正式 OMI launcher 套用 migration 與 runtime。
  - 驗證 PID、owner、實際 backend／frontend ports、health、provider events。
  - 執行 bounded live cases，不做全市場無限制 refresh。
- 驗收：
  - Launcher-owned runtime 載入目前 source 與 migration head。
  - Live 2327、2330、金融／保險與缺期案例符合 golden truth。
  - 發現錯誤時按 stop-and-fix 規則退回來源／模型 milestone。
- 驗證：
  - Launcher log、process path、health endpoints。
  - Live API／AI／MCP／browser evidence。
  - Final reconciliation report。

### M7：正式 filing ingestion 與 production normalization

- 範圍：
  - 建立 MOPS official filing／XBRL 的版本化擷取、解析、來源雜湊與 known-at contract。
  - 納入 basic／diluted EPS、weighted-average shares、restatement、consolidation scope 與公司行動 lineage。
  - 擴充台積電、金融、保險與公司行動案例的 golden dataset。
  - 僅在 reconciliation 通過後產生 production normalized／TTM／valuation facts。
- 驗收：
  - 每一個 decision-facing normalized fact 都能追溯至正式 filing facts、公式版本及公司行動。
  - 來源修訂、重編或股本基準不一致時，舊結果失效且重新計算，不得靜默沿用。
  - Q2／Q3 filing 若提供 official discrete-quarter EPS，必須保存並優先使用該 context；不得以累計 EPS 相減取代官方單季 fact。
  - 同一份 immutable filing 可保留多個 parser-version 的 parse run，facts 必須歸屬明確 parse run；舊 parse run 不覆寫、不刪除。
  - 2327、2330、金融與保險 golden cases 均通過 point-in-time 與 current-comparable 驗證。
- 決策門檻：
  - 已批准以 official filing／iXBRL 作為 production authoritative source。
  - 已撤銷的 v1 evidence fixture 保持 `approval_scope=clone_only`；2327 v2
    production package 與 parse runs 保留 immutable 稽核，但已由 v3
    package hash
    `e46bcaed9dc264f8831ad69531d223ab0808aef60fca82ceb8f2a9c2ba94fe87`
    supersede。V3 production promotion 必須使用新 package、backup 與精確
    parser v3 output hashes，不覆寫 v2 lineage。
  - 正式 ingestion 必須採 explicit CLI、dry-run-first、bounded targets/calls；GET/read path 不得觸發外部 refresh。
  - iXBRL 負責 machine-readable concept／context／unit；正式 PDF 與電子文件目錄負責申報公開時間、股本基準與附註證據。generic XBRL facts 不得用名稱猜測分母。
  - 已採用 `filing -> parse_run -> facts`；canonical selection 只選最新核准且成功的 parse run。舊 parse output 保留供稽核，新 output 在人工核准前一律 pending 且不得進入 decision-facing contract。
  - 已採用 reviewed accounting-basis assessment；當新準則追溯資訊只覆蓋部分比較期間時，contract 必須列出缺少的同基礎期間並阻擋 normalized／TTM／valuation，不得混合新舊會計基礎。

## Stop-and-fix 規則

- 任一 golden case 數值錯誤，立即停止後續 consumer 或 rollout 工作。
- 不得為讓測試通過而調整 golden truth；必須先以官方來源與人工公式重做 reconciliation。
- 不得在股數分母不可比較時以 YTD EPS 相減。
- 官方 filing 已提供 discrete-quarter EPS 時，不得以 YTD delta 當作等價替代。
- 不得以單一股票或 provider-specific hardcode 取代 domain rule。
- 任一 migration、backfill 或 refresh 對 production DB 有未確認破壞風險時停止。
- Targeted test 通過但 public envelope 或 live runtime 不一致時，視為尚未完成。
- Source-health current 但 continuity／semantic validity 失敗時，decision usability 必須為 false。
- Dirty worktree 與本專案目標檔案衝突時，先理解並協調現有變更，不覆寫或 revert。

## 2026-08-01 production rollout checkpoint

- 已完成：正式服務停止後，以 SQLite online backup API 建立 production 一致性備份，並通過 SHA-256、full `PRAGMA integrity_check` 與資料列數核對。
- 已完成：production schema 位於 `20260731_0049`；parse-run review 採 append-only event history，2327 v2 已 revoke、v3 已成為 current canonical，舊 as-of 仍可重現 v2。
- 已完成：2327、2330、2801、2855 的 reviewed production packages；2881、2867、2207 的 reviewed IFRS 17 basis assessments。
- 已完成：整庫 full integrity、foreign-key、targeted financial、AI、public v4、MCP、正式 launcher、live API 與 browser 驗證。
- 正式使用邊界：只有 reviewed normalization 才可輸出單季 EPS／TTM；會計基礎不完整或價格日期不符時必須維持 blocked／unavailable，不得以 legacy 值或舊收盤價補算。
- 後續 rollout 仍採同一 gate：bounded official ingestion → immutable parse run → explicit review → clone-only package → production promotion → full integrity → public runtime proof。

## 已決定事項

- 採 raw／normalized／derived 分層，不覆寫來源原始值。
- Backend 擁有財務語意、公司行動、品質與估值邏輯。
- Current-comparable 與 point-in-time 是不同查詢模式。
- 既有 `eps` 不靜默改義；以版本化欄位與契約逐步遷移。
- Freshness、continuity、semantic validity、decision usability 分開。
- 本專案的完成標準是跨 backend、DB、API、AI、MCP／Kuro、frontend、launcher runtime 的最終公開結果。
- 舊 v1 lineage 的 `12.7175` 是撤銷且不得復用的 disputed result；v2 的
  `12.7175` 雖有 official discrete lineage，也已被 v3 的 period-scope 與
  precision review supersede。現行 golden truth 為 Q4=`3.29`、
  TTM exact=`12.725`、display=`12.73`；年度 difference=`+0.005` 必須以
  來源精度 tolerance 解釋，不得為湊成 0 而改寫 official facts。
