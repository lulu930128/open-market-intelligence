# 實作計畫

## Milestone 1：邊界與契約

- [x] 盤點 quote-depth、選股 hook、launcher 與 provider fallback。
- [x] 依 KGI 官方文件與 2.1.0 wheel 驗證登入、callback、訂閱、退訂、重連事件與欄位。
- [x] 定義 quote-only IPC envelope、lease API 與 additive source-chain 欄位。

驗收：未使用任何 Order / Account / position API；credentials 不出現在 public contract。

## Milestone 2：Provider 與 fallback

- [x] 實作獨立 KGI quote bridge 與 backend process manager。
- [x] 實作 lease ref-count、heartbeat TTL、退訂與 idle shutdown。
- [x] 將有效 KGI event 映射到既有 quote-depth contract。
- [x] 維持 TWSE MIS / DB snapshot fallback，揭露 primary source 狀態。

驗收：KGI disabled / misconfigured / warming / stale / live 都有 deterministic 行為。

## Milestone 3：Frontend 與設定

- [x] 選取個股時 acquire lease，定期 heartbeat，cleanup 時 release。
- [x] 補 `.env.example`、獨立 requirements 與 Windows 安裝腳本。
- [x] 補 README 操作與安全邊界。

驗收：沒有選股時不會啟動 SDK；切換標的後舊訂閱可回收。

## Milestone 4：驗證

- [x] 新增 provider、lease 與 fallback targeted tests。
- [x] 執行 backend targeted pytest / compile。
- [x] 執行 frontend lint / typecheck。
- [x] 執行 `run-safe-validation.ps1` 最小足夠 profile。

失敗規則：驗證失敗先修正；不啟動真實 KGI 登入、不消耗使用者帳號連線額度。

## Milestone 5：KGI Python 3.12 相容 runtime

- [x] 確認 Python 3.13 嚴格 X.509 驗證與 KGI 憑證鏈不相容。
- [x] 安裝腳本只接受 64-bit Python 3.12，並可明確重建舊 `.venv-kgi`。
- [x] Quote bridge 啟動時 fail closed，拒絕錯誤 Python runtime。
- [x] 重建隔離環境後驗證 SDK、TLS 與一次 bounded quote-only 訂閱。

驗收：不使用 `verify=false`、不修改 OMI 主 backend runtime、不存取帳戶／持倉／下單 API。

## 後續 Roadmap

台股即時擴充與美股 KGI 能力評估統一記錄於 [Roadmap.md](./Roadmap.md)。其中尚未實作或尚未經正式環境驗證的能力，不屬於本次已完成範圍。

## Milestone 6：台股成交流 backend contract

- [x] Quote bridge 同時訂閱 All 與 1 分 K，分流 quote／KBar callback。
- [x] Provider manager 建立 bounded recent trades、試撮軌跡、KBar 與五檔衍生值。
- [x] KBar 單獨失敗時回報 capability warning，不中斷即時成交與五檔。

驗收：只在 viewer lease 存在時收集；最後一個 lease 釋放後退訂並清除記憶體資料。

## Milestone 7：Snapshot / SSE API

- [x] 新增 bounded snapshot response model 與 `GET` route。
- [x] 新增 SSE stream；只推送 manager snapshot，不在 read path 建立訂閱或寫 DB。
- [x] 補 dedupe、方向語意、buffer 上限、試撮／正式成交分流與 degraded state tests。

驗收：SSE 斷線不影響既有 quote-depth polling；provider status、warnings 與 freshness 可見。

## Milestone 8：Quote Depth 即時成交版面

- [x] 一般盤右欄顯示近期成交，五檔左欄縮小、成交欄擴大。
- [x] 上方固定使用「即時成交／試撮」切換；試撮欄整合即時 callback 與保存快照。
- [x] 移除右欄下方重複的成交量摘要，維持五檔與目前明細兩個主區塊。
- [x] EventSource 不可用或逾時時使用 bounded snapshot polling fallback。
- [x] 驗證 desktop、窄螢幕、loading、empty、stale、replay 與 provider failure。

驗收：市場語意與 freshness 都來自 backend；UI 不把 `up/down/flat` 說成主動買／賣。

## Milestone 9：試撮合併與 KGI Data bounded fetch

- [x] 保存的早盤、尾盤與延後開收盤試撮快照在同一張明細表依時間合併，不增加第二層切換。
- [x] KGI bridge 新增嚴格白名單 `data_get`，不接受任意 table name，也不暴露 Account／Order。
- [x] 新增單一台股標的明示 POST，支援盤中快照、當日成交明細、歷史分 K 與分價量；限制最多 4 requests、500 records 與 5 天分價量。
- [x] 將 provider `D403` 分類為 `plan_restricted`，讓可用資源與未開通資源能在同一 response 並存。

驗收：一般 quote GET／SSE 不觸發 Data request；bounded fetch 不寫 DB，尚未驗證 schema 的 records 不進 canonical 歷史表。
