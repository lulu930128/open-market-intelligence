# 台股技術卡與 Radar 結構訊號強化

## 背景

現有個股技術卡雖顯示 MA5/20/60、RSI、MACD、ADX、量能與籌碼，但主要 headline 只採用價格相對 MA20。當盤中價格已跌破 MA60 時，日線卡仍可能只顯示前一交易日收盤相對 MA20，無法清楚表達「價格結構已先於均線排列惡化」。

Radar 使用另一條 signals pipeline，已涵蓋多項技術訊號，但缺少價格相對 MA60 與穿越 MA60；主訊號依產生順序選取，關鍵壓力也未優先選取最接近現價的可操作價位。此外，盤中覆蓋預算依自選股原始順序套用，後段高風險股票可能無法取得盤中覆蓋。

## 目標

- 讓台股日線技術卡能在使用盤中價格時，明確區分「盤中現價」與「已收盤日線指標」。
- 將 MA60、完整均線結構與關鍵價格結構納入 backend 技術分析。
- 讓 Radar 的訊號、主訊號、因子分數與關鍵位能反映 MA60 結構。
- 在固定盤中查詢預算內，優先覆蓋最需要即時確認的 Radar 候選，而不是依自選股原始順序。
- 維持 Radar 摘要優先與細節折疊，不將所有 raw indicators 平鋪到第一層。

## 非目標

- 不加入自動交易、買賣指令或猜測漲跌。
- 不將專業 K 線所有 frontend-only 指標直接複製到 backend。
- 不做 DB migration、不重建本機資料庫、不啟動無界限全市場 refresh。
- 不改動台股以外市場的技術 contract。

## 硬性限制

- Backend 是技術語意、freshness 與 Radar 判斷的真相來源；frontend 只呈現。
- 盤中價格與已收盤日線指標必須保留各自的時間點與 provisional 說明。
- Radar GET 維持 bounded provider I/O，不因自選股檔數線性擴張盤中請求。
- 保留既有 API 欄位與行為；新增欄位與訊號必須向後相容。
- 不覆寫目前 dirty worktree 中與本任務無關的使用者修改。

## 交付項目

- Backend 日線技術報告的 MA5/20/60 價格位置、均線排列、盤中覆蓋與結構摘要。
- Signal service 的 MA60 靜態位置與穿越訊號。
- Radar 的 MA60 labels、分類、權重、因子、關鍵位與主訊號語意排序。
- Radar 盤中候選選擇由原始順序改為風險/動能優先。
- Frontend 技術卡 metadata/freshness 呈現與 Radar MA60 細節。
- Targeted backend tests 與 frontend lint/typecheck 驗證。

## 完成條件

- 當現價低於 MA60 時，技術卡能直接顯示距離與「失守 MA60」語意。
- 當前一價格在 MA60 上方、最新價格在 MA60 下方時，signals 產生 `cross_below_ma60`。
- Radar 可將 MA60 失守納入 risk/support-break、trend factor 與 technical evidence。
- Radar 風險情境的 key level 使用現價上方最近的合理回收壓力，不再固定取遠端壓力。
- 超過 intraday limit 的自選股，盤中覆蓋候選依完整日線結果排序，而非原始位置。
- 舊 contract 欄位與現有 targeted tests 不產生 regression。
