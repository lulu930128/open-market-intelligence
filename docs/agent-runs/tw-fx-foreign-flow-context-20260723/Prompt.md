# 台幣趨勢與外資資金流 Context

## Goal

- 在台股個股右側既有 `OVERNIGHT` 報告加入預設收合的「匯率與外資」列。
- 以 USD/TWD 1／5／20 日趨勢、大盤外資 1／5／20 日金額與個股外資 1／5／20 日股數，產出可檢查的資金流確認／背離狀態。

## Non-goals

- 不把「台幣貶值」寫成外資賣超的單向因果，也不提供匯率或股價預測。
- 不修改既有美股隔夜分數、技術分數或自動交易行為。
- 不新增 provider、資料表、migration、獨立頁面或 GET 隱性 refresh。

## Hard constraints

- Backend 擁有匯率方向、時間窗、外資整併、freshness 與 combined signal；frontend 只呈現 response enum 與數值。
- 使用 canonical `USD-TWD` 日線；缺少時才反向換算 `TWD-USD` 並顯示警告。
- 外資大盤金額使用 `market_chip_daily.foreign_investor_net_value`，個股使用 `institutional_trade_daily` 的外資與外資自營商淨額合計。
- 缺資料、歷史不足與 stale 必須可見，不以 `0` 代替。
- 保留 `/api/market/overnight-impact/{stock_id}` 既有欄位，只新增 optional nested context。
- 保留工作樹現有未提交變更，不做無關清理或格式化。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: FastAPI market service、SQLite cache、Next.js stock detail report、i18n、backend/frontend tests。
- Current known state: 本機已有 `USD-TWD` 日線、`market_chip_daily` 大盤外資金額與 `institutional_trade_daily` 個股外資資料；ADR parity 已在同一個 `OVERNIGHT` 區塊採預設收合呈現。

## Capability contract

| 項目 | 本次契約 |
|---|---|
| Product scope | 所有台股個股的匯率／資金流 context；不是方向預測或交易建議。 |
| Target | `USD-TWD`、TAIEX 大盤外資、目前選定台股 `stock_id`。 |
| Provider | FX 沿用 Yahoo chart best-effort cache；外資沿用 TWSE／TPEx 已保存資料。 |
| Resource | FX daily OHLC close、全市場外資買賣超金額與成交值、個股外資淨買賣股數。 |
| Freshness | FX 超過 72 小時為 stale；大盤與個股外資依各自公布時點推算 expected trade date。 |
| Request bounds | GET 僅讀 cache；FX 最多 80 rows，市場與個股最多組成 20 個交易日視窗。 |
| Persistence | 沿用既有 tables，不寫入、不改 schema。 |
| Failure | 缺值回傳 `partial`／`stale`、`missing`、`warnings`；combined signal 可為 `unknown`。 |
| Transaction | 純 read-only query，不 commit。 |
| Public API | Overnight response 新增 optional `fx_flow_context`，其餘欄位相容。 |
| AI contract | Nested context 加入 overnight evidence passport analysis 與 source refs，不改 score。 |
| Consumer | 右側報告顯示 default-collapsed summary；展開才看 1／5／20 日與資料日期。 |
| Validation | Service/schema tests、overnight regression、frontend lint/type/build、focused E2E。 |

## Deliverables

- 後端 FX/foreign-flow context builder、schema 與 overnight evidence 整合。
- 預設收合 UI、TypeScript type 與 zh-TW/en-US/ja-JP 文案。
- 趨勢、確認／背離、缺值、stale、API 與 UI 回歸測試。

## Done criteria

- 完整資料時，API 能回傳可重算的 1／5／20 日匯率與外資數值及 5 日 combined signal。
- 台幣走弱＋外資流出顯示為「資金流出確認」；反向與背離狀態可區分。
- 缺資料與 stale 不會偽裝成正常數字，且收合列仍可看見狀態。
- 相關 backend、frontend 與 focused browser validation 通過。

## Open questions / assumptions

- 第一版只作背景確認，不納入現有權重；累積樣本與回測後再評估 scoring。
- 20 日資料是背景資訊；5 日是主 signal horizon，避免單日噪音直接變成方向判斷。
