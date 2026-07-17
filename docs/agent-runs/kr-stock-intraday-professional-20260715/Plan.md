# 實作計畫

## 里程碑 1：資料契約

- 新增韓股個股分時解析器與 service cache。
- 新增 `/api/kr-market/stocks/{symbol}/intraday`。
- 補 previous close、volume semantics、partial/warning 欄位與 tests。

驗收：targeted backend tests 與 schema validation 通過。

## 里程碑 2：一般圖表

- 個股 timeframe 加入「今日」。
- 串接個股分時 API 與 session-aware polling。
- 移除個股「更新日 K」，保留指數更新能力。
- 串接技術指標選單。

驗收：typecheck、lint 通過，個股 normal chart 可切換今日與歷史 timeframe。

## 里程碑 3：專業模式

- 接上共用 ProfessionalChartPanel。
- 支援 1m／5m／15m／30m／1h／4h／日／週／月。
- 支援指標參數、畫線與 dashboard focus mode。

驗收：build 通過，browser smoke 確認控制與版面。

## Stop-and-fix

- 若 provider payload 與預期 schema 不符，先保留 warning/empty contract，不在 frontend 猜資料。
- 若共用圖表修改會影響台股，改採韓股局部 wiring。
- 若現有 unrelated dirty changes 導致驗證失敗，先隔離並清楚記錄，不回退他人修改。
