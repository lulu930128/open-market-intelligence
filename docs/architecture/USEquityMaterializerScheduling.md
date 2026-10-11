# US equity materializer 的有界選取

## Owner 與啟用範圍

`backend/app/jobs/us_intraday_materializer_scheduler.py` 擁有 recurring equity
選取；仍呼叫原 `materialize_us_intraday_capability`、`USIntradayMarketPlatform`
及 Shared Gateway。沒有新增 Provider、Service、manager、job 或 GET acquisition。
Index、bootstrap、completed-session reconciliation 不屬於這個 equity budget。

`enable_us_dynamic_equity_materializer_universe` 是唯一 opt-in，source default
仍為 `false`。關閉時維持既有 active／canary 行為，不讀 holdings／watchlist。
開啟時，既有四個 active／canary quote／intraday jobs 都成為同一個 selection
窗口的觸發來源，結果統一記錄於既有 `equity_active` materializer lane。
原 index lane、profile、Shared Gateway persistence 及 cache-only publisher 沿用。

## 資格、優先權與公平性

- Viewer：有效 lease，依 normalized symbol 穩定排序後輪轉，不依 heartbeat
  新舊反覆搶佔第一位。最晚下一個選取窗口才納入新 viewer／移除過期 viewer。
- Explicit：既有 `scheduler_us_active_equity_materializer_symbols` 的合法 symbols，
  保持設定順序並獨立輪轉，不再接到 watchlist 尾端。
- 持倉：`market == US`、`is_active`、有限且非零 quantity；負 quantity 仍是
  exposure。保持 id 順序。
- Watchlist：只取 enabled rows，保持 priority／id 順序。不同 group 的相同 symbol 去重。
- Canary：沿用既有 configured symbols。股票／ETF token 必須合法；index alias
  及 malformed token 不得變成 equity acquisition。

Primary owner 優先權是 viewer > explicit > portfolio > watchlist > canary。
前四者是互斥 universe；canary 額外保留可重疊的健康探針角色。同一 symbol 即使
同時有 viewer、持倉、watchlist、canary，也只在同窗口每個 capability 收集一次。

Capacity 為 2 時，先保留一格給 viewer 的 round robin；另一格以
`explicit, portfolio, portfolio, watchlist, canary` weighted round robin 選取。
Explicit 為空時維持原 `portfolio, portfolio, watchlist, canary` 順序。空來源直接
略過；批次內已選 symbol 不再選。沒有 viewer 時兩格均可給背景；沒有背景時
兩格均可給 viewer。Canary turn 可選到同時屬於 watchlist 的 symbol，保留其
primary owner 並標示 canary probe，不因 watchlist 很大而失去探針機會。

若原本任一 equity lane 的 `max_symbols` 或 `max_external_calls` 小於 2，
共同 capacity 隨之降低。Capacity 為 1 且背景非空時，viewer 與背景交替窗口，
各來源內繼續輪轉。這是有界公平的優先權，不是嚴格耗盡高優先來源才准許背景。

## 固定窗口與 reservation

同一 scheduler process 的全部 recurring equity jobs 合計：

- 每個至少相隔 60 秒的選取窗口至多 2 distinct symbols。
- 初始化時同時為 quote 與 intraday 預留，合計至多 4 external-call reservations。
- 每 symbol／capability 至多一次 materializer dispatch，`max_provider_calls=1`；
  不使用原先每檔最多兩個 provider 的 fallback headroom。
- 同窗口第二個 capability 使用相同 target pool，不推進 cursor，也不延長截止。
  `Quote@0, Bars@35, Quote@60` 會於 60 秒選下一批。
- 窗口到期可直接重選，即使另一 capability 從未觸發。未用 reservation 到期
  作廢，不退還、不補抓、不累積 queue；`Quote@0, Quote@61` 不會卡住舊批次。
- IO error、unknown accounting 或 cache noop 都不退款。共同 nonblocking lock
  保護整個 equity dispatch；既有 active lane lock 仍保留，index 不共用此鎖。
- Monotonic clock 保護窗口不受 wall-clock 校時影響。Process restart 清除 cursor，
  啟動後先等 60 秒才容許新 reservation；不聲稱有 durable 或跨 process quota。

