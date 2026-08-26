# Risk Register

## 評級

- 機率：低 / 中 / 高。
- 影響：中 / 高 / 極高。
- 狀態：OPEN / MITIGATED / ACCEPTED / CLOSED。

| ID | 風險 | 機率 | 影響 | 預防／緩解 | Stop trigger | 狀態 |
|---|---|---|---|---|---|---|
| R-01 | dirty worktree覆蓋US、scheduler或既有intraday修改 | 高 | 極高 | 每包開始前exact status/diff；只改task-owned hunks | touched hunk ownership不明 | OPEN |
| R-02 | central quality一次接入造成既有capability大面積失效 | 中 | 極高 | pure evaluator先行；additive flag；bars/quote regression再擴張 | existing platform-owned path大量rejected | MITIGATED |
| R-03 | `minimum_authority`用錯total order | 中 | 高 | 明確policy mapping與contract tests；不依Enum順序 | broker/exchange/vendor eligibility與capability語意衝突 | MITIGATED |
| R-04 | lineage requirement破壞legacy cache read | 高 | 高 | default向後相容；production requirement明確opt-in；legacy fail-closed只在decision-ready path | cache-only outward contract無預期變成missing | MITIGATED |
| R-05 | depth/auction schema導致不可逆資料或migration風險 | 中 | 極高 | typed schema review；disposable DB upgrade/downgrade；不碰user DB rehearsal | downgrade失敗或orphan raw IDs | MITIGATED |
| R-06 | KGI provider被shared core硬編或偽裝成MIS | 中 | 極高 | descriptors在market layer；source guard；provider/source identity tests | shared file出現provider-specific import/name | MITIGATED |
| R-07 | trial/auction leak成actual trade | 中 | 極高 | 沿用canonical converter；session-aware regression；live gate | cumulative=0或trial phase仍產actual trade | OPEN |
| R-08 | quote/account health混燈 | 中 | 高 | capability-specific health；quote lease不依賴account API | account 503令quote候選失效 | OPEN |
| R-09 | viewer lease洩漏或symbol switch殘留 | 中 | 極高 | owner token、serial lifecycle、bounds、cleanup evidence | active handles或舊symbol subscription非0 | OPEN |
| R-10 | GET仍觸發IO、commit或subscription | 高 | 極高 | explicit command先建立；call-counter tests；frontend hook guard | 任一GET external call > 0 | MITIGATED |
| R-11 | NStock資料以Yahoo provider identity持久化 | 高 | 高 | provider-specific receipt/identity；migration compatibility test | source/provider mismatch | MITIGATED |
| R-12 | current index/breadth覆蓋completed official truth | 中 | 極高 | 分capability與finalization；official regression suite | provisional row成completed selected evidence | MITIGATED |
| R-13 | unknown / missing breadth被轉0 | 中 | 極高 | nullable counts、coverage equation、partial gate | missing dimension序列化成0且無證據 | MITIGATED |
| R-14 | frontend重建provider/freshness/quality truth | 中 | 高 | backend projection唯一；source guards與cross-surface snapshot | hook/component出現fallback/quality decision table | MITIGATED |
| R-15 | runtime仍載入舊source或錯port/interpreter | 高 | 高 | launcher-selected identity、direct/proxy分層probe | source fingerprint/runtime identity不一致 | OPEN |
| R-16 | live gate錯過或provider entitlement不足 | 中 | 高 | source與runtime先完成；等待下一正式session；truthful pending | 無合法session或login/quote capability不可用 | ACCEPTED |
| R-17 | 外部provider call浪費quota或造成無界subscription | 中 | 極高 | request bounds、planner routes、explicit approval、bounded lease | attempt/subscription超plan | OPEN |
| R-18 | high-volume persistence造成DB contention | 中 | 高 | bounded transaction、batch size、idempotency、content hash、contention tests | lock timeout/duplicate rows/long transaction | OPEN |
| R-19 | P2 scope膨脹成全市場Big Bang | 高 | 高 | 本輪只做reader/lineage seam與migration order | 開始搬7+13 datasets而無獨立acceptance | MITIGATED |
| R-20 | source tests通過被誤報為runtime/live完成 | 高 | 極高 | G0-G6狀態分離；Progress與artifact明列pending | 未有runtime/session artifact卻標closed | MITIGATED |
| R-21 | legacy breadth unknown/missing double-count令canonical candidate全數被拒 | 高 | 極高 | producer輸出正規partition；adapter legacy subtraction；production-shape regression | partition sum不等於universe | MITIGATED |
| R-22 | realtime telemetry被frontend/consumer誤認canonical research truth | 中 | 極高 | required presentation-only flags、AI/MCP guards、visible UI label | 任一decision path讀stream或usability為true | MITIGATED |
| R-23 | `market.intraday.bars`與`intraday.bars`使planner/registry/AI尋址漂移 | 高 | 高 | canonical ID單一化與cross-registry equality test | production出現兩個未管理ID | MITIGATED |
| R-24 | catalog把registered StockMaster universe宣稱exchange official universe | 高 | 高 | `full_market_registered_stock_universe`、universe definition與`official_full_market=false` regression | registered scope被標成exchange official | MITIGATED |
| R-25 | physical cleanup擴成indices/quote package Big Bang或破壞replay | 中 | 極高 | current-only provider extraction、capture re-export、逐包tests | completed official或replay outward contract改變 | MITIGATED |

## Risk review cadence

- 每開始一個wave重讀所有OPEN風險。
- 發生stop trigger時，先在`Progress.md`記錄evidence，再修正或重新切scope。
- 只有驗證證據成立才把風險改為MITIGATED/CLOSED；不能因程式碼已寫完而關閉。
