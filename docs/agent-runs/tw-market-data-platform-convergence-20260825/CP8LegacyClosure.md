# CP8 Migrated Capability Legacy Closure

## Scope rule

Legacy removal只針對本次已正式遷移的capability：completed daily OHLCV read、public last-trade quote、completed official index/breadth projection、AI Taiwan quote dependency與backend-authoritative technical series。尚未onboard的current-session index/intraday bars、depth、auction與KGI仍保留原capability邊界，不可為了追求搜尋結果為零而誤刪。

## Removed paths

### Public last-trade / intraday masquerading

`market/intraday.py`已移除：

- direct `TWSE_MIS_STOCK_INFO_URL`與`_fetch_mis_message`。
- `_fetch_mis_snapshot`假intraday series。
- `_apply_mis_volume_adjustment`及其把snapshot price/volume注入NStock/Yahoo minute bars的行為。
- `twse_mis_snapshot_z` current-price component與直接`resolve_twse_mis_actual_trade`依賴。

正式路徑只允許`read_taiwan_public_last_trade_quote`取得Data Core cache result，quote作獨立component，不製造或修改bar。

### Daily OHLCV GET mutation

`GET /api/market/ohlc/{stock_id}`保留`ensure_history`參數作outward compatibility，但參數已降為ignored diagnostic：無論true/false都不import或呼叫legacy TWSE/TPEx backfill。若true，payload會回`status=not_attempted`與cache-only說明；mutation只能走explicit bounded refresh operation/job。

### Completed official dashboard fallback

`/indices/summary`的completed official index/breadth fields只由Data Core resolved projection擁有。若0067 schema、canonical row或lineage尚未成立，component回`data_core_missing`，official close/breadth fail closed；不再復活legacy completed row。Current-session observation仍是不同capability，保留獨立trade date與既有compatibility owner，等待後續provider onboarding。

### AI and technical ownership

- Taiwan AI quote context不import quote-depth provider orchestration；provider/strict-provider legacy inputs不影響production acquisition。
- Indicator API與AI technical evidence只讀resolved official daily bars。
- Frontend backend-authoritative series不回算為AI/MCP evidence；local math只保留presentation compatibility scope。

## Machine-enforced inventory

`test_tw_data_core_boundaries.py`與`test_intraday_trend.py`會阻擋以下回歸：direct MIS URL/fetch、snapshot-to-bar helpers、OHLC GET backfill import/call、dashboard `legacy_compatibility` fallback、AI quote-depth dependency、technical raw-table bypass與frontend authority metadata bypass。

## Not removed by design

- `indices.py`的current-session index/MIS breadth/Yahoo compatibility acquisition：它不是completed official index/breadth，尚未完成獨立capability onboarding。
- `quote_depth.py`、auction/depth與KGI runtime：使用者明確deferred。
- Full-market EOD lifecycle呼叫的Registry-owned bounded bulk refresh port：它是explicit mutation operation，不是consumer fallback；後續可替換transaction implementation，但不得讓GET或consumer直接呼叫。
- Technical canonical/legacy rollback flag：保留作capability-level rollback rehearsal，不能在完成rollback gate前刪除。
