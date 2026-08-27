# 台股即時與市場狀態修復

## 目標

- 修正 KGI selected-symbol 即時串流在冷啟動、盤前與收盤集合競價階段可能把試撮誤收為正式成交的語意缺口。
- 將完整五檔、事件時間、接收時間與可解釋 latency 放入 versioned backend stream contract，讓前端不再用 5 秒 GET 輪詢冒充即時五檔。
- 在台股 market dashboard 中採用既有 index resolver 的 resolved index evidence，保留 proxy estimate 但不得把它當官方指數。
- 讓 breadth 除了 coverage 外，也回傳可證明的未分類原因分布；無法判定的原因維持 unknown，不猜成停牌、無成交或 provider missing。
- 把 Foundation runtime acceptance 拆成 `MDF-M5 Core` 與 `Market-State Gate`，各自有獨立 attribution 與可重跑證據。
- 根除 eligible session cold-start 把訂閱快照誤收為正式成交的缺口；Regular 與 Post-close 都必須先建立 cumulative baseline。
- 提供 bounded、redacted callback diagnostics 與可執行 live-session harness，讓 cumulative integrity、trial leakage、latency 與 symbol switch 可由 artifact 自動量化。
- 以 versioned acceptance extension checkpoint 指紋化本輪 Frontend、Market-State 與 live harness source，避免只重算舊 30-target manifest 卻漏掉新 gate owner。
- 在 2026-08-26 08:20 起由本任務的唯一 heartbeat 進入主動待機、runtime adoption、live acceptance 與 bounded 現場排障；可安全修復的 failure 必須修復、重驗並繼續，不得在第一次失敗時直接停止。

## 非目標

- 不修改 KGI 帳務、下單、持倉或美股能力。
- 不新增無界全市場 KGI subscription，也不把 dashboard read path 變成 provider refresh owner。
- 不在缺少 SDK／live evidence 時宣稱 `delay_time` 的時間單位。
- 不以 callback 外觀相同直接判定 provider duplicate；先保留 cumulative-volume integrity gate 與可觀測欄位。
- 不重寫既有 index resolver、trading calendar 或 frontend market semantics。
- 不用離線測試宣告正式交易時段 live gate 已通過。

## 硬限制

- Provider callback 只保留 raw normalized event；session、trade／auction、freshness 與 selected evidence 由 backend market-data boundary 投影。
- `Unknown != 0`、`No Quote != No Trade != Suspended`。
- `cache_only` dashboard read 不得觸發外部 provider I/O。
- HTTP、SSE、MCP 與 frontend 必須讀同一 backend contract，不各自重算正式成交、指數 authority 或 breadth 原因。
- 新欄位採 additive／versioned contract；既有 v1 consumer 在遷移期間仍可解析。
- 保留 provider、source、event time、received time、selection／fallback、freshness 與限制。
- 現有 worktree 有大量既有變更；只做本任務的局部 diff，不 revert、不 commit、不 push。

## 2026-08-26 排程驗收授權

- 08:20 起先執行 SourceOnly base＋extension identity、正式 launcher lineage、effective `compare`、health／ready、frontend／MCP 與 global viewer baseline；啟動、frontend readiness 與 idle cleanup 分別保留最多 180／120／240 秒。Morning remediation 可持續到 10:00，runtime 一旦乾淨就立即進入當下仍可取得的正式 session gate。
- 允許 automation 只透過正式 launcher 執行 component-scoped `Prepare`／`RestartServices`／`Check`，用來採用本輪 source、恢復 OMI runtime、等待 bounded readiness 並重新驗證；不得手動 broad-kill、建立第二個 launcher owner或改用未受控 runtime。
- Runtime、frontend、MCP、idle cleanup、harness 或本任務 source 的 localized failure，先保存真實 redacted artifact、確認 ownership，再做最小安全修正。任何 source／config 修正後必須重跑 affected validation、重建 extension checkpoint、同步 heartbeat pin、重新 adoption，並從最早受影響 gate 重跑。
- 外部 viewer lease 不得代為 release；先做 bounded recheck。自身 probe 必須在每次 attempt 後 owner-only release，並證明 global baseline 回復。
- 第一次 failure、可修復 failure、成功 retry 與中間續排都不通知使用者。盤前或開盤窗口若在修復期間經過，只能如實標為待下個交易日補驗，不得拿盤中證據替代，但 automation 仍須繼續修復與取得可取得的 Regular evidence，直到 10:00 才做 morning terminal 判定。Credential／entitlement／人工作業、外部 owner 逾有效時窗、ownership 不明或廣泛 source drift、需要越界操作可提前回報。
- 此授權不包含 Account／Portfolio／Order／交易、backfill、repair、production DB write／destructive probe、secret／credential 變更、unknown lease release、commit 或 push。

## 交付物

- `omi.tw.realtime_stream.v2`：session-aware trade／auction、完整 L5、latency stages 與 raw provider delay semantics。
- selected-symbol frontend 以股票代號 guard 採用 stream L5，stream 不可用時才回退既有 quote-depth snapshot。
- dashboard additive resolved index evidence 與 breadth coverage reason counts。
- backend／frontend targeted regression、可執行 live-session harness，以及延伸的 live retry runbook。
- Resolver-owned index `authority`、`finalization` 與 selected provider lineage；舊 `official`／`provisional` 欄位只作 compatibility。
- Foundation base checkpoint 之外的 versioned acceptance extension checkpoint 與 preflight verification。
- 本目錄的規格、能力契約、計畫與進度紀錄。

## 完成條件

- 盤前、closing auction、Regular 與 Post-close cold-start 第一筆 positive quote 都不進 `recent_trades`；只有 baseline 建立後、session eligible 且 cumulative volume 嚴格推進才可進正式成交。
- 同 cumulative volume callback 不重複建立正式成交；累計量倒退不污染正式成交序列。
- stream depth 有最多五檔 bid／ask、shares 與原始 lots，且 event／received／manager-ingested／stream-sampled 時間可追溯。
- `delay_time` 原值可見，但在未證明前 unit 明確為 unknown；計算出的 latency stages 不與 provider raw delay 混用。
- 前端切股後不顯示上一檔 depth、stream 或 replay；相符股票的 stream depth 不依賴 GET 完成即可優先顯示。
- dashboard resolved indices 直接來自既有 index resolver，proxy estimates 仍標 `official=false`、`decision_usable=false`。
- resolved index 明確區分 source authority 與 close finalization，並保留 selected provider／source lineage。
- dashboard `resolved_breadth` 沿用既有 index-summary breadth owner，已知 coverage gap 有 reason counts，無法辨識的項目仍是 unknown。
- source／schema／frontend／PowerShell harness targeted tests 通過；live gate runbook 明確列出尚待正式時段重跑的項目。
- Source-ready、runtime-adopted、runtime-accepted 三個狀態分開；沒有正式 launcher adoption 與真實 session artifact 時不得升格。

## 停止條件

- SDK callback 沒有穩定 identity／sequence，而需求改成保證 provider-level exactly-once。
- 需要外部大量 refresh、付費 quota、production DB mutation、正式下單、broad／machine-wide restart、第二 launcher owner或釋放未知 lease；正式 launcher 的 component-scoped OMI adoption／restart 已由本輪排程授權。
- 實測證明 KGI callback 的 `delay_time`、volume unit 或 session timestamp 與現有假設不符，且無法在相容 contract 內修正。
