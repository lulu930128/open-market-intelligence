# 進度

## 狀態

- Current phase: milestones 1-6 complete; milestone 7 implementation and fixture browser smoke complete; representative runtime adoption pending
- Last updated: 2026-08-09 Asia/Taipei

## 已完成

- 已確認 `main` 與 `origin/main` 同步且 worktree 乾淨。
- 已建立 `codex/tw-etf-provider-normalization` 工作分支。
- 已讀取產品文件、backend architecture、既有 ETF provider/service/schema 與 targeted tests。
- 已完成 capability contract 與四階段 rollout 定義。
- 已新增共用 ETF domain records、resource-level provider binding、registry 與 resolver。
- 已將元大 adapter 遷移到共用 contract；保留原 module re-export 相容性。
- 已將 ETF overview／refresh 改為 registry-driven，移除 service 內的元大來源與 request-count hardcode。
- 已驗證測試用第二 provider 可只提供 PCF；未知發行商不會呼叫注入 fetcher，並明確回報 `provider_not_connected`。
- 已依 SITCA 官方 ETF 專區建立 22 家發行商的 issuer code／alias catalog，resolver 會先正規化發行商 identity 再選 provider。
- 已新增富邦官方 adapter：006208 的 PCF 摘要與 iNAV 各只需一個 request；未將 Fund Asset 整體持倉誤標為 PCF 成分籃子。
- 已將前端狀態拆成盤後 NAV、盤中 iNAV、PCF 摘要與成分籃子；富邦會顯示 PCF 摘要已接入、成分籃子尚未接入。
- 已建立 `ProviderCoverage.md`，明列已接資源、未接資源與 TPEx 邊界。
- 已完成本機 ETF watchlist 唯讀稽核；確認問題同時包含 lazy cache、MOPS parser 漏列與 issuer adapter 覆蓋不足，未將私人自選 symbol 寫入 repo 文件。
- 已修正 MOPS malformed table parser：同一投信後續 ETF 的代碼即使落在 orphan `<td>`，仍會配對到正確基金資料列。
- 已接入國泰官方 iNAV：先以證券代號 exact match 解析投信內部 fund code，再取得有來源時間的估值快照，共 2 requests。
- 已接入群益官方 iNAV：單一官方 API 回傳 issuer ETF universe，parser 只接受證券代號 exact match，共 1 request。
- 已接入復華官方 iNAV：只解析官方 ETF 首頁的 `data-type=etfnet` 卡片，避免把推薦卡或盤後 NAV 誤當 iNAV，共 1 request。
- 已接入野村官方 iNAV：保留 TLS certificate verification，僅針對官方舊憑證缺少 SKI 放寬 X509 strict flag，共 1 request。
- 已接入統一官方 PCF 摘要：先從官方頁面解析 fund code 與預設生效日，再呼叫 JSON endpoint，共 2 requests；`asset` 持倉未冒充申贖籃子。
- 已將上述五家加入 resource-level registry；每家只宣告已驗證資源，沒有把 issuer 粗略標成全功能。
- 已完成 00981A／00878 顯示差異的 source-to-UI inspection：確認目前收盤價依附 `daily_nav`、top badge 只跟隨 daily NAV freshness，且 benchmark、holdings、index constituents 與 PCF basket 尚未完整分流。
- 已將後續工作拆成 canonical valuation、resource applicability、代表性 issuer 補齊與 frontend runtime 驗收四個里程碑；TPEx 延後到資料語意收斂後進行。
- 已新增 canonical ETF valuation projection：市價、日淨值／iNAV 與折溢價各自保留來源、日期、basis、status 與 issue codes；只有日期對齊時才計算折溢價。
- 已解除盤後市價對 MOPS NAV record 的依賴；即使日淨值缺少，既有台股日線收盤價仍可獨立顯示。
- 已建立 provider-verified PCF NAV fallback；元大、富邦、統一與國泰只有在 resource contract 明確宣告且 reference date 相容時，PCF `unit_nav` 才可成為盤後日淨值。
- 已建立 backend-owned ETF strategy 與 resource applicability：主動式 ETF 使用績效參考基準；現金申贖的實物籃子為 `not_applicable`；fund holdings、index constituents 與 PCF components 保持獨立。
- 已接入國泰官方 PCF：先以 00878 exact stock id 解析 fund code 與官方短名，再抓取 server-render PCF，共 2 requests；保留 reference/effective date、單位淨值與現金申贖摘要。
- 已將 frontend 頂部改為 canonical NAV、市價、折溢價與估值口徑；資源 chips 直接顯示日 NAV、iNAV、PCF 摘要、申贖籃子與基金持股的個別狀態。
- 已將 PCF 區塊改為「申購買回資料」；現金申贖顯示「不適用實物籃子」，未接基金持股則獨立顯示為來源尚未接入。
- 已更新 ETF Playwright fixture 使用 additive `valuation`、`strategy`、`resource_states` contract，並保留 frontend 對舊 backend response 的 rolling-upgrade fallback。

