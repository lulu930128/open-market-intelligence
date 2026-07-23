# 台灣科技 ADR 台幣隱含價

## Goal

- 在台股個股右側既有 `OVERNIGHT` 報告內，為重要且具有同公司 ADR 的科技股提供美元收盤價、USD/TWD、ADR 轉換比與台幣隱含價。
- 支援 `2330 ↔ TSM`、`2303 ↔ UMC`、`3711 ↔ ASX`、`8150 ↔ IMOS`，並把日期對齊、資料狀態、缺漏與警告留在後端契約。

## Non-goals

- 不把同產業美股或 ETF 偽裝成同公司 ADR。
- 不涵蓋非科技股 ADR，也不提供自動下單、無風險套利或確定開盤價暗示。
- 不新增資料表、migration、獨立頁面或第二套前端換算邏輯。

## Hard constraints

- 後端擁有 ADR 比率、匯率方向、交易日對齊、公式與 freshness；前端只呈現 response。
- 使用未調整日線收盤價 `close_price`，公式固定為 `ADR USD × USD/TWD ÷ 每 ADR 對應台股股數`。
- 以 ADR 交易日當日或之前的最新台股收盤價作為隔夜參考，下一個台股交易日只作為觀察時段。
- 缺少 ADR、匯率或台股參考價時回傳 `partial` / `missing` 與明確欄位，不以 `0` 代替。
- 維持 `/api/market/overnight-impact/{stock_id}` 既有欄位相容，只新增可選的 `adr_parity`。
- 保留工作樹中既有未提交變更，不做無關重構、格式化或 dependency upgrade。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: FastAPI market service、SQLite market cache、Next.js stock detail report、i18n、backend/frontend tests。
- Current known state: `OVERNIGHT` 已呈現美股隔夜加權因子與 `TSM` 日漲跌；`resource_quote_snapshot` 已有 canonical `USD-TWD`，但尚未建立同公司 ADR 對照與台幣隱含價契約。

## Capability contract

| 項目 | 本次契約 |
|---|---|
| Product scope | 台股主線的隔夜 context；是價格映射參考，不是交易建議。 |
| Target | TWSE 普通股 `2330`、`2303`、`3711`、`8150`；對應 NYSE ADR `TSM`、`UMC`、`ASX`、Nasdaq ADR `IMOS`。 |
| Provider | ADR 日線沿用現有 US market provider/cache；FX 沿用 resource market cache 的 `USD-TWD`，不新增 key 或付費依賴。 |
| Resource | ADR raw close（USD/ADR）、USD/TWD（TWD/USD）、台股 raw close（TWD/share）、靜態 ADR ratio。 |
| Freshness | ADR 以現有 expected US trade date 判斷；台股 reference date 必須不晚於 ADR trade date；FX 顯示 as-of 並標記超過 72 小時的 stale。 |
| Request bounds | 既有 GET 最多刷新 8 個 US symbols；直接 ADR 必須列入 bounded refresh，FX 只讀 cache。 |
| Persistence | 沿用 `us_daily_price`、`market_daily_price`、`resource_quote_snapshot`；不改 schema。ADR mapping 為 versioned code registry。 |
| Failure | 非映射股票為 not-applicable（`adr_parity=null`）；缺資料回傳 nested `status`、`missing`、`warnings`。 |
| Transaction | 本次計算只讀 cache；既有 US refresh service 負責 transaction。 |
| Public API | `GET /api/market/overnight-impact/{stock_id}` 新增 optional `adr_parity`，其餘欄位不變。 |
| AI contract | Nested parity 進入既有 overnight evidence payload；附 source refs、日期與 warnings，不擴大 raw payload。 |
| Consumer | Stock detail `OvernightImpactPanel` 顯示 compact parity strip；缺值時降級顯示資料狀態。 |
| Validation | Pure/service tests 驗證 mapping、公式、日期與缺值；schema regression；frontend lint/type/build 與 focused e2e/DOM assertion。 |

## Deliverables

- ADR registry 與後端 parity builder。
- Overnight API nested schema、freshness 掃描與 evidence 整合。
- 右側報告的台幣隱含價呈現、frontend type 與三語文案。
- 針對 mapping、公式、raw close、日期對齊、缺值與 UI 的回歸測試。

## Done criteria

- 四個支援標的都能取得正確 ADR symbol 與 ratio；其他股票不顯示錯誤對照。
- 完整資料時能輸出可重算的 ADR 美元價、USD/TWD、台股參考價、台幣隱含價與價差百分比。
- 缺 FX/ADR/TW reference 不產生假數字；stale 與 session timing 可見。
- 相關 backend tests 與 frontend compile/lint/build 通過，focused UI assertion 可確認 parity strip。

## Open questions / assumptions

- v1 使用目前資料源的 cache-only USD/TWD；若未來要即時盤中追蹤，再獨立設計 bounded FX refresh，而不讓股票 GET 隱性觸發額外 provider。
- ADR ratio 屬低頻但可變的公司行動契約；本次以明確 source URL 與 verified date 管理，未自動抓 filing。
