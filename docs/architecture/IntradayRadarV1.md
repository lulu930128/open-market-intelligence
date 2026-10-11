# Intraday Radar v1

Intraday Radar 的 M0/M1 是 backend market-owned、cache-only discovery 與 deterministic
candidate service seam。Source acceptance 與正式 runtime、live、product acceptance 分開。
尚未新增 HTTP／AI capability、排程或外部通知；不共用 Radar v2 scoring。

## 既有 owner 與缺口

`providers/twse_mis_current_breadth.py` 已經以 active TWSE／TPEX ordinary-stock universe
做 bounded bulk quote batches；受既有 timeout、guard、cache 與 missing-z rescue budget 管理。
`jobs/scheduler.py::collect_taiwan_market_breadth_summary` 經 current-market refresh、receipt
lineage attachment 後，交給 `tw_intraday_state.py::persist_taiwan_intraday_stock_states`。
這是現有 full-market lightweight producer，不是 Tier-A per-symbol Base-1m producer。

收到全市場 responses 不代表每檔都有合法 actual-trade price。只有 volume、沒有成交價的
observation 保持 unavailable；不得改用試撮價、零值或無限逐股 repair。既有 provider／
Canonical／Resolver 仍擁有來源選擇與資料有效性。

## 讀取與 coverage

Screening 與 discovery 共用 `read_taiwan_intraday_stock_states`，從 active ordinary-stock
master 讀 current-session lightweight state，不依賴 holdings、watchlist、lease 或 Tier-A。
Discovery 沿用 `tw_intraday_state` eligibility、calendar 與 freshness policy；不另設 TTL。
相同 event time 以 state id 穩定選擇，不建立新的 provider priority。

`tw_intraday_radar_contracts.py` 是 typed outward service truth：

- `universe_count`：active TWSE/TPEX stock denominator，附 universe revision。
- `observed_count`：evaluation 時點已可取得的 current-session state。
- `coverage_count`：canonical breadth-usable 且有 lineage 的 observations；合法 no-trade
  可計入，成交但缺價不計入。不是單純計算 DB rows。
- `ranking_eligible_count`：可做 factual day ranking；與 current momentum 的
  `research_eligible_count` 分離。
- `coverage_ratio < 0.95` 必為 partial／blocked；完全無 usable coverage 為 blocked。
  `is_full_market` 只在 100% usable coverage 才成立。ready 不代表每檔都有可排名成交。
- 保留最早／最新 price as-of、receipt freshness distribution、逐股 missing／exclusion reasons。
  Factual ranking 不因較舊 last trade 就消失；candidate 必須通過既有 current research gate。

最新 state 不是歷史資料庫。晚於 evaluated_at 的 event／receipt 不得倒灌，缺少舊版本時
回 missing；不能用目前 state 重建過去市場。Replay 必須逐步送入當時可見 observations。
Reader 禁止 autoflush caller WIP；不 fetch、repair、enqueue、lease 或 write。

## Features 與 candidate gate

Feature v1 使用現有 state 的百分比與 rolling reference 公式；1/3/5/15 分鐘基準只能
在目標時間之前，沿用既有 90 秒最大 reference gap。Rolling sample 要有 actual-trade
contract、event／receipt、lineage，且 receipt 不晚於 evaluation。缺值為 null + reason。
新 samples 使用 `tw.trade_sample.v2` 保存真正 receipt clock；舊 v1 把 event clock 當 receipt，
Radar 不接受它作 point-in-time return reference。既有 Price Map sample reader 接受 v1/v2，
不改其原用途；無 DB rewrite，rolling buffer 由正常 producer 逐步換新。
高低位置要求正數且 low <= current <= high；range 的分母是 previous_close。
RVOL@Time 與 volume_velocity 目前沒有足夠 baseline／series，明確回 null，不假造。

Candidate 使用 versioned config 與 SHA-256 config hash。Day change、3m momentum、
接近日高及基本累計量共同決定入選；strength、timing、quality 分開。順序是穩定 identity
order，不是投資吸引力評分，不把接近漲停當成更值得追。Evaluation identity 納入完整
discovery evidence、universe、版本、時間及 config，來源修訂也會失效。

Partial scan 仍可回 individual candidates，但每個 candidate 與 result 保留 limitations，
result 必須攜帶 coverage。Candidate 不是 entry signal，也不產生任何 acquisition side effect。

## Two-tier 與後續 gate

Full-market lightweight state 負責 discovery；既有 Tier-A／lease／canonical demand 負責
深度 acquisition。M1 只交付 candidate，尚未自動 escalation；未把全市場送入 1m materializer。
M2 event lifecycle、candidate escalation budget／lease admission、durable replay evaluation、
producer coverage SLA、runtime adoption、live 與 product acceptance 都仍未完成。
本輪無 schema 變更，沿用現有 bounded samples storage，無需 migration。

