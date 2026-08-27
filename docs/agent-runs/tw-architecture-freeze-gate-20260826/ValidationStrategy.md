# Validation Strategy

## 原則

- 使用最小足夠、逐package驗證；不在每個小包跑全backend/full frontend。
- Source、migration、runtime、live分層；任何一層pass不能替代另一層。
- 測試fixture不得冒充provider entitlement或official-session evidence。
- 外部provider IO、user DB migration、launcher restart與live lease都需相符授權/時機。

## V0 — Planning / docs

- UTF-8 readback。
- Markdown必要heading/link/path檢查。
- JSON artifact parse。
- `git diff --check`。
- 不跑backend/frontend build。

## V1 — Lifecycle / shared contracts

建議targeted：

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests/test_market_data_gateway.py `
  tests/test_market_data_quality_policy.py `
  tests/test_market_data_resolution.py `
  tests/test_market_data_provider_catalog_v2.py `
  tests/test_market_data_registry.py `
  tests/test_tw_dataset_catalog.py `
  tests/test_tw_dataset_health.py
```

再依package加入intraday/realtime/current market tests。

## V2 — AI / MCP / valuation

- `test_ai_market_context_projection.py`
- `test_tw_quote_components.py`
- `test_ai_capability_contract.py`
- `test_ai_outward_contract.py`
- `test_omi_mcp_server.py`
- `test_mcp_schema_contract.py`
- portfolio/valuation/account separation targeted tests。
- AST guard：AI/Portfolio無market price ORM、stream/provider imports。

## V3 — GET / sidecar

- API contract inventory與router targeted tests。
- Provider functions monkeypatch成fail-on-call。
- Session commit/rollback、lease acquire/subscribe設spy；每個GET期望0。
- Search frontend/MCP call sites，禁止以GET refresh或provider query控制production selection。
- Institutional holding/futures/disposition/ETF/corporate event targeted tests。

## V4 — Freshness authority

- Dataset lifecycle expected/eligibility/current/missing/stale/NA/partial cases。
- Source health、AI freshness與context projection regressions。
- Parity guard：Registry、TW Catalog、descriptor/requirement/probe IDs一致。
- Negative guard：generic Gateway無TW session/provider imports。

## V5 — Migration

只有新增migration時執行：

- 在disposable DB copy做upgrade -> inspect -> downgrade -> inspect -> re-upgrade。
- 驗證舊capability alias/rename、FK/index/unique constraints與資料保留。
- 不在source phase寫user DB。

## V6 — Cross-surface source gate

- Backend compileall。
- Task-owned targeted integration集合。
- API/AI/MCP對同一fixture的selected provider、health、lineage、limitations parity。
- Frontend touched時執行ESLint、`tsc --noEmit`、production build。
- Architecture source guards與exact debt equality。
- `git diff --check`、task-doc readback、exact changed-file manifest。
- 若repo full profile有unrelated failure，保留完整error與隔離證據；不得掩蓋task-owned failure。

## V7 — Runtime adoption

需明確授權後：

- 使用既有launcher component-scoped lifecycle。
- 驗證selected port、repo venv/interpreter、project root、source identity、Alembic revision。
- `/health`、`/readyz`、direct API、frontend proxy、MCP schema/ask與visible UI。
- Zero lease/subscription baseline與provider/account health分離。

## V8 — Official-session live

- Preopen：auction indicative不成actual trade。
- Opening：trial退場、first actual trade正確。
- Regular：quote/depth、L5、cumulative monotonicity。
- Symbol switch：舊symbol lease/stream不殘留。
- Closing Auction：indicative與formal close分離。
- Cleanup：active handles=0、stale leases=0。
- 缺session證據維持`PENDING`。

## Failure reporting

每個artifact至少記錄：

- command / test files / timestamps
- exit code與pass/fail counts
- source identity / branch / dirty/staged counts
- task-owned或unrelated判斷
- external IO / DB / runtime是否發生
- remaining unverified gates
