# 一般產業（ci）全市場正規化營運契約

## 目的

本契約把已完成的單檔財務語意、immutable parse run、review、normalized
evidence 與 valuation gate，擴展成一般產業 `ci` 的可持續全市場流程。

`ci` 是目前 TWSE／TPEx financial bundle 最大宗的報表 variant；本階段先提高
一般產業覆蓋，不以一般產業規則推論銀行、證券、金控、保險或異業報表。

## Capability canvas

| 項目 | 契約 |
|---|---|
| Product scope | 支援台股主線的基本面 evidence、單季 EPS、TTM 與具日期估值；不產生自動下單或保證報酬。 |
| Target | 只處理最新已保存 TWSE／TPEx official financial bundle 中 `income_ci`／`balance_ci` 的有效股票代號；其他 variant 保持例外流程。 |
| Provider | TWSE／TPEx bundle 用於 current universe 與 legacy raw；MOPS official filing／iXBRL 是 decision-facing normalized fact 的主要來源。 |
| Resource | Income duration facts、balance instant facts、basic／diluted EPS、正式 filing metadata 與 daily official close。 |
| Time semantics | `period_end`、`filed_at`／`known_at`、`provider_generated_at`、`fetched_at` 分離；OpenAPI `出表日期` 不得當 issuer release time。 |
| Request bounds | 單一 filing ingestion 最多 8 periods；全市場只由明示 batch job 執行，必須有 symbols、periods、offset／limit、timeout 與 request 上限。 |
| Persistence | 沿用 `filing -> immutable parse_run -> statement_fact -> reviewed normalized_fact`；不修改 legacy raw 值，不新增 silent schema drift。 |
| Freshness | 財報 freshness、期間 continuity、semantic validity、decision usability 與價格 freshness 分開判定。 |
| Failure | Empty、missing filing、parser gap、pending review、share-basis unresolved、corporate action、accounting-basis transition、filing version conflict 均需分類，不轉成 0。 |
| Transaction | Provider／parser 不 commit；單一 symbol ingestion 由 service／CLI transaction 擁有；批次隔離單一 symbol failure。 |
| Public API | 現階段沿用 `omi.financial.v1` 與既有 route；規劃器是操作工具，不新增 GET side effect。 |
| AI／consumer | 只有 reviewed、decision-usable normalized facts可進 AI／frontend／MCP；consumer 不重算 EPS、TTM 或 PE。 |
| Validation | Pure bundle parser、planner service、bounded CLI、clone pilot、idempotency、annual reconciliation、API／AI／MCP／runtime proof。 |

## 三層資料狀態

### A. Raw official

- 保存 TWSE／TPEx／MOPS 的來源值、期間與版本。
- 可以查詢與呈現，但不得因「有值」推定單季、TTM 或可比較股本基準。

### B. ci candidate

- 已取得目標期間的 official filing。
- 每份 filing 有成功且 immutable 的 parser output。
- Parser scopes、units、consolidation 與 EPS facts 通過 deterministic checks。
- 尚未通過 share-basis／公司行動／reconciliation 時仍不是 decision-ready。

### C. Reviewed production

- Canonical parse runs 已有 append-only review history。
- Share basis、公司行動、重編與會計基礎已有正式 evidence。
- 單季、annual reconciliation、TTM 及 point-in-time guards 通過。
- Clone-only package 經 promotion gate 轉為 production package，且 public runtime 一致。

## 一般產業分流

| Stage | 意義 | 下一步 |
|---|---|---|
| `missing_official_filings` | 目標期間 filing 不完整 | Bounded MOPS ingestion |
| `pending_parse_review` | Filing 已保存，但 parser output 尚未核准 | Hash／fact-count／scope review |
| `filing_version_conflict` | 同期間有多個 current-approved filing version | 先做 source revision reconciliation |
| `parser_contract_gap` | 缺必要 YTD／annual EPS scope或語意不完整 | 修 parser／source mapping，不進 normalization |
| `needs_share_basis_review` | Parser 完整，但股數基準或公司行動尚未證明 | 取得正式 evidence，建立 clone-only package |
| `needs_action_reconciliation` | 已知 per-share 公司行動 | 驗證追溯重編與 double-adjustment guard |
| `basis_blocked` | 會計基礎不連續 | 維持 TTM／PE null，等待同基礎比較期 |
| `normalized_ready` | Reviewed normalized periods 已完整 | 驗證 TTM、價格、public contract 與 runtime |

