# 02A Dark Control Plane & Research Lease Architecture

## 1. Responsibility map

| Owner | Owns | Must not own in 02A |
| --- | --- | --- |
| Consumer | `DataRequirement`、target、capability、realtime policy、purpose | provider priority、fallback、freshness推論 |
| Provider Policy | deterministic route plan、skip reason、bounds | login、network、subscription、final selection |
| Research Lease | request/attempt lifecycle、deadline、cancel、owned cleanup | provider semantics、cross-provider selection |
| Research Acquisition Port | provider-specific acquisition implementation contract | final selection、consumer projection |
| Control Plane | plan execution、bounded attempts、candidate collection、cleanup evidence | `selected_provider`、resolved selection reason |
| Existing Resolver | candidate eligibility、final selection、fallback_used、resolved health | provider I/O、lease lifecycle |
| Observability | allowlisted acquisition trace | raw payload、secret、account/person identity |

## 2. Dark flow

```text
Consumer requirement
  -> plan_acquisition(requirement, descriptors, health, budget)
  -> AcquisitionPlan(routes, limits, zero-I/O truth)
  -> ControlPlane.execute(...)
       -> ResearchLeaseRunner owns one bounded attempt at a time
       -> ResearchAcquisitionPort returns canonical AcquisitionResult
       -> handle cancel/release before attempt result is finalized
       -> attempt evidence + cleanup evidence
  -> ControlPlaneAcquisitionResult(candidates, attempts, counts, limitations)
  -> caller converts snapshots to existing ResolutionCandidate types
  -> existing resolve_quote / resolve_depth
  -> ResolvedEvidenceHealth(selected_provider, selection_reason, fallback_used)
```

02A tests終止於Control Plane result與existing pure Resolver fixture compatibility；production consumer仍不import這條path。

## 3. Existing contracts to reuse

- `DataRequirement`
- `RealtimePolicy`
- `DataPurpose`
- `AcquisitionResult`
- `CanonicalMarketSnapshot`
- `ProviderResourceHealth`
- `EvidenceFreshness`
- `ResolutionCandidate`
- `ResolvedEvidenceHealth`
- `resolve_quote(...)`
- `resolve_depth(...)`

02A 不複製或改名上述 types。若 lifecycle 需要新型別，放在新 dark modules，並保持能由 02B adapter 對接舊 `AcquisitionResult`。

## 4. Provider policy model

### Planned conceptual types

```text
ProviderDescriptor
  provider_key
  market
  capabilities
  role/authority_hint
  supports_external_fetch
  supports_live_subscription
  max_timeout_seconds
  unknown_health_policy

ProviderRoute
  provider_key
  priority
  capability
  external_fetch_allowed
  subscription_allowed
  route_timeout_seconds
  skip_reason

AcquisitionPlan
  version
  requirement
  routes
  max_provider_attempts
  overall_timeout_seconds
  allow_external_acquisition
  allow_live_subscription
  fallback_allowed
  limitations
```

Provider descriptors與market-specific route catalog是輸入，不是shared module常數。Fake tests可以使用`fake_primary_quote`、`fake_fallback_quote`等logical keys；02B才定義KGI/MIS實際catalog。

### Realtime policy

| Policy | Acquisition behavior | External calls | Live subscriptions |
| --- | --- | ---: | ---: |
| `cache_only` | routes=0；既有cache candidates由caller直接交Resolver | 0 | 0 |
| `completed_session` | routes=0；completed evidence read path不由02A取得 | 0 | 0 |
| `prefer_live` | 依bounded routes嘗試current evidence；結果可含limitations | bounded | bounded |
| `require_live` | 只規劃可追求live的routes；無route時truthful unfillable | bounded | bounded |

### Multi-dimensional health default matrix

| Dimension/value | Default action | Truth requirement |
| --- | --- | --- |
| enablement=`disabled` | skip | `PROVIDER_DISABLED` |
| entitlement=`auth_failed` | skip | `AUTH_FAILED` |
| entitlement=`plan_restricted` | skip | `PLAN_RESTRICTED` |
| operational=`failed` | skip current cycle | `OPERATIONAL_FAILED` |
| operational=`rate_limited` | skip current cycle | `RATE_LIMITED` |
| operational=`unavailable` | skip current cycle | `UNAVAILABLE` |
| operational/connection=`degraded` | explicit rule可允許bounded attempt | limitation必須保留 |
| connection=`disconnected` | 不自動視為永久不可用；只有descriptor明示允許bounded connect才可attempt | route reason必須可見 |
| 任一dimension=`unknown` | 不等於healthy；只有rule明示允許才可attempt | `HEALTH_UNKNOWN` limitation |

這是02A default policy，不覆蓋未來market-specific entitlement或reconnect規則。

## 5. Research acquisition lifecycle contract

現有`MarketDataAcquisitionPort.acquire()`沒有handle/cancel/release，所以02A需要新的dark lifecycle seam。

### Planned conceptual protocol

```text
AcquisitionAttemptContext
  request_id
  owner_token
  requirement
  provider_route
  started_at_monotonic
  absolute_deadline
  cancellation_token

ResearchAcquisitionPort.start(context) -> LeaseAttemptHandle

LeaseAttemptHandle
  owner_token
  activity
  active / terminal
  poll() -> ProviderAttemptResult | None
  cancel(reason) -> CancelResult
  release() -> CleanupResult
```

具體Python signature在A1依既有sync/async patterns收斂，但必須維持以下不變：

