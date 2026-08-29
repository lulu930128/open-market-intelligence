# Open Market Intelligence

<p align="center">
  <strong>English</strong> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.ja-JP.md">日本語</a>
</p>

<p align="center">
  <img alt="Version 4.4.0" src="https://img.shields.io/badge/version-4.4.0-2563eb">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows-0f766e">
  <img alt="Apache License 2.0" src="https://img.shields.io/badge/license-Apache--2.0-334155">
</p>

Open Market Intelligence (OMI) is a local-first research workspace for people who want to understand a stock before deciding what to do. It brings prices, charts, market breadth, watchlists, technical context, company data, and source status into one place.

Taiwan is OMI’s reference market. US stocks have a dedicated research workflow, while Japan, Korea, Hong Kong, futures, commodities, and crypto provide additional market context where data is available.

OMI is a research tool. It does not place trades automatically or promise investment returns.

![OMI dashboard with market breadth, groups, watchlists, and Radar](docs/assets/readme/omi-v4-dashboard-radar-2k.png)

<sub>Actual OMI local runtime. Prices and market conditions shown in screenshots are historical examples.</sub>

## What OMI helps you do

| Need | What you get |
| --- | --- |
| Understand the market first | Market breadth, groups, indices, futures, and cross-market context |
| Research one company | Price history, technical state, fundamentals, ownership, events, and risk context |
| Turn observations into a plan | Evidence-backed scenarios, entry conditions, invalidation, and risk notes |
| Keep a focused workspace | Watchlists, research groups, Radar candidates, and saved local state |
| Know when data is incomplete | Source, freshness, fallback, missing, and partial states remain visible |

## A closer look

### Research a stock without jumping between tools

The stock workspace keeps the chart, market structure, company context, and research notes together, so you can inspect the evidence behind an idea instead of relying on a single score.

![OMI stock research workspace](docs/assets/readme/omi-v4-stock-research-2k.png)

### Read the chart and record the conditions that matter

Professional charts include multiple timeframes, volume profile, indicators, signals, and drawing tools. They are meant to support a hypothesis—not replace one.

![OMI professional chart with indicators and volume profile](docs/assets/readme/omi-v4-professional-chart-2k.png)

### Ask OMI about the stock already on screen

The Decision Dock works with the current symbol and presents evidence, scenarios, invalidation conditions, risks, and data limits in the same workspace.

![OMI Decision Dock beside a stock chart](docs/assets/readme/omi-v4-decision-dock-2k.png)

### See Taiwan market structure beyond the headline index

OMI combines breadth, sectors, futures, and stock-level context so a strong index does not hide weak participation underneath.

![Taiwan futures context in OMI](docs/assets/readme/omi-taiwan-futures-context.png)

### Research US stocks with the wider market in view

The US workspace keeps major indices, active symbols, watchlists, sessions, and company research connected.

![US market context and watchlist in OMI](docs/assets/readme/omi-us-market-context.png)

### Check where the data came from

Source disclosure is part of the product. OMI shows provider roles and limitations instead of presenting every value as equally current or authoritative.

![OMI source and responsibility disclosure](docs/assets/readme/omi-settings-source-disclosure.png)

### Use other markets as context

Additional workbenches, including crypto, are available as contextual research surfaces. Coverage and quality depend on the market and provider.

![OMI crypto real-time workbench](docs/assets/readme/omi-crypto-realtime-workbench.png)

For a screen-by-screen overview, see the [feature tour](docs/guides/feature-tour.md).

## Data status is part of the answer

Market data can be delayed, partial, unavailable, or supplied by a fallback source. OMI keeps those conditions visible:

- missing data is not silently converted to zero;
- stale and partial results stay labeled;
- different kinds of source and data problems are not reduced to one generic “healthy” light;
- research output includes evidence, conditions, risks, and invalidation—not only a conclusion.

## Start on Windows

### Use the packaged release

The Windows package includes its own Python and Node.js runtimes.

1. Download the Windows zip from [Releases](https://github.com/lulu930128/open-market-intelligence/releases).
2. Extract the entire folder. Do not run it from the zip preview.
3. Run <code>Start-OMI-Launcher.cmd</code>.
4. Use the tray menu to open the dashboard.

Your writable data and logs are stored under <code>%LOCALAPPDATA%\Open Market Intelligence</code>.

### Run from a source checkout

If the repository has already been set up:

~~~powershell
cd "C:\project\Open Market Intelligence"
.\Start-OMI-Launcher.cmd
~~~

For first-time source installation, requirements, dynamic ports, and troubleshooting, follow the [getting-started guide](docs/guides/getting-started.md).

## Guides and project information

- [Getting started](docs/guides/getting-started.md) — packaged release and source installation
- [Feature tour](docs/guides/feature-tour.md) — what each main workspace is for
- [Development guide](docs/guides/development.md) — local development, validation, and screenshots
- [Optional KGI SuperPy setup](docs/guides/kgi-superpy.md) — live quotes and read-only holdings sync
- [Support](SUPPORT.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md) · [License](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Current limits

- OMI is local-first and currently optimized for Windows.
- Market coverage is not identical across Taiwan, the US, Japan, Korea, Hong Kong, crypto, futures, and commodities.
- Some capabilities require optional provider credentials, account permissions, or market-specific services.
- Source availability and provider restrictions can affect freshness and completeness.
- The Decision Dock supports research; it does not remove the need for independent judgment.

## Disclaimer

OMI is for research and information only. It is not investment advice, a performance guarantee, or an autonomous trading system. Verify important information with primary sources and assess suitability and risk independently.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and third-party terms.
