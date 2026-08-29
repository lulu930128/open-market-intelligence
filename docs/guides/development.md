# Development guide

This page contains the engineering details intentionally kept out of the public README.

## Local setup

Complete the source installation in the [getting-started guide](getting-started.md) first.

## Run the backend directly

From the repository root:

~~~powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8400 --app-dir backend
~~~

## Run the frontend directly

~~~powershell
Set-Location frontend
npm run dev
~~~

Preferred local endpoints are:

- dashboard: <code>http://127.0.0.1:3000</code>
- API documentation: <code>http://127.0.0.1:8400/docs</code>
- health: <code>http://127.0.0.1:8400/api/system/health</code>
- readiness: <code>http://127.0.0.1:8400/api/system/readyz</code>
- AI tool schema: <code>http://127.0.0.1:8400/api/ai/tools</code>

When using the production launcher, inspect its selected ports instead of assuming these preferred values.

## Safe validation

The repository includes a validation wrapper with timeouts, centralized logs, and sensitive-port warnings:

~~~powershell
.\scripts\run-safe-validation.ps1 -Profile quick
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
.\scripts\run-safe-validation.ps1 -Profile full
~~~

Choose the smallest profile that covers the changed area. The default profiles do not start a long-running runtime, run Playwright, or clear a port owner. Add <code>-IncludeE2E</code> only when actual browser evidence is required.

## README screenshots

With the regular OMI runtime running, capture the maintained 2560 × 1440 README images with:

~~~powershell
node scripts\capture-readme-screenshots.mjs
~~~

The script navigates the local interface and opens the dock. It does not submit an OMI question, call an LLM, or write market data.

## Repository map

~~~text
Open Market Intelligence/
├─ backend/
│  ├─ app/
│  │  ├─ ai/                 decision core, evidence, tools, and contract
│  │  ├─ market_data/        provider-neutral canonical data and resolution
│  │  ├─ market/             Taiwan market capabilities
│  │  ├─ us_market/          US market and research capabilities
│  │  ├─ jp_market/          Japan market context
│  │  ├─ kr_market/          Korea market context
│  │  ├─ crypto_market/      crypto providers and runtime
│  │  ├─ resource_market/    commodity reference data
│  │  ├─ jobs/               scheduled and bounded background work
│  │  └─ routers/            FastAPI outward routes
│  ├─ alembic/               database migrations
│  └─ tests/                 backend regression tests
├─ frontend/
│  ├─ src/app/               Next.js App Router
│  ├─ src/components/        dashboard, details, charts, and OMI dock
│  ├─ src/lib/               API and projection helpers
│  └─ e2e/                   Playwright smoke tests
├─ agents/omi_mcp_server/    thin repository MCP adapter
├─ docs/
│  ├─ architecture/          durable architecture contracts
│  ├─ product/               product direction and quality bar
│  ├─ guides/                user and developer guides
│  └─ assets/readme/         maintained screenshots
├─ scripts/                  launcher, validation, and maintenance tools
├─ Installer/                Windows package builder
├─ data/                     local runtime data, ignored by Git
└─ reports/                  generated reports, ignored by Git
~~~

## Engineering references

These documents describe current implementation and contribution contracts. They are not required for ordinary use.

- [Architecture index](../architecture/index.md)
- [Current implementation state](../architecture/CurrentImplementationState.md)
- [Backend architecture](../architecture/BackendArchitecture.md)
- [OMI decision contract](../architecture/OmiDecisionContract.md)
- [External interfaces](../ExternalInterfaces.md)
- [Product vision](../product/ProductVision.md)
- [Operating model](../product/OperatingModel.md)
- [Quality bar](../product/QualityBar.md)
- [Roadmap](../product/Roadmap.md)
- [Contributing](../../CONTRIBUTING.md)

## Local-only engineering material

Codex configuration, agent instructions, individual agent runs, and one-off execution plans are local workflow material. They are ignored by Git and should not be added to releases or public documentation.
