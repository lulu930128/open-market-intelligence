# 台股 Architecture Freeze Checklist

## Source freeze

- [x] Shared capability IDs、Registry、Catalog、probe與DatasetHealth parity。
- [x] Quote bundle同一request含quote、order book、auction、official close四元evidence。
- [x] Official close只由canonical completed daily owner確認。
- [x] AI與Portfolio不直接查market price ORM或持有quote→daily fallback。
- [x] 台股GET不觸發provider IO、commit或subscription；refresh使用POST/job/lease。
- [x] Platform-owned daily freshness由market lifecycle評估，AI只投影。
- [x] Sidecar都有catalog或explicit compatibility classification。
- [x] Realtime stream固定presentation-only，decision/research consumer不可使用。
- [x] CP0 consumer/provider debt baseline與current source一致。
- [x] Targeted backend、migration、frontend lint/typecheck/build與safe quick通過。
- [x] Task docs、JSON、UTF-8、trailing whitespace與diff hygiene通過。
- [x] Git index保持空，沒有commit/push。

Source state：`SOURCE_FROZEN`。

## Deliberately deferred source debt

- [ ] EOD transaction physical closure（`EOD-02`，不阻塞本輪P0/P1 source freeze）。
- [ ] Legacy index compatibility acquisition移出`indices.py`。
- [ ] Long-tail compatibility/lineage-gap dataset逐項migration。
- [ ] Regional valuation readers接Shared Core完整lineage。

## Runtime acceptance

- [ ] 使用者授權named launcher adoption。
- [ ] 驗launcher-selected endpoint、interpreter、project root與migration revision。
- [ ] Direct API、frontend proxy、MCP、visible UI parity。

Runtime state：`RUNTIME_ADOPTED`。2026-08-27正式launcher已採用current validated overlay；外部owner在兩輪完整compare修復後仍第三次覆寫off，current off baseline健康且zero-lease，但automation已依滯澀條件暫停，完整live acceptance仍分開追蹤。

## Official-session live acceptance

- [x] KGI entitlement與actual provider payload。
- [ ] Preopen、Opening、Regular、Closing Auction各時段合法evidence。
- [x] Symbol switch與L5無stale lease。
- [x] Duplicate trade=0、trial leak=0、cumulative decrease=0。
- [ ] Cleanup後active handles=0，compare/off rollback完成。

Live state：`LIVE_ACCEPTANCE_PARTIAL_BLOCKED`。Opening／Regular／Closing／cleanup／Market-State已有current evidence；final-source Preopen因外部runtime owner衝突暫停，錯過時段不得用後續時段補造。