## 自動化邊界

- 可以自動：universe discovery、coverage 統計、bounded ingestion、immutable
  parse、output hash／fact-count／scope checks、候選排序、annual tolerance 計算、
  idempotency 與 public smoke。
- 不可因無事件紀錄就自動宣稱股本未變；目前公司行動來源 coverage 尚未完整。
- 不可自動批准 conflicting filing、來源重編、股本事件、IFRS transition 或
  annual reconciliation 超出來源精度 tolerance 的標的。
- Planner 與 GET/read path 只讀；任何外部抓取或 DB 寫入都必須是明示、
  bounded、dry-run-first 的 job／CLI。
- Provider 若在回傳 summary 前失敗，已發出的 request 數可能無法精確回收；
  batch 必須把 `actual_request_count` 設為 null，另外回報已知的
  `accounted_request_count` 與 `request_count_complete=false`，不得偽造完整計數。
- `IssuedCapital` 相同只是 share-basis 證據之一，不等於自動證明沒有分割、
  面額變更或追溯重編；仍需跨 filing comparative reconciliation 與 review。

## 第一批驗收門檻

- 從本機 official bundle 重現 `ci` universe，income／balance mismatch 可見。
- 對每檔輸出目標期間 coverage、parse review、scope、normalized coverage、
  corporate-action／basis flags 與唯一下一步。
- Planner 查詢 production DB 時強制 query-only，不產生資料寫入。
- 第一批實際 ingestion 先使用 clone／隔離資料庫，單批 symbols 與 provider
  calls 有上限，單檔失敗不影響其他標的。
- Production promotion 仍沿用 backup、explicit review、clone-only package、
  promotion、integrity check 與正式 launcher runtime gate。

## 2026-08-01 clone 驗收決策

- 驗收抽樣不是每次任意挑股：使用固定 seed 的 deterministic stratified
  sample，保留 TWSE／TPEx 比例並排除既有 pilot，讓結果可重現與稽核。
- Batch 對 MOPS 必須設定明示的 inter-symbol delay。HTTP 200 但找不到 filing
  不能直接判成官方缺期；先以延遲單檔重試區分 soft-block 與真實 coverage。
- `REPORT_ID=AUTO` 可在 consolidated C／AI1 不存在時選 individual A／AI2，
  但同一 symbol 的所有目標期必須由單一 report scope 完整覆蓋；禁止為了補齊
  五期而混用 C 與 A。
- Q2／Q3 official `discrete_3m` 是單季 EPS authoritative fact。YTD 加減只作
  reconciliation 診斷，不得因各 duration context 的 weighted-average shares
  不同而覆寫官方單季值。
- 20 檔 clone 驗收通過的是架構、分類與安全門，不代表 1,928 檔已全部
  normalized。Production 仍只接受通過每檔 machine checks、exact-hash review、
  share-basis／action reconciliation 與 reviewed package gate 的明示清單。

## Production source identity 補充

- `content_hash` 是文件內容的一致性主證據，但 promotion selector 仍必須精確
  對應 production 保存的 `source_document_id`，不得因內容相同就放寬 selector。
- MOPS 同一文件可能在 clone evidence 使用 `.ixbrl` identity，而正式 provider
  保存 `.pdf` identity。此時必須先以 production query-only lineage 重建
  source-aligned clone-only package，再 promotion；不得修改既有 filing identity。
- 2324／3528 已依此規則產生 `*-production-source-aligned.json`，5902 原 package
  identity 已與 production 一致。三份 package 的 canonical hash 與 audit output
  都保存於 M8 manifest。
