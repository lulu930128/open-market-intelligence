# 台股財務資料契約

## 目的

本契約定義 OMI 如何保存、正規化、推導與公開台股財務資料。它的核心不是「產出一個數字」，而是保證每個數字都有：

- 清楚的來源與文件版本。
- 清楚的期間、日期、單位、幣別與合併範圍。
- 清楚的股數基準與公司行動處理。
- 可重現的公式與 normalization version。
- 明確的 freshness、continuity、semantic validity 與 decision usability。

Backend 是唯一 contract owner。Frontend、MCP、Kuro 與 AI 不得自行重建本契約中的市場／會計邏輯。

## 事實版本模型

### Filing

一份正式申報或來源快照至少要有：

```text
filing_id
stock_id
source_id
source_document_id
source_document_url
filing_kind
fiscal_year
fiscal_quarter
period_end
announced_at
filed_at
provider_generated_at
fetched_at
known_at
content_hash
parser_version
supersedes_filing_id
```

`known_at` 是 point-in-time 查詢可使用該資料的最早可靠時間，不得以 `fetched_at` 回填未知的公告時間。

### Raw statement fact

財務事實採一個 metric 一筆的語意模型：

```text
fact_id
filing_id
stock_id
metric_code
source_label
source_value
source_unit
currency
statement_type
period_kind
period_start
period_end
months_covered
fiscal_year
fiscal_quarter
consolidation_scope
attribution_scope
eps_kind
presentation_role
source_share_basis_id
source_restated
source_restated_status
```

重要欄位：

- `statement_type`：income、balance、cash_flow、equity、per_share。
- `period_kind`：duration 或 instant。
- `presentation_role`：current_period 或 comparative_period。
- `eps_kind`：basic、diluted 或 not_applicable。
- `source_restated_status`：confirmed、not_restated、unknown。

同一歷史期間可以在不同 filing 中被重新表達。不得只保留最新值而失去原始申報版本。

## 日期語意

| 欄位 | 定義 | 可否互相替代 |
|---|---|---|
| `period_start` | duration fact 涵蓋起日 | 不可 |
| `period_end` | 財報期間結束日或 instant fact 日期 | 不可 |
| `announced_at` | 公司正式對外公告時間 | 不可由抓取時間推定 |
| `filed_at` | 向主管機關完成申報時間 | 不可由 provider 出表日期推定 |
| `provider_generated_at` | Provider 產製資料集／報表時間 | 不代表公司公告 |
| `fetched_at` | OMI 取得 payload 的時間 | 只代表本機取得時間 |
| `known_at` | Point-in-time 模式最早可用時間 | 必須來自可靠公告／申報證據 |

現有 TWSE financial OpenAPI 的「出表日期」暫定映射到 `provider_generated_at`。在沒有正式證據前，不得映射到 `released_at` 或 `filed_at`。

## 期間語意

### Duration facts

一般損益與現金流指標通常涵蓋一段期間：

```text
quarter_3m
ytd_3m
ytd_6m
ytd_9m
annual_12m
other_duration
unknown_duration
```

`fiscal_quarter=2` 不等於 `quarter_3m`；來源可能是 `ytd_6m`。

### Instant facts

資產、負債、權益與每股參考淨值是期末狀態：

```text
instant_period_end
```

Instant facts 不得以跨季相減產生「單季資產」或「單季淨值」。

## 單位與幣別

- 原始值必須保存 source unit，不能只保存裸數字。
- MOPS 歷史財報頁目前已確認財務金額標示為「新台幣仟元」；EPS 與每股參考淨值為「元／股」。
- TWSE／TPEx OpenAPI payload 沒有在每列附帶 unit，adapter 必須依 endpoint contract 明確補入 inferred unit，並保存 inference source。
- 正規化可另存 canonical unit，但不得覆蓋 source value／unit。

建議 canonical units：

```text
TWD_thousand
TWD
TWD_per_share
shares
percent
ratio
```

## 公司行動與股數基準

公司行動獨立保存：

```text
action_id
stock_id
action_type
announced_at
record_date
effective_date
old_share_basis
new_share_basis
adjustment_ratio
adjustment_purpose
source_document_id
source_id
status
```

`adjustment_purpose` 至少區分：

- `price_series`
- `per_share_financials`
- `shares_outstanding`
- `informational_only`

現金股利不得產生 `per_share_financials` 或 `shares_outstanding` adjustment factor。

### EPS 追溯調整

IAS 33 要求股份分割／反分割對所表達期間的 basic／diluted EPS 追溯調整。因此正規化前必須判斷：

1. 來源值是否已在該 filing 內追溯重編。
2. 比較期間與當期是否來自同一 filing presentation。
3. 是否有 basic／diluted、加權平均股數或其他 denominator 證據。
4. 公司行動是否只是純比例分割，或同時包含現增、換股、庫藏股、併購等非等比例事件。

