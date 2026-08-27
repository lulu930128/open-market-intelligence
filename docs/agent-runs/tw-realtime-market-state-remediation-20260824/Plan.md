# Plan

## 目前進度

- Milestone 0～5 的 source implementation 與 validation 已完成。
- Source-ready 已達成：30-target base、28-target M5 extension、13-target Data Core convergence與19-target Shared Data Core pre-commit overlay均由SourceOnly fail-closed驗證通過。
- Runtime-adopted 已於2026-08-26 16:29透過正式launcher component-scoped `RestartServices`完成；Runtime-accepted仍為`PENDING`，須由新source identity的正式session artifacts完成。

## 執行原則

- 依 milestone 順序實作；每一段先跑最接近的 targeted validation，失敗先修正再前進。
- Source test 通過只代表 implementation ready，不代表 live gate closure。
- 使用者已明示授權 2026-08-26 08:20 起的正式時段驗收，以及正式 launcher 的 component-scoped runtime adoption／repair；其餘外部 refresh、未知 lease、Account／Order、DB write、commit／push仍不在授權內。
- Automation 不因第一次 failure 停止。可安全修復項目必須保存 evidence、修復、重驗並續跑；只有明確 terminal blocker 才暫停。

## Milestone 0：規格與 baseline

- 固定 v1 stream、dashboard、index resolver、frontend L5 與現有 M5 runbook 行為。
- 建立 `Prompt.md`、`CapabilityContract.md`、`Plan.md`、`Progress.md`。
- 驗收：目標、非目標、owner、compatibility 與 live gate 分界明確。

## Milestone 1：Realtime projection v2

- Provider manager 保存 bounded raw quote event 與 manager ingestion timestamp。
- 新增 pure session-aware projection，透過 canonical KGI adapter 產出 trades、auction、L5 與 latency。
- Stream snapshot 採 v2 projection，保留 v1 additive fields。
- 驗收：cold-start auction fail closed、cumulative strict advance、跨日 reset、raw delay unit unknown。
- 驗證：canonical／provider／stream targeted pytest 與 compile check。

## Milestone 1A：Cold-start 與 acceptance diagnostics hardening

- Regular／Post-close first eligible callback 改成 baseline-only；下一個 strict cumulative advance 才可新增 trade。
- 新增 bounded redacted diagnostic events／counters；normal SSE 不輸出 event history。
- 驗收：fixed-time tests 覆蓋 Regular、Post-close、same、decreasing、cross-date 與 diagnostic redaction／counter reconciliation。
- 驗證：`test_kgi_superpy_quote.py`、router/schema targeted pytest。

## Milestone 2：Frontend selected-symbol adoption

- 擴充 TypeScript stream v2 type。
- `QuoteDepthPanel` 不等待 GET；只有 current stream stock id 相符且 depth 可用／非 stale 時優先採用 stream L5。
- 保留既有 resolved GET depth 作 fallback；hook return boundary 隔離舊 quote depth、stream、replay 與不相符的 load state。
- 驗收：不顯示上一檔 L5，stream update 不受 5 秒 polling 上限。
- 驗證：Playwright stream-before-GET、GET-error+stream、2330→2303→2330、lint、TypeScript、build。

## Milestone 3：Market-State Gate

- Dashboard additive 採用既有 index resolver cache-only summary，回傳 resolved indices。
- Dashboard 以既有 index-summary breadth 作 `resolved_breadth` headline；舊 intraday-state breadth 只作 compatibility。
- Breadth 補可證明的 coverage reason counts，不猜無法辨識原因。
- 更新 Pydantic／MCP snapshot contract tests。
- 驗收：proxy estimate 與 resolved index 同時可見但權威性不混用；reason counts 可 reconciliation。
- Resolver 另輸出 selected provider、authority 與 finalization；Dashboard 直接投影，不自行推論第二套語意。
- 驗證：dashboard、index resolution、MCP snapshot targeted pytest。

## Milestone 4：MDF-M5／Market-State live retry contract

- 延伸 runbook：selected-symbol cold-start、正式成交、duplicate integrity、L5 first-useful timing、symbol switch、latency distribution。
- 另列 TWSE／TPEX resolved source、breadth coverage／reason reconciliation。
- 新 source 變更後將舊 checkpoint 標為歷史證據，不沿用其通過結論。
- 驗收：每個 gate 都有前置條件、輸出 artifact、pass／fail、owner attribution 與 stop condition。

## Milestone 4A：Executable harness 與 source identity extension

- 新增獨立 `invoke-mdf-m5-live-session.ps1`；preflight 保持 runtime／source gate owner。
- Harness 支援 live bounded lease sampling與 offline fixture validation，輸出 trade integrity、latency、L5 first-useful、symbol switch、redaction 與 cleanup summary。
- 建立 versioned acceptance extension checkpoint，涵蓋本輪 Frontend、Market-State、diagnostic contract、tests 與 live harness；preflight 同時驗 base 與 extension。
- 驗收：PowerShell parser、mock aggregation、percentile、switch timing、redaction 與 checkpoint mismatch fail-closed tests通過。

## Milestone 5：整體驗證與交付

- 執行最小足夠 backend／frontend regression、`git diff --check`、任務文件 UTF-8 讀回。
- 更新 `Progress.md`：已完成、證據、尚待 live gate、風險與精確下一步。
- 不 commit、不 push。

## Milestone 6：08:20 主動待機與 live closure

- 08:20 先驗 base＋extension source identity、launcher lineage、effective `compare`、health／ready、frontend／MCP與global lease baseline；啟動／frontend／cleanup timeout分別放寬至180／120／240秒，讓正式程式完成初始化而不因短暫慢啟動失敗。
- Runtime 一旦乾淨就立即完成單一 probe readiness並取得當下有效 evidence；Preopen 與 08:58 Opening仍維持真實時窗，09:05後取得Regular，13:25前後取得Closing Auction與formal close。沒有固定停止時間；只要仍能安全修復、取得新證據或推進有效gate就持續。
- Runtime／frontend／MCP transient failure走正式 launcher component-scoped repair；localized task-owned source／harness failure完成 validation、extension checkpoint重建、heartbeat pin同步與runtime重新adopt後，從最早受影響 gate重跑。
- 外部 lease只等待owner lifecycle並bounded recheck；不得代為release。每個probe attempt只釋放自身lease並證明cleanup。
- 中間成功與可修復failure不通知；全部gate完成或terminal blocker才回報。
- 驗收：Preopen、Opening、Regular、Closing、cleanup、resolved index與breadth evidence都有同一source identity的dated artifacts；最後完成component-scoped `compare -> off` rollback與final validation。

## 狀態邊界

1. Source-ready：Milestone 1A～5 與兩份 checkpoint pass。
2. Runtime-adopted：另經正式 launcher adoption；目前Shared Data Core source已完成此層，live readiness不在此層冒充通過。
3. Runtime-accepted：下一個真實台股交易 session 的全部 gates pass。

## Stop-and-fix 規則

- Source或config一旦修改，舊的本日session evidence失效；必須重建extension、重新adopt並從最早受影響gate重跑，不得用後續時段補前一時段。
- Credential／entitlement／人工作業、外部owner持續阻擋、ownership不明／廣泛drift、需越界操作，或同一component blocker已完整診斷並完成至少兩輪給足等待的修復／重試仍無新證據，才成為terminal blocker。單一session窗口經過只把該gate標pending；其餘安全修復與仍有效gate繼續，最後由同一automation續排。
- 任何可安全修復的問題不得只記錄failure後等待隔日；先在同一session window內完成修復與重驗。
