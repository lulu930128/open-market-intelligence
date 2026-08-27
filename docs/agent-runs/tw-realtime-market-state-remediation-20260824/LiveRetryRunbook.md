# MDF-M5 Core / Market-State Live Retry Runbook

## 執行狀態

- 本文件是 2026-08-24 source remediation 後的新 gate extension。
- 舊 `M5RetryRunbook20260825.md` 的30-target checkpoint `8acbaea6...`只能作historical base；正式gate必須同時驗28-target M5 extension `2ec74562...`、13-target Data Core convergence `460903c9...`與19-target Shared Data Core pre-commit overlay `5eec32a6...`，不得把舊層的superseded mismatch當成回復正確新source的理由。
- 使用者已授權2026-08-26 08:20起主動待機，以及只透過正式launcher完成component-scoped runtime adoption／repair。本文件仍不授權provider refresh、Account、Order、DB write、broad-kill、第二launcher owner或釋放未知lease。

## 共用前置門檻

1. 新 source checkpoint validation=`passed`，所有 target mismatch=0。
2. 正式 launcher、backend listener、frontend listener、selected port、Python 與 project root lineage 一致。
3. Effective mode=`compare`、health／ready／catalog／frontend proxy／stdio MCP 皆通過。
4. 2330 及 global lease baseline=0；外部 viewer lease 只能等 owner 自行釋放。
5. 建立單一 `owner_kind=acceptance_probe` 的 TW 2330 lease，sample 完成後只釋放自己持有的 lease。
6. Artifact 不保存 lease id、credential、raw provider payload或私人 identity。

## 08:20 主動待機與排障

### 啟動順序

1. 以preflight依base→M5 extension→Data Core convergence→Shared Data Core pre-commit precedence驗證所有checkpoint；older overlay的superseded mismatch不得單獨判定source drift。
2. 只透過正式launcher採用目前source並啟用process-scoped `compare`；backend啟動、frontend readiness與idle cleanup分別允許最多180／120／240秒，再驗證listener／Python／project root lineage、health／ready、catalog、frontend proxy與stdio MCP。
3. Global lease baseline必須為0；再建立單一TW 2330 `acceptance_probe`執行acquire／sample readiness／owner-only release／idle cleanup。08:20 readiness不是Preopen pass。
4. 08:20起作啟動、readiness、修復與必要retry；沒有固定完成期限。Runtime乾淨後立即取得當下仍有效的Preopen／08:58 Opening／09:05後Regular／13:25前後Closing evidence。已經過的session gate標pending，不得用後一時段補pass，並由同一automation續排下一個合法時窗。

### Failure處置

1. Runtime lineage、effective mode、health／ready、frontend或MCP transient failure：使用正式launcher的component-scoped `Prepare`／`RestartServices`，bounded等待後重跑完整Check；不得手動kill或建立第二runtime owner。
2. Global lease=0但bridge逾idle timeout：先等既定自然cleanup；仍存在才component-scoped restart，並重新證明lineage、compare與zero baseline。
3. External viewer lease：不得release；保存redacted owner／symbol counts並在有效時窗內bounded recheck。Owner自行清除後繼續；逾越對應session window才terminal。
4. KGI Python／CA／login／subscription failure：先release自身probe並驗證after baseline，再讀redacted log／config status。Task-owned source、harness或runtime seam可修者，完成affected validation、extension checkpoint重建、heartbeat pin同步與runtime重新adopt後重試；需要credential、entitlement或人工作業才terminal。
5. Source drift：列出exact target與ownership，只允許localized task-owned修正。修正後舊session evidence失效，必須重建extension、同步pin、重新adopt並從最早受影響gate重跑；ownership不明或廣泛drift才terminal。
6. Session semantic failure：保存真實artifact與cleanup evidence；只要仍在同一有效session window且可由task-owned範圍修正，就修復並重跑。若窗口已過，該gate維持pending且不得拿後續時段補pass，但仍繼續安全修復與其餘可取得gate；最後由同一automation續排。

### 通知與停止

- 第一次failure、可修復failure、成功retry與中間續排一律不通知；automation繼續工作。
- Credential／entitlement／人工作業、外部owner持續阻擋、ownership不明／廣泛drift、需要Account／Order／DB／broad-kill等越界操作，或同一component blocker在完整診斷與至少兩輪給足等待的component-scoped修復／重試後仍無新證據，才暫停並回報。時間經過本身不是terminal blocker。
- 全部live gates、cleanup、Market-State reconciliation、compare-to-off rollback與final validation完成後，才通知最終摘要並將heartbeat設為paused。

## Gate A：MDF-M5 Core

### A1 Preopen cold-start

