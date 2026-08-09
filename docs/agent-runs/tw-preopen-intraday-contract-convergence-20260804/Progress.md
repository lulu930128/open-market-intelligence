# 台股盤前／盤中契約收斂與實盤驗收進度

## 狀態

- 目前階段：M0～M7 與 M8 正式 rollout 已完成；等待 2026-08-05 真實盤前／
  盤中時段驗收。
- 最後更新：2026-08-04（Asia/Taipei）。
- Repo：`C:\project\Open Market Intelligence`。
- Branch：`main`。
- 建立時 HEAD：`2d0476d`。
- Worktree：已有 2026-08-03 breadth v2 的未提交 backend、migration、AI、MCP、
  Radar、tests 與 Frontend 修改；本任務會疊加而不回復。
- 本任務未 commit、未 push；已透過正式 launcher 載入目前 source。沒有手動
  backfill、report/memory write 或破壞性 DB 操作。

## 里程碑狀態

| 里程碑 | 狀態 | 結果／下一門檻 |
| --- | --- | --- |
| M0 | 完成 | 001～011 deterministic regression 與 ownership 已鎖定。 |
| M1 | 完成 | Canonical session + interval-aware observation freshness。 |
| M2 | 完成 | Session-bound trade value + trading-day continuity boundary。 |
| M3 | 完成 | Market indices live／official composite + aggregate freshness。 |
| M4 | 完成 | Unified source-health row age + TXF semantic payload。 |
| M5 | 完成 | Negation-aware NLU + refresh reconciliation telemetry。 |
| M6 | 完成 | Public v4／MCP snapshot／consumer projection 相容。 |
| M7 | 完成 | Targeted/full regression、isolated REST/MCP runtime 與 DB safety 通過。 |
| M8 | 部分完成 | 正式 rollout／post-close smoke 通過；2026-08-05 真實盤前／盤中待使用者驗收。 |

## 已完成

- M1：`preopen_auction` 與 `regular_live` 走共用 canonical phase；近期 1 分 K
  依 interval-aware window 判定，不再要求 provider stream flag 才可用。
- M2：盤前不再把 index daily trade value 寫成當日累積成交值；跨交易日正常
  session boundary 不再被誤判為漏 K。
- M3：`market.indices` 同時保留 `official_close` 與 current `live_snapshot`，並明示
  `current_for_requested_session`、`is_complete`、mixed trade dates／as-of。
- M4：unified source health 每列重用 provider-health age serializer，aggregate 以
  oldest／newest 與 current／stale／expired buckets 表達；TXF 回傳 request-context
  `source_health` semantic payload。
- M5：交易決策 NLU 加入 clause-aware negation 與欄位退場語境；refresh telemetry
  分開 `refresh_requested`、policy allowed、primary reader、tool run、provider fetch、
  cache hit 與未嘗試原因。
- M6：更新 public capability fields 與 MCP offline snapshot；digest 為
  `3c03b3a51b72854b90b58c7b778d9ba519ae1565e7c15f74c4745166df14f6aa`。
- 已通過的局部驗證：104 個 session／projection／continuity／market-state tests、
  29 個 market projection tests、23 個 supplemental context tests（另 21 subtests）、
  24 個 NLU tests（另 33 subtests）、60 個 capability tests（另 12 subtests）、
  33 個 MCP／snapshot tests（另 2 subtests）。

## M7／M8 驗證與 rollout 證據

- Response budget 壓縮保留 index temporal/completeness 欄位與 source-health
  `snapshot_age_seconds`、`snapshot_is_stale`、`snapshot_lifecycle`；相關 outward
  regression 為 132 tests + 15 subtests 通過。
- Isolated runtime 使用 `18400`、獨立 SQLite 與獨立 runtime locks；顯式關閉所有
  component scheduler、stock-master bootstrap、crypto auto-refresh/WS。隔離 DB
  revision `20260803_0050`、`quick_check=ok`、`job_run=0`、`provider_event=0`，smoke
  完成後精確停止 PID，沒有碰正式 DB。
- Isolated REST 與 repo MCP 皆回 `omi.decision.v4`，public digest 為
  `3c03b3a51b72854b90b58c7b778d9ba519ae1565e7c15f74c4745166df14f6aa`；
  `allow_external_fetch=false` 時 telemetry 明示 policy observed／refresh denied／
  provider fetch not attempted。
- Formal post-close smoke 首次抓到一個額外 stop-and-fix bug：provider index
  `as_of=2026-08-04T13:30:00+08:00` 被直接和 `YYYY-MM-DD` 比較，誤標為 previous
  session。已將 normalized `trade_date` 與 observation `as_of` 分離，新增 regression。
- 最後 targeted suite 為 157 tests + 15 subtests 通過；完整 backend safe profile
  通過 compileall、`1455 passed`、`git diff --check`。Log：
  `.tmp/validation/20260804-195120`。Frontend 本任務未改，故未重跑 frontend
  profile/build/e2e。
