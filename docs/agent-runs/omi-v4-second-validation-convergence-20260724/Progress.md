# Progress

## Status

- Current phase：completed
- Last updated：2026-07-24 Asia/Taipei
- Milestones 1–6：implementation、regressions 與 isolated runtime validation
  已完成

## Completed

- 建立 `Prompt.md`、`Plan.md` 與本進度紀錄，固定第二輪 12 項問題、非目標、
  consumer boundary、驗收條件與 stop-and-fix 規則。
- Multi-domain answer：
  - answer profile 由 selected capabilities／requested domains 決定。
  - broker primary intent 的複合查詢改用 `multi_domain_stock_summary`。
  - brief 可同時摘要價格、技術、法人／融資券、分點與資料限制。
- Ownership 與 selected freshness：
  - `ownership.distribution` 正規化為 capability-shaped object。
  - semantic-empty payload 不再標 ready 或 facts usable。
  - 未選取的基本面／跨市場缺口移至
    `limitations.supplemental_context_gaps`，不影響 selected quality。
- US intraday：
  - 相同 tool step 會合併 requested capabilities。
  - market open 不再誤判 completed session。
  - 有 provenance、temporal evidence、continuity 與 volume unit 的 stale bars
    可作 facts，但不可作即時 decision。
  - legacy `market_data_params.intraday_limit` 只在沒有 explicit selection limit
    時映射至 canonical limit。
- Source Health：
  - 分離 total／matched／returned entry 與 problem counts。
  - snapshot 依一小時／二十四小時 TTL 判 current、stale、expired。
  - budget 壓力下依 20 problem sample、5 problem sample、summary only 逐級降級。
- Passport 與 response budget：
  - consumer-facing trust 由 selected capability quality 聚合。
  - producer 原始 trust 保留在 `upstream_source_trust`。
  - 已解決的 `status_sources_disagree` 不進一般 limitations warnings。
  - 32 KiB brief 先裁 execution/debug，再保留 capability-aware evidence summary。
- 更新 `docs/architecture/OmiDecisionContract.md`，記錄 selected trust、
  supplemental gaps、Source Health TTL／降級與 brief projection priority。

## Validation evidence

- P0 targeted：
  - `81 passed, 14 subtests passed`
- US intraday targeted：
  - `66 passed, 14 subtests passed`
- Source Health targeted：
  - `73 passed, 27 subtests passed`
- Decision envelope：
  - `27 passed, 4 subtests passed`
- Answer／capability／realtime／ask／Source Health adjacent：
  - `91 passed, 23 subtests passed`
- Public v4／outward／tool boundary／intraday：
  - 首次 `49 passed, 2 subtests passed`，1 個預期 SHA snapshot 過期。
  - 核對 tool name 與 v4 schema change 後更新 catalog SHA；精準重跑 `2 passed`。
- Freshness／projection／MCP：
  - `109 passed, 2 subtests passed`
- `decision_envelope_v4.py` compile：通過。
- `git diff --check`：目前無 whitespace error；只有既有 Windows LF/CRLF
  conversion warnings。
- Safe backend profile：
  - 第一次：`1011 passed, 1 failed`；failure 為 Yahoo adapter 已新增
    `resource="daily_price"`，舊 mock signature 未同步。
  - 核對 provider wrapper 後更新測試期待，精準重跑 `1 passed`。
  - 最終兩次完整 backend：`1012 passed`；compileall 與
    `git diff --check` 均通過。
  - 最終 log：`.tmp/validation/20260725-002530/`。
- Isolated runtime：
  - URL：`http://127.0.0.1:18400`
  - Python：`C:\project\Open Market Intelligence\.venv\Scripts\python.exe`
  - Project root：`C:\project\Open Market Intelligence`
  - 最終 PID：53812；驗證後 graceful shutdown，18400 已無 listener。
- Live v4 smoke：
  - `/api/ai/tools` 只暴露 `omi.ask`、只接受 `omi.decision.v4`，registry
    `omi.capability.registry.v1` 共 38 capabilities。
  - 2330 multi-domain 32 KiB：`answer.style=multi_domain_stock_summary`；
    9 個 selected evidence keys 全保留，raw body 30,728 bytes，
    `omitted_capabilities=[]`、`budget_met=true`；未選月營收只在
    supplemental gaps，不進 answer data limits。
  - AAPL bounded external smoke：最多 1 call／1 external fetch／10 秒；
    tool success，63 點中回 30 點，`bar_limit=30`、`truncated=true`；
    stale bars 為 `facts_usable=true`、`decision_usable=false`；
    reconciliation attempted 且無 remaining fill action。
  - Source Health 131 KiB：pre-projection 193,407 bytes，降為 19,868 bytes；
    保留 summary + 20 problem sample，沒有 capability omission；sample 後
    entry/problem/status/market returned counts 均為 20。
  - Quote consistency：Quality 與 Passport quote 都是 ready／facts usable，
    trust scope 為 selected capabilities；一般 warnings 不含
    `status_sources_disagree`。
  - Structured rejection：不存在的 `999999` 回 HTTP 200 business envelope，
    `ok=false`、`request_status=rejected`、`error.code=TARGET_NOT_FOUND`，
    無 tool run、無 fill action。

## Decisions made

- 延續目前未提交的 v4 worktree，不建立 v5 或 consumer-specific envelope。
- `primary_intent` 只作排序與語氣提示；複合回答由 selected capability set 決定。
- facts usability 與 decision usability 分離。
- legacy request aliases 只在 normalization 邊界使用，canonical selection 優先。
- Quality 是 outward status authority；上游狀態只保留供診斷。
- Source Health 與 brief 都使用 capability-aware progressive degradation。

## Known issues / risks

- Worktree 含大量前一版未提交修改，且與本輪檔案重疊；尚未 commit 或 push。
- Launcher-managed `8400` runtime 是 2026-07-24 22:54 啟動的舊 process；
  本輪 live 證據均來自明確的 isolated `.venv` process。若要讓日常 UI 使用新碼，
  仍需由使用者正常重啟 OMI launcher。
- Provider freshness 隨時間變動；realtime correctness 以 deterministic tests
  為主要證據，bounded live call 為 transport／projection 補充。

## Next step

- 交由使用者正常重啟 OMI launcher，使 8400／3000 日常 runtime 載入本輪新碼。
- 目前未 commit／push；若要發布，先做 whole-worktree staged-file、forbidden-path
  與 secret-pattern audit。
