# OMI 定時派報 v2：可靠執行、資料就緒與可觀測性

## Goal

- 在既有 SMTP 派報、recipient group、preview、delivery、job queue 與 DB schedule 基礎上，建立可恢復、可去重、可追蹤且資料語意可信的定時派報執行層。
- 讓每一個正式排程 slot 都有永久、可查詢的 run 紀錄，並由資料庫保證同一 slot 不會被重複 claim。
- 明確區分「排程已 claim」、「內容已建立」、「job 已排入」、「SMTP 正在寄送」、「SMTP 已接受」、「結果不明」與「最終失敗」，不再以 queue 成功冒充寄送成功。
- Backend 重啟後能安全恢復尚未產生外部 side effect 的 run；對可能已完成 SMTP side effect 的不確定狀態，保留人工決策而不自動重寄。
- 讓台股盤前、盤後、Radar 與 watchlist 派報使用 backend-owned structured readiness contract，保留 `current`、`latest completed session`、`provisional`、`partial`、`missing`、`stale`、provider failure 與 source refs。
- 讓設定 UI 可看到 next run、最近正式排程狀態、run history、readiness、delivery/job 關聯、錯誤分類與安全 retry action。
- 完成 migration、backend/API、scheduler/runtime、frontend、restart recovery 與一封受控真實 SMTP smoke test 的驗證閉環。

## Non-goals

- 不做自動交易、下單、保證績效或單句猜漲跌派報。
- 不做大量行銷郵件、訂閱／退訂管理、開信追蹤、行銷名單匯入或 bulk campaign。
- 不在本階段建立 Slack、LINE、Discord、SMS 等 omnichannel delivery framework；v2 仍以既有 SMTP mail path 為主。
- 不為本案導入 Celery、Redis、RabbitMQ、Kafka 或外部 message broker。OMI 目前是 local-first 單機產品，先使用 SQLite-backed run ledger 與既有 background leader。
- 不承諾 SMTP end-to-end exactly-once。系統只承諾正式 schedule slot 的 exactly-once claim，以及不確定寄送結果不會被無條件自動重送。
- 不在 scheduler GET/list/read path 觸發寄送、昂貴全市場 refresh、大量 backfill、AI memory 寫入或未受 policy 控制的 LLM 呼叫。
- 不讓 frontend、MCP、Kuro 或 mail renderer 重做 backend 的市場日曆、freshness、quality、session、Radar 或 evidence 判斷。
- 不把本案混入正在進行的台股 breadth/session semantics 修改，也不順手重構無關 scheduler、job 或大型 frontend 模組。

## Hard constraints

### 產品與市場語意

- 台股仍是派報主線；其他市場維持台股研究的 context layer。
- 派報內容必須公開資料日期、session、freshness、coverage、warnings、missing、provider failure 與 best-effort 限制。
- `quality=ready` 不得抹去 optional capability 的缺口；required 與 optional capability 必須分開判定。
- 台股盤後報不得把 preopen auction、provisional breadth、partial coverage 或快取成功誤稱為 official close／finalized market state。
- 派報 readiness 不得解析 email HTML 或自然語言文字；必須使用 backend 產生的 structured snapshot／contract。

### 架構與相容性

- Backend 是 schedule、run state machine、market readiness、delivery orchestration 與 public API contract 的 owner。
- Frontend 只呈現 backend 回傳狀態與執行使用者 action，不自行計算 due、交易日、readiness 或 retryability。
- 既有 `/api/dispatch/preview`、`/send`、schedule CRUD、`/schedules/{id}/run` 與 delivery history 預設維持相容；若 v2 manual run 無法維持既有 job + delivery response，必須新增 additive/versioned endpoint，不得直接破壞現有 shape。
- Adapter、frontend 與 Kuro 不直接讀寫 OMI SQLite。
- Router 不擁有 transaction；claim、queue、recovery 與 reconciliation transaction 留在 dispatch/job service owner。
- 一個關聯只能有一個 canonical FK；不得同時用互相指向的 `schedule_run.delivery_id` 與 `delivery.schedule_run_id` 保存同一關係。

### 資料庫與時間

