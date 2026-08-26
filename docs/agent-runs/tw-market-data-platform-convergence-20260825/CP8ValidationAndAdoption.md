# CP8 Validation and Runtime Adoption Contract

## Source validation completed

- 0066 -> 0067 -> 0068 migrations與downgrade compatibility regression通過；legacy rows在測試情境保留。
- Actual TWSE daily、TWSE official index與TWSE MIS last-trade fixture在同一fresh file-backed SQLite完成persist；dispose engine模擬process restart後，再以新engine/session由Gateway讀回daily/index/breadth/quote。
- Cold read四個result均為Resolver `selected`、external calls為0、具raw receipt lineage；chart與dashboard stable projection亦從同一persisted evidence讀回。
- Migrated-capability legacy source inventory與current architecture docs已同步。
- 歷史Foundation/M5 checkpoint保持不可變；本任務以`artifacts/foundation-extension-checkpoint.json`疊加13個TW Data Core/common platform精確source hash，US integration hunk維持排除，dark-boundary 7 tests通過。
- Full safe validation `20260825-222211`通過：backend compileall、2280 backend tests、frontend lint、TypeScript、production build與`git diff --check`皆為passed。
- Backend suite成長後完整teardown需約310秒，safe-validation的bounded預設timeout由300秒調為420秒；先前300秒結果已印出2280 passed但被wrapper誤標timeout，未當成正式通過證據。

## Rollback rule

- 0067／0068是additive nullable schema。Production application rollback應保留已升級schema並退回上一版程式，不應在已有新canonical writes後立刻downgrade schema，因為移除lineage columns會丟失新row的直接FK linkage。
- Migration downgrade tests只證明legacy compatibility與emergency schema rollback可執行，不代表它是production首選。
- Technical engine有`TECHNICAL_CANONICAL_V2_ACTIVE=false` bounded rollback，既有test證明active contract與legacy path可切回。
- Data Core read失敗的安全rollback是capability unavailable／missing與保留persisted data，不是讓consumer重新call provider或復活snapshot-to-bar。

## Production adoption preconditions（已執行，F-07除外）

以下皆是material runtime mutation，source tests不能代替：

1. 確認正式DB backup/lock/runtime owner與目前Alembic revision。
2. 對production DB執行0067／0068 upgrade，不刪資料。
3. 以explicit bounded operations取得至少一筆具lineage的official index與public quote，並確認postcondition。
4. 只重啟OMI named backend/frontend runtime，從launcher log確認selected PID/port/interpreter。
5. 驗證health、Data Core catalog/health、daily/index/breadth/public quote與indicator APIs。
6. 驗證visible frontend chart/dashboard indicator authority與missing/partial presentation。
7. 驗證MCP `omi.ask`／decision v4 parity與cold restart readback。
8. 在台股active session另做F-07 public quote live acceptance；不得用recorded fixture補造。

使用者已於`2026-08-25`明確核准正式backup、0067/0068 adoption、bounded official/public acquisition、named launcher restart與API/UI/MCP/cold-read/rollback驗證。使用者先行重啟OMI後，launcher startup migration已自動將production DB由0066升至0068；agent未再手動重跑production migration。第1至7項已完成，第8項F-07因收盤後不可補造而維持pending。

## Read-only production preflight

- `2026-08-25 22:31 +08:00`：active DB為24.512 GiB、WAL/SHM存在、Alembic仍在`20260822_0066`，且檔案持續更新。
- 目前唯一named backup是2026-06-07的1.61 GiB檔案，時間與大小皆不足以作本次migration rollback point；正式採用前必須建立並驗證current consistent backup。
- Launcher selected backend為`127.0.0.1:8916`、frontend為`127.0.0.1:3000`；health與UI health均200，runtime identity來自repo `.venv`與frontend proxy target `8916`。
- Running process在10:41啟動，Data Core catalog與dataset health routes皆404，證明目前runtime尚未採用本輪source。
- 完整machine-readable evidence：`artifacts/cp8-production-adoption-preflight.json`。

## Production adoption result

- Offline current backup：`data/backups/open_market_intelligence-after-tw-data-core-auto-migration-20260825-223925.db`，26,334,392,320 bytes，SHA-256 `1b03b478c2c5b3969826a6a8321bc7e6119ff46d746d01f9fdde6bd51c3319d4`，revision 0068、`quick_check=ok`、FK violation 0。它是auto-migration後、bounded acquisition前的rollback point，不冒充不存在的pre-migration snapshot。
- Backup clone完成0068 -> 0066 -> 0068 rehearsal；5,170筆index、3,781筆quote與legacy unknown lineage均保留，FK 0、quick check ok。Temporary clone已移除，正式backup保留。
- 正式runtime由launcher PID 58996管理；backend listener `127.0.0.1:8916`、frontend `127.0.0.1:3000`，兩條ancestor chain均回到`omi-launcher.ps1 -LauncherAction Run`。Backend health/ready與DB check、frontend UI health/proxy均通過。
- Running Data Core公開28個dataset contracts、18個bounded operations。`tw.market_index.daily`實際storage已觀察到2026-08-25且canonical lineage成立；`tw.quote.snapshot`則如實回`lineage_incomplete`，沒有把legacy current row冒充canonical。
- Bounded official acquisition：TPEX 2026-08-25成功寫入raw receipt 96206並由Resolver選中，close 389.41、change 3.31、volume 701,017,083 shares、transaction count 809,034；TAIEX來源response只到2026-08-24，2026-08-25回`TARGET_TRADE_DATE_NOT_FOUND`且未寫假row。
- 收盤後2330 public quote acquisition以0 external calls回`SESSION_NOT_SUPPORTED_BY_RESOURCE`；這是正確policy rejection，不作F-07 live acceptance。
- Cold restart後TPEX raw receipt、transaction count、provider與row timestamp保持不變；GET為0 acquisition／0 persistence且Resolver `selected`。2330 latest indicator與technical API均回200。
- Visible browser驗證：dashboard可見TPEX 389.41、+3.31、+0.86%與2026-08-25資料日期；breadth missing/failure保留可見，console無warning/error。
- MCP `omi.ask`以`quote.official_close`、`cache_only`回`omi.decision.v4`，2026-08-25 close 389.41、quality ready、trust high、0 external fetch。另以錯誤scope請求`market.indices`時會truthful unsupported並阻擋，不silent fallback。
- 本輪stop-and-fix修正兩個production regression：latest technical calendar-range超出`max_rows`，以及legacy restart writer覆寫canonical index row/lineage。Targeted regression為118 passed、8 subtests；full validation `20260825-231250`為2282 passed、frontend lint/tsc/build與diff check全綠。
- 完整machine-readable evidence：`artifacts/cp8-production-adoption-20260825.json`。

## Adoption boundary

Production DB/runtime、API、visible UI、MCP、cold-read與rollback rehearsal已完成，H-06可標記passed。F-07仍只能在下一個台股active session完成；因此目前label是`TW_DATA_CORE_PRODUCTION_ADOPTED_F07_PENDING`，尚不得標記`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`。KGI、depth/auction、realtime lease與M5仍是explicitly deferred follow-up。

## Stop conditions

- Migration revision或DB backup/owner不明。
- Runtime listener/PID不是named OMI owner。
- New repository因schema/lineage fail closed後，bounded refresh仍無法建立canonical row。
- API/MCP隱藏missing/partial、出現consumer provider selection或GET產生provider IO。
- Visible UI仍顯示legacy completed evidence但Data Core status為missing。