- 正式 DB 在 rollout 前確認 revision `20260803_0050`、`quick_check=ok`。官方
  launcher 於 2026-08-04 19:54 偵測舊 backend PID 52312 早於 source，精確停止後
  啟動 backend runner PID 27684；Uvicorn server PID 21180。既有 frontend 被正確
  採用於 `127.0.0.1:3270`，proxy target 為 `127.0.0.1:8400`，launcher 狀態為
  `API OK; UI OK`。
- 正式 REST 與 repo MCP 均確認：`market.indices.status=ready`、
  `current_for_requested_session=true`、`is_complete=true`、TAIEX/TPEX
  `trade_date=2026-08-04`，且 oldest/newest as-of 都保留 13:30 timestamp；否定交易
  問句只產生 `data_freshness` intent。
- Formal unified source health 顯示 mixed snapshot ages，不再以 newest row 掩蓋
  expired history；逐列 age/stale/lifecycle 可見。TXF `diagnostics.source_health`
  回傳 quote/daily 兩筆 request-context evidence，不再是 semantic empty。

- 讀取使用者 2026-08-04 盤前／盤中測試指南並逐項對照 source、contract、DB
  與 live outward behavior。
- 讀取並對齊：
  - 2026-07-30 `tw-intraday-contract-convergence`
  - 2026-08-03 `tw-market-breadth-canonicalization`
  - OMI product docs 與 backend architecture boundary
- 確認本任務不是重新實作 breadth v2，而是前兩個專案的 live acceptance
  follow-up。
- 完成 `Prompt.md`、`Plan.md`、`IssueMap.md` 與本進度文件。
- 四份規劃文件已通過 strict UTF-8 讀回、標題／里程碑／issue ID 結構檢查、
  trailing-whitespace 檢查與 `git diff --check`；本輪未執行 build、test 或
  runtime smoke，符合 docs-only Tier 0 驗證邊界。

## 規劃前診斷證據

- 001、002、004、005、006、009 已以 fixed-time／pure contract probe 重現。
- 003 已由 live DB 時序證明：2026-08-04 08:59 的 TWSE/TPEX row 帶入前一
  completed session 累積成交值，09:00 才切換 intraday estimate。
- 008 已由 live source-health 查詢證明：Taiwan rows 中大量 snapshot 已過期，
  AI unified aggregate 仍可因單一較新 `checked_at` 顯示 current，且 row 缺 age。
- 010 已由 public v4 TXF payload 證明 applicable 但 semantic payload empty。
- 011 已與 public docs／tests 對照：`refresh_if_missing` 為 permission，現況缺的是
  reader/provider/tool-run telemetry 分層，不是單純漏執行所有 fill actions。
- 既有相關 targeted regression 共 140 tests 通過，代表目前 tests 未覆蓋這批
  exact phase alias、time-boundary 與 aggregation 案例；不能把全綠當成問題不存在。

## 已確認決策

- 001、002、004 以共用 session/observation resolver 根治，不各自加 alias。
- 003 不刪歷史 DB；停止新錯誤寫入，舊 row 由 read-time eligibility 隔離。
- 006 先保留 `market.indices` 相容 composite，live 與 daily close 分 component。
- 007 不禁止 `partial + is_current=true`；改為明示 session alignment、
  completeness、coverage 與 mixed as-of。
- 008 重用既有 provider-health age/stale serializer，AI 不再另算一套。
- 010 只有 supported payload 或 not-applicable 兩個合法出口。
- 011 維持 bounded refresh permission，不為了讓 `attempted=true` 引入 read-path
  side effect。
- 預設不新增 migration；任何 schema 需求必須先證明 projection／reader 無法
  安全表達。

## 已知風險

- 正式 runtime 目前載入 dirty worktree，而不是已 commit artifact；明早驗收前若
  再修改 backend source，launcher 需重新載入並重新記錄 digest/PID。
- 盤前、第一分鐘與 closing auction 的完整 live proof 受交易時段限制；fixture
  只能證明 determinism，不能代替 provider runtime evidence。
- 本任務沒有 frontend source diff，因此沒有重跑 frontend build/e2e；現有
  `3270/omi-ui-health` 與 backend proxy smoke 已通過。
- Standalone `C:\GPT_MCPtool\OMI_search` tray 未 reload；本輪驗證的是 repo MCP
  對正式 backend 的 parity，不宣稱外部 tray runtime 已更新。

## 下一步

1. 2026-08-05 08:50～08:59：依 `IssueMap.md` 驗收 001、002、003、007、008、
   009、011；保留 raw phase/event time、REST/AI payload 與必要 DB row。
2. 09:00～09:02 與 09:05～09:20：驗收 first-trade handoff、1m freshness、index
   live/official separation、TXF health 與 refresh telemetry；任一 P0 重現即停止
   closeout。
3. 尚未實際遇到的 closing auction/provider edge case標 `not observed`，不得用
   fixture 改標 live passed。完成後再決定是否 commit/push；本輪不代為執行。
