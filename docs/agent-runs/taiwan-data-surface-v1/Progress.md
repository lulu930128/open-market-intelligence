# Taiwan Data Surface v1 進度

## 狀態

- 目前階段：v1 垂直切片完成，完整 regression 通過，準備 commit／push main
- 最後更新：2026-07-29（Asia/Taipei）

## 已完成

- 在 checkpoint `abff4c2` 之上建立 `codex/taiwan-data-surface-v1`；使用者已核准
  將目前安全快照直接保存至 main。
- 建立 backend-owned public target/capability registry v2、typed
  `selection.parameters`、target+market applicability、manifest 與 deterministic
  digest。
- 保留 `omi.decision.v4` 與 `evidence.data[capability_id]` canonical projection；
  未新增 `tw_screener`、`tw_calendar`、第二套 response contract 或 MCP 市場邏輯。
- 新增 cache-only Taiwan screening ranking／coverage，第一批 metric 為外資買賣超、
  投信買賣超與融資餘額變化率；具 stable snapshot、交易日 window、deterministic
  ties/pagination 與 full-universe coverage。
- 將 quote order book、auction 與 official close 拆成獨立 capability/freshness，
  盤前 last trade unavailable 不會再連帶阻擋可用委買賣與試撮。
- 正規化 Taiwan market indices、local-sample sectors、index contributions、
  institutional flow、margin/short 與 corporate-event calendar；跨日期 TWSE/TPEx
  aggregate 不做錯誤相加。
- 正規化 stock upcoming/history events、disposition 與 trading restrictions；
  event-only query plan 不載入 OHLC、技術面、基本面、籌碼面、券商分點或 quote
  depth。
- 將 corporate-event plural filters 與 offset pagination 下推至共用 cache reader，
  避免先截 1000 筆再篩選造成後段假分頁。
- Repo MCP 與 standalone `C:\GPT_MCPtool\OMI_search` 都先讀 backend
  `/api/ai/tools`，離線才讀 backend 產生的 snapshot；兩份 adapter 不 import
  backend、不讀 DB、不計算 freshness/ranking。
- 新增 snapshot 產生器、adapter 文件、contract/screening/quote/aggregate/event
  regression tests。

## 驗證證據

- Safe validation：
  `.tmp/validation/20260729-191421`；backend compileall、191 項 focused regression
  與 `git diff --check` 全部通過。
- Main pre-push regression：
  `.tmp/validation/20260729-195223` 的 117 項 failure-focused regression 通過；
  `.tmp/validation/20260729-195302` 的完整 backend suite `1174 passed`，
  compileall 與 `git diff --check` 通過。完整 suite 先揭露並已修正一般股票
  context 未建構 `event_context`、MCP literal fallback capability 漂移，以及
  payload budget compaction 將 diagnostics-only 空 answer/decision 變成 truthy
  空陣列結構的相容性問題。
- Standalone OMI_search：`python -B -m unittest discover -s tests`，
  `Ran 31 tests ... OK`；path-scoped `git diff --check -- OMI_search` 通過。
- 兩份 generated snapshot：registry=`omi.capability.registry.v2`、
  selection=`omi.capability.selection.v2`、22 targets、53 capabilities，digest
  均為
  `6fd8eacb0f17e48d0c369a0f49da887949ad856bc19249f5a2b13a5577965eb2`。
- 隔離 runtime `127.0.0.1:18400` health 證明 project root、venv 與目前
  worktree 正確；live `/api/ai/tools` schema 含 screening、quote、events、
  regulation 與 typed parameter keys。
- Live screening ask：`omi.decision.v4`、cache-only、as-of `2026-07-28`；
  coverage `1892/1973`、status=`partial`，缺口與 window warnings 保留，沒有
  隱性 full-market refresh。
- Live event calendar ask：status=`ready`、available_count=`247`、limit=`5`、
  `has_more=true`，as-of `2026-07-29` 與 assembly time 分離。
- Live `2330` disposition/restrictions ask：reader_profile=`event_only`；
  required reader 只有 stock identity/disposition，重型 market-analysis readers
  明確列為 excluded。
- Live stdio MCP：`initialize` → `tools/list` → `tools/call` 成功；
  registry/digest 與 backend 相同，business call `isError=false`，回傳 canonical
  v4 calendar evidence。
- 暫時 runtime 僅使用 `18400`；驗證後已核對並停止精確父子 PID，
  `18400` 無 listener。既有 `3000`／`8400` 程序未被操作。

## 已做決策

- 不以操作名詞建立 screener/calendar target。
- 不在 reader compact payload 建立第二套 public contract。
- 以 backend manifest／digest 消除三份人工 enum 漂移。
- Snapshot 只是 backend 不可用時的 schema fallback；正常狀態以
  `/api/ai/tools` 為權威。
- Screening、event calendar 與 regulation read path 固定 cache-only；需要外部
  contribution fetch 的 capability 仍由 backend trust/budget gate 控制。
- 既有 derivatives capability 足以表達目前台股衍生品 surface，不新增同義
  capability。

## 已知風險

- 使用者目前 `8400` runtime 是施工前載入的舊 process；本輪刻意不重啟它。
  部署驗收需經 launcher 安全重啟後，再對實際 selected port 做一次相同 smoke。
- 本階段未改 frontend；UI 仍可使用既有 specialized routes，新的 canonical
  capability surface 先供 AI/MCP/Kuro consumer 使用。
- `market.sectors` 明確是 OMI local sample，不宣稱官方全市場 sector breadth。
- 使用者要求保存整個目前專案快照，因此
  `docs/台股Radar現行計算與判斷基準_v1.0.txt` 會原樣納入 main checkpoint。
  文件證實現行 Radar bucket、批次相對 grade、盤中 overlay 與 T+1 hit/miss
  是不同語意，不能直接包成一般 ranking。
- 下一階段仍可擴充 `screening.radar`、更多 ranking metrics、technical
  indicators/signals/levels split、持股/融資歷史與 ownership concentration；
  這些不應回頭破壞本次 registry kernel。
- Standalone OMI_search 所在 monorepo 有其他專案既有 dirty changes；本輪只改
  `OMI_search/`，後續 commit/push 仍須 path-scoped audit。

## 下一步

- 使用者驗收後，安全重啟 OMI launcher，使主要 backend 載入本分支，再重跑
  `/api/ai/tools`、三個 representative `/api/ai/ask` 與外部 MCP smoke。
- 以 `docs/台股Radar現行計算與判斷基準_v1.0.txt` 為下一階段輸入，先把
  universe-independent read-only Radar 與 outcome contract 分離；外部 read
  不建立 snapshot、不 evaluate/write outcome。
- Main repo 依使用者指示直接保存至 main；`C:\GPT_MCPtool\OMI_search` 仍是另一個
  repo 的 path-scoped publish，未納入本次 main push。