- Migration 採 additive 方式：新增 run table／欄位，不刪除現有 schedule、delivery、job 或歷史資料。
- 實作前必須確認當時 Alembic head；目前 worktree 的 `20260803_0050_tw_breadth_session_semantics.py` 尚未提交，v2 revision 不得在它仍不穩定時硬接或混入同一 revision。
- Live SQLite migration 前必須使用既有備份工具建立離線可恢復備份，並驗證 `PRAGMA quick_check`、foreign keys 與 migration head；不得刪除或重建 `data/open_market_intelligence.db`。
- DB 中排程時間以 UTC 儲存，排程設定保留 IANA timezone，所有 domain helper 明確處理 aware／naive datetime。不得假設 SQLite `DateTime(timezone=True)` 會保留 `tzinfo`。
- 正式 scheduled slot 使用 nullable `scheduled_slot_key` 或等價欄位作 DB unique guarantee；manual／manual_retry 使用獨立 run token，不與正式 slot 共用脆弱的 timestamp 唯一性。
- Claim 時保存 immutable schedule snapshot 或 schedule revision，避免排程被編輯、停用或刪除後改變既有 run 的原始意圖。
- Schedule 刪除需保留 run audit history；預設採 soft delete／archive 或受控停用，不得 cascade 刪除 run、delivery、job。

### 執行與 side effect

- APScheduler 只做 bounded heartbeat，不直接執行 SMTP，也不把每筆 DB schedule 註冊成 memory cron job。
- 舊 v1 與新 v2 scheduler 不可同時 active；feature flag/cutover 必須保證單一 execution owner。
- 必須有 bounded catch-up policy。預設只處理最新仍在 grace 內的 slot，並限制單次 claim count；不得因長時間關機一次補寄大量過期郵件。
- Readiness 輪詢與 SMTP delivery retry 使用不同 counter、interval 與 deadline，不得共用 `attempt_count`。
- DB 標記 `sending` 後若程序中斷，必須標記 `DELIVERY_RESULT_UNKNOWN_AFTER_RESTART` 或等價 error code，不得自動重寄。
- Deterministic Message-ID 只作追查與人工對帳，不宣稱 provider 一定去重。
- SMTP secret、app password、實際 smoke-test email 地址與私人 recipient data 不得寫入 tracked source、task docs、log、fixture 或 commit；使用本機 `.env`／recipient group／安全 runtime 設定。
- 使用者已在本對話中明確授權最終真實 SMTP smoke test寄到其指定的單一地址。此授權只適用於本任務受控驗證，不擴張成任意收件者或多封寄送權限。
- 每次 live smoke verification 最多寄一封、收件者數必須是 1、主旨明示 `[OMI TEST]`、內容不得含 secret 或不必要的私人投資資料；若結果進入 unknown，不自動補寄。

### Git 與工作區

- 現有 worktree 有未提交的 breadth、AI contract、market state、frontend 與 migration 修改；所有派報 v2 改動必須保持獨立、局部，禁止 revert 或覆寫既有變更。
- 不修改 Installer/staging 複製內容作為 source of truth；正式 source 穩定後才由既有 packaging flow 更新。
- 未獲使用者明確要求前不 commit、不 push、不發 PR。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: FastAPI backend、SQLAlchemy/Alembic、SQLite、APScheduler、ThreadPool JobRun、SMTP、Next.js Settings UI、OMI market/AI evidence contracts。
- 現有 mail dispatch 已有 recipient groups、manual preview/send、delivery history、SMTP background job 與 HTML/text renderer。
- 現有 scheduled dispatch 已有 `dispatch_schedule`、schedule CRUD、interval tick、timezone/day-of-week、`last_run_key` 去重與 manual run。
- 現有 `_schedule_is_due()` 只在本地時間分鐘完全相等時執行，backend 關閉跨過該分鐘會漏寄。
- 現有 `_trigger_schedule()` 在 delivery/job queue 完成後即更新 `last_success_at`，語意不等於 SMTP success。
- 現有 delivery 建立、job 建立、job submit、delivery-job attachment 分屬多個 commit／side-effect 邊界，需要明確 recovery 與 reconciliation。
- 現有 runtime background leader 在啟動時先將 queued/running JobRun 標為 interrupted error，再啟動 scheduler；派報 v2 recovery 必須接在此 ownership 之下。
- 現有 dispatch preview contract 已包含 `as_of`、`warnings`、`missing` 與 `metadata`，可作 structured readiness 的起點，但不得只靠文字或 missing 數量判斷。
- 台股 trading calendar、market session、breadth、Radar 與 outward data-quality contract 已有 owner；v2 應重用而非複製。

## Deliverables

