# Shared Market Data Foundation AGENTS.md

此 subtree 是 provider-neutral Shared Market Data Foundation。開始前讀 `backend/AGENTS.md`、`docs/architecture/BackendArchitecture.md`、現有 registry／contracts 與 architecture debt。

## 允許的責任

- Typed provider-neutral observations、requirements、results 與 lineage。
- Deterministic candidate resolution、quality evaluation 與 dataset lifecycle contract。
- Provider-neutral gateway orchestration：read candidates、plan、透過 port acquire、交由明確 owner persist、reread、resolve。
- Registry、provider resource descriptor、health 與 repair policy primitives。

## 禁止的責任

除已精確宣告的 architecture debt 外，不得新增：

- 對 `app.ai`、`app.routers`、market-specific service／provider namespace 的 reverse dependency。
- Provider HTTP／SDK／登入／subscription 實作。
- Market-specific session、regulation、provider priority 或 consumer presentation。
- SQLAlchemy model ownership、DB transaction ownership或隱性 commit／rollback。
- AI decision、Frontend、MCP、Kuro 或 Account business logic。

## 檔案責任

- Contract／observation module：typed data only；不得 IO、DB 或 provider selection。
- Resolution／quality module：pure deterministic logic；不得 fetch、persist 或讀 runtime global state。
- Gateway：可以協調 ports 與 owner，但本身不成為 provider、repository 或 transaction owner。
- Registry／catalog：保存 executable lifecycle truth，不 import AI、scheduler、DB 或 provider implementation。

## 變更完成條件

- 先確認 owner、dependency direction、negative acceptance 與 legacy removal requirement。
- 新 capability 優先整合既有 canonical／resolver／registry，不建立平行 owner。
- Architecture debt 不得擴張；修掉 occurrence 時同步移除對應 debt entry。
- Temporal 變更先確認既有 canonical axes；不得以 shared enum 混合 Market Session、item finalization、authority、release 或 reconciliation。
- 跑 architecture guard 與最接近的 contract／registry／resolution tests；需要 runtime 或 live evidence 時分開回報。
