# Progress

## Status

- Current phase：Milestone 1-8 implemented, runtime-validated, and browser-verified
- Last updated：2026-07-19 10:48 +08:00

## Completed

- 依 live launcher/state/log 確認目前 frontend `3000`、backend `8400`，direct health 與 frontend proxy 正常。
- 量測 index summary、OHLC、indicators、Radar、institutional、shareholding 等關鍵 read path 的 cold/warm latency。
- 對照首頁 SSR、Taiwan tape、stock chart、data panel、ranking/Radar hook 與 backend service/job call chain。
- 確認首頁 20 秒等待的主因是 index summary cold/provider path，而不是固定 port 或 SQLite 基本查詢。
- 確認 K 線與法人本機 cache 很快，但 client effects 與 ensure/refresh contract 會把讀取升級成外部回補／job polling。
- 確認 group 3 Radar/ranking 涉及 83 檔、serialized batches 與隨後的全群組 refresh。
- 確認 TDCC shareholding refresh 有 scoped TLS certificate validation failure；TPEx index provider 有重複 transport failure。
- 讀取產品文件、backend architecture、frontend instructions 與既有 `frontend-backend-stability-20260718` 任務。
- 判定本專案應獨立於 connectivity/readiness stability 批次，避免混合已完成變更與新的 market-data contract。
- 建立本任務 `Prompt.md`、`Plan.md`、`Baseline.md` 與 `Progress.md`。
- 完成四份任務文件的 UTF-8 讀回、必要章節與 scoped whitespace diff 檢查。
- Taiwan index summary GET 改為本機／shared cache read，加入 `cache_status`、`refresh_recommended`、`warnings`，外部 provider refresh 由 explicit POST/job 擁有。
- 新增 index summary background refresh job，保留既有同步 refresh route相容性，並讓 frontend只在 cache建議更新時排一次背景 job。
- 首頁 SSR不再同步計算 Radar；Radar GET優先重用既有 persisted snapshot，回傳 snapshot id、日期、計算時間與 cache status。
- 排行批次由每批3檔收斂為20檔，移除 ranking load完成後自動啟動83檔全群組 refresh的 effect。
- 台股 K 線 read一律使用 `ensure_history=false`；backend與frontend都在 chart boundary正規化日期順序與唯一性。
- 法人、籌碼、分點、營收與財報 tab改為先讀本機 cache；只有使用者按下「更新資料」才執行 provider-backed selection refresh。
- 移除選股／component mount自動執行 basic selection refresh，避免每次切股造成 job polling與 chart reload。
- Backend job enqueue加入 process-local atomic active dedupe與 recent-success cooldown；selection、group latest與 index refresh都使用明確 cooldown。
- TDCC改用僅限 `www.tdcc.com.tw` 的 verified TLS session，只放寬 OpenSSL `VERIFY_X509_STRICT`，仍保留 `CERT_REQUIRED`與 hostname verification。
- 共用 HTTP client對 `https://www.tpex.org.tw/` mount相同的verified compatibility adapter，修復TPEX OpenAPI在目前Python/OpenSSL的`Missing Subject Key Identifier`，不影響其他host。
- 股權分散週資料加入保守的 Friday expected-date規則，source health不再把數月前資料只標成 available。
- Provider HTTP wrapper加入 scoped request transport injection，不改變其他 provider的預設 session／錯誤分類。
- UI新增市場指數 cache、Radar snapshot與資料 tab手動更新狀態；breadth契約新舊 runtime短暫錯位時採 defensive rendering，不讓整頁崩潰。
- 盤後／休市 Radar request不再附帶等同預設值的技術參數，讓 backend可以命中每日 snapshot；盤中即時模式仍保留 explicit calculation參數。
- 盤後 Radar snapshot與ranking改為並行啟動，不再等待第一批ranking完成後才開始；盤中computed Radar維持原本延後策略，避免和首批ranking爭用資源。
- 更新中心badge只彙總每個`job_type + target`的最新工作，並以explicit error count與可見failed items的較大值計數；歷史部分完成仍保留在展開明細，不再重複堆入首頁badge。

## Validation evidence

