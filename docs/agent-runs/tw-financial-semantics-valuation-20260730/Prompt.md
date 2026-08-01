# 台股財務語意與估值正規化

## 目標

- 建立可長期維護、可追溯、可做 point-in-time 查詢的台股基本面資料能力。
- 明確區分來源原始值、正規化值、單季／TTM／估值衍生值及其品質狀態。
- 讓 backend 成為財務期間、公司行動、股本基準、資料連續性、估值與 AI 可用性的唯一真相來源。
- 修正目前把累計 EPS 當單季、把累計值相加、跨股本基準比較、錯用 provider 出表日期及缺期仍標示可用等問題。
- 以多個 golden cases 驗證；若任何最終數值與官方來源或會計語意不一致，停止擴大實作並重新審視來源、模型與公式。

## 非目標

- 不把 OMI 變成自動交易或單純猜漲跌工具。
- 不在 frontend、MCP 或 Kuro 重做財務正規化與估值邏輯。
- 不以國巨專屬 hardcode、固定 `/4` 或單一股票例外作為正式解法。
- 不在本任務順手重構無關 market、Radar、US corporate events 或其他既有功能。
- 不在尚未完成 dry-run、備份與可逆性驗證前修改 production SQLite 資料。
- 不因本專案自動觸發無邊界的全市場外部 API 回補。

## 不可違反的限制

- 原始來源事實必須不可變且可追溯；更正資料以新版本或 superseding relation 保存，不覆蓋歷史事實。
- `period_end`、`filed_at`、`announced_at`、`provider_generated_at`、`fetched_at` 必須是不同語意。
- 損益／現金流的 duration fact 與資產負債表的 instant fact 不可使用同一個模糊期間語意。
- 單季 EPS 只有在會計口徑與股數分母可比較時才能由累計值相減；前置條件不明時必須回傳 blocked。
- 公司行動必須區分價格調整、每股財務指標調整與流通股數變動；現金股利不得被當成股數調整。
- TTM 只能由四個可比較、正規化後的離散季度值建立。
- PE 必須攜帶 price、price_as_of、price_basis、EPS basis 與 freshness，不得成為無時間基準的季度常數。
- freshness、continuity、semantic validity、decision usability 必須分開表達。
- 既有 public API 需採相容演進；不得靜默改變既有 `eps` 欄位含義。
- 所有 migration 必須可追蹤；不得以 `Base.metadata.create_all()` 造成 silent schema drift。
- Frontend、MCP、Kuro 只能消費 backend HTTP／AI contract，不得直接讀寫 OMI DB。
- 現有 dirty worktree 視為使用者或其他流程所有；不得 revert、覆寫或夾帶無關修改。

## 真相來源與衝突處理

優先順序：

1. 公司正式財報、MOPS 正式申報文件與重大訊息。
2. TWSE／TPEx 正式彙整資料及公司行動公告。
3. OMI 保存的 provider raw payload。
4. 第三方鏡像或衍生資料。

若來源間不一致：

- 保存所有來源與版本，不以無證據的優先序靜默覆蓋。
- 將該 metric／period 標為 disputed 或 blocked。
- 記錄差異、來源文件、抓取時間與選擇理由。
- 在完成 reconciliation 前，不產出 decision-ready TTM、PE 或趨勢結論。

## 重新審視規則

以下任一情況發生時，立即停止目前 milestone 的擴大工作：

- Golden case 與官方財報、重大訊息或可重現人工計算不一致。
- 同一來源在重跑後產生不同 canonical 結果。
- 正規化後年度值無法在允許誤差內與官方年度值 reconciliation。
- 單季、TTM、ROE、ROA 或 PE 的 lineage 無法完整回溯。
- Point-in-time 查詢使用了當時尚未公開的財報或公司行動。
- Frontend、AI、MCP 與 backend public envelope 對同一數值呈現不同語意。

發生時必須回到下列順序重新審查：

1. 原始文件與來源版本。
2. period scope／duration／instant 語意。
3. basic／diluted EPS 與加權平均股數。
4. 公司行動類型、effective date 與 adjustment purpose。
5. 正規化版本與 derivation lineage。
6. API／AI／consumer projection。

不得以調整 tolerance、增加股票特例或修改 UI 顯示來掩蓋資料錯誤。

## 範圍

### 目前優先階段：一般產業 `ci`

- 先將最大宗的一般產業 official filing coverage、parse review、正規化候選與
  例外分流產品化，再擴大特殊 variant。
- 一般產業 universe 以已保存的 TWSE／TPEx official financial bundle
  `income_ci`／`balance_ci` 為依據，不以名稱、產業描述或 legacy 欄位猜測。
- `ci` 只代表報表 variant，不代表股本未變或資料必然可自動核准；公司行動、
  重編、會計基礎與 filing conflict 仍必須走相同 stop-and-fix gate。