1. Owned handle在可能長時間等待前可被runner取得，`poll()`必須non-blocking。
2. `cancel`與`release`可重複呼叫而不傷害其他owner。
3. Provider若不能中止blocking acquisition，02B adapter必須另有component-owned abort boundary；不能把thread timeout描述為成功取消。
4. Runner在回傳Control Plane result前完成cleanup。

### Orthogonal final state

```text
AcquisitionOutcome
  not_required
  acquired
  unavailable
  failed
  cancelled
  timed_out
  policy_unfillable

CleanupStatus
  not_required
  pending
  released
  cleanup_failed
```

例：timeout後成功清理是`outcome=timed_out + cleanup=released`，不能只留下`released`。

### Internal lifecycle events

```text
created
  -> acquiring
  -> active (only when a resource actually exists)
  -> cancelling? / releasing
  -> terminal outcome + terminal cleanup status
```

State event用於diagnostics，不取代final outcome/cleanup欄位。

## 6. Deadline and cancellation model

- 使用monotonic clock，不以wall-clock計算timeout。
- Caller提供overall absolute deadline；每條route的budget為：

```text
min(route.max_timeout_seconds, overall_deadline - monotonic_now)
```

- Remaining budget <= 0 時不得啟動新attempt。
- Cancellation token在start前、等待中、fallback前都要檢查。
- Timeout/cancel sequence：

```text
signal cancellation
  -> port cancel/abort
  -> wait for bounded terminal acknowledgement
  -> release owned handle
  -> verify no late callback/reactivation
  -> record outcome and cleanup separately
```

- Fake tests使用injected clock/event，不依賴長時間`Start-Sleep`或真實network。

## 7. Control Plane result contract

```text
ControlPlaneAcquisitionResult
  request_id
  requirement
  candidates
  provider_health
  attempts
  logical_attempt_count
  external_call_count
  subscription_create_count
  active_handle_count_after
  limitations
  final_acquisition_outcome
```

不得包含：

- final `selected_provider`
- final selection reason
- `fallback_used` as resolved evidence truth
- merged cross-provider quote/depth
- raw payload

可以包含：

- attempted provider
- skip/continue reason
- candidate-producing provider
- attempt fallback path

名稱必須清楚區分acquisition與resolution。

## 8. Acquisition completion rule

- Control Plane不能自己重做Resolver排序或生成selected evidence。
- 若existing Resolver有可重用的public eligibility seam，A1可將其作為「是否還需要更多acquisition」的read-only predicate，但不得將結果 outward成selected provider。
- 目前沒有安全可重用seam，因此02A會執行plan內全部bounded routes並保留所有canonical candidates；不新增一套近似Resolver的hidden selector。
- 最終`require_live`是否滿足由caller交給existing Resolver判斷。

## 9. Counter semantics

| Counter | Meaning |
| --- | --- |
| logical_attempt_count | Control Plane開始處理的provider route數 |
| port_start_count | 實際呼叫port `start`的次數 |
| external_call_count | port truthfully回報的provider外部請求數；unknown不得改成0 |
| subscription_create_count | 實際建立subscription的次數，不是目前active symbol數 |
| active_handle_count_after | 此request-owned handles cleanup後數量 |

- Retry/reconnect若實際造成外部request或subscription，必須計入physical counts。
- 計數缺失時用`None/unknown`與limitation，不以0代表無side effect。
- 任一count超過plan budget時fail closed並cleanup。

## 10. Observability allowlist

### Allowed

- request ID、owner token的非敏感opaque ID
- purpose、market、instrument canonical key、capability、realtime policy
- route provider key、priority、safe detail code
- monotonic elapsed/absolute timestamps
- outcome、cleanup status、bounded counts、limitations

### Forbidden

- raw provider payload或callback body
- exception message/traceback原文進artifact
- credential、password、token、cookie、certificate detail
- account ID、person ID、portfolio或order資料
- environment dump、command line secret

Exception只經allowlisted classifier轉成 bounded `detail_code`；未知錯誤使用`UNCLASSIFIED_PROVIDER_ERROR`並在本機log之外保持無原文。

## 11. Import boundary

```text
allowed:
  app.market_data.control_plane
    -> app.market_data.provider_policy
    -> app.market_data.research_lease
    -> app.market_data.acquisition_observability
    -> existing app.market_data contracts/policies

forbidden:
  existing production modules -> any new 02A dark module
  new app.market_data modules -> app.market providers / AI / DB / routers / agents
```

Dark boundary test以AST/import graph為主；不能用naive字串掃描把四個新模組彼此的合法imports判成失敗。

## 12. Foundation checkpoint separation

- `source-checkpoint.json`與`99f95233...`屬Foundation歷史證據，不由02A修改。
- 02A建立自己的baseline/manifest/validation artifacts。
- Foundation known closing failure使舊fingerprint失去closure eligibility，但不妨礙02A在未碰frozen owners的前提下保留dark work。
- Foundation若另行產生新checkpoint，02A只更新reference baseline與Progress，不把其修正納入02A changed files。

## 13. 02B compatibility seam

02B market-specific adapter可位於：

```text
backend/app/market/acquisition/
  kgi_tw_quote.py
  twse_mis_quote.py
```

它們可以import provider implementation並實作02A lifecycle protocol；shared `app.market_data.*`不可反向import。

02B不在本任務執行範圍，且必須等待Foundation新checkpoint完成正式closure。
