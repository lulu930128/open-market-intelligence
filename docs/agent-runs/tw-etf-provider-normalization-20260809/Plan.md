# 計畫

## Milestones

1. 通用 provider contract 與元大相容遷移（已完成）
   - 範圍：抽離 domain records，建立 resource-level provider binding、registry 與 resolver；service 改由 registry 驅動來源、能力與 request count。
   - 驗收：現有元大 PCF／iNAV parser 與 refresh 行為不變；未知 issuer 明確回報 `provider_not_connected`；公開 response schema 不變。
   - 驗證：`backend/tests/test_tw_etf_capability.py`、`backend/tests/test_api_contract_inventory.py`、`backend/tests/test_market_transaction_contracts.py`。

2. 官方 ETF universe／issuer identity 與第二個 provider（已完成）
   - 範圍：建立官方來源的 issuer code／alias mapping；以富邦 006208 驗證新增 provider 不需修改 service 分支。
   - 驗收：resolver 優先使用穩定 issuer identity；富邦已接資源與未接資源分開呈現；provider request 有明確上限。
   - 驗證：官方 endpoint bounded smoke、provider parser fixtures、registry conformance、service/API regression。

3. 發行商覆蓋擴張與 capability matrix（已完成）
   - 範圍：依本機實際覆蓋率優先接入國泰、統一，再評估群益、復華、野村等官方 PCF／iNAV adapter；記錄 provider/資源差異，但不把私人 watchlist symbol 寫入 repo。
   - 驗收：新增 adapter 不改 consumer contract；single-provider failure 不清空其他成功資源；coverage matrix 可稽核。
   - 驗證：每個 provider pure tests、malformed/timeout tests、bounded live canary。

4. Canonical valuation 與欄位級 fallback（已完成）
   - 範圍：在 backend service／projection 建立獨立的 market price、daily NAV、iNAV 與 derived premium/discount；market price 使用既有行情資料，不再依附 MOPS NAV record；daily NAV 依明確優先序選擇官方 observation。
   - 驗收：daily NAV 缺少時仍可顯示同日收盤價；PCF `unit_nav` 只有在語意與 `reference_date` 相容時才可 fallback；盤中／盤後折溢價只使用同日期與同估值基礎的輸入；既有 API 欄位保持相容，新欄位只做 additive extension。
   - 驗證：`backend/tests/test_tw_etf_capability.py` 的 composition、date mismatch、fallback 與 provider-failure cases；`backend/tests/test_api_contract_inventory.py`；`backend/tests/test_market_transaction_contracts.py`。

5. Resource applicability 與資料邊界（已完成）
   - 範圍：新增 backend-owned resource state，區分 `not_published`、`not_applicable`、`provider_not_connected` 與 `provider_failed`；正規化 active/passive management style、benchmark role、fund holdings、index constituents、PCF summary 與 PCF basket。
   - 驗收：主動式 ETF 顯示「績效參考基準」而非缺少追蹤指數；現金申購買回沒有實物籃子時顯示不適用；基金持股、指數成分與 PCF components 不共用錯誤語意或 persistence。
   - 驗證：resource-state truth-table tests、active/passive fixtures、cash/physical redemption fixtures、API schema regression；若新增 holdings tables，加入 Alembic migration、model contract 與 migration tests。

6. 代表性 issuer 資料補齊（已完成）
   - 範圍：以 00981A 與 00878 驗證欄位級多來源；先稽核統一官方 daily NAV／iNAV／holdings 與國泰官方 PCF／holdings，僅接入有穩定 identity、timestamp、授權與 request budget 的資源。
   - 驗收：00981A 可由行情與相容的官方 NAV observation 組成盤後估值，並正確呈現 active benchmark／cash redemption 語意；00878 的核心估值狀態不因 PCF／holdings 缺口降級；新增來源失敗不清空既有成功 cache。
   - 驗證：每個新增 provider 的 pure parser/schema-drift/timeout tests、bounded official smoke、service partial-failure 與 idempotent upsert tests。

