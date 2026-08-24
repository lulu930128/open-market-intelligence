# M5 Retry Reliability Hardening — 2026-08-24

## 目標

在不降低 M5 live-session gate 的前提下，消除 2026-08-24 暴露的三個可工程化問題：viewer ownership 不可觀察、隱藏頁籤不主動釋放、preflight 太晚才發現 source/runtime blocker。

本計畫只提高準備與診斷可靠度；不以 source test 取代 Preopen／Opening／Regular／Closing Auction live evidence，也不提前宣告 Foundation closure。

## 邊界

- Viewer lease 與 02A dark research lease 維持不同 lifecycle，不把 02A 接入 production。
- 禁止 Account、Order、交易、backfill、repair、DB destructive/write probe 與 raw provider payload/credentials。
- Runtime adoption 只走正式 launcher；不得 broad-kill、不得釋放未知 lease。
- Frontend/MCP 仍是 thin consumer；owner/cleanup truth 由 backend manager 與 preflight contract 提供。

## Milestone 1 — Owner-scoped viewer contract

- Lease 建立明示 `owner_kind=frontend_viewer|acceptance_probe`，舊 client 預設為 `frontend_viewer`。
- Manager heartbeat/release 保留 owner kind。
- 新增 redacted global summary，只暴露 owner kind、symbol、lease/process/worker counts；不暴露 lease ID、credential 或私人 identity。
- API inventory與 manager regression 必須通過。

驗收：可區分外部 frontend lease 與 acceptance probe；summary 中找不到 lease capability token。

## Milestone 2 — Frontend lifecycle cleanup

- `visibilitychange -> hidden` 與 `pagehide` 主動 release。
- `visible`／`pageshow` 才 reacquire，且 acquire/release/heartbeat 序列化，避免 race 形成雙 lease。
- pagehide 使用 bounded keepalive DELETE；失敗時保留 capability token，visible 後先 heartbeat，不立即製造 replacement lease。
- TTL 與 backend idle shutdown 保留為最後防線。

驗收：ESLint、TypeScript、production build 通過；running backend 可將 frontend lease分類為 `frontend_viewer`。

## Milestone 3 — 分段 preflight

1. 07:50 `SourceOnly`：只驗 local date、checkpoint SHA、30/30 target與 harness hashes；runtime相關欄位明示 `not_run`。
2. 08:10 `Prepare`：允許 component-owned compare adoption，驗 runtime/calendar/catalog/frontend/MCP與乾淨 global viewer baseline。
3. 08:20 起進入 active observation／remediation window：先執行 `Check`，再執行單一 `acceptance_probe` readiness lifecycle。可安全修復的 runtime、launcher adoption、idle cleanup、frontend/MCP readiness 或 localized task-owned source/harness 問題，由 automation 現場診斷、修復、重驗並繼續；中間成功重試不打擾使用者。
4. 外部 viewer lease 不得代為 release；改以 08:24／08:28／08:31 的 bounded recheck 等待 owner lifecycle 正常清除。只有 08:31 仍衝突、需要 credential/entitlement/人工作業、source ownership 不明，或修復會跨越安全邊界時才暫停並回報。
5. 08:30 起（最晚 08:31）取得正式 Preopen 當下 evidence；成功後依序 08:58 Opening、09:05 Regular。08:20 readiness 不能替代正式 Preopen gate。

精確 failure code：

- `EXTERNAL_VIEWER_LEASE_PRESENT`：任何 external/global lease 存在；不得 release。
- `BRIDGE_IDLE_CLEANUP_TIMEOUT`：global lease 已為零，但 bridge 未在 bounded idle window 自然退出。
- `OWNED_VIEWER_LEASE_LEAK`：只有本次 acceptance lease 未回到 baseline。
- `VIEWER_BASELINE_PROBE_FAILED`：summary/stream/process probe 本身失敗。

## Milestone 4 — Checkpoint、runtime與明日執行

- Full backend/frontend validation 後才重建 30-target checkpoint。
- 使用新 checkpoint 完成 `SourceOnly` 實測與 component-owned compare adoption。
- 明日 automation 依 dated artifact 判斷 stage；08:20 前的 preparation 與 08:20 起的 remediation 都保存真實 evidence。可修復 failure 必須在同一安全邊界內修復、重驗後自動續排，只有 terminal blocker 才暫停。
- Closing Auction live retest 仍是獨立 blocker；即使三個正式 session gate 通過，也不得直接標記 `runtime-accepted / ready-for-02`。

## 完成條件

- Backend targeted、checkpoint guard、full pytest通過。
- Frontend lint、typecheck、build通過。
- `SourceOnly` artifact證明 runtime surfaces 全為 `not_run`。
- Running compare runtime回傳新 global summary contract。
- 外部 3711 viewer存在時，preflight精確回報 `EXTERNAL_VIEWER_LEASE_PRESENT`，且本次未建立或釋放任何 lease。
- Runbook與 automation更新為 07:50／08:10 preparation、08:20 active observation/remediation、08:30 起正式 Preopen 的 staged flow。
