# M8 一般產業財務架構驗收

## 驗收結論

2026-08-01 的 clone 架構驗收通過，可以進入 reviewed production promotion
階段；尚未把 20 檔或全市場寫入 production，也尚未宣告全市場 normalized。

通過範圍包括 deterministic universe／sampling、bounded official ingestion、
provider 節流、同一報表 scope 選擇、immutable parser v4 lineage、exact-hash
review、stage 分流、代表性 normalized／單季 EPS／TTM／PE、idempotency 與
整庫完整性。Production promotion、正式 launcher、API／AI／MCP／frontend
runtime proof 是下一個獨立 gate。

## 樣本設計

- Universe：最新 `ci` official bundle，共 1,928 檔。
- 排除既有 pilot／production sentinel：1815、2303、2317、2324、2327、2330。
- 可抽樣母體：1,922 檔。
- Seed：`omi-ci-acceptance-20260801-v1`。
- 分層：TWSE 11 檔、TPEx 9 檔。
- 抽樣契約：`omi.tw-financial-ci-acceptance-sample.v1`；query-only，無網路、
  無 DB 寫入。

| 市場 | 樣本 |
|---|---|
| TWSE | 1503、1529、2548、2609、3138、3528、4764、6201、6235、6671、6854 |
| TPEx | 3362、4442、5230、5902、6751、6961、6983、8403、8440 |

## 實際結果

| 結果 | 檔數 | 標的 | 判定 |
|---|---:|---|---|
| `normalized_ready` | 1 | 3528 | A／AI2 個別報表完整 normalization、TTM、PE 路徑通過 |
| `needs_share_basis_review` | 9 | 1503、1529、2609、4764、5902、6201、6671、6751、6854 | 五期完整且 current issued capital 穩定；仍需每檔 reviewed package |
| `needs_action_reconciliation` | 7 | 3138、3362、4442、5230、6235、8403、8440 | current issued capital 發生變化，正確進例外佇列 |
| `missing_official_filings` | 3 | 2548、6961、6983 | 無單一 C 或 A scope 覆蓋五期，正確 rollback 且不標 ready |

完整 ingestion 的 17 檔共建立 85 個 parser v4 runs 與 2,322 個 statement
facts。Declared fact count 與 stored fact count 相同；85 個 output hashes 都是
64 位，85 個 runs 都有 append-only approval event；每個 run 都有一個
current-period `IssuedCapital` fact。三個缺期標的沒有留下 partial parser v4
filing。

## 驗收中發現並修正的問題

### MOPS burst soft-block

第一次密集批次只有 4／20 成功；延遲單檔重試證明多數 filing 實際存在，
不是資料缺失。Batch 已新增 0–60 秒的 explicit inter-symbol delay，CLI 預設
5 秒；驗收批次使用 10 秒。失敗仍按 symbol transaction rollback，不污染
其他標的。

### 合併與個別報表 coverage

3528 只有 A／AI2，原本固定 C 會誤判缺檔。Provider 現在支援
`REPORT_ID=AUTO`，在同一份 document index 同時評估 C／AI1 與 A／AI2，
只選能完整覆蓋所有要求期別的單一 scope，優先 C；若必須跨期混用則整檔
拒絕。2548、6961、6983 因沒有任何單一 scope 覆蓋五期，維持缺期例外。

## EPS 與估值語意驗證

- 10 檔 current issued capital 穩定樣本的 2025Q1 current EPS，都與 2026Q1
  filing 的 2025Q1 comparative EPS 完全一致。
- Q2／Q3 優先採官方 `discrete_3m`，同時保留 YTD context。YTD 與單季加總
  可能因四捨五入或 weighted-average shares 不同而有差異，因此只當診斷，
  不得取代官方單季 fact。
- 3528 單季 EPS：2025Q1 2.02、Q2 -3.33、Q3 1.58、Q4 2.03、
  2026Q1 2.83；TTM exact 3.11，status=`ready`。
- 3528 用驗收用明示價格 31.10 驗證 PE TTM=10.00；這只是公式 contract
  測試，不是實際市場估值。未提供新鮮價格時，既有 stale-price guard 仍讓
  PE 保持 unavailable。

## 驗證證據

- Evidence package dry-run：7 create candidate。
- 第一次 clone apply：7 created。
- 第二次 clone apply：0 created／7 reused。
- 3528 package hash：
  `538a4d18a66ee9c6b766394ee894d626acb102615de6515055e259a1d4314532`。
- `PRAGMA integrity_check`：`ok`。
- Targeted regression：45 passed。
- Backend compileall：通過。
- Production query-only proof：revision=`20260731_0049`、parser v4 runs=0、
  3528 normalized facts=0。

## 驗收邊界與下一個 gate

20 檔抽樣足以驗收「同一套一般產業架構」是否能正確成功、分流與拒絕，
不需要人工逐筆檢查 1,928 檔。但是不能把抽樣通過解讀成每檔事實都已核准。
專業系統會對全市場自動跑 per-symbol coverage、hash、scope、capital、
comparative 與 reconciliation machine checks，只對通過者建立 reviewed promotion
候選；缺期、公司行動、重編與會計基礎轉換繼續留在例外佇列。

下一階段只允許：明示 promotion 清單、production backup、exact package／parse
hash、先 dry-run、再 apply、full integrity、正式 launcher runtime 與 public
API／AI／MCP／frontend 一致性驗證。任一數值不符即停止 promotion 並退回
source／parser／share-basis reconciliation，不以 legacy 值補洞。

## 2026-08-01 M8 production 收尾

上述獨立 gate 已完成，M8 驗收狀態改為「通過並收尾」。本次只 promotion
明示 canary 2324、3528、5902，沒有把 clone 抽樣或其餘 universe 靜默寫入
production。

- 備份：`data/backups/open_market_intelligence-before-m8-ci-canary-20260801-151400.db`，
  SHA-256=`5195a3ecff894b2237edd8a8aca391362ca2b73bed524f897a29a013805cfac1`，
  full `integrity_check=ok`，13,144,727,552 bytes。
- Ingestion／review：21／21 provider requests 成功；15 filings、15 parser v4
  runs、390 statement facts；15 個 exact output hashes 全數核准，review events
  為 3925–3939。
- Promotion：三檔各 7 normalized facts，第二次 apply 均為 0 create／7 reuse；
  final full `integrity_check=ok`。
- Public contract：2324／3528／5902 normalized 與 derived 均 ready，TTM EPS=
  1.33／3.11／2.16；三檔價格日期均落後 2026-07-31 expected close，所以 PE
  正確維持 unavailable，而不是以 stale price 計算。
- Public surfaces：formal HTTP、`omi.decision.v4`、stdio MCP 與 frontend 使用同一
  `omi.financial.v1` 語意；MCP `isError=false`，frontend 明確顯示來源 YTD／全年
  不可相加、正規化單季 EPS、TTM 與「待有效價格」。
- DB：revision=`20260731_0049`、`quick_check=ok`、foreign-key violations=0。
- Full universe：四頁 planner 共 1,928 個唯一 stock id，每檔恰一 terminal
  stage；5 檔 `normalized_ready`（2324、2327、2330、3528、5902），1,923 檔
  `missing_official_filings`。

### 最終邊界

M8 完成的是可重現的全市場分類、受限批次能力、reviewed promotion 安全門與
正式 consumer 一致性，不是「1,928 檔都已有官方 v4 facts」。其餘 1,923 檔
仍可查 legacy/raw 基本面，但單季 EPS、TTM 與 PE 不得冒充已正規化；後續擴充
屬於相同系統的受控 coverage 維運，不是 M8 未完成事項。
