# M1 Relation Registry 維運手冊

## 邊界

- Public API 只有 `GET /api/market/cross-market/relations/{stock_id}`，不提供 relation CRUD。
- GET 只讀本機 registry，不呼叫 provider、不 refresh、不產生昂貴 side effect。
- Candidate 建立與 review 狀態變更只能透過 trusted maintenance command。
- LLM、Frontend、MCP adapter 與 Kuro 不得直接核准 relation，也不得直接讀寫 OMI DB。
- 本里程碑尚未把 migration 套用到 live `data/open_market_intelligence.db`；部署時必須先依 repo migration 流程升級，再啟動採用新 code 的 runtime。

## 只讀檢查

在 repo root 執行：

```powershell
$env:PYTHONPATH = (Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance validate
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance list
```

`validate` 的 `status=ready` 只代表 relation/evidence governance invariant 通過，不代表海外行情 current，也不代表 cross-market context 已可用。

## 建立候選

Candidate JSON 必須符合 `CrossMarketRelationCandidate`：canonical source/target identity、relation type/bucket、validity、verification time、ratio（只限 direct relation）與 evidence。建立動作只會產生 inactive `candidate`，不會自動進 production read path。

```powershell
$env:PYTHONPATH = (Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance create-candidate `
  --input C:\absolute\path\candidate.json `
  --actor "reviewer-id" `
  --reason "source and scope of the proposed relation"
```

## Review lifecycle

```powershell
# 核准沒有 validity overlap 的 candidate
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance approve 42 `
  --actor "approver-id" `
  --reason "primary evidence and ratio verified"

# 以新版本接替既有 active relation；舊版 valid_to 會關閉到新版前一天
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance approve 43 `
  --supersedes-relation-id 42 `
  --actor "approver-id" `
  --reason "new ratio effective from corporate action date"

# 候選不成立
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance reject 44 `
  --actor "approver-id" `
  --reason "primary evidence does not support the claimed relation"

# 撤銷 active relation
.\.venv\Scripts\python.exe -m app.market.cross_market.maintenance disable 43 `
  --actor "approver-id" `
  --reason "relation requires reverification"
```

所有 mutating command 都要求非空 `actor` 與 `reason`。`created_by` 保留候選建立者；review decision 寫入 `reviewed_by/reviewed_at`。

## 部署前驗證

```powershell
$env:PYTHONPATH = (Resolve-Path '.\backend').Path
$env:PYTHONPYCACHEPREFIX = '.tmp/pycache-cross-market'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  backend\tests\test_cross_market_relation_store.py `
  backend\tests\test_cross_market_relation_migration.py `
  backend\tests\test_cross_market_relation_api.py `
  backend\tests\test_database_model_contract.py
```

完成 migration 與 runtime adoption 後，另做代表性 outward check：

```powershell
Invoke-RestMethod "http://127.0.0.1:<selected-backend-port>/api/market/cross-market/relations/2330"
```

先由 launcher log／tray menu 確認實際 backend port，不預設一定是 8400。
