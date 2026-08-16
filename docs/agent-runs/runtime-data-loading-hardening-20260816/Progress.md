# Progress

## Status

- Current phase: completed
- Last updated: 2026-08-16 14:31 +08:00

## Completed

- 追查 launcher、Frontend proxy、indicator、Radar snapshot、SQLite pool/lock 與區域市場背景載入路徑。
- 確認主要斷線根因是 Windows 將 `8400` 納入 TCP excluded range `8344-8443`；Backend bind `WinError 10013` 後 crash-loop 停止，但舊 Frontend 仍存活並持續 proxy 到失效的 Backend。
- 將 Uvicorn bind failure 從一般 crash 分類為 runner exit code `78`，避免在同一個無效 port 重試。
- Launcher 收到 exit `78` 時會 boundedly 重選 Backend port、同步 proxy environment、停止舊 Frontend 並重新啟動 Backend/Frontend；最多嘗試 3 次。
- 將 K 線 moving-average 交易日缺口判定改為一次預算 prefix，所有 MA 與 volume MA 重用同一份 continuity evidence。
- 將 US daily OHLC 與 intraday provider I/O 移出 caller SQLite connection 持有期間，避免 provider 等待佔滿 pool。
- 將 US/JP/KR market tape polling 改為 cache-first，不再從輪詢 read path 隱性觸發 history refresh。
- 移除非當前市場的 US ranking preload 自動 provider refresh；仍預載快取，只有使用者真正切到美股且資料過期時才執行 bounded refresh。
- 正式重啟 launcher 並採用新程式；preflight 避開 `8400`，實際 Backend 改用 `127.0.0.1:8544`，Frontend 維持 `127.0.0.1:3000`。

## Validation evidence

- `test_technical_parameters.py`: 14 passed。
- 2330 indicator read-only benchmark：240 rows best 0.0840 秒、median 0.1008 秒；1000 rows best 0.3309 秒、median 0.3352 秒。修正前分別約 4.643 秒與 18.179 秒。
- PowerShell AST：`omi-launcher.ps1`、`run-service-logged.ps1` 均通過。
- `test_runtime_launcher_recovery.py`: 2 passed；isolated Uvicorn bind failure 只啟動一次 child 並回傳 `78`。
- `test_database_contention_boundaries.py`: 4 passed；`pool_size=1` 下 provider wait 期間第二個 Session 仍可取得 connection，並鎖定 cache-first polling / inactive preload contract。
- US OHLC / intraday targeted regression：21 passed，50 deselected。
- Backend safe validation：124 passed；log 在 `.tmp/validation/20260816-141548`。
- Frontend safe validation：lint、TypeScript、`git diff --check` 通過；log 在 `.tmp/validation/20260816-142635`。
- 正式 runtime live probes：readyz 200 / 179.5 ms、OHLC 200 / 19.6 ms、indicator 200 / 164.5 ms、Radar snapshot 200 / 134.5 ms。
- Fresh in-app browser tab：K 線 2600 根、Radar 20 筆、自選股 132 檔完整載入；斷線 banner 0、API 500 0、console warning/error 0。
- 新 runtime 啟動後 log：Backend error matches 0、Frontend error matches 0；重載台股頁後沒有新增 off-market US refresh job。

## Decisions made

- bind failure 必須由 child runtime 明確分類，不能只依賴啟動前 port probe，因為 probe 與 bind 之間仍可能發生 race。
- Calendar-aware gap 判定維持 Backend canonical semantics，但不可在每個 MA window 重複掃描。
- 自動輪詢與非當前市場 preload 必須 cache-first；provider refresh ownership 留給 active-market freshness policy、scheduler 或明確操作。
- 跨市場個股 context refresh 保留：它有 Backend freshness decision、單檔上限與 120 秒 runtime 邊界；此次 live refresh 實際約 1.35 秒完成。

## Known issues / risks

- Worktree 原本已有大量其他工作中的變更；本任務只做局部修改，沒有 revert、commit 或 push。
- 「更新狀態」仍可能顯示獨立的 provider 資料補齊失敗（例如 TDCC 憑證驗證）；它會保持可見，不應與 Backend 連線或 Radar/K 線載入回歸混為一談。
- 真實 post-start bind race 不宜在正式 runtime 人為製造；已用 isolated runner regression 驗證 exit `78`，並用正式啟動驗證 excluded-range preflight 與 proxy adoption。

## Next step

- 無必要修正。建議保留 launcher 運行，觀察下一個交易時段的 provider/source-health 告警；若要處理「更新狀態」中的資料源失敗，應另開 provider freshness 任務逐項修復。