## 驗證證據

- `git status --short --branch`：開始時為 `main...origin/main`，無未提交檔案。
- 原始碼 inspection：profile/NAV 已共通；PCF/iNAV 的 provider 判斷、來源與 request count 仍 hardcode 為元大。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_tw_etf_capability.py','backend\tests\test_api_contract_inventory.py','backend\tests\test_market_transaction_contracts.py')`：compileall、40 tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-191052`。
- 富邦官方 endpoint bounded smoke：新 adapter 以 2 requests 取得 006208 PCF 摘要與 iNAV；保留來源日期／時間與折溢價，未產生成分籃子假資料。
- `.\scripts\run-safe-validation.ps1 -Profile frontend`：lint、TypeScript typecheck、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-191444`。
- MOPS 2026-08-07 bounded smoke：1 request；parser 從修正前 19 筆恢復為 61 筆，且保留不在報表 universe 內的 ETF 為 missing。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_tw_etf_capability.py`：compileall、ETF targeted tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-192955`。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_tw_etf_capability.py')`：compileall、35 個 ETF capability tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-201317`。
- 五家官方端點 bounded smoke：國泰 2、群益 1、復華 1、野村 1、統一 2，共 7 requests；五個 adapter 都成功保留 exact stock id 與來源日期／時間。此驗證發生在非交易時段，只證明 official source contract 與 parser，不宣稱盤中 current。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_tw_etf_capability.py','backend\tests\test_api_contract_inventory.py','backend\tests\test_market_transaction_contracts.py')`：compileall、49 tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-201644`。
- canonical valuation／applicability regression：compileall、55 tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-204442`。
- 國泰 PCF 官方 bounded smoke：`code=CN` 單獨查詢不會選定基金；`code=CN&name=國泰永續高股息` 會 server-render 00878 identity、2026-08-07 reference date、2026-08-10 effective date 與 PCF 欄位。Adapter 因此固定先做 exact lookup，再以 code＋官方短名查詢。
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_tw_etf_capability.py','backend\tests\test_api_contract_inventory.py','backend\tests\test_market_transaction_contracts.py')`：compileall、56 tests、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-205624`。
- `.\scripts\run-safe-validation.ps1 -Profile frontend`：lint、TypeScript typecheck、`git diff --check` 全部通過；log 位於 `.tmp\validation\20260809-210209`。
- Playwright targeted smoke：重用使用者既有 3000 dev server，只跑 `Taiwan ETF selection renders the ETF work surface and bounded refresh`，1 test passed；未終止或重啟既有 runtime。
- 8400 cache-only API runtime：00981A 組成 2026-08-07 市價 28.03 與 PCF unit NAV 28.15，valuation=`current`、premium/discount=-0.4263%、strategy=`active/performance_benchmark`、PCF basket=`not_applicable`；00878 組成市價 32.81 與 MOPS NAV 32.76，valuation=`current`、premium/discount=+0.1526%、strategy=`passive/tracked_index`。
- 3000 真實 DOM runtime：00981A 正確顯示「資料目前有效」、折價 -0.43%、績效參考基準、PCF 摘要有效、申贖籃子不適用與基金持股來源未接；00878 正確顯示核心估值與前一交易時段 iNAV。現有 backend process 尚未載入新 Cathay PCF binding，因此 00878 PCF runtime adoption 仍待重啟。

