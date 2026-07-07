# OMI MCP Server

Minimal stdio MCP adapter for Open Market Intelligence.

By default it exposes one public OMI tool and forwards calls to the local
FastAPI backend:

```text
MCP client -> agents/omi_mcp_server/server.py -> http://127.0.0.1:8400/api/ai/...
```

Run it after the OMI backend is running:

```powershell
python agents/omi_mcp_server/server.py
```

Optional environment variable:

```powershell
$env:OMI_API_BASE_URL = "http://127.0.0.1:8400"
$env:OMI_API_TIMEOUT_SECONDS = "180"
$env:OMI_MCP_EXPOSE_INTERNAL_TOOLS = "false"
$env:OMI_MCP_AI_TRUST_TOKEN = ""
$env:OMI_MCP_TRUSTED_DEFAULT_EXTERNAL_FETCH = "true"
```

Public tool:

- `omi.ask`

`omi.ask` is read-only by default. It accepts a question plus optional v2
`target` object, then the OMI backend resolves `target.type=auto` into a Taiwan
stock/watchlist/index/futures, US stock, Japan stock/index, Korea stock/index,
crypto market/asset, market, or freshness context and chooses `data_only`,
`brief`, `full`, `analysis`, or `report` mode. `brief` returns a compact human
summary plus key numbers; `data_only` returns compact structured core data when
available; `full` returns the complete backend evidence pack. Analysis mode calls OpenAI for a
non-persistent OMI LLM answer,
so it requires a backend server-side trusted request and `allow_llm=true`.
Report mode calls OpenAI and persists an AI report, so it additionally requires
`allow_write=true`.
OMI can autonomously refresh external market data through configured external APIs
when trusted callers set `allow_external_fetch=true` with a bounded `tool_budget`.
The MCP client does not call market APIs directly; it sends the request to OMI,
and the backend chooses from allowlisted market-data tools, enforces the budget,
executes the tools, updates the local evidence cache when allowed by refresh
policy, and returns `tool_plan` / `tool_runs` evidence.

`market_data_params` is forwarded unchanged to the backend reader. It is for
bounded reader selection such as:

- Shared payload controls: `include_intraday`, `payload_level`, `intraday_limit`.
- US stock: `provider`, `timeframe`, `bars`, `daily_limit`, `include_intraday`.
- Japan/Korea stock or index: `provider`, `timeframe`, `bars`.
- Crypto market/asset: `provider`, `providers`, `symbol`, `symbols`,
  `instrument_type`, `interval`, `limit`.

`payload_level` supports `summary`, `compact`, `standard`, and `full`.
Use `summary` for voice/desktop-pet answers, `compact` for default ChatGPT/MCP
answers, and `standard` or `full` only when the user explicitly needs a richer
chart/evidence view. `intraday_limit` is bounded by the backend and should stay
small for ChatGPT Web or voice use.

The MCP schema also accepts `include_intraday`, `payload_level`, and
`intraday_limit` as top-level tool arguments. The server merges those values into
`market_data_params` before calling OMI so ChatGPT clients do not need to build a
nested JSON object for simple bounded requests.

OMI responses can include `result.data.slots` or
`result.data.compact.slots`. Consumers should use slot `status` values such as
`ready`, `partial`, `missing`, `not_requested`, `planned`, and `not_applicable`
to decide whether to render, speak, or request a richer follow-up payload.
Slots point to existing payload fields with `payload_ref`; they are not separate
large data copies.

Unsupported or missing data remains visible through `missing`, `warnings`,
`freshness`, and `evidence_passport`; callers must not treat fallback daily data
as live quote data.

For US/ADR targets, trusted MCP calls default to a small external-fetch budget
when the request clearly looks like a US stock question, such as `target.type=us_stock`,
`target.id=MU`, `$MU`, `NASDAQ:MU`, or a question containing US market hints.
Set `allow_external_fetch=false` per request or
`OMI_MCP_TRUSTED_DEFAULT_EXTERNAL_FETCH=false` for the MCP process to disable
that default.

For Taiwan stock targets, `refresh_policy.mode=stale_first` with
`before_answer=true` makes OMI check local freshness first and, when trusted
external fetch is allowed, run the backend `tw.refresh_stock_evidence` tool
before rebuilding the evidence pack.
`caller_profile` is only a label and is not trusted for permissions.

Japan, Korea, and Crypto ask paths are local-cache evidence paths today. They
support compact `data_only`, `brief`, and `full` evidence packs, but
OpenAI-backed `analysis` / persisted `report` mode still downgrade to
`data_only` until dedicated decision/report paths are implemented.

OpenAI-backed analysis/report mode requires the OMI backend process to have
`OPENAI_API_KEY`, `OPENAI_LLM_API_KEY`, or `OMI_OPENAI_ENV_FILE` configured.
`OMI_OPENAI_ENV_FILE` may point at another local env file that contains
`OPENAI_API_KEY` or `OPENAI_LLM_API_KEY`. The MCP server does not read, store,
or forward API keys.

Set `OMI_MCP_EXPOSE_INTERNAL_TOOLS=true` only for debugging or a trusted local
agent that needs direct tool selection. If the backend disables local trust or
runs across a non-loopback boundary, configure `OMI_AI_TRUST_TOKEN` on the
backend and pass the same value to the MCP process as `OMI_MCP_AI_TRUST_TOKEN`.
Direct memory writes, brief saves, and LLM analysis/report generation are also
protected by that backend trust policy; regular external callers should go through
`omi.ask`.

Internal tools:

- `omi.read_market_overview`
- `omi.read_stock_context`
- `omi.read_us_stock_context`
- `omi.read_jp_stock_context`
- `omi.read_jp_index_context`
- `omi.read_kr_stock_context`
- `omi.read_kr_index_context`
- `omi.read_crypto_market_context`
- `omi.read_crypto_asset_context`
- `omi.read_watchlist_context`
- `omi.read_data_freshness`
- `omi.generate_stock_brief`
- `omi.generate_us_stock_brief`
- `omi.generate_jp_stock_brief`
- `omi.generate_jp_index_brief`
- `omi.generate_kr_stock_brief`
- `omi.generate_kr_index_brief`
- `omi.generate_crypto_market_brief`
- `omi.generate_crypto_asset_brief`
- `omi.generate_watchlist_brief`
- `omi.generate_stock_llm_report`
- `omi.generate_us_stock_llm_report`
- `omi.generate_watchlist_llm_report`
- `omi.read_memories`
- `omi.write_memory`
- `omi.update_memory`
- `omi.archive_memory`
- `omi.read_reports`
- `omi.read_report`
- `omi.save_stock_brief`
- `omi.save_us_stock_brief`
- `omi.save_watchlist_brief`

Memory write tools only change AI research memory rows. They do not modify market,
watchlist, or source data. Archive incorrect memories instead of deleting them so
the history remains auditable.
