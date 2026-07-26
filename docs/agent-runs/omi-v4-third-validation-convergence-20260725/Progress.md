# Progress

## Status

- Current phase: closeout complete, awaiting final scope review/launcher restart/commit
- Last updated: 2026-07-25 21:02 +08:00

## Completed

- 讀取第三輪驗證清單、產品基線、backend architecture、v4 contract owners與既有 tests。
- 用 pure Query Plan probe確認 structured selection正常、自然語言 capability negation缺失。
- 用隔離 `18401` runtime確認 chips domain污染、Source Health filter缺失、pullback zone缺失與 passport reason噪音；runtime已關閉。
- 第三輪施工範圍與 additive compatibility策略已鎖定。
- `freshness_by_capability` 已由 Taiwan producer一路投影到 canonical evidence、manifest、quality與 fill plan。
- chips.institutional、chips.margin、ownership.distribution 已各自綁定 dataset freshness；domain stale只保留為 summary/fallback。
- Query Plan已支援 capability-level positive/negative hints；structured selection維持 caller authority。
- TDCC weekly freshness已加入保守 Saturday 12:00 Asia/Taipei release window。
- shareholding no-new-data refresh會透過 provider event記錄一小時 cooldown，Fill Plan保留 deferred action與 next eligible time。
- multi-domain answer會在 preferred zone缺失時回退 aggressive zone；stale quote可作歷史 facts但不可作決策。
- Source Health已正式支援 `problems_only`、`status_filter`、`include_healthy`與 provider filter，並拆分 total/matched/returned counts。
- resolved status contradiction已移出一般 issues/passport reasons，完整 authority evidence留在 capability diagnostics。
- Source Health problem集合已直接納入 shared provider `ERROR_STATUSES`，包含 `failed`、`timeout`、`rate_limited`與 `partial_success`。
- `release_status=pending`只在既有 observation 可用時抑制 refresh；empty/missing history會保留 refresh plan。
- stale historical facts現在同時要求 observation timestamp、provider與 source；任一 provenance欄位缺失即不可作 facts。
- shareholding refresh telemetry已改用獨立 short-lived session；telemetry commit failure會 rollback/log/close自身 session，不碰 caller transaction，後續 refresh step可繼續。

## Validation evidence

- Baseline targeted regression：`149 passed, 14 subtests passed`。
- Baseline isolated HTTP：`chips.institutional`、`chips.margin`、`ownership.distribution` 同時 blocked。
- Baseline Source Health：`problems_only=true` 的 20 筆包含 6 筆 healthy。
- Baseline port check：`18401` shutdown後無 listener。
- Capability/query/projection targeted：`44 passed, 10 subtests passed`。
- Release/cooldown/freshness targeted：`113 passed, 10 subtests passed`。
- Answer/quality/fill-plan targeted：`83 passed, 14 subtests passed`。
- Source Health/MCP schema targeted：`77 passed, 25 subtests passed`。
- 合併 regression：`216 passed, 29 subtests passed`；其後唯一 stale timestamp assertion已修正並單獨通過。
- `git diff --check`：通過；僅有既有 Windows LF/CRLF提示。
- Safe backend profile：compileall passed、`1029 passed`、full-tree `git diff --check` passed；log在 `.tmp/validation/20260725-082840`。
- 隔離 HTTP `18402`：自然語言 required為 institutional+margin、excluded為 ownership+fundamentals；無多餘 fill action。
- 隔離 HTTP `18402`：全 chips query顯示 institutional/margin `ready`，ownership在 Saturday noon前為 `pending/limited`且進 `deferred_actions.release_pending`。
- 隔離 HTTP `18402`：Source Health `total=307`、`matched problems=114`、returned 50、healthy returned 0。
- 隔離 HTTP `18402`：multi-domain answer顯示回測區 `2,334–2,350`。
- 隔離 MCP stdio：initialize、tools/list、成功 call與 `TARGET_NOT_FOUND` business rejection皆通過；business rejection維持 `isError=false`。
- 隔離 runtime已 graceful shutdown；port `18402`確認無 listener。
- Final review targeted safe profile：`111 passed`、compileall與 `git diff --check`通過；log在 `.tmp/validation/20260725-205657`。
- Telemetry session regression單檔：`12 passed`；log在 `.tmp/validation/20260725-205853`。
- Final review完整 backend safe profile：compileall passed、`1034 passed`、`git diff --check` passed；log在 `.tmp/validation/20260725-205903`。
- 隔離 HTTP `18403`：`/api/system/readyz=ready`；v4 Source Health `total=186`、`matched=29`、returned 20 problem rows、healthy returned 0。
- 隔離 HTTP `18403`：不存在台股維持 HTTP 200 business rejection，`ok=false`、`request_status=rejected`、`error.code=TARGET_NOT_FOUND`。
- 隔離 runtime已 graceful shutdown；port `18403`確認無 listener。

## Decisions made

- Backend-only contract修正；不在 consumer重做 freshness或 selection。
- Capability freshness成為單一 capability authority，domain freshness降為 summary/fallback。
- Structured selection不改；新增 natural-language capability hints。
- 以既有 provider event儲存 no-new-data cooldown，避免 schema migration。
- stale facts不再列入 blocked-required；保留 `facts_usable=true`、`decision_usable=false`並在 limitations揭露 observed time。
- Source Health filter先套 market/resource/target/provider作 total集合，再套 status/problem filter作 matched集合，最後由 limit形成 returned集合。
- Missing/empty dataset的 refresh authority優先於 pending release gate；只有 usable cached observation才可 deferred。
- Provider event屬 best-effort observability，必須與 stock refresh transaction隔離。

## Known issues / risks

- 工作樹原本已有大量未提交 v4變更；本任務只做局部疊加，不做 reset或無關清理。
- Launcher-managed 8400目前 health/ready正常，但 backend是 09:00啟動、早於 final review修改；最終隔離驗證不等於已部署這四項修正。
- TDCC沒有公開精確發布時刻；本次採保守且對外可見的 release-window policy。

## Next step

- 整理既有整批 v4 worktree的 staged scope，透過 tray `Restart Services`完成正式 8400部署驗證後，再 commit/push；本輪未 commit、未 push。