- 在沒有當日 prior KGI callback baseline 的條件下啟動 2330 lease。
- 至少保存第一筆正價量 callback 與 bounded 後續 sample 的：`session_phase`、sequence、event／received／manager-ingested／stream-sampled time、`simtrade`、cumulative volume、trade／auction counts。
- Pass：preopen positive callback 不進 `recent_trades`；auction observation 為 indicative；L5 可用時 lots→shares 可對帳。
- Fail：任何 preopen callback 被標 actual trade，或 cold-start 因沒有 previous cumulative baseline 而放行。

### A2 Opening transition

- 08:58 起持續到第一筆 formal trade 或 09:02 stop time。
- Pass：試撮 callback 不進正式成交；第一筆正式成交只在 session 允許且 cumulative volume 嚴格推進時出現；跨 sample sequence／event time 不倒退。
- `recent_trades` 仍是 newest-first；同 cumulative callback 不新增 event。

### A3 Regular callback integrity

- Bounded 收集至少 60 秒，記錄 callback count、unique cumulative advances、recent trade additions、same cumulative suppressions、decreasing cumulative suppressions。
- Pass：`recent_trade_additions <= unique_cumulative_advances`，且不存在同 cumulative 或倒退量新增正式成交。
- 此 gate 只證明 OMI projection integrity；沒有 provider event id／sequence 時不得宣稱 provider-level exactly-once。

### A4 L5 first-useful 與 symbol switch

- 2330 lease active 後，量測 acquire requested→subscription ready→first matching-symbol depth→frontend first render。
- 切換 2330→2317→2330，每次保存 requested symbol、stream stock id、depth event time 與 first-useful elapsed。
- Pass：切換期間上一檔 depth 永不呈現；只有 matching stock id 且 non-stale stream depth 可取代 GET snapshot。
- Source-only 階段不固定 SLA；live artifact 先輸出 p50／p95／max 與 sample count，再依實測設定後續 threshold。

### A5 Latency telemetry

- 每筆 sample 保存四階段 timestamp 與 derived event→bridge、bridge→manager、manager→stream、event→stream milliseconds。
- 另存 `provider_delay_raw` 與 `provider_delay_unit=unknown`；在 SDK 文件加 correlation proof 前不得換算或併入 derived latency。
- 負值 duration 必須為 null 並有 warning，不能取絕對值掩蓋 clock／timestamp 問題。
- Artifact 輸出每階段 sample count、missing count、negative count、p50／p95／max。

### A6 Closing auction／formal match

- 13:25 前建立乾淨 bounded lease，覆蓋 closing auction cold-start 與 13:30 formal match。
- Pass：closing auction positive nonsim callback 仍不進正式成交；13:30 後只有 cumulative volume 推進的 formal callback可新增正式成交。
- 同 cumulative trial／non-trial pair必須保留 auction evidence而不新增 trade。

## Gate B：Market-State Gate

### B1 Resolved index authority

- 在相同 sample 讀 dashboard 與既有 index summary resolver。
- TWSE／TPEX 分別對帳 `resolution_id`、selected candidate/value/source/trade date、official close status、decision usable。
- Pass：dashboard `headline_index_field=resolved_indices`；resolved projection與 resolver 完全一致；legacy proxy `indices` 仍為 `official=false`、`decision_usable=false`。
- 缺資料可為 honest missing／partial，但不得退回 proxy 冒充 official headline。

### B2 Breadth reconciliation

- 每市場驗證 `advance + decline + unchanged = coverage`、`coverage + unknown = universe`。
- 已知 reason buckets 必須對帳 unknown：legacy compatibility breadth 使用 `state_missing + state_not_observed + reason_unknown`；resolved breadth 使用 `not_received + received_unclassified + reason_unknown`。
- `valid_no_trade`、`not_tradable`、`provider_missing`、`mapping_error` 未被 canonical evidence 證明時必須為 null，不得以 0 表示已確認沒有該原因。
- 保存 coverage ratio、reason distribution、as-of 與 warnings；full-market owner 未觀察到的項目維持 unknown。

## Closure 規則

- A 與 B 分開產生 artifact、pass／fail 與 owner attribution。
- A failure 不得被 B pass 抵銷，反之亦然。
- Source test、preview UI、post-close replay、readiness lease 都不能替代正式 session gate。
- 只有 Preopen、Opening、Regular、Closing、cleanup、resolved index與breadth reconciliation 全部通過，且 runtime 採用相同 checkpoint，才可討論 Foundation runtime closure。
- 任一 source／config 修正都使該修正前的本輪 evidence失效；重建 checkpoint、重新adopt並從受影響的最早 gate 重跑。
