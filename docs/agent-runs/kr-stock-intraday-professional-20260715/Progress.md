# 進度

## 目前狀態

- 已完成台股、韓股、日股、美股圖表 call chain 比對。
- 已確認根因：韓股 frontend 明確只允許指數使用 `today`，且沒有個股分時 backend route。
- 已確認可沿用 `TechnicalIndicatorMenu`、`ProfessionalChartPanel`、分時聚合與畫線持久化能力。

## 已確認決策

- 韓股個股分時使用 Yahoo chart `1d/1m`，backend 統一處理正常交易時段、cache 與 failure contract。
- 個股成交量以 shares 表示，不沿用韓股指數的 thousand_shares。
- 個股移除手動「更新日 K」；指數更新按鈕保留。
- 專業模式沿用現有共用圖表，不建立韓股專用圖表引擎。

## 已完成

- 新增 `/api/kr-market/stocks/{symbol}/intraday`，使用 Yahoo `1d/1m`、正常交易時段過濾、60 秒 cache 與可見 failure contract。
- 分時 payload 已包含 previous close、OHLC、每分鐘 shares、累計成交量、volume semantics、source、partial 與 warnings。
- 收盤後若 Yahoo 分鐘資料未涵蓋收盤競價，會以同交易日的日線收盤價與總量校準到 15:30，並明示校準來源。
- 韓股個股加入「今日」，並移除個股「更新日 K」；指數更新入口維持不變。
- 一般模式加入分時／歷史圖表技術指標選單。
- 專業模式加入 1m／5m／15m／30m／1h／4h／日／週／月、K 線／折線、技術指標與畫線持久化。
- Dashboard focus mode 已接上，進入專業模式會隱藏市場 tape 與右側資料面板。

## 驗證證據

- `run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_kr_market_data.py`：23 passed，compileall 與 `git diff --check` 通過。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過。
- 隔離副本 `npm run build -- --webpack`：production build 通過。
- Live API `000660.KS`：收盤校準後為 360 個正常盤中 1 分 K，末點 15:30，`volume_unit=shares`、`regular_session_close_source=kr_daily_price`、`is_partial=false`。
- Browser smoke：一般模式可見今日／指標／放大且無更新日 K；專業模式可切換所有 timeframe，1 分 K 實際成圖；無 error overlay 與 console error。

## 剩餘限制

- Yahoo 是韓股個股分時的 bounded fallback/provider；provider 限流或缺點時會顯示 unavailable/partial，不保證交易所等級逐筆即時。
- 本次沒有重啟使用者目前的 `3000/8400` runtime，避免讓 worktree 其他未完成修改一起上線。