## 已做決策

- 第一 milestone 採 resource-level provider binding，為不同發行商只提供部分資源保留正確語意。
- 保留 Yuanta module 對 domain record 的 re-export，避免不必要的 internal import breakage。
- 未接入發行商維持可用的 profile/NAV，但 PCF/iNAV 明確降級，不顯示假資料。
- provider capability 以 PCF／iNAV resource 分開宣告；整個 issuer resource budget 上限為 6，加上 profile/NAV 後維持 public refresh 上限 8。
- PCF 摘要與 component exposure 是不同 capability；consumer 不得只因有 PCF summary 就宣稱成分籃子已接入。
- MOPS 日淨值是 shared-but-partial provider，不是全 ETF universe；parser completeness 與 source universe coverage 必須分開表達。
- 大型投信覆蓋採 resource-first：國泰已宣告 PCF＋iNAV，群益／復華／野村目前只宣告 iNAV，統一目前只宣告 PCF summary；尚未驗證的另一種資源維持 `provider_not_connected`。
- 市場價格、daily NAV、iNAV 與折溢價將由 backend canonical projection 組成；frontend 不跨 API 自行 join 或推論日期相容性。
- `applicable` 與 connector `supported` 分開建模；現金申贖無實物籃子、主動式 ETF 無追蹤指數都不再視為 provider 缺口。
- PCF、fund holdings 與 index constituents 是三種獨立資料集；後續若保存 holdings，使用獨立 migration，不沿用 PCF component rows。
- top-level ETF badge 使用 canonical valuation status；PCF、holdings 與 benchmark 缺口只顯示在各自 resource，不再共同拖低核心估值。
- 國泰 PCF 是現金申贖摘要，`components=()` 且 `redemption_method=cash`；這代表實物籃子不適用，不代表基金沒有持股。
- frontend 對舊 overview response 保留顯示 fallback，但不在 client 重建日期對齊、fallback 優先序或主動／被動判定。

## 已知問題／風險

- 公開 ETF overview 已 additive 新增 `valuation`、`strategy`、`resource_states`；既有欄位仍保留，未新增 DB migration。
- 目前已有元大、富邦、統一、群益、復華、野村、國泰共 7 家 adapter；其餘 15 家雖可辨識，但未驗證的 PCF／iNAV 仍會明確回報 `provider_not_connected`。
- TPEx 尚未納入本 contract；現階段不能宣稱全台股 ETF 已覆蓋。
- 本輪未重啟 backend／frontend runtime；目前 8400／3000 已採用 canonical valuation 與新 UI，但 8400 尚未載入最後新增的 Cathay PCF registry binding，00878 仍顯示 PCF source 未接。
- ETF profile 來源可覆蓋目前 TWSE ETF universe，但現行 UI 是選到個股才做 bounded refresh；尚未加入 watchlist-scope 預熱 job。
- 基金實際持股與被動式 ETF 的指數成分來源仍未接入；目前會明確顯示 `provider_not_connected`，不再冒充 PCF component。
- 非交易時段的 official smoke 只能證明 schema、identity 與日期 contract，不能作為盤中 iNAV current 驗收。

## 下一步

- 先讓使用者決定是否重啟目前 8400／3000 runtime；重啟後更新 00878 PCF，並與一檔實物 PCF ETF 完成最後 DOM／screenshot 驗收。
- runtime 驗收完成後進入 milestone 8：盤點 TPEx ETF universe、identity 與官方 profile/NAV/provider 差異，再決定最小 adapter 範圍。
