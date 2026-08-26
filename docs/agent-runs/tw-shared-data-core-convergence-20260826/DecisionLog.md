# Decision Log

## 已定決策

### D-001 — 採vertical slices，不做Big Bang

- 日期：2026-08-26
- 決策：quality、KGI、bars、current index/breadth、P2 seams分波次完成。
- 理由：保留已production-adopted Shared Core與dirty worktree，讓每包可驗證、可回退。

### D-002 — Quality最低gate提前

- 日期：2026-08-26
- 決策：CORE-01/02在KGI production candidate cutover前完成。
- 理由：不能先讓新provider candidate成為decision-ready，再補中央eligibility。

### D-003 — Authority policy明確化

- 日期：2026-08-26
- 決策：`minimum_authority`由shared quality policy的明確mapping / admissibility rules執行；不使用Enum lexical/definition order。
- 理由：authority與provider priority是不同概念，且排序必須可測試。

### D-004 — Canonical lineage requirement採additive contract

- 日期：2026-08-26
- 決策：新增向後相容的explicit requirement；不從capability ID或provider名稱暗推。
- 理由：legacy cache與canonical decision path需要不同truthful handling。

### D-005 — GET一律cache-only

- 日期：2026-08-26
- 決策：先提供bounded POST/job/lease，再切除GET refresh side effects。
- 理由：避免polling造成provider IO、DB mutation或subscription。

### D-006 — Realtime lease lifecycle分層

- 日期：2026-08-26
- 決策：viewer heartbeat與request-scoped research lease共用ownership/cleanup primitives，但保留不同application lifecycle。
- 理由：直接把persistent viewer塞入ResearchLeaseRunner會掩蓋heartbeat、visibility與symbol-switch語意。

### D-007 — Current與completed capability分離

- 日期：2026-08-26
- 決策：current index/breadth不塞回completed official capability。
- 理由：trade date、session、provisional/final與authority語意不同。

### D-008 — P2採seam closure

- 日期：2026-08-26
- 決策：本輪完成company profile reader、derived lineage seam、migration order與guards；不一次fully migrate全部長尾dataset。
- 理由：P0/P1是主要production truth，長尾Big Bang會擴大風險與驗證面。

## 待實作時確認

### O-001 — Authority admissibility mapping

- 狀態：`RESOLVED`（CORE-01）。
- 決策：使用明確shared rank `EXCHANGE > BROKER > VENDOR > DERIVED > CACHE`；不依Enum順序，也不包含provider例外。
- 證據：authority floor parameterized tests；若未來capability證明total order不成立，必須升級成admissibility matrix並保留現有contract compatibility。

### O-002 — Required fields合併語意

- 狀態：`RESOLVED`（CORE-01）。
- 決策：`SnapshotCapabilityRequest.required_fields`與`QualityRequirement.required_fields`採ordered union；consumer需求在前、quality最低欄位在後，重複欄位只保留一次。
- 防護：field path需合法、trimmed、unique；中央evaluator輸出missing fields與stable reason code，reader後續不再重建policy。

### O-003 — Depth / auction typed storage

- 狀態：`RESOLVED`（KGI-03）。
- 決策：新增depth snapshot + normalized level rows與auction snapshot三張typed tables；不重用legacy quote row的depth JSON，也不新增generic JSON blob平台。
- 理由：depth level identity/order、auction provisional constraint與各自raw lineage可由schema與repository獨立驗證，不會把trial或order book誤投影成actual trade。
- 回退：0069 downgrade只移除三張新增表；disposable DB已驗證upgrade / downgrade / re-upgrade。

### O-004 — Existing KGI quote row compatibility

- 狀態：`RESOLVED`（KGI-02）。
- 決策：repository只接受可由SourceRegistry / RawFetchResult / binding驗證的row；legacy無法證明lineage即ineligible，不做推測式backfill。

### O-005 — Public lease API transition

- 狀態：`RESOLVED`（KGI-04/05）。
- 決策：保留既有route/response compatibility，內部改由provider-neutral coordinator與market-owned port；沒有breaking rename。

### D-009 — Source closure與runtime/live分離

- 日期：2026-08-26
- 決策：P0/P1可標`SOURCE_COMPLETE`，但program保持`SOURCE_COMPLETE_RUNTIME_PENDING`；未經named runtime adoption與official-session證據不標G4/G5/G6完成。
- 理由：running process、user DB revision、provider entitlement與market session不會因source tests自動更新。

### D-010 — Realtime stream是presentation telemetry

- 日期：2026-08-26
- 決策：stream contract固定`presentation_only`，canonical、decision與research usability全部為false；AI、MCP與decision modules禁止依賴stream owner或KGI lease port。
- 理由：sub-second UI telemetry不必逐筆落DB，但不得形成第二條research truth。

### D-011 — Current provider IO物理移出indices

- 日期：2026-08-26
- 決策：TWSE MIS current index、Yahoo current index與TWSE MIS current breadth各自由market-owned provider module負責；`indices.py`只保留completed/historical與compatibility projection責任。
- 理由：shared planner已擁有selection，physical IO也必須離開legacy service owner，且不得改寫completed official platform。

### D-012 — Breadth registered universe命名

- 日期：2026-08-26
- 決策：使用`full_market_registered_stock_universe`，並保留`official_full_market=false`與完整universe definition。
- 理由：排除viewer/subscription universe誤解，同時不把StockMaster registry冒充exchange official universe。
