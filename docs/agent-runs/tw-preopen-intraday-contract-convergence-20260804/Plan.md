# 台股盤前／盤中契約收斂與實盤驗收計畫

## 執行原則

- 順序固定為「保全現況 → 失敗案例 → 共用 session/freshness → persistence／
  continuity → indices／aggregate → health → NLU／refresh → consumers → runtime」。
- 不按 11 個 issue 各自加 if/else；同一語意只能有一個 canonical owner。
- 每個里程碑先建立 deterministic failing test，再修改 production behavior，
  focused regression 全綠後才進下一階段。
- 2026-08-03 breadth v2 未提交修改是現況基線。進入任何重疊檔案前先讀現有
  diff，保留其 session、coverage、legacy isolation 與 migration 行為。
- 預設不新增 DB migration、不重啟正式 runtime、不寫正式 DB。若證據顯示
  projection／read-time eligibility 不足，先更新本計畫再做 schema 決策。
- 每完成一個里程碑即更新 `Progress.md` 與 `IssueMap.md`，記錄驗證、決策、
  未解風險與 live acceptance 狀態。

## 依賴順序

```text
M0 Baseline / reproducible failures
  -> M1 Canonical session + observation-aware freshness
    -> M2 Session-bound persistence + continuity
      -> M3 Market indices + aggregate freshness
        -> M4 Source health + TXF capability
          -> M5 NLU + refresh reconciliation
            -> M6 Public consumers and compatibility
              -> M7 Safe regression and isolated runtime
                -> M8 Production rollout and live-session acceptance
```

M4 與 M5 在 M0 完成後可分別分析，但目前 worktree 有大量重疊修改，預設仍採
單線實作與單一檔案 owner，避免同時改 AI projection／capability contract。

## 里程碑

### M0：基線保全、owner 對照與失敗案例

#### 範圍

- 記錄 `2d0476d + current dirty diff` 的檔案清單、breadth v2 owner 與本任務
  可能重疊區，不要求使用者先 commit，也不建立第二個 worktree 假裝乾淨。
- 將 2026-08-04 的 preopen、09:00、09:16、stale health、TXF 與 NLU 案例
  固定成小型、去識別、無外網 fixture。
- 為 001～006、008～010 建立會失敗的 regression；007、011 先建立 contract
  characterization，證明現況歧義再鎖定新欄位語意。
- 確認既有 7/30 CASE-01～10 與 8/3 breadth v2 tests 仍是必跑 regression。

#### 預計修改面

- `backend/tests/` 中現有 realtime、data quality、market projection、source
  health、decision core、futures 與 outward contract tests。
- 新增專用 `test_tw_preopen_intraday_contract_acceptance.py`，或沿用 repo 最接近
  的 acceptance 命名；不建立大型 raw payload dump。
- 僅在需要時新增 `backend/tests/fixtures/` 的精簡 JSON。

#### 驗收

- 每個 issue 都能在固定 `now`、固定 trade date、無外網、無正式 DB 下重現。
- Fixture 同時保存 raw phase、event time、observation kind、semantics 與預期
  public outcome，不能只保存最終 projection。
- 測試失敗訊息能指向 session alias、interval policy、fallback、aggregate 或
  NLU owner，而不是 generic `quality != ready`。
- 現有 breadth v2 行為沒有被新 expected value 改寫。

#### 驗證

- 新 acceptance test 單檔執行。
- 7/30 intraday acceptance 與 8/3 breadth session contract targeted tests。
- `git diff --check`。

#### 停止條件

- 無法分辨 raw provider observation、persisted row 與 public projection 時，先
  修 fixture schema，不進 M1。
- 發現 current dirty diff 與既有任務文件不一致時，先更新 `Progress.md` 並
  完成 ownership audit，不以 reset 解決。

### M1：Canonical session 與 observation-aware freshness

#### 範圍

- 盤點並重用現有 Taiwan session primitive；若目前沒有單一 owner，建立 pure
  `normalize_taiwan_session_phase` 等價 resolver。
- Resolver 同時輸出 raw phase、canonical phase、market session、auction
  relevance 與 observation phase，不讓 `realtime_contract`、
  `taiwan_projection` 各維護一份 alias set。
- 建立 observation-aware freshness：至少區分 quote/depth、auction indication、
  partial 1m、finalized 1m、daily official close、health snapshot。
- Bar freshness 使用 event time、interval、bar boundary、partial/finalized 與
  provider delay budget；不用 quote 的秒級 age threshold 直接判 1m。
