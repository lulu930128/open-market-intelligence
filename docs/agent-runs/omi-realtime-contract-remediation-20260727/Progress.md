# 進度

最後更新：2026-07-27 22:30 Asia/Taipei

## 目前狀態

- Milestone 1～5：完成。
- Milestone 6：待下一個交易日取得指定時段的實盤證據；不影響本輪 source、regression 與正式 runtime 驗收。
- P0／P1／P2 契約修正已完成；provider 無法提供的資料維持可見限制，不以推算值或綠色狀態掩蓋。
- 本任務未處理使用者已暫緩的 TAIEX Yahoo fallback／rate-limit 問題。
- 未 commit、未 push，並保留既有 dirty worktree。

## 已完成修正

- required unsupported 保留 `unmet_required_capabilities`、missing 與 limitation，並阻擋 `analysis_ready`；optional unsupported 可維持 ready，但仍揭露 limitation。
- `data.freshness` 可由 selected capability／domain／slot 合成，TW／JP／KR 收盤後資料依交易 session 判為 `latest_completed_session`。
- `cache_only` 只讀已保存 intraday，不觸發外部 API；TW／JP／KR 可跨 request 與正式 launcher restart 重播。
- JP／KR 5m 改為 session-aware 的真實 1m→5m OHLCV 聚合。
- TAIEX close contract 分離 last trade、high、official close 候選、13:33 確認、選擇理由與原始／顯示精度。
- TAIEX volume、trade value、VWAP 分開表達 unit、status、semantics 與 provenance；5m request 保留 requested interval，不把 5s source relabel 成 5m。
- compact／standard／full projection 保留必要 quote metadata、top-5 depth、官方收盤狀態與 provider-specific volume。
- ranking 新增 `rank_scope`、requested／ranked universe、full market／full requested universe 與 coverage semantics。
- focused source-health 同時依 target 與 selected resource 判斷 relevance。
- 固定時點新增 13:32／13:34，並新增 TAIEX／TPEX index contract snapshot migration、scheduler、repository 與 replay route。
- JP／KR breadth 維持 partial／coverage limitation；auction unmatched 與 depth order count 在 provider 未提供時維持 `null + not_provided`。

## 驗證證據

### Source 與 regression

- 最終安全驗證：`.\scripts\run-safe-validation.ps1 -Profile backend`。
- 結果：compileall 通過，pytest `1125 passed in 90.42s`。
- Log：`.tmp/validation/20260727-222311`。
- `git diff --check` 通過。

### 正式 launcher runtime

- Launcher PID `6524`，backend runner PID `1660`，frontend runner PID `55836`。
- Listener：backend leaf PID `59860` 於 `127.0.0.1:8400`；frontend leaf PID `61312` 於 `127.0.0.1:3000`。
- Launcher 使用 repo `.venv`，`backend_reload=False`；backend readyz、frontend UI 與 proxy 均成功。
- DB revision：`20260727_0040 (head)`。

### 代表性 HTTP／AI 契約

- TAIEX：正式收盤 `43634.19` 已確認，selection 為 `official_close`；trade value `747647200740` 為 official，volume `8876197` 明確標示 provider-specific、非市場成交金額。
- TAIEX intraday：requested `5m`、source／effective `5s`、status `unsupported`；資料連續、正式收盤發布 gap 被辨識，不製造 missing／quality warning，`analysis_ready=true`。
- required `market.breadth` unsupported：transport completed，但 `analysis_ready=false`、quality blocked，並保留 `required_capability_unsupported`。
- JP `7203.T` cache-only：67 根 5m、`local_ohlcv_1m_to_5m`、`persisted_hit=true`、無外部 fetch。
- KR `005930.KS` cache-only：73 根 5m、`persisted_hit=true`；因資料只到 15:00、未覆蓋 15:30 收盤，正確維持 stale／blocked。
- 排行 group 3：requested／ranked 83、full requested universe true、full market false、market reference 1801、coverage `0.0460855`。
- Index replay：required slots `13:24/13:28/13:30/13:32/13:34`，目前 captured 0、coverage 0、complete false、read-path side effects false。

### MCP 與瀏覽器

- MCP `127.0.0.1:8797`：initialize、`Mcp-Session-Id`、initialized notification、tools/list 六項均成功。
- `omi.ask` 成功案例 `2330`：v4、completed、quality ready；business-error `999999`：transport 成功、`TARGET_NOT_FOUND`。
- 瀏覽器實際開啟 `http://127.0.0.1:3000/`，確認 TW／US／JP／KR／Crypto dashboard、TAIEX 與排行資料可見。
- 瀏覽器 console：11 筆記錄、0 筆 error；驗證後已關閉分頁。

## 已知限制

- 今日 migration／scheduler 建立時已晚於 13:24～13:34，因此 index replay 不能偽造或補寫今日固定時點；需下一交易日自然 capture。
- KR 目前保存資料未覆蓋完整收盤 session，故維持 stale／blocked，不能改成 ready。
- JP／KR breadth provider universe 不足，只能標示 partial／coverage limitation。
- Dashboard 的「補失敗 3」來自本輪正式重啟前的 TPEX market-chip parser 歷史失敗；本輪來源重整只涵蓋 TPEX index replay，未擴張修正該 parser。
