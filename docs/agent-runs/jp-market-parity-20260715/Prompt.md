# 日股市場對齊台股研究工作台

## Goal

- 將日股整理成可長期維護的跨市場研究 context layer，版面與操作節奏以台股為基準。
- 先建立可信的日本交易日、資料新鮮度、bounded refresh、source health 與更新狀態契約，再擴充市場總覽、個股證據、AI／MCP 與前端呈現。
- 讓使用者、Frontend、OMI AI、MCP 與其他 consumer 對同一筆日股資料使用一致的 `as_of`、freshness、provider、missing／partial／stale 語意。

## Non-goals

- 不將日股提升為與台股同等的產品核心；日股仍服務台股研究與使用者的日股觀察需求。
- 不設計自動交易、下單或價格漲跌保證。
- 不隱藏 J-Quants entitlement、Yahoo best-effort、休市、stale、partial、missing 或 provider failure。
- 不在 Frontend、MCP 或 Kuro 重做市場交易日、freshness、refresh 與 AI decision logic。
- 不執行無邊界的全市場外部回補，不購買或假設不存在的資料授權。
- 不重構與本任務無關的韓股、加密、資源市場或共用圖表程式。

## Hard constraints

- 台股版面是資訊架構、掃描節奏與狀態語意的基準，但日本市場特有的交易時段、休市日、資料頻率與 provider 限制必須保留。
- Backend 是市場資料、freshness、source health、bounded refresh、AI evidence 與 slot status 的唯一真相來源。
- Read path 不得因為顯示畫面而啟動無限制、長時間或高 quota 的全市場抓取；需要更新時走 bounded refresh 或明確 job。
- `data/open_market_intelligence.db` 不得刪除、重建或用臨時 schema drift 修改；新增持久化資料必須使用 migration。
- 保留現有 public route 與 response compatibility；新增欄位優先採可選、向後相容設計。
- 共用或重疊檔案已有其他未提交變更時，必須保留既有 diff，只做日股所需的局部修改。
- 免費／公開來源只能標成 third-party 或 best-effort；沒有授權的功能必須回傳 `blocked`、`missing`、`planned` 或 `partial`，不得顯示成完整可用。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: Backend、Frontend、SQLite、Job scheduler、OMI AI、MCP、provider source health。
- Runtime baseline: Backend `127.0.0.1:8400`、Frontend `127.0.0.1:3000`。
- Current known state:
  - 個股 `8035.T` 已可取得 2026-07-15 Yahoo 1 分鐘盤中資料與當日日線。
  - `^N225` 與 `1306.T` 本機日線停在 2026-06-19，但現有 OHLC backfill 因 K 棒數量足夠而不更新。
  - 日股 source health 預設為 `availability_only`；日本交易所休市日尚未建模。
  - 日股 AI context 仍是 local-cache 日線；intraday slot 與 JP-specific decision adapter 尚未完成。
  - 有效日股 master 4,456 檔、自選股 120 檔；基本面 12 檔、信用交易 0 檔、投資人別 0 筆、disclosures 尚未實作。
  - 本機 core scheduler 與 JP scheduler 目前均關閉。
  - Worktree 同時存在其他市場的未提交變更，本任務必須局部共存。

## Deliverables

- 日本交易日與 session/release-window backend contract，Frontend 只讀 backend 狀態。
- 以 expected trading date 為基準的日股 source health、index freshness、watchlist freshness 與 bounded refresh。
- 不會因「舊 K 棒數量足夠」或「整批資料同步落後」而誤判 current 的更新策略。
- JP intraday 加入 AI／REST／MCP market payload contract，包含 bounded request controls、slot completeness、as-of 與 evidence passport。
- 日股市場總覽 backend contract：指數、可計算的市場廣度、產業強弱、coverage、provider/source health 與限制。
- 依台股 dashboard pattern 整理日股 sidebar、market tape、ranking、detail、今日／日週月、資料 slot 與更新狀態。
- 改善基本面、信用、投資人別、揭露與標的生命週期；不能取得的項目保留清楚的 entitlement／coverage 狀態。
- Targeted backend/frontend tests、API smoke、safe validation 與 browser screenshot evidence。

## Done criteria

- 日本休市日不會被當成交易日，也不會在休市日錯誤輪詢或把前一交易日標成 stale。
- `^N225`、TOPIX context 與 watchlist freshness 以 backend expected date 判定；stale 指數能觸發 bounded refresh，失敗時仍顯示 cached/stale 與原因。
- 日股 AI／MCP 在明確要求盤中時能取得 JP intraday，並在 payload 中正確標示 realtime、as-of、source、point count 與缺口。
- 市場總覽明確區分全市場、local coverage、watchlist coverage 與 proxy，不把 `1306.T` 偽裝成正式 TOPIX 指數。
- 日股主要畫面在 desktop 下和台股維持一致的資訊層級、控制位置與狀態節奏，且沒有重複外露錯誤框、文字遮擋或圖表崩壞。
- Backend targeted regression、Frontend lint/typecheck/build 與必要 browser smoke 通過；若 provider entitlement 仍阻擋，驗證必須證明 UI/API 顯示正確限制而非假資料。

## Open questions / assumptions

- 先以現有 Yahoo、JPX 與 J-Quants provider 能力完成可驗證的最大覆蓋；外部官方資料若沒有穩定公開 API，使用 partial/planned slot 而不是脆弱 scraping。
- 市場廣度與產業強弱先以本機已覆蓋標的計算並暴露 coverage denominator；後續取得全市場每日資料後可無痛升級。
- 分鐘線持久化若需要新表，會在 freshness、AI contract 與 overview 完成後，以 migration 與 bounded retention 實作。