- Policy compliance、facts/research usability 與 execution-grade usability 分離。
- `market_session` 與 `observation_mix` 分離，處理 09:00 handoff。

#### 預計修改面

- `backend/app/ai/realtime_contract.py`
- `backend/app/ai/data_quality_contract.py`
- Taiwan session/calendar 的既有 pure helper。
- `backend/app/ai/market_context/taiwan_projection.py`
- 必要的 outward capability quality projection。

#### 驗收

- `preopen_auction` quote depth/facts 在 TTL 內 current，auction capability
  relevant；actual trade／execution-grade 仍 unavailable/false。
- closing auction 與 post-close 不因 preopen 修正而回歸。
- 31 秒級 1m observation 在合理 interval window 內可供 intraday research；
  真正超過 interval + provider budget 的 bar 仍 stale。
- `require_live` 不滿足時可 blocked，但已取得的 usable facts 不被清空。
- 09:00 mixed observations 不把 authoritative `market_session` 變成 `mixed`。
- 001、002、004 的新 tests 與既有跨市場 shared-contract regression 通過。

#### 驗證

- Realtime/data-quality pure tests。
- AI market projection、decision envelope、public v4 targeted tests。
- 受 shared resolver 影響的 US/JP/KR smoke regression。

#### 停止條件

- 任一 consumer 仍需自行判斷 `preopen_auction` 或 1m tolerance，先回到共用
  resolver，不在 consumer 加例外。
- 新 quality 欄位若與 `evidence.capability_status` 形成第二套 readiness，停止並
  收斂 projection。

### M2：Session-bound 成交值與 continuity boundary

#### 範圍

- 建立 pure trade-value eligibility：以 trade date、canonical phase、event
  time、semantics、authority 與 estimate flag 決定能否作 current-session
  cumulative value。
- 移除盤前對 daily `item.trade_value` 的無條件 fallback。
- Regular intraday 只接受 current-session actual observation 或明確估算；
  post-close 只接受同交易日 official value。
- 既有錯誤 preopen row 不刪除；reader 依 semantics/date/phase 隔離，對外回
  unavailable 或 legacy-invalid warning。
- Continuity 先依 trade date、session segment、午間/收盤邊界與 trading
  calendar 切段，再在段內計算 missing interval 與 median interval。

#### 預計修改面

- `backend/app/market/taiwan_market_state.py`
- `backend/app/ai/data_quality_contract.py`
- `backend/app/market/trading_calendar.py`
- `backend/app/ai/market_context/taiwan_market.py` 的 reader/projection glue。
- Market-state persistence、continuity 與 outward tests。

#### 驗收

- 08:50～08:59 無 current-session成交證據時，累積成交值為 null/unavailable，
  不出現前一交易日 1 兆級數值。
- 09:00 後數值的 `observed_trade_date`、`event_time`、semantics、estimate、
  authority 同時可見。
- Post-close official value 不被盤前規則錯誤遮蔽。
- 跨夜、週末、休市、已知 session gap 不計 missing；同一 regular session
  真正缺一根仍被抓到。
- 不新增 production DB rewrite；舊 row count 不變。
- 003、005 與 breadth v2 persistence regression 通過。

#### 驗證

- Market-state、calendar、continuity、AI projection targeted tests。
- 若 reader 測試需要 DB，只使用 transaction rollback／暫存 SQLite／正式 DB
  副本，不寫唯一 production DB。

#### 停止條件

- 現有欄位無法辨識 legacy wrong value 時，先提出最小 additive migration、
  copy migration、downgrade 與 rollback 設計；未審議前不直接改正式 schema。

### M3：Market indices 與 aggregate freshness 契約

#### 範圍

- 將 index current-session snapshot 與 completed daily official close 分成兩種
  component，保留 `market.indices` 作相容 composite。
- Regular session 優先使用 eligible `taiwan_index_minute_snapshot`；若只有 daily
  close，明確標示 previous completed session、fallback reason 與
  `current_for_requested_session=false`。
- 稽核是否需要 additive `market.indices.live`／
  `market.indices.official_close` capability；沒有 consumer 必要性時不增加
  registry 複雜度。
- 重構 `data.freshness` aggregate，分離：
  - temporal currency
  - requested-session alignment
  - completeness／coverage
  - oldest/newest required as-of
  - mixed date/time
  - capability-level as-of
