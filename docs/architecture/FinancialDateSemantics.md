# 財務資料日期語意

`financial_metric_quarterly` 的日期欄位必須維持下列分工，避免抓取時間被誤認成公司已發布財報的時間。

- `fiscal_year`、`quarter`、`period`：財務資料所屬會計期間；這是排序與比較財報的主要鍵。
- `released_at`：來源明確提供的發布／出表日期，只有來源真的提供時才填值。
- `filed_at`：來源明確提供的正式申報日期，沒有申報證據時保持 `null`。
- `report_date`：相容舊 caller 的 deprecated alias；若有值，必須等於 `released_at`，不得填入抓取日。
- `raw_fetch_result.fetched_at`：OMI 實際取得來源內容的時間；它只代表抓取時間，不代表發布或申報時間。
- `created_at`、`updated_at`：本機資料列建立與更新時間，不是市場事件日期。

歷史 MOPS 財務報表 endpoint 只帶財報期間、未提供公司發布或申報日期時，`released_at`、`filed_at`、`report_date` 一律保持 `null`。對外回答應顯示財報期間，並把抓取時間標示為資料取得時間，不能稱為財報發布日。

Migration `20260719_0037` 會清除已知由 `mops-financial-metrics-history-v1` 寫入的抓取日；其他 parser 原本能從來源讀到的 `report_date` 會回填到 `released_at`，保留相容性。
