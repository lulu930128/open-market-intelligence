# Execution 模擬環境資格驗證邊界

`execution/` 繼續擁有 pure Draft admission 與 reducer。
`execution_simulation/SimulationApplication` 繼續擁有 factory-only synthetic SQLite
transaction、confirmation consumption、reservation、outbox 與 replay。
另有明確 opt-in retained LOCAL_MOCK lifecycle 與無 route 的 headless manual command seam；
來源、限制與未來 MCP App owner 見 [Execution backend](ExecutionBackendMilestone.md)。
Retained synthetic ledger 不解除 durable REAL_SIM qualification gate。
`execution_kgi_simulator/` 只擁有隔離 qualification 工具與本地 SDK-shaped fixture，
不新增 provider、account owner、正式下單服務或另一套 canonical model。正式 caller 不得 import。

新增 `rehearsal_*` commands 屬於 `SimulationApplication`，重用既有 schema 與 full replay。
claim 必須在 fixture 呼叫前 commit；result 與 correlated observation 分別以 command 保存。
已 claim 的 command 永不重送；明確 fencing 撤銷舊 generation，未決 claim 保持 UNKNOWN。
constructor、status、audit、replay 均不自動 dispatch、reconcile、排程或 recovery。
fake acceptance/cancel 使用既有 reducer；schema v1 繼續保留 reservation。

分離 call boundary 的 executable evidence 僅為 **LOCAL MOCK**。
wire 只接受確切的本地 `FakeSDK`／`FakeOrder` 類別；login 呼叫 literal `simulation=True`，
但 fixture 呼叫不能證明已安裝 SDK 的實際環境。
canonical contract 仍標記 SYNTHETIC、test_only、broker_connected=False；
真實 observation 不得塞入此 envelope 或重新標記成 synthetic。

PowerShell worker 有 Preflight、ContractTest、Probe、Send 模式，無網路、真 SDK import、
secret value ingress 或 production switch。Probe/Send 固定 fail closed；
補環境變數或等待平日不會解鎖。真實 simulator 實作需要 reviewed environment/account ingress、
native endpoint/output confinement、有效 session、真實 account facts、unit/correlation 證明及
durable simulator ledger lifecycle。這些是 source/evidence gates，不是使用者 bool flags。

SDK inspection 僅將 allowlist source 與 distribution metadata 當資料讀取，不執行 SDK。
不讀 broker log、CA 內容、SDK encrypted config，也不證明 native binary 的行為。

機械防護由 `execution_kgi_simulator/constraints.toml`、zero-debt manifest 與 injected negative tests
執行；既有 M1/M2A/M2B/M3/manual manifests 繼續有效。
本 package 沒有 frontend、HTTP route、MCP/AI/Kuro tool、scheduler、正式 migration、quote session 或 PAOS 整合。
