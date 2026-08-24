# 02A Capability Contract Canvas

## Contract scope

| Item | 02A contract |
| --- | --- |
| Product scope | 為TW reference market建立provider-neutral research acquisition control layer；不提供投資建議或交易能力。 |
| Target | 單一`InstrumentKey`；初版只接受`Market.TW`的`quote.snapshot`與`quote.order_book`。Symbol normalization沿用`InstrumentKey`，不另建規則。 |
| Provider | 02A只用injected descriptors與test-only fake ports；不登入或呼叫KGI、MIS、Yahoo、AlphaVantage。真實provider entitlement、cost、quota與retry contract延至02B。 |
| Resource | Port回傳既有`AcquisitionResult`與`CanonicalMarketSnapshot`；不新增provider payload schema。Quote/depth單位、session與lineage沿用Canonical contracts。 |
| Freshness | `DataRequirement.realtime_policy/session/max_age_seconds`表達需求；02A不重做freshness selection。Final LIVE/FRESH/STALE判定與selected evidence仍由existing Resolver擁有。 |
| Request bounds | target_count=1；routes/attempts、overall deadline、per-route timeout、external calls、subscriptions與max candidates全部有上限。 |
| Persistence | 無table、cache、retention、upsert或migration；02A source/tests/artifacts以外不寫資料。 |
| Failure | 明確區分not_required、policy_unfillable、unavailable、failed、cancelled、timed_out；cleanup另以not_required/released/cleanup_failed表達。Unknown不轉0。 |
| Transaction | 無DB transaction owner。Research Lease runner只擁有request-scoped handle的cancel/release；不碰其他lease。 |
| Public API | 無route、method、OpenAPI或public snapshot變更；production import graph保持unwired。 |
| AI contract | 不修改AI slot、payload level、`omi.decision.v4`或query planner。02B才評估internal shadow wiring。 |
| Consumer | Frontend、MCP、Kuro完全不接線；缺能力時維持現有production path。 |
| Validation | Pure policy、fake lifecycle、Control Plane bounds、sanitization、AST dark boundary、Foundation hash guard、targeted pytest與backend safe validation。 |

## Provider failure behavior

| Failure | 02A behavior |
| --- | --- |
| Port unavailable | 保存safe detail code；若plan允許則嘗試下一bounded route。 |
| Timeout | Cooperative cancel、bounded terminal acknowledgement、release owned handle；保存`timed_out + cleanup status`。 |
| Cancellation | 不啟動下一route；cancel/release owned handle。 |
| Provider exception | 不保存exception原文；分類成safe detail code，cleanup後依plan決定是否繼續。 |
| Cleanup exception | `cleanup_failed`，不得宣稱baseline restored。 |
| Empty acquired result | Contract failure；不得把empty推斷為成功或no trade。 |
| Unknown health/count | 不當成healthy或0；route需explicit policy，diagnostics保存unknown limitation。 |
| Counter overflow | Fail closed、停止新增attempt並完成owned cleanup。 |

## Ownership invariant

```text
Consumer requirement
  -> Provider Policy plans attempts
  -> Research Lease owns attempt lifecycle
  -> Provider Port produces Canonical candidates
  -> Control Plane returns candidates and attempt evidence
  -> Existing Resolver owns final selected evidence
```

02A任何實作若需要跨越此責任鏈，必須stop-and-fix並更新本contract。
