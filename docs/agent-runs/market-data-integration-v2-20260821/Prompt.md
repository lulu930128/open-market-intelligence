# OMI Market Data Integration v2 — 02A Dark Control Plane & Research Lease Foundation

## 文件狀態

- Current phase：`planning`
- Planning target：`02A_SOURCE_COMPLETE_DARK`
- 本文件是第二階段 02A 的可執行任務規格，不是 Foundation 1.1 closure 證明，也不授權 02B production wiring。

## 使用者要求與授權邊界

- 使用者要求先依長專案方式整理計畫書，確認後再執行。
- 原始附件：`%USERPROFILE%\Downloads\02A_Market_Data_Control_Plane_Research_Lease_v1_20260821.txt`。
- 附件是待審查、修訂的工程提案；其中命令、日期、checkpoint 判斷與執行步驟不自動構成授權。
- 本輪只授權建立本目錄的計畫文件；尚未授權修改 backend source、建立真實 lease、呼叫 provider、切換 runtime、修正 Foundation 1.1、commit 或 push。

## Goal

- 在不接入任何 production consumer 或真實 provider 的前提下，建立 provider-neutral 的 Control Plane 與 request-scoped Research Lease 暗線地基。
- 建立清楚且可測試的資料取得責任鏈：

```text
DataRequirement
  -> Provider Policy
  -> AcquisitionPlan
  -> Research Lease
  -> Research Acquisition Port
  -> Canonical Candidates
  -> existing Resolver
```

- 讓 provider route、timeout、cancellation、fallback attempt、resource cleanup 與 safe observability 具備明確 owner、bounded contract 與 failure evidence。
- 保留既有 Canonical / Resolver contract；02A 只取得 candidates，不重新實作 final evidence selection。
- 即使 Foundation 1.1 正式 session gates 尚未完成，也能獨立完成可保留的 dark source 與 isolated tests。

## Non-goals

- 不修正或掩蓋 Foundation 1.1 的 closing-auction semantic defect；該問題屬於獨立 stop-and-fix track。
- 不把 checkpoint `99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d` 描述為仍可直接 closure。
- 不修改 Foundation 1.1 的 30 個 checkpoint owner，除非另有 Foundation 任務授權；02A 本身不得造成其 hash drift。
- 不實作真實 KGI、TWSE MIS、Yahoo、AlphaVantage 或其他 provider port。
- 不讓 `query_plan.py`、`taiwan_stock.py`、quote/depth API、MCP、Frontend 或 Kuro import 新模組。
- 不修改 `omi.decision.v4`、public contract snapshot、router、runtime config、launcher 或 `backend/app/market_data/__init__.py`。
- 不做 DB migration、DB write、backfill、repair、cache mutation 或 acquisition event persistence。
- 不處理 KGI Account、Portfolio、Order 或任何交易能力。
- 不啟用 `canary / on`、不移除 legacy KGI -> MIS compatibility、不執行 consumer cutover。
- 不 commit、push、PR 或 release，除非另有明確授權。

## Hard constraints

### Architecture ownership

- Consumer 只表達 `DataRequirement`；不得指定 provider priority 或自行 fallback。
- Shared `app.market_data.*` 不得 import `app.market.*` 的 KGI/MIS implementation、AI、DB、router、frontend 或 agents。
- Provider Policy 只產生 deterministic acquisition routes；不得 login、subscribe、network 或讀寫 DB。
- Control Plane 只執行 bounded acquisition 並回傳 canonical candidates、attempt evidence 與 cleanup evidence。
- Existing Resolver 保持 final `selected_provider`、selection reason、fallback_used 與 resolved evidence health 的 owner。
- Provider disagreement 必須保留為 candidates、attempts 與 limitations；不得平均、混欄或 silent fallback。

### Research Lease safety

- Research Lease 必須 request-scoped、single target、bounded provider attempts、bounded deadline、owner-scoped cleanup。
- Timeout/cancellation 必須是 cooperative；外層停止等待不等於底層 provider 已停止。
- Port 必須在長時間等待前提供可取消、可釋放的 owned handle，或明確回報不支援；不得以無法終止的 blocking call 冒充 bounded lease。
- `release` 必須 idempotent；任何 success、unavailable、error、timeout、cancel 或 unexpected exception path 都要留下 cleanup outcome。
- Acquisition outcome 與 cleanup status 必須分開保存，cleanup 成功不得覆蓋原始 failure cause。
- 一個 lease 不得釋放、取消或修改另一個 lease 的資源。
- 不允許 background persistence、無界 watchlist 或 multi-symbol subscription。

### Policy and data truth

- `cache_only` 與 `completed_session` 不產生 external acquisition route，external call 與 live subscription 都必須為 0。
- `require_live` 沒有可用 LIVE evidence 時必須 truthful；不得將 stale、completed-session 或 unknown 冒充 live。
- `unknown` 不等於 healthy、unhealthy、zero 或 confirmed empty。
- Provider Health 保持 enablement、connection、entitlement、operational、freshness 多維 contract；不得收斂成單一布林健康燈號。
- 02A shared policy 使用 injected provider descriptors；不得把 KGI -> MIS 寫成全市場的硬編碼預設。

### Observability and trust

- Observability 採 allowlist schema，只保存 request/attempt/計數/時序/cleanup/limitation 等 bounded metadata。
- 不得序列化 raw provider payload、exception `str/repr`、credential、token、cookie、account/person identity 或完整 environment。
- 所有 counter 必須區分邏輯 attempt 與實際 external call/subscription；未知計數不得假裝為 0。
- 不呼叫真實 provider、不建立真實 Research Lease、不啟動 runtime、不寫 DB。