7. Frontend ETF 資訊架構與 runtime 驗收（實作完成；實際 runtime 驗收待執行）
   - 範圍：將畫面分為「估值與折溢價」、「基金策略與投資組合」、「申購買回資料」；top badge 僅描述核心估值，resource chips 顯示各自狀態與日期；frontend 不自行推論 applicability 或 fallback。
   - 驗收：00981A 不再整排顯示 `—`，並能區分不適用與未接來源；00878 顯示核心估值有效，PCF／holdings 缺口留在對應區塊；desktop/mobile 無溢出或狀態誤色。
   - 驗證：frontend lint、TypeScript typecheck、fixture/e2e assertions；實際 runtime 重啟後，以 00981A、00878 及一檔完整 PCF ETF 做 DOM／screenshot 驗收。

8. TPEx 與全市場驗收
   - 範圍：納入 TPEx ETF identity、profile/NAV/PCF/iNAV 差異與交易日語意。
   - 驗收：TWSE／TPEx ETF 都能得到正確的 capability/freshness/source 狀態；未能合法或穩定取得的資源明確標示限制。
   - 驗證：universe coverage audit、API/data smoke、safe backend profile；若 frontend 狀態有變更再跑 frontend profile 與 browser check。

## Stop-and-fix rules

- 若公開 ETF response schema、request count 上限、transaction rollback 或 cache-only GET regression 失敗，先修正再進下一 milestone。
- 若官方來源授權、schema 或 request pattern 無法確認，不以網頁猜測或非官方聚合資料假裝完成 provider。
- 若發現需要 DB schema，先新增可追蹤 migration 與 migration tests，不做 silent schema drift。
- 若 runtime／外部 canary 只能證明非交易時段資料，不將它寫成盤中 current acceptance。
- 若市價與 NAV／iNAV 日期、session 或估值基礎不相容，不計算折溢價，也不以最近值硬湊。
- 若資料其實是基金持股、指數成分或現金申贖摘要，不得轉存成 PCF 實物籃子。
- 若 backend 尚未提供 `not_applicable`／`not_published` 判定，frontend 不得以 symbol 名稱或基金類型字串自行推論。

## Decisions

- 2026-08-09：先正規化 backend provider contract，再接第二家發行商，避免在 service 繼續累積 issuer-specific `if`。
- 2026-08-09：capability 採 resource-level，而不是 issuer-level；同一發行商可只接 PCF 或只接 iNAV。
- 2026-08-09：保留現有 API shape、DB tables 與 frontend 呈現，第一 milestone 不影響 AI／MCP 對外 contract。
- 2026-08-09：MOPS 日淨值定位為 shared-but-partial provider；先修 malformed table parser，再以 issuer adapter 補主動式與海外型 ETF，不用零值或錯誤日期掩蓋缺口。
- 2026-08-09：發行商 adapter 擴張後，下一優先是欄位級 composition 與 resource applicability；先修正資料語意，再擴張 TPEx。
- 2026-08-09：top-level ETF 狀態只代表核心估值可用性；PCF、holdings、benchmark 等次要 resource 各自保留狀態，不共同拖低整檔狀態。
- 2026-08-09：canonical projection 採 additive API extension 並保留 legacy fields，避免 frontend 遷移影響 AI／MCP 既有 consumer。
- 2026-08-09：PCF `unit_nav` 只有 provider resource 明確宣告 `unit_nav_is_daily_nav`，且具有可比對 `reference_date` 時，才可進入 canonical daily NAV。
- 2026-08-09：國泰 PCF 採官方清單 lookup 加 server-render PCF 頁共 2 requests；現金申贖摘要不宣稱具有實物籃子或基金持股。
- 2026-08-09：frontend 保留 legacy response fallback 以支援 rolling upgrade，但新狀態與 applicability 只採 backend `valuation`／`resource_states`，不以 ETF 名稱自行推論。
