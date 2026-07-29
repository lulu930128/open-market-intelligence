# 計畫

狀態：Milestone 1～5 已完成；Milestone 6 等待下一交易日自然資料。

## Milestone 1：新版 baseline 與任務控制面

- 讀取產品文件、架構邊界、現有 dirty diff 與新版修正清單。
- 在正式 launcher runtime 重現 P0／P1 主要缺口。
- 重寫任務文件與 completion matrix，區分 source、test、runtime、實盤證據。

驗收：

- 每個項目都有 backend owner、測試表面與完成狀態。
- 使用者已暫緩的 Yahoo fallback 問題不混入本次 blocker。

## Milestone 2：P0 readiness、freshness 與 close semantics

1. required unsupported 保留 `unmet_required_capabilities` 並降低 readiness。
2. `data.freshness` 可從 canonical freshness views 合成，不依賴預先存在的 payload。
3. TW／JP／KR completed-session 使用交易日曆判斷。
4. TAIEX close resolution 分離 last trade、summary 與 official close。
5. `cache_only` 不關閉 intraday，並以 `refresh=false` 讀取落地 cache。

驗收：

- 對應 targeted tests 通過。
- 正式 runtime 的五項既有重現均改為預期結果。

## Milestone 3：P1 外部契約完整性

1. volume／interval metadata 經過 projection 與 quality 後仍一致。
2. JP／KR 1m→5m session-aware OHLCV 聚合。
3. quote compact／standard／full 保留正確 depth 欄位。
4. ranking 加入不易誤讀的 additive 欄位。
5. source-health relevance 同時符合 target 與 selected resource。
6. index volume、trade value、VWAP 分開表達。
7. 個股 slots 新增 13:32／13:34；建立 bounded TAIEX／TPEX index capture／replay。

驗收：

- 公開 response 不再裁掉必要 metadata。
- replay 保存候選值、selected candidate、selection reason 與 close status。

## Milestone 4：P2 provider 限制與負向契約

- JP／KR breadth 維持 coverage／reconciliation／partial 語意。
- auction unmatched 與 depth order count 在 provider 未提供時維持 `null + not_provided`。
- 補負向 regression，禁止以推算值填補。

## Milestone 5：整合驗證

- 跑最接近的 targeted tests，失敗即停下修正。
- 跑 `run-safe-validation.ps1 -Profile backend` 與 `git diff --check`。
- 由正式 launcher 重啟後驗證 PID／port owner／readyz。
- 驗證 Backend HTTP、frontend proxy、MCP initialize／tools/list／代表性成功與 business-error call。
- 使用 web／browser 工具驗證需要的本機頁面；不接管桌面。

## Milestone 6：明日實盤驗收

- 08:30～08:59：3105 五檔與 auction null semantics。
- 09:05～09:15：2330、7203.T、005930.KS 的 1m／5m、timezone、partial last bar、cache metadata。
- 11:00：focused intraday source-health relevance。
- 13:24、13:28、13:30、13:32、13:34：TAIEX close handoff 與固定時點 replay。
- 收盤後：`cache_only` replay 與 `latest_completed_session`。

目前限制：

- 今日 index contract migration／scheduler 建立時已晚於固定 slots，不能人工偽造歷史 capture。
- source、regression、正式 launcher、HTTP、frontend proxy、MCP 與 browser 驗收已完成；此 milestone 僅補交易時段證據。

## Stop-and-fix 規則

- required capability 無法滿足卻仍 ready。
- high、last trade 或未確認 summary 被標成 official close。
- `cache_only` 觸發外部 API 或因未 refresh 而回空。
- 5m 只是改名、跨午休／session 聚合，或 volume 語意不允許仍被加總。
- focused request 被未選 resource 的歷史／背景 failure 阻擋。
- 任何修正覆蓋 dirty worktree 內不屬於本任務的變更。