- 保留現有 `status`／`is_current` 相容語意，新增欄位前先做 consumer audit；
  不建立「partial 一律不 current」的錯誤規則。

#### 預計修改面

- `backend/app/market/indices.py`
- `backend/app/ai/market_context/taiwan_market.py`
- `backend/app/ai/market_context/taiwan_projection.py`
- `backend/app/ai/capability_contract.py`
- Public v4 schema/snapshot 與 index/freshness tests。

#### 驗收

- 盤中有 current index snapshot 時顯示其 event time／synthetic/finalized／source；
  沒有時 daily close 只作 reference。
- TAIEX/TPEX 可個別 partial；combined 不用單一最新 timestamp 掩蓋舊 component。
- `partial + is_current=true` 在「已取得資料夠新但 coverage 不完整」時合法；
  若 required index 只屬前一 session，`current_for_requested_session=false`。
- Top-level `as_of` 有明確 semantics，oldest/newest/mixed 欄位能揭露混合日期。
- Frontend/MCP 不必自行比較 capability dates 才知道 readiness。
- 006、007 與既有 market indices/breadth/outward contract regression 通過。

#### 驗證

- Market index daily/minute、AI market projection、capability contract、public
  outward snapshot targeted tests。
- 固定 08:59、09:00:30、09:17、13:31、post-close 時鐘案例。

#### 停止條件

- 需要改變既有 capability ID 或移除欄位時，停止並提出 versioned compatibility
  設計；不得直接破壞 `omi.decision.v4` caller。

### M4：Unified source health 與 TXF capability

#### 範圍

- 讓 AI `source_health_context` 重用 `provider_health` 的 row age、stale、TTL
  與 serialization 語意，避免 system API 與 AI 各算一套。
- Aggregate 只對本次 requested capability/target 的 required/active rows 計算；
  不以整個 Taiwan market 的 `MAX(checked_at)` 代表整體 current。
- 分離 request-local success、persisted snapshot、effective health 與 snapshot
  freshness；direct reader success 可優先，但 persisted expiry 警告仍保留。
- 舊 target/resource row 不刪除；投影 active／expired／historical lifecycle，
  history/detail 與 readiness aggregate 分開。
- 稽核 TXF 現有 provider events、stored source health 與 futures reader：
  - 有可追溯、scope 正確資料：實作 `diagnostics.source_health` payload。
  - 沒有：registry 對 TXF 回 `not_applicable` 與清楚 reason。

#### 預計修改面

- `backend/app/observability/provider_health.py`
- `backend/app/ai/market_context/source_health_context.py`
- `backend/app/market/source_health.py`
- Taiwan stock/futures context、capability registry 與 outward tests。

#### 驗收

- 每個 unified health row 都有 `checked_at`、age、stale 與 lifecycle。
- 大量 expired rows 不會被一筆新 snapshot 掩蓋成 overall current。
- Requested target 的 direct reader success、persisted expiry 與 effective status
  可同時表達且不互相覆寫。
- GET/source-health/AI read path 不寫 DB、不 prune、不啟動無界 refresh。
- TXF 不再是 applicable + semantic payload empty。
- 008、010 與 provider-health/source-health/runtime ownership regression 通過。

#### 驗證

- Provider serializer、AI context、market source-health、TXF outward contract tests。
- 使用 synthetic clock 驗 age threshold，不依執行測試當下時間。

#### 停止條件

- 若 lifecycle 必須新增 persisted 欄位，先證明 projection/filter 無法安全完成，
  再提出 additive migration；不得以 read path 刪舊資料。

### M5：Negation-aware NLU 與 refresh reconciliation

#### 範圍

- 找出 position context、risk intent、exit decision 與 query plan 使用的所有
  substring hint path，收斂到可重用 matcher。
- Matcher 只在鄰近 span 內套用 negation，並加入欄位／驗證語境排除；explicit
  caller intent 優先於 heuristic inference。
- 保留真正的風險問題、停損／續抱／減碼問題，不以全句含「不」就全部清除。
- `refresh_if_missing`／`allow_external_fetch` 維持 permission 語意，不自動執行
  所有 fill actions，也不在 GET path 引入副作用。
- Reconciliation telemetry 分開 refresh requested/allowed、primary reader、
  provider fetch、tracked tool run、cache hit、outcome、refreshed item count、
  error 與 not-attempted reason。

#### 預計修改面

- `backend/app/ai/decision_core.py`
- 相關 ask/query-plan/policy module。
- `backend/app/ai/decision_envelope_v4.py` 或現有 reconciliation owner。
- Taiwan reader telemetry、public v4 schema 與 AI tool-boundary tests。