Golden fixture 的 6442 價格／量來自 2026-10-07 本機持久化早盤 bars；以 bar end 模擬
lightweight receipt，其他 universe members 為 synthetic controls。這驗證來源可用時的
早期 selection，不能證明當日 producer 在該時點確實交付了 observation。

## Production coverage blocker

2026-10-07 唯讀取證的 receipt 621552 已在 parsed component 標記 6442
`ACTUAL_TRADE_PRICE_MISSING`（2,489 張），該次 bounded rescue skipped；原始 MIS
msgArray 未留在該 receipt，不能據此斷定 wire-level parser bug。Fixture
`6442_20261007_missing_price.json` 凍結負向案例；原 parser owner regression 驗證缺價
不以 O/H/L、indicative 或 volume 補價，合法正式 z 則可通過。
Production producer 的價格覆蓋與 latency 問題仍未解除，須有 bounded original-message
與 acquisition evidence 才能安全決定修復；M0/M1 checkpoint 未變更其 quota／timeout／rescue policy。

M0/M1 source checkpoint：sample v2 Radar／producer suite 35 passed、鄰近 platform／
contract／scheduler／Price Map suite 60 passed，golden 首次 09:04。Architecture checker
與 tests 通過。其他 intraday/preopen regression 的 33 個 reader_profile assertions 在
修改前 state source 亦可重現，未因本輪修改 AI 邊界；詳細 batch 與 baseline 證據留在
本地 active exec-plan。這個 checkpoint 不構成 runtime、live 或 product accepted。

驗收標記：**Source accepted / Live not accepted**。Source accepted 涵蓋上述
M0/M1 foundation／skeleton，以及下列 M0.5 source tests；TWSE MIS missing-z production coverage
blocker、M2、candidate escalation、RVOL 及 Runtime／Product gates 仍未完成。
本輪沒有 restart、provider IO、production DB mutation、commit 或 push。

## M0.5 Full-Market Observation Reliability

唯一 consumer-visible diagnostics owner 仍是 Shared Market Data 的
`BreadthAcquisitionDiagnostics`／`BreadthRescueDiagnostics`；只追加可省略的
`receipt_evidence_id`／`receipt_evidence_version`，舊資料與其他 provider 不需提供。
`tw_breadth_acquisition_contract.py` 僅定義 provider-internal RawResult receipt schema
`tw.mis.breadth.acquisition.v1`，不擁有 freshness、eligibility 或 readiness。
Architecture rule `tw_breadth_receipt_evidence_internal` 禁止 Shared Market Data、AI、router、
external adapter 與 Radar/discovery imports 這份 internal contract／IO helper。

既有 `twse_mis_current_breadth` producer 記錄 acquisition ID、venue、trade date/session、
start/finish、每批 requested/returned/eligible/actual-z/missing-z、duration、error/timeout、
receipt/event range、budget 與 rescue count/skip reasons。既有 CurrentBreadthAdapter
把它放入原 RawFetchResult receipt body，由原 transaction owner 持久化；沒有新增資料表。
`tw_current_market_repository.inspect_breadth_acquisition_receipt(db, raw_result_id=...)`
是 explicit internal inspect seam，唯讀、`no_autoflush`，補上 raw ID、receipt ID 與 content hash。
失敗 attempt evidence 與 last-good observation 分開，cache hit 沿用原 acquisition ID。

儲存上限為 20 scan batches + 1 rescue batch，每批最多 3 個 missing-z examples；只保存
13 個 allowlisted fields，各值最多 96 字元。Digest 的對象是分類前原始 message objects，
不是 HTTP wire bytes；完整 msgArray 不進 outward state。批次 delay distribution 使用
event-to-receipt 秒數，不把較舊 last trade 誤稱為 transport latency；request duration 另列。
每檔 batch receipt 保留到 stock-state lineage／sample v2，aggregate receipt 不覆蓋它；
event time 也保留各檔原值。6442-like 有量無 z 的 receipt 維持 unavailable，後續合法 z
只恢復後續 state，不回填先前 evaluation 的缺口。

Acquisition `requested_symbol_count` 是 scan 實際嘗試的 symbol 數，`returned_row_count`
是 scan 原始回傳列數，`eligible_stock_row_count` 是最後去重分類後 observed stocks；
`missing_z_count` 是原 scan 缺正數 z 的列數，包含 canonical valid-no-trade 與合法 cache
companion 的情況，並不等於最後 actual-price unavailable 數。Actual-price/no-trade 是
rescue 後結果，rescue attempt/success/failure/skip 另列並對帳。Universe-based ratios
附於 receipt；usable/ranking/research 與其 ratios 仍由既有 discovery eligibility 計算，
附 discovery evaluation time、universe revision 與 raw IDs。跨輪比對需使用這些 identities，
不可把 latest receipt 的 acquisition ratios 當作任意 evaluation 的 readiness。
Discovery usable coverage <95% 仍 partial/blocked；100% 才能宣稱 is_full_market。