- `dispatch_schedule_run` additive migration、ORM model、indexes、constraints、relationship 與 migration regression。
- `DispatchSchedule` v2 policy／next-run／summary／archive 欄位與 backward-compatible serialization。
- 純函式 `schedule_time`／calendar policy，處理 UTC、IANA timezone、weekday/trading-day、DST、inclusive boundary 與 bounded catch-up。
- Schedule/run state machine、DB unique claim、immutable snapshot、manual run、manual retry、queue handoff、startup recovery 與 periodic reconciliation。
- Queue 與 SMTP success/error/unknown 回寫契約；queue success、SMTP success 與 schedule summary 明確分離。
- Backend-owned `DispatchPreflightResult`／readiness requirement registry，含 required/optional capability、deadline、retryability、source refs 與 structured limitations。
- Additive API schema：schedule v2 fields、run history、run detail、安全 retry、pause/resume semantics；保護既有 route shape。
- Frontend API types、排程設定、next run、狀態、run history、readiness、錯誤與 safe retry UI；必要時拆分大型 dispatch settings component。
- i18n：繁中、英文、日文狀態／錯誤／policy 文案。
- Unit、migration、concurrency、recovery、API contract、frontend type/lint/build、copied-DB migration、runtime 與 SMTP smoke 驗證證據。
- README、`.env.example`、architecture/task docs 更新；不包含 real secrets 或實際收件地址。

## Done criteria

- Backend 關閉跨過排程分鐘後，在 grace 內只補執行一次；超過 grace 有永久 `skipped` 紀錄且不寄送。
- 同一正式 `schedule_id + scheduled_slot_key` 在 concurrent claim 下只能建立一筆 scheduled run。
- 長時間關機不會補寄無上限舊報；catch-up 數量與策略可解釋、可測且有上限。
- Queue 成功只更新 queued 狀態與 `last_queued_at`；只有 SMTP 成功才更新 delivery/run success 與 `last_sent_at`。
- claimed、waiting_data、retry_wait 與尚未開始 sending 的安全 queued 狀態可在 restart 後恢復；sending interruption 不自動重寄。
- Manual run 不消耗正式 slot、不修改 `next_run_at`、有獨立 history，且不覆蓋正式排程健康摘要。
- Readiness 使用 backend structured evidence；required/optional、official/provisional、current/latest completed、partial/missing/stale/provider failure 均有 regression。
- Readiness polling 不消耗 SMTP retry 次數；deadline 超時留存可見 reason code。
- 既有 manual preview/send、schedule CRUD、delivery list 與既有 API consumer regression 維持通過。
- UI 可看到 next run、最近正式排程狀態、last queued、last sent、run history、readiness、error code、delivery/job link 與可否 retry。
- Additive migration 可從空白 DB 與代表性舊 schema 升到 head，且 copied live DB 驗證 `quick_check=ok`、無 FK violation、既有 rows 保留。
- Runtime cutover 證明只有一個 background leader 與一個 dispatch scheduler active，舊/新 tick 不會雙跑。
- 真實 SMTP smoke 最多寄出一封 `[OMI TEST]` 郵件到使用者已授權的單一地址；DB 中 run、delivery、job、Message-ID 與 `last_sent_at` 對得上，且未產生第二封 duplicate。
- 相關 backend/frontend safe validation 通過，使用者可見 runtime 行為已以實際 launcher port、health、log 與 delivery/run 狀態驗證。
- 無 secret、私人收件地址、local DB、log、cache、build artifact 或無關修改進入 staged diff；未經要求不 commit/push。

## Open questions / assumptions

- 預設正式 schedule catch-up 採 `latest_only`；若未來需要逐 slot 補發，必須另外設定 `all_slots` 與低上限，不由系統自動猜測。
- 預設 schedule card 的健康摘要只由 `trigger_type=scheduled` 更新；manual/manual_retry 顯示在 history，但不覆蓋正式排程的 last status。
- 預設以 explicit `readiness_profile`（例如 `generic`、`tw_preopen`、`tw_post_close`、`watchlist_radar`）描述資料需求，不只從寄送時間推測報告類型。
- 預設既有 `/schedules/{id}/run` 保持 immediate/manual compatibility；完整 v2 manual state machine 透過 additive POST runs endpoint 提供。
- 預設 live SMTP smoke 使用本機既有 SMTP 設定與臨時／既有 recipient group；實際地址不落 tracked files。
- 若實作時發現現有 breadth `0050` 尚未穩定或 Alembic head 已改變，先停在 migration 前並更新本文件與 `Progress.md`。
