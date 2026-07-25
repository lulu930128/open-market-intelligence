# OMI v4 第二輪契約收斂

## Goal

- 修正 2026-07-24 第二輪黑箱驗證仍可重現的 `omi.decision.v4` 對外契約缺陷。
- 讓 multi-domain answer、capability payload、freshness、realtime、quality、
  passport 與 response budget 對同一份 selected evidence 使用一致語意。
- 保留上一輪已打通的 tool execution、result ingestion、capability projection、
  refresh reconciliation 與 structured business error。

## Non-goals

- 不新增市場、provider、capability 或交易功能。
- 不把 OMI 變成自動下單或猜漲跌系統。
- 不做 DB schema migration，不重建或覆蓋
  `data/open_market_intelligence.db`。
- 不讓 Frontend、MCP、Kuro 重做 backend 的 freshness、quality、realtime 或
  decision logic。
- 不做全市場 backfill、無邊界外部 refresh、LLM、報告或 AI memory 寫入。
- 不清理或重寫目前 worktree 中與本輪無關的既有修改。

## Hard constraints

- Public contract 維持 `omi.decision.v4` only。
- Backend 是 answer profile、capability projection、semantic usability、
  freshness、realtime、trust、budget 與 fill reconciliation 的唯一 owner。
- `stale`、`partial`、`missing`、provider failure、supplemental gap 與 projection
  omission 必須保持可見，不得轉成 zero、ready 或 current。
- Quality 與 consumer-facing passport 不得對同一 capability 給出互斥狀態。
- Canonical `selection.limits` 維持最高優先；legacy
  `market_data_params.intraday_limit` 只在未明確指定 selection limit 時映射。
- Response budget 必須先降級 diagnostics／execution，再摘要 selected
  evidence；不得讓 brief 回應留下 debug 而清空全部核心 evidence。
- 修改採 minimal localized diff，與目前未提交的 v4 工作共存。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Public contract：`omi.decision.v4`
- Baseline runtime：`http://127.0.0.1:8400`，仍須以 launcher log 與 health root
  驗證實際 process。
- Second-round source：
  `C:\Users\thoma\Downloads\OMI_v4_第二輪驗證問題清單_2026-07-24.txt`
- 已確認現況：
  - multi-domain query 已選到資料，但 answer 仍固定為 broker-branch summary。
  - `ownership.distribution` 可投影成 `[{}, ...]` 並被 Quality 誤判 ready。
  - selected capabilities 仍會被未選取的 fundamentals／cross-market gap 污染。
  - US 同一 tool 的 `requested_capabilities` 未合併。
  - stale intraday bars 同時失去 facts 與 decision usability。
  - canonical `selection.limits["intraday.bars"]` 已正常；legacy
    `market_data_params.intraday_limit` 尚未映射。
  - Source Health total／returned 核心計數已改善，但 TTL 與 budget 降級未完成。
  - brief 32 KiB budget 會先移除全部 selected evidence。

## Deliverables

- Multi-domain stock answer profile 與可驗證的 brief section coverage。
- `ownership.distribution` producer／CapabilitySpec 對齊與通用 semantic-empty
  quality guard。
- selected freshness 與 supplemental/global gaps 分離。
- US tool capability merge、open-session realtime invariant、stale facts usability
  與 intraday limit compatibility mapping。
- Source Health total／returned problem semantics、snapshot TTL 與 progressive
  summary/sample degradation。
- Consumer-facing passport／quality 一致性與 debug-only contradiction handling。
- Brief response budget 的 evidence-first projection priority。
- 每項缺陷的 regression、targeted backend validation 與 bounded live API smoke。

## Done criteria

- 複合 2330 brief 同時涵蓋價格、技術、法人、融資券、分點與資料限制，不再只講分點。
- `ownership.distribution` 不含空 dict；semantic-empty payload 不得
  `facts_usable=true` 或 `status_class=ready`。
- 未選取的月營收／跨市場缺口只列為 supplemental，不阻塞 selected evidence。
- 單一 `us.read_intraday_trend` step 同時對帳 `quote.snapshot` 與
  `intraday.bars`。
- `market_status=open` 不得產生 `latest_completed_session`／`session_close`。
- 完整且有 provenance 的 stale bars 為
  `facts_usable=true`、`decision_usable=false`。
- `market_data_params.intraday_limit=30` 在沒有 explicit selection limit 時回傳
  30 點；explicit selection limit 優先。
- Source Health 分離 total／returned entry 與 problem count，舊 snapshot 不標
  current。
- Source Health 超過 budget 時先保留 summary 與 bounded problem sample。
- Quality ready 時 consumer-facing passport 不得 blocked；已解決的
  `status_sources_disagree` 不進一般 warnings。
- 32 KiB multi-domain brief 仍保留核心 selected evidence summary，並優先裁切
  execution diagnostics。
- Targeted regressions、safe backend profile 與代表性 live calls 都有可追蹤證據。

## Open questions / assumptions

- Assumption：本輪直接延續目前 worktree 的 v4 implementation，不建立第二套
  envelope 或 compatibility layer。
- Assumption：Source Health TTL 以 contract constant 表達，預設一小時 current、
  二十四小時內 stale、超過二十四小時 expired；測試不依賴真實現在時間。
- Assumption：一般 limitations 只呈現 consumer 可採取行動的 selected-data
  問題；完整矛盾診斷仍保留在 debug diagnostics。