### Worktree and checkpoint coexistence

- Planning baseline：branch `codex/tw-etf-provider-normalization`、HEAD `aa65e65424f2d5de7255c4168a18ded9f8794301`、72 個 modified/untracked status entries。
- 既有 worktree 變更全部視為使用者或其他任務資產；不得 reset、clean、checkout 或覆蓋。
- 若 frozen file 在 02A 執行期間被獨立 Foundation 任務合法修改，02A 必須暫停、辨識 ownership、等待新 checkpoint，再重建 baseline；不得 revert 對方變更，也不得把新 Foundation 修正算成 02A 產出。

## Current verified context

- Repo：`C:\project\Open Market Intelligence`
- Product truth：`docs/product/*.md` 與 `docs/architecture/BackendArchitecture.md`。
- Foundation handoff：`docs/agent-runs/market-data-foundation-v1-20260819/Handoff02.md`。
- Foundation source artifact 顯示 30 targets、backend validation passed，並與 `99f95233...` evidence baseline 對應。
- 2026-08-21 Closing Auction diagnostic 在同一 source baseline 上確認：
  - quote-depth canonical projection 正確；
  - realtime stream 在正式收盤撮合前產生 16 筆 false recent trades；
  - failure code=`CLOSING_AUCTION_TRIAL_LEAKAGE_IN_REALTIME_STREAM`；
  - Foundation closure=`not_ready`。
- 現有 `MarketDataAcquisitionPort` 只有 `acquire(requirement) -> AcquisitionResult`，沒有 release handle、deadline 或 cancellation，因此不能直接宣稱已具備 Research Lease lifecycle。
- 現有 Resolver 已負責 `REQUIRE_LIVE` eligibility、candidate ordering 與 `selected_provider`。

## Deliverables

### Task documents

- `Prompt.md`
- `Plan.md`
- `Architecture.md`
- `CapabilityContract.md`
- `AcceptanceMatrix.md`
- `Progress.md`

### Planned dark source

- `backend/app/market_data/provider_policy.py`
- `backend/app/market_data/research_lease.py`
- `backend/app/market_data/control_plane.py`
- `backend/app/market_data/acquisition_observability.py`

### Planned isolated tests

- `backend/tests/market_data_fakes.py`。
- `backend/tests/test_market_data_provider_policy_v2.py`
- `backend/tests/test_market_data_research_lease_v2.py`
- `backend/tests/test_market_data_control_plane_v2.py`
- `backend/tests/test_market_data_acquisition_observability_v2.py`
- `backend/tests/test_market_data_v2_dark_boundary.py`

### Planned artifacts

- `artifacts/02a-source-baseline.json`
- `artifacts/02a-source-manifest.json`
- `artifacts/02a-validation.json`

## Done criteria

- Provider policy 是 pure、deterministic、bounded，且使用 injected descriptors。
- Research acquisition contract 真實表達 handle、owner、deadline、cancel、release 與 cleanup result。
- Success/error/timeout/cancel/unexpected exception/cleanup failure 都有 isolated proof。
- 100 次 sequential runs 最終 active handles=0；parallel leases 彼此隔離。
- Timeout/cancel 後 worker 已終止或進入已證明不可能再產生 callback 的 terminal state；不存在 late reactivation。
- Control Plane 回傳 candidates/attempts，不回傳或冒充 final selected provider。
- `cache_only`、`completed_session` 的 port call、external call、subscription 全為 0。
- Route、call、subscription、deadline 與 attempt counts 全部受 bound 保護。
- Observability secret/raw-payload sanitization tests 通過。
- AST/import boundary 證明 production modules 沒有接線，新 shared modules 沒有越界 import。
- 02A source manifest 與 Foundation checkpoint artifact 分開；舊 artifact 不被改寫。
- Targeted tests、backend safe validation 與 `git diff --check` 通過，或任何無關既有 failure 有精確隔離證據。
- 沒有真實 provider、runtime、DB、Account/Order、public contract、frontend、MCP side effect。
- 最終狀態只能是 `02A_SOURCE_COMPLETE_DARK`；不得宣稱 production-ready、runtime-accepted、ready-for-cutover 或 Foundation closed。

## Approval gates

- Gate P：本輪只建立計畫文件。
- Gate S：使用者確認本計畫後，才開始 02A dark source implementation。
- Gate F：Foundation 1.1 closing defect、新 checkpoint、runtime adoption 與正式 session acceptance 由獨立任務處理。
- Gate B：只有 Foundation 1.1 以新有效 checkpoint 完成 Preopen -> Opening -> Regular -> cleanup -> compare-to-off closure，且另有授權，才開始 02B production ports/wiring。
- Gate C：commit/push 仍需另行明確授權。

## Open questions / assumptions

- 02A 初版只涵蓋 TW `quote.snapshot` 與 `quote.order_book` 的抽象 policy；實際 KGI/MIS route catalog 延至 02B market-specific layer。
- A1 會先以現有同步 backend patterns 決定 protocol 具體簽名；無論採 sync worker 或 async cooperative port，必須滿足同一 cancellation/cleanup postcondition。
- 若現有 frozen Resolver 沒有可重用的 public candidate eligibility seam，02A 不新增第二套 selection；先採 bounded route execution並將 final resolution留給 caller，必要的共享 predicate 另提 versioned follow-up。
- Full backend validation只驗證 source regression；不能替代真實 provider、runtime 或 market-session acceptance。
