# 台股 Backend Outward Contract 收斂進度

## 狀態

- 目前階段：`planning_awaiting_user_approval`
- Source acceptance：`not_started`
- Runtime acceptance：`not_started`
- Live acceptance：`baseline_failed`
- Product acceptance：`not_ready`
- 最後更新：`2026-08-28 15:26 Asia/Taipei`

## 已完成

- 讀取root／Backend／Market Data／Agents適用規則與current product／architecture truth。
- 讀取並保留既有TW Data Core umbrella task與`tw-final-eod-technical-cleanup-20260827`的成果及live acceptance歷史。
- 完成P0–P3 source owner、dependency direction、quality contract、scheduler ownership、MCP parity與existing test gap的read-only audit。
- 直接呼叫running OMI backend、`omi.decision.v4`、Dashboard、index、intraday與tool catalog，完成bounded live baseline。
- 以read-only DB query確認3711 2026-08-28 row的raw receipt與ingest time；未修改或刪除production row。
- 建立本active exec plan的Prompt、Plan與Progress；尚未修改production source、schema、runtime或automation。

## 驗證證據

### Runtime baseline

- Backend：`http://127.0.0.1:8400`
- `/api/system/health`：`ok`
- `/api/system/readyz`：`ready`
- Runtime project root：`C:\project\Open Market Intelligence`
- Runtime仍回報`canonical_market_data_mode=off`；不能以本輪source inspection宣稱canonical-on product acceptance。

### Completed daily temporal evidence

- 2026-08-28 14:59，3711 direct daily read：
  - `latest_data_date=2026-08-28`
  - `expected_data_date=2026-08-27`
  - `freshness_status=future`
  - `data_quality=ok`
  - `volume_semantics=finalized_traded_shares`
- Explicit `to_date=2026-08-28`時，`expected_data_date`被caller路徑推為2026-08-28並標current。
- DB：`raw_result_id=113461`、source=`TWSE OpenAPI Daily Trading`、raw fetched=`2026-08-28 14:01:28 Asia/Taipei`。
- 2026-08-28 15:15:27，沒有新receipt或row update，API仍自動變為`expected=2026-08-28 / current / ok / finalized_traded_shares`。
- 結論：backfill release guard已修正，但completed read boundary與freshness仍未release-qualify existing storage row。

### Quality與technical evidence

- 3711 `omi.decision.v4` daily evidence：latest D、expected D-1，但daily quality `current / ready / decision_usable=true`、continuity `not_applicable`、data freshness current/usable。
- 2330 request 20、return 1：daily quality仍`current / ready / decision_usable=true`。
- 2330 technical：`selected_score=7.0`、`波段偏多`、selected confidence low；quality仍ready／decision usable。
- Daily payload live顯示`bars`為int count、實際array為`points`。

### Market與current-session evidence

- Sectors：observed date 2026-08-28、sample 1/1973；current projection已誠實標partial/sample-only/decision unusable。
- Dashboard TAIEX/TPEX 13:30 resolved index：stale、provisional、decision unusable、official close not available yet。
- AI同一13:30 index evidence：ready、complete、decision usable，nested finalization provisional、official close pending。
- Intraday screening top 20中4筆stale仍decision usable；多筆delayed亦decision usable。
- 3711 intraday 1m：point count 0、persisted miss、`CACHE_ONLY_NO_ELIGIBLE_CANDIDATE`。
- TAIEX／TPEX intraday：HTTP 502；exact traceback：

```text
backend/app/market/tw_current_market_platform.py:108
NameError: name 'TAIWAN_TZ' is not defined
```

### Planner與applicability evidence

- Data-only explicit daily selection仍可顯示`decision_required=true`。
- Explicit technical request使用standard reader profile，帶回cross-market、breadth與其他unselected supplemental health。
- 0050 revenue最終not applicable，但仍建立payload並回傳不相關health noise。
- `/api/ai/tools`有68 capabilities並包含`quote.session_close`。

### Existing targeted regression

```text
10 passed in 4.19s
```

- Covered existing official daily defaults/refresh guard、daily freshness、technical factor model、intraday state、MCP parity與position-context promotion。
- 這些tests全綠但沒有future-of-release storage fixture，不能證明P0已受保護。
- `ruff`未安裝於repo `.venv`；本輪為docs-only planning，未以此作必要validation。

## 已做決策

- 本任務不重開TW Data Core Foundation；只修現有owner與outward convergence。
- Release qualification必須同時包含calendar cutoff與qualified ingest evidence，不能只做`min(to_date, expected_date)`。
- Existing `CapabilityStatus`已具六個正交axes；計畫只補resolver input、planner outcome與consumer convergence。
- P1-01現有sample coverage gate保留，僅修raw latest date ownership。
- Intraday scheduler預設採bounded Tier A，不採full-market常駐抓取。
- P2-01目前視為Backend/source parity已通過；installed MCP adoption留到runtime gate。
- P3-01的summary-only是hard budget fallback，不做「任何budget都強制problem row」的錯誤修復。

## 已知風險

- Worktree有大量既有TW、US與architecture未提交變更；implementation必須先建立exact file/hunk scope並與既有修改共存。
- Existing daily row lineage可指出fetched time，但是否足以長期重建release qualification仍需M0/M1 cold-read contract test。
- Scheduler會引入正常provider IO與DB write；source實作、production enable與runtime adoption必須分gate。
- Installed MCP host可能與repo MCP schema不同；目前只確認Backend tool catalog與repo parity。
- Live release acceptance依賴交易日時窗與正式provider publication，不能用fixture或15:15後舊row自動升格代替。
- Existing inaccessiblepytest temp directories可能影響full collection；targeted tests需使用`-p no:cacheprovider`並隔離非功能性權限問題。

## 下一步

- 等待使用者審核並確認`Prompt.md`中的四個預設決策。
- 核准後先執行M0：補failing fixtures、consumer inventory與release qualification storage decision；在M0 evidence完成前不修改production behavior。
- Runtime restart、production migration、scheduler enable、external refresh、commit、push與release仍留在各自review checkpoint。
