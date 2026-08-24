# 02 Market Data Integration handoff

## 起點

02 必須把 Foundation v1 視為 source-complete、尚未 runtime-accepted 的底層 contract。不得跳過 runtime adoption、provider policy、lease cleanup 或 public compatibility gates，直接把 canonical shadow切成 outward truth。

## 可用介面

- `DataRequirement`：instrument、capability、realtime policy、purpose、session、tradability、requested time、max age與candidate bound。
- `MarketDataAcquisitionPort`：由 market-specific owner實作；Foundation沒有 live implementation。
- `AcquisitionResult`：bounded canonical snapshots、provider resource health、external call/subscription counts與limitations。
- Pure resolver：quote、depth、bar series、trading status。
- Dataset Registry：五個 TW/US core datasets與refresh truth。
- Rollout seam：`off / shadow / compare`；02 才能設計 `canary / on`。

## Research Lease lifecycle

02 至少要分開：

1. Viewer Lease：由 frontend viewer lifecycle擁有。
2. Research Lease：由單次 AI/MCP request擁有，single target、bounded timeout、finally cleanup。
3. Background Collector Lease：只允許明確 bounded universe與獨立budget。

共同要求：

- provider selection由 backend Control Plane決定，consumer不得指定 KGI priority。
- lease/refcount、subscription symbols、TTL、idle shutdown與exception cleanup可觀察且有tests。
- `cache_only`與`completed_session` external call/subscription count必須為0。
- completed-session需求不得啟動無意義 KGI subscription。
- 不碰 KGI Account / Order；Quote、Data、Account health維持分離。

## Provider integration次序

1. 先完成 KGI TW / MIS production policy與single-symbol Research Lease。
2. KGI US、Yahoo、AlphaVantage各自只做market-specific adapter；共同 evidence進Canonical/Resolver。
3. 對每個 market/capability/session建立versioned provider policy與authority規則。
4. Level 1 / Level 5、shares/lots/contracts、session與entitlement差異保持顯式。
5. Provider disagreement不平均、不混欄；保留candidates、selection reason與limitations。

## Public contract決策

- 評估是否把 `completed_session` additive加入public `omi.decision.v4` realtime policy；在HTTP/SSE/MCP同時更新且有snapshot/compatibility tests前，保持internal。
- `instrument.trading_status` 只有在official evidence projector與fixture存在後才能 advertised。
- Canonical outward projection必須由backend單一owner產生；MCP/frontend/Kuro不得重算fallback、freshness或tradability。

## Canary / on先決條件

- Gate G1先證明launcher-selected port、PID、executable path、start time、source identity與health。
- Compare telemetry在bounded target/session sample下沒有未分類的price、volume/unit、session、trade-evidence或trading-status mismatch。
- KGI trial的`legacy zero -> canonical missing`差異需保留已核准taxonomy，不能再把missing壓回0。
- Canonical adapter/resolver latency、error rate與memory series都有budget。
- Rollback只需把mode改回`off`，不得依賴DB rollback或刪資料。

## Consumer cutover順序

1. AI/MCP internal projection與Research Lease。
2. Backend quote/read API canonical projection。
3. Frontend viewer contract。
4. Kuro/external consumers。
5. 全面驗收後才移除KGI→MIS masquerading與legacy fallback。

每一步都必須保留HTTP/SSE/MCP語意一致，且驗證`partial / missing / stale / fallback / policy_unsatisfied` outward truth。

## 02 完成條件

- Runtime source adoption已證明，不只source tests通過。
- KGI TW與US/MIS/Yahoo/AlphaVantage provider policies有bounded fixture與live smoke證據。
- Research Lease在success/timeout/error/cancellation均清理，active lease/subscription回零。
- Public realtime policy、capability catalog、MCP snapshot與consumer schema一致。
- Canary可回退`off`，沒有DB destructive migration、raw payload/credential leakage或無界subscription。