Reservation 是 admission 上限，不是任意 sliding 60 秒內實際 HTTP 完成數的量測。
Provider 延遲可能跨窗口；G5 必須驗證正式 call accounting、單 runtime owner
與 quota。此 gate 不啟用、不修改 `.env`，也不以 source 測試聲稱 quota live accepted。

長期 state 至多保存五個來源 cursor、一個背景 cursor、兩個 selected symbols、
兩個 capability consumed flags 與 counts。每窗口會暫時讀取符合資格的 account
intent rows，記憶體／查詢成本隨 universe 大小增加，但不建立無界待執行 queue。

## Status 與延遲限制

既有 materializer runtime summary 的 `runs_by_lane.equity_active.<capability>`
保留 additive `selection`：capacity、symbols、primary sources、canary probe
symbols、eligible／deferred counts、原因、window reservation 與 process scope。
`count_semantics=exclusive_priority_owner_except_overlapping_canary_role` 表示
viewer 擁有的 symbol 不再列入 portfolio／watchlist denominator；canary role
可重疊，所以不同 source 的 counts 不能直接相加當 distinct total。
`deferred_reason=bounded_priority_round_robin_capacity` 表示未被本窗口選入，
不是 provider failure。既有 market-data success／partial／freshness 語意不變。

每個 lane／capability 的最後一筆 run 另保留至多兩檔 `symbol_runs`，不累積歷史。
只投影 symbol、status、固定 reason／postcondition codes、attempted、persisted、
external_calls、registered selected provider、resolved_status、cache_satisfied、facts_usable。
Exception 分支只揭露白名單 class identifier 與固定 failure_stage；不留 message、
raw payload、URL、token、帳戶欄位或任意 exception class 名稱。缺少 accounting
就省略欄位，不推定 persisted=false；provider 指 resolved selected provider，
不代表失敗請求的 provider。GET 只複製記憶體診斷，不查 DB、不 acquisition。

在來源 membership／排序穩定、兩個 capability 都正常觸發、沒有 lock contention、
沒有長 IO，且每 60 秒建立新批次的條件下，capacity=2 的保守**選取／嘗試**上限：

| 來源 | 最多等待窗口數 | 範例 |
| --- | --- | --- |
| V 個 viewers | V | 3 viewers 各至多約 180 秒一輪，不是全部 1m |
| H 個持倉 | 4H（保守界；每四背景 turn 有兩個持倉 turn） | H 隨實際資格而定 |
| W 個 watchlist primary symbols | 4W | W=376 時 1504 分鐘，即 25 小時 4 分鐘 acquisition-window time |
| C 個 canary probe symbols | 4C | C=2 時至多約 8 分鐘，重疊角色可能更早滿足 |

上表是 explicit 為空的既有界線。Explicit 非空時，背景週期為五個 turn，
E 個 explicit 的保守界為 5E，持倉／watchlist／canary 分別為 5H／5W／5C。
因此單一 explicit AMD、長期 viewer 佔一格、持倉、374 檔 watchlist 與 canary
皆存在時，AMD 在任意起始背景 phase 至多五個可用窗口入選。Capacity=1
仍交替 viewer／背景，各背景界乘二；初始 explicit turn 的 AMD 在第二窗口入選，
任意 phase 最差為十窗口。多個 explicit 按 E 線性有界，不承諾任意 E 皆六窗口。

只有 viewer＋watchlist 時，空持倉／canary turn 被略過，W=376 的保守輪轉為
376 分鐘（6 小時 16 分鐘）。Capacity=1 且有 viewer 時，背景與 viewer bounds
再乘 2。若實際批次週期為 Δ，以上窗口數乘 Δ；休市時間不計入 acquisition
時間。G0 的 379 rows／376 distinct 是使用者提供的正式資料證據，本 gate 僅以
隔離 fixture 驗證對應規模，未讀正式 DB。

上述不是成功刷新或 freshness SLO。休市、缺少某 capability callback、持續
provider failure、長時間鎖競爭、頻繁重啟或持續改動 universe 時，成功資料刷新
沒有有限 wall-clock 上限。不得據此宣稱所有 watchlist／viewer 每分鐘都會更新。