- 詳細營運與自動化邊界見 `CiRolloutContract.md`。

### 資料與 persistence

- 財務 statement facts 的 raw／versioned 保存。
- 台股公司行動 ledger。
- 正規化結果、derivation lineage 與 normalization version。
- 月營收與季度財報 continuity。
- Source precedence、重複資料 canonicalization、idempotent backfill。

### Backend contract

- As-reported、comparable-adjusted、single-quarter、TTM、valuation snapshot。
- Freshness、continuity、semantic validity、decision usability。
- Structured issue codes、warnings、missing／partial／blocked。
- Point-in-time 與 current-comparable 查詢模式。

### AI 與 consumer

- AI fundamentals slot 只使用 decision-usable 指標。
- Frontend 顯示來源期間、股本基準、調整狀態與資料限制。
- MCP／Kuro 維持 thin consumer，不複製計算。

### Runtime 與操作

- Bounded refresh、provider events、source health。
- Migration dry-run、資料庫副本、integrity check、backfill audit。
- 透過正式 launcher 驗證 deployed runtime。

## 交付物

- `FinancialDataContract.md`：事實、日期、期間、股本基準、調整、品質與 public envelope。
- Alembic migrations 與 ORM model contract。
- Raw fact／corporate action／normalization／derivation services。
- Deterministic backfill 與 reconciliation report。
- Versioned backend API 與 AI fundamentals projection。
- Frontend 基本面顯示修正。
- Parser、service、migration、API、AI、frontend 與 live runtime 驗證。
- Golden-case fixtures 與人工計算對照。

## 完成條件

- 一般產業 `ci` 全市場都有可重現的 coverage stage 與下一步，且 raw、candidate、
  reviewed production 三層不混用。
- 可批次處理的 `ci` 標的能以 bounded、dry-run-first、單檔失敗隔離的流程完成
  filing ingestion、immutable parse、review、normalization candidate 與驗證。
- 無法自動處理的公司行動、重編、filing version conflict、會計基礎或
  reconciliation 異常會進例外清單，不產生猜測 TTM／PE。
- 國巨案例能解釋每個來源值的期間與股本基準，並產出可追溯的單季與 TTM；`12.7175` 僅是目前候選期望值，必須經正式文件、股數基準與公式 reconciliation 後才能成為 golden truth。
- 台積電等無股本事件案例在 factor=1 時不產生不必要變更。
- 至少涵蓋一般產業、金融控股／銀行、保險及存在公司行動的發行人。
- 缺少內部月份／季度時，即使最新 key 存在也會輸出 continuity warning，且不錯誤標成完全可用。
- Provider 出表日期不再被當成公司發布日。
- Annual、YTD、single-quarter、TTM、ROE／ROA、PE 均有明確公式、時間基準、lineage 與阻擋條件。
- Existing legacy consumers 不因 contract 演進而 silent break；舊欄位有明確 deprecation／semantics。
- Backfill 可重跑且結果 deterministic；production DB 修改前已完成副本 dry-run、差異摘要與 integrity check。
- Backend API、AI v4、MCP／Kuro projection、frontend 與 live launcher runtime 對相同標的輸出一致。
- 所有驗收測試與 live smoke 通過；若數值不符，依「重新審視規則」回到前置 milestone，不標記完成。

## 已知狀態

- Repo：`C:\project\Open Market Intelligence`
- 輸入規格：`C:\Users\thoma\Downloads\OMI_台股財務語意與估值修正規格書_2026-07-30.txt`
- 目前確認 `financial_metric_quarterly` 缺少期間、股本基準與正規化語意。
- 目前 frontend 會把來源累計 EPS 當季度並在年度模式相加。
- 目前 AI fundamentals 可在語意未正規化時標為 ready／usable。
- 目前台股 corporate-events contract 無法完整表達面額變更、分割、減資與換股。
- 目前月營收 expected-latest-key freshness 無法偵測內部缺期。
- 目前 v4 decision envelope 已有部分 quote／daily date fusion guard，但其他公開路徑尚未一致。
- Worktree 有大量其他未完成變更，且與本專案會碰到的 model、AI projection、frontend type 檔案重疊。

## 待確認假設

- MOPS／TWSE 各 financial OpenAPI variant 對 EPS 是否提供已追溯重編值，需逐來源及文件版本驗證。
- 國巨 2025 年各期 EPS 的 basic／diluted、weighted-average-share 與後續重編語意需以正式文件確認。
- Point-in-time 與 current-comparable 是否共用 persistence 或只在 projection 層建立，待基準測試後決定。
- 是否能從現有官方來源穩定取得台股完整公司行動資料，否則 capability 必須明確標示 provider gap。
