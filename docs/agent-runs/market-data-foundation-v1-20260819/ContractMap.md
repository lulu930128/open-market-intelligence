# OMI Market Data Foundation v1 Contract Map

## Baseline

- Captured at：2026-08-19（Asia/Taipei）
- Branch：`codex/tw-etf-provider-normalization`
- HEAD：`aa65e65`
- Worktree：49 筆 modified/untracked entries before Foundation source work。
- `backend/app/market_data/`：不存在。
- Runtime / DB / provider：本 milestone 未探測、未寫入、未 refresh、未 restart。

## Target ownership and baseline

| Boundary | Current owner | Baseline state | SHA-256 before Foundation |
| --- | --- | --- | --- |
| Settings / rollout | `backend/app/config.py` | modified, existing KGI settings | `4FCB6E32FB3BDF917404A1C2861D2ACE7041B07EF8D83D11867691A62811630` |
| TW quote/depth service | `backend/app/market/quote_depth.py` | modified, existing KGI integration | `CE795367E82288F925D3EFCEB11C739BD79169C8537740C6AEAEB03130188665` |
| MIS observation semantics | `backend/app/market/twse_mis_observation.py` | clean | `22844801D3664F0047B40AB67549D7388B6512E191D20B204A4AB36835AA0E75` |
| KGI quote manager | `backend/app/market/providers/kgi_superpy.py` | untracked integration base | `76485E558DC07D95682F2902E2B2D34D05287915D9CF0E81D9C889E37E04202F` |
| KGI bridge | `backend/app/market/providers/kgi_superpy_bridge.py` | untracked integration base | `478047069BC117604274FA2B907EA99B7CD63C72AE19A85FED8D04429833EA54` |
| AI capability registry | `backend/app/ai/capability_contract.py` | clean | `7897EB3C8134B2960F24E7FC8614EFCC2A3B149F97AE4D3808191C47957E876C` |
| AI resolution registry | `backend/app/ai/capability_resolution_registry.py` | clean | `DD552723F0D56E64F520B807CE6101A9E65588A639A76CE2A6785CE62A037310` |
| AI realtime contract | `backend/app/ai/realtime_contract.py` | clean | `89EFBD1F37DBA15F560BE3295762424CEE45CB45CBB3CFE46E6CFA8D0EFAED15` |
| US AI context | `backend/app/ai/market_context/us_context.py` | clean | `FC1A720C63EF456D83CED0FD3D1B1D817033469AF99F5B81E8F5B9D04535047F` |
| Scheduler | `backend/app/jobs/scheduler.py` | clean | `F1A91C6405F719D9818A97F9003AC84FC702E0193C9BE22D827BBE1ED09C1778` |
| TW daily repair | `backend/app/jobs/taiwan_daily_metric_repair.py` | clean | `BB6E98DC221C6957E7552536E3A3178FD8DF15F0D4887DC53B6CE37865BB3A6B` |

Foundation 必須保留 modified/untracked baseline，不 reset、restore、clean、commit 或搬移既有 hunks。

## Current KGI / MIS quote chain

```text
Frontend selected symbol
  -> POST /api/market/realtime-quote-leases
  -> KGI SuperPy manager acquire / subscribe
  -> KGI callback in isolated Python 3.12 bridge
  -> get_kgi_superpy_quote_snapshot()
  -> quote_depth._kgi_quote_to_mis_message()
  -> quote_depth._snapshot_values_from_message()
  -> TaiwanStockQuoteSnapshot upsert
  -> quote-depth API / AI market context
```

No active viewer lease：

```text
KGI snapshot = not_subscribed
  -> quote_depth fetches TWSE MIS
  -> MIS parser / local snapshot fallback
```

AI Taiwan stock context calls `get_taiwan_stock_quote_depth(refresh=True)` but does not acquire a KGI lease. Production Research Lease is therefore an acquisition/lifecycle gap and remains 02 scope。

## Current public AI contract

- Public business contract：`omi.decision.v4`。
- Current realtime policy values：`cache_only`、`prefer_live`、`require_live`。
- `completed_session` is not currently accepted by `backend/app/ai/capability_contract.py` and will remain internal in Foundation 01。
- Capability projection is path-based through `CapabilitySpec.paths` and `project_selected_data()`。
- `technical.structure` currently advertises `ALL_INSTRUMENT_SCOPES`, but only Taiwan stock/index/futures market-context builders emit the registered `technical` / `analysis` paths。
- HTTP/SSE/MCP/Frontend consumer shapes are out of scope for Foundation outward changes；truthful capability-scope correction still requires public catalog/snapshot regression。

## Current lifecycle gaps retained for later work

- `scheduler.market_daily_refresh` currently owns institutional-trade refresh rather than TW daily OHLCV。
- `taiwan_daily_metric_repair.REPAIR_SPECS` covers institutional and margin data, not market daily price。
- Foundation Dataset Registry will model these owners/operations truthfully but will not activate repair or rewrite scheduler behavior。

## Foundation seams

```text
backend/app/market_data/
  contracts.py      pure versioned canonical types
  policies.py       pure request/selection policies
  resolution.py     pure candidate selection
  registry.py       pure dataset lifecycle specs
  comparison.py     bounded legacy/canonical comparison

backend/app/market/providers/
  kgi_canonical.py
  twse_mis_canonical.py

backend/app/ai/
  capability_projection_registry.py
```

- Shared package cannot import market-specific services, provider SDK, SQLAlchemy, FastAPI or AI。
- Adapters receive explicit instrument/session/fetch context and do no IO/persistence。
- Existing quote-depth service remains transaction owner and legacy outward owner。
- Shadow/compare must reuse the same already-acquired provider payload, never issue an additional fetch/subscription。