### Budget 與 deliberate fractional rescue migration

- `scan_budget_seconds=20`、`rescue_max_budget_seconds=4`、`total_hard_deadline_seconds=20`
  （實際依既有 route 傳入較小 timeout 時縮小總額）。Primary scan 優先使用原額度，無固定預留。
- Rescue 只用 `min(4, deadline - now)`；準備、排序與 IO 共用 absolute monotonic deadline。
  移除舊 `floor(remaining)` 與 `<1` gate，0.8 秒可以執行最多一次 bounded rescue；0 秒
  完全不 fetch，記 `RESCUE_SKIPPED_BUDGET`。Backoff、guard、symbol cap、in-flight block
  與 request failure 都有 evidence；不做重試 storm。
- Code 已證明舊 main scan 可吃完整 budget，且 rescue 在它結束後才啟動；不能據此認定
  2026-10-07 production 缺價只有這一個根因。移除「main failed/skipped 就禁止 rescue」
  的過度限制，保留原 guard；rescue 成功不得清除主 scan 的 partial 狀態。
- 11 batches／19.184 秒 fake-clock replay：before/after requested/observed 均 1,100，
  最後一批不因固定 reservation 消失；剩餘 0.816 秒允許一次 rescue。成功案例總計
  19.684 秒，timeout 案例（含 0.25 秒準備耗時）維持 20 秒，未擴 route deadline。
- Requests/socket timeout 本身不能保證總牆鐘等待。Provider-local helper 每 venue 最多
  一個 daemon IO slot（合計最多兩個），不排隊、不疊 worker；超時後同 venue 明確
  `AcquisitionInFlight`，另一 venue 獨立，完成後恢復。晚到結果不改 cache/guard；
  active reset 拒絕，idle reset 可用。已進入 requests 的 socket 無法由 Python thread
  強制取消，可能在 caller timeout 後結束；期間同 venue fail closed，不另開 request。
  20 秒是 acquisition 的等待／request admission deadline，非 OS hard real-time 保證；
  少量本機排程／序列化尾端成本會反映在 elapsed/deadline_exceeded，不被隱藏。

既有 0.8 秒視為 exhausted 的 test 改為 0 秒，另以 timeout／429 參數化 cases 鎖住新
fractional contract，並驗證後續 backoff、skip/failure counts。Actual-z resolver 沒有變更；
不得用 pz、O/H/L、bid/ask、volume 或 1m bars 填補 z。

### 正式盤 Live acceptance contract（尚未執行）

先以另行授權的 runtime adoption 證明 loaded source，再在正式 regular session 逐輪留存
TWSE/TPEX acquisition ID、RawResult IDs、discovery evaluated_at 與 universe revision。
每輪及整段驗收窗口均報告以下資料，不得只選成功 receipts：

- Active universe/requested/observed/actual-price/missing-z/valid-no-trade/usable/ranking/research
  數量與比例；usable coverage >=95% 才通過 full-market readiness gate。
- Scan/rescue/total duration 的 p50/p95/max、deadline exceed 次數、receipt freshness
  distribution、event-to-receipt delay；latency/freshness 沿用原 canonical policy 判斷。
- Missing-z ratio，rescue candidate/attempt/success/failure/skip 與各 reason；成功率分母
  是 attempted，skip rate 分母是 candidate，不能把 no-trade 算成救援失敗。
- 6442-like 序列需量測 first missing-z receipt、first legal-z receipt、first discovery
  candidate 的時間差，保留當時 evidence；不能用後來合法 z 或 bar-derived replay
  改寫 earlier availability，也不能用 fixture 09:04 宣稱 production 09:04 已可發現。

Source tests 通過只證明 bounded observability、語意保護與可重現的 budget 行為；
正式盤 usable coverage、latency 與 missing-z production blocker 仍為 **Live not accepted**。

M0.5 最終 source checkpoint（2026-10-07）：**Source accepted / Live not accepted**。
最後 absolute-deadline patch 後 core 三檔 **18 passed**（18.67 秒）；先前 core checkpoints
17／14 passed，safe breadth 51 passed，current-market／Radar 69 passed，最後 provider
matrix 81 passed。全 architecture 38 passed，最後 boundary 重跑通過，checker PASS
（15 actual violations／15 declared debt），compileall 與 git diff --check PASS。
各批包含重複 tests，不相加當作 unique test count；命令與 log 位置見 active Progress。
本輪無 restart、provider IO、production DB mutation、Discord、commit 或 push，未實作 M2。
