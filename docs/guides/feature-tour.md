# Feature tour

Open Market Intelligence is organized around a simple research sequence: understand the market, inspect a company, form a conditional view, and keep the limits of the evidence visible.

The screenshots below come from a local OMI runtime. Prices and market conditions are historical examples.

## Dashboard and Radar

The dashboard combines broad market participation, research groups, watchlists, and Radar candidates. It is intended to answer “where should I look?” before you open a detailed chart.

![OMI dashboard and Radar](../assets/readme/omi-v4-dashboard-radar-2k.png)

Use it to:

- compare index direction with market breadth;
- move between saved groups and active symbols;
- find candidates without treating a ranking as a trade instruction;
- notice missing, stale, or incomplete market context.

## Stock research workspace

The stock workspace keeps price action and company context together.

![OMI stock research workspace](../assets/readme/omi-v4-stock-research-2k.png)

Depending on the market and available sources, the workspace can include:

- price history and technical state;
- fundamentals, revenue, earnings, and events;
- ownership or institutional context;
- related indices, futures, currencies, or cross-market signals;
- visible source and freshness information.

Coverage differs by market. An unavailable field stays unavailable rather than being presented as zero.

## Professional chart

The chart workspace supports multiple timeframes, indicators, volume profile, signals, and drawing tools.

![OMI professional chart](../assets/readme/omi-v4-professional-chart-2k.png)

It is most useful for recording a testable view:

- what price or market condition supports the idea;
- what would invalidate it;
- where liquidity, volatility, or event risk changes the plan;
- which data is current enough to rely on.

## Decision Dock

The Decision Dock works with the symbol already open on screen.

![OMI Decision Dock](../assets/readme/omi-v4-decision-dock-2k.png)

Its role is to organize the available evidence into a conditional research answer. A useful answer includes supporting evidence, counter-evidence, entry conditions, invalidation, risks, and data limits. It is not an order-entry surface.

## Taiwan market context

Taiwan is OMI’s reference market. The product connects market breadth, sectors, listed and OTC context, futures, and stock-level research.

![Taiwan futures context](../assets/readme/omi-taiwan-futures-context.png)

This helps distinguish a broad move from an index move driven by a small number of large companies.

OMI can also present bounded stock-level evidence such as broker-branch activity when the source is available.

![Taiwan Radar and broker-branch panel](../assets/readme/omi-stock-data-branch-panel.png)

## US market context

US stocks have a first-class research workflow with major indices, sessions, watchlists, active symbols, and company research.

![US market context](../assets/readme/omi-us-market-context.png)

US and Taiwan coverage are not assumed to be identical. Market-specific fields and provider limits remain explicit.

## Additional market workbenches

Other markets provide context where OMI has usable data. For example, the crypto workbench can compare real-time observations across its available providers.

![Crypto real-time workbench](../assets/readme/omi-crypto-realtime-workbench.png)

These surfaces are contextual. Availability, history, freshness, and provider authority vary by market.

## Source disclosure and update status

OMI treats source state as part of the research result.

![Source and responsibility disclosure](../assets/readme/omi-settings-source-disclosure.png)

The interface distinguishes provider responsibility, dataset status, fallback, stale data, partial coverage, and missing results. A green application process does not imply that every market dataset is current.

## Where to go next

- [Start OMI on Windows](getting-started.md)
- [Set up local development](development.md)
- [Configure optional KGI SuperPy access](kgi-superpy.md)
- Return to the [main README](../../README.md)
