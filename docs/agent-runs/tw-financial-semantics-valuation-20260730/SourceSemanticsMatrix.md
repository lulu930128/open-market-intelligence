# 台股財務來源語意矩陣

## 已連接來源

| 資源 | 正式來源／endpoint | Coverage | 來源期間語意 | 日期語意 | 單位 | 目前 OMI 狀態 |
|---|---|---|---|---|---|---|
| TWSE 綜合損益表 | `t187ap06_L_{variant}` | 上市公司、最新資料集期間 | Q1 通常 3M；Q2／Q3 為 YTD；Q4 為 annual | `出表日期` 是資料集產製日期，不是公司公告日 | 財務金額需由 endpoint contract 補入；EPS 為元／股 | 直接寫入季度寬表，缺 scope／unit |
| TWSE 資產負債表 | `t187ap07_L_{variant}` | 上市公司、最新資料集期間 | Period-end instant | 同上 | 財務金額需補入；BVPS 為元／股 | 直接與 duration facts 合併 |
| TPEx 綜合損益表 | `mopsfin_t187ap06_O_{variant}` | 上櫃公司、最新資料集期間 | 與 TWSE 同類，仍需 variant fixture 驗證 | `出表日期` 不得當 filed/released | 待 endpoint contract 固化 | 同上 |
| TPEx 資產負債表 | `mopsfin_t187ap07_O_{variant}` | 上櫃公司、最新資料集期間 | Period-end instant | 同上 | 待 endpoint contract 固化 | 同上 |
| MOPS 歷史損益表 | `ajax_t163sb04` | 指定市場、年度、季度 | 來源列為該期報表累計／年度數值 | Endpoint 不提供可靠公告／申報日 | 頁面明示新台幣仟元；EPS 元／股 | 可回補歷史，但未保存 period/unit |
| MOPS 歷史資產負債表 | `ajax_t163sb05` | 指定市場、年度、季度 | Period-end instant | Endpoint 不提供可靠公告／申報日 | 頁面明示新台幣仟元；BVPS 元／股 | 與損益列合併進寬表 |
| TWSE 月營收 | `t187ap05_L` | 上市公司、最新月份 | 單月與年初累計同列 | `出表日期` 是 provider output date；`資料年月` 是 period | 新台幣仟元 | 歷史與 current parser 日期語意不一致 |
| TPEx 月營收 | `mopsfin_t187ap05_O` | 上櫃公司、最新月份 | 同上 | 同上，待 fixture 驗證 | 新台幣仟元 | 同上 |

正式 OpenAPI 入口：[TWSE OpenAPI](https://openapi.twse.com.tw/)

## Financial variants

| Variant | 類型 | 2026Q1 TWSE sample | Golden candidate |
|---|---|---|---|
| `basi` | 金融業／銀行 | 2801 彰銀 | 2801 |
| `bd` | 證券期貨業 | 2855 統一證 | 2855 |
| `ci` | 一般業 | 2327 國巨、2330 台積電 | 2327、2330 |
| `fh` | 金控業 | 2881 富邦金 | 2881 |
| `ins` | 保險業 | 2867 三商壽 | 2867 |
| `mim` | 異業 | 2207 和泰車 | 2207 |

Parser 必須以 variant 驗證 not-applicable 與欄位 mapping，不能假設所有產業都有 revenue、gross profit、parent equity 或相同 income label。

## 已確認的 local evidence

### OpenAPI 出表日期

Raw result `50065`：

- Fetch time：2026-07-27 12:11:12。
- 十二個 TWSE financial bundle entries 全部只有 `出表日期=1150727`。
- 所有公司及全部 financial variants 使用相同出表日期。
- 國巨、台積電、銀行、證券、金控、保險及異業資料均相同。

因此現行 parser 將 `出表日期` 映射到 `report_date/released_at` 是錯誤語意。契約映射應為 `provider_generated_at`。

### MOPS 歷史頁單位

Raw results `5266`–`5269` 對應國巨 2025 Q1–Q4：

- Income 與 balance 頁均出現「單位：新台幣仟元」。
- `基本每股盈餘（元）` 另有 per-share unit。
- 現行 `FinancialMetricQuarterly` 未保存 source unit。

### Period scope

國巨財報與月營收 reconciliation：

| 財務期間 | 財報 revenue | 月營收 cumulative | 差異 |
|---|---:|---:|---:|
| 2025Q1 | 31,103,695 | 31,103,695 | 0 |
| 2025Q2 | 63,875,083 | 63,875,083 | 0 |
| 2025Q3 | 96,961,795 | 96,961,793 | 2 |
| 2025Q4 | 132,930,016 | 132,930,016 | 0 |
| 2026Q1 | 38,165,648 | 38,165,648 | 0 |

這證明 income rows 是 3M／6M／9M／12M duration，不是四個獨立單季。Q3 差異 2 也證明月營收累計只能作 reconciliation evidence，不能取代正式財報事實；需允許明確、極小且有來源的差異。

## 日期分類決策

| 來源欄位 | 契約欄位 | 狀態 |
|---|---|---|
| 財報期間年度／季別 | fiscal period + derived period_end | 需依 issuer fiscal calendar 驗證 |
| OpenAPI 出表日期 | provider_generated_at | confirmed by cross-row evidence |
| MOPS 歷史 fetch time | fetched_at | confirmed |
| 公司重大訊息發布時間 | announced_at | 需保存正式 document ID |
| 公司財報申報完成時間 | filed_at | 尚未由目前 source 提供 |
| 月營收資料年月 | period | confirmed |
| 月營收出表日期 | provider_generated_at | 現行歷史 rows 尚有錯誤 mapping |

## 公司行動來源

| 來源 | 可提供內容 | 限制 |
|---|---|---|
| MOPS 每日重大訊息 `t187ap04_L` | 當日重大訊息 | 非完整歷史 backfill |
| TWSE 變更股票面額恢復買賣頁 | 面額變更與恢復買賣參考資料 | 需確認 machine-readable endpoint 與歷史 coverage |
| TWSE 除權除息預告 | 除權息事件 | 不能代表面額變更、減資或換股 |
| 公司正式公告／財報 | 事件與 EPS 重編證據 | 文件取得與 parsing 尚未整合 |

TWSE 官方頁：

- [變更股票面額恢復買賣參考價格](https://www.twse.com.tw/zh/announcement/change/twtb8u.html)
- [國巨個股資訊](https://www.twse.com.tw/pdf/ch/2327_ch.pdf)

目前台股 corporate-events contract 只涵蓋除權息與法說會，無法作為完整 share-basis ledger。

## Source precedence 初步規則

1. 同一 filing／period 的公司正式申報 fact。
2. TWSE／TPEx 正式財務資料。
3. OMI 保存的相同官方來源 raw snapshot。
4. 第三方資料只作 discovery 或 reconciliation，不能靜默覆蓋正式來源。

若兩個正式來源不同：

- 保存兩者與 content hash。
- 標記 disputed。
- 由 filing version、known-at、provider-generated-at 與 source document reconciliation。
- 未解決前禁止 decision-ready derived metrics。

## 尚未解決

- OpenAPI financial 金額單位需從官方 schema 或固定 endpoint metadata 建立可測試 mapping。
- 國巨 2025 Q1／H1 EPS 在後續 filing 中是否已追溯重編，需取得 filing-level comparative disclosure。
- Basic／diluted weighted-average shares 尚未進入 OMI。
- 台股公司行動完整歷史資料源與 machine-readable contract 尚未確立。
- 非曆年制發行人的 period_end 推導規則尚未驗證。
