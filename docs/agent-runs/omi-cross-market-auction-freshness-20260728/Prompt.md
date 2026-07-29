# OMI 跨市場、尾盤試撮與 Freshness 收斂

## 任務目標

依 `OMI_綜合修改單_跨市場_尾盤試撮_2026-07-28.txt`，以 backend 作為唯一真相來源，收斂台股尾盤試撮、跨市場成交量、market scope、合法市場事件與 freshness／realtime 契約，並用 focused regression、safe validation 與 bounded runtime smoke 驗證對外 `omi.decision.v4` 行為。

## 範圍

- P0：
  - closing auction 的最後成交、委託簿快照與 indicative match 語意分離。
  - `require_live` 不得把歷史收盤或 fallback 當成 current-session live fact。
  - Crypto OHLCV 對外升冪、latest point 與 event time 一致。
  - TXF 分 K 保留每分鐘成交口數及單位。
  - explicit US／JP／KR `market` target 保留 market scope，代表指數只能作補充證據。
  - KR 合法交易暫停可被 continuity contract 辨識，不冒充 provider missing interval。
  - current request observation、capability、dataset、background health 使用固定 freshness authority。
- P1：
  - 跨市場 volume metadata、latest completed session、canonical `data.freshness`、breadth、TPEX 與 selection contract 收斂。
- P2：
  - 日韓官方 refresh、Crypto persistence、完整 market breadth、resource／TXF aliases、市場事件 registry 與 timezone 正規化。

## 非目標

- 不自動下單，不輸出猜漲跌式交易指令。
- 不在 frontend、MCP 或 Kuro 複製市場、session、freshness 或 quality 判斷。
- 不隱藏 stale、delayed、partial、missing、fallback 或 provider failure。
- 不以單一代表指數冒充完整市場，也不以本地小樣本冒充全市場 breadth。
- 不執行無邊界全市場 refresh、昂貴 external backfill 或 DB 重建。
- 本輪不 commit、不 push，除非使用者另行明確要求。

## 硬性限制

- 所有 public contract 變更採 additive、consumer-safe；既有欄位若需修正語意，保留相容欄位並增加明確狀態與 provenance。
- `last_trade_time` 只表示成交事件；snapshot／auction book／indicative match 使用各自時間與 availability。
- `require_live` 未滿足時必須降低 readiness，歷史 fallback 僅能作明確標記的參考資料。
- current request 成功觀測優先於舊 background source health；預期延遲不得重複標成 stale／missing。
- DB 讀寫、provider refresh 與 transaction owner 維持既有 backend 架構邊界。
- 保留並共存於目前大型 dirty worktree，不覆蓋或回退無關變更。

## Dirty worktree 基線

- 分支：`codex-kr-market-readiness`
- 基線 HEAD：`eb0423d`
- 建立任務時：84 個 tracked 修改、15 個 untracked 項目。
- tracked diff：約 9,093 行新增、432 行刪除。
- 本任務只對修改票直接相關檔案做增量修改；交付時重新列出完整 status 與本任務 touched files。

## 完成定義

1. 所有 P0 case 具有先失敗後通過的 focused regression。
2. public v4 payload 能區分 last trade、auction book snapshot、indicative match 與 fallback。
3. Crypto、TXF、market scope、KR halt 與 freshness authority 的代表性 payload 符合修改單驗收條件。
4. targeted tests、相關 safe backend profile、`git diff --check` 通過。
5. 正式 runtime 經 health、代表性 HTTP／AI contract smoke 驗證；若盤中時段或 provider 限制阻擋，保留可重播 fixture 與待實盤驗收項目。
6. `Progress.md` 記錄實際命令、結果、已知限制與下一個 milestone。
