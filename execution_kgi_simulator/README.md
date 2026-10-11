# KGI simulator qualification only

本 package 是隔離資格驗證工具。**真實 Probe/Send 尚未實作為可啟用能力**，
只回傳 BLOCKED；沒有正式環境開關，也不能把 fake adapter 替換成 real SDK。

在 repo root 執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode Preflight
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode ContractTest
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode Probe
```

Exit 0：LOCAL MOCK tests PASS；1：測試失敗；2：BLOCKED。
Preflight/Probe 不會登入、連線或排程；Send 同樣封鎖，沒有真實 order payload 入口。
輸出為 JSON。SDK version/signatures/enums 為 AST inspection，不是 import/ABI 驗證。
PowerShell 只檢查 `KGI_SIM_PERSON_ID`、`KGI_SIM_PASSWORD`、`KGI_SIM_ACCOUNT` 的存在性，
不讀普通 KGI 設定、不載入 `.env`、不將 credential value 傳入 child。

LOCAL MOCK 使用相同 M1 Draft/admission/reducer、M2A confirmation/reservation/outbox。
只有固定的 `FakeSDK` 可進入 wire rehearsal；1000 shares/unit 完全是 fixture 假設。
claim 先 commit，fake call 在 transaction 外，transport Pending 不 accept。
後續明確的本地 correlated observation 才能推進 reducer。
claim 後 crash 是 UNKNOWN，不重送；query/reconcile/cancel 只在明確 command 時執行。

2026-10-11 Source audit 修復：kill switch 只封鎖新 SEND claim；明確 QUERY/CANCEL
仍須通過既有 digest、generation、一次性 command 與取消 identity 檢查。
`CancelOrder.Success` 只保存 `ACK_ONLY` audit，不產生 reducer event；正常取消流程維持
`CANCEL_PENDING`，UNKNOWN 也不會被 ACK 解決。
只有另一筆 `OrderStatus.Cancelled`，附上完整且綁定 command／preview／generation／
`LOCAL-ORDER` 的 `finality_fixture`（`origin=SYNTHETIC`、`scope=LOCAL_MOCK`、
`status=Cancelled`、`complete=True`），才可交由原 M1 reducer 判斷終局。
這是 test-only fixture schema，不是 broker finality 證明或可替換的真實 ingress。
晚到 partial/full fill 保留原 reducer 語意；取消不抹除累計成交。

Replay 相容範圍：舊 audit 中未帶 `semantics` 的取消成功紀錄，仍依原本事件重放，
不改寫歷史 projection；新 command 一律寫 `ACK_ONLY`，不能產生該舊格式。
舊紀錄相容不代表其 ACK 已取得獨立終局證據。

本次修復重跑結果（前次 Acceptance／Evidence／SourceManifest 保留原樣）：

- KGI ContractTest：32 PASS、0 FAIL、0 ERROR、0 SKIP；包含原 25 tests 與新增 7 個回歸。
- 五組 legacy suites：240 tests，239 PASS、0 FAIL、0 ERROR、1 SKIP（Windows symlink 1314）。
- 六組 execution architecture manifests：全部 PASS、0 violations、0 debt。
- Repo architecture guard：PASS，15 violations 均屬既有 declared debt。
- Backend architecture integration：2 PASS。
- ACK、終局、晚到成交、kill switch 與歷史紀錄皆含獨立 child-process replay parity；
  child 只重開 factory sandbox、verify/status/audit，沒有呼叫 wire。

本輪直接執行隔離 ContractTest worker，避免 launcher 的 credential presence lookup：

```powershell
.\.venv\Scripts\python.exe -I -S -B execution_kgi_simulator/worker.py ContractTest
```

沒有執行 Preflight/Probe/Send；沒有真 SDK import、憑證／CA 讀取、券商登入／送單／取消、
排程或 production DB 寫入。上述結果只驗證 LOCAL MOCK source，真實 simulator 仍 BLOCKED。

真實測試前缺口與命令見
[Handoff](../docs/exec-plans/active/kgi-official-simulator-20261011/Handoff.md)。
架構邊界見 [Architecture](../docs/architecture/ExecutionSimulatorQualification.md)。
