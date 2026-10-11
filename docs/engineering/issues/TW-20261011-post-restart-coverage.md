# 台股重啟後 coverage 觀察：Job 108842 與 completed intraday audit

紀錄日期：2026-10-11，時區 **Asia/Taipei**。狀態：OPEN / RECORD ONLY；修復 DEFERRED。

本紀錄只保存已觀察問題與後續調查驗收條件，不授權 scheduler、EOD、retry、quota、DB 或 runtime 變更。重啟後觀察到問題，不代表問題由重啟引起。

## 已確認的觀察

證據來源為本機 `logs/backend/2026-10-11/backend.log`，本次逐行核對；原始 log 為 ignored runtime artifact，不納入 Git。使用者提供的重啟時間約為 20:55；本次唯讀程序檢查顯示 backend PID 67220 啟動於 20:55:16、frontend PID 20792 啟動於 20:55:23。這些資訊不構成正式 loaded-release attestation。

1. **CONFIRMED：台股 EOD coverage postcondition 失敗。** Log 第 83 行：

   ```text
   Tracked job 108842 failed its outcome contract: EOD coverage postcondition not met: market=TW current=1927/1967 partial=0 stale=38 missing=2.
   ```

   JobRun ID 為 **108842**；current **1927/1967**、partial **0**、stale **38**、missing **2**。這是已確認的輸出不足；未在本次開啟 production DB 查詢 persisted JobRun，因此 DB 中的最終狀態與 result payload 尚待核對。

2. **CONFIRMED：completed TW intraday audit 多次遭 APScheduler 跳過。** Log 第 20、23、46、50、67、86 行等出現相同類型訊息，例如：

   ```text
   Execution of job "audit_completed_taiwan_intraday_coverage (trigger: interval[0:00:15], next run at: 2026-10-11 20:56:01 CST)" skipped: maximum number of running instances reached (1)
   ```

   20:56:16、20:57:16、20:57:31 等訊息證明反覆發生。引文時間是 scheduler 的 `next run at` 欄位，不冒充精確 task 起迄時間。應以 **Asia/Taipei** 解讀並核對 timezone 設定，不能只依含糊的 `CST` 縮寫推論地區。

## 分類與尚未驗證事項

- EOD：已確認 coverage failure；**root cause UNVERIFIED**。預期交易日、venue、provider、universe eligibility、各缺口原因均不得臆測。
- Scheduler：OBSERVATION / architecture risk，**P2 provisional**；**root cause UNVERIFIED、impact UNVERIFIED**。已有執行個體尚未釋放與排程跳過是訊息所示；執行是否超過 15 秒、是否卡住、是否造成 starvation、是否只是有界正常工作均未驗證。不能稱為已證實 deadlock。
- 兩項觀察的因果關係 **UNVERIFIED**；本次未修復、重試、repair、調整 interval 或放寬 `max_instances`。

## Source owner 與調查入口

- [`run_eod_coverage_reconcile_job`](../../../backend/app/jobs/eod_coverage.py)：job producer 呼叫 `reconcile_eod_coverage`；postcondition 未滿足且不符合可延續 partial 條件時，拋出含 result 的 `JobExecutionError`，交給 tracked-job owner。
- [`reconcile_eod_coverage`](../../../backend/app/market_data/eod_coverage.py)：coverage reconciliation / postcondition owner；台股日線 qualification / venue refresh 由 [`daily_ohlcv_platform.py`](../../../backend/app/market/daily_ohlcv_platform.py) 注入。
- [`service.py`](../../../backend/app/jobs/service.py) 與 [`JobRun`](../../../backend/app/db/models.py)：tracked-job lifecycle / persisted status schema owner。未以 log 替代 DB truth。
- [`audit_completed_taiwan_intraday_coverage` / `add_taiwan_intraday_bar_jobs`](../../../backend/app/jobs/taiwan_intraday_bar_scheduler.py)：audit 先 `dispatch_due_materializations`，再 `audit_completed_sessions`；不能因名稱含 audit 就當作純讀操作。註冊使用 `coalesce=True`、`max_instances=1`。
- [`config.py`](../../../backend/app/config.py)：`scheduler_taiwan_completed_materialization_interval_seconds` 預設 15 秒、下限 15 秒；本次 log 亦觀察到 15 秒 interval。設定預設不等於完整 loaded-config attestation。

## 後續調查與 acceptance checks（本次不執行修復）

1. 在明確界定的觀察期間，對齊 Asia/Taipei / UTC、scheduler job ID、task 開始／結束／例外與 monotonic duration；核對 p50 / p95 / max duration、skip 次數及最終 task end。沒有 end evidence 時保留 UNVERIFIED。
2. 以經授權的唯讀方式核對 JobRun 108842 的 request、expected trade date、status、started/finished timestamps、result 與錯誤；逐項解釋 38 stale、2 missing，保留原始 failure 與 universe denominator。
3. 核對 completed-session target selection、輪轉與重選 cadence、pending/running persisted job statuses、去重及 continuation；確認是否有 starvation，不能只以後來單次成功判定結案。
4. 追蹤 audit / dispatch / enqueue / reconcile 的 read/write、transaction、lock 與 provider-call 邊界；量測時不得隱性 refresh、repair 或消耗 quota。任何寫入式調查另行取得授權。
5. 若後續提出修復，需先建立可重現且離線的 regression，再驗證連續 bounded cycles、task 正常結束、狀態一致與 coverage postcondition。只有接受的 eligibility 排除才可解釋缺口，不得補零、掩蓋 stale/missing 或直接增大 concurrency 宣稱解決。

## 分開保留的 acceptance debt

下列為使用者提供的交接證據，本次未重跑，不屬於新缺陷或本紀錄已驗證的修復：

- US SSO 2026-10-09 regular 1m 為 378/390、missing 12、gap 10，`retry_budget_exhausted=3`；AMD 390/390。不得 reset / repair。
- MCP `omi.ask` cache-only AMD AutoTarget 曾回傳 `ok=true` / `omi.decision.v4`；未知 ZZZZZZ 曾正常回傳 blocked/unavailable；explicit AMD / auto SSO 曾通過。Backend / Frontend 曾回報 4.9.0。
- 正式 loaded-release identity **UNATTESTED**；`database_handle_binding` **UNVERIFIED**；先前 Launcher B1/B2/B4、rollback identity 與整體 B1–B4 驗收仍未確認。本次 source commit 不提升這些 gate。
- 先前約 483 cases、backup / restore 證據只屬歷史 receipt；未核對目前 source byte identities 前，不作本次測試通過證明。私有 backup、source archives、receipts 與 runtime data 均不提交。