#### 驗收

- 「只驗證資料，不做任何交易、持倉或風險判斷」不推論 position/risk intent。
- 「auction 欄位開盤後是否退場」不推論 exit position decision。
- 「請分析下跌風險」仍推論 risk check。
- Explicit intents 與 heuristic 衝突時，規則 deterministic 且有測試。
- 無 tracked tool run 時 `attempted=false` 仍可同時看見 reader/provider 是否
  嘗試；完全未嘗試則有 machine-readable reason。
- 不重新加入已移除或未註冊的 `tw.refresh_quote`／`tw.refresh_intraday`，除非
  另有完整 tool ownership 設計。
- 009、011 與 AI routing/tool-boundary/outward contract regression 通過。

#### 驗證

- Table-driven NLU tests，包含肯定、否定、雙重否定、欄位語境與真正風險詢問。
- Reconciliation tests 覆蓋 cache hit、reader fetch success、provider failure、
  no executable tool、policy denied。

#### 停止條件

- Matcher 若需靠大量特例才能工作，先抽出 typed span/result contract，不在多個
  intent function 複製 negation list。
- 若 refresh 修正會讓 GET/read path 新增外部 side effect，停止並保留 permission
  + telemetry 方案。

### M6：公開 consumer、snapshot 與文件相容

#### 範圍

- 將新 session/freshness/health/reconciliation 欄位投影到
  `omi.decision.v4`、backend API 與 repo MCP public snapshot。
- Frontend 只在使用者需要看見新狀態時補型別與呈現；不重算 freshness 或
  readiness。
- 保留 legacy fields／capability ID 的 additive compatibility，更新 generated
  schema/digest 與 contract docs。
- Standalone `C:\GPT_MCPtool\OMI_search` 只做 read-only parity audit；若需寫入或
  tray reload，另取得使用者授權。

#### 預計修改面

- Backend public schema、answer composer、capability contract。
- `agents/omi_mcp_server/public_contract_snapshot.json` 與 consistency tests。
- 必要的 `frontend/src/types/market.ts`、OMI dock／market panels、i18n。
- API／product contract 文件。

#### 驗收

- REST、AI、repo MCP 對同一 evidence 回傳一致 phase、as-of、freshness、health
  與 limitation。
- Frontend 不把 previous close 顯示成 live、不把 `partial` 隱藏、不依本地日期
  比較重新判斷 readiness。
- MCP adapter 維持 thin，不讀 DB、不 import backend market logic。
- Public digest 與 snapshot generator/test 一致。
- 既有 caller 不因 additive fields 失敗。

#### 驗證

- Public v4、answer composer、MCP snapshot consistency targeted tests。
- 若 Frontend 有 TypeScript 修改：lint + tsc；只有 UI 行為實際變更才加 build/
  browser screenshot。
- Repo MCP protocol：`initialize` → `tools/list` → representative `omi.ask`。

#### 停止條件

- Consumer 若仍需自行選 live vs daily index、計算 snapshot age 或解釋
  `attempted=false`，退回 backend contract 修正。

### M7：Safe regression 與隔離 runtime

#### 範圍

- 合併執行 001～011 targeted suites、7/30 intraday acceptance、8/3 breadth v2、
  AI outward、source health、TXF、Radar 與 MCP regression。
- 執行 backend safe profile；Frontend 有修改才跑對應 profile。
- 使用隔離或 launcher-aware runtime 驗證，不先假設固定 port。
- 如有任何 migration，先在 DB 副本完成 upgrade/downgrade/upgrade、row count、
  quick_check；預設本任務不應需要 migration。

#### 驗收

- 所有 targeted tests 與 safe profile 通過；失敗不得用 skip、放寬 assertion 或
  expected-value 洗掉。
- Runtime source、venv、PID owner、selected backend/frontend ports、DB revision
  與 public digest 一致。
- REST／AI／repo MCP representative payload 沒有跨層 drift。
- Validation 不啟動無界 provider refresh、不改寫唯一正式 DB。

#### 驗證

- `.\scripts\run-safe-validation.ps1 -Profile backend`
- 若 Frontend 有修改：`.\scripts\run-safe-validation.ps1 -Profile frontend`
- 必要時在短時隔離 runtime 做 health、readyz、AI tools、AI ask 與 repo MCP
  smoke。

#### 停止條件

