# Plan

## Milestones

1. Baseline、contract inventory 與任務文件
   - Scope：讀取 product/architecture/v3 文件，盤點 schema、query plan、decision envelope、tool policy、MCP、Frontend、external consumers 與 tests。
   - Acceptance：固定 goals、non-goals、trust boundary、compatibility strategy、known defects 與驗證矩陣。
   - Validation：UTF-8 讀回、`git diff --check`、目前 runtime schema/代表性 request 證據。

2. Additive v4 contract 與 capability selection
   - Scope：request schema、supported version、capability registry、selection normalization、query plan、data manifest 與 response builder。
   - Acceptance：v4 可選 capability/field/limit；v2/v3 保持；非法 capability/field 產生 predictable business error。
   - Validation：pure contract tests、query-plan tests、v2/v3/v4 parity tests。

3. Current P0 correctness defects
   - Scope：target/multi-intent、MCP business error、stance/headline invariant、v3/v4 payload projection。
   - Acceptance：截圖中的兩個 FAIL 與兩個主要 WARN 都有 regression；summary/compact 不再保留無界 legacy result。
   - Validation：scope、answer、decision envelope、outward contract、MCP targeted tests。

4. Granular fill actions
   - Scope：capability-to-fill registry、TW dataset 級 refresh operation、US 現有 granular tools 對齊、crypto local-cache/refresh boundary、continuation action selection。
   - Acceptance：單一缺口只計畫/執行單一 capability；action 有 target/window/cost/timeout/write/idempotency metadata。
   - Validation：planner/execution/freshness tests；mocked provider call-count 與 dataset-scope assertions。

5. Realtime evidence semantics
   - Scope：共用 realtime observation contract、session-aware validator、TW/US/crypto projection。
   - Acceptance：current 不等於 live；closed session、delayed、snapshot、stale、provider failure 與 timezone 語意一致。
   - Validation：pure validator tests、market context regressions、唯讀/最小 bounded runtime probes。

6. In-repo consumers and documentation
   - Scope：repo MCP schema/forwarding、Frontend types/request/rendering、`docs/architecture/OmiDecisionContract.md`。
   - Acceptance：consumer 不做市場語意或 Kuro 專用 projection；可選 v4 並妥善 fallback v3。
   - Validation：MCP tests、Frontend lint/typecheck、contract docs diff check。

7. External consumer alignment
   - Scope：`OMI_search` 與 Kuro request/parse path。
   - Acceptance：兩者只選資料並消費 canonical contract；Kuro 的可朗讀稿仍由 Kuro 模型負責。
   - Validation：各自既有 unit/syntax/schema tests與最小 smoke；無法修改時在 `Progress.md` 列為明確剩餘交付。

8. Full validation and runtime handoff
   - Scope：safe backend/frontend profile、HTTP/SSE/MCP、payload bytes、latency、paid API bounded probe。
   - Acceptance：done criteria 全部有證據；未完成項目清楚隔離。
   - Validation：
     - `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs <targeted tests>`
     - `.\scripts\run-safe-validation.ps1 -Profile frontend`
     - `/api/ai/tools`、`/api/ai/ask`、`/api/ai/ask/stream`
     - MCP `initialize`、`tools/list`、`tools/call`

## Stop-and-fix rules

- 任一 v2/v3 compatibility regression 發生時，先修正再擴大 v4。
- 任一 explicit capability/field 被忽略而回傳更大資料面時，停止 consumer rollout。
- 任一 missing/stale capability 仍觸發整包或無界 refresh 時，停止 fill-action rollout。
- 任一 `current/live/snapshot/session` 矛盾或缺 timezone 時，不得宣稱 realtime contract 完成。
- 任一 headline/stance/timeframe invariant 失敗時，不得讓該 answer 進入 decision-ready。
- 任一 HTTP/SSE/MCP business error 被誤標為 transport error或反向情況時，停止 transport rollout。
- 付費 API、外部 refresh 或 LLM 若無 trust、cost budget、timeout、source refs 或 failure telemetry，停止該 live 驗證。
- Dirty worktree 若與本任務檔案重疊，保留既有改動並以 localized patch 共存，不 reset、不覆寫。

## Decisions

- 2026-07-24：一個總出口是單一業務 contract，不是單一巨大 implementation；內部使用 registry、planner、reader、validator、projection 分層。
- 2026-07-24：不建立 Kuro/桌寵/語音專用 response profile。Kuro 模型使用相同 capability-selection contract，朗讀稿由 Kuro 端產生。
- 2026-07-24：consumer 選擇 capability 與資料量；provider/tool 選擇、freshness 與 fill policy由 backend 決定。
- 2026-07-24：v4 採 additive rollout，v2/v3 先保留；舊 `market_data_params` 與 `payload_level` 映射到 v4 selection。
- 2026-07-24：MCP `isError` 只代表 protocol/transport/internal tool failure；structured business rejection 是成功傳輸的 canonical result。