`source_restated_status=unknown` 時，不得自動再套 adjustment factor 後宣稱 decision-ready。

參考：

- [IFRS IAS 33](https://www.ifrs.org/issued-standards/list-of-standards/ias-33-earnings-per-share.html/)
- [會計研究發展基金會 IAS 33 問答](https://www.ardf.org.tw/TIFRS-Q%26A/IAS33.pdf)

## 正規化結果

```text
normalized_fact_id
source_fact_id
comparison_basis_id
normalized_value
normalized_unit
adjustment_factor
normalization_status
normalization_version
derived_at
issue_codes
lineage_json
```

`normalization_status`：

```text
normalized
unchanged
blocked
disputed
not_applicable
```

不得只保存 `raw_eps` 與 `adjusted_eps` 卻沒有來源 fact、事件與 normalization version。

## 衍生指標規則

### 單季

- Revenue／profit 等 duration fact 可在相同會計口徑、相同 consolidation scope、相同 unit、連續 YTD 與可比較版本下相減。
- EPS 除上述條件外，還必須確認 denominator comparability。
- 任一前置 fact missing、disputed 或 blocked 時，不輸出單季值。

### TTM

- 必須由四個連續且 decision-usable 的 discrete quarters 建立。
- 不得把 Q1、H1、9M、FY 或任意四個來源列直接相加。
- 輸出必須攜帶四個 input IDs、涵蓋期間與 normalization version。

### ROE／ROA

- Numerator 必須有期間範圍。
- Denominator 優先使用可取得的期初／期末平均權益或資產。
- 必須標示 `period_months` 與 `annualized`。
- 資料不足時可提供明確命名的 legacy ratio，但不得標成標準 ROE／ROA 或用於跨期 ranking。

### PE／PB

Valuation 是 point-in-time snapshot：

```text
valuation_metric
value
price
price_as_of
price_basis
earnings_or_book_value
financial_basis
financial_period_end
known_at
decision_usable
```

PE 不得被保存為沒有價格日期與 EPS basis 的季度常數。

## 品質契約

```json
{
  "freshness": "current",
  "continuity": "complete",
  "semantic_validity": "valid",
  "decision_usable": true,
  "issues": [],
  "source_refs": []
}
```

### 維度

- `freshness`：current、stale、missing、provider_failure、unknown。
- `continuity`：complete、interior_gap、leading_gap、trailing_gap、not_applicable。
- `semantic_validity`：valid、unknown_period、unknown_share_basis、mixed_basis、disputed、not_applicable。
- `decision_usable`：只有前置能力均符合特定用途時為 true。

Latest expected key 存在不能覆蓋 interior gap 或 semantic failure。

## Public envelope

```json
{
  "contract_version": "omi.financial.v1",
  "target": {"market": "TW", "stock_id": "2327"},
  "as_of": "2026-07-30T13:30:00+08:00",
  "mode": "current_comparable",
  "as_reported": {},
  "normalized": {},
  "derived": {},
  "valuation": {},
  "quality": {
    "freshness": "current",
    "continuity": "complete",
    "semantic_validity": "valid",
    "decision_usable": true,
    "issues": []
  },
  "source_refs": []
}
```

查詢模式：

- `as_reported_as_of`：只使用當時已知 filing 與公司行動。
- `current_comparable`：以目前 comparison basis 呈現歷史可比較序列。

兩種模式不得共用未標示的結果。

## 相容演進

- 現有 `eps` 保持 source-reported legacy semantics，不靜默改成單季或 adjusted EPS。
- 新增欄位必須明確命名，如 `source_reported_eps`、`normalized_ytd_eps`、`single_quarter_eps`、`ttm_eps`。
- Legacy API 在遷移期加上 `semantics`、`quality` 與 deprecation metadata。
- AI 與 frontend 優先消費 versioned financial envelope。

## Persistence 與 refresh

- Provider／parser 不擁有 DB transaction。
- Service／job 擁有 upsert、commit、rollback 與 provider-event 記錄。
- GET/read path 不隱性執行全市場 backfill。
- Refresh 必須限定 source、target、period range、timeout、retry 與 request count。
- Backfill 在 production DB 前先以 clone 執行 dry-run、row count、checksum、reconciliation 與 integrity check。

## 核心 invariants

- Raw source value 與 raw payload 可重現。
- 同一 source fact 不會因重跑產生不同 canonical identity。
- Annual duration value 不以四個 YTD 值相加。
- TTM 恰好使用四個連續 discrete quarters。
- Instant facts 不參與 duration subtraction。
- EPS adjustment 不會在已追溯重編值上重複套用。
- Point-in-time 結果不使用 `known_at > as_of` 的資料。
- Semantic validity 失敗時，AI fundamentals 不得為 decision-ready。