- Runtime topology：launcher state 與 log顯示 frontend `127.0.0.1:3000`、backend `127.0.0.1:8400`。
- Direct/proxy health：HTTP 200。
- Frontend log：同日多次 `/api/market/indices/summary` 20,000 ms timeout；page request 21.9–24.6 秒。
- Direct probes：index summary cold約 5.7 秒、warm約 5 ms；2330 OHLC約 8 ms、indicators約 24 ms、institutional約 8 ms；group 3 Radar約 1.6–5 秒。
- Recent jobs：group 3 refresh requested 83、refreshed 73、errors 10、sleep 5 秒；chips refresh因 TDCC shareholding TLS failure 呈 partial。
- Source-health/data probes：2330 daily price與 institutional最新 2026-07-17；shareholding local最新 2026-05-29。
- Code search：確認 initial SSR、`ensure_history`、selection refresh、group refresh、ranking batches 與 E2E interception surface。
- UTF-8 readback：4/4 文件無 replacement character，全部以 newline 結尾。
- Scoped `git diff --no-index --check`：4/4 文件無 trailing whitespace、space-before-tab 或 blank-line-at-EOF。
- Repo default `git diff --check`：通過；未修改既有 dirty worktree 的其他檔案。
- Backend targeted regression第一輪：`56 passed, 28 subtests passed`，涵蓋 provider HTTP、TDCC transport、job dedupe、OHLC invariant、Radar snapshot、source health、index summary與 API inventory。
- Backend index/Radar重驗：`50 passed, 28 subtests passed`。
- Backend HTTP/TPEX/index重驗：`52 passed, 34 subtests passed`。
- Frontend：`npm run lint`通過；`npm exec tsc -- --noEmit --incremental false`通過；`npm run build`通過（Next.js 16.2.6）。
- Explicit index refresh job：入列 85 ms，job `3834`成功；完成後 summary read 64 ms並回傳 `memory_cache`，45秒 cooldown重送 26 ms取得同一 job id。
- Explicit chips refresh job：入列 73 ms，job `3835`約10秒完成，法人／融資券／分點／股權分散4/4成功、0 error。
- TDCC live smoke：補抓7個缺少週次、插入105筆；2330 shareholding由2026-05-29更新到2026-07-17，source health由 stale、lag 49天轉為 current、lag 0天。
- 10次 direct cache probe p95：OHLC 58 ms（27,101 bytes）、institutional 92 ms（67,858 bytes）、Radar snapshot 51 ms（36,913 bytes）。
- 10次 frontend proxy probe p95：OHLC 66 ms、institutional 698 ms、Radar snapshot 124 ms；測試前後 latest job id皆為3835，GET未隱性建立 job。
- Runtime page benchmark：修正 rolling-contract crash並重啟一致 runtime後，10/10 HTTP 200、0 failure、p95 951 ms；基線為21.9-24.6秒。
- TPEX live smoke：官方`mainboard_quotes`回傳1,013筆，OMI普通股篩選後為868檔；修正後breadth為上漲58、下跌785、平盤25，資料日2026-07-17。
- Current index contract：refresh job `3836`成功；TAIEX breadth ready（1,091檔）、TPEX breadth ready（868檔）、summary warnings為空。
- In-app Browser desktop smoke（1280x720）：首頁無Next/Vite error overlay、console error為0；2330 stock header與2600根日K繪圖約911 ms可用。
- Radar browser benchmark：修正前完整結果約4,725 ms；改用snapshot並與ranking並行後約1,847 ms，畫面明確顯示`資料日 2026-07-17 · 快照 2026-07-17`。
- Radar direct comparison：相同83檔group的computed endpoint連續3次約1,540-1,690 ms；default-contract snapshot endpoint約46 ms。
- Data tab interaction：法人約305 ms、籌碼約299 ms顯示cache資料，資料日皆為2026-07-17；「更新資料」按鈕可見且enabled，切換後console error仍為0。
- 更新中心browser smoke：修正前badge把最近20筆歷史錯誤累加為23；修正後只顯示最新group refresh的10筆失敗，最新2330 selection與index refresh成功狀態不再被舊紀錄覆蓋。
- Frontend safe validation：`frontend lint`、`frontend tsc`與`git diff --check`全部通過，log位於`.tmp/validation/20260719-104637`。

## Decisions made

- 不延長 timeout作為主要修復；要拆開 cache read與 explicit refresh。
- 不把 provider failure隱藏成空資料；cache-first畫面仍需顯示 freshness與 resource-level warning。
- 不讓 component mount擁有 refresh唯一性；dedupe移到 backend job/policy boundary。
- 不讓 Radar GET隱性建立 snapshot；優先重用既有 automation/outcome persistence。
- TDCC TLS只接受 scoped trust或官方介面修復，不接受全域關閉 certificate verification。
- 台股先驗收，避免一次擴張到 US/JP/KR/Crypto。
- Radar只有在default calculation parameters時自動重用snapshot；custom MA、volume window或threshold仍走即時計算，避免錯用不同參數的快照。
- 盤後／休市前端使用default Radar contract以重用已保存snapshot；盤中需要即時疊加時才送explicit parameters並走computed path。
- 使用者操作才是個股資料 provider refresh邊界；自動流程只讀cache並顯示stale/missing狀態。
- 使用者解除視覺操作限制後，僅使用in-app Browser操作localhost OMI頁面完成desktop smoke與截圖驗證，未接管其他瀏覽器分頁。

## Known issues / risks

- Worktree仍有大量其他進行中的既有修改；本任務沒有revert、commit或push，交付前需由整體owner決定如何切commit。
- Job enqueue的atomic lock保證單一backend process；若未來改成多worker／多instance，需把dedupe唯一性提升到DB constraint或distributed lock。
- TPEX TLS compatibility policy目前依賴host-scoped adapter；若官方更新certificate chain，可移除相容flag，但在此之前仍維持CA與hostname驗證。
- Runtime benchmark為本機Next dev mode與目前SQLite資料量，不等同跨機器production SLA；但相同環境的before/after已有可重複證據。
- Radar snapshot目前沿用既有automation保存內容；未新增第二套table。後續若要支援custom params snapshot，需先加入params version/fingerprint。
- 更新中心目前仍正確顯示latest group 3 refresh的10筆失敗；要清除此狀態需另外執行一次83檔group bounded refresh，依驗證規則不在本次browser smoke中自動觸發大量provider request。

## Next step

- 若要把更新中心的latest group 3失敗數清為0，下一步可在明確確認後重跑一次bounded group refresh並重驗83檔coverage；其餘K線、Radar、法人與籌碼read path已完成browser驗收。
- 後續架構批次仍優先建立multi-process job dedupe與custom-parameter Radar snapshot fingerprint，而不是再增加frontend timeout。