- Worktree ownership、runtime source、DB migration 或 selected port owner 任一
  不明時，不進正式 restart。
- Safe profile 發現共享 contract regression，回到對應 milestone 修正。

### M8：正式 rollout 與交易時段驗收

#### 範圍

- 在 source、tests、digest 與 DB safety 都穩定後，以正式 launcher 流程重啟。
- 依時段採 bounded capture；保留 raw phase/event time、DB row、REST、AI 與
  repo MCP 對照，不做全市場大量手動 refresh。
- 每一時段把 `IssueMap.md` 的 acceptance 標為 passed／failed／not observed，
  failed 時停止 closeout 並回到 canonical owner。

#### 驗收時段

1. 08:50～08:59 preopen：001、002、003、007、008、009、011。
2. 09:00～09:02 first-trade handoff：001、002、003、004、006、007。
3. 09:05～09:20 stable intraday：004、006、007、008、010、011。
4. 13:24～13:31 closing auction／close：001、002、003、006、007。
5. Post-close + overnight replay：003、005、006、007、008。

#### 驗收

- `Prompt.md` 完成定義逐項有 evidence。
- 正式 backend、frontend、DB、repo MCP 來源一致；launcher log 有新的
  `selected=` 與 process ownership 證據。
- 盤前不再出現 yesterday cumulative trade value；盤中 index/freshness 不再
  把 previous close 冒充 current；source health 不被單筆新 row 掩蓋。
- NLU 與 refresh telemetry 在 public `/api/ai/ask` 與 MCP `omi.ask` 一致。
- 尚未實際遇到的 provider edge case 明確標 `not observed`，不能用 fixture
  宣稱 live passed。

#### 停止條件

- 正式 runtime digest/source 不一致、provider semantics 無證據、DB 出現意外
  寫入、或任一 P0 correctness issue 重現，停止 rollout 並保留證據。

## Issue 對應里程碑

| Issue | 主要里程碑 | 回歸面 |
| --- | --- | --- |
| 001 | M1 | realtime/session/public capability |
| 002 | M1 | Taiwan auction projection |
| 003 | M2 | market persistence/reader/AI |
| 004 | M1 | interval freshness/require-live |
| 005 | M2 | continuity/calendar |
| 006 | M3 | index service/market projection |
| 007 | M3 | aggregate freshness/public v4 |
| 008 | M4 | provider serializer/unified health |
| 009 | M5 | decision routing/query plan |
| 010 | M4 | futures context/capability registry |
| 011 | M5 | reconciliation/reader telemetry |

## 全域 stop-and-fix 規則

- Source、DB、API、AI、MCP、Frontend 對同一 observation 的 phase、time、
  semantics、freshness 或 readiness 不一致，停止下游工作並修 canonical owner。
- 發現 `pz`、previous close、daily turnover、synthetic snapshot 被當 actual trade，
  立即停止，不以 confidence/warning 補救錯誤語意。
- 發現 read path 寫 DB、prune history、啟動全市場 refresh、昂貴 backfill、
  report/memory write 或付費 quota，立即停止並回到 bounded job ownership。
- 發現 migration 需要刪表、重建正式 DB、不可 downgrade 或不能在副本重放，
  不部署。
- 發現 shared contract 影響其他市場，先補 regression 或加 market-scoped input，
  不用 consumer 特例繞過。
- 不 revert 使用者／既有任務修改，不使用 `git reset --hard`、force push 或
  未授權 commit/push。

## 決策紀錄

- 2026-08-04：新建本 follow-up task；不覆寫 7/30 intraday 或 8/3 breadth
  歷史文件。
- 2026-08-04：001、002、004 共用 session/observation resolver；不採三處 alias
  patch。
- 2026-08-04：003 優先 read/write eligibility 修正與 legacy quarantine，預設
  不做 historical DB rewrite。
- 2026-08-04：006 保留 `market.indices` 相容 composite，live 與 official close
  分 component；新增 capability ID 需 consumer audit。
- 2026-08-04：007 保留 freshness、coverage、completeness 正交；
  `partial + is_current=true` 不是一律錯誤。
- 2026-08-04：008 重用 system provider-health serializer/TTL，AI 不另建 age
  規則；aggregate 不再以 market-wide max timestamp 代表整體。
- 2026-08-04：010 必須 supported payload 或 not-applicable，禁止 semantic empty。
- 2026-08-04：011 不把 refresh permission 改成強制 side effect；以 telemetry
  分層解決可觀測性。
